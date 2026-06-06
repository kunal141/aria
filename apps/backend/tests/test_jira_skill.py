"""
Deterministic tests for the Jira skill and jira_node.

No LLM, no network, no filesystem. All tests run against:
  - The mock path (has_llm() == False) of jira_skill.run()
  - JiraInput / JiraOutput / JiraTicketDraft schema validation
  - jira_node state-in / state-out contract
  - _build_jira_card output structure
"""
import json
import pytest

from aria.skills.jira_skill import (
    JiraInput,
    JiraOutput,
    JiraTicketDraft,
    run as jira_run,
    GOLDEN_EXAMPLES,
    EVAL_RUBRIC,
)


# ── Input schema ──────────────────────────────────────────────────────────────

def test_jira_input_defaults():
    inp = JiraInput(raw_input="Fix broken test", task_id="t-001")
    assert inp.project_key == "AU-ENG"
    assert inp.read_only is True
    assert inp.data_sensitivity == "internal"
    assert inp.audience == "developer"


def test_jira_input_project_key_override():
    inp = JiraInput(raw_input="Sprint blocker in QA", task_id="t-002", project_key="AU-QA")
    assert inp.project_key == "AU-QA"


# ── Mock output (no LLM) ──────────────────────────────────────────────────────

@pytest.fixture()
def mock_output() -> JiraOutput:
    return jira_run(JiraInput(raw_input="test input", task_id="t-mock"))


def test_mock_output_is_jira_output(mock_output):
    assert isinstance(mock_output, JiraOutput)


def test_mock_output_version(mock_output):
    assert mock_output.version == "v1"


def test_mock_output_action_taken(mock_output):
    assert mock_output.action_taken == "draft_created"


def test_mock_output_approval_required_false(mock_output):
    # V1 is always draft-only; no approval should be required
    assert mock_output.approval_required is False


def test_mock_output_has_ticket_draft(mock_output):
    assert isinstance(mock_output.ticket_draft, JiraTicketDraft)


def test_mock_draft_title_nonempty(mock_output):
    assert mock_output.ticket_draft.title
    assert len(mock_output.ticket_draft.title) <= 100


def test_mock_draft_ticket_type_valid(mock_output):
    valid = {"bug", "task", "story", "epic", "sub-task"}
    assert mock_output.ticket_draft.ticket_type in valid


def test_mock_draft_priority_valid(mock_output):
    valid = {"critical", "high", "medium", "low"}
    assert mock_output.ticket_draft.priority in valid


def test_mock_draft_acceptance_criteria_nonempty(mock_output):
    assert len(mock_output.ticket_draft.acceptance_criteria) >= 1


def test_mock_draft_labels_nonempty(mock_output):
    assert len(mock_output.ticket_draft.labels) >= 1


def test_mock_draft_project_key_propagated():
    out = jira_run(JiraInput(raw_input="test", task_id="t-pkey", project_key="AU-QA"))
    assert out.ticket_draft.project_key == "AU-QA"


def test_mock_output_sprint_impact_nonempty(mock_output):
    assert mock_output.sprint_impact


def test_mock_blocker_detected_is_bool(mock_output):
    assert isinstance(mock_output.blocker_detected, bool)


# ── JiraTicketDraft validation ────────────────────────────────────────────────

def test_ticket_draft_story_points_none_for_bug():
    """Bugs should have story_points=None (effort estimate doesn't apply)."""
    out = jira_run(JiraInput(raw_input="production bug", task_id="t-bug"))
    if out.ticket_draft.ticket_type == "bug":
        assert out.ticket_draft.story_points is None


def test_ticket_draft_blocker_for_is_list(mock_output):
    assert isinstance(mock_output.ticket_draft.blocker_for, list)


# ── Serialisation ─────────────────────────────────────────────────────────────

def test_output_serialises_to_json(mock_output):
    raw = mock_output.model_dump_json(indent=2)
    parsed = json.loads(raw)
    assert "ticket_draft" in parsed
    assert "action_taken" in parsed
    assert "approval_required" in parsed
    assert "blocker_detected" in parsed
    assert "sprint_impact" in parsed
    assert "version" in parsed


def test_ticket_draft_nested_in_json(mock_output):
    parsed = json.loads(mock_output.model_dump_json())
    draft = parsed["ticket_draft"]
    assert "title" in draft
    assert "ticket_type" in draft
    assert "priority" in draft
    assert "acceptance_criteria" in draft


