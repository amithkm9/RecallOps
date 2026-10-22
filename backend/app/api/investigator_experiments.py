"""Isolated simulations, comparative evaluation and an explicitly fictional demo."""

from typing import Literal
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.api.routes import demo_allowed, require_incident
from app.core.database import get_db
from app.core.security import require_admin
from app.repositories.records import record
from app.services.investigator_experiments import simulate, simulation_options
from app.services.investigator_evaluation import latest_comparison, run_comparison
from app.schemas.investigator_benchmark import InvestigationDataset

router = APIRouter(tags=["investigator experiments"])


class SimulationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=36)
    evidence_ids: list[str] = Field(max_length=1000)


class ComparisonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_model: bool = False
    include_memory: bool = True
    dataset: InvestigationDataset | None = None


@router.get("/incidents/{incident_id}/investigator/simulation-options")
def options(
    incident_id: str,
    run_id: str | None = Query(None),
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    return simulation_options(
        db, require_incident(db, incident_id, authorization), run_id
    )


@router.post("/incidents/{incident_id}/investigator/simulate")
def simulation(
    incident_id: str,
    body: SimulationIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    return simulate(
        db,
        require_incident(db, incident_id, authorization),
        body.run_id,
        body.evidence_ids,
    )


@router.get("/investigator/evaluation/latest")
def comparison_latest(
    db: Session = Depends(get_db), authorization: str | None = Header(None)
):
    # Results contain synthetic cases only; demo viewers may read recorded results.
    from app.core.security import authorize, identity

    authorize("replay", authorization)
    person = identity(authorization)
    from app.core.config import settings

    local_admin = (
        settings.environment == "development"
        and not settings.operator_token
        and not settings.public_demo
        and not authorization
    )
    result = latest_comparison(
        db, public_only=not (local_admin or (person and person.role == "admin"))
    )
    return record(result) if result else None


@router.post("/investigator/evaluation")
def comparison(
    body: ComparisonIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    require_admin(authorization)
    dataset = (
        body.dataset.model_dump(mode="json", exclude_none=True)
        if body.dataset
        else None
    )
    return record(
        run_comparison(db, body.include_model, body.include_memory, dataset=dataset)
    )


@router.post("/investigator/demo")
def demo(db: Session = Depends(get_db), authorization: str | None = Header(None)):
    demo_allowed(authorization)
    from app.services.investigator_demo import start_investigator_demo

    return start_investigator_demo(db)
