"""Play the real API journey; accepts an operator token through the environment."""

import json
import os
import httpx

base = os.environ.get("RECALLOPS_URL", "http://127.0.0.1:8080")
token = os.environ.get("OPERATOR_TOKEN", "")
with httpx.Client(
    base_url=base,
    headers={"Authorization": f"Bearer {token}"} if token else {},
    timeout=90,
) as client:
    response = client.post("/api/demo/replay/start", json={})
    response.raise_for_status()
    replay = response.json()
    print("Replay:", replay["id"])
    for step in range(3):
        if step:
            response = client.post(
                "/api/demo/replay/next",
                json={"replay_id": replay["id"], "expected_step": step - 1},
            )
            response.raise_for_status()
            replay = response.json()
        detail = replay["detail"]
        run = detail["runs"][-1]
        print(
            json.dumps(
                {
                    "stage": step + 1,
                    "status": detail["incident"]["status"],
                    "held_units": sum(
                        h["quantity"]
                        for h in detail["holds"]
                        if h["status"] == "active"
                    ),
                    "decisions": [
                        (d["lot"], d["verdict"])
                        for d in detail["decisions"]
                        if d["run_id"] == run["id"]
                    ],
                    "latency_ms": run["latency_ms"],
                },
                indent=2,
            )
        )
