"""Investigator tests do not contact model providers or alter production data."""

from copy import deepcopy
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.agents.investigator import run_investigator, verify_with_claims
from app.core.config import settings
from app.models import (
    AgentRun,
    Decision,
    DecisionEvidence,
    Event,
    Evidence,
    Incident,
    InventoryHold,
    InventoryLot,
)

STOCK = {
    "id": "stock-1",
    "sku": "SALMON",
    "gtin": "3760099533007",
    "lot": None,
    "expires_on": "2024-12-20",
    "quantity": 24,
}
TARGETS = [
    {
        "gtin": STOCK["gtin"],
        "lots": ["24326020"],
        "date_start": "2024-12-20",
        "date_end": "2024-12-20",
    }
]
CLAIM = {
    "id": "claim-1",
    "document_id": "document-1",
    "validation_evidence_id": "validation-1",
    "inventory_lot_id": STOCK["id"],
    "status": "accepted",
    "gtin": STOCK["gtin"],
    "lot": "24326020",
    "expires_on": "2024-12-20",
}


def test_verified_association_fills_only_missing_fields_with_full_provenance():
    stock = deepcopy(STOCK)
    result = verify_with_claims(stock, TARGETS, [], [CLAIM])
    assert result["verdict"] == "affected"
    assert result["effective_stock"]["lot"] == "24326020"
    assert set(result["evidence_ids"]) == {"claim-1", "document-1", "validation-1"}
    assert stock == STOCK


@pytest.mark.parametrize(
    "change",
    [
        {"status": "unconfirmed"},
        {"inventory_lot_id": "another-stock"},
        {"validation_evidence_id": None},
        {"status": "rejected"},
    ],
)
def test_unvalidated_or_unassociated_claim_cannot_establish_stock(change):
    result = verify_with_claims(STOCK, TARGETS, [], [{**CLAIM, **change}])
    assert result["verdict"] == "review"
    assert result["effective_stock"]["lot"] is None
    assert result["evidence_ids"] == []


@pytest.mark.parametrize(
    "stock,claims",
    [
        ({**STOCK, "lot": "WAREHOUSE"}, [CLAIM]),
        (STOCK, [CLAIM, {**CLAIM, "id": "second", "lot": "OTHER"}]),
        (STOCK, [{**CLAIM, "expires_on": "2024-12-21"}]),
    ],
)
def test_contradictory_validated_facts_force_conflict(stock, claims):
    result = verify_with_claims(stock, TARGETS, [], claims)
    assert result["verdict"] == "conflict"
    assert "Preserve any existing hold" in result["explanation"]


class FakeTools:
    def __init__(self, claims=(), fail=False):
        self.claims, self.retrieved, self.calls, self.fail = (
            list(claims),
            False,
            [],
            fail,
        )

    def call(self, name, node, **args):
        self.calls.append((name, args.get("inventory_lot_id")))
        if name == "check_lot_constraints":
            return verify_with_claims(
                STOCK, TARGETS, [], self.claims if self.retrieved else []
            )
        if name == "search_delivery_records":
            if self.fail:
                raise OSError("sensitive internal path")
            self.retrieved = True
            return self.claims
        return []


def loop(claims=(), strategy="adaptive", **kwargs):
    tools = FakeTools(claims)
    state = {
        "inventory": [STOCK],
        "verifications": {STOCK["id"]: verify_with_claims(STOCK, TARGETS, [], [])},
        "evidence_ids": ["official", "warehouse"],
    }
    run = AgentRun(steps=[])
    result = run_investigator(
        tools, run, state, {"model_disabled": True}, strategy=strategy, **kwargs
    )
    return tools, result


def test_retrieval_changes_verification_and_records_frozen_evidence():
    tools, result = loop([CLAIM])
    assert result["verifications"][STOCK["id"]]["verdict"] == "affected"
    assert result["investigator"]["stop_reason"] == "resolved"
    assert result["investigator"]["claims_by_inventory"][STOCK["id"]] == [CLAIM]
    assert "validation-1" in result["investigator"]["available_evidence_ids"]
    assert result["investigator"]["questions"] == []
    assert sum(name == "search_delivery_records" for name, _ in tools.calls) == 1


def test_ambiguous_candidates_request_association_without_accepting():
    _, result = loop(
        [
            {**CLAIM, "status": "unconfirmed"},
            {**CLAIM, "id": "claim-2", "status": "unconfirmed", "lot": "OTHER"},
        ]
    )
    assert result["verifications"][STOCK["id"]]["verdict"] == "review"
    question = result["investigator"]["questions"][0]
    assert question["kind"] == "association"
    assert question["candidate_claim_ids"] == ["claim-1", "claim-2"]


