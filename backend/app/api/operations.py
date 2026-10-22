"""Operator tooling for source health, recovery, scoped access and ordered stock intake."""

from hashlib import sha256
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import (
    authorize,
    require_admin,
    require_store,
    store_scope,
    actor_name,
)
from app.models import (
    SourceRefresh,
    SourceRejection,
    Event,
    AgentRun,
    AccessCredential,
    Store,
    InventoryReceipt,
    InventoryLot,
    InventoryHold,
    utcnow,
)
from app.repositories.records import record, append_audit_event, digest
from app.schemas.api import Entity, MessageOut
from app.schemas.api import EvaluationOut
from app.schemas.benchmark import LabeledBenchmark
from app.services.inventory import InventoryRow
from app.services.ingestion import discover_incidents
from app.services.matching import lot_key

router = APIRouter()


class OperationsHealth(BaseModel):
    status: str
    worker_enabled: bool
    worker_heartbeat: str | None
    failed_events: int
    pending_events: int
    oldest_pending_seconds: float | None
    alerts: list[str]


@router.get("/operations/health", response_model=OperationsHealth)
def operations_health(
    db: Session = Depends(get_db), authorization: str | None = Header(None)
):
    require_admin(authorization)
    from app.core.config import settings
    from app.models import SourceState

    failed = db.scalar(select(func.count(Event.id)).where(Event.status == "failed"))
    pending = db.scalar(
        select(func.count(Event.id)).where(Event.status.in_(["pending", "processing"]))
    )
    oldest = db.scalar(
        select(func.min(Event.created_at)).where(
            Event.status.in_(["pending", "processing"])
        )
    )
    age = (utcnow() - oldest).total_seconds() if oldest else None
    heartbeat = db.get(SourceState, "worker")
    alerts = []
    if failed:
        alerts.append(f"{failed} failed events need operator attention.")
    if age is not None and age > 120:
        alerts.append("The oldest pending event is over two minutes old.")
    if not settings.worker_enabled:
        alerts.append("Background worker is disabled.")
    elif (
        not heartbeat
        or not heartbeat.last_attempt
        or (utcnow() - heartbeat.last_attempt).total_seconds() > 90
    ):
        alerts.append("No recent background-worker heartbeat.")
    return {
        "status": "degraded" if alerts else "ok",
        "worker_enabled": settings.worker_enabled,
        "worker_heartbeat": (
            heartbeat.last_attempt.isoformat()
            if heartbeat and heartbeat.last_attempt
            else None
        ),
        "failed_events": failed,
        "pending_events": pending,
        "oldest_pending_seconds": age,
        "alerts": alerts,
    }


