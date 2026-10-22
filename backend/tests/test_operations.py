import json
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.models import (
    AccessCredential,
    Store,
    SourceRefresh,
    SourceRejection,
    Recall,
    RecallVersion,
    Event,
    AgentRun,
    InventoryHold,
    Incident,
)
from app.core.config import settings
from app.services.ingestion import ingest_records, sync_source
from app.services.replay import start_replay, next_replay
from app.services.events import process_event
from app.repositories.views import recall_view


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def credential(db, role, stores):
    token = str(uuid4())
    db.add(
        AccessCredential(
            name="Reviewer " + token[:8],
            token_hash=sha256(token.encode()).hexdigest(),
            role=role,
            store_ids=stores,
        )
    )
    db.commit()
    return {"Authorization": "Bearer " + token}


def test_clock_anomaly_separate_from_scope(db, fixture_dir):
    from app.models import utcnow

    raw = json.loads((fixture_dir / "official_snapshot.json").read_text())[0]
    raw = {
        **raw,
        "id": "future-" + str(uuid4()),
        "date_publication": (utcnow() + timedelta(hours=1)).isoformat(),
    }
    ingest_records(db, [raw])
    db.commit()
    recall = db.scalar(select(Recall).where(Recall.source_id == raw["id"]))
    view = recall_view(db, recall)
    assert (
        view["clock_warnings"]
        and view["raw"]["date_publication"] == raw["date_publication"]
    )
    assert not any("clock" in warning for warning in view["parse_warnings"])


def test_refresh_quarantines_bad_record_and_reports_truncation(
    db, monkeypatch, fixture_dir
):
    raw = json.loads((fixture_dir / "official_snapshot.json").read_text())[0]
    monkeypatch.setattr(settings, "source_max_records", 100)
    rows = [{**raw, "id": "refresh-" + str(uuid4())}, {"id": "invalid"}]

    def fetch(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", "https://test.invalid"),
            json={"results": rows, "total_count": 200},
        )

    monkeypatch.setattr(httpx.Client, "get", fetch)
    result = sync_source(db)
    refresh = db.get(SourceRefresh, result["refresh_id"])
    assert refresh.status == "partial" and refresh.details["truncated"]
    assert db.scalar(
        select(SourceRejection).where(SourceRejection.refresh_id == refresh.id)
    ).raw == {"id": "invalid"}


def test_scoped_credentials_and_ordered_inventory(db, client):
    a, b = Store(name="Intake A", mode="live"), Store(name="Private B", mode="live")
    db.add_all([a, b])
    db.commit()
    headers = credential(db, "integration", [a.id])
    body = {
        "external_id": "warehouse-1",
        "sequence": 2,
        "stock": {
            "sku": "SAFE",
            "product_name": "Synthetic connector test",
            "gtin": "00000000000000",
            "lot": "A",
            "quantity": 7,
        },
    }
    path = f"/api/stores/{a.id}/inventory-events"
    first = client.post(path, headers=headers, json=body)
    assert first.status_code == 202, first.text
    assert client.post(path, headers=headers, json=body).json()["duplicate"]
    assert (
        client.post(path, headers=headers, json={**body, "sequence": 1}).status_code
        == 409
    )
    assert (
        client.post(
            path,
            headers=headers,
            json={**body, "stock": {**body["stock"], "quantity": 8}},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/stores/{b.id}/inventory-events", headers=headers, json=body
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/recalls/sync", headers=headers, json={"source": "snapshot"}
        ).status_code
        == 403
    )
    assert {s["id"] for s in client.get("/api/stores", headers=headers).json()} == {
        a.id
    }
    viewer = credential(db, "viewer", [a.id])
    assert client.post(path, headers=viewer, json=body).status_code == 403
    assert all(
        i["store_id"] == a.id
        for i in client.get("/api/inventory?mode=live", headers=viewer).json()["items"]
    )


def test_failed_event_retry_after_hold_commit_keeps_one_hold(db, client, monkeypatch):
    replay = start_replay(db)
    from app.agents.tools import InvestigationTools

    original = InvestigationTools.prepare_supplier_notification

    def crash(*args):
        raise RuntimeError("Injected crash after action commit")

    monkeypatch.setattr(InvestigationTools, "prepare_supplier_notification", crash)
    with pytest.raises(RuntimeError):
        next_replay(db, replay.id, 0)
    db.expire_all()
    event = db.scalar(
        select(Event)
        .where(Event.incident_id == replay.incident_id, Event.status == "pending")
        .order_by(Event.created_at.desc())
    )
    for _ in range(2):
        with pytest.raises(RuntimeError):
            process_event(event.id)
    db.expire_all()
    assert db.get(Event, event.id).status == "failed"
    assert (
        db.scalar(
            select(func.count(InventoryHold.id)).where(
                InventoryHold.incident_id == replay.incident_id
            )
        )
        == 1
    )
    monkeypatch.setattr(InvestigationTools, "prepare_supplier_notification", original)
    headers = credential(db, "operator", [replay.store_id])
    r = client.post(
        f"/api/operations/events/{event.id}/retry",
        headers=headers,
        json={"reason": "Injected failure resolved; resume recorded case."},
    )
    assert r.status_code == 200, r.text
    run_id = process_event(event.id)
    db.expire_all()
    assert db.get(AgentRun, run_id).status == "completed"
    assert (
        db.scalar(
            select(func.count(InventoryHold.id)).where(
                InventoryHold.incident_id == replay.incident_id
            )
        )
        == 1
    )


