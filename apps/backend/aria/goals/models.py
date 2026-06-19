"""
Typed models for V3.1 — Goal Ownership Foundation.

Planning-layer models only. A GoalIntake captures a vague request turned into a
structured goal; a Roadmap is its phased plan; a TaskItem is one planning step; a
GoalProgress is a computed summary. NONE of these execute work or write to any
external system — V3.1 is a planning / control layer.

All models are frozen Pydantic (immutable records), consistent with the platform
rule that every contract is a typed, versioned model.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GoalStatus(str, Enum):
    intake = "intake"                 # structured, awaiting confirmation/clarification
    planned = "planned"               # roadmap + task board created
    in_progress = "in_progress"       # at least one task moving
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    cancelled = "cancelled"


class TaskStatus(str, Enum):
    planned = "planned"                       # ready / not-yet-started (V3.1 initial)
    in_progress = "in_progress"
    blocked = "blocked"
    awaiting_approval = "awaiting_approval"
    needs_clarification = "needs_clarification"   # V3.2: missing context
    needs_evidence = "needs_evidence"             # V3.2: required evidence not provided
    failed = "failed"                             # V3.2: step failed safely
    completed = "completed"
    cancelled = "cancelled"


class ExecutionOutcome(str, Enum):
    """The outcome of a single governed execution step."""
    completed_step = "completed_step"
    blocked_for_clarification = "blocked_for_clarification"
    blocked_for_evidence = "blocked_for_evidence"
    blocked_for_approval = "blocked_for_approval"
    failed_safely = "failed_safely"
    no_actionable_task = "no_actionable_task"


class OwnerType(str, Enum):
    human = "human"
    aria = "aria"
    agent = "agent"
    team = "team"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# Terminal statuses can't transition further (except documentation reads).
_TERMINAL_TASK_STATUSES = frozenset({TaskStatus.completed, TaskStatus.cancelled})


def is_terminal_task_status(status: TaskStatus) -> bool:
    return status in _TERMINAL_TASK_STATUSES


class GoalIntake(BaseModel):
    """A vague request converted into a structured, governed goal."""
    model_config = ConfigDict(frozen=True)

    goal_id: str
    title: str
    raw_request: str
    problem_statement: str
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    known_context: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)
    scope: str = "general"
    risk_level: str = "low"
    status: GoalStatus = GoalStatus.intake
    workspace_id: str | None = None
    created_at: datetime
    updated_at: datetime


class RoadmapPhase(BaseModel):
    model_config = ConfigDict(frozen=True)
    order: int
    name: str
    objective: str
    evidence_needed: list[str] = Field(default_factory=list)


class Roadmap(BaseModel):
    """A phased plan for a goal: phases, milestones, dependencies, risks,
    evidence needed, and deliverables. Planning only."""
    model_config = ConfigDict(frozen=True)

    roadmap_id: str
    goal_id: str
    phases: list[RoadmapPhase] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence_needed: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TaskItem(BaseModel):
    """One planning task on the board. ``status`` is a PLANNING state — moving a
    task does NOT execute any tool or external action in V3.1."""
    model_config = ConfigDict(frozen=True)

    task_id: str
    goal_id: str
    roadmap_id: str | None = None
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.planned
    priority: Priority = Priority.medium
    owner_type: OwnerType = OwnerType.aria
    required_skill: str | None = None
    required_evidence: list[str] = Field(default_factory=list)
    approval_required: bool = False
    blocked_by: list[str] = Field(default_factory=list)
    output_artifact: str | None = None
    created_at: datetime
    updated_at: datetime


class GoalProgress(BaseModel):
    """Computed snapshot of a goal's task board. Derived, never authoritative state."""
    model_config = ConfigDict(frozen=True)

    goal_id: str
    completed_tasks: int = 0
    pending_tasks: int = 0
    blocked_tasks: int = 0
    awaiting_approval_tasks: int = 0
    cancelled_tasks: int = 0
    total_tasks: int = 0
    current_phase: str | None = None
    next_action: str | None = None
    last_update: datetime | None = None
    risk_summary: str = "low"


