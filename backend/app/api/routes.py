import asyncio
import json
from typing import Literal
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.security import (
    authorize,
    is_operator,
    require_store,
    store_scope,
    require_admin,
    actor_name,
)
from app.models import (
    AgentRun,
    AuditLog,
    Decision,
    EvaluationRun,
    Event,
    Incident,
    InventoryHold,
    InventoryLot,
    Recall,
    Replay,
    Store,
    utcnow,
)
from app.repositories.records import append_audit_event, enqueue, record
from app.repositories.views import (
    detail_view,
    incident_view,
    inventory_view,
    recall_view,
    replay_view,
    settings_view,
)
from app.schemas.api import (
    DashboardOut,
    DetailOut,
    Entity,
    EvaluationOut,
    EventOut,
    HealthOut,
    ImportOut,
    IncidentList,
    InventoryList,
    InvestigateIn,
    MessageOut,
    ModelCheckOut,
    RecallOut,
    ReplayNextIn,
    ReplayOut,
    ReviewIn,
    SettingsOut,
    SupplierEvidenceIn,
    SupplierEvidenceOut,
    SyncIn,
    SyncOut,
)
from app.services.ingestion import sync_source
from app.services.inventory import import_csv
from app.services.replay import next_replay, start_replay

router = APIRouter()
Mode = Literal["live", "replay"]


def require_incident(
    db: Session, incident_id: str, authorization: str | None
) -> Incident:
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found.")
    store = db.get(Store, incident.store_id)
    authorize(store.mode, authorization)
    require_store(store.id, authorization)
    return incident


def demo_allowed(authorization: str | None):
    if not settings.demo_enabled:
        raise HTTPException(403, "Replay is disabled on this deployment.")
    authorize("replay", authorization)
    if store_scope(authorization) is not None:
        raise HTTPException(
            403, "Replay creation/reset requires an administrator credential."
        )


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "postgresql", "api_version": "1"}


@router.get("/settings", response_model=SettingsOut)
def config(
    db: Session = Depends(get_db), authorization: str | None = Header(default=None)
):
    # Public configuration omits secrets and business counts.
    result = settings_view(db)
    if settings.public_demo and not is_operator(authorization):
        result["source_count"] = 0
    return result


@router.post("/settings/model-check", response_model=ModelCheckOut)
def model_check(authorization: str | None = Header(default=None)):
    authorize(authorization=authorization)
    from app.agents.llm import check_model_connection

    return check_model_connection()