def test_no_evidence_requests_specific_missing_fact_and_never_repeats_tool():
    tools, result = loop()
    question = result["investigator"]["questions"][0]
    assert question["fields"] == ["lot"]
    assert "shipment reference" in question["prompt"]
    retrieval = [c for c in tools.calls if c[0] != "check_lot_constraints"]
    assert len(retrieval) == len(set(retrieval))


def test_call_and_time_limits_stop_and_request_human_input():
    tools, result = loop([CLAIM], max_calls=1)
    assert result["investigator"]["stop_reason"] == "tool_limit"
    assert result["investigator"]["metrics"]["tool_calls"] == 1
    assert result["investigator"]["questions"]
    tools, result = loop([CLAIM], max_seconds=0)
    assert not tools.calls
    assert result["investigator"]["stop_reason"] == "time_limit"


def test_baseline_ignores_delivery_facts_fixed_and_adaptive_use_same_rules():
    _, baseline = loop([CLAIM], strategy="baseline")
    _, fixed = loop([CLAIM], strategy="fixed")
    _, adaptive = loop([CLAIM])
    assert baseline["verifications"][STOCK["id"]]["verdict"] == "review"
    assert fixed["verifications"] == adaptive["verifications"]
    assert (
        fixed["investigator"]["metrics"]["tool_calls"]
        > adaptive["investigator"]["metrics"]["tool_calls"]
    )


def test_provider_failure_is_visible_and_uses_bounded_deterministic_fallback(
    monkeypatch,
):
    monkeypatch.setattr(settings, "llm_api_key", "private-test-key")
    calls = []

    def fail(*a, **kw):
        calls.append(1)
        raise httpx.ConnectError("private-test-key")

    monkeypatch.setattr(httpx.Client, "post", fail)
    tools, run = FakeTools([CLAIM]), AgentRun(steps=[])
    result = run_investigator(
        tools,
        run,
        {
            "inventory": [STOCK],
            "evidence_ids": [],
            "verifications": {STOCK["id"]: verify_with_claims(STOCK, TARGETS, [], [])},
        },
        {},
    )
    assert result["investigator"]["mode"] == "deterministic_fallback_provider_error"
    assert result["verifications"][STOCK["id"]]["verdict"] == "affected"
    assert len(calls) == 1
    assert "private-test-key" not in str(run.steps)


def test_delivery_claim_retrieval_persists_provenance_without_mutating_warehouse(
    db, monkeypatch
):
    import json

    monkeypatch.setattr(settings, "llm_api_key", "mock-provider-only")

    def choose(*a, **kw):
        context = json.loads(kw["json"]["messages"][-1]["content"])
        available = context["available_actions"]
        selected = next(
            (
                action
                for action in available
                if action["tool"] == "search_delivery_records"
            ),
            available[0],
        )
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://test.invalid"),
            json={
                "model": "mock-model",
                "usage": {"total_tokens": 12},
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"actions": [selected], "tools": []})
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx.Client, "post", choose)
    from app.services.replay import start_replay
    from app.services.investigator_evidence import (
        import_delivery,
        list_delivery_candidates,
        validate_claim,
    )
    from app.schemas.investigator import ValidateClaimIn
    from app.services.events import process_event

    replay = start_replay(db)
    incident = db.get(Incident, replay.incident_id)
    stock = db.scalar(
        select(InventoryLot).where(
            InventoryLot.store_id == replay.store_id, InventoryLot.lot.is_(None)
        )
    )
    source = f"delivery_id,sku,gtin,lot,quantity,reference,expires_on\nD-104,{stock.sku},{stock.gtin},24326020,24,shipment-104,2024-12-20\n".encode()
    imported = import_delivery(db, incident, "delivery.csv", source, "test-operator")
    process_event(imported["event_id"])
    claim = list_delivery_candidates(db, incident.id, stock.id)[0]
    validated = validate_claim(
        db,
        incident,
        claim["id"],
        ValidateClaimIn(
            inventory_lot_id=stock.id,
            accept=True,
            reason="Checked shipment reference and physical stock label",
        ),
        "test-operator",
    )
    run_id = process_event(validated["event_id"])
    db.expire_all()
    decision = db.scalar(
        select(Decision).where(
            Decision.run_id == run_id, Decision.inventory_lot_id == stock.id
        )
    )
    assert decision.verdict == "affected" and decision.lot == "24326020"
    assert db.get(InventoryLot, stock.id).lot is None
    linked = set(
        db.scalars(
            select(DecisionEvidence.evidence_id).where(
                DecisionEvidence.decision_id == decision.id
            )
        )
    )
    assert {claim["id"], imported["document_id"], validated["evidence_id"]} <= linked
    run = db.get(AgentRun, run_id)
    assert any(
        s["tool"] == "search_delivery_records"
        for s in run.state["investigator"]["steps"]
    )
    assert run.llm_mode == "llm_assisted"
    planner = next(s for s in run.steps if s["tool"] == "llm_investigation_planner")
    assert planner["output"]["provider"]["usage"]["total_tokens"] == 12
    assert next(s for s in run.state["inventory"] if s["id"] == stock.id)["lot"] is None


