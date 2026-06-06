"""
skill_nodes.py — Week 19

Real skill implementations:
  kpi_node         → Week 6  ✅ DONE
  pr_review_node   → Week 7  ✅ DONE
  qa_node          → Week 17 ✅ DONE
  test_review_node → Week 18 ✅ DONE
  ci_cd_node       → Week 19 ✅ DONE
  jira_node        → Week 20
"""
from aria.state import ARIAState
from aria.skills import skill_registry
from aria.skills.kpi_skill import KPIInput, run as kpi_run
from aria.skills.pr_review_skill import PRReviewInput, run as pr_review_run
from aria.skills.qa_skill import QAInput, run as qa_run
from aria.skills.test_review_skill import TestReviewInput, run as test_review_run
from aria.skills.ci_cd_skill import CICDInput, run as ci_cd_run
from aria.notifications.notifier import notify_ci_cd_failure


# Register skills on module load
skill_registry.register(
    name="kpi",
    fn=kpi_run,
    version="v1",
    description="Investigates KPI drops and anomalies for Amar Ujala media platform",
    action_tier=2,
)

skill_registry.register(
    name="pr_review",
    fn=pr_review_run,
    version="v1",
    description="Reviews pull requests for code quality, risk, and business impact",
    action_tier=2,
)

skill_registry.register(
    name="qa",
    fn=qa_run,
    version="v1",
    description="Generates test cases (functional, edge, negative) for engineering features",
    action_tier=2,
)

skill_registry.register(
    name="test_review",
    fn=test_review_run,
    version="v1",
    description="Reviews existing test suites for quality, flakiness, and regression risks",
    action_tier=2,
)

skill_registry.register(
    name="ci_cd",
    fn=ci_cd_run,
    version="v1",
    description="Analyses CI/CD pipeline failures — root causes, fix suggestions, deployment safety verdict",
    action_tier=2,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_KNOWN_PIPELINES = [
    "recommendation-service",
    "notification-service",
    "cms-ingestion",
    "analytics-pipeline",
    "feed-ranking-service",
]


def _infer_pipeline_name(raw_input: str) -> str:
    """Extract a known pipeline name from the raw input, or return empty string."""
    lower = raw_input.lower()
    for name in _KNOWN_PIPELINES:
        if name in lower or name.replace("-", " ") in lower:
            return name
    return ""


def _routing_kwargs(state: ARIAState) -> dict:
    """Extract routing signals from state with safe defaults."""
    return {
        "data_sensitivity": state.get("data_sensitivity") or "internal",
        "audience":         state.get("audience") or "developer",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Skill nodes
# ─────────────────────────────────────────────────────────────────────────────

def kpi_node(state: ARIAState) -> dict:
    rk = _routing_kwargs(state)
    skill_meta = skill_registry.get("kpi")
    result = skill_meta.fn(KPIInput(
        raw_input=state["raw_input"],
        task_id=state["task_id"],
        **rk,
    ))
    return {
        "skill_name":      f"kpi:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["kpi_node"],
    }


def pr_review_node(state: ARIAState) -> dict:
    rk = _routing_kwargs(state)
    skill_meta = skill_registry.get("pr_review")
    result = skill_meta.fn(PRReviewInput(
        raw_input=state["raw_input"],
        task_id=state["task_id"],
        **rk,
    ))
    return {
        "skill_name":      f"pr_review:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["pr_review_node"],
    }


def qa_node(state: ARIAState) -> dict:
    rk = _routing_kwargs(state)
    skill_meta = skill_registry.get("qa")
    result = skill_meta.fn(QAInput(
        raw_input=state["raw_input"],
        task_id=state["task_id"],
        **rk,
    ))
    return {
        "skill_name":      f"qa:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["qa_node"],
    }


def test_review_node(state: ARIAState) -> dict:
    rk = _routing_kwargs(state)
    skill_meta = skill_registry.get("test_review")
    result = skill_meta.fn(TestReviewInput(
        raw_input=state["raw_input"],
        task_id=state["task_id"],
        **rk,
    ))
    return {
        "skill_name":      f"test_review:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["test_review_node"],
    }


def ci_cd_node(state: ARIAState) -> dict:
    rk = _routing_kwargs(state)
    pipeline_name = _infer_pipeline_name(state["raw_input"])
    skill_meta = skill_registry.get("ci_cd")
    result = skill_meta.fn(CICDInput(
        raw_input=state["raw_input"],
        task_id=state["task_id"],
        pipeline_name=pipeline_name,
        **rk,
    ))

    # Proactive notification — governed by notify_team flag on skill output
    notify_ci_cd_failure(
        task_id=state["task_id"],
        pipeline_name=pipeline_name,
        failure_summary=result.failure_summary,
        severity=result.severity,
        suggested_fix=result.suggested_fixes[0] if result.suggested_fixes else "See skill output",
        notify_team=result.notify_team,
    )

    return {
        "skill_name":      f"ci_cd:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["ci_cd_node"],
    }


def jira_node(state: ARIAState) -> dict:
    return {
        "skill_name":      "jira:placeholder",
        "skill_output":    f"[Week 20] Jira skill will create ticket for: '{state['raw_input'][:80]}'",
        "steps_completed": state["steps_completed"] + ["jira_node"],
    }


def general_node(state: ARIAState) -> dict:
    return {
        "skill_name":      "general:placeholder",
        "skill_output":    f"[Week 4] General handler: '{state['raw_input'][:80]}'",
        "steps_completed": state["steps_completed"] + ["general_node"],
    }
