"""External labels are supplied before predictions; provenance is a declaration."""

from typing import Literal
from datetime import date
from pydantic import BaseModel, Field, ConfigDict
from app.services.inventory import InventoryRow


class LabeledCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    scope: str = Field(max_length=5000)
    gtin: str = Field(pattern=r"^(?:[0-9]{8}|[0-9]{12,14})$")
    lot: str | None = Field(default=None, max_length=300)
    expires_on: date | None = None
    fallback_gtin: str | None = None
    supplier_lot: str | None = Field(default=None, max_length=300)
    expected: Literal["affected", "unaffected", "review", "conflict"]
    product_name: str = Field(min_length=1, max_length=500)
    recall_name: str = Field(min_length=1, max_length=500)


class LabeledBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=5, max_length=500)
    labeler: str = Field(min_length=2, max_length=200)
    split: Literal["development", "held_out"]
    cases: list[LabeledCase] = Field(min_length=2, max_length=200)
