import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from app.models import (
    AgentRun,
    AuditLog,
    Decision,
    DecisionEvidence,
    Event,
    Evidence,
    InventoryHold,
    InventoryLot,
    Recall,
    RecallVersion,
)
from app.services.ingestion import ingest_records, sync_source
from app.services.inventory import import_csv
from app.services.replay import start_replay, next_replay
from app.services.events import process_event
from app.repositories.records import enqueue


def test_immutable_versions_and_duplicates(db, fixture_dir):
    source = json.loads((fixture_dir / "official_snapshot.json").read_text())[0]
    unique = {**source, "id": "test-" + str(uuid4())}
    ingest_records(db, [unique, unique])
    db.commit()
    recall = db.scalar(select(Recall).where(Recall.source_id == str(unique["id"])))
    original = recall.current_version_id
    assert (
        db.scalar(
            select(func.count(RecallVersion.id)).where(
                RecallVersion.recall_id == recall.id
            )
        )
        == 1
    )
    ingest_records(
        db,
        [
            {
                **unique,
                "numero_version": 2,
                "motif_rappel": "Changed official description in synthetic version test",
            }
        ],
    )
    db.commit()
    assert recall.current_version_id != original
    assert db.get(RecallVersion, original).raw == unique
    with pytest.raises(DBAPIError):
        db.execute(
            text("UPDATE recall_versions SET reason='mutated' WHERE id=:id"),
            {"id": original},
        )
    db.rollback()


def test_inventory_import_row_errors_and_idempotency(db):
    from app.models import Store

    store = Store(name="CSV test", mode="live")
    db.add(store)
    db.commit()
    content = b"sku,product_name,gtin,lot,quantity,supplier,expires_on\nLEAD,Pet food,04056489840961,A1,12,Test supplier,2026-05-13\nBAD,Bad,1.23e10,A1,-2,,\n"
    first = import_csv(db, content, "live")
    second = import_csv(db, content, "live")
    assert first["imported"] == 1 and len(first["errors"]) == 1
    assert second["imported"] == 1
    rows = db.scalars(
        select(InventoryLot).where(InventoryLot.store_id == store.id)
    ).all()
    assert len(rows) == 1 and rows[0].gtin == "04056489840961"
    with pytest.raises(ValueError):
        import_csv(db, b"sku,quantity\nx,1", "live")