# ── jira_node state contract ──────────────────────────────────────────────────

def test_jira_node_returns_expected_keys():
    from aria.nodes.skill_nodes import jira_node
    state = {
        "raw_input":        "Fix the recommendation service crash",
        "task_id":          "t-node-001",
        "task_type":        "jira",
        "task_status":      "executing",
        "routing_reason":   "keyword match",
        "steps_completed":  ["intake", "router"],
        "skill_name":       None,
        "skill_output":     None,
        "response":         None,
        "messages":         [],
        "error":            None,
        "audience":         "developer",
        "langsmith_run_id": None,
        "routing_tier":     "smart",
        "complexity":       None,
        "approval_request_id": None,
        "data_sensitivity": "internal",
    }
    result = jira_node(state)
    assert "skill_name" in result
    assert "skill_output" in result
    assert "steps_completed" in result
    assert result["skill_name"].startswith("jira:")
    assert "jira_node" in result["steps_completed"]


def test_jira_node_skill_output_is_valid_json():
    from aria.nodes.skill_nodes import jira_node
    state = {
        "raw_input":        "Create a ticket for the analytics pipeline OOM crash",
        "task_id":          "t-node-002",
        "task_type":        "jira",
        "task_status":      "executing",
        "routing_reason":   "",
        "steps_completed":  ["intake", "router"],
        "skill_name":       None,
        "skill_output":     None,
        "response":         None,
        "messages":         [],
        "error":            None,
        "audience":         "developer",
        "langsmith_run_id": None,
        "routing_tier":     "smart",
        "complexity":       None,
        "approval_request_id": None,
        "data_sensitivity": "internal",
    }
    result = jira_node(state)
    parsed = json.loads(result["skill_output"])
    assert "ticket_draft" in parsed


def test_jira_node_no_approval_request_id_in_v1():
    """V1 is draft-only; approval_request_id must not be set by jira_node."""
    from aria.nodes.skill_nodes import jira_node
    state = {
        "raw_input":        "Investigate feed ranking bug",
        "task_id":          "t-node-003",
        "task_type":        "jira",
        "task_status":      "executing",
        "routing_reason":   "",
        "steps_completed":  ["intake", "router"],
        "skill_name":       None,
        "skill_output":     None,
        "response":         None,
        "messages":         [],
        "error":            None,
        "audience":         "developer",
        "langsmith_run_id": None,
        "routing_tier":     "smart",
        "complexity":       None,
        "approval_request_id": None,
        "data_sensitivity": "internal",
    }
    result = jira_node(state)
    # approval_required=False in V1 mock → no approval_request_id key added
    assert "approval_request_id" not in result


# ── _build_jira_card structure ────────────────────────────────────────────────

def test_build_jira_card_returns_adaptive_card(mock_output):
    from aria.integrations.teams_bot import _build_jira_card
    data = json.loads(mock_output.model_dump_json())
    card = _build_jira_card(data, "task-abc-123")
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == "1.5"
    assert isinstance(card["body"], list)
    assert len(card["body"]) >= 3


def test_build_jira_card_has_three_actions(mock_output):
    from aria.integrations.teams_bot import _build_jira_card
    data = json.loads(mock_output.model_dump_json())
    card = _build_jira_card(data, "task-abc-123")
    assert len(card["actions"]) == 3
    titles = [a["title"] for a in card["actions"]]
    assert any("Create" in t for t in titles)
    assert any("Discard" in t for t in titles)


def test_build_card_routes_to_jira_card(mock_output):
    from aria.integrations.teams_bot import _build_card
    raw = mock_output.model_dump_json()
    card = _build_card("jira", raw, "task-xyz")
    assert card is not None
    assert card["type"] == "AdaptiveCard"


def test_build_card_returns_none_for_placeholder():
    from aria.integrations.teams_bot import _build_card
    card = _build_card("jira", "[Week 20] placeholder", "task-xyz")
    assert card is None


# ── Eval-Lite artefacts present ───────────────────────────────────────────────

def test_golden_examples_nonempty():
    assert len(GOLDEN_EXAMPLES) == 5


def test_golden_examples_have_required_keys():
    for ex in GOLDEN_EXAMPLES:
        assert "input" in ex
        assert "expected_type" in ex
        assert "expected_priority" in ex
        assert "expected_blocker" in ex


def test_eval_rubric_nonempty():
    assert len(EVAL_RUBRIC.strip()) > 0