@router.post(
    "/incidents/{incident_id}/supplier-evidence",
    response_model=SupplierEvidenceOut,
    status_code=202,
)
def supplier_evidence(
    incident_id: str,
    body: SupplierEvidenceIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    incident = require_incident(db, incident_id, authorization)
    if settings.public_demo and not is_operator(authorization):
        raise HTTPException(
            403, "Submitting supplier evidence requires operator access."
        )
    from app.services.evidence import submit_supplier_evidence

    return submit_supplier_evidence(db, incident, body, actor_name(authorization))


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    mode: Mode = "replay",
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    authorize(mode, authorization)
    stores = list(
        db.scalars(select(Store.id).where(Store.mode == mode, Store.active.is_(True)))
    )
    scope = store_scope(authorization)
    if scope is not None:
        stores = [store_id for store_id in stores if store_id in scope]
    incidents = db.scalars(
        select(Incident)
        .where(Incident.store_id.in_(stores))
        .order_by(Incident.updated_at.desc())
    ).all()
    ids = [i.id for i in incidents]
    holds = db.scalars(
        select(InventoryHold).where(
            InventoryHold.incident_id.in_(ids), InventoryHold.status == "active"
        )
    ).all()
    latest = []
    for i in incidents:
        run = db.scalar(
            select(AgentRun)
            .where(AgentRun.incident_id == i.id, AgentRun.status == "completed")
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
        if run:
            latest.extend(
                db.scalars(select(Decision).where(Decision.run_id == run.id)).all()
            )
    # Distinct stock units, even if multiple recalls hold the same inventory lot.
    held_by_lot = {}
    for h in holds:
        held_by_lot[h.inventory_lot_id] = max(
            held_by_lot.get(h.inventory_lot_id, 0), h.quantity
        )
    outcomes = [
        {"name": "Affected", "value": sum(d.verdict == "affected" for d in latest)},
        {
            "name": "Needs review",
            "value": sum(d.verdict in {"review", "conflict"} for d in latest),
        },
        {"name": "Unaffected", "value": sum(d.verdict == "unaffected" for d in latest)},
    ]
    return {
        "active_incidents": sum(i.status != "unaffected" for i in incidents),
        "affected_units": sum(held_by_lot.values()),
        "awaiting_review": sum(i.status in {"review", "conflict"} for i in incidents),
        "completed_actions": db.scalar(
            select(func.count(InventoryHold.id)).where(
                InventoryHold.incident_id.in_(ids)
            )
        ),
        "inventory_units": db.scalar(
            select(func.coalesce(func.sum(InventoryLot.quantity), 0)).where(
                InventoryLot.store_id.in_(stores)
            )
        ),
        "recall_count": db.scalar(
            select(func.count(Recall.id)).where(
                ~Recall.source_id.startswith("benchmark:")
            )
        ),
        "latest_incidents": [incident_view(db, i) for i in incidents[:5]],
        "activity": [
            record(a)
            for a in db.scalars(
                select(AuditLog)
                .where(AuditLog.store_id.in_(stores))
                .order_by(AuditLog.created_at.desc())
                .limit(5)
            )
        ],
        "settings": settings_view(db),
        "outcomes": outcomes,
    }


@router.get("/recalls", response_model=list[RecallOut])
def recalls(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    authorize("live", authorization)
    return [
        recall_view(db, r)
        for r in db.scalars(
            select(Recall)
            .where(~Recall.source_id.startswith("benchmark:"))
            .order_by(Recall.last_seen_at.desc())
            .limit(limit)
        )
    ]


@router.post("/recalls/sync", response_model=SyncOut)
def synchronize(
    body: SyncIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    authorize("live", authorization)
    require_admin(authorization)
    return sync_source(db, body.source, body.start_offset)


@router.get("/recalls/{recall_id}", response_model=RecallOut)
def recall_detail(
    recall_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    authorize("live", authorization)
    recall = db.get(Recall, recall_id)
    if not recall:
        raise HTTPException(404, "Recall not found.")
    return recall_view(db, recall)


@router.get("/inventory/sample")
def inventory_sample():
    return Response(
        "sku,product_name,gtin,lot,quantity,supplier,expires_on\nDEMO-001,Fictional example inventory,3760099533007,SAFE-DEMO-LOT,18,Fictional supplier,2024-12-20\nDEMO-002,Fictional example inventory,3760099533007,,24,Fictional supplier,2024-12-20\n",
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="recallops-inventory.csv"'
        },
    )


@router.get("/inventory", response_model=InventoryList)
def inventory(
    mode: Mode = "replay",
    search: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    authorize(mode, authorization)
    query = (
        select(InventoryLot)
        .join(Store, Store.id == InventoryLot.store_id)
        .where(Store.mode == mode, Store.active.is_(True))
    )
    scope = store_scope(authorization)
    if scope is not None:
        query = query.where(InventoryLot.store_id.in_(scope))
    if search:
        query = query.where(
            or_(
                InventoryLot.product_name.ilike(f"%{search}%"),
                InventoryLot.sku.ilike(f"%{search}%"),
                InventoryLot.gtin.ilike(f"%{search}%"),
                InventoryLot.lot.ilike(f"%{search}%"),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    return {
        "items": [
            inventory_view(db, i)
            for i in db.scalars(
                query.order_by(InventoryLot.created_at)
                .offset((page - 1) * 20)
                .limit(20)
            )
        ],
        "total": total,
    }


@router.post("/inventory/import", response_model=ImportOut)
def upload_inventory(
    file: UploadFile = File(...),
    mode: Mode = Form("live"),
    store_id: str | None = Form(None),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    authorize(mode, authorization)
    if settings.public_demo and not is_operator(authorization):
        raise HTTPException(
            403,
            "Public replay uses controlled fictional inventory; CSV import requires an operator.",
        )
    scope = store_scope(authorization)
    if scope is not None and not store_id:
        if len(scope) != 1:
            raise HTTPException(422, "Specify a store_id within your credential scope.")
        store_id = scope[0]
    if store_id:
        require_store(store_id, authorization)
    return import_csv(db, file.file.read(2_000_001), mode, store_id)


@router.get("/incidents", response_model=IncidentList)
def incidents(
    mode: Mode = "replay",
    search: str = Query("", max_length=200),
    status: str = "",
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    authorize(mode, authorization)
    rows = db.scalars(
        select(Incident)
        .join(Store)
        .where(Store.mode == mode, Store.active.is_(True))
        .order_by(Incident.updated_at.desc())
    ).all()
    scope = store_scope(authorization)
    items = [
        incident_view(db, i)
        for i in rows
        if (scope is None or i.store_id in scope) and (not status or i.status == status)
    ]
    if search:
        items = [
            i
            for i in items
            if search.casefold()
            in (i["reference"] + " " + i["product_name"]).casefold()
        ]
    return {"items": items}


@router.get("/incidents/empty", response_model=None)
def empty_incident():
    return None


@router.get("/incidents/{incident_id}", response_model=DetailOut)
def incident_detail(
    incident_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    return detail_view(db, require_incident(db, incident_id, authorization))


@router.post("/incidents/{incident_id}/investigate", response_model=EventOut)
def trigger_investigation(
    incident_id: str,
    body: InvestigateIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    incident = require_incident(db, incident_id, authorization)
    if settings.public_demo:
        authorize(authorization=authorization, strict=True)
    event = enqueue(
        db,
        f"manual:{incident.id}:{body.idempotency_key or uuid4()}",
        "operator_reinvestigation",
        incident.id,
        incident.store_id,
    )
    db.commit()
    return record(event)


@router.get("/incidents/{incident_id}/evidence", response_model=list[Entity])
def evidence(
    incident_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    return detail_view(db, require_incident(db, incident_id, authorization))["evidence"]


@router.get("/incidents/{incident_id}/history", response_model=list[Entity])
def history(
    incident_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    return detail_view(db, require_incident(db, incident_id, authorization))["history"]


@router.post("/incidents/{incident_id}/review", response_model=MessageOut)
def review(
    incident_id: str,
    body: ReviewIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    authorize(authorization=authorization, strict=True)
    incident = require_incident(db, incident_id, authorization)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,2))"),
        {"key": incident.store_id},
    )
    db.refresh(incident)
    person = actor_name(authorization)
    if body.action in {"assign", "acknowledge"}:
        incident.assigned_to = person
        incident.review_status = (
            "acknowledged" if body.action == "acknowledge" else "assigned"
        )
    elif body.action == "reopen":
        incident.review_status, incident.closed_at = "open", None
    elif body.action == "close":
        from app.models import Evidence, DecisionEvidence

        run = db.scalar(
            select(AgentRun)
            .where(AgentRun.incident_id == incident.id)
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
        if not run or run.id != body.expected_run_id or run.status != "completed":
            raise HTTPException(
                409,
                "The investigation changed. Refresh and review its latest completed run.",
            )
        store = db.get(Store, incident.store_id)
        recall = db.get(Recall, incident.recall_id)
        if store.mode == "live" and run.recall_version_id != recall.current_version_id:
            raise HTTPException(
                409,
                "The official recall changed. Reassess the current version before closing this case.",
            )
        pending = db.scalar(
            select(Event.id)
            .where(
                Event.incident_id == incident.id,
                Event.status.in_(["pending", "processing", "failed"]),
            )
            .limit(1)
        )
        held = db.scalar(
            select(InventoryHold.id)
            .where(
                InventoryHold.incident_id == incident.id,
                InventoryHold.status == "active",
            )
            .limit(1)
        )
        unresolved = db.scalar(
            select(Decision.id)
            .where(Decision.run_id == run.id, Decision.verdict != "unaffected")
            .limit(1)
        )
        if pending or held or unresolved:
            raise HTTPException(
                409,
                "Resolve outstanding events, affected stock, holds and uncertain evidence before closing this case.",
            )
        if not body.evidence_ids or any(
            not (e := db.get(Evidence, eid)) or e.incident_id != incident.id
            for eid in body.evidence_ids
        ):
            raise HTTPException(
                422, "Closure requires contributing evidence from this incident."
            )
        contributing = set(
            db.scalars(
                select(DecisionEvidence.evidence_id)
                .join(Decision)
                .where(Decision.run_id == run.id)
            )
        )
        if not set(body.evidence_ids).issubset(contributing):
            raise HTTPException(
                422, "Cite evidence contributing to the latest completed decision."
            )
        incident.review_status, incident.closed_at = "closed", utcnow()
    if body.action == "release_hold":
        hold = db.scalar(
            select(InventoryHold)
            .where(
                InventoryHold.id == body.hold_id,
                InventoryHold.incident_id == incident_id,
            )
            .with_for_update()
        )
        if not hold:
            raise HTTPException(404, "Hold not found for this incident.")
        if hold.status == "released":
            return {"message": "Hold was already released."}
        hold.status = "released"
        hold.released_at = utcnow()
        hold.released_by = person
        hold.release_reason = body.reason
        incident.status = "review"
    append_audit_event(
        db,
        "human_review",
        {
            "message": body.reason,
            "action": body.action,
            "hold_id": body.hold_id,
            "evidence_ids": body.evidence_ids,
            "run_id": body.expected_run_id,
        },
        incident.id,
        incident.store_id,
        actor=person,
    )
    db.commit()
    return {
        "message": "Human review recorded. External systems have not been modified."
    }


@router.post("/demo/seed", response_model=ReplayOut)
@router.post("/demo/replay/start", response_model=ReplayOut)
def replay_start(
    db: Session = Depends(get_db), authorization: str | None = Header(default=None)
):
    demo_allowed(authorization)
    return replay_view(db, start_replay(db))


@router.post("/demo/replay/next", response_model=ReplayOut)
def replay_next(
    body: ReplayNextIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    demo_allowed(authorization)
    return replay_view(db, next_replay(db, body.replay_id, body.expected_step))


@router.get("/demo/replay/latest", response_model=ReplayOut | None)
def replay_latest(
    db: Session = Depends(get_db), authorization: str | None = Header(default=None)
):
    demo_allowed(authorization)
    replay = db.scalar(select(Replay).order_by(Replay.created_at.desc()).limit(1))
    return replay_view(db, replay) if replay else None


@router.get("/demo/replay/{replay_id}", response_model=ReplayOut)
def replay_get(
    replay_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    demo_allowed(authorization)
    replay = db.get(Replay, replay_id)
    if not replay:
        raise HTTPException(404, "Replay not found.")
    return replay_view(db, replay)


@router.post("/evaluation/run", response_model=EvaluationOut)
def evaluate(
    db: Session = Depends(get_db), authorization: str | None = Header(default=None)
):
    authorize("replay" if settings.public_demo else "live", authorization)
    if not settings.public_demo:
        require_admin(authorization)
    from app.services.evaluation import run_evaluation

    return record(run_evaluation(db))


@router.get("/evaluation/latest", response_model=EvaluationOut | None)
def evaluation_latest(
    db: Session = Depends(get_db), authorization: str | None = Header(default=None)
):
    authorize("replay" if settings.public_demo else "live", authorization)
    result = db.scalar(
        select(EvaluationRun)
        .where(~EvaluationRun.benchmark.startswith("Investigator comparison v1"))
        .order_by(EvaluationRun.created_at.desc())
        .limit(1)
    )
    return record(result) if result else None


@router.get("/events/stream")
async def event_stream(
    request: Request,
    authorization: str | None = Header(default=None),
    last_event_id: str | None = Header(default=None),
):
    authorize("replay" if settings.public_demo else "live", authorization)
    public_only = settings.public_demo and not is_operator(authorization)
    scope = store_scope(authorization)

    async def generate():
        # IDs are UUIDs; timestamp + UUID gives a stable cursor even within one transaction.
        with SessionLocal() as db:
            last = db.get(AuditLog, last_event_id) if last_event_id else None
            cursor = (last.created_at, last.id) if last else (utcnow(), "")
        while not await request.is_disconnected():
            if authorization:
                from app.core.security import identity

                if not identity(authorization):
                    break
            with SessionLocal() as db:
                query = select(AuditLog).where(
                    or_(
                        AuditLog.created_at > cursor[0],
                        (AuditLog.created_at == cursor[0]) & (AuditLog.id > cursor[1]),
                    )
                )
                if scope is not None:
                    query = query.where(AuditLog.store_id.in_(scope))
                if public_only:
                    query = query.join(Store, Store.id == AuditLog.store_id).where(
                        Store.mode == "replay"
                    )
                rows = db.scalars(
                    query.order_by(AuditLog.created_at, AuditLog.id).limit(100)
                ).all()
                data = [record(row) for row in rows]
                if rows:
                    cursor = (rows[-1].created_at, rows[-1].id)
            for row in data:
                yield f"id: {row['id']}\nevent: progress\ndata: {json.dumps(row)}\n\n"
            if not data:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
