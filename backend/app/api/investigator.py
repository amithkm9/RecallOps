"""Operator evidence intake and read-only investigation views."""

import base64

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import actor_name, authorize, identity
from app.models import Evidence
from app.schemas.investigator import (
    AnswerIn,
    DeliveryImportOut,
    EvidenceMutationOut,
    ResolveIn,
    ValidateClaimIn,
)
from app.services import investigator_evidence as service

router = APIRouter(
    prefix="/incidents/{incident_id}/investigator", tags=["investigator"]
)


def _incident(db, incident_id, authorization):
    from app.api.routes import require_incident

    return require_incident(db, incident_id, authorization)


def _import_access(authorization):
    from app.core.config import settings

    person = identity(authorization)
    if person and person.role not in {"admin", "operator"}:
        raise HTTPException(403, "Evidence import requires operator access.")
    if (
        settings.public_demo
        or settings.environment != "development"
        or settings.operator_token
    ):
        authorize(authorization=authorization, strict=True)


@router.get("")
def get_overview(
    incident_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    return service.overview(db, _incident(db, incident_id, authorization))


@router.post("/deliveries", response_model=DeliveryImportOut, status_code=202)
async def delivery(
    incident_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    incident = _incident(db, incident_id, authorization)
    _import_access(authorization)
    content = await file.read(service.MAX_BYTES + 1)
    return service.import_delivery(
        db,
        incident,
        file.filename or "delivery.csv",
        content,
        actor_name(authorization),
    )


@router.post(
    "/claims/{claim_id}/validate", response_model=EvidenceMutationOut, status_code=202
)
def validation(
    incident_id: str,
    claim_id: str,
    body: ValidateClaimIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    incident = _incident(db, incident_id, authorization)
    authorize(authorization=authorization, strict=True)
    return service.validate_claim(
        db, incident, claim_id, body, actor_name(authorization)
    )


@router.post("/answers", response_model=EvidenceMutationOut, status_code=202)
def answer(
    incident_id: str,
    body: AnswerIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    incident = _incident(db, incident_id, authorization)
    authorize(authorization=authorization, strict=True)
    return service.answer_question(db, incident, body, actor_name(authorization))


@router.post("/resolve", response_model=EvidenceMutationOut)
def resolve(
    incident_id: str,
    body: ResolveIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    incident = _incident(db, incident_id, authorization)
    authorize(authorization=authorization, strict=True)
    return service.resolve_case(db, incident, body, actor_name(authorization))


@router.get("/documents/{evidence_id}")
def download(
    incident_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    _incident(db, incident_id, authorization)
    evidence = db.get(Evidence, evidence_id)
    if (
        not evidence
        or evidence.incident_id != incident_id
        or evidence.kind != "delivery_document"
    ):
        raise HTTPException(404, "Delivery document not found in this incident.")
    extension = "pdf" if evidence.payload["media_type"] == "application/pdf" else "csv"
    return Response(
        base64.b64decode(evidence.payload["content_base64"]),
        media_type=evidence.payload["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="delivery-{evidence.id}.{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
