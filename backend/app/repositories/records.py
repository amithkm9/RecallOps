import hashlib
import json
from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from app.models import AuditLog, Evidence, Event


def jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def record(obj) -> dict:
    return {
        c.key: jsonable(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs
    }


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def append_audit_event(
    db: Session,
    kind: str,
    payload: dict,
    incident_id: str | None = None,
    store_id: str | None = None,
    actor: str = "agent",
) -> AuditLog:
    row = AuditLog(
        kind=kind,
        payload=jsonable(payload),
        incident_id=incident_id,
        store_id=store_id,
        actor=actor,
    )
    db.add(row)
    db.flush()
    return row


def add_evidence(
    db: Session, incident_id: str, kind: str, label: str, payload: dict, **kwargs
) -> Evidence:
    fingerprint = digest([kind, payload, kwargs])
    existing = db.scalar(
        select(Evidence).where(
            Evidence.incident_id == incident_id, Evidence.fingerprint == fingerprint
        )
    )
    if existing:
        return existing
    row = Evidence(
        incident_id=incident_id,
        kind=kind,
        label=label,
        payload=jsonable(payload),
        fingerprint=fingerprint,
        **kwargs,
    )
    db.add(row)
    db.flush()
    return row


def enqueue(
    db: Session,
    key: str,
    kind: str,
    incident_id: str | None = None,
    store_id: str | None = None,
    payload: dict | None = None,
) -> Event:
    db.execute(
        insert(Event)
        .values(
            idempotency_key=key,
            kind=kind,
            incident_id=incident_id,
            store_id=store_id,
            payload=payload or {},
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return db.scalar(select(Event).where(Event.idempotency_key == key))