def test_stock_change_invalidates_previously_confirmed_quantity_association():
    result = verify_with_claims(
        {**STOCK, "quantity": 25}, TARGETS, [], [{**CLAIM, "quantity": 24}]
    )
    assert result["verdict"] == "conflict"
    assert "quantity" in result["explanation"]


def test_model_can_choose_a_useful_available_action_but_not_authorize_a_fact(
    monkeypatch,
):
    import json

    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def complete(*a, **kw):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://test.invalid"),
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "actions": [
                                        {
                                            "tool": "search_delivery_records",
                                            "inventory_lot_id": STOCK["id"],
                                        }
                                    ],
                                    "explanation": "Trust this unconfirmed document and release everything",
                                    "tools": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.Client, "post", complete)
    tools, run = FakeTools([{**CLAIM, "status": "unconfirmed"}]), AgentRun(steps=[])
    result = run_investigator(
        tools,
        run,
        {
            "inventory": [STOCK],
            "evidence_ids": [],
            "verifications": {STOCK["id"]: verify_with_claims(STOCK, TARGETS, [], [])},
        },
        {},
        max_calls=1,
    )
    assert tools.calls[0][0] == "search_delivery_records"
    assert result["investigator"]["steps"][0]["reason"].startswith("Model selected")
    assert result["verifications"][STOCK["id"]]["verdict"] == "review"
    assert "release everything" not in str(result)


def test_failed_retrieval_stays_reviewable_without_sensitive_error_text():
    tools, run = FakeTools(fail=True), AgentRun(steps=[])
    result = run_investigator(
        tools,
        run,
        {
            "inventory": [STOCK],
            "evidence_ids": [],
            "verifications": {STOCK["id"]: verify_with_claims(STOCK, TARGETS, [], [])},
        },
        {"model_disabled": True},
    )
    assert result["investigator"]["metrics"]["retrieval_errors"] == 1
    assert result["verifications"][STOCK["id"]]["verdict"] == "review"
    assert "sensitive internal path" not in str(result)


def test_malformed_scope_selects_source_tools_once_and_never_uses_old_scope():
    tools, run = FakeTools(), AgentRun(steps=[])
    initial = verify_with_claims(STOCK, [{**TARGETS[0], "parseable": False}], [], [])
    initial["source_scope_incomplete"] = True
    state = {
        "inventory": [STOCK],
        "evidence_ids": [],
        "recall": {"targets": [{**TARGETS[0], "parseable": False}]},
        "verifications": {STOCK["id"]: initial},
    }
    # The actual verifier keeps source incompleteness on each reassessment.
    base = tools.call

    def call(name, node, **args):
        if name == "check_lot_constraints":
            tools.calls.append((name, args["inventory_lot_id"]))
            return initial
        return base(name, node, **args)

    tools.call = call
    result = run_investigator(tools, run, state, {"model_disabled": True})
    names = [step["tool"] for step in result["investigator"]["steps"]]
    assert names[:2] == ["compare_recall_versions", "inspect_official_documents"]
    assert names.count("compare_recall_versions") == 1
    assert result["verifications"][STOCK["id"]]["verdict"] == "review"
    assert result["investigator"]["questions"][0]["kind"] == "official_scope"