@router.post("/evaluation/labeled", response_model=EvaluationOut)
def labeled_evaluation(
    body: LabeledBenchmark,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    require_admin(authorization)
    from app.services.evaluation import run_evaluation

    return record(
        run_evaluation(
            db,
            [c.model_dump(mode="json", exclude_none=True) for c in body.cases],
            body.model_dump(exclude={"cases"}),
        )
    )


class DocumentIn(BaseModel):
    field: Literal[
        "lien_vers_affichette_pdf",
        "lien_vers_la_liste_des_produits",
        "lien_vers_la_liste_des_distributeurs",
    ]


class DocumentOut(BaseModel):
    evidence_id: str
    event_id: str
    text_status: str
    scope_verified: bool


@router.post("/incidents/{incident_id}/documents", response_model=DocumentOut)
def document(
    incident_id: str,
    body: DocumentIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    from app.api.routes import require_incident
    from app.services.documents import fetch_document
    from app.core.config import settings

    if settings.public_demo:
        authorize(authorization=authorization, strict=True)
    incident = require_incident(db, incident_id, authorization)
    return fetch_document(db, incident, body.field)


@router.get("/incidents/{incident_id}/documents/{evidence_id}")
def document_download(
    incident_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    import base64
    from app.api.routes import require_incident
    from app.models import Evidence

    require_incident(db, incident_id, authorization)
    evidence = db.get(Evidence, evidence_id)
    if (
        not evidence
        or evidence.incident_id != incident_id
        or evidence.kind != "official_document"
    ):
        raise HTTPException(404, "Document not found in this incident.")
    return Response(
        base64.b64decode(evidence.payload["content_base64"]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="official-{evidence.id}.pdf"'
        },
    )


@router.get("/operations/refreshes", response_model=list[Entity])
def refreshes(
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
    limit: int = Query(20, ge=1, le=100),
):
    require_admin(authorization)
    return [
        record(r)
        for r in db.scalars(
            select(SourceRefresh).order_by(SourceRefresh.created_at.desc()).limit(limit)
        )
    ]


@router.get(
    "/operations/refreshes/{refresh_id}/rejections", response_model=list[Entity]
)
def rejections(
    refresh_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    require_admin(authorization)
    return [
        record(r)
        for r in db.scalars(
            select(SourceRejection)
            .where(SourceRejection.refresh_id == refresh_id)
            .limit(100)
        )
    ]


@router.get("/operations/events", response_model=list[Entity])
def events(db: Session = Depends(get_db), authorization: str | None = Header(None)):
    authorize(authorization=authorization)
    if store_scope(authorization) is None:
        require_admin(authorization)
    query = select(Event).where(Event.status.in_(["pending", "processing", "failed"]))
    scope = store_scope(authorization)
    if scope is not None:
        query = query.where(Event.store_id.in_(scope))
    return [record(r) for r in db.scalars(query.order_by(Event.created_at).limit(100))]


class RetryIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


@router.post("/operations/events/{event_id}/retry", response_model=MessageOut)
def retry(
    event_id: str,
    body: RetryIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    authorize(authorization=authorization, strict=True)
    event = db.scalar(select(Event).where(Event.id == event_id).with_for_update())
    if not event:
        raise HTTPException(404, "Event not found.")
    if event.store_id:
        require_store(event.store_id, authorization)
    if event.status != "failed":
        raise HTTPException(409, "Only failed events can be retried manually.")
    previous = event.attempts
    event.status, event.attempts, event.error = "pending", 0, None
    event.available_at, event.locked_at = utcnow(), None
    append_audit_event(
        db,
        "operator_retry",
        {"event_id": event.id, "previous_attempts": previous, "message": body.reason},
        event.incident_id,
        event.store_id,
        actor_name(authorization),
    )
    db.commit()
    return {
        "message": "Retry queued. Existing decisions and protective holds are retained."
    }


class CredentialIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role: Literal["admin", "operator", "integration", "viewer"]
    store_ids: list[str] = Field(default_factory=list, max_length=100)


class CredentialOut(BaseModel):
    id: str
    name: str
    role: str
    store_ids: list[str]
    active: bool


class CreatedCredential(CredentialOut):
    token: str


def credential_view(row):
    return {k: getattr(row, k) for k in ["id", "name", "role", "store_ids", "active"]}


@router.get("/operations/credentials", response_model=list[CredentialOut])
def credentials(
    db: Session = Depends(get_db), authorization: str | None = Header(None)
):
    require_admin(authorization)
    return [
        credential_view(c)
        for c in db.scalars(
            select(AccessCredential).order_by(AccessCredential.created_at.desc())
        )
    ]


@router.post("/operations/credentials", response_model=CreatedCredential)
def create_credential(
    body: CredentialIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    require_admin(authorization)
    if body.role != "admin" and not body.store_ids:
        raise HTTPException(422, "Non-admin credentials require explicit store scope.")
    if any(not db.get(Store, store_id) for store_id in body.store_ids):
        raise HTTPException(422, "Unknown store in credential scope.")
    token = secrets.token_urlsafe(36)
    row = AccessCredential(
        name=body.name,
        role=body.role,
        store_ids=body.store_ids,
        token_hash=sha256(token.encode()).hexdigest(),
    )
    db.add(row)
    db.flush()
    append_audit_event(
        db,
        "credential_created",
        {
            "credential_id": row.id,
            "name": row.name,
            "role": row.role,
            "store_ids": row.store_ids,
        },
        actor=actor_name(authorization),
    )
    db.commit()
    return {**credential_view(row), "token": token}


@router.post(
    "/operations/credentials/{credential_id}/revoke", response_model=MessageOut
)
def revoke(
    credential_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    require_admin(authorization)
    row = db.get(AccessCredential, credential_id)
    if not row:
        raise HTTPException(404, "Credential not found.")
    row.active = False
    append_audit_event(
        db,
        "credential_revoked",
        {"credential_id": row.id},
        actor=actor_name(authorization),
    )
    db.commit()
    return {"message": "Credential revoked."}


@router.get("/stores", response_model=list[Entity])
def stores(db: Session = Depends(get_db), authorization: str | None = Header(None)):
    authorize(authorization=authorization)
    query = select(Store).where(Store.active.is_(True), Store.mode != "evaluation")
    scope = store_scope(authorization)
    if scope is not None:
        query = query.where(Store.id.in_(scope))
    return [record(s) for s in db.scalars(query)]


class StoreIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)


@router.post("/stores", response_model=Entity)
def create_store(
    body: StoreIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    require_admin(authorization)
    row = Store(name=body.name, mode="live")
    db.add(row)
    db.flush()
    append_audit_event(
        db,
        "store_created",
        {"message": body.name},
        store_id=row.id,
        actor=actor_name(authorization),
    )
    db.commit()
    return record(row)


class StockUpdate(BaseModel):
    external_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=1)
    stock: InventoryRow


class StockUpdateOut(BaseModel):
    receipt_id: str
    inventory_lot_id: str
    duplicate: bool


@router.post(
    "/stores/{store_id}/inventory-events",
    response_model=StockUpdateOut,
    status_code=202,
)
def stock_event(
    store_id: str,
    body: StockUpdate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    authorize(authorization=authorization)
    require_store(store_id, authorization)
    store = db.get(Store, store_id)
    if not store or not store.active:
        raise HTTPException(404, "Active store not found.")
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,2))"),
        {"key": store.id},
    )
    content_hash = digest(body.model_dump(mode="json"))
    receipt = db.scalar(
        select(InventoryReceipt).where(
            InventoryReceipt.store_id == store.id,
            InventoryReceipt.external_id == body.external_id,
            InventoryReceipt.sequence == body.sequence,
        )
    )
    if receipt:
        if receipt.content_hash != content_hash:
            raise HTTPException(
                409, "The same sequence cannot carry different inventory data."
            )
        return {
            "receipt_id": receipt.id,
            "inventory_lot_id": receipt.payload["inventory_lot_id"],
            "duplicate": True,
        }
    latest = db.scalar(
        select(InventoryReceipt)
        .where(
            InventoryReceipt.store_id == store.id,
            InventoryReceipt.external_id == body.external_id,
        )
        .order_by(InventoryReceipt.sequence.desc())
        .limit(1)
    )
    if latest and latest.sequence >= body.sequence:
        raise HTTPException(409, "Stale inventory sequence. Submit a newer sequence.")
    stock = db.get(InventoryLot, latest.payload["inventory_lot_id"]) if latest else None
    if stock:
        hold = db.scalar(
            select(func.max(InventoryHold.quantity)).where(
                InventoryHold.inventory_lot_id == stock.id,
                InventoryHold.status == "active",
            )
        )
        if hold and (
            body.stock.quantity < hold
            or stock.gtin != body.stock.gtin
            or stock.lot != body.stock.lot
            or stock.expires_on != body.stock.expires_on
        ):
            raise HTTPException(
                409,
                "Held stock identity or quantity cannot be overwritten. Submit contradictory evidence for human review.",
            )
        for key, value in body.stock.model_dump().items():
            setattr(stock, key, value)
        stock.lot_key = lot_key(body.stock.lot)
    else:
        stock = InventoryLot(
            store_id=store.id,
            lot_key=lot_key(body.stock.lot),
            **body.stock.model_dump(),
        )
        db.add(stock)
    db.flush()
    receipt = InventoryReceipt(
        store_id=store.id,
        external_id=body.external_id,
        sequence=body.sequence,
        content_hash=content_hash,
        payload={
            "inventory_lot_id": stock.id,
            "stock": body.stock.model_dump(mode="json"),
            "synthetic": store.mode != "live",
        },
    )
    db.add(receipt)
    db.flush()
    discover_incidents(db, store_id=store.id, mode=store.mode)
    append_audit_event(
        db,
        "inventory_event_received",
        {
            "receipt_id": receipt.id,
            "sequence": body.sequence,
            "synthetic": store.mode != "live",
        },
        store_id=store.id,
        actor=actor_name(authorization),
    )
    db.commit()
    return {"receipt_id": receipt.id, "inventory_lot_id": stock.id, "duplicate": False}
