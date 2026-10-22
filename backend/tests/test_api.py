import pytest
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def test_health_and_api_version(client):
    assert client.get("/api/health").json()["database"] == "postgresql"
    assert client.get("/api/v1/health").status_code == 200


def test_unknown_route_and_consistent_errors(client):
    assert client.get("/api/no-such-route").status_code == 404
    result = client.post("/api/demo/replay/next", json={})
    assert result.status_code == 422
    assert "error" in result.json()


def test_public_demo_cannot_read_or_mutate_live_business(client, monkeypatch):
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "operator_token", "secret-test-token")
    for path in [
        "/api/dashboard?mode=live",
        "/api/inventory?mode=live",
        "/api/incidents?mode=live",
        "/api/recalls",
    ]:
        assert client.get(path).status_code == 403
    assert (
        client.post("/api/recalls/sync", json={"source": "snapshot"}).status_code == 403
    )
    assert client.get("/api/dashboard?mode=replay").status_code == 200
    assert (
        client.get(
            "/api/dashboard?mode=live",
            headers={"Authorization": "Bearer secret-test-token"},
        ).status_code
        == 200
    )


def test_release_requires_explicit_authorized_human(client, monkeypatch):
    replay = client.post("/api/demo/replay/start", json={}).json()
    replay = client.post(
        "/api/demo/replay/next", json={"replay_id": replay["id"], "expected_step": 0}
    ).json()
    incident_id = replay["incident_id"]
    hold = replay["detail"]["holds"][0]
    body = {
        "action": "release_hold",
        "hold_id": hold["id"],
        "reason": "Verified physical stock and supplier batch documents.",
    }
    assert (
        client.post(f"/api/incidents/{incident_id}/review", json=body).status_code
        == 403
    )
    monkeypatch.setattr(settings, "operator_token", "review-test-token")
    r = client.post(
        f"/api/incidents/{incident_id}/review",
        json=body,
        headers={"Authorization": "Bearer review-test-token"},
    )
    assert r.status_code == 200
    r = client.get(
        f"/api/incidents/{incident_id}",
        headers={"Authorization": "Bearer review-test-token"},
    )
    assert r.json()["holds"][0]["status"] == "released"
    assert any(h["kind"] == "human_review" for h in r.json()["history"])


def test_invalid_csv_shows_row_error(client):
    response = client.post(
        "/api/inventory/import",
        data={"mode": "replay"},
        files={
            "file": (
                "bad.csv",
                b"sku,product_name,gtin,lot,quantity,supplier,expires_on\nx,Test,broken,,5,,\n",
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    assert response.json()["errors"][0]["row"] == 2
