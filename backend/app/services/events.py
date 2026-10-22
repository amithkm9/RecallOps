"""PostgreSQL outbox: committed claims, bounded retry, session advisory locks."""

import logging
from datetime import timedelta
from sqlalchemy import or_, select, text
from app.core.database import SessionLocal, engine
from app.models import Event, Incident, Recall, Store, utcnow
from app.repositories.records import enqueue, append_audit_event
from app.agents.workflow import investigate

log = logging.getLogger(__name__)


def process_event(event_id: str) -> str | None:
    with engine.connect() as lock_connection:
        # Lock lives across workflow commits and releases automatically on connection loss.
        lock_connection.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:key,0))"), {"key": event_id}
        )
        incident_key = None
        store_key = None
        try:
            with SessionLocal() as db:
                event = db.get(Event, event_id)
                if not event or event.status in {"completed", "superseded"}:
                    from app.models import AgentRun

                    run = db.scalar(
                        select(AgentRun).where(AgentRun.event_id == event_id)
                    )
                    return run.id if run else None
                incident_key = event.incident_id
                store_key = event.store_id
                if store_key:
                    lock_connection.execute(
                        text("SELECT pg_advisory_lock(hashtextextended(:key,2))"),
                        {"key": store_key},
                    )
                if incident_key:
                    lock_connection.execute(
                        text("SELECT pg_advisory_lock(hashtextextended(:key,1))"),
                        {"key": incident_key},
                    )
                    db.refresh(event)
                    incident = db.get(Incident, incident_key)
                    recall = db.get(Recall, incident.recall_id)
                    store = db.get(Store, incident.store_id)
                    pinned = event.payload.get("recall_version_id")
                    if (
                        store.mode == "live"
                        and pinned
                        and pinned != recall.current_version_id
                    ):
                        event.status = "superseded"
                        event.completed_at = utcnow()
                        replacement = enqueue(
                            db,
                            f"supersedes:{event.id}:{recall.current_version_id}",
                            "source_version_reconsidered",
                            incident.id,
                            store.id,
                            {"recall_version_id": recall.current_version_id},
                        )
                        append_audit_event(
                            db,
                            "stale_event_superseded",
                            {
                                "event_id": event.id,
                                "replacement_event_id": replacement.id,
                            },
                            incident.id,
                            store.id,
                        )
                        db.commit()
                        return None
                event.status = "processing"
                event.locked_at = utcnow()
                event.attempts += 1
                db.commit()
                try:
                    run = investigate(db, event) if incident_key else None
                    event.status = "completed"
                    event.completed_at = utcnow()
                    event.error = None
                    db.commit()
                    return run.id if run else None
                except Exception as exc:
                    db.rollback()
                    event = db.get(Event, event_id)
                    event.status = "failed" if event.attempts >= 3 else "pending"
                    event.error = type(exc).__name__
                    from app.models import AgentRun

                    failed_run = db.scalar(
                        select(AgentRun).where(AgentRun.event_id == event_id)
                    )
                    if failed_run:
                        failed_run.status = (
                            "failed" if event.attempts >= 3 else "retrying"
                        )
                    event.available_at = utcnow() + timedelta(seconds=2**event.attempts)
                    append_audit_event(
                        db,
                        "investigation_failed",
                        {
                            "event_id": event.id,
                            "error_type": event.error,
                            "attempts": event.attempts,
                            "status": event.status,
                        },
                        event.incident_id,
                        event.store_id,
                    )
                    db.commit()
                    log.exception("Event processing failed: %s", event_id)
                    raise
        finally:
            if incident_key:
                lock_connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key,1))"),
                    {"key": incident_key},
                )
            if store_key:
                lock_connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key,2))"),
                    {"key": store_key},
                )
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                {"key": event_id},
            )


def process_next() -> bool:
    with SessionLocal() as db:
        event = db.scalar(
            select(Event)
            .where(
                or_(
                    (Event.status == "pending") & (Event.available_at <= utcnow()),
                    (Event.status == "processing")
                    & (Event.locked_at < utcnow() - timedelta(minutes=5)),
                )
            )
            .order_by(Event.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not event:
            return False
        event.status = "processing"
        event.locked_at = utcnow()
        event_id = event.id
        db.commit()
    process_event(event_id)
    return True