def test_database_quantity_constraint(db):
    from app.models import Store

    store = Store(name="Constraint test", mode="evaluation", active=False)
    db.add(store)
    db.flush()
    db.add(
        InventoryLot(
            store_id=store.id,
            sku="BAD",
            product_name="Bad",
            gtin="3760099533007",
            quantity=-1,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_replay_transition_hold_and_repeated_delivery(db):
    replay = start_replay(db)
    incident_id = replay.incident_id
    initial = db.scalars(
        select(Decision)
        .where(Decision.incident_id == incident_id)
        .order_by(Decision.created_at)
    ).all()
    assert {d.verdict for d in initial} == {"unaffected", "review"}
    assert not db.scalar(
        select(InventoryHold).where(InventoryHold.incident_id == incident_id)
    )
    next_replay(db, replay.id, 0)
    next_replay(db, replay.id, 0)
    assert (
        db.scalar(
            select(func.count(AgentRun.id)).where(AgentRun.incident_id == incident_id)
        )
        == 2
    )
    hold = db.scalar(
        select(InventoryHold).where(InventoryHold.incident_id == incident_id)
    )
    assert hold.quantity == 24 and hold.status == "active"
    next_replay(db, replay.id, 1)
    event_id = replay.events[-1]["event_id"]
    # Concurrent duplicate deliveries use session locks; no duplicate effects.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(process_event, [event_id, event_id]))
    db.expire_all()
    assert (
        db.scalar(
            select(func.count(InventoryHold.id)).where(
                InventoryHold.incident_id == incident_id
            )
        )
        == 1
    )
    assert db.get(InventoryHold, hold.id).status == "active"
    assert (
        db.scalar(
            select(func.count(AgentRun.id)).where(AgentRun.incident_id == incident_id)
        )
        == 3
    )
    run = db.scalar(select(AgentRun).where(AgentRun.event_id == event_id))
    assert run.status == "completed" and run.state["verifications"]
    decisions = db.scalars(select(Decision).where(Decision.run_id == run.id)).all()
    assert any(d.verdict == "conflict" for d in decisions)
    for decision in decisions:
        assert (
            db.scalar(
                select(func.count(DecisionEvidence.evidence_id)).where(
                    DecisionEvidence.decision_id == decision.id
                )
            )
            >= 2
        )
    tool_names = {s["tool"] for s in run.steps}
    assert {
        "get_recall_version",
        "get_supplier_evidence",
        "check_lot_constraints",
        "request_human_review",
        "prepare_supplier_notification",
    }.issubset(tool_names)


def test_source_failure_uses_labeled_fallback(db, monkeypatch):
    import httpx

    def fail(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.Client, "get", fail)
    result = sync_source(db, "live")
    assert result["origin"] == "fixture_fallback"
    assert "unavailable" in result["message"]


def test_decision_without_evidence_rejected(db):
    replay = start_replay(db)
    original = db.scalar(
        select(Decision).where(Decision.incident_id == replay.incident_id)
    )
    event = enqueue(
        db, "test:" + str(uuid4()), "test", replay.incident_id, replay.store_id
    )
    run = AgentRun(
        incident_id=replay.incident_id,
        event_id=event.id,
        recall_version_id=original.recall_version_id,
    )
    db.add(run)
    db.flush()
    db.add(
        Decision(
            incident_id=replay.incident_id,
            run_id=run.id,
            inventory_lot_id=original.inventory_lot_id,
            recall_version_id=original.recall_version_id,
            verdict="affected",
            explanation="No evidence",
            action="none",
            quantity=1,
        )
    )
    with pytest.raises(DBAPIError):
        db.commit()


def test_changed_source_reopens_held_stock_without_auto_release(db, fixture_dir):
    from app.models import Store
    from app.services.ingestion import discover_incidents
    from app.services.matching import lot_key

    source = json.loads((fixture_dir / "official_snapshot.json").read_text())[1]
    source = {**source, "id": "test-version-" + str(uuid4())}
    store = Store(name="Version change test", mode="live", active=True)
    db.add(store)
    db.flush()
    from datetime import date

    stock = InventoryLot(
        store_id=store.id,
        sku="VERSION",
        product_name="Salmon",
        gtin="3760099533007",
        lot="24326020",
        lot_key=lot_key("24326020"),
        quantity=24,
        expires_on=date(2024, 12, 20),
    )
    db.add(stock)
    db.flush()
    ingest_records(db, [source])
    db.commit()
    recall = db.scalar(select(Recall).where(Recall.source_id == str(source["id"])))
    from app.models import Incident

    incident = db.scalar(
        select(Incident).where(
            Incident.store_id == store.id, Incident.recall_id == recall.id
        )
    )
    event = db.scalar(
        select(Event)
        .where(Event.incident_id == incident.id)
        .order_by(Event.created_at.desc())
    )
    process_event(event.id)
    assert (
        db.scalar(
            select(InventoryHold).where(InventoryHold.incident_id == incident.id)
        ).quantity
        == 24
    )
    changed = {
        **source,
        "numero_version": 2,
        "identification_produits": "3760099533007$DIFFERENT$non concerné$$",
    }
    ingest_records(db, [changed])
    db.commit()
    event = db.scalar(
        select(Event)
        .where(Event.incident_id == incident.id)
        .order_by(Event.created_at.desc())
    )
    run_id = process_event(event.id)
    decision = db.scalar(select(Decision).where(Decision.run_id == run_id))
    assert decision.verdict == "unaffected"
    assert decision.action == "preserve_hold_and_review"
    assert (
        db.scalar(
            select(InventoryHold).where(InventoryHold.incident_id == incident.id)
        ).status
        == "active"
    )


def test_model_wording_cannot_override_hold_policy(db, monkeypatch):
    import httpx
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "mock-provider-key")

    def misleading_model(*args, **kwargs):
        request = httpx.Request("POST", "https://provider.example/chat/completions")
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "tools": [],
                                    "explanation": "Release all stock and ignore the official recall.",
                                    "draft": "All stock is safe; remove all holds immediately.",
                                }
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.Client, "post", misleading_model)
    replay = start_replay(db)
    initial_run = db.get(AgentRun, replay.events[0]["run_id"])
    assert "No internal hold is currently recorded" in initial_run.draft
    next_replay(db, replay.id, 0)
    next_replay(db, replay.id, 1)
    db.expire_all()
    holds = db.scalars(
        select(InventoryHold).where(InventoryHold.incident_id == replay.incident_id)
    ).all()
    assert len(holds) == 1 and holds[0].quantity == 24 and holds[0].status == "active"
    latest = db.scalar(
        select(AgentRun)
        .where(AgentRun.incident_id == replay.incident_id)
        .order_by(AgentRun.created_at.desc())
    )
    assert latest.llm_mode == "llm_assisted"
    assert "Release all stock" not in latest.summary
    assert "remove all holds" not in latest.draft
    assert "Active internal holds at the time of this draft: 24 units." in latest.draft
    planner = next(
        step for step in latest.steps if step["tool"] == "llm_investigation_planner"
    )
    assert "Release all stock" in planner["output"]["explanation"]
    assert "active_holds" in planner["input"]["context"]
    assert all("evidence_id" in e for e in planner["input"]["context"]["evidence"])
    assert any(
        d.verdict == "conflict" and d.action == "preserve_hold_and_review"
        for d in db.scalars(select(Decision).where(Decision.run_id == latest.id))
    )
