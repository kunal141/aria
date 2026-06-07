"""
End-to-end scenario tests — deterministic, no LLM, no network.

Six scenarios as directed by the Codex product review:
  1. KPI investigation       — kpi_node produces structured output
  2. Flaky-test analysis     — test_review_node handles flakiness input
  3. Jira T4 creation path   — approval gate gates ticket creation
  4. Privacy gate            — ModelRouter flags restricted data
  5. Idem key dedup          — execute() with same key, fn called once
  6. Malicious metadata      — injection attempts blocked at spec + scaffold
"""
import json

import pytest

from aria.nodes.skill_nodes import jira_node, kpi_node
from aria.nodes.skill_nodes import test_review_node as _test_review_node
from aria.routing.model_router import ModelRouter
from aria.runtime.harness import ToolCall, clear_idem_cache, execute, make_idem_key
from aria.runtime.budget import budget_tracker


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _make_state(task_id: str = "e2e-default", **kwargs) -> dict:
    base = {
        "task_id":             task_id,
        "raw_input":           "test input",
        "task_type":           None,
        "task_status":         "executing",
        "routing_reason":      None,
        "steps_completed":     [],
        "skill_name":          None,
        "skill_output":        None,
        "response":            None,
        "messages":            [],
        "error":               None,
        "audience":            "developer",
        "langsmith_run_id":    None,
        "routing_tier":        None,
        "complexity":          None,
        "approval_request_id": None,
        "data_sensitivity":    "internal",
        "execution_mode":      None,
        "token_budget":        None,
        "token_budget_used":   None,
    }
    base.update(kwargs)
    return base


@pytest.fixture(autouse=True)
def clean_state():
    """Reset approval gate and idem cache between tests."""
    from aria.governance.approval_gate import clear as clear_approvals
    clear_approvals()
    clear_idem_cache()
    budget_tracker.clear_all()
    yield
    clear_approvals()
    clear_idem_cache()
    budget_tracker.clear_all()


# ── Scenario 1: KPI investigation ─────────────────────────────────────────────

def test_e2e_kpi_investigation_returns_structured_output():
    state = _make_state(
        task_id="e2e-kpi-001",
        raw_input=(
            "Our CTR dropped 15% on the Hindi news feed after yesterday's 2pm deploy. "
            "Investigate root cause and suggest remediation."
        ),
    )
    result = kpi_node(state)
    assert result["skill_name"].startswith("kpi:")
    assert "kpi_node" in result["steps_completed"]


def test_e2e_kpi_investigation_output_is_valid_json():
    state = _make_state(
        task_id="e2e-kpi-002",
        raw_input="Feed engagement dropped 20% after notification service v3.1 rollout.",
    )
    result = kpi_node(state)
    data = json.loads(result["skill_output"])
    assert "version" in data


def test_e2e_kpi_investigation_steps_tracked():
    state = _make_state(
        task_id="e2e-kpi-003",
        raw_input="KPI anomaly on recommendation engine CTR.",
        steps_completed=["intake", "router"],
    )
    result = kpi_node(state)
    assert "intake" in result["steps_completed"]
    assert "router" in result["steps_completed"]
    assert "kpi_node" in result["steps_completed"]


# ── Scenario 2: Flaky-test analysis ───────────────────────────────────────────

def test_e2e_test_review_flakiness_returns_structured_output():
    state = _make_state(
        task_id="e2e-test-review-001",
        raw_input=(
            "test_feed_ranking_integration flakes in CI — fails 1 in 5 runs with "
            "TimeoutError. It passes locally every time. Diagnose."
        ),
    )
    result = _test_review_node(state)
    assert result["skill_name"].startswith("test_review:")
    assert "test_review_node" in result["steps_completed"]


def test_e2e_test_review_output_is_valid_json():
    state = _make_state(
        task_id="e2e-test-review-002",
        raw_input="test_recommendation_service_ctr is flaky — intermittent AssertionError.",
    )
    result = _test_review_node(state)
    data = json.loads(result["skill_output"])
    assert "version" in data


def test_e2e_test_review_preserves_prior_steps():
    state = _make_state(
        task_id="e2e-test-review-003",
        raw_input="Flaky test analysis for notification service.",
        steps_completed=["intake"],
    )
    result = _test_review_node(state)
    assert "intake" in result["steps_completed"]
    assert "test_review_node" in result["steps_completed"]


# ── Scenario 3: Jira T4 creation path ────────────────────────────────────────

