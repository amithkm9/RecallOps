"""A replay with real historical recall facts and fictional delivery evidence."""

import json
from datetime import date
from uuid import uuid4
from sqlalchemy import select, text
from app.core.config import settings
from app.models import Incident, InventoryLot, Recall, RecallVersion, Store
from app.repositories.records import enqueue
from app.services.ingestion import ingest_records
from app.services.investigator_evidence import import_delivery
from app.services.events import process_event


def start_investigator_demo(db):
    db.execute(text("SELECT pg_advisory_xact_lock(4242003)"))
    ingest_records(
        db,
        json.loads((settings.fixture_dir / "official_snapshot.json").read_text()),
        "archived_fixture",
    )
    for previous in db.scalars(
        select(Store).where(Store.mode == "replay", Store.active.is_(True))
    ):
        previous.active = False
    store = Store(name="Investigator demonstration · Fictional", mode="replay")
    unresolved_store = Store(
        name="Missing delivery demonstration · Fictional", mode="replay", active=False
    )
    db.add_all([store, unresolved_store])
    db.flush()
    recall = db.scalar(select(Recall).where(Recall.source_id == "17010"))
    version = db.scalar(
        select(RecallVersion)
        .where(
            RecallVersion.recall_id == recall.id, RecallVersion.official_version == "1"
        )
        .order_by(RecallVersion.created_at)
        .limit(1)
    )
    incident = Incident(store_id=store.id, recall_id=recall.id)
    unresolved = Incident(store_id=unresolved_store.id, recall_id=recall.id)
    db.add_all([incident, unresolved])
    db.flush()
    for owner, sku, lot, quantity in [
        (store, "SALMON-KNOWN", "SAFE-DEMO-LOT", 18),
        (store, "SALMON-DELIVERY", None, 24),
        (unresolved_store, "SALMON-NO-RECORD", None, 7),
    ]:
        db.add(
            InventoryLot(
                store_id=owner.id,
                sku=sku,
                product_name=version.product_name,
                gtin="3760099533007",
                lot=lot,
                lot_key=(lot or "").lower(),
                quantity=quantity,
                supplier="Fictional Atlantic Foods",
                expires_on=date(2024, 12, 20),
            )
        )
    db.flush()
    # Seed explicitly synthetic source evidence; do not pre-accept its association.
    content = (
        "delivery_id,sku,gtin,lot,quantity,expires_on,reference\n"
        "D-104,SALMON-DELIVERY,3760099533007,24326020,24,2024-12-20,Fictional receiving reference D-104\n"
        "D-105,SALMON-DELIVERY,3760099533007,OTHER-DELIVERY,24,2024-12-20,Fictional different shipment D-105\n"
    ).encode()
    imported = import_delivery(
        db,
        incident,
        "fictional-deliveries.csv",
        content,
        "replay_simulator",
        event_payload={"disable_llm": True, "recall_version_id": version.id},
    )
    # Fixture demo must not incur hidden provider usage. It uses real retrieval
    # and verification with labelled deterministic planning.
    from app.models import Event

    event = db.get(Event, imported["event_id"])
    second = enqueue(
        db,
        f"investigator-demo:{unresolved.id}",
        "investigator_demo_started",
        unresolved.id,
        unresolved_store.id,
        {
            "disable_llm": True,
            "recall_version_id": version.id,
            "synthetic_inventory": True,
        },
    )
    db.commit()
    process_event(event.id)
    process_event(second.id)
    return {
        "incident_id": incident.id,
        "unresolved_incident_id": unresolved.id,
        "store_id": store.id,
        "message": "Historical official recall with fictional stock and deliveries. Confirm D-104 only after reviewing the demonstration source; D-105 is a different shipment. The second case has no delivery evidence and remains unresolved.",
    }
