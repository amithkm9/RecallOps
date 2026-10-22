from uuid import uuid4

import pytest
from app.core.config import settings
from app.main import app
from app.models import (
    AgentRun,
    Decision,
    Event,
    Evidence,
    Incident,
    InventoryHold,
    InventoryLot,
    Store,
)
from app.services.events import process_event
from app.services.replay import next_replay, start_replay
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def held_case(db):
    replay = start_replay(db)
    replay = next_replay(db, replay.id, 0)
    stock = db.scalar(
        select(InventoryLot).where(
            InventoryLot.store_id == replay.store_id,
            InventoryLot.sku == "SALMON-UNVERIFIED",
        )
    )
    return replay, stock


def statement(stock):
    return {
        "inventory_lot_id": stock.id,
        "supplier": "Test supplier",
        "lot": "DISPUTED-LOT",
        "reference": "Delivery-note-123",
        "notes": "Supplier says this stock belongs to a different lot.",
        "source_url": "https://example.com/delivery/123",
    }


def test_supplier_intake_reopens_live_incident_and_preserves_hold(db, client):
    replay, stock = held_case(db)
    # Exercise live-mode behavior using a clearly labeled test store in the isolated test DB.
    store = db.get(Store, replay.store_id)
    store.mode = "live"
    store.name = "Synthetic live-intake test"
    db.commit()
    path = f"/api/incidents/{replay.incident_id}/supplier-evidence"
    first = client.post(path, json=statement(stock))
    assert first.status_code == 202, first.text
    second = client.post(path, json=statement(stock))
    assert second.json()["evidence_id"] == first.json()["evidence_id"]
    assert second.json()["event_id"] == first.json()["event_id"]
    evidence = db.get(Evidence, first.json()["evidence_id"])
    assert (
        evidence.synthetic is False
        and evidence.source_url == "https://example.com/delivery/123"
    )
    assert evidence.payload["reference"] == "Delivery-note-123"
    run_id = process_event(first.json()["event_id"])
    db.expire_all()
    run = db.get(AgentRun, run_id)
    decisions = db.scalars(select(Decision).where(Decision.run_id == run.id)).all()
    assert any(
        d.verdict == "conflict" and d.action == "preserve_hold_and_review"
        for d in decisions
    )
    holds = db.scalars(
        select(InventoryHold).where(InventoryHold.incident_id == replay.incident_id)
    ).all()
    assert len(holds) == 1 and holds[0].quantity == 24 and holds[0].status == "active"
    assert db.get(InventoryLot, stock.id).lot == "24326020"
    assert db.get(Incident, replay.incident_id).status == "conflict"
    assert (
        db.scalar(
            select(func.count(Event.id)).where(Event.id == first.json()["event_id"])
        )
        == 1
    )


def test_supplier_evidence_requires_access_and_rejects_wrong_lot(
    db, client, monkeypatch
):
    replay, stock = held_case(db)
    path = f"/api/incidents/{replay.incident_id}/supplier-evidence"
    monkeypatch.setattr(settings, "operator_token", "operator-test")
    assert client.post(path, json=statement(stock)).status_code == 401
    monkeypatch.setattr(settings, "public_demo", True)
    assert client.post(path, json=statement(stock)).status_code == 403
    headers = {"Authorization": "Bearer operator-test"}
    assert (
        client.post(
            path,
            headers=headers,
            json={**statement(stock), "inventory_lot_id": str(uuid4())},
        ).status_code
        == 404
    )
    assert (
        client.post(
            path,
            headers=headers,
            json={**statement(stock), "source_url": "javascript:alert(1)"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            path, headers=headers, json={**statement(stock), "notes": "   "}
        ).status_code
        == 422
    )


def test_connection_check_is_not_available_to_public_demo(client, monkeypatch):
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "operator_token", "operator-test")
    assert client.post("/api/settings/model-check").status_code == 403


def test_explicit_supplier_correction_keeps_old_evidence_and_hold(db, client):
    replay, stock = held_case(db)
    path = f"/api/incidents/{replay.incident_id}/supplier-evidence"
    original = client.post(path, json=statement(stock)).json()
    process_event(original["event_id"])
    correction = {
        **statement(stock),
        "lot": stock.lot,
        "reference": "Corrected-delivery-note",
        "supersedes_evidence_id": original["evidence_id"],
    }
    response = client.post(path, json=correction)
    assert response.status_code == 202, response.text
    run_id = process_event(response.json()["event_id"])
    db.expire_all()
    assert db.get(Evidence, original["evidence_id"]).payload["lot"] == "DISPUTED-LOT"
    decisions = db.scalars(select(Decision).where(Decision.run_id == run_id)).all()
    assert (
        next(d for d in decisions if d.inventory_lot_id == stock.id).verdict
        == "affected"
    )
    holds = db.scalars(
        select(InventoryHold).where(InventoryHold.incident_id == replay.incident_id)
    ).all()
    assert len(holds) == 1 and holds[0].status == "active"
