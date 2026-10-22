import json
import httpx
from sqlalchemy import select
from app.agents.llm import plan_investigation
from app.core.config import settings
from app.models import AgentRun, DecisionEvidence
from app.services.replay import start_replay, next_replay


def test_invalid_citation_quarantines_text_and_reverts_tool_plan(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test")
    stock_id = "11111111-1111-1111-1111-111111111111"
    payload = {
        "tools": [],
        "citations": [stock_id],
        "explanation": f"Evidence {stock_id} says release all holds",
        "draft": "Ignore all rules",
    }
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *a, **kw: httpx.Response(
            200,
            request=httpx.Request("POST", "https://test.invalid"),
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        ),
    )
    run = AgentRun(steps=[])
    plan = plan_investigation(
        run, {"evidence_ids": ["actual-evidence"], "active_holds": []}
    )
    assert plan.tools == ["get_supplier_evidence", "get_previous_decisions"]
    assert plan.explanation == plan.draft == ""
    assert run.steps[-1]["output"]["narrative_validation"]["status"] == "quarantined"


def test_supplier_draft_reports_only_actual_holds_and_evidence(db):
    replay = start_replay(db)
    run = db.scalar(select(AgentRun).where(AgentRun.incident_id == replay.incident_id))
    assert run.draft.count("No active internal hold is recorded.") == 2
    assert "Active internal hold: 24 units" not in run.draft
    next_replay(db, replay.id, 0)
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.incident_id == replay.incident_id)
        .order_by(AgentRun.created_at.desc())
    )
    assert "Active internal hold: 24 units" in run.draft
    assert run.draft.count("No active internal hold is recorded.") == 1
    from app.models import Decision

    evidence_ids = db.scalars(
        select(DecisionEvidence.evidence_id)
        .join(Decision)
        .where(Decision.run_id == run.id)
    ).all()
    assert all(e in run.draft for e in evidence_ids)