class ExecutionStep(BaseModel):
    """A single governed execution step. Records what ARIA chose to do, why, and the
    safe outcome. PLANNING ONLY — ``produced_artifact`` is a planning artifact, never
    an external write. ``safe_user_message`` is redacted (no raw exception text)."""
    model_config = ConfigDict(frozen=True)

    step_id: str
    goal_id: str
    task_id: str | None = None
    workspace_id: str | None = None
    selected_action: str
    reason: str
    required_evidence: list[str] = Field(default_factory=list)
    approval_required: bool = False
    produced_artifact: str | None = None
    status_before: str | None = None
    status_after: str | None = None
    outcome: ExecutionOutcome
    safe_user_message: str = ""
    created_at: datetime


class ClarificationRequest(BaseModel):
    """A request for missing context. Stored + logged; answered by a human."""
    model_config = ConfigDict(frozen=True)

    clarification_id: str
    goal_id: str
    task_id: str | None = None
    questions: list[str] = Field(default_factory=list)
    answers: dict[str, str] | None = None
    status: str = "open"                      # open | answered
    created_at: datetime
    answered_at: datetime | None = None


class Deliverable(BaseModel):
    """A tracked planning/progress deliverable reference (NOT an external write)."""
    model_config = ConfigDict(frozen=True)

    deliverable_id: str
    goal_id: str
    task_id: str | None = None
    kind: str                                 # investigation_report | action_plan | manager_summary | ...
    title: str
    artifact_ref: str | None = None
    created_at: datetime


class ExecutionProgress(BaseModel):
    """Rich execution-aware progress report, computed from persisted state."""
    model_config = ConfigDict(frozen=True)

    goal_id: str
    goal_title: str
    current_phase: str | None = None
    total_tasks: int = 0                      # preserved from V3.1 GoalProgress
    completed_tasks: int = 0
    in_progress_tasks: int = 0
    blocked_tasks: int = 0
    pending_approvals: int = 0
    evidence_needed: list[str] = Field(default_factory=list)
    artifacts_created: list[str] = Field(default_factory=list)
    open_clarifications: list[str] = Field(default_factory=list)
    next_recommended_action: str | None = None
    risk_summary: str = "low"
    boundary_note: str = (
        "Planning/control only. No external writes, no live connectors, no deployment."
    )


class AgentStatus(str, Enum):
    planned = "planned"
    ready = "ready"
    running = "running"
    completed = "completed"
    blocked = "blocked"
    failed = "failed"
    cancelled = "cancelled"
    killed = "killed"


# Statuses that mean an assignment did NOT produce trustworthy final findings.
_NON_FINDINGS_AGENT_STATUSES = frozenset({
    AgentStatus.blocked, AgentStatus.failed, AgentStatus.cancelled, AgentStatus.killed,
    AgentStatus.planned, AgentStatus.ready, AgentStatus.running,
})


class AgentBrief(BaseModel):
    """A bounded specialist-agent brief. Defines a NARROW objective and explicit
    permission boundaries. V3.3 is DRY-RUN only — a brief is a plan, never a live
    process. Tools are read-only; write tools are always forbidden."""
    model_config = ConfigDict(frozen=True)

    agent_id: str
    goal_id: str
    task_id: str | None = None
    name: str
    role: str
    objective: str
    allowed_context: list[str] = Field(default_factory=list)
    forbidden_context: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    expected_output_schema: str = "AgentFindings"
    approval_required: bool = False
    risk_level: str = "low"
    time_limit_seconds: int = 60
    cost_limit_units: int = 1
    status: AgentStatus = AgentStatus.planned
    created_at: datetime
    updated_at: datetime


class AgentAssignment(BaseModel):
    """A DRY-RUN execution record for an agent brief, with supervision metadata.
    A cancelled/killed assignment must NOT present findings as if completed."""
    model_config = ConfigDict(frozen=True)

    assignment_id: str
    agent_id: str
    goal_id: str
    task_id: str | None = None
    workspace_id: str | None = None
    input_summary: str = ""
    output_summary: str = ""
    output_artifact: str | None = None
    status: AgentStatus = AgentStatus.planned
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    ledger_refs: list[str] = Field(default_factory=list)
    # Supervision / kill-switch metadata
    kill_reason: str | None = None
    max_runtime_seconds: int = 60
    max_cost_units: int = 1
    risk_level: str = "low"
    approval_required: bool = False
    supervisor: str | None = None
    stopped_at: datetime | None = None

    @property
    def has_findings(self) -> bool:
        return self.status is AgentStatus.completed


