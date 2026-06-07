"""
skill_nodes.py — Week 22

Real skill implementations:
  kpi_node              → Week 6  ✅ DONE
  pr_review_node        → Week 7  ✅ DONE
  qa_node               → Week 17 ✅ DONE
  test_review_node      → Week 18 ✅ DONE
  ci_cd_node            → Week 19 ✅ DONE
  jira_node             → Week 20 ✅ DONE
  analytics_qa_crew_node→ Week 22 ✅ DONE  (CrewAI multi-agent)
"""
from typing import Optional

from aria.state import ARIAState
from aria.skills import skill_registry
from aria.skills.kpi_skill import KPIInput, run as kpi_run
from aria.skills.pr_review_skill import PRReviewInput, run as pr_review_run
from aria.skills.qa_skill import QAInput, run as qa_run
from aria.skills.test_review_skill import TestReviewInput, run as test_review_run
from aria.skills.ci_cd_skill import CICDInput, run as ci_cd_run
from aria.skills.jira_skill import JiraInput, run as jira_run
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

skill_registry.register(
    name="jira",
    fn=jira_run,
    version="v1",
    description="Drafts structured Jira tickets from natural language — bug/task/story/epic with acceptance criteria",
    action_tier=3,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _guard_budget(state: ARIAState, estimated_tokens: int) -> Optional[dict]:
    """
    Pre-execution budget check. Call at the start of each skill node before
    any LLM call. Returns an error state dict if budget is exhausted, None if
    the node may proceed. consume() is called here — not in respond — so the
    budget is reserved before the work begins, not measured after.
    """
    task_id = state["task_id"]
    try:
        from aria.runtime.budget import budget_tracker
        if not budget_tracker.consume(task_id, estimated_tokens):
            remaining = budget_tracker.remaining(task_id)
            return {
                "skill_name":      "budget_exceeded",
                "skill_output":    (
                    f"[Budget exceeded: need {estimated_tokens} tokens, "
                    f"{remaining} remaining for task {task_id[:12]}]"
                ),
                "steps_completed": state["steps_completed"] + ["budget_check"],
                "task_status":     "failed",
                "error":           (
                    f"Token budget exceeded ({remaining} remaining, "
                    f"{estimated_tokens} required)"
                ),
            }
    except Exception:
        pass
    return None


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
    budget_err = _guard_budget(state, 3000)
    if budget_err:
        return budget_err
    rk = _routing_kwargs(state)
    skill_meta = skill_registry.get("kpi")
    result = skill_meta.fn(KPIInput(
        raw_input=state["raw_input"],
        task_id=state["task_id"],
        **rk,
    ))

    # Platform Intelligence — evidence assembly after skill execution
    platform_evidence_json: Optional[str] = None
    try:
        platform_evidence_json = _assemble_kpi_evidence(state)
    except Exception:
        pass  # Evidence layer failure must never break the skill path

    updates = {
        "skill_name":      f"kpi:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["kpi_node"],
    }
    if platform_evidence_json:
        updates["platform_evidence"] = platform_evidence_json
    return updates


def _assemble_kpi_evidence(state: ARIAState) -> Optional[str]:
    """
    Build an EvidencedAnswer for the KPI query using Platform Intelligence.

    Infers which services are relevant from raw_input.
    Caller's clearance comes from the state's data_sensitivity field.
    Returns the JSON-serialised EvidencedAnswer, or None if assembly cannot proceed.
    """
    from aria.platform.catalog import ServiceCatalog, InMemoryCatalogStore
    from aria.platform.sources import SourceRepository
    from aria.platform.fixtures import load_fixtures_into
    from aria.platform.evidence import EvidenceAssembler
    from aria.platform.models import ClaimSpec, SensitivityLevel

    # Map ARIAState data_sensitivity to platform SensitivityLevel
    raw_sens = (state.get("data_sensitivity") or "internal").lower()
    # "confidential" maps to "restricted" — platform layer has no "confidential" level
    _sens_map = {"public": "public", "internal": "internal",
                 "confidential": "restricted", "restricted": "restricted"}
    caller_level: SensitivityLevel = _sens_map.get(raw_sens, "internal")  # type: ignore[assignment]

    # Build fresh in-memory catalog + source repo populated with fixtures
    catalog = ServiceCatalog(InMemoryCatalogStore())
    source_repo = SourceRepository()
    load_fixtures_into(catalog, source_repo, include_restricted=False)

    # Infer relevant service from the query (fall back to all 5 services)
    pipeline = _infer_pipeline_name(state["raw_input"])
    service_ids = [pipeline] if pipeline else _KNOWN_PIPELINES

    claims = [
        ClaimSpec(
            claim_id="service-health",
            claim_text=f"Current health and telemetry for {', '.join(service_ids)}",
            service_ids=service_ids,
            source_types=["telemetry", "ci"],
            keywords=["error", "latency", "ctr", "throughput", "failed", "health"],
        ),
        ClaimSpec(
            claim_id="recent-issues",
            claim_text=f"Recent blockers or CI failures for {', '.join(service_ids)}",
            service_ids=service_ids,
            source_types=["jira", "ci", "repository"],
            keywords=["blocker", "failing", "regression", "timeout", "issue"],
        ),
    ]

    assembler = EvidenceAssembler(catalog, source_repo)
    evidenced = assembler.assemble(
        query=state["raw_input"],
        claims=claims,
        caller_level=caller_level,
    )
    return evidenced.model_dump_json(indent=2)


def pr_review_node(state: ARIAState) -> dict:
    budget_err = _guard_budget(state, 3000)
    if budget_err:
        return budget_err
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
    budget_err = _guard_budget(state, 3000)
    if budget_err:
        return budget_err
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
    budget_err = _guard_budget(state, 3000)
    if budget_err:
        return budget_err
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
    budget_err = _guard_budget(state, 3000)
    if budget_err:
        return budget_err
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

    # Platform Intelligence — pipeline state + dependency impact evidence
    platform_evidence_json: Optional[str] = None
    try:
        platform_evidence_json = _assemble_cicd_evidence(state)
    except Exception:
        pass

    updates = {
        "skill_name":      f"ci_cd:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["ci_cd_node"],
    }
    if platform_evidence_json:
        updates["platform_evidence"] = platform_evidence_json
    return updates


def _assemble_cicd_evidence(state: ARIAState) -> Optional[str]:
    """
    Build an EvidencedAnswer covering pipeline state and transitive dependency impact.

    claim "pipeline-state": current CI/telemetry for the failing service.
    claim "dependency-impact": downstream services that may be affected, from
        documentation and telemetry of all transitively dependent services.
    """
    from aria.platform.catalog import ServiceCatalog, InMemoryCatalogStore
    from aria.platform.sources import SourceRepository
    from aria.platform.fixtures import load_fixtures_into
    from aria.platform.evidence import EvidenceAssembler
    from aria.platform.models import ClaimSpec, SensitivityLevel

    raw_sens = (state.get("data_sensitivity") or "internal").lower()
    _sens_map = {"public": "public", "internal": "internal",
                 "confidential": "restricted", "restricted": "restricted"}
    caller_level: SensitivityLevel = _sens_map.get(raw_sens, "internal")  # type: ignore[assignment]

    catalog = ServiceCatalog(InMemoryCatalogStore())
    source_repo = SourceRepository()
    load_fixtures_into(catalog, source_repo, include_restricted=False)

    pipeline = _infer_pipeline_name(state["raw_input"])
    service_ids = [pipeline] if pipeline else _KNOWN_PIPELINES

    # BFS impact analysis: which downstream services are affected
    affected: list[str] = []
    if pipeline:
        try:
            affected = catalog.impact_analysis(pipeline)
        except Exception:
            pass

    all_relevant = list({*service_ids, *affected})

    claims = [
        ClaimSpec(
            claim_id="pipeline-state",
            claim_text=f"Current CI build and health status for {', '.join(service_ids)}",
            service_ids=service_ids,
            source_types=["ci", "telemetry"],
            keywords=["failing", "failed", "error", "test", "build", "deploy", "health"],
        ),
        ClaimSpec(
            claim_id="dependency-impact",
            claim_text=(
                f"Services downstream of {', '.join(service_ids)} "
                f"that may be affected: {', '.join(affected) or 'none identified'}"
            ),
            service_ids=all_relevant,
            source_types=["documentation", "telemetry"],
            keywords=["depends", "dependency", "downstream", "impact", "latency"],
        ),
    ]

    assembler = EvidenceAssembler(catalog, source_repo)
    evidenced = assembler.assemble(
        query=state["raw_input"],
        claims=claims,
        caller_level=caller_level,
    )
    return evidenced.model_dump_json(indent=2)


def _mock_jira_create(draft) -> dict:
    """Placeholder Jira API call — real REST client in V2 (needs credentials)."""
    return {
        "ticket_id": "AU-ENG-MOCK",
        "url":       "https://jira.amar-ujala.internal/browse/AU-ENG-MOCK",
        "status":    "created (mock — real Jira API integration arrives in V2)",
    }


def jira_node(state: ARIAState) -> dict:
    budget_err = _guard_budget(state, 2000)
    if budget_err:
        return budget_err
    from aria.runtime.harness import execute, guard_loop, make_idem_key, ToolCall

    guard_loop(state["steps_completed"], state["task_id"])

    rk = _routing_kwargs(state)
    skill_meta = skill_registry.get("jira")
    result = skill_meta.fn(JiraInput(
        raw_input=state["raw_input"],
        task_id=state["task_id"],
        **rk,
    ))

    updates: dict = {
        "skill_name":      f"jira:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["jira_node"],
    }

    if not result.approval_required:
        return updates

    # T4 path — user explicitly asked to create a ticket
    from aria.governance.approval_gate import request_approval, is_approved

    if is_approved(state["task_id"], "jira_create"):
        # Human has already clicked Approve on the Teams card — execute through harness
        idem_key = make_idem_key(state["task_id"], "jira_create", result.ticket_draft.title)
        call = ToolCall(
            task_id=state["task_id"],
            tool_name="jira_create",
            action_tier="T4",
            dry_run=state.get("execution_mode") == "dry_run",
            idem_key=idem_key,
            data_sensitivity=rk["data_sensitivity"],
        )
        tool_result = execute(call, _mock_jira_create, result.ticket_draft)
        if tool_result.success and not tool_result.was_dry_run:
            ticket_id = (tool_result.output or {}).get("ticket_id", "AU-ENG-???")
            # Annotate skill_output with the created ticket ID
            import json as _json
            payload = _json.loads(updates["skill_output"])
            payload["created_ticket_id"] = ticket_id
            payload["created_ticket_url"] = (tool_result.output or {}).get("url", "")
            updates["skill_output"] = _json.dumps(payload, indent=2)
    else:
        # Approval pending — register request so the Teams card button can resolve it
        try:
            req = request_approval(
                task_id=state["task_id"],
                tool_name="jira_create",
                proposed_action=f"Create Jira ticket: {result.ticket_draft.title}",
                action_tier="T4",
            )
            updates["approval_request_id"] = req.request_id
        except Exception:
            pass

    return updates


def analytics_qa_crew_node(state: ARIAState) -> dict:
    """
    Week 22 — CrewAI Analytics+QA crew node.
    Routes KPI anomaly investigations through the two-agent crew:
      AnalyticsAgent → investigates root causes
      QAAgent        → generates test cases to prevent recurrence
    Falls back gracefully when no LLM is configured.
    """
    budget_err = _guard_budget(state, 4000)
    if budget_err:
        return budget_err
    from aria.runtime.harness import guard_loop
    from aria.crews.analytics_qa_crew import AnalyticsQACrew

    guard_loop(state["steps_completed"], state["task_id"])

    crew = AnalyticsQACrew()
    result = crew.run(
        anomaly=state["raw_input"],
        task_id=state["task_id"],
        dry_run=state.get("execution_mode") == "dry_run",
    )

    return {
        "skill_name":      f"analytics_qa_crew:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["analytics_qa_crew_node"],
    }


def general_node(state: ARIAState) -> dict:
    """
    Fallback node for unclassified tasks.
    Runs Decision Intelligence (LATS) to rank available skills and recommend
    the most likely useful one — T2 recommendation, never executes autonomously.
    """
    budget_err = _guard_budget(state, 500)
    if budget_err:
        return budget_err
    from aria.decision import next_best_action, DecisionOption

    options = [
        DecisionOption(
            option_id="kpi",
            action="Route to KPI Investigation skill",
            rationale="Input may describe a metric anomaly or data quality issue",
            risk_score=0.1, confidence=0.5, cost_estimate="low", approval_likelihood=0.8,
        ),
        DecisionOption(
            option_id="pr_review",
            action="Route to PR Review skill",
            rationale="Input may describe a pull request or code change",
            risk_score=0.1, confidence=0.5, cost_estimate="low", approval_likelihood=0.8,
        ),
        DecisionOption(
            option_id="clarify",
            action="Ask the user to clarify their request",
            rationale="Input is ambiguous — requesting more information is the safest action",
            risk_score=0.0, confidence=0.9, cost_estimate="low", approval_likelihood=0.95,
        ),
    ]
    result = next_best_action(
        task_id=state["task_id"],
        task_description=state["raw_input"],
        options=options,
        method="greedy",
    )
    return {
        "skill_name":      f"decision:{result.version}",
        "skill_output":    result.model_dump_json(indent=2),
        "steps_completed": state["steps_completed"] + ["general_node"],
    }
