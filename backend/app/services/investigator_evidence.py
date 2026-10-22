"""Immutable delivery claims, explicit stock association, and attributed review.

A shared barcode is only a retrieval clue. Neither document extraction nor a previous
case can establish the identity of today's stock. Acceptance is an operator action.
"""

import base64
import csv
import hashlib
import io
import re
from pathlib import PurePath

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    AgentRun,
    Decision,
    DecisionEvidence,
    Event,
    Evidence,
    Incident,
    InventoryLot,
    Recall,
    RecallTarget,
    Store,
)
from app.repositories.records import add_evidence, append_audit_event, enqueue, record
from app.schemas.investigator import AnswerIn, DeliveryRow, ResolveIn, ValidateClaimIn
from app.services.documents import extract_pdf
from app.services.matching import gtin_key

MAX_BYTES = 2_000_000
MAX_ROWS = 500
FIELDS = tuple(DeliveryRow.model_fields)


def _lock(db, incident):
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,2))"),
        {"key": incident.store_id},
    )
    db.scalar(select(Incident).where(Incident.id == incident.id).with_for_update())
    # require_incident may have loaded this instance before waiting on the store
    # lock. Refresh its state so a concurrent close/resolution is not overwritten.
    db.refresh(incident)


def _stock(db, incident, inventory_lot_id):
    stock = db.get(InventoryLot, inventory_lot_id)
    if not stock or stock.store_id != incident.store_id:
        raise HTTPException(404, "Inventory lot is not in this incident's store.")
    recall = db.get(Recall, incident.recall_id)
    target_gtins = db.scalars(
        select(RecallTarget.gtin).where(
            RecallTarget.recall_version_id == recall.current_version_id
        )
    ).all()
    previous = db.scalar(
        select(Decision.id)
        .where(
            Decision.incident_id == incident.id, Decision.inventory_lot_id == stock.id
        )
        .limit(1)
    )
    if not previous and gtin_key(stock.gtin) not in {gtin_key(x) for x in target_gtins}:
        raise HTTPException(
            422, "Choose stock associated with this recall investigation."
        )
    return stock


def _all(db, incident_id, kind):
    return list(
        db.scalars(
            select(Evidence)
            .where(Evidence.incident_id == incident_id, Evidence.kind == kind)
            .order_by(Evidence.created_at, Evidence.id)
        )
    )


def _queue(db, incident, evidence, kind, event_payload=None):
    existing = db.scalar(
        select(Event).where(Event.idempotency_key == f"investigator:{evidence.id}")
    )
    if existing:
        return existing
    recall = db.get(Recall, incident.recall_id)
    incident.review_status, incident.closed_at = "open", None
    return enqueue(
        db,
        f"investigator:{evidence.id}",
        kind,
        incident.id,
        incident.store_id,
        {
            "evidence_id": evidence.id,
            "recall_version_id": recall.current_version_id,
            **(event_payload or {}),
        },
    )


