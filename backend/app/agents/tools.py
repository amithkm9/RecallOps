"""Validated, store-scoped investigation tools with a durable execution trace."""

from time import perf_counter
from typing import Any, Callable
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import (
    AgentRun,
    Decision,
    DecisionEvidence,
    Evidence,
    Incident,
    InventoryHold,
    InventoryLot,
    Recall,
    RecallTarget,
    RecallVersion,
    utcnow,
)
from app.repositories.records import append_audit_event, jsonable, record
from app.schemas.matching import Stock, Target
from app.services.matching import check_lot_constraints, gtin_key


class ToolInput(BaseModel):
    incident_id: str = Field(min_length=1)
    inventory_lot_id: str | None = None
    gtin: str | None = None
    decision_id: str | None = None


class ToolOutput(BaseModel):
    tool: str
    data: Any


class InvestigationTools:
    def __init__(self, db: Session, incident: Incident, run: AgentRun):
        self.db, self.incident, self.run = db, incident, run
        self.use_delivery_claims = True
        self.retrieved_claims = {}
        self.retrieval_hints = {}

    def call(self, name: str, node: str, **arguments) -> Any:
        args = ToolInput(incident_id=self.incident.id, **arguments)
        if args.incident_id != self.incident.id:
            raise PermissionError("Incident scope mismatch.")
        if args.inventory_lot_id:
            lot = self.db.get(InventoryLot, args.inventory_lot_id)
            if not lot or lot.store_id != self.incident.store_id:
                raise PermissionError("Inventory is outside the authorized store.")
        allowed = {
            "get_recall",
            "search_delivery_records",
            "get_retrieval_hints",
            "compare_recall_versions",
            "inspect_official_documents",
            "get_recall_version",
            "search_inventory_by_gtin",
            "get_inventory_lots",
            "get_supplier_evidence",
            "get_previous_decisions",
            "check_lot_constraints",
            "create_inventory_hold",
            "request_human_review",
            "prepare_supplier_notification",
            "append_audit_event",
        }
        if name not in allowed:
            raise PermissionError("Tool is not permitted.")
        start = perf_counter()
        output = ToolOutput(tool=name, data=getattr(self, name)(args))
        step = {
            "node": node,
            "tool": name,
            "input": args.model_dump(),
            "output": jsonable(output.data),
            "timestamp": utcnow().isoformat(),
            "latency_ms": round((perf_counter() - start) * 1000, 3),
        }
        self.run.steps = [*self.run.steps, step]
        self.db.flush()
        return output.data

    def get_recall(self, args: ToolInput):
        return record(self.db.get(Recall, self.incident.recall_id))

    def get_recall_version(self, args: ToolInput):
        version = self.db.get(RecallVersion, self.run.recall_version_id)
        return {
            **record(version),
            "targets": [
                r.scope
                for r in self.db.scalars(
                    select(RecallTarget).where(
                        RecallTarget.recall_version_id == version.id
                    )
                )
            ],
        }

    def search_inventory_by_gtin(self, args: ToolInput):
        lots = self.db.scalars(
            select(InventoryLot).where(InventoryLot.store_id == self.incident.store_id)
        ).all()
        return [
            record(i) for i in lots if gtin_key(i.gtin) == gtin_key(args.gtin or "")
        ]

    def get_inventory_lots(self, args: ToolInput):
        return [
            record(i)
            for i in self.db.scalars(
                select(InventoryLot).where(
                    InventoryLot.store_id == self.incident.store_id
                )
            )
        ]

    def get_supplier_evidence(self, args: ToolInput):
        query = select(Evidence).where(
            Evidence.incident_id == self.incident.id, Evidence.kind == "supplier"
        )
        if args.inventory_lot_id:
            query = query.where(Evidence.inventory_lot_id == args.inventory_lot_id)
        return [record(e) for e in self.db.scalars(query.order_by(Evidence.created_at))]

    def get_previous_decisions(self, args: ToolInput):
        return [
            record(d)
            for d in self.db.scalars(
                select(Decision)
                .where(
                    Decision.incident_id == self.incident.id,
                    Decision.run_id != self.run.id,
                )
                .order_by(Decision.created_at)
            )
        ]

    def check_lot_constraints(self, args: ToolInput):
        stock = self.db.get(InventoryLot, args.inventory_lot_id)
        version = self.db.get(RecallVersion, self.run.recall_version_id)
        targets = [
            Target.model_validate(t.scope)
            for t in self.db.scalars(
                select(RecallTarget).where(RecallTarget.recall_version_id == version.id)
            )
        ]
        suppliers = self.db.scalars(
            select(Evidence).where(
                Evidence.incident_id == self.incident.id,
                Evidence.inventory_lot_id == stock.id,
                Evidence.kind == "supplier",
            )
        ).all()
        superseded = {e.payload.get("supersedes_evidence_id") for e in suppliers}
        suppliers = [e for e in suppliers if e.id not in superseded]
        incomplete = any(
            w.startswith("Unrecognized GTIN") or w.startswith("No usable")
            for w in version.parse_warnings
        )
        # Attached text is supplementary, not a replacement for structured scope.
        # References such as "voir liste" already remain unparseable/reviewable.
        from app.agents.investigator import verify_with_claims

        if not self.use_delivery_claims:
            # Preserve the pre-investigator baseline, including its original
            # supplier handling. New capabilities must not inflate the baseline.
            result = check_lot_constraints(
                Stock.model_validate(record(stock)),
                targets,
                [str(e.payload["lot"]) for e in suppliers if e.payload.get("lot")],
                incomplete,
            ).model_dump()
            return {
                **result,
                "effective_stock": record(stock),
                "evidence_ids": [],
                "used_claim_ids": [],
                "accepted_claims": [],
            }
        claims = self.retrieved_claims.get(stock.id, [])
        result = verify_with_claims(
            record(stock),
            [t.model_dump(mode="json") for t in targets],
            [str(e.payload["lot"]) for e in suppliers if e.payload.get("lot")],
            claims,
            incomplete,
        )
        # Metadata signals available evidence without reading its batch/date facts.
        # A complete warehouse row still needs retrieval when validated evidence changes.
        result["pending_delivery_check"] = bool(
            self.use_delivery_claims
            and stock.id not in self.retrieved_claims
            and self.db.scalar(
                select(Evidence.id)
                .where(
                    Evidence.incident_id == self.incident.id,
                    Evidence.inventory_lot_id == stock.id,
                    Evidence.kind == "claim_validation",
                )
                .limit(1)
            )
        )
        result["source_scope_incomplete"] = incomplete or any(
            not t.parseable and gtin_key(t.gtin) == gtin_key(stock.gtin)
            for t in targets
        )
        if result["pending_delivery_check"] and result["verdict"] != "conflict":
            result["verdict"] = "review"
            result["explanation"] = (
                "Validated delivery evidence is available and must be retrieved before concluding."
            )
        return result

    def search_delivery_records(self, args: ToolInput):
        from app.services.investigator_evidence import list_delivery_candidates

        rows = list_delivery_candidates(
            self.db, self.incident.id, args.inventory_lot_id
        )
        formats = {
            h.get("document_format")
            for h in self.retrieval_hints.get(args.inventory_lot_id, [])
        }

        def preferred(claim):
            document = (
                self.db.get(Evidence, claim.get("document_id"))
                if claim.get("document_id")
                else None
            )
            return bool(document and document.payload.get("media_type") in formats)

        if formats:
            rows.sort(key=preferred, reverse=True)
        self.retrieved_claims[args.inventory_lot_id] = rows
        return rows

    def get_retrieval_hints(self, args: ToolInput):
        stock = self.db.get(InventoryLot, args.inventory_lot_id)
        rows = self.db.scalars(
            select(Evidence)
            .join(Incident, Evidence.incident_id == Incident.id)
            .where(
                Incident.store_id == self.incident.store_id,
                Evidence.kind == "retrieval_hint",
            )
            .order_by(Evidence.created_at.desc())
            .limit(50)
        )
        hints = []
        for evidence in rows:
            payload = evidence.payload
            validation = (
                self.db.get(Evidence, payload.get("validation_evidence_id"))
                if payload.get("validation_evidence_id")
                else None
            )
            if (
                not validation
                or validation.kind != "claim_validation"
                or not validation.payload.get("accept")
            ):
                continue
            latest_validation = self.db.scalar(
                select(Evidence)
                .where(
                    Evidence.incident_id == validation.incident_id,
                    Evidence.kind == "claim_validation",
                    Evidence.payload["claim_id"].astext
                    == validation.payload.get("claim_id"),
                )
                .order_by(Evidence.created_at.desc(), Evidence.id.desc())
                .limit(1)
            )
            if not latest_validation or latest_validation.id != validation.id:
                continue
            validation_incident = self.db.get(Incident, validation.incident_id)
            if validation_incident.store_id != self.incident.store_id:
                continue
            if payload.get("sku") and payload["sku"] != stock.sku:
                continue
            hints.append(
                {
                    "id": evidence.id,
                    "strategy": "search_delivery_records",
                    "document_format": payload.get("document_format"),
                    "reference_pattern": payload.get("reference_pattern"),
                    "message": "Previously confirmed source format; revalidate current shipment association.",
                    "operational_fact": False,
                }
            )
        self.retrieval_hints[args.inventory_lot_id] = hints
        return hints

    def compare_recall_versions(self, args: ToolInput):
        pinned = self.db.get(RecallVersion, self.run.recall_version_id)
        previous = self.db.scalar(
            select(RecallVersion)
            .where(
                RecallVersion.recall_id == pinned.recall_id,
                RecallVersion.id != pinned.id,
                RecallVersion.created_at <= pinned.created_at,
            )
            .order_by(RecallVersion.created_at.desc())
            .limit(1)
        )
        records = []
        for version in (previous, pinned):
            if not version:
                continue
            evidence = self.db.scalar(
                select(Evidence)
                .where(
                    Evidence.incident_id == self.incident.id,
                    Evidence.recall_version_id == version.id,
                    Evidence.kind.in_(["official", "benchmark"]),
                )
                .order_by(Evidence.created_at.desc())
                .limit(1)
            )
            records.append(
                {
                    "id": evidence.id if evidence else None,
                    "recall_version_id": version.id,
                    "official_version": version.official_version,
                    "role": "pinned" if version.id == pinned.id else "previous",
                    "source_url": version.source_url,
                    "parse_warnings": version.parse_warnings,
                    "targets": [
                        t.scope
                        for t in self.db.scalars(
                            select(RecallTarget).where(
                                RecallTarget.recall_version_id == version.id
                            )
                        )
                    ],
                    "operational_scope": version.id == pinned.id,
                }
            )
        return records

    def inspect_official_documents(self, args: ToolInput):
        # Existing fetched attachments only: no arbitrary URL, network or source replacement.
        documents = self.db.scalars(
            select(Evidence)
            .where(
                Evidence.incident_id == self.incident.id,
                Evidence.recall_version_id == self.run.recall_version_id,
                Evidence.kind == "official_document",
            )
            .order_by(Evidence.created_at.desc())
            .limit(10)
        )
        return [
            {
                "id": e.id,
                "source_url": e.source_url,
                "recall_version_id": e.recall_version_id,
                "text_status": e.payload.get("text_status"),
                "pages": [
                    {"page": p.get("page"), "text": str(p.get("text", ""))[:4000]}
                    for p in e.payload.get("pages", [])[:10]
                ],
                "scope_verified": False,
                "message": "Supplementary source text needs human interpretation; it cannot replace the pinned structured scope.",
            }
            for e in documents
        ]

    def persist_investigation_progress(self, progress: dict):
        # The event/store session locks outlive this commit. Retrying a crashed run
        # replays read-only retrieval; decisions and holds remain separately idempotent.
        self.run.state = {**self.run.state, **jsonable(progress)}
        append_audit_event(
            self.db,
            "investigator_progress",
            {
                "run_id": self.run.id,
                "message": "Evidence retrieval completed",
                "completed_tools": len(progress["investigator"]["steps"]),
            },
            self.incident.id,
            self.incident.store_id,
        )
        self.db.commit()

    def create_inventory_hold(self, args: ToolInput):
        decision = self.db.get(Decision, args.decision_id)
        if (
            not decision
            or decision.incident_id != self.incident.id
            or decision.inventory_lot_id != args.inventory_lot_id
            or decision.verdict != "affected"
        ):
            raise PermissionError(
                "Only an evidence-backed affected decision may create a hold."
            )
        existing = self.db.scalar(
            select(InventoryHold).where(
                InventoryHold.incident_id == self.incident.id,
                InventoryHold.inventory_lot_id == args.inventory_lot_id,
                InventoryHold.status == "active",
            )
        )
        if existing:
            existing.quantity = max(existing.quantity, decision.quantity)
            return {
                "hold_id": existing.id,
                "quantity": existing.quantity,
                "result": "existing_hold_preserved",
            }
        if decision.quantity == 0:
            return {"result": "no_stock_to_hold"}
        hold = InventoryHold(
            incident_id=self.incident.id,
            inventory_lot_id=args.inventory_lot_id,
            decision_id=decision.id,
            quantity=decision.quantity,
        )
        self.db.add(hold)
        self.db.flush()
        append_audit_event(
            self.db,
            "inventory_hold_created",
            {
                "message": f"Internal hold created for {hold.quantity} units. No POS action.",
                "hold_id": hold.id,
                "quantity": hold.quantity,
            },
            self.incident.id,
            self.incident.store_id,
        )
        return {
            "hold_id": hold.id,
            "quantity": hold.quantity,
            "result": "internal_hold_created",
        }

    def request_human_review(self, args: ToolInput):
        append_audit_event(
            self.db,
            "human_review_requested",
            {
                "message": "Review missing or contradictory lot evidence. Existing holds remain active.",
                "inventory_lot_id": args.inventory_lot_id,
            },
            self.incident.id,
            self.incident.store_id,
        )
        return {"result": "review_requested", "external_notification_sent": False}

    def prepare_supplier_notification(self, args: ToolInput):
        version = self.db.get(RecallVersion, self.run.recall_version_id)
        decisions = self.db.scalars(
            select(Decision).where(Decision.run_id == self.run.id)
        ).all()
        lines = [
            f"DRAFT — Supplier verification request: {version.product_name}",
            f"Official source: {version.source_url}",
            f"Recall version: {version.official_version}",
        ]
        for decision in decisions:
            hold = self.db.scalar(
                select(InventoryHold).where(
                    InventoryHold.incident_id == self.incident.id,
                    InventoryHold.inventory_lot_id == decision.inventory_lot_id,
                    InventoryHold.status == "active",
                )
            )
            citations = list(
                self.db.scalars(
                    select(DecisionEvidence.evidence_id).where(
                        DecisionEvidence.decision_id == decision.id
                    )
                )
            )
            hold_state = (
                f"Active internal hold: {hold.quantity} units."
                if hold
                else "No active internal hold is recorded."
            )
            lines.append(
                f"Lot {decision.lot or 'unknown'}: {decision.quantity} units; {decision.verdict}. {decision.explanation} {hold_state} Evidence: {', '.join(citations)}."
            )
        active_holds = self.db.scalars(
            select(InventoryHold).where(
                InventoryHold.incident_id == self.incident.id,
                InventoryHold.status == "active",
            )
        ).all()
        lines.append(
            f"Active internal holds at the time of this draft: {sum(h.quantity for h in active_holds)} units."
            if active_holds
            else "No internal hold is currently recorded for this incident."
        )
        lines.append(
            "Please provide traceable batch and delivery documentation. Existing holds can only be released by an authorized operator. This draft has not been sent."
        )
        return {"draft": "\n".join(lines), "sent": False}

    def append_audit_event(self, args: ToolInput):
        row = append_audit_event(
            self.db,
            "investigation_completed",
            {
                "message": "Evidence, decisions and permitted internal actions persisted.",
                "run_id": self.run.id,
            },
            self.incident.id,
            self.incident.store_id,
        )
        return {"audit_id": row.id}
