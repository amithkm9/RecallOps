"""Record a reproducible investigator run. Real provider calls require --live-model.

Use a dedicated verification database. Every case is stored as synthetic evaluation
data. No real stock, supplier message, or external business action is involved.
"""

import argparse
import json
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--live-model", action="store_true")
parser.add_argument("--comparison", action="store_true")
parser.add_argument("--output", default="docs/investigator-verification.json")
args = parser.parse_args()
if not args.live_model:
    os.environ["LLM_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select
from app.core.config import settings
from app.core.database import SessionLocal
from app.models import AgentRun, Decision, InventoryHold, utcnow
from app.repositories.records import add_evidence, enqueue, record
from app.services.evaluation import create_case
from app.services.events import process_event
from app.services.investigator_evaluation import run_comparison, seed_claims
from app.services.investigator_experiments import simulate, simulation_options

if args.live_model and not settings.llm_api_key:
    parser.error(
        "--live-model requires a configured server model key; credentials are never printed."
    )
with SessionLocal() as db:
    case = {
        "name": "Investigator verification",
        "scope": "3760099533007$A1$non concerné$$",
        "gtin": "3760099533007",
        "lot": None,
        "product_name": "Fictional verification stock",
        "recall_name": "Synthetic recall",
        "expected": "affected",
    }
    incident, stock, event = create_case(db, case, commit=False)
    seed_claims(db, incident, stock, [{"lot": "A1", "accepted": True}])
    event.payload = {
        **event.payload,
        "disable_llm": not args.live_model,
        "memory_enabled": False,
        "investigation_strategy": "adaptive",
    }
    db.commit()
    run_id = process_event(event.id)
    db.expire_all()
    run = db.get(AgentRun, run_id)
    decision = db.scalar(select(Decision).where(Decision.run_id == run_id))
    options = simulation_options(db, incident, run_id)
    full = simulate(db, incident, run_id, options["default_evidence_ids"])
    no_claim_ids = [
        e["id"] for e in options["evidence"] if e["kind"] != "delivery_claim"
    ]
    omitted = simulate(db, incident, run_id, no_claim_ids)
    hold = db.scalar(
        select(InventoryHold).where(
            InventoryHold.incident_id == incident.id, InventoryHold.status == "active"
        )
    )
    assert decision.verdict == "affected" and hold.quantity == 24
    assert stock.lot is None and full["decisions"][0]["verdict"] == "affected"
    assert omitted["decisions"][0]["verdict"] == "review"
    provider = [
        s["output"]["provider"]
        for s in run.steps
        if s.get("tool") == "llm_investigation_planner"
        and isinstance(s.get("output"), dict)
        and s["output"].get("provider")
    ]
    model_trace = {
        "requested": args.live_model,
        "mode": run.llm_mode,
        "provider_calls": provider,
        "selected_actions": [
            s for s in run.state.get("investigator", {}).get("steps", [])
        ],
    }
    add_evidence(
        db,
        incident.id,
        "supplier",
        "Fictional contradictory statement",
        {"lot": "B2", "supplier": "Fictional verification supplier"},
        inventory_lot_id=stock.id,
        synthetic=True,
    )
    correction = enqueue(
        db,
        f"verify-investigator:{incident.id}:conflict",
        "supplier_evidence_changed",
        incident.id,
        incident.store_id,
        {"disable_llm": True},
    )
    db.commit()
    conflict_run = process_event(correction.id)
    db.expire_all()
    conflict = db.scalar(select(Decision).where(Decision.run_id == conflict_run))
    held = list(
        db.scalars(
            select(InventoryHold).where(
                InventoryHold.incident_id == incident.id,
                InventoryHold.status == "active",
            )
        )
    )
    assert conflict.verdict == "conflict" and len(held) == 1 and held[0].id == hold.id
    report = {
        "created_at": utcnow().isoformat(),
        "synthetic": True,
        "incident_id": incident.id,
        "run_id": run_id,
        "conflict_run_id": conflict_run,
        "checks": {
            "validated_delivery_affected": True,
            "warehouse_unchanged": True,
            "frozen_simulation_with_claim_affected": True,
            "frozen_simulation_without_claim_review": True,
            "supplier_conflict_preserves_same_hold": True,
        },
        "model": model_trace,
        "limitations": [
            "Pre-confirmed associations are synthetic fixture inputs.",
            "This functional check does not establish general model quality or independent production accuracy.",
        ],
    }
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    if args.comparison:
        report["comparison"] = record(run_comparison(db, include_model=False))
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "report": args.output,
                "checks_passed": len(report["checks"]),
                "model_mode": model_trace["mode"],
                "provider_calls": len(provider),
            }
        )
    )
    if args.live_model and not provider:
        raise SystemExit(
            "Functional fallback worked, but no successful live model call was recorded."
        )
