"""Opt-in integration rehearsal: real government/model APIs, fictional store stock.

Runs against the Docker app, advances a new replay, and adds labeled synthetic
inventory to its store. Uses provider credits when configured. Prints a JSON
report without secrets; progress goes to stderr. Never sends notifications.

docker compose cp scripts/live_integration.py app:/tmp/live_integration.py
docker compose exec -T -e PYTHONPATH=/app/backend app python /tmp/live_integration.py /tmp/live-test-results.json
docker compose cp app:/tmp/live-test-results.json docs/live-test-results.json
"""

import csv
import io
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from threading import Event as Signal, Thread

import httpx
from app.core.config import settings
from app.services.matching import parse_identification

report = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "checks": [],
    "inventory_and_supplier_data": "Fictional test data, never official stock records",
    "runs": [],
    "source": {},
    "external_notifications_sent": 0,
}


def check(name, condition, details=None):
    report["checks"].append(
        {"name": name, "passed": bool(condition), "details": details}
    )
    print(f'{"PASS" if condition else "FAIL"}: {name}', file=sys.stderr, flush=True)


headers = (
    {"Authorization": f"Bearer {settings.operator_token}"}
    if settings.operator_token
    else {}
)
client = httpx.Client(base_url="http://127.0.0.1:8080", headers=headers, timeout=180)


