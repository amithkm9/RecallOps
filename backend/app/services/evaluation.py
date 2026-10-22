"""Small synthetic safety benchmark. Labels are fixtures, never matcher-derived."""

import json
from datetime import date
from difflib import SequenceMatcher
from time import perf_counter
from statistics import median, quantiles
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import (
    AgentRun,
    Decision,
    EvaluationRun,
    Incident,
    InventoryHold,
    InventoryLot,
    Recall,
    RecallTarget,
    RecallVersion,
    Store,
    utcnow,
)
from app.repositories.records import add_evidence, digest, enqueue
from app.services.events import process_event
from app.services.matching import gtin_key, lot_key, parse_identification


def create_case(db: Session, case: dict, *, commit: bool = True):
    store = Store(
        name="Synthetic benchmark — " + case["name"], mode="evaluation", active=False
    )
    db.add(store)
    db.flush()
    recall = Recall(
        source_id="benchmark:" + str(uuid4()), reference="SYNTHETIC-BENCHMARK"
    )
    db.add(recall)
    db.flush()
    targets, warnings = parse_identification(case["scope"], case.get("fallback_gtin"))
    version = RecallVersion(
        recall_id=recall.id,
        content_hash=digest(case),
        official_version="1",
        product_name=case["recall_name"],
        brand="Synthetic benchmark",
        category="synthetic",
        published_at=utcnow(),
        source_url="",
        reason="Synthetic test case",
        risk="Synthetic test case",
        raw={"identification_produits": case["scope"], "_synthetic": True},
        parse_warnings=warnings,
    )
    db.add(version)
    db.flush()
    recall.current_version_id = version.id
    for target in targets:
        db.add(
            RecallTarget(
                recall_version_id=version.id,
                gtin=gtin_key(target.gtin),
                scope=target.model_dump(mode="json"),
            )
        )
    inventory = InventoryLot(
        store_id=store.id,
        sku="BENCHMARK",
        product_name=case["product_name"],
        gtin=case["gtin"],
        lot=case.get("lot"),
        lot_key=lot_key(case.get("lot")),
        quantity=24,
        supplier="Synthetic supplier",
        expires_on=(
            date.fromisoformat(case["expires_on"]) if case.get("expires_on") else None
        ),
    )
    db.add(inventory)
    incident = Incident(store_id=store.id, recall_id=recall.id)
    db.add(incident)
    db.flush()
    if case.get("supplier_lot"):
        add_evidence(
            db,
            incident.id,
            "supplier",
            "Synthetic supplier evidence",
            {"lot": case["supplier_lot"]},
            inventory_lot_id=inventory.id,
            synthetic=True,
        )
    event = enqueue(
        db,
        f"benchmark:{incident.id}:initial",
        "synthetic_benchmark_case",
        incident.id,
        store.id,
        {
            "recall_version_id": version.id,
            "disable_llm": not case.get("include_model", False),
        },
    )
    if commit:
        db.commit()
    return incident, inventory, event


def metrics(
    method: str,
    predictions: list[str],
    cases: list[dict],
    latencies: list[float],
    revision_rate: float | None = None,
):
    tp = sum(
        p == "affected" and c["expected"] == "affected"
        for p, c in zip(predictions, cases)
    )
    fp = sum(
        p == "affected" and c["expected"] != "affected"
        for p, c in zip(predictions, cases)
    )
    fn = sum(
        p != "affected" and c["expected"] == "affected"
        for p, c in zip(predictions, cases)
    )
    nonaffected = sum(c["expected"] != "affected" for c in cases)
    ambiguous = sum(c["expected"] in {"review", "conflict"} for c in cases)
    correct_reviews = sum(
        p in {"review", "conflict"} and c["expected"] in {"review", "conflict"}
        for p, c in zip(predictions, cases)
    )
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    return {
        "method": method,
        "precision": precision,
        "recall": recall,
        "f1": (
            2 * precision * recall / (precision + recall) if precision + recall else 0
        ),
        "false_hold_rate": fp / nonaffected if nonaffected else 0,
        "review_accuracy": correct_reviews / ambiguous if ambiguous else 0,
        "latency_ms": sum(latencies) / len(latencies),
        "revision_rate": revision_rate,
        "missed_hold_rate": fn / (tp + fn) if tp + fn else 0,
        "review_request_rate": sum(p in {"review", "conflict"} for p in predictions)
        / len(cases),
        "p50_latency_ms": median(latencies),
        "p95_latency_ms": (
            quantiles(latencies, n=100, method="inclusive")[94]
            if len(latencies) > 1
            else latencies[0]
        ),
        "counts": {
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "sample_size": len(cases),
        },
    }


