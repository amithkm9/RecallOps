"""Cross-surface review regressions: privacy, closure and stock identity."""

from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models import (
    AgentRun,
    Decision,
    DecisionEvidence,
    EvaluationRun,
    Incident,
    InventoryLot,
    Recall,
    RecallVersion,
    Store,
    utcnow,
)
from app.repositories.records import record
from app.schemas.investigator import ResolveIn, ValidateClaimIn
from app.services.evaluation import create_case
from app.services.events import process_event
from app.services.investigator_evaluation import BENCHMARK
from app.services.investigator_evidence import (
    accepted_claims,
    import_delivery,
    list_delivery_candidates,
    resolve_case,
    validate_claim,
)
from app.services.replay import start_replay


def test_public_latest_comparison_never_returns_imported_metadata(db, monkeypatch):
    now = utcnow()
    public = EvaluationRun(
        sample_size=1,
        benchmark=BENCHMARK + ". Built-in synthetic fixture",
        results=[],
        cases=[{"name": "Public fixture"}],
        created_at=now,
    )
    private = EvaluationRun(
        sample_size=1,
        benchmark=BENCHMARK + ". Imported labels from CONFIDENTIAL-CUSTOMER",
        results=[],
        cases=[{"name": "CONFIDENTIAL-CASE", "labeler": "Private person"}],
        created_at=now + timedelta(seconds=1),
    )
    db.add_all([public, private])
    db.commit()
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "operator_token", "privacy-admin-test")
    with TestClient(app) as client:
        result = client.get("/api/investigator/evaluation/latest")
        assert result.status_code == 200
        assert result.json()["id"] == public.id
        assert "CONFIDENTIAL" not in result.text
        authorized = client.get(
            "/api/investigator/evaluation/latest",
            headers={"Authorization": "Bearer privacy-admin-test"},
        )
        assert authorized.status_code == 200 and authorized.json()["id"] == private.id
    # Avoid leaving an artificial future timestamp as latest in other tests.
    private.created_at = now - timedelta(days=1)
    db.commit()


def test_stale_live_recall_blocks_close_but_archived_replay_remains_pinned(
    db, monkeypatch
):
    incident, stock, event = create_case(
        db,
        {
            "name": "Stale closure review",
            "scope": "3760099533007$A1$non concerné$$",
            "gtin": "3760099533007",
            "lot": "B2",
            "product_name": "Synthetic stock",
            "recall_name": "Synthetic recall",
            "expected": "unaffected",
        },
        commit=False,
    )
    event.payload = {**event.payload, "disable_llm": True}
    db.commit()
    run_id = process_event(event.id)
    db.expire_all()
    run = db.get(AgentRun, run_id)
    recall = db.get(Recall, incident.recall_id)
    old_version = db.get(RecallVersion, run.recall_version_id)
    values = {
        key: value
        for key, value in record(old_version).items()
        if key
        not in {
            "id",
            "created_at",
            "content_hash",
            "official_version",
            "published_at",
            "source_updated_at",
        }
    }
    values["published_at"] = old_version.published_at
    values["source_updated_at"] = old_version.source_updated_at
    newer = RecallVersion(**values, content_hash=uuid4().hex * 2, official_version="2")
    db.add(newer)
    db.flush()
    recall.current_version_id = newer.id
    store = db.get(Store, incident.store_id)
    store.mode = "live"
    ids = list(
        db.scalars(
            select(DecisionEvidence.evidence_id)
            .join(Decision)
            .where(Decision.run_id == run_id)
        )
    )
    db.commit()
    monkeypatch.setattr(settings, "operator_token", "review-admin-test")
    headers = {"Authorization": "Bearer review-admin-test"}
    body = {
        "action": "close",
        "expected_run_id": run_id,
        "evidence_ids": ids,
        "reason": "Reviewed the current decision and retained source evidence.",
    }
    with TestClient(app) as client:
        rejected = client.post(
            f"/api/incidents/{incident.id}/review", headers=headers, json=body
        )
        assert rejected.status_code == 409 and "recall changed" in rejected.text
        store.mode = "replay"
        db.commit()
        closed = client.post(
            f"/api/incidents/{incident.id}/review", headers=headers, json=body
        )
        assert closed.status_code == 200, closed.text
        db.expire_all()
        assert db.get(Incident, incident.id).review_status == "closed"
        response = client.post(
            f"/api/incidents/{incident.id}/investigator/resolve",
            headers=headers,
            json={
                "expected_run_id": run_id,
                "evidence_ids": ids,
                "reason": body["reason"],
            },
        )
        assert response.status_code == 409 and "Reopen" in response.text


def test_rejection_of_accepted_claim_cannot_be_attributed_to_other_stock(db):
    replay = start_replay(db)
    incident = db.get(Incident, replay.incident_id)
    stocks = list(
        db.scalars(
            select(InventoryLot).where(InventoryLot.store_id == incident.store_id)
        )
    )
    stock = next(s for s in stocks if s.sku == "SALMON-UNVERIFIED")
    other = next(s for s in stocks if s.id != stock.id)
    content = f"delivery_id,sku,gtin,lot,quantity,expires_on,reference\nD1,{stock.sku},{stock.gtin},24326020,24,2024-12-20,SHIPMENT-D1\n".encode()
    import_delivery(db, incident, "delivery.csv", content, "test_operator")
    claim = list_delivery_candidates(db, incident.id, stock.id)[0]
    validate_claim(
        db,
        incident,
        claim["id"],
        ValidateClaimIn(
            inventory_lot_id=stock.id,
            accept=True,
            reason="Checked the source against this physical stock group.",
        ),
        "test_operator",
    )
    with pytest.raises(HTTPException) as exc:
        validate_claim(
            db,
            incident,
            claim["id"],
            ValidateClaimIn(
                inventory_lot_id=other.id,
                accept=False,
                reason="This statement belongs to a different stock group.",
            ),
            "test_operator",
        )
    assert exc.value.status_code == 422
    assert accepted_claims(db, incident.id, stock.id)[0]["id"] == claim["id"]
