from time import perf_counter
from typing import TypedDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from langgraph.graph import END, START, StateGraph
from app.agents.investigator import run_investigator
from app.agents.tools import InvestigationTools
from app.models import (
    AgentRun,
    Decision,
    DecisionEvidence,
    Event,
    Evidence,
    Incident,
    InventoryHold,
    Recall,
    Store,
    utcnow,
)
from app.repositories.records import add_evidence, append_audit_event


class InvestigationState(TypedDict, total=False):
    event_id: str
    recall: dict
    inventory: list[dict]
    evidence_ids: list[str]
    previous: list[dict]
    verifications: dict[str, dict]
    plan: dict
    needs_investigation: bool
    decisions: list[str]
    investigator: dict
    effective_inventory: list[dict]


def investigate(db: Session, event: Event) -> AgentRun:
    incident = db.get(Incident, event.incident_id)
    recall = db.get(Recall, incident.recall_id)
    run = db.scalar(select(AgentRun).where(AgentRun.event_id == event.id))
    if run and run.status == "completed":
        return run
    if not run:
        run = AgentRun(
            incident_id=incident.id,
            event_id=event.id,
            recall_version_id=event.payload.get("recall_version_id")
            or recall.current_version_id,
        )
        db.add(run)
        db.flush()
    strategy = event.payload.get("investigation_strategy", "adaptive")
    if strategy not in {"baseline", "fixed", "adaptive"}:
        raise ValueError("Unknown investigation strategy")
    tools = InvestigationTools(db, incident, run)
    tools.use_delivery_claims = strategy != "baseline"
    start = perf_counter()
    store = db.get(Store, incident.store_id)

    def wrap(name, fn):
        def node(state):
            run.active_node = name
            result = fn(state)
            state_after = {**state, **result}
            run.state = state_after
            append_audit_event(
                db,
                "workflow_transition",
                {"message": name.replace("_", " "), "node": name, "run_id": run.id},
                incident.id,
                incident.store_id,
            )
            db.commit()
            return result

        return node

    def detect(state):
        if incident.review_status in {"closed", "resolved"}:
            append_audit_event(
                db,
                "closed_case_reopened",
                {
                    "event_id": event.id,
                    "message": "New evidence reopens the closed review.",
                },
                incident.id,
                incident.store_id,
            )
        incident.review_status = "open"
        incident.closed_at = None
        incident.status = "investigating"
        append_audit_event(
            db,
            "investigation_reopened" if run.steps else "event_detected",
            {"message": event.kind.replace("_", " "), "event_id": event.id},
            incident.id,
            incident.store_id,
        )
        return {"event_id": event.id}

    def load(state):
        tools.call("get_recall", "load_recall_inventory")
        version = tools.call("get_recall_version", "load_recall_inventory")
        inventory = {}
        for target in version["targets"]:
            for lot in tools.call(
                "search_inventory_by_gtin", "load_recall_inventory", gtin=target["gtin"]
            ):
                inventory[lot["id"]] = lot
        # Previously held lots must remain visible even when a source revision removes their GTIN.
        held_ids = {
            h.inventory_lot_id
            for h in db.scalars(
                select(InventoryHold).where(
                    InventoryHold.incident_id == incident.id,
                    InventoryHold.status == "active",
                )
            )
        }
        if held_ids:
            for lot in tools.call("get_inventory_lots", "load_recall_inventory"):
                if lot["id"] in held_ids:
                    inventory[lot["id"]] = lot
        official = add_evidence(
            db,
            incident.id,
            "official" if store.mode != "evaluation" else "benchmark",
            (
                f"Official recall version {version['official_version']}"
                if store.mode != "evaluation"
                else "Synthetic benchmark scope"
            ),
            {
                "recall_version_id": version["id"],
                "raw": version["raw"],
                "targets": version["targets"],
            },
            recall_version_id=version["id"],
            source_url=version["source_url"] or None,
            synthetic=store.mode == "evaluation",
        )
        ids = [official.id]
        for lot in inventory.values():
            e = add_evidence(
                db,
                incident.id,
                "inventory",
                f"Warehouse stock: {lot['sku']}",
                lot,
                inventory_lot_id=lot["id"],
                synthetic=store.mode != "live",
            )
            ids.append(e.id)
        return {
            "recall": version,
            "inventory": list(inventory.values()),
            "evidence_ids": ids,
        }

    def retrieve(state):
        previous = tools.call("get_previous_decisions", "retrieve_prior_evidence")
        supplier = tools.call("get_supplier_evidence", "retrieve_prior_evidence")
        warehouse_ids = list(
            db.scalars(
                select(Evidence.id).where(
                    Evidence.incident_id == incident.id,
                    (Evidence.kind == "warehouse_update")
                    | (
                        (Evidence.kind == "official_document")
                        & (Evidence.recall_version_id == run.recall_version_id)
                    ),
                )
            )
        )
        return {
            "previous": previous,
            "evidence_ids": list(
                dict.fromkeys(
                    state["evidence_ids"] + [e["id"] for e in supplier] + warehouse_ids
                )
            ),
        }

    def verify(state):
        results = {
            lot["id"]: tools.call(
                "check_lot_constraints",
                "verify_identifiers_lots_dates",
                inventory_lot_id=lot["id"],
            )
            for lot in state["inventory"]
        }
        return {
            "verifications": results,
            "needs_investigation": True,
        }

    def ambiguity(state):
        trigger = (
            db.get(Evidence, event.payload["evidence_id"])
            if event.payload.get("evidence_id")
            else None
        )
        context = {
            "focus_inventory_lot_id": (
                trigger.inventory_lot_id
                if trigger and trigger.incident_id == incident.id
                else None
            ),
            "model_disabled": event.payload.get(
                "disable_llm", store.mode == "evaluation"
            ),
            "memory_enabled": event.payload.get("memory_enabled", True),
            "recall_version": state["recall"]["id"],
            "source_url": state["recall"]["source_url"],
            "evidence_ids": state["evidence_ids"],
            "evidence": [
                {
                    "evidence_id": e.id,
                    "kind": e.kind,
                    "inventory_lot_id": e.inventory_lot_id,
                    "label": e.label,
                }
                for evidence_id in state["evidence_ids"]
                if (e := db.get(Evidence, evidence_id)) is not None
            ],
            "active_holds": [
                {
                    "inventory_lot_id": h.inventory_lot_id,
                    "quantity": h.quantity,
                    "status": h.status,
                }
                for h in db.scalars(
                    select(InventoryHold).where(
                        InventoryHold.incident_id == incident.id,
                        InventoryHold.status == "active",
                    )
                )
            ],
            "inventory": state["inventory"],
            "checks": state["verifications"],
        }
        result = run_investigator(tools, run, state, context, strategy=strategy)
        return {**result, "plan": {"strategy": strategy}}

    def choose(state):
        actions = {
            lot_id: (
                "create_inventory_hold"
                if v["verdict"] == "affected"
                else (
                    "request_human_review"
                    if v["verdict"] in {"review", "conflict"}
                    else "no_hold"
                )
            )
            for lot_id, v in state["verifications"].items()
        }
        return {"plan": {**state.get("plan", {}), "permitted_actions": actions}}

    def execute(state):
        ids = []
        for lot in state["inventory"]:
            existing = db.scalar(
                select(Decision).where(
                    Decision.run_id == run.id, Decision.inventory_lot_id == lot["id"]
                )
            )
            if existing:
                ids.append(existing.id)
                continue
            verification = state["verifications"][lot["id"]]
            verdict = verification["verdict"]
            held = db.scalar(
                select(InventoryHold).where(
                    InventoryHold.incident_id == incident.id,
                    InventoryHold.inventory_lot_id == lot["id"],
                    InventoryHold.status == "active",
                )
            )
            action = state["plan"]["permitted_actions"][lot["id"]]
            explanation = verification["explanation"]
            if held and verdict != "affected":
                action = "preserve_hold_and_review"
                explanation += " Existing hold is preserved; only an authorized human can release it."
            previous = next(
                (
                    p
                    for p in reversed(state["previous"])
                    if p["inventory_lot_id"] == lot["id"]
                ),
                None,
            )
            decision = Decision(
                incident_id=incident.id,
                run_id=run.id,
                inventory_lot_id=lot["id"],
                recall_version_id=run.recall_version_id,
                verdict=verdict,
                explanation=explanation,
                action=action,
                quantity=lot["quantity"],
                lot=verification.get("effective_stock", lot).get("lot"),
                previous_verdict=previous["verdict"] if previous else None,
            )
            db.add(decision)
            db.flush()
            for evidence_id in state["evidence_ids"]:
                e = db.get(Evidence, evidence_id)
                if e and (not e.inventory_lot_id or e.inventory_lot_id == lot["id"]):
                    db.add(
                        DecisionEvidence(
                            decision_id=decision.id, evidence_id=evidence_id
                        )
                    )
            if verdict == "affected":
                tools.call(
                    "create_inventory_hold",
                    "execute_internal_actions",
                    inventory_lot_id=lot["id"],
                    decision_id=decision.id,
                )
            elif verdict in {"review", "conflict"} or held:
                tools.call(
                    "request_human_review",
                    "execute_internal_actions",
                    inventory_lot_id=lot["id"],
                    decision_id=decision.id,
                )
            ids.append(decision.id)
        return {"decisions": ids}

    def persist(state):
        draft = tools.call("prepare_supplier_notification", "persist_outcome")["draft"]
        decisions = [db.get(Decision, i) for i in state["decisions"]]
        verdicts = {d.verdict for d in decisions}
        holds = db.scalars(
            select(InventoryHold).where(
                InventoryHold.incident_id == incident.id,
                InventoryHold.status == "active",
            )
        ).all()
        incident.status = (
            "conflict"
            if "conflict" in verdicts
            else (
                "review"
                if "review" in verdicts
                or any(d.action == "preserve_hold_and_review" for d in decisions)
                else "held" if holds else "unaffected"
            )
        )
        incident.updated_at = utcnow()
        run.summary = " ".join(
            f"Lot {d.lot or 'unknown'}: {d.verdict} ({d.quantity} units)."
            for d in decisions
        )
        # Operator summaries and copyable drafts come only from recorded decisions.
        # Model commentary remains available in the planner trace and run state.
        run.draft = draft
        run.status = "completed"
        # Full event-to-decision latency includes time queued before the worker started.
        run.latency_ms = round((utcnow() - event.created_at).total_seconds() * 1000, 3)
        tools.call("append_audit_event", "persist_outcome")
        return {}

    graph = StateGraph(InvestigationState)
    steps = [
        ("detect_event", detect),
        ("load_recall_inventory", load),
        ("retrieve_prior_evidence", retrieve),
        ("verify_identifiers_lots_dates", verify),
        ("investigate_ambiguity", ambiguity),
        ("select_response_tools", choose),
        ("execute_internal_actions", execute),
        ("persist_outcome", persist),
    ]
    for name, fn in steps:
        graph.add_node(name, wrap(name, fn))
    graph.add_edge(START, "detect_event")
    graph.add_edge("detect_event", "load_recall_inventory")
    graph.add_edge("load_recall_inventory", "retrieve_prior_evidence")
    graph.add_edge("retrieve_prior_evidence", "verify_identifiers_lots_dates")
    graph.add_conditional_edges(
        "verify_identifiers_lots_dates",
        lambda s: (
            "investigate_ambiguity"
            if s["needs_investigation"]
            else "select_response_tools"
        ),
    )
    graph.add_edge("investigate_ambiguity", "select_response_tools")
    graph.add_edge("select_response_tools", "execute_internal_actions")
    graph.add_edge("execute_internal_actions", "persist_outcome")
    graph.add_edge("persist_outcome", END)
    saved_state = run.state or {}
    saved_decisions = saved_state.get("decisions", [])
    if saved_decisions and all(
        (decision := db.get(Decision, decision_id)) is not None
        and decision.run_id == run.id
        for decision_id in saved_decisions
    ):
        # Execution already committed. Finish from its frozen evidence snapshot;
        # re-retrieval here could pair old decisions with newer contradictory facts.
        wrap("persist_outcome", persist)(saved_state)
    else:
        graph.compile().invoke({"event_id": event.id})
    run.state = {
        **run.state,
        "processing_latency_ms": round((perf_counter() - start) * 1000, 3),
    }
    db.commit()
    return run


def settings_llm():
    from app.core.config import settings

    return settings.llm_api_key
