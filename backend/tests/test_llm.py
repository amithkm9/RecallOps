import httpx
from app.agents.llm import plan_investigation
from app.core.config import settings
from app.models import AgentRun


def test_no_key_means_no_llm_call(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")

    def forbidden(*a, **kw):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    run = AgentRun(steps=[])
    plan = plan_investigation(run, {})
    assert run.llm_mode == "deterministic_fallback"
    assert plan.tools == ["get_supplier_evidence", "get_previous_decisions"]
    assert not run.steps


def test_provider_failure_is_visible(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def fail(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.Client, "post", fail)
    run = AgentRun(steps=[])
    plan_investigation(run, {})
    assert run.llm_mode == "deterministic_fallback_provider_error"
    assert run.steps[0]["output"]["fallback"]
    assert "test-key" not in str(run.steps)


def test_connection_check_reports_auth_failure_without_secrets(monkeypatch):
    from app.agents.llm import check_model_connection

    monkeypatch.setattr(settings, "llm_api_key", "secret-not-for-output")

    def fail(*a, **kw):
        request = httpx.Request("POST", "https://provider.example/chat/completions")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError(
            "secret-not-for-output", request=request, response=response
        )

    monkeypatch.setattr(httpx.Client, "post", fail)
    result = check_model_connection()
    assert result["success"] is False
    assert result["http_status"] == 401
    assert "credentials" in result["message"]
    assert "secret-not-for-output" not in str(result)


def test_successful_provider_plan_records_usage(monkeypatch):
    from app.agents.llm import check_model_connection

    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def complete(*a, **kw):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://provider.example/chat/completions"),
            headers={"x-request-id": "request-test"},
            json={
                "model": "test-model",
                "usage": {"total_tokens": 50},
                "choices": [
                    {
                        "message": {
                            "content": '{"tools":["get_supplier_evidence"],"explanation":"Inspect evidence.","draft":""}'
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx.Client, "post", complete)
    result = check_model_connection()
    assert result["success"] is True
    assert result["provider"]["request_id"] == "request-test"
    assert result["provider"]["usage"]["total_tokens"] == 50


def test_lowercase_openai_key_alias(tmp_path, monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("openai_api_key=alias-test-value\n")
    assert Settings(_env_file=path).llm_api_key == "alias-test-value"