def test_e2e_jira_draft_does_not_create_ticket():
    """
    Raw input without a create-intent keyword → draft only, no approval request.
    """
    state = _make_state(
        task_id="e2e-jira-draft-001",
        raw_input=(
            "The recommendation-service CI pipeline keeps timing out on Elasticsearch "
            "integration tests. Draft a bug ticket."
        ),
    )
    result = jira_node(state)
    assert result["skill_name"].startswith("jira:")
    # approval_request_id should NOT be set for a draft-only request
    assert result.get("approval_request_id") is None


def test_e2e_jira_create_intent_triggers_approval_request():
    """
    'create ticket' in input → approval_required path → approval request created.
    """
    task_id = "e2e-jira-t4-001"
    state = _make_state(
        task_id=task_id,
        raw_input="create ticket: authentication regression after yesterday's deploy.",
    )
    result = jira_node(state)
    assert "approval_request_id" in result
    assert result["approval_request_id"] is not None


def test_e2e_jira_t4_approved_creates_ticket():
    """
    After approving the T4 request, a second call to jira_node executes the real action.
    """
    from aria.governance.approval_gate import approve

    task_id = "e2e-jira-t4-002"
    state = _make_state(
        task_id=task_id,
        raw_input="create ticket for the authentication regression in production",
    )

    # First pass — register approval request
    result1 = jira_node(state)
    request_id = result1.get("approval_request_id")
    assert request_id is not None, "Approval request must be created before T4 execution"

    # Human approves
    approved = approve(request_id, approved_by="kunal")
    assert approved is not None
    assert approved.status == "approved"

    # Second pass — T4 executes through harness
    result2 = jira_node(state)
    output = json.loads(result2["skill_output"])
    assert "created_ticket_id" in output, (
        "T4 execution should annotate skill_output with created_ticket_id"
    )


def test_e2e_jira_t4_without_approval_does_not_create_ticket():
    """
    T4 path without approval must NOT create a ticket.
    The first jira_node call should request approval but not proceed.
    """
    task_id = "e2e-jira-t4-no-approval-001"
    state = _make_state(
        task_id=task_id,
        raw_input="create ticket: CI failure on notification service",
    )
    result = jira_node(state)
    # approval_request_id present means we're waiting — ticket not yet created
    output = json.loads(result["skill_output"])
    assert "created_ticket_id" not in output


# ── Scenario 4: Privacy gate ──────────────────────────────────────────────────

def test_e2e_model_router_flags_restricted_data():
    decision = ModelRouter().route(
        task_type="pr_review",
        data_sensitivity="restricted",
        audience="developer",
    )
    assert decision.privacy_note is not None
    assert "self-hosted" in decision.privacy_note.lower() or "restricted" in decision.privacy_note.lower()


def test_e2e_model_router_flags_confidential_data():
    decision = ModelRouter().route(
        task_type="kpi",
        data_sensitivity="confidential",
        audience="developer",
    )
    assert decision.privacy_note is not None


def test_e2e_model_router_internal_data_no_privacy_flag():
    """Internal data (the default) must not generate a privacy note."""
    decision = ModelRouter().route(
        task_type="pr_review",
        data_sensitivity="internal",
        audience="developer",
        input_length=500,
    )
    assert decision.privacy_note is None


def test_e2e_model_router_restricted_capped_at_smart_tier():
    """Restricted data is capped at smart tier to minimise external exposure."""
    decision = ModelRouter().route(
        task_type="pr_review",
        data_sensitivity="restricted",
        audience="leadership",   # Would normally route frontier
    )
    assert decision.tier == "smart"


# ── Scenario 5: Idem key prevents duplicate side-effects ─────────────────────

def test_e2e_idem_key_second_call_served_from_cache():
    """
    Two execute() calls with the same idem_key — fn called exactly once.
    Second call returns was_cached=True.
    """
    call_count = {"n": 0}

    def _side_effect_fn():
        call_count["n"] += 1
        return {"ticket_id": "AU-ENG-001"}

    idem = make_idem_key("e2e-idem-001", "jira_create", "ticket-title")
    call = ToolCall(
        task_id="e2e-idem-001",
        tool_name="jira_create",
        action_tier="T4",
        idem_key=idem,
    )

    from aria.governance.approval_gate import request_approval, approve
    req = request_approval(
        task_id="e2e-idem-001",
        tool_name="jira_create",
        proposed_action="Create test ticket",
    )
    approve(req.request_id, approved_by="kunal")

    result1 = execute(call, _side_effect_fn)
    result2 = execute(call, _side_effect_fn)

    assert result1.success
    assert result2.success
    assert result2.was_cached, "Second call must be served from idem cache"
    assert call_count["n"] == 1, "Side-effect function must be called exactly once"