def run_evaluation(
    db: Session, cases: list[dict] | None = None, provenance: dict | None = None
) -> EvaluationRun:
    cases = (
        cases
        if cases is not None
        else json.loads((settings.fixture_dir / "benchmark.json").read_text())
    )
    provenance = provenance or {
        "source": "Development-authored synthetic fixtures",
        "labeler": "RecallOps development suite",
        "independent_review_verified": False,
    }
    provenance = {
        **provenance,
        "sha256": digest(cases),
        "sample_size": len(cases),
        "independent_review_verified": False,
    }
    predictions = {name: [] for name in ["Product name", "GTIN only", "RecallOps"]}
    latencies = {name: [] for name in predictions}
    details = []
    for case in cases:
        start = perf_counter()
        name_prediction = (
            "affected"
            if SequenceMatcher(
                None, case["product_name"].casefold(), case["recall_name"].casefold()
            ).ratio()
            >= 0.5
            else "unaffected"
        )
        latencies["Product name"].append((perf_counter() - start) * 1000)
        predictions["Product name"].append(name_prediction)
        start = perf_counter()
        targets, _ = parse_identification(case["scope"], case.get("fallback_gtin"))
        gtin_prediction = (
            "affected"
            if any(gtin_key(t.gtin) == gtin_key(case["gtin"]) for t in targets)
            else "unaffected"
        )
        latencies["GTIN only"].append((perf_counter() - start) * 1000)
        predictions["GTIN only"].append(gtin_prediction)
        incident, inventory, event = create_case(db, case)
        run_id = process_event(event.id)
        db.expire_all()
        run = db.get(AgentRun, run_id)
        decision = db.scalar(
            select(Decision).where(
                Decision.run_id == run.id, Decision.inventory_lot_id == inventory.id
            )
        )
        prediction = decision.verdict if decision else "unaffected"
        predictions["RecallOps"].append(prediction)
        latencies["RecallOps"].append(run.latency_ms)
        details.append(
            {
                **case,
                "predictions": {
                    name: values[-1] for name, values in predictions.items()
                },
                "run_id": run.id,
                "event_to_decision_ms": run.latency_ms,
            }
        )
    # Stateful revision sub-benchmark uses the same persisted workflow and action tools.
    revision_case = {
        "name": "Stateful revision",
        "scope": "3760099533007$A1$non concerné$$",
        "gtin": "3760099533007",
        "lot": None,
        "expected": "review",
        "product_name": "Smoked salmon",
        "recall_name": "Smoked salmon",
    }
    incident, stock, event = create_case(db, revision_case)
    process_event(event.id)
    stock.lot = "A1"
    stock.lot_key = "a1"
    event2 = enqueue(
        db,
        f"benchmark:{incident.id}:stock",
        "warehouse_stock_updated",
        incident.id,
        incident.store_id,
        {"disable_llm": True},
    )
    db.commit()
    run2 = process_event(event2.id)
    affected = (
        db.scalar(select(Decision).where(Decision.run_id == run2)).verdict == "affected"
    )
    add_evidence(
        db,
        incident.id,
        "supplier",
        "Synthetic contradiction after hold",
        {"lot": "B2"},
        inventory_lot_id=stock.id,
        synthetic=True,
    )
    event3 = enqueue(
        db,
        f"benchmark:{incident.id}:supplier",
        "supplier_evidence_changed",
        incident.id,
        incident.store_id,
        {"disable_llm": True},
    )
    db.commit()
    run3 = process_event(event3.id)
    conflict = (
        db.scalar(select(Decision).where(Decision.run_id == run3)).verdict == "conflict"
    )
    preserved = db.scalar(
        select(InventoryHold).where(
            InventoryHold.incident_id == incident.id, InventoryHold.status == "active"
        )
    )
    revision_rate = (int(affected) + int(conflict and preserved is not None)) / 2
    results = [
        metrics(
            name,
            predictions[name],
            cases,
            latencies[name],
            revision_rate if name == "RecallOps" else None,
        )
        for name in predictions
    ]
    result = EvaluationRun(
        sample_size=len(cases),
        benchmark=f"{provenance['source']}; {len(cases)} labeled cases + 2 stateful revision transitions. Independent labeling has not been verified. RecallOps latency includes PostgreSQL and LangGraph; baseline latency is in-process matching only.",
        results=results,
        cases=details
        + [{"name": "Dataset provenance", **provenance}]
        + [
            {
                "name": "Stateful decision revisions",
                "expected": "review → affected → conflict; hold preserved",
                "transition_count": 2,
                "successful_revisions": int(affected)
                + int(conflict and preserved is not None),
                "incident_id": incident.id,
            }
        ],
    )
    db.add(result)
    db.commit()
    return result
