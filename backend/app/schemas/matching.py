from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class Target(BaseModel):
    gtin: str
    lots: list[str] = Field(default_factory=list)
    all_lots: bool = False
    date_start: date | None = None
    date_end: date | None = None
    date_type: str | None = None
    parseable: bool = True
    raw: str = ""
    warning: str | None = None


class Stock(BaseModel):
    id: str = ""
    gtin: str
    lot: str | None = None
    expires_on: date | None = None
    quantity: int = Field(default=1, ge=0)
    product_name: str = ""


class Verification(BaseModel):
    verdict: Literal["affected", "unaffected", "review", "conflict"]
    explanation: str
    matched_gtin: bool = False
    checks: list[str] = Field(default_factory=list)
