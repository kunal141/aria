"""
Skill spec / test-plan / evaluation generators (V3.5) — deterministic, offline.

All outputs are ARTIFACTS / config (documentation), never live code. Forbidden
write tools always stay forbidden; specs are read-only + approval-gated by default.
Evaluation is advisory — it computes readiness/safety/ROI and a recommended
decision, but it can NEVER auto-approve or activate a skill.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from aria.skill_evolution.models import (
    FORBIDDEN_SKILL_TOOLS,
    READY_THRESHOLD,
    SAFE_THRESHOLD,
    RecommendedDecision,
    SkillEvaluation,
    SkillProposal,
    SkillSpec,
    SkillTestPlan,
)

# Activation thresholds are defined in ``models`` (the store authority also imports
# them) and re-exported here for the evaluator + existing callers.
__all_thresholds__ = (SAFE_THRESHOLD, READY_THRESHOLD)

# Test-case kinds a complete plan must cover (used by the evaluator for coverage).
_REQUIRED_TEST_KINDS = (
    "happy_path", "missing_evidence", "sensitive_input", "prompt_injection",
    "forbidden_tool", "output_schema", "rollback",
)


def _now() -> datetime:
    return datetime.now(UTC)


def generate_spec(proposal: SkillProposal) -> SkillSpec:
    """Deterministically derive a structured skill spec from a proposal. Write tools
    are stripped from ``allowed_tools`` and always listed in ``forbidden_tools``."""
    allowed = [t for t in proposal.required_tools if t not in FORBIDDEN_SKILL_TOOLS]
    input_schema = {name: "string" for name in proposal.expected_inputs} or {"query": "string"}
    output_schema = {name: "string" for name in proposal.expected_outputs} or {"findings": "string"}
    return SkillSpec(
        spec_id=f"spec-{uuid.uuid4().hex}", proposal_id=proposal.proposal_id,
        skill_name=proposal.name, problem_solved=proposal.purpose,
        target_users=[proposal.target_domain],
        input_schema=input_schema, output_schema=output_schema,
        allowed_tools=allowed, forbidden_tools=list(FORBIDDEN_SKILL_TOOLS),
        memory_access_policy="read-approved-only",
        evidence_requirements=list(proposal.expected_inputs) or ["evidence ref"],
        approval_requirements="human approval required before activation; no auto-activation",
        risk_classification=proposal.risk_level,
        failure_modes=[
            "missing/insufficient evidence", "ambiguous input", "sensitive input rejected",
            "prompt-injection attempt rejected", "forbidden tool requested",
        ],
        rollback_plan="deactivate the registry entry and restore the prior inactive state",
        acceptance_criteria=[
            "produces typed output matching the schema",
            "cites evidence for every factual claim",
            "never calls a forbidden write tool",
            "never leaks secrets or raw exceptions",
        ],
        created_at=_now(),
    )


def generate_test_plan(spec: SkillSpec) -> SkillTestPlan:
    """Generate a planned test suite (artifact). Tests are NOT executed against
    production and do NOT activate the skill."""
    cases = [
        ("happy path", "happy_path", "valid input + evidence → typed output"),
        ("missing evidence", "missing_evidence", "no evidence → blocked_for_evidence, no fabrication"),
        ("bad input", "bad_input", "malformed input → safe validation error"),
        ("sensitive input", "sensitive_input", "secret-bearing input → refused/redacted"),
        ("prompt injection", "prompt_injection", "injected instruction → ignored, no tool escalation"),
        ("forbidden tool request", "forbidden_tool", "request a write tool → refused"),
        ("unsupported factual claim", "unsupported_claim", "numeric claim w/o evidence → flagged"),
        ("output schema validation", "output_schema", "output validates against the output schema"),
        ("cost/time limit", "cost_time", "exceeding budget/time → blocked safely"),
        ("rollback/deprecation", "rollback", "deactivation restores prior inactive state"),
        ("work ledger logging", "ledger", "each lifecycle step emits an audited ledger event"),
    ]
    return SkillTestPlan(
        test_plan_id=f"tp-{uuid.uuid4().hex}", proposal_id=spec.proposal_id, spec_id=spec.spec_id,
        test_cases=[{"name": n, "kind": k, "expectation": e} for n, k, e in cases],
        created_at=_now(),
    )


def evaluate_proposal(
    proposal: SkillProposal, spec: SkillSpec, test_plan: SkillTestPlan,
) -> SkillEvaluation:
    """Advisory readiness/safety/ROI evaluation. Cannot auto-approve."""
    missing: list[str] = []

    # ── Safety ────────────────────────────────────────────────────────────────
    safety_violations: list[str] = []
    bad_allowed = [t for t in spec.allowed_tools if t in FORBIDDEN_SKILL_TOOLS]
    if bad_allowed:
        safety_violations.append(f"allowed_tools include forbidden write tools: {sorted(bad_allowed)}")
    if not set(FORBIDDEN_SKILL_TOOLS).issubset(set(spec.forbidden_tools)):
        safety_violations.append("not all write tools are explicitly forbidden")
    if not proposal.approval_required:
        safety_violations.append("approval is not required before activation")
    if "approved" not in spec.memory_access_policy.lower():
        safety_violations.append("memory access policy is too permissive")
    safety_score = max(0.0, 1.0 - 0.34 * len(safety_violations))
    missing.extend(safety_violations)

    # ── Readiness ──────────────────────────────────────────────────────────────
    readiness_gaps: list[str] = []
    if not spec.input_schema:
        readiness_gaps.append("missing input schema")
    if not spec.output_schema:
        readiness_gaps.append("missing output schema")
    if not spec.evidence_requirements:
        readiness_gaps.append("missing evidence requirements")
    if not spec.acceptance_criteria:
        readiness_gaps.append("missing acceptance criteria")
    missing_kinds = sorted(set(_REQUIRED_TEST_KINDS) - test_plan.case_kinds)
    if missing_kinds:
        readiness_gaps.append(f"insufficient test coverage: {missing_kinds}")
    readiness_score = max(0.0, 1.0 - 0.15 * len(readiness_gaps))
    missing.extend(readiness_gaps)

    # ── Recommendation (advisory) ───────────────────────────────────────────────
    if safety_score < SAFE_THRESHOLD:
        decision = RecommendedDecision.reject
    elif readiness_score < READY_THRESHOLD:
        decision = RecommendedDecision.needs_more_work
    else:
        decision = RecommendedDecision.approve

    roi = ("high" if readiness_score >= 0.85 and safety_score >= SAFE_THRESHOLD
           else "medium" if readiness_score >= READY_THRESHOLD else "low")
    return SkillEvaluation(
        evaluation_id=f"eval-{uuid.uuid4().hex}", proposal_id=proposal.proposal_id,
        spec_id=spec.spec_id, test_plan_id=test_plan.test_plan_id,
        readiness_score=round(readiness_score, 2), safety_score=round(safety_score, 2),
        expected_roi=roi, risk_summary=proposal.risk_level,
        missing_requirements=missing, recommended_decision=decision, created_at=_now(),
    )
