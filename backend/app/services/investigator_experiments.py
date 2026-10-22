"""Frozen evidence experiments. No operational write occurs during simulation."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.investigator import verify_with_claims
from app.models import (
    AgentRun,
    Decision,
    DecisionEvidence,
    Evidence,
    Incident,
    RecallTarget,
)


def _frozen(db: Session, incident: Incident, run_id: str | None):
    run = (
        db.get(AgentRun, run_id)
        if run_id
        else db.scalar(
            select(AgentRun)
            .where(AgentRun.incident_id == incident.id, AgentRun.status == "completed")
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
    )
    if not run or run.incident_id != incident.id or run.status != "completed":
        raise HTTPException(404, "Choose a completed investigation from this incident.")
    decisions = list(db.scalars(select(Decision).where(Decision.run_id == run.id)))
    linked = set(
        db.scalars(
            select(DecisionEvidence.evidence_id)
            .join(Decision)
            .where(Decision.run_id == run.id)
        )
    )
    investigator = run.state.get("investigator", {})
    available = linked | set(investigator.get("available_evidence_ids", []))
    # Only this incident's persisted evidence is selectable. Other cases may
    # supply search hints, never facts in a counterfactual stock decision.
    evidence = {
        e.id: e
        for e in db.scalars(
            select(Evidence).where(
                Evidence.incident_id == incident.id, Evidence.id.in_(available)
            )
        )
    }
    return run, decisions, linked, investigator, evidence


def simulation_options(db: Session, incident: Incident, run_id: str | None):
    run, decisions, linked, investigator, evidence = _frozen(db, incident, run_id)
    dependencies = {}
    for claims in investigator.get("claims_by_inventory", {}).values():
        for c in claims:
            dependencies[c["id"]] = [
                i
                for i in (c.get("document_id"), c.get("validation_evidence_id"))
                if i in evidence
            ]
    return {
        "run_id": run.id,
        "recall_version_id": run.recall_version_id,
        "evidence": [
            {
                "id": e.id,
                "kind": e.kind,
                "label": e.label,
                "inventory_lot_id": e.inventory_lot_id,
                "required_ids": dependencies.get(e.id, []),
                "fixed": e.kind in {"official", "benchmark", "inventory"},
            }
            for e in evidence.values()
        ],
        "default_evidence_ids": sorted(evidence),
        "limitations": [
            "The recall version and original warehouse inventory are frozen. Toggle supplementary evidence only."
        ],
    }


def simulate(db: Session, incident: Incident, run_id: str, evidence_ids: list[str]):
    run, decisions, linked, investigator, evidence = _frozen(db, incident, run_id)
    selected = set(evidence_ids)
    if not selected.issubset(evidence):
        raise HTTPException(
            422, "Select only evidence available in this frozen investigation."
        )
    targets = [
        t.scope
        for t in db.scalars(
            select(RecallTarget).where(
                RecallTarget.recall_version_id == run.recall_version_id
            )
        )
    ]
    recall = run.state.get("recall", {})
    results = []
    before = {d.inventory_lot_id: d for d in decisions}
    for stock in run.state.get("inventory", []):
        claims = []
        for claim in investigator.get("claims_by_inventory", {}).get(stock["id"], []):
            required = {
                i
                for i in (
                    claim.get("id"),
                    claim.get("document_id"),
                    claim.get("validation_evidence_id"),
                )
                if i
            }
            if required.issubset(selected):
                claims.append(claim)
        suppliers = [
            e
            for eid, e in evidence.items()
            if eid in selected
            and e.kind == "supplier"
            and e.inventory_lot_id == stock["id"]
        ]
        superseded = {e.payload.get("supersedes_evidence_id") for e in suppliers}
        supplier_lots = [
            e.payload["lot"]
            for e in suppliers
            if e.id not in superseded and e.payload.get("lot")
        ]
        incomplete = any(
            w.startswith("Unrecognized GTIN") or w.startswith("No usable")
            for w in recall.get("parse_warnings", [])
        )
        verification = verify_with_claims(
            stock, targets, supplier_lots, claims, incomplete
        )
        if investigator.get("strategy") == "baseline":
            from app.schemas.matching import Stock, Target
            from app.services.matching import check_lot_constraints

            verification = {
                **check_lot_constraints(
                    Stock.model_validate(stock),
                    [Target.model_validate(t) for t in targets],
                    supplier_lots,
                    incomplete,
                ).model_dump(),
                "used_claim_ids": [],
            }
        previous = before.get(stock["id"])
        verdict = verification["verdict"]
        results.append(
            {
                "inventory_lot_id": stock["id"],
                "quantity": stock["quantity"],
                "verdict": verdict,
                "explanation": verification["explanation"],
                "previous_verdict": previous.verdict if previous else None,
                "changed": previous is None or previous.verdict != verdict,
                "action": "simulation_only",
                "used_claim_ids": verification["used_claim_ids"],
            }
        )
    return {
        "run_id": run.id,
        "recall_version_id": run.recall_version_id,
        "decisions": results,
        "changed_count": sum(r["changed"] for r in results),
        "read_only": True,
        "limitations": [
            "This experiment creates no decisions, events, or holds and releases no stock.",
            "Recall scope and warehouse stock are frozen to the selected run; this is an evidence comparison, not causal proof.",
            "A delivery claim is used only when its source and its recorded operator validation are selected.",
        ],
    }