class AgentMergeResult(BaseModel):
    """A goal-level merge of specialist agent outputs. Findings are NEVER invented
    for blocked/cancelled agents — only completed agents contribute findings."""
    model_config = ConfigDict(frozen=True)

    goal_id: str
    agents_run: int = 0
    completed_assignments: int = 0
    blocked_assignments: int = 0
    cancelled_assignments: int = 0
    key_findings: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    memory_citations: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    draft_actions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_recommended_action: str | None = None
    boundary_note: str = (
        "Dry-run / fixture-first. No real agent process, no external writes, no live connectors."
    )


class AgentPlan(BaseModel):
    """The planned workforce: briefs + their (planned) assignments."""
    model_config = ConfigDict(frozen=True)

    goal_id: str
    briefs: list[AgentBrief] = Field(default_factory=list)
    assignments: list[AgentAssignment] = Field(default_factory=list)


# ── V3.4: agent supervisor + multi-agent governance ──────────────────────────


class SupervisionStatus(str, Enum):
    planned = "planned"
    running = "running"
    completed = "completed"
    completed_with_blockers = "completed_with_blockers"
    failed_safely = "failed_safely"
    cancelled = "cancelled"


class QualityStatus(str, Enum):
    passed = "passed"
    blocked_for_quality_review = "blocked_for_quality_review"
    escalation_required = "escalation_required"


class GovernancePolicy(BaseModel):
    """Supervision-level governance limits. Safe defaults; callers may override."""
    model_config = ConfigDict(frozen=True)

    max_total_cost_units: int = 100
    max_total_runtime_seconds: int = 3600
    max_assignments_per_run: int = 20
    allowed_risk_levels: list[str] = Field(default_factory=lambda: ["low", "medium"])
    require_approval_for_high_risk: bool = True
    max_retries: int = 2


class AgentExecutionPlan(BaseModel):
    """A governed multi-agent execution plan: dependency-ordered, budget-estimated."""
    model_config = ConfigDict(frozen=True)

    plan_id: str
    goal_id: str
    workspace_id: str | None = None
    assignment_ids: list[str] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)
    blocked_assignments: list[str] = Field(default_factory=list)
    approval_required_assignments: list[str] = Field(default_factory=list)
    estimated_cost_units: int = 0
    estimated_runtime_seconds: int = 0
    risk_summary: str = "low"
    created_at: datetime
    updated_at: datetime


class Escalation(BaseModel):
    """A human-review escalation. NO external message is sent — it is recorded."""
    model_config = ConfigDict(frozen=True)

    escalation_id: str
    goal_id: str
    run_id: str | None = None
    assignment_id: str | None = None
    reason: str
    suggested_action: str
    risk_level: str = "low"
    workspace_id: str | None = None
    created_at: datetime


class AgentSupervisionRun(BaseModel):
    """A supervision run record + outcome counts and governance verdicts."""
    model_config = ConfigDict(frozen=True)

    run_id: str
    plan_id: str
    goal_id: str
    workspace_id: str | None = None
    status: SupervisionStatus = SupervisionStatus.planned
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_assignments: int = 0
    completed_assignments: int = 0
    blocked_assignments: int = 0
    failed_assignments: int = 0
    cancelled_assignments: int = 0
    quality_passed: bool = True
    escalation_required: bool = False
    summary: str = ""
    ledger_refs: list[str] = Field(default_factory=list)
    boundary_note: str = (
        "Supervised dry-run. No real agent process, no external writes, no live connectors."
    )


class GoalPlan(BaseModel):
    """Convenience bundle returned when a goal is created: the intake, its roadmap,
    its task list, and the linked workspace id."""
    model_config = ConfigDict(frozen=True)

    goal: GoalIntake
    roadmap: Roadmap
    tasks: list[TaskItem] = Field(default_factory=list)
    workspace_id: str | None = None

    def as_summary(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal.goal_id,
            "roadmap_id": self.roadmap.roadmap_id,
            "task_ids": [t.task_id for t in self.tasks],
            "workspace_id": self.workspace_id,
            "status": self.goal.status.value,
        }
