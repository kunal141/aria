"""
Tests for the Jira T4 (Execute-with-Approval) path — Week 21.

Covers:
  - _wants_create() keyword detection
  - run() approval_required flag set correctly for create vs draft intent
  - jira_node T4 approval flow: pending → registered; approved → harness executes
"""
import json
import pytest

from aria.runtime.harness import clear_idem_cache
from aria.governance import approval_gate


@pytest.fixture(autouse=True)
def reset():
    clear_idem_cache()
    approval_gate.clear()
    yield
    clear_idem_cache()
    approval_gate.clear()


# ── _wants_create keyword detection ──────────────────────────────────────────

from aria.skills.jira_skill import _wants_create, JiraInput, run as jira_run


@pytest.mark.parametrize("text", [
    "create ticket for this bug",
    "please create a ticket",
    "create a ticket for the ES timeout issue",
    "file a ticket in Jira",
    "file ticket for this regression",
    "create now — it's a blocker",
    "go ahead and create the ticket",
    "actually create it",
    "submit ticket for the analytics OOM",
    "create it now",
])
def test_wants_create_true(text):
    assert _wants_create(text) is True, f"Expected True for: {text!r}"


@pytest.mark.parametrize("text", [
    "Fix the Elasticsearch timeout in CI",
    "Add rate limiting to notification service",
    "Investigate CTR drop on recommendation feed",
    "Sprint blocker: analytics pipeline OOM",
    "Review my PR for the feed ranking service",
    "We should probably open a ticket for this",
    "Draft a ticket for the next sprint",
    "What ticket should we create?",
])
def test_wants_create_false(text):
    assert _wants_create(text) is False, f"Expected False for: {text!r}"


# ── run() approval_required flag ─────────────────────────────────────────────

def test_run_draft_intent_approval_required_false():
    out = jira_run(JiraInput(raw_input="Fix ES timeout in recommendation CI", task_id="t-1"))
    assert out.approval_required is False
    assert out.action_taken == "draft_created"


def test_run_create_intent_approval_required_true():
    out = jira_run(JiraInput(
        raw_input="Please create a ticket for the ES timeout issue",
        task_id="t-2",
    ))
    assert out.approval_required is True
    assert out.action_taken == "would_require_approval"


# ── jira_node — T4 pending (no approval yet) ─────────────────────────────────

def _make_state(raw_input: str, task_id: str, execution_mode: str = "live") -> dict:
    return {
        "raw_input":          raw_input,
        "task_id":            task_id,
        "task_type":          "jira",
        "task_status":        "executing",
        "routing_reason":     "",
        "steps_completed":    ["intake", "router"],
        "skill_name":         None,
        "skill_output":       None,
        "response":           None,
        "messages":           [],
        "error":              None,
        "audience":           "developer",
        "langsmith_run_id":   None,
        "routing_tier":       "smart",
        "complexity":         None,
        "approval_request_id": None,
        "data_sensitivity":   "internal",
        "execution_mode":     execution_mode,
        "token_budget":       None,
        "token_budget_used":  None,
    }


def test_jira_node_t4_registers_approval_request():
    from aria.nodes.skill_nodes import jira_node
    state = _make_state("Please create a ticket for the ES timeout", "t-node-t4-1")
    result = jira_node(state)
    # approval_request_id should be set in updates
    assert "approval_request_id" in result
    assert result["approval_request_id"] is not None
    # Gate must have a pending request
    pending = [r for r in approval_gate.get_for_task("t-node-t4-1") if r.status == "pending"]
    assert len(pending) == 1
    assert pending[0].tool_name == "jira_create"


def test_jira_node_draft_does_not_register_approval():
    from aria.nodes.skill_nodes import jira_node
    state = _make_state("Fix the ES timeout in CI", "t-node-draft-1")
    result = jira_node(state)
    assert "approval_request_id" not in result
    assert approval_gate.get_for_task("t-node-draft-1") == []


# ── jira_node — T4 approved path (harness executes mock) ─────────────────────

def test_jira_node_t4_approved_executes_via_harness():
    from aria.nodes.skill_nodes import jira_node

    task_id = "t-node-t4-approved"
    # Pre-approve jira_create for this task
    req = approval_gate.request_approval(
        task_id=task_id,
        tool_name="jira_create",
        proposed_action="Create Jira ticket",
        action_tier="T4",
    )
    approval_gate.approve(req.request_id, approved_by="kunal")

    state = _make_state("Please create a ticket for the ES timeout", task_id)
    result = jira_node(state)

    # skill_output should contain the created ticket info
    payload = json.loads(result["skill_output"])
    assert "created_ticket_id" in payload
    # Employer-neutral mock id (M4); tenant keys arrive via TenantOrgProfile.
    assert payload["created_ticket_id"] == "ENG-MOCK"


def test_jira_node_t4_approved_dry_run_does_not_annotate():
    from aria.nodes.skill_nodes import jira_node

    task_id = "t-node-t4-dry"
    req = approval_gate.request_approval(
        task_id=task_id,
        tool_name="jira_create",
        proposed_action="Create Jira ticket",
        action_tier="T4",
    )
    approval_gate.approve(req.request_id, approved_by="kunal")

    state = _make_state("Please create a ticket for the ES timeout", task_id, execution_mode="dry_run")
    result = jira_node(state)

    # Dry-run: harness does not call mock, so created_ticket_id must NOT be added
    payload = json.loads(result["skill_output"])
    assert "created_ticket_id" not in payload
