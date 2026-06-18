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
    planned = "planned"
    in_progress = "in_progress"
    blocked = "blocked"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    cancelled = "cancelled"


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
