import json
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.models import (
    AgentRun,
    Incident,
    InventoryLot,
    Recall,
    RecallVersion,
    Replay,
    Store,
    utcnow,
)
from app.repositories.records import add_evidence, append_audit_event, enqueue
from app.services.events import process_event
from app.services.ingestion import ingest_records
from app.core.config import settings

LABELS = [
    "Initial lot verification",
    "Warehouse confirms 24 affected units",
    "Supplier contradicts warehouse lot",
]


def start_replay(db: Session) -> Replay:
    db.execute(text("SELECT pg_advisory_xact_lock(4242003)"))
    ingest_records(
        db,
        json.loads((settings.fixture_dir / "official_snapshot.json").read_text()),
        "archived_fixture",
    )
    for store in db.scalars(
        select(Store).where(Store.mode == "replay", Store.active.is_(True))
    ):
        store.active = False
    store = Store(name="Marché Saint-Martin · Fictional", mode="replay")
    db.add(store)
    db.flush()
    recall = db.scalar(select(Recall).where(Recall.source_id == "17010"))
    # Pin the original snapshot even if live ingestion has a newer version.
    version = db.scalar(
        select(RecallVersion)
        .where(
            RecallVersion.recall_id == recall.id, RecallVersion.official_version == "1"
        )
        .order_by(RecallVersion.created_at)
    )
    from datetime import date

    db.add_all(
        [
            InventoryLot(
                store_id=store.id,
                sku="SALMON-KNOWN",
                product_name=version.product_name,
                gtin="3760099533007",
                lot="SAFE-DEMO-LOT",
                lot_key="safe-demo-lot",
                quantity=18,
                supplier="Fictional Atlantic Foods",
                expires_on=date(2024, 12, 20),
            ),
            InventoryLot(
                store_id=store.id,
                sku="SALMON-UNVERIFIED",
                product_name=version.product_name,
                gtin="3760099533007",
                lot=None,
                lot_key="",
                quantity=24,
                supplier="Fictional Atlantic Foods",
                expires_on=date(2024, 12, 20),
            ),
        ]
    )
    incident = Incident(store_id=store.id, recall_id=recall.id)
    db.add(incident)
    db.flush()
    replay = Replay(store_id=store.id, incident_id=incident.id)
    db.add(replay)
    db.flush()
    event = enqueue(
        db,
        f"replay:{replay.id}:0",
        "recorded_recall_detected",
        incident.id,
        store.id,
        {
            "recall_version_id": version.id,
            "synthetic_inventory": True,
            "replay_id": replay.id,
            "step": 0,
        },
    )
    replay.events = [
        {
            "step": 0,
            "label": LABELS[0],
            "event_id": event.id,
            "run_id": None,
            "created_at": utcnow().isoformat(),
        }
    ]
    db.commit()
    run_id = process_event(event.id)
    db.refresh(replay)
    replay.events = [{**e, "run_id": run_id} for e in replay.events]
    db.commit()
    return replay


def next_replay(db: Session, replay_id: str, expected_step: int) -> Replay:
    replay = db.scalar(select(Replay).where(Replay.id == replay_id).with_for_update())
    if not replay:
        raise ValueError("Replay not found.")
    # A repeated delivery of the same next request must never inject a second event.
    if replay.step != expected_step or replay.step >= 2:
        db.commit()
        return replay
    prior_event = replay.events[-1]
    prior_run = db.scalar(
        select(AgentRun).where(AgentRun.event_id == prior_event["event_id"])
    )
    if not prior_run or prior_run.status != "completed":
        raise ValueError(
            "Wait for the previous investigation to finish before injecting evidence."
        )
    stock = db.scalar(
        select(InventoryLot).where(
            InventoryLot.store_id == replay.store_id,
            InventoryLot.sku == "SALMON-UNVERIFIED",
        )
    )
    step = replay.step + 1
    if step == 1:
        stock.lot = "24326020"
        stock.lot_key = "24326020"
        stock.updated_at = utcnow()
        payload = {
            "message": "Synthetic warehouse scan confirms 24 units of official recalled lot 24326020.",
            "inventory_lot_id": stock.id,
            "lot": stock.lot,
            "quantity": 24,
            "synthetic": True,
        }
        add_evidence(
            db,
            replay.incident_id,
            "warehouse_update",
            "Simulated warehouse stock confirmation",
            payload,
            inventory_lot_id=stock.id,
            synthetic=True,
        )
        kind = "warehouse_stock_updated"
    else:
        payload = {
            "message": "Synthetic supplier correction contradicts the warehouse scan.",
            "inventory_lot_id": stock.id,
            "lot": "SUPPLIER-DISPUTED-LOT",
            "quantity": 24,
            "synthetic": True,
        }
        add_evidence(
            db,
            replay.incident_id,
            "supplier",
            "Simulated supplier correction — conflicting lot",
            payload,
            inventory_lot_id=stock.id,
            synthetic=True,
        )
        kind = "supplier_evidence_changed"
    event = enqueue(
        db,
        f"replay:{replay.id}:{step}",
        kind,
        replay.incident_id,
        replay.store_id,
        {
            **payload,
            "recall_version_id": prior_run.recall_version_id,
            "replay_id": replay.id,
            "step": step,
        },
    )
    append_audit_event(
        db, kind, payload, replay.incident_id, replay.store_id, actor="replay_simulator"
    )
    replay.step = step
    replay.events = [
        *replay.events,
        {
            "step": step,
            "label": LABELS[step],
            "event_id": event.id,
            "run_id": None,
            "created_at": utcnow().isoformat(),
        },
    ]
    db.commit()
    run_id = process_event(event.id)
    db.refresh(replay)
    replay.events = [
        {**e, "run_id": run_id} if e["step"] == step else e for e in replay.events
    ]
    db.commit()
    return replay
