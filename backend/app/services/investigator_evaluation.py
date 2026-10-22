"""Comparative investigation benchmark with shared inputs and explicit human work.

Confirmed associations are fixture inputs, not autonomous discoveries. Results
measure retrieval and verification, not a replacement for an operator stock check.
"""

import json
from statistics import median, quantiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from fastapi import HTTPException
from app.models import AgentRun, Decision, EvaluationRun
from app.repositories.records import add_evidence, digest
from app.services.evaluation import create_case
from app.services.events import process_event

BENCHMARK = "Investigator comparison v1"


def seed_claims(db, incident, stock, claims):
    """Install explicitly synthetic, pre-reviewed benchmark evidence before running."""
    setup_confirmations = 0
    for i, item in enumerate(claims):
        payload = {
            "delivery_id": f"BENCH-{i}",
            "sku": stock.sku,
            "gtin": stock.gtin,
            "lot": item["lot"],
            "quantity": stock.quantity,
            "expires_on": item.get("expires_on"),
            "reference": f"Synthetic delivery {i}",
            "locator": f"Fixture row {i + 1}",
            "excerpt": item.get(
                "excerpt", f"Batch {item['lot']} in synthetic delivery {i}"
            ),
        }
        document = add_evidence(
            db,
            incident.id,
            "delivery_document",
            f"Synthetic delivery {i}",
            {
                "filename": f"fixture-{i}.csv",
                "media_type": "text/csv",
                "sha256": digest(payload),
                "bytes": 0,
                "content_base64": "",
                "text_status": "parsed_unverified",
                "claim_count": 1,
                "errors": [],
                "synthetic": True,
            },
            synthetic=True,
        )
        claim = add_evidence(
            db,
            incident.id,
            "delivery_claim",
            f"Synthetic claim {i}",
            {
                **payload,
                "document_id": document.id,
                "association_confirmed": False,
                "extraction_method": "synthetic_fixture",
            },
            synthetic=True,
        )
        if item.get("accepted"):
            setup_confirmations += 1
            add_evidence(
                db,
                incident.id,
                "claim_validation",
                "Synthetic pre-confirmed association",
                {
                    "claim_id": claim.id,
                    "document_id": document.id,
                    "accept": True,
                    "reason": "Fixture assumes an operator has checked this shipment association.",
                    "actor": "synthetic_fixture",
                    "association_confirmed": True,
                    "supersedes_validation_id": None,
                },
                inventory_lot_id=stock.id,
                synthetic=True,
            )
    return setup_confirmations


def seed_memory_route(db, incident, stock):
    """Import a synthetic prior confirmed case; reuse its route, never its facts.

    The stock row is a stable inventory identity across cases. Its earlier
    observed batch is deliberately different; that old claim stays in its own
    incident and cannot enter the current verifier.
    """
    from datetime import timedelta
    from uuid import uuid4
    from app.models import Incident, Recall, RecallTarget, RecallVersion, utcnow

    earlier = utcnow() - timedelta(days=30)
    prior_recall = Recall(
        source_id="benchmark-memory:" + str(uuid4()),
        reference="SYNTHETIC-PRIOR-CASE",
        created_at=earlier,
    )
    db.add(prior_recall)
    db.flush()
    prior_version = RecallVersion(
        recall_id=prior_recall.id,
        content_hash=digest([prior_recall.id, "prior-route"]),
        official_version="1",
        product_name="Synthetic historical delivery case",
        brand="Synthetic benchmark",
        category="synthetic",
        published_at=earlier,
        source_url="",
        reason="Imported synthetic history",
        risk="Synthetic only",
        raw={"_synthetic": True, "_imported_history": True},
        parse_warnings=[],
        created_at=earlier,
    )
    db.add(prior_version)
    db.flush()
    prior_recall.current_version_id = prior_version.id
    db.add(
        RecallTarget(
            recall_version_id=prior_version.id,
            gtin=stock.gtin.zfill(14),
            scope={"gtin": stock.gtin, "lots": ["PRIOR-ONLY-NOT-CURRENT"]},
        )
    )
    previous = Incident(
        store_id=incident.store_id,
        recall_id=prior_recall.id,
        status="review",
        review_status="resolved",
        closed_at=earlier,
        created_at=earlier,
    )
    db.add(previous)
    db.flush()
    document = add_evidence(
        db,
        previous.id,
        "delivery_document",
        "Synthetic historical CSV",
        {
            "media_type": "text/csv",
            "filename": "historical-route.csv",
            "claim_count": 1,
            "errors": [],
            "text_status": "parsed_unverified",
            "content_base64": "",
            "bytes": 0,
            "sha256": digest([previous.id, "document"]),
        },
        synthetic=True,
        created_at=earlier,
    )
    claim = add_evidence(
        db,
        previous.id,
        "delivery_claim",
        "Synthetic historical stock observation",
        {
            "document_id": document.id,
            "delivery_id": "PRIOR-ONLY",
            "sku": stock.sku,
            "gtin": stock.gtin,
            "lot": "PRIOR-ONLY-NOT-CURRENT",
            "quantity": stock.quantity,
            "reference": "Imported synthetic historical delivery",
            "locator": "Fixture row 1",
            "extraction_method": "synthetic_fixture",
            "association_confirmed": False,
        },
        synthetic=True,
        created_at=earlier,
    )
    validation = add_evidence(
        db,
        previous.id,
        "claim_validation",
        "Synthetic historical confirmation",
        {
            "claim_id": claim.id,
            "document_id": document.id,
            "accept": True,
            "actor": "synthetic_fixture",
            "reason": "Fixture assumes a past operator-confirmed association.",
            "association_confirmed": True,
            "supersedes_validation_id": None,
        },
        inventory_lot_id=stock.id,
        synthetic=True,
        created_at=earlier,
    )
    return add_evidence(
        db,
        previous.id,
        "retrieval_hint",
        "Imported confirmed historical source route",
        {
            "store_id": incident.store_id,
            "sku": stock.sku,
            "document_format": "text/csv",
            "claim_id": claim.id,
            "validation_evidence_id": validation.id,
            "strategy": "search_delivery_records",
            "facts_reusable": False,
            "description": "Imported synthetic prior confirmation: search CSV deliveries; validate the current shipment separately.",
            "provenance": "synthetic_imported_history_not_learned_optimization",
        },
        synthetic=True,
        created_at=earlier,
    )