def test_e2e_idem_key_different_keys_both_execute():
    """Two calls with distinct idem keys — fn called twice (no dedup)."""
    call_count = {"n": 0}

    def _fn():
        call_count["n"] += 1
        return {"status": "ok"}

    idem1 = make_idem_key("e2e-idem-002", "teams_message_send", "msg-1")
    idem2 = make_idem_key("e2e-idem-002", "teams_message_send", "msg-2")

    from aria.governance.approval_gate import request_approval, approve
    req = request_approval(
        task_id="e2e-idem-002",
        tool_name="teams_message_send",
        proposed_action="Send test message",
    )
    approve(req.request_id, approved_by="kunal")

    call1 = ToolCall(task_id="e2e-idem-002", tool_name="teams_message_send", action_tier="T4", idem_key=idem1)
    call2 = ToolCall(task_id="e2e-idem-002", tool_name="teams_message_send", action_tier="T4", idem_key=idem2)

    execute(call1, _fn)
    execute(call2, _fn)
    assert call_count["n"] == 2


def test_e2e_dry_run_skips_fn_without_executing():
    """Dry-run mode must return success without calling the underlying function."""
    called = {"n": 0}

    def _fn():
        called["n"] += 1
        return {"created": True}

    call = ToolCall(
        task_id="e2e-dry-run-001",
        tool_name="jira_draft",
        action_tier="T3",
        dry_run=True,
    )
    result = execute(call, _fn)
    assert result.success
    assert result.was_dry_run
    assert called["n"] == 0


# ── Scenario 6: Malicious metadata injection blocked ─────────────────────────

def test_e2e_spec_name_starting_with_digit_blocked():
    """Agent names that produce invalid Python identifiers must be rejected at spec creation."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="invalid Python identifier"):
        from aria.factory.agent_spec import AgentSpec
        AgentSpec(
            name="123-malicious",
            role="Attacker",
            goal="Gain access",
            backstory="Trying to inject",
        )


def test_e2e_spec_name_with_spaces_blocked():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="invalid Python identifier"):
        from aria.factory.agent_spec import AgentSpec
        AgentSpec(
            name="bad agent name",
            role="R",
            goal="G",
            backstory="B",
        )


def test_e2e_triple_quote_in_role_does_not_break_scaffold():
    """Triple-double-quotes in role must be escaped; generated code must compile."""
    from aria.factory.agent_spec import AgentSpec, AgentCapability
    from aria.factory.scaffold import scaffold_agent
    spec = AgentSpec(
        name="injection-test-aria",
        role='Specialist with """dangerous""" role',
        goal='Optimise """click-through""" rates.',
        backstory='Deep analyst with """industry""" knowledge.',
        capabilities=[AgentCapability(skill_name="kpi")],
    )
    source = scaffold_agent(spec)
    # Must compile without SyntaxError
    compile(source, "<scaffold>", "exec")
    # The raw triple-quote string must not appear in source (was escaped)
    assert '"""dangerous"""' not in source


def test_e2e_newline_in_capability_skill_name_blocked_in_scaffold():
    """Newline injection into capability skill_name must not break the scaffold."""
    from aria.factory.agent_spec import AgentSpec, AgentCapability
    from aria.factory.scaffold import scaffold_agent
    spec = AgentSpec(
        name="injection-test-aria",
        role="R",
        goal="G",
        backstory="B",
        capabilities=[AgentCapability(skill_name="kpi\nmalicious_import")],
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")


def test_e2e_backslash_in_owner_does_not_break_scaffold():
    """Windows-style backslash paths in owner must not produce invalid Unicode escapes."""
    from aria.factory.agent_spec import AgentSpec
    from aria.factory.scaffold import scaffold_agent
    spec = AgentSpec(
        name="injection-test-aria",
        role="R",
        goal="G",
        backstory="B",
        owner=r"domain\user\path",
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")


def test_e2e_version_with_double_quote_does_not_break_scaffold():
    """A version string with a double-quote must produce a compilable scaffold."""
    from aria.factory.agent_spec import AgentSpec, AgentCapability
    from aria.factory.scaffold import scaffold_agent
    spec = AgentSpec(
        name="injection-test-aria",
        role="R",
        goal="G",
        backstory="B",
        capabilities=[AgentCapability(skill_name="kpi")],
        version='v1"oops',
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")


def test_e2e_security_check_rejects_scaffold_with_injected_os_import():
    """
    Even if a malicious name somehow passed spec validation, the security scan
    at Stage 2 of the lifecycle must catch unsafe patterns in the generated source.
    """
    from aria.factory.lifecycle import security_check
    from aria.factory.agent_spec import AgentSpec
    spec = AgentSpec(name="clean-aria", role="R", goal="G", backstory="B")
    malicious_source = "import os\nos.system('rm -rf /')\n"
    result = security_check(spec, malicious_source)
    assert not result.passed
    assert len(result.issues) >= 2