def parse_csv(content):
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV must be UTF-8 encoded.") from exc
    reader = csv.DictReader(io.StringIO(decoded))
    required = set(FIELDS) - {"expires_on"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise HTTPException(
            422,
            "CSV headers required: delivery_id,sku,gtin,lot,quantity,reference; expires_on is optional.",
        )
    claims, errors = [], []
    previous_line = 1
    try:
        for number, values in enumerate(reader, 2):
            first_line, last_line = previous_line + 1, reader.line_num
            previous_line = last_line
            if number > MAX_ROWS + 1:
                raise HTTPException(422, "Maximum 500 delivery rows per import.")
            try:
                if None in values:
                    raise ValueError(
                        "Unexpected extra cells; quote fields containing commas."
                    )
                selected = {key: values.get(key) for key in FIELDS}
                selected["expires_on"] = selected.get("expires_on") or None
                row = DeliveryRow.model_validate(selected)
                # Normalized row excerpt; original bytes are retained in the source document.
                excerpt = ", ".join(f"{key}={values.get(key, '')}" for key in FIELDS)
                claims.append(
                    {
                        **row.model_dump(mode="json"),
                        "locator": (
                            f"CSV row {first_line}"
                            if first_line == last_line
                            else f"CSV lines {first_line}–{last_line}"
                        ),
                        "excerpt": excerpt,
                        "row": first_line,
                    }
                )
            except (ValidationError, ValueError) as exc:
                message = (
                    "; ".join(
                        f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                        for e in exc.errors()
                    )
                    if isinstance(exc, ValidationError)
                    else str(exc)
                )
                errors.append({"row": first_line, "message": message})
    except csv.Error as exc:
        raise HTTPException(422, "Malformed CSV; no document was imported.") from exc
    return claims, errors, "parsed_unverified", []


def parse_pdf(content):
    extracted = extract_pdf(content)
    claims, errors = [], []
    for page in extracted.get("pages", []):
        # Conservative labelled records only. Multiple batch fields on one page
        # remain unresolved instead of pairing unrelated quantities and batches.
        values = {}
        for key in FIELDS:
            matches = re.findall(
                r"^\s*" + re.escape(key) + r"\s*[:=]\s*([^\n\r]+)",
                page["text"],
                flags=re.M | re.I,
            )
            if len(matches) == 1:
                values[key] = matches[0].strip()
        try:
            row = DeliveryRow.model_validate(values)
            claims.append(
                {
                    **row.model_dump(mode="json"),
                    "locator": f"PDF page {page['page']}",
                    "excerpt": page["text"][:15000],
                    "page": page["page"],
                }
            )
        except ValidationError:
            errors.append(
                {
                    "row": None,
                    "message": f"Page {page['page']}: no complete, unambiguous labelled delivery record. Review the original and provide a sourced operator answer.",
                }
            )
    if not extracted.get("pages") or extracted["text_status"] == "needs_ocr":
        errors.append(
            {
                "row": None,
                "message": "Text could not be extracted. Scanned/encrypted or unsupported PDFs need manual review.",
            }
        )
    return claims, errors, extracted["text_status"], extracted.get("pages", [])


def import_delivery(
    db: Session,
    incident: Incident,
    filename: str,
    content: bytes,
    actor: str,
    event_payload: dict | None = None,
):
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(422, "Upload a nonempty CSV or text PDF up to 2 MB.")
    filename = PurePath(filename.replace("\\", "/")).name[:160] or "delivery.csv"
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix not in {"csv", "pdf"} or (
        suffix == "pdf" and not content.startswith(b"%PDF-")
    ):
        raise HTTPException(
            422, "Only UTF-8 CSV and PDF delivery records are supported."
        )
    _lock(db, incident)
    sha = hashlib.sha256(content).hexdigest()
    previous = next(
        (
            d
            for d in _all(db, incident.id, "delivery_document")
            if d.payload.get("sha256") == sha
        ),
        None,
    )
    if previous:
        result = {
            "document_id": previous.id,
            "event_id": None,
            "duplicate": True,
            "claims_count": previous.payload["claim_count"],
            "errors": previous.payload["errors"],
            "text_status": previous.payload["text_status"],
            "message": "These source bytes were already imported; no duplicate evidence or work was created.",
        }
        db.commit()
        return result
    parsed, errors, text_status, pages = (
        parse_csv(content) if suffix == "csv" else parse_pdf(content)
    )
    store = db.get(Store, incident.store_id)
    document = add_evidence(
        db,
        incident.id,
        "delivery_document",
        f"Delivery source · {filename}",
        {
            "filename": filename,
            "media_type": "text/csv" if suffix == "csv" else "application/pdf",
            "sha256": sha,
            "bytes": len(content),
            "content_base64": base64.b64encode(content).decode(),
            "text_status": text_status,
            "pages": pages,
            "errors": errors,
            "claim_count": len(parsed),
            "submitted_by": actor,
            "scope_verified": False,
        },
        synthetic=store.mode != "live",
    )
    for row in parsed:
        add_evidence(
            db,
            incident.id,
            "delivery_claim",
            f"Unconfirmed delivery · {row['delivery_id']}",
            {
                **row,
                "document_id": document.id,
                "extraction_method": (
                    "csv_fields" if suffix == "csv" else "labelled_pdf_text"
                ),
                "association_confirmed": False,
            },
            synthetic=store.mode != "live",
        )
    event = _queue(db, incident, document, "delivery_document_received", event_payload)
    append_audit_event(
        db,
        "delivery_document_imported",
        {
            "document_id": document.id,
            "claim_count": len(parsed),
            "rejected_rows": len(errors),
            "message": "Source retained; extracted claims require explicit stock association.",
        },
        incident.id,
        store.id,
        actor,
    )
    db.commit()
    return {
        "document_id": document.id,
        "event_id": event.id,
        "duplicate": False,
        "claims_count": len(parsed),
        "errors": errors,
        "text_status": text_status,
        "message": "Source saved. Claims are unconfirmed until an operator verifies their association with stock.",
    }


def _claim_views(db, incident):
    stocks = list(
        db.scalars(
            select(InventoryLot).where(InventoryLot.store_id == incident.store_id)
        )
    )
    validations = {}
    for validation in _all(db, incident.id, "claim_validation"):
        validations[validation.payload["claim_id"]] = validation
    result = []
    for evidence in _all(db, incident.id, "delivery_claim"):
        payload = evidence.payload
        validation = validations.get(evidence.id)
        candidates = [
            s.id
            for s in stocks
            if s.sku == payload.get("sku")
            and gtin_key(s.gtin) == gtin_key(payload.get("gtin", ""))
        ]
        result.append(
            {
                **payload,
                "id": evidence.id,
                "status": (
                    ("accepted" if validation.payload["accept"] else "rejected")
                    if validation
                    else "unconfirmed"
                ),
                "inventory_lot_id": validation.inventory_lot_id if validation else None,
                "validation_evidence_id": validation.id if validation else None,
                "candidate_inventory_lot_ids": candidates,
                "validation_reason": (
                    validation.payload["reason"] if validation else None
                ),
                "validated_by": validation.payload["actor"] if validation else None,
            }
        )
    return result


def list_delivery_candidates(
    db: Session, incident_id: str, inventory_lot_id: str
) -> list[dict]:
    incident = db.get(Incident, incident_id)
    if not incident:
        return []
    return [
        c
        for c in _claim_views(db, incident)
        if inventory_lot_id in c["candidate_inventory_lot_ids"]
        or c["inventory_lot_id"] == inventory_lot_id
    ]


def accepted_claims(db: Session, incident_id: str, inventory_lot_id: str) -> list[dict]:
    return [
        c
        for c in list_delivery_candidates(db, incident_id, inventory_lot_id)
        if c["status"] == "accepted" and c["inventory_lot_id"] == inventory_lot_id
    ]


def validate_claim(
    db: Session,
    incident: Incident,
    claim_id: str,
    body: ValidateClaimIn,
    actor: str,
    commit=True,
):
    _lock(db, incident)
    claim = db.get(Evidence, claim_id)
    if not claim or claim.incident_id != incident.id or claim.kind != "delivery_claim":
        raise HTTPException(404, "Delivery claim not found in this incident.")
    stock = _stock(db, incident, body.inventory_lot_id)
    if body.accept and (
        gtin_key(stock.gtin) != gtin_key(claim.payload["gtin"])
        or stock.sku != claim.payload["sku"]
    ):
        raise HTTPException(
            422,
            "The claim's SKU and barcode must match the selected stock. Neither alone proves the delivery association.",
        )
    if body.accept and claim.payload.get("quantity") != stock.quantity:
        raise HTTPException(
            422,
            "Delivery quantity must match the entire selected stock group. Split the inventory or correct the source before confirming a partial shipment.",
        )
    store = db.get(Store, incident.store_id)
    previous = next(
        (
            v
            for v in reversed(_all(db, incident.id, "claim_validation"))
            if v.payload["claim_id"] == claim.id
        ),
        None,
    )
    if (
        not body.accept
        and previous
        and previous.payload["accept"]
        and previous.inventory_lot_id != stock.id
    ):
        raise HTTPException(
            422,
            "Reject this accepted claim against the stock group it is currently associated with.",
        )
    same = (
        previous
        and previous.inventory_lot_id == stock.id
        and previous.payload["accept"] == body.accept
        and previous.payload["reason"] == body.reason
        and previous.payload["actor"] == actor
    )
    validation = (
        previous
        if same
        else add_evidence(
            db,
            incident.id,
            "claim_validation",
            (
                "Operator accepted stock association"
                if body.accept
                else "Operator rejected delivery claim"
            ),
            {
                "claim_id": claim.id,
                "document_id": claim.payload.get("document_id"),
                "accept": body.accept,
                "reason": body.reason,
                "actor": actor,
                "supersedes_validation_id": previous.id if previous else None,
                "association_confirmed": body.accept,
            },
            inventory_lot_id=stock.id,
            synthetic=store.mode != "live",
        )
    )
    event = _queue(db, incident, validation, "delivery_claim_validated")
    if not same:
        append_audit_event(
            db,
            "delivery_claim_validated",
            {
                "evidence_id": validation.id,
                "claim_id": claim.id,
                "inventory_lot_id": stock.id,
                "accept": body.accept,
                "message": body.reason,
            },
            incident.id,
            store.id,
            actor,
        )
        if body.accept:
            document = (
                db.get(Evidence, claim.payload.get("document_id"))
                if claim.payload.get("document_id")
                else None
            )
            add_evidence(
                db,
                incident.id,
                "retrieval_hint",
                "Confirmed delivery retrieval route",
                {
                    "store_id": store.id,
                    "sku": stock.sku,
                    "document_format": (
                        document.payload.get("media_type")
                        if document
                        else "operator_observation"
                    ),
                    "strategy": "search_delivery_records",
                    "claim_id": claim.id,
                    "validation_evidence_id": validation.id,
                    "description": f"Previously located delivery evidence for SKU {stock.sku}. Recheck the current shipment and source; prior stock facts are not reusable.",
                    "facts_reusable": False,
                },
                synthetic=store.mode != "live",
            )
    if commit:
        db.commit()
    return {
        "evidence_id": validation.id,
        "event_id": event.id,
        "message": "Review recorded and reassessment queued. Existing holds are preserved.",
    }


def answer_question(db: Session, incident: Incident, body: AnswerIn, actor: str):
    _lock(db, incident)
    stock = _stock(db, incident, body.inventory_lot_id)
    store = db.get(Store, incident.store_id)
    answer = add_evidence(
        db,
        incident.id,
        "operator_answer",
        "Operator stock observation",
        {
            **body.model_dump(mode="json"),
            "actor": actor,
            "source_type": "operator_observation",
        },
        inventory_lot_id=stock.id,
        synthetic=store.mode != "live",
    )
    claim = add_evidence(
        db,
        incident.id,
        "delivery_claim",
        "Operator-confirmed stock observation",
        {
            "document_id": answer.id,
            "delivery_id": "operator-observation",
            "sku": stock.sku,
            "gtin": stock.gtin,
            "lot": body.lot,
            "quantity": stock.quantity,
            "expires_on": body.expires_on.isoformat() if body.expires_on else None,
            "reference": body.reference,
            "locator": "Operator observation",
            "excerpt": body.reason,
            "extraction_method": "operator_answer",
            "association_confirmed": False,
        },
        synthetic=store.mode != "live",
    )
    return validate_claim(
        db,
        incident,
        claim.id,
        ValidateClaimIn(inventory_lot_id=stock.id, reason=body.reason, accept=True),
        actor,
    )


def resolve_case(db: Session, incident: Incident, body: ResolveIn, actor: str):
    _lock(db, incident)
    if incident.review_status == "closed":
        raise HTTPException(
            409, "Reopen this closed case before recording a new review resolution."
        )
    recall = db.get(Recall, incident.recall_id)
    store = db.get(Store, incident.store_id)
    latest = db.scalar(
        select(AgentRun)
        .where(AgentRun.incident_id == incident.id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    pending = db.scalar(
        select(Event.id)
        .where(
            Event.incident_id == incident.id,
            Event.status.in_(["pending", "processing", "failed"]),
        )
        .limit(1)
    )
    if (
        not latest
        or latest.id != body.expected_run_id
        or (
            store.mode == "live"
            and latest.recall_version_id != recall.current_version_id
        )
        or latest.status != "completed"
        or pending
    ):
        raise HTTPException(
            409,
            "Investigation changed or has unsettled work. Wait for successful reassessment and review the latest run before resolving.",
        )
    ids = list(dict.fromkeys(body.evidence_ids))
    evidence = list(
        db.scalars(
            select(Evidence).where(
                Evidence.id.in_(ids), Evidence.incident_id == incident.id
            )
        )
    )
    if len(evidence) != len(ids):
        raise HTTPException(
            422, "Every cited evidence record must belong to this incident."
        )
    contributing = set(
        db.scalars(
            select(DecisionEvidence.evidence_id)
            .join(Decision, Decision.id == DecisionEvidence.decision_id)
            .where(Decision.run_id == latest.id)
        )
    )
    for claim in _claim_views(db, incident):
        if claim["status"] == "accepted":
            contributing.update([claim["id"], claim["validation_evidence_id"]])
    if not set(ids).issubset(contributing):
        raise HTTPException(
            422,
            "Cite evidence used by the latest decision or explicitly accepted claims/validations.",
        )
    resolution = add_evidence(
        db,
        incident.id,
        "investigation_resolution",
        "Operator review resolution",
        {
            "reason": body.reason,
            "evidence_ids": ids,
            "run_id": latest.id,
            "actor": actor,
            "holds_released": False,
        },
        synthetic=store.mode != "live",
    )
    incident.review_status = "resolved"
    append_audit_event(
        db,
        "investigation_resolved",
        {"evidence_id": resolution.id, "message": body.reason, "holds_released": False},
        incident.id,
        store.id,
        actor,
    )
    db.commit()
    return {
        "evidence_id": resolution.id,
        "event_id": None,
        "message": "Review resolution recorded. Holds remain active and require a separate authorized release.",
    }


def retrieval_hints(db, store_id):
    # Scope through incident ownership; never trust a user-supplied store_id in JSON.
    hints = db.scalars(
        select(Evidence)
        .join(Incident, Incident.id == Evidence.incident_id)
        .where(Incident.store_id == store_id, Evidence.kind == "retrieval_hint")
        .order_by(Evidence.created_at.desc())
        .limit(30)
    )
    return [{"id": h.id, **h.payload} for h in hints]


def overview(db: Session, incident: Incident):
    recall = db.get(Recall, incident.recall_id)
    gtins = {
        gtin_key(g)
        for g in db.scalars(
            select(RecallTarget.gtin).where(
                RecallTarget.recall_version_id == recall.current_version_id
            )
        )
    }
    previous = set(
        db.scalars(
            select(Decision.inventory_lot_id).where(Decision.incident_id == incident.id)
        )
    )
    inventory = [
        record(s)
        for s in db.scalars(
            select(InventoryLot).where(InventoryLot.store_id == incident.store_id)
        )
        if gtin_key(s.gtin) in gtins or s.id in previous
    ]
    claims = _claim_views(db, incident)
    questions = []
    for stock in inventory:
        candidates = [
            c
            for c in claims
            if stock["id"] in c["candidate_inventory_lot_ids"]
            and c["status"] == "unconfirmed"
        ]
        if candidates:
            questions.append(
                {
                    "id": f"association:{stock['id']}",
                    "inventory_lot_id": stock["id"],
                    "question": f"Which delivery record describes these {stock['quantity']} units of {stock['sku']}? Confirm using the shipment reference or physical stock; a matching barcode is insufficient.",
                    "claim_ids": [c["id"] for c in candidates],
                }
            )
        elif not stock["lot"] and not any(
            c["inventory_lot_id"] == stock["id"] and c["status"] == "accepted"
            for c in claims
        ):
            questions.append(
                {
                    "id": f"batch:{stock['id']}",
                    "inventory_lot_id": stock["id"],
                    "question": f"What batch is printed on these {stock['quantity']} units of {stock['sku']}? Provide a physical check or delivery source reference.",
                    "claim_ids": [],
                }
            )
    latest = db.scalar(
        select(AgentRun)
        .where(AgentRun.incident_id == incident.id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    agent_questions = (
        (latest.state or {}).get("investigator", {}).get("questions", [])
        if latest
        else []
    )
    unsettled = db.scalar(
        select(Event.id)
        .where(
            Event.incident_id == incident.id,
            Event.status.in_(["pending", "processing", "failed"]),
        )
        .limit(1)
    )
    if (
        latest
        and latest.status == "completed"
        and not unsettled
        and "investigator" in (latest.state or {})
    ):
        # A remaining alternative document is not an information gap once a
        # completed run resolved this stock with explicitly accepted evidence.
        questions = []
    for question in agent_questions:
        stock_id = question["inventory_lot_id"]
        questions = [q for q in questions if q["inventory_lot_id"] != stock_id]
        questions.append(
            {
                "id": f"{question.get('kind', 'investigation')}:{stock_id}",
                "inventory_lot_id": stock_id,
                "question": question.get(
                    "prompt", "Review the unresolved stock information."
                ),
                "claim_ids": question.get("candidate_claim_ids", []),
                "kind": question.get("kind", "investigation"),
                "fields": question.get("fields", []),
            }
        )
    documents = [
        {
            "id": d.id,
            **{
                k: d.payload[k]
                for k in (
                    "filename",
                    "media_type",
                    "sha256",
                    "bytes",
                    "text_status",
                    "claim_count",
                )
            },
            "created_at": d.created_at.isoformat(),
            "errors": d.payload.get("errors", []),
        }
        for d in _all(db, incident.id, "delivery_document")
    ]
    return {
        "documents": documents,
        "claims": claims,
        "inventory": inventory,
        "questions": questions,
        "resolutions": [
            {"id": r.id, **r.payload, "created_at": r.created_at.isoformat()}
            for r in _all(db, incident.id, "investigation_resolution")
        ],
        "review_status": incident.review_status,
        "reassessment_pending": bool(unsettled),
        "retrieval_hints": retrieval_hints(db, incident.store_id),
        "latest_run": (
            {
                "id": latest.id,
                "status": latest.status,
                "summary": latest.summary,
                "latency_ms": latest.latency_ms,
            }
            if latest
            else None
        ),
        "investigator": latest.state.get("investigator", {}) if latest else {},
        "effective_inventory": (
            latest.state.get("effective_inventory", []) if latest else []
        ),
        "limitations": [
            "Delivery association requires explicit operator confirmation; barcode matches are retrieval clues.",
            "PDF extraction supports labelled text records; scans and ambiguous layouts require review.",
            "Review resolution does not release holds or modify checkout systems.",
            "Retrieval memory suggests where to search; previous batch facts never establish today's stock identity.",
        ],
    }