def api(method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


def capture(detail, stage):
    run = detail["runs"][-1]
    decisions = [d for d in detail["decisions"] if d["run_id"] == run["id"]]
    planner = [s for s in run["steps"] if s.get("tool") == "llm_investigation_planner"]
    report["runs"].append(
        {
            "stage": stage,
            "incident_id": detail["incident"]["id"],
            "run_id": run["id"],
            "event_id": run["event_id"],
            "status": run["status"],
            "llm_mode": run["llm_mode"],
            "latency_ms": run["latency_ms"],
            "provider": planner[-1]["output"].get("provider") if planner else None,
            "planner_output": planner[-1]["output"] if planner else None,
            "tools": [s.get("tool") for s in run["steps"]],
            "decisions": decisions,
            "holds": detail["holds"],
            "recall_version_id": run["recall_version_id"],
        }
    )
    check(
        stage + ": completed real LLM workflow",
        run["status"] == "completed" and run["llm_mode"] == "llm_assisted",
    )
    check(
        stage + ": decisions reference evidence",
        bool(decisions) and all(d["evidence_ids"] for d in decisions),
    )
    check(
        stage + ": operational draft cites actual contributing evidence",
        all(eid in run["draft"] for d in decisions for eid in d["evidence_ids"]),
    )
    active = {
        h["inventory_lot_id"]: h for h in detail["holds"] if h["status"] == "active"
    }
    check(
        stage + ": operational draft reflects recorded hold state",
        all(
            (
                f"Active internal hold: {active[d['inventory_lot_id']]['quantity']} units."
                if d["inventory_lot_id"] in active
                else "No active internal hold is recorded."
            )
            in run["draft"]
            for d in decisions
        ),
    )
    return decisions


def await_run(incident_id, event_id=None):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        detail = api("GET", f"/api/incidents/{incident_id}")
        if any(
            r["status"] == "completed"
            and (event_id is None or r["event_id"] == event_id)
            for r in detail["runs"]
        ):
            return detail
        time.sleep(0.5)
    raise TimeoutError("Background investigation did not complete within 90 seconds")


try:
    check("PostgreSQL health", api("GET", "/api/health")["status"] == "ok")
    check("Model key loaded by running app", api("GET", "/api/settings")["llm_enabled"])
    sync = api("POST", "/api/recalls/sync", json={"source": "live"})
    report["source"]["sync"] = sync
    check(
        "Government API live ingestion without fixture fallback",
        sync["origin"] == "live" and not sync["errors"],
        sync,
    )
    report["source"]["settings_after_sync"] = api("GET", "/api/settings")

    replay = api("POST", "/api/demo/replay/start", json={})
    report["replay_id"] = replay["id"]
    official = replay["detail"]["recall"]
    with httpx.Client(timeout=30) as government:
        response = government.get(
            settings.source_url, params={"where": "id=17010", "limit": 100}
        )
        response.raise_for_status()
        rows = response.json()["results"]
    strip_projection = lambda row: {k: v for k, v in row.items() if k != "gtin"}
    check(
        "Archived demonstration scope reverified against live official API",
        any(strip_projection(row) == strip_projection(official["raw"]) for row in rows),
    )
    report["source"]["historical_recall"] = {
        k: official[k]
        for k in ("source_id", "source_url", "published_at", "version_id")
    }
    decisions = capture(replay["detail"], "Initial historical scenario")
    check(
        "Known nonaffected lot excluded; missing lot reviewed",
        sorted(d["verdict"] for d in decisions) == ["review", "unaffected"]
        and not replay["detail"]["holds"],
    )
    replay = api(
        "POST",
        "/api/demo/replay/next",
        json={"replay_id": replay["id"], "expected_step": 0},
    )
    capture(replay["detail"], "Warehouse confirms recalled lot")
    holds = replay["detail"]["holds"]
    check(
        "Exactly one internal hold for 24 units",
        len(holds) == 1
        and holds[0]["quantity"] == 24
        and holds[0]["status"] == "active",
    )
    duplicate = api(
        "POST",
        "/api/demo/replay/next",
        json={"replay_id": replay["id"], "expected_step": 0},
    )
    check(
        "Duplicate replay event does not duplicate run or hold",
        duplicate["step"] == 1
        and len(duplicate["detail"]["runs"]) == 2
        and len(duplicate["detail"]["holds"]) == 1,
    )
    replay = api(
        "POST",
        "/api/demo/replay/next",
        json={"replay_id": replay["id"], "expected_step": 1},
    )
    capture(replay["detail"], "Supplier contradicts warehouse")
    check(
        "Conflict preserves the same protective hold",
        replay["detail"]["incident"]["status"] == "conflict"
        and replay["detail"]["holds"][0]["id"] == holds[0]["id"]
        and replay["detail"]["holds"][0]["status"] == "active",
    )
    rejected = client.post(
        f'/api/incidents/{replay["incident_id"]}/review',
        headers={"Authorization": "Bearer deliberately-invalid-test-token"},
        json={
            "action": "release_hold",
            "hold_id": holds[0]["id"],
            "reason": "Synthetic unauthorized release test",
        },
    )
    check("Unauthorized hold release rejected", rejected.status_code in {401, 403})

    # Select a second genuine record fetched now, not a built-in scenario fixture.
    with httpx.Client(timeout=30) as government:
        response = government.get(
            settings.source_url,
            params={"limit": 100, "order_by": "date_publication desc"},
        )
        response.raise_for_status()
        latest = response.json()["results"]
    chosen = None
    for raw in latest:
        targets, warnings = parse_identification(
            raw.get("identification_produits"), raw.get("gtin")
        )
        if (
            not warnings
            and len(targets) == 1
            and targets[0].lots
            and str(raw["id"]) != "17010"
        ):
            chosen = (raw, targets[0])
            break
    if not chosen:
        raise ValueError(
            "No simple independently fetched lot-specific recall found; do not invent a source"
        )
    raw, target = chosen
    report["source"]["additional_live_recall"] = raw
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["sku", "product_name", "gtin", "lot", "quantity", "supplier", "expires_on"]
    )
    prefix = "LIVE-TEST-" + replay["id"][:8]
    for suffix, lot, qty in [
        ("AFFECTED", target.lots[0], 7),
        ("OTHER", "SYNTHETIC-EXCLUDED-LOT", 9),
        ("UNKNOWN", "", 3),
    ]:
        writer.writerow(
            [
                prefix + "-" + suffix,
                "FICTIONAL TEST STOCK: " + raw.get("libelle", ""),
                target.gtin,
                lot,
                qty,
                "Fictional integration-test supplier",
                target.date_start or "",
            ]
        )
    imported = api(
        "POST",
        "/api/inventory/import",
        data={"mode": "replay"},
        files={
            "file": ("fictional-live-source-test.csv", buffer.getvalue(), "text/csv")
        },
    )
    check(
        "CSV import accepts all three fictional test rows",
        imported["imported"] == 3 and not imported["errors"],
        imported,
    )
    incidents = api("GET", "/api/incidents", params={"mode": "replay"})["items"]
    incident = next(i for i in incidents if i["reference"] == str(raw["numero_fiche"]))
    detail = await_run(incident["id"])
    decisions = capture(detail, "New live-source record with uploaded synthetic stock")
    check(
        "Fresh-source matching: affected, excluded, missing",
        sorted(d["verdict"] for d in decisions) == ["affected", "review", "unaffected"],
    )
    check(
        "Fresh-source hold covers exactly seven units",
        len(detail["holds"]) == 1 and detail["holds"][0]["quantity"] == 7,
    )

    stock = next(i for i in detail["inventory"] if i["sku"] == prefix + "-AFFECTED")
    statement = {
        "inventory_lot_id": stock["id"],
        "supplier": "Fictional integration-test supplier",
        "lot": "SYNTHETIC-CONTRADICTORY-LOT",
        "reference": prefix,
        "notes": "Synthetic test statement contradicting the warehouse lot; no real supplier communication occurred.",
    }
    # Subscribe before submitting so the SSE check observes actual worker transitions.
    ready, observed = Signal(), Signal()
    stream_result = {}

    def listen():
        try:
            with httpx.Client(
                base_url="http://127.0.0.1:8080", headers=headers, timeout=40
            ) as stream_client:
                with stream_client.stream("GET", "/api/events/stream") as stream:
                    stream.raise_for_status()
                    ready.set()
                    for line in stream.iter_lines():
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            if (
                                event.get("incident_id") == incident["id"]
                                and event.get("kind") == "workflow_transition"
                            ):
                                stream_result.update(event)
                                observed.set()
                                return
        except Exception as exc:
            stream_result["error_type"] = type(exc).__name__
            ready.set()

    thread = Thread(target=listen, daemon=True)
    thread.start()
    ready.wait(5)
    path = f'/api/incidents/{incident["id"]}/supplier-evidence'
    submitted = api("POST", path, json=statement)
    repeated = api("POST", path, json=statement)
    check(
        "Supplier intake deduplicates evidence and queued event",
        submitted["event_id"] == repeated["event_id"]
        and submitted["evidence_id"] == repeated["evidence_id"],
    )
    revised = await_run(incident["id"], submitted["event_id"])
    capture(revised, "API supplier correction handled by background worker")
    check(
        "Supplier API automatically reopens incident and preserves seven-unit hold",
        revised["incident"]["status"] == "conflict"
        and len(revised["holds"]) == 1
        and revised["holds"][0]["status"] == "active"
        and revised["holds"][0]["quantity"] == 7,
    )
    check(
        "Supplier test evidence remains explicitly synthetic",
        any(
            e["id"] == submitted["evidence_id"] and e["synthetic"]
            for e in revised["evidence"]
        ),
    )
    check(
        "SSE delivers a real investigation transition", observed.wait(5), stream_result
    )
    report["additional_incident_id"] = incident["id"]
    check("Frontend served", client.get("/").status_code == 200)
except Exception as exc:
    # Do not serialize exception request headers, credentials, or provider bodies.
    check("Integration script completed", False, {"error_type": type(exc).__name__})
finally:
    client.close()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = all(c["passed"] for c in report["checks"])
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(serialized + "\n")
        print(
            json.dumps(
                {
                    "passed": report["passed"],
                    "checks": len(report["checks"]),
                    "report": sys.argv[1],
                }
            )
        )
    else:
        print(serialized)
sys.exit(0 if report["passed"] else 1)