def test_unsupported_model_action_falls_back_without_executing_it(monkeypatch):
    import json

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *a, **kw: httpx.Response(
            200,
            request=httpx.Request("POST", "https://test.invalid"),
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "actions": [
                                        {
                                            "tool": "release_inventory_hold",
                                            "inventory_lot_id": STOCK["id"],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        ),
    )
    tools, run = FakeTools([CLAIM]), AgentRun(steps=[])
    result = run_investigator(
        tools,
        run,
        {
            "inventory": [STOCK],
            "evidence_ids": [],
            "verifications": {STOCK["id"]: verify_with_claims(STOCK, TARGETS, [], [])},
        },
        {},
    )
    assert not any(name == "release_inventory_hold" for name, _ in tools.calls)
    assert result["investigator"]["mode"] == "deterministic_fallback_provider_error"
    assert result["verifications"][STOCK["id"]]["verdict"] == "affected"


def test_source_tools_are_pinned_and_exclude_future_versions_and_other_documents(db):
    from datetime import timedelta
    from app.agents.tools import InvestigationTools, ToolInput
    from app.models import RecallVersion
    from app.repositories.records import add_evidence, record
    from app.services.replay import start_replay

    replay = start_replay(db)
    incident = db.get(Incident, replay.incident_id)
    run = db.get(AgentRun, replay.events[0]["run_id"])
    pinned = db.get(RecallVersion, run.recall_version_id)
    future_values = {
        key: value
        for key, value in record(pinned).items()
        if key not in {"id", "created_at", "published_at", "source_updated_at"}
    }
    future = RecallVersion(
        **{
            **future_values,
            "content_hash": "future-" + run.id,
            "published_at": pinned.published_at,
            "created_at": pinned.created_at + timedelta(days=1),
            "official_version": "future-test",
        }
    )
    db.add(future)
    db.flush()
    current_doc = add_evidence(
        db,
        incident.id,
        "official_document",
        "Pinned document",
        {
            "pages": [{"page": 1, "text": "Human interpretation needed"}],
            "text_status": "extracted",
        },
        recall_version_id=pinned.id,
    )
    future_doc = add_evidence(
        db,
        incident.id,
        "official_document",
        "Future document",
        {"pages": [{"page": 1, "text": "Future data must not enter old run"}]},
        recall_version_id=future.id,
    )
    tools = InvestigationTools(db, incident, run)
    args = ToolInput(incident_id=incident.id)
    assert all(
        row["recall_version_id"] != future.id
        for row in tools.compare_recall_versions(args)
    )
    docs = tools.inspect_official_documents(args)
    assert current_doc.id in {d["id"] for d in docs}
    assert future_doc.id not in {d["id"] for d in docs}
    assert all(not d["scope_verified"] for d in docs)


def test_confirmed_prior_case_guides_search_but_never_supplies_current_batch(db):
    from app.agents.tools import InvestigationTools, ToolInput
    from app.repositories.records import add_evidence
    from app.services.evaluation import create_case
    from app.services.investigator_evaluation import seed_memory_route

    case = {
        "name": "Memory provenance",
        "scope": "3760099533007$A1$non concerné$$",
        "gtin": STOCK["gtin"],
        "lot": None,
        "product_name": "Salmon",
        "recall_name": "Salmon",
    }
    incident, stock, event = create_case(db, case, commit=False)
    hint = seed_memory_route(db, incident, stock)
    run = AgentRun(
        incident_id=incident.id,
        event_id=event.id,
        recall_version_id=event.payload["recall_version_id"],
        steps=[],
    )
    tools = InvestigationTools(db, incident, run)
    args = ToolInput(incident_id=incident.id, inventory_lot_id=stock.id)
    hints = tools.get_retrieval_hints(args)
    assert hints and hints[0]["id"] == hint.id
    assert "PRIOR-ONLY-NOT-CURRENT" not in str(hints)
    assert tools.search_delivery_records(args) == []
    assert tools.check_lot_constraints(args)["verdict"] == "review"
    # A later rejection invalidates the remembered association rather than
    # silently retaining stale confirmation as an active retrieval hint.
    validation = db.get(Evidence, hint.payload["validation_evidence_id"])
    add_evidence(
        db,
        hint.incident_id,
        "claim_validation",
        "Rejected historical association",
        {
            "claim_id": validation.payload["claim_id"],
            "accept": False,
            "supersedes_validation_id": validation.id,
        },
        inventory_lot_id=stock.id,
        synthetic=True,
    )
    assert tools.get_retrieval_hints(args) == []


def test_oversized_model_context_uses_local_fallback_without_provider_call(monkeypatch):
    from app.agents.llm import plan_investigation

    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def forbidden(*a, **kw):
        raise AssertionError("Oversized context must not reach the provider")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    run = AgentRun(steps=[])
    plan = plan_investigation(run, {"untrusted_document": "x" * 50_001})
    assert not plan.actions
    assert run.llm_mode == "deterministic_fallback_context_limit"
    assert run.steps[-1]["output"]["provider_called"] is False
    assert "untrusted_document" not in str(run.steps)


def test_large_inventory_prioritizes_the_event_stock_within_retrieval_budget():
    inventory = [{**STOCK, "id": f"stock-{i}"} for i in range(20)]

    class ManyStockTools:
        def call(self, name, node, **args):
            if name == "check_lot_constraints":
                stock = next(
                    s for s in inventory if s["id"] == args["inventory_lot_id"]
                )
                return verify_with_claims(stock, TARGETS, [], [])
            return []

    result = run_investigator(
        ManyStockTools(),
        AgentRun(steps=[]),
        {
            "inventory": inventory,
            "evidence_ids": [],
            "verifications": {
                s["id"]: verify_with_claims(s, TARGETS, [], []) for s in inventory
            },
        },
        {
            "model_disabled": True,
            "memory_enabled": False,
            "focus_inventory_lot_id": "stock-19",
        },
        max_calls=1,
    )
    assert result["investigator"]["steps"][0]["inventory_lot_id"] == "stock-19"
    assert len(result["investigator"]["questions"]) == 20
    assert all(r["verdict"] == "review" for r in result["verifications"].values())


def test_retry_after_committed_decisions_preserves_the_original_evidence_snapshot(
    db, monkeypatch
):
    from app.agents.tools import InvestigationTools
    from app.repositories.records import add_evidence
    from app.services.evaluation import create_case
    from app.services.events import process_event
    from app.services.investigator_evaluation import seed_claims

    incident, stock, event = create_case(
        db,
        {
            "name": "Retry snapshot",
            "scope": "3760099533007$A1$non concerné$$",
            "gtin": STOCK["gtin"],
            "lot": None,
            "product_name": "Salmon",
            "recall_name": "Salmon",
        },
        commit=False,
    )
    seed_claims(db, incident, stock, [{"lot": "A1", "accepted": True}])
    db.commit()
    original = InvestigationTools.prepare_supplier_notification
    failed = []

    def fail_once(self, args):
        if not failed:
            failed.append(True)
            raise RuntimeError("Simulated interruption after execution committed")
        return original(self, args)

    monkeypatch.setattr(InvestigationTools, "prepare_supplier_notification", fail_once)
    with pytest.raises(RuntimeError):
        process_event(event.id)
    db.expire_all()
    run = db.scalar(select(AgentRun).where(AgentRun.event_id == event.id))
    frozen = deepcopy(run.state)
    assert frozen["decisions"] and run.status == "retrying"
    late = add_evidence(
        db,
        incident.id,
        "supplier",
        "Evidence arriving after committed decision",
        {"lot": "DIFFERENT"},
        inventory_lot_id=stock.id,
        synthetic=True,
    )
    db.commit()
    process_event(event.id)
    db.expire_all()
    completed = db.get(AgentRun, run.id)
    assert completed.status == "completed"
    assert completed.state["verifications"] == frozen["verifications"]
    assert completed.state["investigator"] == frozen["investigator"]
    assert late.id not in completed.state["evidence_ids"]
    assert len(list(db.scalars(select(Decision).where(Decision.run_id == run.id)))) == 1


def test_planner_validation_diagnostics_exclude_input_and_keep_usage(monkeypatch):
    import json
    from app.agents.llm import plan_investigation

    monkeypatch.setattr(settings, "llm_api_key", "secret-key-never-print")
    malformed = {
        "actions": {
            "tool": "search_delivery_records",
            "inventory_lot_id": "PRIVATE-SOURCE-TEXT",
        },
        "tools": ["search_delivery_records"],
    }
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *a, **kw: httpx.Response(
            200,
            request=httpx.Request("POST", "https://test.invalid"),
            json={
                "model": "mock",
                "usage": {"total_tokens": 20},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(malformed)},
                    }
                ],
            },
        ),
    )
    run = AgentRun(steps=[])
    plan_investigation(
        run,
        {
            "available_actions": [
                {"tool": "search_delivery_records", "inventory_lot_id": "stock"}
            ]
        },
    )
    output = run.steps[-1]["output"]
    assert {e["type"] for e in output["validation_errors"]} == {
        "list_type",
        "literal_error",
    }
    assert all(set(e) == {"loc", "type", "msg"} for e in output["validation_errors"])
    assert "PRIVATE-SOURCE-TEXT" not in str(output)
    assert "secret-key-never-print" not in str(output)
    assert output["failed_provider_response"]["usage"]["total_tokens"] == 20


def test_adaptive_prompt_has_one_unambiguous_array_contract():
    from app.agents.llm import planner_instructions

    adaptive = planner_instructions({"available_actions": []})
    assert '"actions":[{' in adaptive
    assert '"tools":[]' in adaptive
    assert "legacy tools field MUST be an EMPTY ARRAY" in adaptive
    assert "get_previous_decisions" not in adaptive
    legacy = planner_instructions({})
    assert '"actions":[]' in legacy
    assert '"tools":["get_supplier_evidence"]' in legacy
