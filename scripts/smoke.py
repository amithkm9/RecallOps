"""Real PostgreSQL + HTTP API smoke journey; no external model or source required."""

import os
import sys

sys.path.insert(0, "backend")
os.environ["WORKER_ENABLED"] = "false"
os.environ["SOURCE_REFRESH_SECONDS"] = "0"
os.environ["LLM_API_KEY"] = ""  # Live provider testing is explicit in verify_live.py.
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    r = client.post("/api/demo/replay/start", json={})
    assert r.status_code == 200, r.text
    replay = r.json()
    assert [d["verdict"] for d in replay["detail"]["decisions"]] == [
        "unaffected",
        "review",
    ], replay
    assert not replay["detail"]["holds"]
    print("PASS: initial known lot unaffected, unknown lot reviewed, no holds")
    r = client.post(
        "/api/demo/replay/next", json={"replay_id": replay["id"], "expected_step": 0}
    )
    assert r.status_code == 200, r.text
    replay = r.json()
    assert (
        len(replay["detail"]["holds"]) == 1
        and replay["detail"]["holds"][0]["quantity"] == 24
    ), replay
    print("PASS: warehouse update creates one 24-unit internal hold")
    r = client.post(
        "/api/demo/replay/next", json={"replay_id": replay["id"], "expected_step": 0}
    )
    assert r.status_code == 200, r.text
    assert r.json()["step"] == 1
    r = client.post(
        "/api/demo/replay/next", json={"replay_id": replay["id"], "expected_step": 1}
    )
    assert r.status_code == 200, r.text
    replay = r.json()
    assert replay["detail"]["incident"]["status"] == "conflict", replay
    assert (
        len(replay["detail"]["holds"]) == 1
        and replay["detail"]["holds"][0]["status"] == "active"
    )
    assert len(replay["detail"]["runs"]) == 3
    print("PASS: contradictory supplier evidence preserves hold; all 3 runs persisted")
    for path in [
        "/api/dashboard",
        "/api/inventory",
        "/api/incidents",
        "/api/settings",
        f"/api/incidents/{replay['incident_id']}/evidence",
        f"/api/incidents/{replay['incident_id']}/history",
    ]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
    r = client.post("/api/evaluation/run", json={})
    assert r.status_code == 200, r.text
    evaluation = r.json()
    print("BENCHMARK:", evaluation["sample_size"], "labeled cases")
    for result in evaluation["results"]:
        print(result)
    import json
    from pathlib import Path

    Path("docs/last-benchmark.json").write_text(json.dumps(evaluation, indent=2) + "\n")
    print("PASS: all API smoke checks; benchmark saved to docs/last-benchmark.json")
