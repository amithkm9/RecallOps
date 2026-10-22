"""Explicit opt-in live integration check. Keeps fictional inventory in replay mode.

Run: backend/.venv/bin/python scripts/verify_live.py --url http://127.0.0.1:8088
Makes real government API and model requests. Does not send supplier messages.
"""

import argparse
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import settings
from app.services.matching import parse_identification


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    parser.add_argument("--output", default="docs/live-verification.json")
    args = parser.parse_args()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.url,
        "inventory_is_synthetic": True,
        "inventory_mode": "replay",
        "checks": {},
    }
    headers = (
        {"Authorization": f"Bearer {settings.operator_token}"}
        if settings.operator_token
        else {}
    )
    with httpx.Client(base_url=args.url, headers=headers, timeout=120) as client:

        def call(method, path, **kw):
            response = client.request(method, "/api" + path, **kw)
            if not response.is_success:
                raise RuntimeError(
                    f"{method} {path} returned HTTP {response.status_code}"
                )
            return response.json()

        def wait_for(incident_id, predicate, timeout=90):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                detail = call("GET", f"/incidents/{incident_id}")
                if predicate(detail):
                    return detail
                time.sleep(1)
            raise RuntimeError("Investigation did not complete within 90 seconds.")

        try:
            report["checks"]["health"] = call("GET", "/health")
            report["checks"]["model_connection"] = call("POST", "/settings/model-check")
            assert report["checks"]["model_connection"]["success"], (
                "Model connection did not succeed."
            )
            sync = call("POST", "/recalls/sync", json={"source": "live"})
            report["checks"]["official_sync"] = sync
            assert sync["origin"] == "live", (
                "Government source used a fallback; live ingestion was not verified."
            )
            assert not sync["errors"], "Official ingestion reported record errors."
            recalls = call("GET", "/recalls?limit=200")
            candidates = []
            for recall in recalls:
                raw = recall["raw"]
                targets, warnings = parse_identification(
                    raw.get("identification_produits"), raw.get("gtin")
                )
                for target in targets:
                    if target.parseable and target.lots and not warnings:
                        candidates.append((recall, target))
            assert candidates, (
                "No recent record with explicit parseable lot scope was available."
            )
            recall, target = max(candidates, key=lambda pair: pair[0]["published_at"])
            report["checks"]["selected_official_recall"] = {
                "id": recall["id"],
                "product": recall["product_name"],
                "published_at": recall["published_at"],
                "source_url": recall["source_url"],
                "gtin": target.gtin,
                "lot": target.lots[0],
            }
            sku = "LIVE-CHECK-" + uuid4().hex[:10].upper()
            content = io.StringIO()
            writer = csv.writer(content)
            writer.writerow(
                [
                    "sku",
                    "product_name",
                    "gtin",
                    "lot",
                    "quantity",
                    "supplier",
                    "expires_on",
                ]
            )
            writer.writerow(
                [
                    sku,
                    "SYNTHETIC VERIFICATION · " + recall["product_name"],
                    target.gtin,
                    target.lots[0],
                    3,
                    "Fictional live-check supplier",
                    target.date_start or "",
                ]
            )
            result = call(
                "POST",
                "/inventory/import",
                data={"mode": "replay"},
                files={
                    "file": (
                        "synthetic-live-verification.csv",
                        content.getvalue().encode(),
                        "text/csv",
                    )
                },
            )
            report["checks"]["inventory_import"] = result
            assert result["imported"] == 1 and not result["errors"]
            incidents = call("GET", "/incidents?mode=replay")["items"]
            incident = next(i for i in incidents if i["recall_id"] == recall["id"])
            report["incident_id"] = incident["id"]
            report["incident_url"] = args.url + "/incidents/" + incident["id"]
            initial = wait_for(
                incident["id"],
                lambda d: any(
                    decision["inventory_lot_id"] == item["id"]
                    and any(
                        run["id"] == decision["run_id"] and run["status"] == "completed"
                        for run in d["runs"]
                    )
                    for item in d["inventory"]
                    if item["sku"] == sku
                    for decision in d["decisions"]
                ),
            )
            stock = next(i for i in initial["inventory"] if i["sku"] == sku)
            holds = [
                h
                for h in initial["holds"]
                if h["inventory_lot_id"] == stock["id"] and h["status"] == "active"
            ]
            assert holds and holds[0]["quantity"] == 3, "Matching stock was not held."
            baseline = initial["runs"][-1]
            assert baseline["llm_mode"] == "llm_assisted", (
                "Initial investigation fell back instead of using the provider."
            )
            report["checks"]["initial_investigation"] = {
                "run_id": baseline["id"],
                "llm_mode": baseline["llm_mode"],
                "held_units": 3,
            }
            statement = {
                "inventory_lot_id": stock["id"],
                "supplier": "Fictional live-check supplier",
                "lot": "SYNTHETIC-DISPUTED-LOT",
                "reference": sku,
                "notes": "Synthetic verification statement: supplier disputes the recorded warehouse lot. This is not real supplier evidence.",
            }
            submitted = call(
                "POST", f"/incidents/{incident['id']}/supplier-evidence", json=statement
            )
            duplicate = call(
                "POST", f"/incidents/{incident['id']}/supplier-evidence", json=statement
            )
            assert (
                submitted["evidence_id"] == duplicate["evidence_id"]
                and submitted["event_id"] == duplicate["event_id"]
            )
            final = wait_for(
                incident["id"],
                lambda d: any(
                    r["event_id"] == submitted["event_id"]
                    and r["status"] == "completed"
                    for r in d["runs"]
                ),
            )
            run = next(
                r for r in final["runs"] if r["event_id"] == submitted["event_id"]
            )
            decisions = [
                d
                for d in final["decisions"]
                if d["run_id"] == run["id"] and d["inventory_lot_id"] == stock["id"]
            ]
            assert decisions and decisions[0]["verdict"] == "conflict"
            assert decisions[0]["action"] == "preserve_hold_and_review"
            assert run["llm_mode"] == "llm_assisted"
            assert any(
                h["id"] == holds[0]["id"]
                and h["status"] == "active"
                and h["quantity"] == 3
                for h in final["holds"]
            )
            assert any(
                e["id"] == submitted["evidence_id"] and e["synthetic"]
                for e in final["evidence"]
            )
            planner = next(
                s for s in run["steps"] if s["tool"] == "llm_investigation_planner"
            )
            report["checks"]["supplier_reassessment"] = {
                "run_id": run["id"],
                "llm_mode": run["llm_mode"],
                "evidence_id": submitted["evidence_id"],
                "verdict": decisions[0]["verdict"],
                "action": decisions[0]["action"],
                "held_units": 3,
                "duplicate_submission_idempotent": True,
                "latency_ms": run["latency_ms"],
                "provider": planner["output"].get("provider"),
            }
            report["success"] = True
        except Exception as exc:
            report["success"] = False
            report["error"] = (
                str(exc)
                if isinstance(exc, (AssertionError, RuntimeError))
                else type(exc).__name__
            )
        Path(args.output).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
