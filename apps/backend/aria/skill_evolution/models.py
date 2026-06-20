"""
Typed models for V3.5 — Skill Evolution Engine.

GOVERNED, approval-gated, documentation/config-only. A "skill" here is a *proposal*
plus a *specification*, a *test plan*, an *evaluation*, and a registry *status* — it
is NOT live production code, and nothing here modifies production behaviour or
auto-activates. Activation is approval-gated and reversible.

All models are frozen Pydantic (immutable records), consistent with the platform's
typed-contract rule.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GapSourceType(str, Enum):
    repeated_blocker = "repeated_blocker"
    repeated_quality_failure = "repeated_quality_failure"
    repeated_missing_evidence = "repeated_missing_evidence"
    repeated_escalation = "repeated_escalation"
    manual_task = "manual_task"
    user_feedback = "user_feedback"


class SkillProposalStatus(str, Enum):
    draft = "draft"
    proposed = "proposed"
    spec_generated = "spec_generated"
    test_plan_generated = "test_plan_generated"
    sandbox_ready = "sandbox_ready"
    evaluated = "evaluated"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    activated = "activated"
    deprecated = "deprecated"
    rolled_back = "rolled_back"


class RecommendedDecision(str, Enum):
    approve = "approve"
    reject = "reject"
    needs_more_work = "needs_more_work"


# Tools an evolving skill must NEVER request (write/live-action tools). A spec or
# proposal that lists any of these is unsafe and cannot pass evaluation/activation.
FORBIDDEN_SKILL_TOOLS: tuple[str, ...] = (
    "jira_create", "teams_send", "pr_comment", "deploy", "db_write", "run_pipeline",
    "fs_write", "shell_exec", "http_post",
)

# Activation thresholds. An unsafe skill (below SAFE) can NEVER activate — enforced
# at BOTH the service layer and the store authority. Below READY → "needs more work".
SAFE_THRESHOLD = 0.8
READY_THRESHOLD = 0.7

# Terminal statuses (no further transition except documentation reads).
_TERMINAL_STATUSES = frozenset({
    SkillProposalStatus.rejected, SkillProposalStatus.deprecated, SkillProposalStatus.rolled_back,
})


def is_terminal_status(status: SkillProposalStatus) -> bool:
    return status in _TERMINAL_STATUSES


class SkillGap(BaseModel):
    """A detected, repeated capability gap. Detection is deterministic; a single weak
    signal does NOT become a high-confidence gap."""
    model_config = ConfigDict(frozen=True)

    gap_id: str
    source_type: GapSourceType
    source_refs: list[str] = Field(default_factory=list)
    description: str
    repeated_pattern: str
    affected_goals: list[str] = Field(default_factory=list)
    affected_tasks: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    risk_level: str = "low"
    created_at: datetime


class SkillProposal(BaseModel):
    """A proposal to create a new skill (PROPOSAL ONLY — never live code)."""
    model_config = ConfigDict(frozen=True)

    proposal_id: str
    gap_id: str
    name: str
    purpose: str
    target_domain: str
    expected_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    risk_level: str = "low"
    approval_required: bool = True
    status: SkillProposalStatus = SkillProposalStatus.proposed
    created_at: datetime
    updated_at: datetime


class SkillSpec(BaseModel):
    """A structured skill specification (documentation/config, not active code)."""
    model_config = ConfigDict(frozen=True)

    spec_id: str
    proposal_id: str
    skill_name: str
    problem_solved: str
    target_users: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    memory_access_policy: str = "read-approved-only"
    evidence_requirements: list[str] = Field(default_factory=list)
    approval_requirements: str = "human approval required before activation"
    risk_classification: str = "low"
    failure_modes: list[str] = Field(default_factory=list)
    rollback_plan: str = "deactivate registry entry; restore prior inactive state"
    acceptance_criteria: list[str] = Field(default_factory=list)
    created_at: datetime


class SkillTestPlan(BaseModel):
    """A generated test plan (ARTIFACT/spec — never executed against production)."""
    model_config = ConfigDict(frozen=True)

    test_plan_id: str
    proposal_id: str
    spec_id: str
    test_cases: list[dict[str, str]] = Field(default_factory=list)   # {name, kind, expectation}
    created_at: datetime

    @property
    def case_kinds(self) -> set[str]:
        return {c.get("kind", "") for c in self.test_cases}


class SkillEvaluation(BaseModel):
    """An advisory readiness/safety evaluation. It CANNOT auto-approve."""
    model_config = ConfigDict(frozen=True)

    evaluation_id: str
    proposal_id: str
    spec_id: str
    test_plan_id: str
    readiness_score: float = 0.0
    safety_score: float = 0.0
    expected_roi: str = "unknown"
    risk_summary: str = "low"
    missing_requirements: list[str] = Field(default_factory=list)
    recommended_decision: RecommendedDecision = RecommendedDecision.needs_more_work
    created_at: datetime


class SkillDecisionRecord(BaseModel):
    """A typed approval/activation decision record. Attribution-only ``decided_by``."""
    model_config = ConfigDict(frozen=True)

    decision: str                    # approve | reject
    proposal_id: str
    status: SkillProposalStatus      # resulting status
    activated: bool = False
    decided_by: str                  # attribution only, NOT authorization
    reason: str = ""
    decided_at: datetime
