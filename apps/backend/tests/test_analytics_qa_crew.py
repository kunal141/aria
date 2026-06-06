"""
Deterministic tests for the Analytics+QA CrewAI crew (Week 22).
All tests use the mock path (no LLM) so they are fully deterministic.
"""
import json
import pytest
from aria.crews.analytics_qa_crew import AnalyticsQACrew, CrewResult


@pytest.fixture()
def crew():
    return AnalyticsQACrew()


# ── CrewResult schema ─────────────────────────────────────────────────────────

def test_crew_result_fields():
    r = CrewResult(
        investigation_summary="CTR dropped 18%.",
        root_causes=["Algorithm change"],
        recommended_actions=["Revert model"],
        test_cases=["Test CTR baseline"],
    )
    assert r.version == "v1"
    assert r.confidence_score == 0.0


# ── Mock run ──────────────────────────────────────────────────────────────────

def test_mock_run_returns_crew_result(crew):
    result = crew.run("CTR dropped 18% on recommendation feed this week", "t-crew-1")
    assert isinstance(result, CrewResult)


def test_mock_run_crew_mode_is_mock(crew):
    result = crew.run("Feed ranking degraded after model update", "t-crew-2")
    assert result.crew_mode == "mock"


def test_mock_run_investigation_summary_nonempty(crew):
    result = crew.run("Notification CTR down 12% this week", "t-crew-3")
    assert result.investigation_summary
    assert len(result.investigation_summary) > 0


def test_mock_run_root_causes_list(crew):
    result = crew.run("Analytics pipeline processing 30% fewer events", "t-crew-4")
    assert isinstance(result.root_causes, list)


def test_mock_run_test_cases_list(crew):
    result = crew.run("Feed engagement dropped after A/B test rollout", "t-crew-5")
    assert isinstance(result.test_cases, list)


def test_mock_run_confidence_score_in_range(crew):
    result = crew.run("CMS ingestion pipeline throughput halved", "t-crew-6")
    assert 0.0 <= result.confidence_score <= 1.0


def test_mock_run_serialises_to_json(crew):
    result = crew.run("CTR anomaly on recommendation feed", "t-crew-7")
    raw = result.model_dump_json()
    parsed = json.loads(raw)
    assert "investigation_summary" in parsed
    assert "root_causes" in parsed
    assert "test_cases" in parsed
    assert "recommended_actions" in parsed
    assert "confidence_score" in parsed
    assert "crew_mode" in parsed


# ── Dry-run ───────────────────────────────────────────────────────────────────

def test_dry_run_returns_immediately(crew):
    result = crew.run("CTR dropped", "t-dry", dry_run=True)
    assert result.crew_mode == "dry_run"
    assert result.root_causes == []
    assert result.test_cases == []


# ── analytics_qa_crew_node ────────────────────────────────────────────────────

def _make_state(raw_input: str, task_id: str, execution_mode: str = "live") -> dict:
    return {
        "raw_input":          raw_input,
        "task_id":            task_id,
        "task_type":          "kpi",
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


def test_crew_node_returns_expected_keys():
    from aria.nodes.skill_nodes import analytics_qa_crew_node
    state = _make_state("CTR dropped 18% on recommendation feed", "t-node-crew-1")
    result = analytics_qa_crew_node(state)
    assert "skill_name" in result
    assert "skill_output" in result
    assert "steps_completed" in result
    assert result["skill_name"].startswith("analytics_qa_crew:")
    assert "analytics_qa_crew_node" in result["steps_completed"]


def test_crew_node_skill_output_is_valid_json():
    from aria.nodes.skill_nodes import analytics_qa_crew_node
    state = _make_state("Notification CTR anomaly", "t-node-crew-2")
    result = analytics_qa_crew_node(state)
    parsed = json.loads(result["skill_output"])
    assert "investigation_summary" in parsed
    assert "crew_mode" in parsed


def test_crew_node_dry_run():
    from aria.nodes.skill_nodes import analytics_qa_crew_node
    state = _make_state("CTR dropped", "t-node-crew-dry", execution_mode="dry_run")
    result = analytics_qa_crew_node(state)
    parsed = json.loads(result["skill_output"])
    assert parsed["crew_mode"] == "dry_run"
