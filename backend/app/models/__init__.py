from datetime import date, datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Store(Record, Base):
    __tablename__ = "stores"
    name: Mapped[str] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(16), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("mode IN ('live','replay','evaluation')"),)


class InventoryLot(Record, Base):
    __tablename__ = "inventory_lots"
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    sku: Mapped[str] = mapped_column(String(120))
    product_name: Mapped[str] = mapped_column(String(500))
    gtin: Mapped[str] = mapped_column(String(14), index=True)
    lot: Mapped[str | None] = mapped_column(String(300))
    lot_key: Mapped[str] = mapped_column(String(300), default="")
    quantity: Mapped[int] = mapped_column(Integer)
    supplier: Mapped[str] = mapped_column(String(300), default="")
    expires_on: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    __table_args__ = (
        UniqueConstraint("store_id", "sku", "lot_key", name="uq_inventory_identity"),
        CheckConstraint("quantity >= 0"),
        CheckConstraint("gtin ~ '^[0-9]{8}$|^[0-9]{12,14}$'", name="ck_gtin_format"),
    )


class Recall(Record, Base):
    __tablename__ = "recalls"
    source_id: Mapped[str] = mapped_column(String(100), unique=True)
    reference: Mapped[str] = mapped_column(String(100), index=True)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "recall_versions.id", use_alter=True, name="fk_recall_current_version"
        )
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class RecallVersion(Record, Base):
    __tablename__ = "recall_versions"
    recall_id: Mapped[str] = mapped_column(ForeignKey("recalls.id"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    official_version: Mapped[str] = mapped_column(String(30))
    product_name: Mapped[str] = mapped_column(String(1000))
    brand: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(300))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    risk: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB)
    parse_warnings: Mapped[list] = mapped_column(JSONB, default=list)
    __table_args__ = (
        UniqueConstraint("recall_id", "content_hash", name="uq_recall_content"),
    )


class RecallTarget(Record, Base):
    __tablename__ = "recall_targets"
    recall_version_id: Mapped[str] = mapped_column(
        ForeignKey("recall_versions.id"), index=True
    )
    gtin: Mapped[str] = mapped_column(String(14), index=True)
    scope: Mapped[dict] = mapped_column(JSONB)


class Incident(Record, Base):
    __tablename__ = "incidents"
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    recall_id: Mapped[str] = mapped_column(ForeignKey("recalls.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(120))
    review_status: Mapped[str] = mapped_column(String(30), default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    __table_args__ = (
        UniqueConstraint("store_id", "recall_id", name="uq_incident_store_recall"),
    )


class Evidence(Record, Base):
    __tablename__ = "evidence"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    inventory_lot_id: Mapped[str | None] = mapped_column(
        ForeignKey("inventory_lots.id"), index=True
    )
    recall_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("recall_versions.id")
    )
    kind: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSONB)
    source_url: Mapped[str | None] = mapped_column(Text)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    fingerprint: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("incident_id", "fingerprint", name="uq_evidence_content"),
    )


class Event(Record, Base):
    __tablename__ = "events"
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id"), index=True
    )
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_outbox_queue", "status", "available_at"),)


class AgentRun(Record, Base):
    __tablename__ = "agent_runs"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), unique=True)
    recall_version_id: Mapped[str] = mapped_column(ForeignKey("recall_versions.id"))
    status: Mapped[str] = mapped_column(String(30), default="running")
    active_node: Mapped[str] = mapped_column(String(80), default="detect_event")
    llm_mode: Mapped[str] = mapped_column(String(60), default="deterministic_fallback")
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    steps: Mapped[list] = mapped_column(JSONB, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    draft: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[float | None] = mapped_column(Float)


class Decision(Record, Base):
    __tablename__ = "decisions"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    inventory_lot_id: Mapped[str] = mapped_column(ForeignKey("inventory_lots.id"))
    recall_version_id: Mapped[str] = mapped_column(ForeignKey("recall_versions.id"))
    verdict: Mapped[str] = mapped_column(String(30))
    explanation: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(60))
    quantity: Mapped[int] = mapped_column(Integer)
    lot: Mapped[str | None] = mapped_column(String(300))
    previous_verdict: Mapped[str | None] = mapped_column(String(30))
    __table_args__ = (
        UniqueConstraint("run_id", "inventory_lot_id", name="uq_run_decision"),
        CheckConstraint("verdict IN ('affected','unaffected','review','conflict')"),
    )


class DecisionEvidence(Base):
    __tablename__ = "decision_evidence"
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decisions.id"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence.id"), primary_key=True
    )


class InventoryHold(Record, Base):
    __tablename__ = "inventory_holds"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    inventory_lot_id: Mapped[str] = mapped_column(
        ForeignKey("inventory_lots.id"), index=True
    )
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="active")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[str | None] = mapped_column(String(120))
    release_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("quantity > 0"),
        Index(
            "uq_active_hold",
            "incident_id",
            "inventory_lot_id",
            unique=True,
            postgresql_where=(status == "active"),
        ),
    )


class AuditLog(Record, Base):
    __tablename__ = "audit_log"
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id"), index=True
    )
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(80), default="agent")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class EvaluationRun(Record, Base):
    __tablename__ = "evaluation_runs"
    sample_size: Mapped[int] = mapped_column(Integer)
    benchmark: Mapped[str] = mapped_column(Text)
    results: Mapped[list] = mapped_column(JSONB)
    cases: Mapped[list] = mapped_column(JSONB)


class Replay(Record, Base):
    __tablename__ = "replays"
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), unique=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    step: Mapped[int] = mapped_column(Integer, default=0)
    events: Mapped[list] = mapped_column(JSONB, default=list)


class SourceState(Base):
    __tablename__ = "source_state"
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default="rappelconso")
    last_successful_sync: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceRefresh(Record, Base):
    __tablename__ = "source_refreshes"
    source: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceRejection(Record, Base):
    __tablename__ = "source_rejections"
    refresh_id: Mapped[str] = mapped_column(
        ForeignKey("source_refreshes.id"), index=True
    )
    reason: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB)


class AccessCredential(Record, Base):
    __tablename__ = "access_credentials"
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    store_ids: Mapped[list] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint("role IN ('admin','operator','integration','viewer')"),
    )


class InventoryReceipt(Record, Base):
    __tablename__ = "inventory_receipts"
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(160))
    sequence: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint(
            "store_id", "external_id", "sequence", name="uq_inventory_receipt"
        ),
    )


class RequestBudget(Base):
    __tablename__ = "request_budgets"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    bucket_window: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
