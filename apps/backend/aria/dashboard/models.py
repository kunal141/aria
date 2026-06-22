"""
Typed models for V3.10 — Manager Dashboard + ROI + Final V3 Proof.

A READ-ONLY manager view over every V3 system. A manager can inspect ARIA like an
employee: what it worked on, what it learned, what it needs, what it risks, and what
value it produced. Nothing here executes work, approves anything, activates a skill,
or performs an external action — these are source-cited summaries only.

ROI is always ESTIMATED and transparent (minutes saved by default; cost only if an
hourly rate is configured). All models are frozen Pydantic (immutable records).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GoalProgressSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    active_goals: int = 0
    completed_goals: int = 0
    blocked_goals: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    blocked_tasks: int = 0
    next_recommended_steps: list[str] = Field(default_factory=list)


class AgentWorkforceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    agents_planned: int = 0
    assignments_created: int = 0
    assignments_completed: int = 0
    assignments_blocked: int = 0
    quality_failures: int = 0
    escalations: int = 0
    supervision_status: str = "none"


class LearningSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    memory_nodes: int = 0
    lessons_created: int = 0
    lessons_disabled: int = 0
    world_updates: int = 0
    improvement_proposals: int = 0
    skill_gaps: int = 0
    skill_proposals: int = 0
    activated_skills: int = 0
    rejected_skills: int = 0


class CollaborationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    manager_updates: int = 0
    stakeholder_questions: int = 0
    handoff_notes: int = 0
    approval_request_drafts: int = 0
    risk_escalation_drafts: int = 0
    drafts_ready_for_review: int = 0


class RoutineSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    routines_defined: int = 0
    routines_enabled: int = 0
    runs_completed: int = 0
    runs_failed: int = 0
    runs_missed: int = 0
    outputs_created: int = 0
    followups_drafted: int = 0


class ActionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    action_intents: int = 0
    previews: int = 0
    approvals_requested: int = 0
    approved_actions: int = 0
    rejected_actions: int = 0
    blocked_actions: int = 0
    dry_run_receipts: int = 0
    mock_live_receipts: int = 0
    live_receipts: int = 0           # MUST stay 0 in V3.10 (no real live execution)


class ApprovalQueueItem(BaseModel):
    """A read-only pending-approval item (no decision is taken here)."""
    model_config = ConfigDict(frozen=True)
    item_id: str
    item_type: str                   # skill_proposal | collaboration_approval | action_intent | improvement
    title: str
    risk_level: str = "low"
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    status: str = "pending"
    recommended_decision: str = "review"


class ApprovalQueueSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[ApprovalQueueItem] = Field(default_factory=list)
    count: int = 0
    boundary_note: str = "Read-only. No approval, activation, or execution happens here."


class RiskItem(BaseModel):
    """A source-linked risk/blocker (never invented; missing evidence is marked)."""
    model_config = ConfigDict(frozen=True)
    risk_id: str
    risk_type: str                   # blocked_task | failed_run | failed_agent | escalation |
    #                                  missing_evidence | blocked_action | high_risk_world | unsafe_skill
    title: str
    severity: str = "low"
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    owner: str = "aria"
    recommended_action: str = ""
    status: str = "open"


class RiskSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[RiskItem] = Field(default_factory=list)
    count: int = 0
    high_severity: int = 0
    boundary_note: str = "Source-linked risks only. High-risk actions remain blocked."


class ROISummary(BaseModel):
    """A transparent, ESTIMATED value summary. Minutes saved by default; cost only if
    an hourly rate is configured. Never invents salary/cost."""
    model_config = ConfigDict(frozen=True)
    roi_summary_id: str
    tasks_completed: int = 0
    drafts_created: int = 0
    routines_completed: int = 0
    action_previews_created: int = 0
    approvals_prepared: int = 0
    estimated_minutes_saved: int = 0
    estimated_cost_saved: float | None = None      # None unless an hourly rate is configured
    risk_reduction_notes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    calculation_method: str = ""
    estimated: bool = True
    created_at: datetime | None = None


class ManagerDashboardSnapshot(BaseModel):
    """A read-only aggregate of all V3 systems at a point in time."""
    model_config = ConfigDict(frozen=True)
    snapshot_id: str
    generated_at: datetime
    workspace_id: str | None = None
    goal_summary: GoalProgressSummary = Field(default_factory=GoalProgressSummary)
    task_summary: dict[str, Any] = Field(default_factory=dict)
    agent_summary: AgentWorkforceSummary = Field(default_factory=AgentWorkforceSummary)
    memory_summary: LearningSummary = Field(default_factory=LearningSummary)
    skill_summary: dict[str, Any] = Field(default_factory=dict)
    collaboration_summary: CollaborationSummary = Field(default_factory=CollaborationSummary)
    routine_summary: RoutineSummary = Field(default_factory=RoutineSummary)
    action_summary: ActionSummary = Field(default_factory=ActionSummary)
    approval_summary: ApprovalQueueSummary = Field(default_factory=ApprovalQueueSummary)
    risk_summary: RiskSummary = Field(default_factory=RiskSummary)
    roi_summary: ROISummary | None = None
    source_refs: list[str] = Field(default_factory=list)
    ledger_refs: list[str] = Field(default_factory=list)
    boundary_note: str = (
        "Read-only manager view. ARIA can be inspected like an employee; nothing here "
        "executes work, approves actions, activates skills, or performs an external write."
    )


# Boundary note attached to dashboard/proof results.
DASHBOARD_BOUNDARY = (
    "V3.10 is visibility, control, proof, ROI, and acceptance — not more autonomy. "
    "Read-only aggregation only; no live writes, no connectors, no network, no "
    "automatic approval/activation/execution."
)
