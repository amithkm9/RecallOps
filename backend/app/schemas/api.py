from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Entity(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str


class RecallOut(Entity):
    source_id: str
    product_name: str
    source_url: str
    published_at: str
    ingested_at: str
    version_id: str
    official_version: str
    raw: dict[str, Any]


class InventoryOut(Entity):
    store_id: str
    sku: str
    product_name: str
    gtin: str
    lot: str | None
    quantity: int
    supplier: str
    expires_on: str | None
    status: str


class IncidentOut(Entity):
    status: str
    product_name: str
    reference: str
    store_name: str
    affected_quantity: int
    updated_at: str
    published_at: str
    mode: str
    recall_id: str


class InventoryList(BaseModel):
    items: list[InventoryOut]
    total: int


class IncidentList(BaseModel):
    items: list[IncidentOut]


class DetailOut(BaseModel):
    incident: IncidentOut
    recall: RecallOut
    inventory: list[InventoryOut]
    evidence: list[Entity]
    targets: list[Entity]
    decisions: list[Entity]
    holds: list[Entity]
    runs: list[Entity]
    history: list[Entity]


class SettingsOut(BaseModel):
    llm_enabled: bool
    llm_model: str
    auth_required: bool
    demo_enabled: bool
    last_successful_sync: str | None
    last_sync_error: str | None
    coverage: str
    dataset_url: str
    mode: str
    source_count: int
    refresh_interval_seconds: int


class DashboardOut(BaseModel):
    active_incidents: int
    affected_units: int
    awaiting_review: int
    completed_actions: int
    inventory_units: int
    recall_count: int
    latest_incidents: list[IncidentOut]
    activity: list[Entity]
    settings: SettingsOut
    outcomes: list[dict[str, Any]]


class ReplayOut(Entity):
    step: int
    incident_id: str
    events: list[dict[str, Any]]
    detail: DetailOut


class EvaluationOut(Entity):
    created_at: str
    sample_size: int
    benchmark: str
    results: list[dict[str, Any]]
    cases: list[dict[str, Any]]


class SyncIn(BaseModel):
    source: Literal["live", "snapshot"] = "live"
    start_offset: int = Field(default=0, ge=0, le=9900, multiple_of=100)


class ReviewIn(BaseModel):
    action: Literal["acknowledge", "release_hold", "assign", "close", "reopen"]
    hold_id: str | None = None
    reason: str = Field(min_length=10, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    expected_run_id: str | None = None


class ReplayNextIn(BaseModel):
    replay_id: str
    expected_step: int = Field(ge=0, le=2)


class InvestigateIn(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=100)


class SupplierEvidenceIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    inventory_lot_id: str = Field(min_length=1, max_length=100)
    supplier: str = Field(min_length=2, max_length=200)
    lot: str = Field(min_length=1, max_length=300)
    reference: str = Field(min_length=3, max_length=200)
    notes: str = Field(min_length=10, max_length=2000)
    source_url: HttpUrl | None = None
    supersedes_evidence_id: str | None = Field(default=None, max_length=36)


class SupplierEvidenceOut(BaseModel):
    evidence_id: str
    event_id: str
    event_status: str
    message: str


class ModelCheckOut(BaseModel):
    success: bool
    mode: str
    model: str
    latency_ms: float | None
    checked_at: str
    message: str
    http_status: int | None
    provider: dict[str, Any] | None


class SyncOut(BaseModel):
    refresh_id: str | None = None
    created: int
    skipped: int
    errors: list[str]
    origin: str
    message: str


class ImportOut(BaseModel):
    imported: int
    errors: list[dict[str, Any]]


class MessageOut(BaseModel):
    message: str


class EventOut(Entity):
    status: str
    kind: str


class HealthOut(BaseModel):
    status: str
    database: str
    api_version: str
