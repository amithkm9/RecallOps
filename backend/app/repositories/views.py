from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import (
    AgentRun,
    AuditLog,
    Decision,
    DecisionEvidence,
    Evidence,
    Incident,
    InventoryHold,
    InventoryLot,
    Recall,
    RecallTarget,
    RecallVersion,
    Replay,
    SourceState,
    Store,
)
from app.repositories.records import jsonable, record
from app.services.ingestion import COVERAGE, DATASET_URL


def evidence_view(evidence):
    result = record(evidence)
    if evidence.kind in {"official_document", "delivery_document"}:
        result["payload"] = {
            k: v for k, v in evidence.payload.items() if k != "content_base64"
        }
        segment = "investigator/documents" if evidence.kind == "delivery_document" else "documents"
        result["download_path"] = f"/api/incidents/{evidence.incident_id}/{segment}/{evidence.id}"
    return result


def recall_view(db: Session, recall: Recall, version_id: str | None = None) -> dict:
    version = db.get(RecallVersion, version_id or recall.current_version_id)
    from datetime import timedelta

    clock_warnings = []
    if version.published_at > version.created_at + timedelta(minutes=5):
        clock_warnings.append(
            "Official publication time is ahead of collection time. Publisher and collector clocks may differ; freshness cannot be inferred from this value."
        )
    if (
        version.source_updated_at
        and version.source_updated_at > version.created_at + timedelta(minutes=5)
    ):
        clock_warnings.append("Official modification time is ahead of collection time.")
    return {
        **record(version),
        "id": recall.id,
        "source_id": recall.source_id,
        "reference": recall.reference,
        "version_id": version.id,
        "ingested_at": version.created_at.isoformat(),
        "clock_warnings": clock_warnings,
    }


def inventory_view(db: Session, lot: InventoryLot) -> dict:
    held = db.scalar(
        select(InventoryHold.id)
        .where(
            InventoryHold.inventory_lot_id == lot.id, InventoryHold.status == "active"
        )
        .limit(1)
    )
    decision = db.scalar(
        select(Decision)
        .where(Decision.inventory_lot_id == lot.id)
        .order_by(Decision.created_at.desc())
        .limit(1)
    )
    return {
        **record(lot),
        "status": "held" if held else decision.verdict if decision else "unverified",
    }


def incident_view(db: Session, incident: Incident) -> dict:
    recall = db.get(Recall, incident.recall_id)
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.incident_id == incident.id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    version = db.get(
        RecallVersion, run.recall_version_id if run else recall.current_version_id
    )
    store = db.get(Store, incident.store_id)
    held = db.scalar(
        select(func.coalesce(func.sum(InventoryHold.quantity), 0)).where(
            InventoryHold.incident_id == incident.id, InventoryHold.status == "active"
        )
    )
    return {
        **record(incident),
        "product_name": version.product_name,
        "reference": recall.reference,
        "store_name": store.name,
        "mode": store.mode,
        "affected_quantity": held,
        "published_at": version.published_at.isoformat(),
    }


def detail_view(db: Session, incident: Incident) -> dict:
    decisions = []
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.incident_id == incident.id)
        .order_by(AgentRun.created_at)
    ).all()
    for decision in db.scalars(
        select(Decision)
        .where(Decision.incident_id == incident.id)
        .order_by(Decision.created_at)
    ):
        evidence_ids = db.scalars(
            select(DecisionEvidence.evidence_id).where(
                DecisionEvidence.decision_id == decision.id
            )
        ).all()
        decisions.append({**record(decision), "evidence_ids": list(evidence_ids)})
    inventory = db.scalars(
        select(InventoryLot)
        .where(InventoryLot.store_id == incident.store_id)
        .order_by(InventoryLot.created_at)
    ).all()
    return {
        "incident": incident_view(db, incident),
        "recall": recall_view(
            db,
            db.get(Recall, incident.recall_id),
            runs[-1].recall_version_id if runs else None,
        ),
        "inventory": [inventory_view(db, i) for i in inventory],
        "targets": [
            record(t)
            for t in db.scalars(
                select(RecallTarget).where(
                    RecallTarget.recall_version_id
                    == (
                        runs[-1].recall_version_id
                        if runs
                        else db.get(Recall, incident.recall_id).current_version_id
                    )
                )
            )
        ],
        "evidence": [
            evidence_view(e)
            for e in db.scalars(
                select(Evidence)
                .where(Evidence.incident_id == incident.id)
                .order_by(Evidence.created_at)
            )
        ],
        "decisions": decisions,
        "holds": [
            record(h)
            for h in db.scalars(
                select(InventoryHold)
                .where(InventoryHold.incident_id == incident.id)
                .order_by(InventoryHold.created_at)
            )
        ],
        "runs": [record(r) for r in runs],
        "history": [
            record(a)
            for a in db.scalars(
                select(AuditLog)
                .where(AuditLog.incident_id == incident.id)
                .order_by(AuditLog.created_at)
            )
        ],
    }


def replay_view(db: Session, replay: Replay):
    events = []
    for event in replay.events:
        run = db.scalar(select(AgentRun).where(AgentRun.event_id == event["event_id"]))
        events.append({**event, "run_id": run.id if run else None})
    return {
        **record(replay),
        "events": events,
        "detail": detail_view(db, db.get(Incident, replay.incident_id)),
    }


def settings_view(db: Session):
    state = db.get(SourceState, "rappelconso")
    return {
        "llm_enabled": bool(settings.llm_api_key),
        "llm_model": settings.llm_model,
        "auth_required": bool(settings.operator_token)
        or settings.environment != "development",
        "demo_enabled": settings.demo_enabled,
        "last_successful_sync": jsonable(state.last_successful_sync) if state else None,
        "last_sync_error": state.last_error if state else None,
        "coverage": COVERAGE,
        "dataset_url": DATASET_URL,
        "mode": "public_demo" if settings.public_demo else settings.environment,
        "source_count": db.scalar(
            select(func.count(Recall.id)).where(
                ~Recall.source_id.startswith("benchmark:")
            )
        ),
        "refresh_interval_seconds": settings.source_refresh_seconds,
    }