def test_named_review_assignment_and_unsafe_closure_rejected(db, client):
    replay = start_replay(db)
    headers = credential(db, "operator", [replay.store_id])
    path = f"/api/incidents/{replay.incident_id}/review"
    assert (
        client.post(
            path,
            headers=headers,
            json={
                "action": "assign",
                "reason": "Taking responsibility for investigation.",
            },
        ).status_code
        == 200
    )
    db.expire_all()
    assert db.get(Incident, replay.incident_id).assigned_to.startswith("Reviewer ")
    detail = client.get(f"/api/incidents/{replay.incident_id}", headers=headers).json()
    r = client.post(
        path,
        headers=headers,
        json={
            "action": "close",
            "reason": "Trying to close an unresolved case.",
            "expected_run_id": detail["runs"][-1]["id"],
            "evidence_ids": [detail["evidence"][0]["id"]],
        },
    )
    assert r.status_code == 409
    other = credential(db, "operator", [])
    assert (
        client.get(f"/api/incidents/{replay.incident_id}", headers=other).status_code
        == 403
    )


def test_mutation_budget_and_origin(client, monkeypatch):
    monkeypatch.setattr(settings, "mutation_limit_per_minute", 1)
    # Unique invalid token isolates this budget from other tests; never authorizes a mutation.
    h = {"Authorization": "Bearer " + str(uuid4())}
    assert (
        client.post(
            "/api/recalls/sync", headers=h, json={"source": "snapshot"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/recalls/sync", headers=h, json={"source": "snapshot"}
        ).status_code
        == 429
    )
    assert (
        client.post(
            "/api/recalls/sync",
            headers={"Origin": "https://attacker.invalid"},
            json={"source": "snapshot"},
        ).status_code
        == 403
    )
    assert client.post("/api/recalls/sync", content=b"x" * 2_100_001).status_code == 413


def test_stale_official_event_is_superseded(db, fixture_dir):
    from app.repositories.records import enqueue
    from app.models import InventoryLot

    raw = json.loads((fixture_dir / "official_snapshot.json").read_text())[1]
    raw = {**raw, "id": "ordering-" + str(uuid4())}
    store = Store(name="Synthetic ordering test", mode="live")
    db.add(store)
    db.flush()
    db.add(
        InventoryLot(
            store_id=store.id,
            sku="ORDER",
            product_name="Synthetic",
            gtin="3760099533007",
            lot="24326020",
            quantity=2,
        )
    )
    ingest_records(db, [raw])
    db.commit()
    recall = db.scalar(select(Recall).where(Recall.source_id == raw["id"]))
    incident = db.scalar(
        select(Incident).where(
            Incident.store_id == store.id, Incident.recall_id == recall.id
        )
    )
    old = enqueue(
        db,
        "ordering:" + str(uuid4()),
        "old_delivery",
        incident.id,
        store.id,
        {"recall_version_id": recall.current_version_id},
    )
    db.commit()
    ingest_records(
        db,
        [
            {
                **raw,
                "numero_version": 2,
                "identification_produits": "3760099533007$OTHER$non concerné$$",
            }
        ],
    )
    db.commit()
    assert process_event(old.id) is None
    db.expire_all()
    assert db.get(Event, old.id).status == "superseded"
    assert not db.scalar(select(AgentRun).where(AgentRun.event_id == old.id))


def test_ordered_stock_updates_are_serialized_under_concurrency(db, client):
    from concurrent.futures import ThreadPoolExecutor

    store = Store(name="Synthetic concurrent intake", mode="live")
    db.add(store)
    db.commit()
    h = credential(db, "integration", [store.id])

    def submit(sequence):
        with TestClient(app) as c:
            return c.post(
                f"/api/stores/{store.id}/inventory-events",
                headers=h,
                json={
                    "external_id": "same-stock",
                    "sequence": sequence,
                    "stock": {
                        "sku": "ORDERED",
                        "product_name": "Synthetic",
                        "gtin": "00000000000000",
                        "lot": "A",
                        "quantity": sequence,
                    },
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [2, 3]))
    assert all(code in {202, 409} for code in results)
    from app.models import InventoryLot

    db.expire_all()
    assert (
        db.scalar(
            select(InventoryLot).where(InventoryLot.store_id == store.id)
        ).quantity
        == 3
    )


def test_safe_case_closure_and_new_event_reopens(db, client, fixture_dir):
    from app.repositories.records import enqueue

    replay = start_replay(db)
    from app.models import InventoryLot, Evidence, DecisionEvidence, Decision

    stock = db.scalar(
        select(InventoryLot).where(
            InventoryLot.store_id == replay.store_id, InventoryLot.lot.is_(None)
        )
    )
    stock.lot, stock.lot_key = "KNOWN-EXCLUDED", "known-excluded"
    event = enqueue(
        db,
        "closing:" + str(uuid4()),
        "warehouse_verified",
        replay.incident_id,
        replay.store_id,
    )
    db.commit()
    run_id = process_event(event.id)
    h = credential(db, "operator", [replay.store_id])
    evidence_id = db.scalar(
        select(DecisionEvidence.evidence_id)
        .join(Decision)
        .where(Decision.run_id == run_id)
    )
    result = client.post(
        f"/api/incidents/{replay.incident_id}/review",
        headers=h,
        json={
            "action": "close",
            "reason": "All stock identifiers verified against the official scope.",
            "expected_run_id": run_id,
            "evidence_ids": [evidence_id],
        },
    )
    assert result.status_code == 200, result.text
    db.expire_all()
    assert db.get(Incident, replay.incident_id).review_status == "closed"
    event = enqueue(
        db,
        "reopening:" + str(uuid4()),
        "new_supplier_document",
        replay.incident_id,
        replay.store_id,
    )
    db.commit()
    process_event(event.id)
    db.expire_all()
    assert db.get(Incident, replay.incident_id).review_status == "open"