def _summary(name, strategy, rows, model_requested):
    n = len(rows)
    times = [r["latency_ms"] for r in rows]
    resolved = sum(r["prediction"] in {"affected", "unaffected"} for r in rows)
    return {
        "method": name,
        "strategy": strategy,
        "accuracy": sum(r["prediction"] == r["expected"] for r in rows) / n,
        "resolved_rate": resolved / n,
        "review_request_rate": sum(
            r["prediction"] in {"review", "conflict"} for r in rows
        )
        / n,
        "incorrect_exclusions": sum(
            r["prediction"] == "unaffected" and r["expected"] != "unaffected"
            for r in rows
        ),
        "incorrect_holds": sum(
            r["prediction"] == "affected" and r["expected"] != "affected" for r in rows
        ),
        "tool_calls": sum(r["tool_calls"] for r in rows),
        "additional_retrieval_calls": sum(
            r["additional_retrieval_calls"] for r in rows
        ),
        "memory_hints_retrieved": sum(r["memory_hints_retrieved"] for r in rows),
        "operator_interventions": sum(r["operator_interventions"] for r in rows),
        "setup_confirmations": sum(r["setup_confirmations"] for r in rows),
        "p50_latency_ms": median(times),
        "p95_latency_ms": (
            quantiles(times, n=100, method="inclusive")[94] if n > 1 else times[0]
        ),
        "model_calls": sum(r["model_calls"] for r in rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "mode": (
            "model_requested"
            if model_requested and strategy == "adaptive"
            else "deterministic"
        ),
        "actual_modes": sorted({r["mode"] for r in rows}),
        "memory_retrieval_calls": sum(r["memory_calls"] for r in rows),
    }


def run_comparison(db: Session, include_model=False, include_memory=True, dataset=None):
    # Evaluation endpoints are admin-only; serialize to avoid overlapping large runs.
    # Session.commit() returns its connection to the pool. Keep this session-level
    # lock on a separate checked-out connection through every committed case.
    with engine.connect() as lock_connection:
        acquired = lock_connection.scalar(text("SELECT pg_try_advisory_lock(4242098)"))
        if not acquired:
            raise HTTPException(
                409,
                "Another investigator comparison is running. Wait for it to finish.",
            )
        try:
            return _run_comparison(db, include_model, include_memory, dataset)
        finally:
            lock_connection.execute(text("SELECT pg_advisory_unlock(4242098)"))


def _run_comparison(db, include_model, include_memory, dataset=None):
    fixture = (
        {
            **dataset,
            "provenance": f"Imported labels from {dataset['source']}; labeler: {dataset['labeler']}. Independence is unverified.",
        }
        if dataset
        else json.loads((settings.fixture_dir / "investigator-cases.json").read_text())
    )
    strategies = [
        ("Existing workflow", "baseline", False),
        ("Fixed retrieval", "fixed", False),
        ("Adaptive investigator", "adaptive", include_memory),
    ]
    if include_memory:
        strategies.append(("Adaptive without memory", "adaptive", False))
    outputs = {name: [] for name, _, _ in strategies}
    details = []
    for scenario in fixture["cases"]:
        row = {
            "name": scenario["name"],
            "expected": scenario["expected"],
            "predictions": {},
            "run_ids": {},
            "tool_calls": {},
            "split": scenario["split"],
        }
        for name, strategy, memory_enabled in strategies:
            case = {
                "name": scenario["name"],
                "scope": scenario.get("scope", "3760099533007$A1$non concerné$$"),
                "gtin": "3760099533007",
                "lot": scenario.get("lot"),
                "product_name": "Synthetic smoked salmon",
                "recall_name": "Synthetic smoked salmon",
                "expected": scenario["expected"],
                "supplier_lot": scenario.get("supplier_lot"),
            }
            incident, stock, event = create_case(db, case, commit=False)
            confirmations = seed_claims(db, incident, stock, scenario.get("claims", []))
            # The same valid historical hint is available to every strategy.
            if include_memory:
                seed_memory_route(db, incident, stock)
            event.payload = {
                **event.payload,
                "investigation_strategy": strategy,
                "memory_enabled": memory_enabled,
                "disable_llm": not (include_model and strategy == "adaptive"),
            }
            db.commit()
            run_id = process_event(event.id)
            db.expire_all()
            run = db.get(AgentRun, run_id)
            if not run or run.status != "completed":
                raise ValueError(
                    "An investigation did not complete; partial benchmarks are not reported as success."
                )
            decision = db.scalar(
                select(Decision).where(
                    Decision.run_id == run_id, Decision.inventory_lot_id == stock.id
                )
            )
            prediction = decision.verdict if decision else "review"
            investigator = run.state.get("investigator", {})
            metrics = investigator.get("metrics", {})
            model_steps = [
                s for s in run.steps if s.get("tool") == "llm_investigation_planner"
            ]
            usage = [
                (
                    s.get("output", {}).get("provider")
                    or s.get("output", {}).get("failed_provider_response", {})
                ).get("usage", {})
                for s in model_steps
            ]
            record = {
                "expected": scenario["expected"],
                "prediction": prediction,
                "latency_ms": run.state.get("processing_latency_ms", run.latency_ms),
                "tool_calls": sum(
                    s.get("tool")
                    not in {"llm_investigation_planner", "planner_context_limit"}
                    for s in run.steps
                ),
                "additional_retrieval_calls": metrics.get("tool_calls", 0),
                "memory_hints_retrieved": len(investigator.get("memory", [])),
                "operator_interventions": metrics.get(
                    "operator_interventions_required",
                    int(prediction in {"review", "conflict"}),
                ),
                "setup_confirmations": confirmations,
                "model_calls": len(model_steps),
                "input_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
                "output_tokens": sum(u.get("completion_tokens", 0) for u in usage),
                "mode": investigator.get("mode", run.llm_mode),
                "memory_calls": sum(
                    s.get("tool") == "get_retrieval_hints"
                    for s in investigator.get("steps", [])
                ),
            }
            outputs[name].append(record)
            row["predictions"][name], row["run_ids"][name], row["tool_calls"][name] = (
                prediction,
                run.id,
                record["tool_calls"],
            )
        details.append(row)
    results = [
        _summary(name, strategy, outputs[name], include_model)
        for name, strategy, _ in strategies
    ]
    result = EvaluationRun(
        sample_size=len(fixture["cases"]),
        benchmark=BENCHMARK + ". " + fixture["provenance"],
        results=results,
        cases=details
        + [
            {
                "name": "Dataset provenance",
                "sha256": digest(fixture),
                "independent_review_verified": False,
                "held_out": bool(dataset)
                and all(c["split"] == "held_out" for c in fixture["cases"]),
                "holdout_status": (
                    "declared_by_importer_unverified"
                    if dataset
                    else "development_suite"
                ),
                "independent_review_declared": bool(
                    fixture.get("independent_review_declared")
                ),
                "labeler": fixture.get("labeler", "RecallOps development suite"),
                "include_model": include_model,
                "setup_confirmations_are_human_work": True,
                "limitations": [
                    "All strategies receive equivalent synthetic evidence.",
                    "Confirmed shipment associations are supplied fixture inputs, not agent discoveries.",
                    "Review prompts count requested interventions, not measured operator time.",
                    "Memory imports a synthetic prior case with confirmed source association; it is not learned optimization or a trained model.",
                    "Total tool calls include initial loading, deterministic verification, retrieval and internal actions; additional retrieval calls are reported separately.",
                    "No real-store effectiveness, provider cost, or independent accuracy is established.",
                ],
            }
        ],
    )
    db.add(result)
    db.commit()
    return result


def latest_comparison(db, *, public_only=False):
    query = select(EvaluationRun).where(EvaluationRun.benchmark.startswith(BENCHMARK))
    if public_only:
        query = query.where(
            ~EvaluationRun.benchmark.startswith(BENCHMARK + ". Imported labels")
        )
    return db.scalar(query.order_by(EvaluationRun.created_at.desc()).limit(1))
