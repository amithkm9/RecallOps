"""Append operator-supplied evidence and queue a scoped, idempotent investigation."""

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    Event,
    Evidence,
    Incident,
    InventoryLot,
    Recall,
    RecallTarget,
    Store,
)
from app.repositories.records import add_evidence, append_audit_event, enqueue
from app.schemas.api import SupplierEvidenceIn
from app.services.matching import gtin_key


def submit_supplier_evidence(
    db: Session, incident: Incident, body: SupplierEvidenceIn, actor: str = "operator"
) -> dict:
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,2))"),
        {"key": incident.store_id},
    )
    # Serialize submissions for this case; repeated identical evidence produces one event.
    db.scalar(select(Incident).where(Incident.id == incident.id).with_for_update())
    stock = db.get(InventoryLot, body.inventory_lot_id)
    if not stock or stock.store_id != incident.store_id:
        raise HTTPException(
            404, "This inventory lot is not part of the incident's store."
        )
    recall = db.get(Recall, incident.recall_id)
    targets = db.scalars(
        select(RecallTarget).where(
            RecallTarget.recall_version_id == recall.current_version_id
        )
    ).all()
    # Previously affected inventory may still be relevant after a source revision.
    from app.models import Decision

    previously_assessed = db.scalar(
        select(Decision.id)
        .where(
            Decision.incident_id == incident.id, Decision.inventory_lot_id == stock.id
        )
        .limit(1)
    )
    if not previously_assessed and not any(
        gtin_key(t.gtin) == gtin_key(stock.gtin) for t in targets
    ):
        raise HTTPException(
            422, "Choose a lot associated with this recall investigation."
        )
    store = db.get(Store, incident.store_id)
    if body.supersedes_evidence_id:
        previous = db.get(Evidence, body.supersedes_evidence_id)
        if (
            not previous
            or previous.incident_id != incident.id
            or previous.inventory_lot_id != stock.id
            or previous.kind != "supplier"
            or previous.payload.get("supplier") != body.supplier
        ):
            raise HTTPException(
                422,
                "A correction must reference the same supplier's statement for this incident and inventory lot.",
            )
    source_url = str(body.source_url) if body.source_url else None
    payload = {
        "inventory_lot_id": stock.id,
        "supplier": body.supplier,
        "lot": body.lot,
        "reference": body.reference,
        "message": body.notes,
        "submitted_by": actor,
        "supersedes_evidence_id": body.supersedes_evidence_id,
        "synthetic": store.mode != "live",
    }
    evidence = add_evidence(
        db,
        incident.id,
        "supplier",
        f"Supplier statement · {body.supplier}",
        payload,
        inventory_lot_id=stock.id,
        source_url=source_url,
        synthetic=store.mode != "live",
    )
    key = f"supplier-evidence:{evidence.id}"
    existing = db.scalar(select(Event).where(Event.idempotency_key == key))
    event = enqueue(
        db,
        key,
        "supplier_evidence_changed",
        incident.id,
        store.id,
        {"evidence_id": evidence.id, "recall_version_id": recall.current_version_id},
    )
    if not existing:
        append_audit_event(
            db,
            "supplier_evidence_submitted",
            {
                "message": f"Supplier statement recorded from {body.supplier}; investigation queued.",
                "evidence_id": evidence.id,
                "inventory_lot_id": stock.id,
                "reference": body.reference,
            },
            incident.id,
            store.id,
            actor=actor,
        )
    db.commit()
    return {
        "evidence_id": evidence.id,
        "event_id": event.id,
        "event_status": event.status,
        "message": (
            "This statement was already recorded."
            if existing
            else "Evidence recorded. A new investigation is queued; existing holds remain in place."
        ),
    }
