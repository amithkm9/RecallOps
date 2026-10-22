"""Explicit, bounded input contracts for operator-confirmed investigation evidence."""

from datetime import date
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class DeliveryRow(Input):
    delivery_id: str = Field(min_length=1, max_length=160)
    sku: str = Field(min_length=1, max_length=120)
    gtin: str = Field(pattern=r"^(?:[0-9]{8}|[0-9]{12,14})$")
    lot: str = Field(min_length=1, max_length=300)
    quantity: int = Field(gt=0, le=100000000)
    expires_on: date | None = None
    reference: str = Field(min_length=1, max_length=500)


class ValidateClaimIn(Input):
    inventory_lot_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=10, max_length=2000)
    accept: bool


class ResolveIn(Input):
    expected_run_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=10, max_length=4000)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)


class AnswerIn(Input):
    inventory_lot_id: str = Field(min_length=1, max_length=36)
    lot: str = Field(min_length=1, max_length=300)
    expires_on: date | None = None
    reference: str = Field(min_length=3, max_length=500)
    reason: str = Field(min_length=10, max_length=2000)


class EvidenceMutationOut(BaseModel):
    evidence_id: str
    event_id: str | None = None
    message: str


class ImportErrorOut(BaseModel):
    row: int | None = None
    message: str


class DeliveryImportOut(BaseModel):
    document_id: str
    event_id: str | None = None
    duplicate: bool
    claims_count: int
    errors: list[ImportErrorOut]
    text_status: str
    message: str
