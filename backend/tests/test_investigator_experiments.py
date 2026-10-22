from sqlalchemy import func, select
import pytest
from fastapi import HTTPException

from app.models import AgentRun, AuditLog, Decision, Event, Evidence, InventoryHold
from app.services.evaluation import create_case
from app.services.events import process_event
from app.services.investigator_evaluation import seed_claims, run_comparison
from app.services.investigator_experiments import simulate, simulation_options


def confirmed_case(db):
    incident, stock, event = create_case(
        db,
        {
            "name": "Frozen evidence experiment",
            "scope": "3760099533007$A1$non concerné$$",
            "gtin": "3760099533007",
            "lot": None,
            "product_name": "Synthetic salmon",
            "recall_name": "Synthetic salmon",
            "expected": "affected",
        },
        commit=False,
    )
    seed_claims(db, incident, stock, [{"lot": "A1", "accepted": True}])
    event.payload = {
        **event.payload,
        "disable_llm": True,
        "investigation_strategy": "adaptive",
    }
    db.commit()
    run_id = process_event(event.id)
    db.expire_all()
    return incident, stock, run_id


def counts(db, incident_id):
    return [
        db.scalar(select(func.count(model.id)).where(model.incident_id == incident_id))
        for model in (Decision, Evidence, InventoryHold, Event, AuditLog)
    ]


def test_simulation_recomputes_without_operational_side_effects(db):
    incident, stock, run_id = confirmed_case(db)
    options = simulation_options(db, incident, run_id)
    before = counts(db, incident.id)
    full = simulate(db, incident, run_id, options["default_evidence_ids"])
    assert full["decisions"][0]["verdict"] == "affected"
    assert full["changed_count"] == 0
    claim = next(e for e in options["evidence"] if e["kind"] == "delivery_claim")
    without_claim = simulate(
        db,
        incident,
        run_id,
        [i for i in options["default_evidence_ids"] if i != claim["id"]],
    )
    assert without_claim["decisions"][0]["verdict"] == "review"
    assert without_claim["changed_count"] == 1
    assert counts(db, incident.id) == before
    assert (
        db.scalar(
            select(InventoryHold.status).where(InventoryHold.incident_id == incident.id)
        )
        == "active"
    )
    assert without_claim["read_only"] is True


def test_simulation_requires_validation_dependency_and_rejects_future_evidence(db):
    incident, stock, run_id = confirmed_case(db)
    options = simulation_options(db, incident, run_id)
    validation = next(e for e in options["evidence"] if e["kind"] == "claim_validation")
    result = simulate(
        db,
        incident,
        run_id,
        [i for i in options["default_evidence_ids"] if i != validation["id"]],
    )
    assert result["decisions"][0]["verdict"] == "review"
    from app.repositories.records import add_evidence

    future = add_evidence(
        db,
        incident.id,
        "supplier",
        "Later evidence",
        {"lot": "B2"},
        inventory_lot_id=stock.id,
        synthetic=True,
    )
    db.commit()
    with pytest.raises(HTTPException) as exc:
        simulate(db, incident, run_id, [*options["default_evidence_ids"], future.id])
    assert exc.value.status_code == 422
    # Older run remains reproducible after later evidence is added.
    assert (
        simulate(db, incident, run_id, options["default_evidence_ids"])["decisions"][0][
            "verdict"
        ]
        == "affected"
    )


def test_comparison_reports_human_inputs_and_honest_memory_ablation(db):
    result = run_comparison(db, include_model=False, include_memory=True)
    by_name = {r["method"]: r for r in result.results}
    assert result.sample_size == 12
    assert len(by_name) == 4
    assert all(r["model_calls"] == 0 for r in result.results)
    assert by_name["Adaptive investigator"]["setup_confirmations"] > 0
    assert by_name["Adaptive investigator"]["accuracy"] == 1
    assert by_name["Fixed retrieval"]["accuracy"] == 1
    assert by_name["Existing workflow"]["accuracy"] < 1
    assert (
        by_name["Adaptive without memory"]["accuracy"]
        == by_name["Adaptive investigator"]["accuracy"]
    )
    provenance = result.cases[-1]
    assert provenance["held_out"] is False
    assert provenance["independent_review_verified"] is False
    unresolved = next(
        c for c in result.cases if c["name"] == "Two unconfirmed shipments"
    )
    assert set(unresolved["predictions"].values()) == {"review"}


def test_comparison_lock_is_released_and_concurrent_work_returns_conflict(db):
    from app.core.database import engine
    from sqlalchemy import text
    from app.schemas.investigator_benchmark import InvestigationDataset

    dataset = InvestigationDataset.model_validate(
        {
            "source": "Synthetic regression",
            "labeler": "Development test",
            "cases": [
                {
                    "name": "Known affected",
                    "lot": "A1",
                    "expected": "affected",
                    "split": "development",
                }
            ],
        }
    ).model_dump(mode="json", exclude_none=True)
    for _ in range(2):
        result = run_comparison(db, include_memory=False, dataset=dataset)
        assert result.sample_size == 1
    with engine.connect() as owner:
        owner.execute(text("SELECT pg_advisory_lock(4242098)"))
        try:
            with pytest.raises(HTTPException) as exc:
                run_comparison(db, include_memory=False, dataset=dataset)
            assert exc.value.status_code == 409
        finally:
            owner.execute(text("SELECT pg_advisory_unlock(4242098)"))
