"""Bounded evidence retrieval and pure, provenance-preserving verification.

No model output is a stock fact. Only an explicitly associated, validated claim
can fill a missing warehouse field. Original warehouse records remain intact.
"""

from time import perf_counter

from app.agents.llm import plan_investigation
from app.schemas.matching import Stock, Target
from app.services.matching import check_lot_constraints, gtin_key, lot_key


def verify_with_claims(
    stock: dict,
    targets: list[dict],
    supplier_lots: list[str],
    claims: list[dict],
    scope_incomplete: bool = False,
) -> dict:
    effective = dict(stock)
    accepted = [
        c
        for c in claims
        if c.get("status") == "accepted"
        and c.get("inventory_lot_id") == stock.get("id")
        and c.get("validation_evidence_id")
    ]
    conflicts = []
    if len({lot_key(v) for v in supplier_lots if v}) > 1:
        conflicts.append("Supplier statements disagree about the batch")
    evidence_ids = []
    for claim in accepted:
        evidence_ids.extend(
            c
            for c in (
                claim.get("id"),
                claim.get("document_id"),
                claim.get("validation_evidence_id"),
            )
            if c
        )
        if claim.get("gtin") and gtin_key(claim["gtin"]) != gtin_key(stock["gtin"]):
            conflicts.append(
                "Validated document identifier contradicts warehouse identifier"
            )
        if claim.get("sku") and stock.get("sku") and claim["sku"] != stock["sku"]:
            conflicts.append("Validated delivery SKU no longer matches warehouse stock")
        if claim.get("quantity") is not None and claim["quantity"] != stock.get(
            "quantity"
        ):
            conflicts.append(
                "Validated delivery quantity no longer covers exactly this stock; recheck association"
            )
    for field in ("lot", "expires_on"):
        values = [c[field] for c in accepted if c.get(field)]
        if stock.get(field):
            values.append(stock[field])
        normalize = lot_key if field == "lot" else str
        if len({normalize(v) for v in values}) > 1:
            conflicts.append(f"Validated evidence disagrees about {field}")
        elif not effective.get(field) and values:
            effective[field] = values[0]
    result = check_lot_constraints(
        Stock.model_validate(effective),
        [Target.model_validate(t) for t in targets],
        supplier_lots,
        scope_incomplete,
    ).model_dump()
    if conflicts:
        result.update(
            verdict="conflict",
            explanation="; ".join(conflicts)
            + ". Preserve any existing hold and request human investigation.",
            checks=[*result["checks"], *conflicts],
        )
    elif accepted:
        result["checks"].append(
            "Explicitly associated, operator-validated evidence checked"
        )
    return {
        **result,
        "effective_stock": effective,
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "used_claim_ids": [c["id"] for c in accepted],
        "accepted_claims": accepted,
    }


def investigation_questions(inventory, verifications, candidates, targets=None):
    questions = []
    for stock in inventory:
        result = verifications[stock["id"]]
        if result["verdict"] not in {"review", "conflict"}:
            continue
        effective = result.get("effective_stock", stock)
        available = [
            c
            for c in candidates.get(stock["id"], [])
            if c.get("status") not in {"accepted", "rejected", "superseded"}
        ]
        relevant = [
            t for t in targets or [] if gtin_key(t["gtin"]) == gtin_key(stock["gtin"])
        ]
        required = (
            ["lot"]
            if not relevant or any(not t.get("all_lots") for t in relevant)
            else []
        )
        if not relevant or any(t.get("date_start") for t in relevant):
            required.append("expires_on")
        fields = [f for f in required if not effective.get(f)]
        if result.get("source_scope_incomplete") and result["verdict"] != "conflict":
            kind, prompt = "official_scope", (
                "The pinned official recall scope cannot be fully interpreted. Review its original "
                "notice and attachments and request a clarified official scope. Previous versions "
                "and document prose cannot establish a current stock exclusion."
            )
        elif result["verdict"] == "conflict":
            kind, prompt = "conflict", (
                f"Evidence for {stock.get('sku', stock['id'])} disagrees. Check the physical batch/date "
                "and the original delivery reference; record which evidence is supported and why. "
                "Any existing hold remains active."
            )
        elif result.get("pending_delivery_check"):
            kind, prompt = "pending_evidence", (
                "Validated delivery evidence has not yet been checked within this investigation's "
                "retrieval budget. Reassess this stock before concluding; its available evidence "
                "must be retrieved and compared with the current warehouse record."
            )
        elif available:
            kind, prompt = "association", (
                f"Which delivery record describes these {stock['quantity']} units of "
                f"{stock.get('sku', stock['id'])}? Confirm the shipment association and "
                "the batch/date on the source before accepting a claim."
            )
        else:
            kind, prompt = "missing_fact", (
                f"Check the physical label or upload the delivery record for "
                f"{stock.get('sku', stock['id'])} ({stock['quantity']} units). "
                + (
                    "Provide " + ", ".join(fields) + " and the shipment reference."
                    if fields
                    else "Clarify the official recall scope with a source reference."
                )
            )
        questions.append(
            {
                "inventory_lot_id": stock["id"],
                "kind": kind,
                "prompt": prompt,
                "fields": fields,
                "candidate_claim_ids": [c["id"] for c in available],
            }
        )
    return questions


