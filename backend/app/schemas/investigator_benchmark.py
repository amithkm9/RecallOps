"""Bounded external-label intake. Label independence is declared, never certified."""

from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ClaimFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lot: str = Field(min_length=1, max_length=300)
    expires_on: date | None = None
    accepted: bool = False
    excerpt: str | None = Field(default=None, max_length=2000)


class InvestigationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    lot: str | None = Field(default=None, max_length=300)
    scope: str = Field(default="3760099533007$A1$non concerné$$", max_length=3000)
    supplier_lot: str | None = Field(default=None, max_length=300)
    claims: list[ClaimFixture] = Field(default_factory=list, max_length=10)
    expected: Literal["affected", "unaffected", "review", "conflict"]
    split: Literal["development", "held_out"] = "held_out"


class InvestigationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=3, max_length=500)
    labeler: str = Field(min_length=3, max_length=200)
    independent_review_declared: bool = False
    cases: list[InvestigationCase] = Field(min_length=1, max_length=100)
