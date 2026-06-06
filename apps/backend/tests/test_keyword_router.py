"""
Unit tests for the keyword router (_keyword_classify).

These are fully deterministic — no LLM, no network, no filesystem.
They exercise the rule ordering and word-boundary matching that
caused regressions in earlier Codex reviews.
"""
import pytest
from aria.nodes.router import _keyword_classify


# ── happy-path routing ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    # PR review
    ("Please review my pull request for the recommendation engine", "pr_review"),
    ("Code review needed for this diff", "pr_review"),
    ("Approve the merge from feature/auth to main", "pr_review"),

    # KPI / metrics
    ("CTR dropped 18% this week, investigate", "kpi"),
    ("Our feed recommendation quality has degraded", "kpi"),
    ("There's a spike in error metrics on the notification service", "kpi"),

    # CI/CD
    ("Build failed on the notification service pipeline", "ci_cd"),
    ("Deploy failed for the recommendation service", "ci_cd"),
    ("GitHub Actions workflow is broken", "ci_cd"),
    ("Release blocked — pipeline red", "ci_cd"),

    # Jira
    ("Create a Jira ticket for this bug", "jira"),
    ("Sprint blocker: auth service is down", "jira"),
    ("Add this to the backlog", "jira"),

    # Test generation (QA)
    ("Generate unit tests for the UserService class", "qa"),
    ("Write integration tests for the payment flow", "qa"),
    ("We need better test coverage on the analytics module", "qa"),

    # Test review (diagnose existing tests)
    ("Our test suite has flaky tests, help me diagnose", "test_review"),
    ("Flakiness in the login tests is blocking CI", "test_review"),
    ("Review test quality in the recommendation service", "test_review"),
    ("Why are my tests failing intermittently?", "test_review"),

    # General
    ("What is the meaning of life?", "general"),
    ("Good morning", "general"),
])
def test_keyword_classify_happy_paths(text, expected):
    skill, _ = _keyword_classify(text)
    assert skill == expected, f"Expected {expected!r} for {text!r}, got {skill!r}"


# ── word-boundary false-positive guards ──────────────────────────────────────

@pytest.mark.parametrize("text, not_expected", [
    # "ci" must not match inside "pricing", "social", "special", etc.
    ("Adjust the pricing model for premium users", "ci_cd"),
    ("Social media performance review", "ci_cd"),

    # "cd" must not match inside "included", "scheduled"
    ("The feature is included in the next sprint", "ci_cd"),

    # "pr" must not match inside "improvement", "pricing"
    ("Continuous improvement process review", "pr_review"),

    # "kpi" only as full token — no word that contains "kpi" exists naturally,
    # but guard against "qa" inside "squash"
    ("We need to squash all the bugs before release", "qa"),
])
def test_word_boundary_no_false_positives(text, not_expected):
    skill, _ = _keyword_classify(text)
    assert skill != not_expected, (
        f"False positive: got {not_expected!r} for {text!r}"
    )


# ── rule ordering: test_review must beat ci_cd and qa ─────────────────────────

def test_ci_failing_routes_to_test_review_not_ci_cd():
    skill, _ = _keyword_classify("CI failing because of flaky tests")
    assert skill == "test_review"


def test_tests_failing_routes_to_test_review():
    skill, _ = _keyword_classify("Tests failing in the auth service")
    assert skill == "test_review"


def test_flakiness_routes_to_test_review():
    skill, _ = _keyword_classify("Flakiness in the recommendation tests is causing noise")
    assert skill == "test_review"


# ── routing reason is non-empty ───────────────────────────────────────────────

def test_routing_reason_always_returned():
    for text in ["review my PR", "CTR dropped", "build failed", "general query"]:
        skill, reason = _keyword_classify(text)
        assert reason, f"Empty routing_reason for {text!r} (skill={skill!r})"


# ── P2.5: analytics_qa routing ────────────────────────────────────────────────

def test_analytics_crew_keyword_routes_to_analytics_qa():
    skill, _ = _keyword_classify("Use the analytics crew to investigate the CTR drop")
    assert skill == "analytics_qa"


def test_deep_investigate_routes_to_analytics_qa():
    skill, _ = _keyword_classify("Deep investigate the KPI anomaly with multi-agent analysis")
    assert skill == "analytics_qa"


def test_analytics_qa_beats_kpi_when_crew_requested():
    skill, _ = _keyword_classify("analytics_qa investigation of the notification CTR")
    assert skill == "analytics_qa"


def test_kpi_keyword_alone_still_routes_to_kpi():
    skill, _ = _keyword_classify("CTR dropped 18% this week")
    assert skill == "kpi"


# ── P2.6: general_node uses Decision Intelligence ─────────────────────────────

def test_general_node_uses_decision_intelligence():
    """general_node must import and use aria.decision (P2.6 integration fix)."""
    from aria.nodes.skill_nodes import general_node
    import json

    state = {
        "task_id":         "t-general-di",
        "raw_input":       "What should ARIA do with this vague input?",
        "steps_completed": ["intake", "router"],
    }
    result = general_node(state)
    assert result["skill_name"].startswith("decision:")
    parsed = json.loads(result["skill_output"])
    assert "selected_option" in parsed
    assert "matrix" in parsed


# ── P2.8: registry list_agents skips versioned aliases ────────────────────────

def test_registry_list_agents_excludes_versioned_aliases():
    """list_agents() must not include deprecated @v1 alias keys (P2.8 fix)."""
    from aria.factory.registry import AgentRegistry
    from aria.factory.agent_spec import AgentSpec, AgentCapability

    r = AgentRegistry()
    spec_v1 = AgentSpec(name="dupe-agent", role="R", goal="G", backstory="B",
                        capabilities=[], status="active", version="v1")
    spec_v2 = AgentSpec(name="dupe-agent", role="R", goal="G", backstory="B",
                        capabilities=[], status="sandbox", version="v2")
    r.register(spec_v1)
    r.register(spec_v2)

    agents = r.list_agents()
    names  = [a.name for a in agents]
    assert "dupe-agent" in names
    assert "dupe-agent@v1" not in names
    assert len([n for n in names if n.startswith("dupe-agent")]) == 1