def run_investigator(
    tools,
    run,
    state: dict,
    context: dict,
    strategy="adaptive",
    max_calls=8,
    max_seconds=25.0,
) -> dict:
    """Read-only tool loop. Limits include planner time; no repeated action keys."""
    started = perf_counter()
    inventory, verifications = state["inventory"], dict(state["verifications"])
    candidates, steps, memory, errors, source_inspections = {}, [], [], [], []
    source_tools = {"compare_recall_versions", "inspect_official_documents"}
    seen, discovered = set(), set(state["evidence_ids"])
    baseline = strategy == "baseline"
    mode = (
        "baseline"
        if baseline
        else "fixed_retrieval" if strategy == "fixed" else "deterministic_fallback"
    )
    model_failed = False
    verification_calls = 0
    stop_reason = "baseline_workflow" if baseline else "evidence_exhausted"
    # Baseline preserves the old planner for trace compatibility, but cannot gain new tools.
    if baseline:
        from app.core.config import settings

        if any(
            v["verdict"] in {"review", "conflict"} for v in verifications.values()
        ) or (settings.llm_api_key and not context.get("model_disabled")):
            plan = plan_investigation(run, context)
            for name in dict.fromkeys(plan.tools):
                if len(steps) >= max_calls or perf_counter() - started >= max_seconds:
                    stop_reason = (
                        "tool_limit" if len(steps) >= max_calls else "time_limit"
                    )
                    break
                rows = tools.call(name, "investigate_ambiguity")
                steps.append(
                    {
                        "tool": name,
                        "inventory_lot_id": None,
                        "reason": "Original workflow planned retrieval",
                        "status": "completed",
                        "result_count": len(rows),
                        "new_evidence_ids": [],
                    }
                )
            for stock in inventory:
                verifications[stock["id"]] = tools.call(
                    "check_lot_constraints",
                    "investigate_ambiguity",
                    inventory_lot_id=stock["id"],
                )
                verification_calls += 1

    while not baseline and len(steps) < max_calls:
        remaining = max_seconds - (perf_counter() - started)
        if remaining <= 0:
            stop_reason = "time_limit"
            break
        unresolved = [
            s
            for s in inventory
            if verifications[s["id"]]["verdict"] in {"review", "conflict"}
            or verifications[s["id"]].get("pending_delivery_check")
        ]
        actions = []
        candidates_to_investigate = inventory if strategy == "fixed" else unresolved
        focus_id = context.get("focus_inventory_lot_id")
        if focus_id:
            candidates_to_investigate = sorted(
                candidates_to_investigate, key=lambda s: s["id"] != focus_id
            )
        for stock in candidates_to_investigate:
            names = [
                "get_retrieval_hints",
                "search_delivery_records",
                "get_supplier_evidence",
            ]
            if strategy == "adaptive":
                names = ["get_retrieval_hints", "search_delivery_records"]
            if (
                strategy == "adaptive"
                and verifications[stock["id"]]["verdict"] == "conflict"
            ):
                names = [
                    "get_supplier_evidence",
                    "get_retrieval_hints",
                    "search_delivery_records",
                ]
            if strategy == "fixed" or verifications[stock["id"]].get(
                "source_scope_incomplete"
            ):
                names = [
                    "compare_recall_versions",
                    "inspect_official_documents",
                    *names,
                ]
            if not context.get("memory_enabled", True):
                names = [n for n in names if n != "get_retrieval_hints"]
            for name in names:
                key = (name, "source" if name in source_tools else stock["id"])
                if key not in seen:
                    actions.append({"tool": name, "inventory_lot_id": stock["id"]})
        actions = actions[:24]
        if not actions:
            stop_reason = (
                "resolved" if not unresolved else "human_confirmation_required"
            )
            break
        choice, reason = actions[0], (
            "Fixed retrieval order"
            if strategy == "fixed"
            else "Retrieve evidence for unresolved stock"
        )
        if strategy == "adaptive":
            action_stock_ids = {a["inventory_lot_id"] for a in actions}
            planner_context = {
                **context,
                "inventory": [s for s in inventory if s["id"] in action_stock_ids][:24],
                "evidence": context.get("evidence", [])[:100],
                "evidence_ids": context.get("evidence_ids", [])[:100],
            }
            plan = plan_investigation(
                run,
                {
                    **planner_context,
                    "model_disabled": context.get("model_disabled") or model_failed,
                    "available_actions": actions,
                    "completed_retrievals": steps,
                    "checks": {
                        key: {k: v for k, v in check.items() if k != "accepted_claims"}
                        for key, check in verifications.items()
                        if key in action_stock_ids
                    },
                    "retrieval_hints": memory[:20],
                    "source_inspections": source_inspections[-4:],
                    "retrieved_candidates": [
                        {
                            **{
                                k: c.get(k)
                                for k in (
                                    "id",
                                    "document_id",
                                    "inventory_lot_id",
                                    "status",
                                    "lot",
                                    "expires_on",
                                    "reference",
                                    "locator",
                                )
                            },
                            "excerpt": str(c.get("excerpt", ""))[:2000],
                        }
                        for rows in candidates.values()
                        for c in rows[:20]
                    ],
                    "timeout_seconds": min(remaining, 8.0),
                },
            )
            if run.llm_mode == "deterministic_fallback_provider_error":
                model_failed = True
            mode = (
                "deterministic_fallback_provider_error"
                if model_failed
                else run.llm_mode
            )
            requested = [a.model_dump() for a in plan.actions]
            matching = next((a for a in requested if a in actions), None)
            if matching:
                choice, reason = (
                    matching,
                    "Model selected an available read-only evidence source",
                )
            elif run.llm_mode == "llm_assisted":
                mode = "llm_assisted_with_deterministic_selection"
            if perf_counter() - started >= max_seconds:
                stop_reason = "time_limit"
                break
        key = (
            choice["tool"],
            "source" if choice["tool"] in source_tools else choice["inventory_lot_id"],
        )
        seen.add(key)
        try:
            rows = tools.call(
                choice["tool"],
                "investigate_ambiguity",
                inventory_lot_id=choice["inventory_lot_id"],
            )
            source_ids = dict.fromkeys(
                value
                for r in rows
                for value in (
                    r.get("id"),
                    r.get("document_id"),
                    r.get("validation_evidence_id"),
                )
                if value
            )
            new_ids = [value for value in source_ids if value not in discovered]
            discovered.update(new_ids)
            step = {
                **choice,
                "reason": reason,
                "result_count": len(rows),
                "new_evidence_ids": new_ids,
                "status": "completed",
            }
            if choice["tool"] == "search_delivery_records":
                candidates[choice["inventory_lot_id"]] = rows
            elif choice["tool"] == "get_retrieval_hints":
                memory.extend(rows)
            elif choice["tool"] in source_tools:
                source_inspections.extend(rows)
        except (ValueError, PermissionError, OSError) as exc:
            # No exception message/source contents leak into operator-facing state.
            step = {
                **choice,
                "reason": reason,
                "status": "failed",
                "error_type": type(exc).__name__,
                "result_count": 0,
                "new_evidence_ids": [],
            }
            errors.append(step)
        steps.append(step)
        # Reassessment is deterministic, and never uses model prose or retrieval hints as facts.
        stock_id = choice["inventory_lot_id"]
        verifications[stock_id] = tools.call(
            "check_lot_constraints", "investigate_ambiguity", inventory_lot_id=stock_id
        )
        verification_calls += 1
        if hasattr(tools, "persist_investigation_progress"):
            tools.persist_investigation_progress(
                {
                    "verifications": verifications,
                    "investigator": {
                        "strategy": strategy,
                        "mode": mode,
                        "steps": steps,
                        "questions": investigation_questions(
                            inventory,
                            verifications,
                            candidates,
                            state.get("recall", {}).get("targets"),
                        ),
                        "memory": memory,
                        "source_inspections": source_inspections,
                        "stop_reason": "investigating",
                        "available_evidence_ids": sorted(discovered),
                        "metrics": {
                            "tool_calls": len(steps),
                            "verification_calls": verification_calls,
                            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
                        },
                    },
                }
            )
    else:
        if not baseline:
            stop_reason = "tool_limit"
    if model_failed:
        run.llm_mode = "deterministic_fallback_provider_error"
    questions = investigation_questions(
        inventory, verifications, candidates, state.get("recall", {}).get("targets")
    )
    evidence_ids = list(state["evidence_ids"])
    effective = []
    for stock in inventory:
        result = verifications[stock["id"]]
        evidence_ids.extend(result.get("evidence_ids", []))
        effective.append(result.get("effective_stock", stock))
    investigator = {
        "strategy": strategy,
        "mode": mode,
        "steps": steps,
        "questions": questions,
        "stop_reason": stop_reason,
        "memory": memory,
        "source_inspections": source_inspections,
        "available_evidence_ids": sorted(discovered | set(evidence_ids)),
        "claims_by_inventory": {
            stock["id"]: verifications[stock["id"]].get("accepted_claims", [])
            for stock in inventory
        },
        "memory_policy": "Search hints only; prior stock facts never establish current stock facts.",
        "metrics": {
            "tool_calls": len(steps),
            "verification_calls": verification_calls,
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
            "new_evidence_count": len(discovered - set(state["evidence_ids"])),
            "operator_interventions_required": len(questions),
            "retrieval_errors": len(errors),
            "max_calls": max_calls,
            "max_seconds": max_seconds,
        },
    }
    return {
        "investigator": investigator,
        "effective_inventory": effective,
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "verifications": verifications,
    }
