"""
Typed models for V3.8 — Scheduled Routines + Approved Monitoring.

ARIA runs recurring INTERNAL work loops (goal reviews, blocker/risk reviews, memory
and collaboration reviews, fixture-only world checks) on a deterministic, LOCAL,
manual/due-run basis. There is no OS cron, no cloud scheduler, no background daemon,
no live browsing/network, and no external send — routines produce cited digests and
DRAFT artifacts only.

All models are frozen Pydantic (immutable records), consistent with the platform's
typed-contract rule.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RoutineType(str, Enum):
    daily_goal_review = "daily_goal_review"
    weekly_goal_review = "weekly_goal_review"
    blocker_review = "blocker_review"
    memory_review = "memory_review"
    collaboration_review = "collaboration_review"
    world_fixture_check = "world_fixture_check"
    skill_gap_review = "skill_gap_review"
    manager_summary = "manager_summary"
    risk_review = "risk_review"
    approval_queue_review = "approval_queue_review"


class Cadence(str, Enum):
    daily = "daily"
    weekly = "weekly"
    manual = "manual"
    every_n_hours = "every_n_hours"


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    missed = "missed"
    skipped = "skipped"
    disabled = "disabled"


class OutputType(str, Enum):
    daily_summary = "daily_summary"
    weekly_summary = "weekly_summary"
    blocker_digest = "blocker_digest"
    memory_lesson_digest = "memory_lesson_digest"
    world_awareness_digest = "world_awareness_digest"
    approval_queue_digest = "approval_queue_digest"
    risk_digest = "risk_digest"
    manager_update_draft = "manager_update_draft"
    followup_question_draft = "followup_question_draft"


# Cadence → window length in hours (every_n_hours uses the definition's interval_hours).
_CADENCE_HOURS = {Cadence.daily: 24, Cadence.weekly: 24 * 7}


class RoutineDefinition(BaseModel):
    """A recurring internal work loop. ``enabled=False`` means it can NEVER run.
    Cadence is evaluated deterministically against an injected ``now`` — no OS cron,
    no background scheduler."""
    model_config = ConfigDict(frozen=True)

    routine_id: str
    name: str
    description: str = ""
    routine_type: RoutineType
    cadence: Cadence = Cadence.manual
    interval_hours: int = 24                 # used only when cadence == every_n_hours
    timezone: str = "UTC"
    enabled: bool = True
    source_scope: str = "internal"           # internal / fixture — never live web
    goal_ids: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    allowed_inputs: list[str] = Field(default_factory=list)
    output_policy: str = "draft_only"        # draft_only — never send/post/email
    approval_required: bool = True
    last_run_at: datetime | None = None      # advanced on each completed/missed run
    created_by: str = "aria"
    created_at: datetime
    updated_at: datetime

    def window_hours(self) -> int | None:
        """The cadence window in hours, or None for manual (never auto-due)."""
        if self.cadence is Cadence.manual:
            return None
        if self.cadence is Cadence.every_n_hours:
            return max(1, self.interval_hours)
        return _CADENCE_HOURS.get(self.cadence)


class RoutineRun(BaseModel):
    """A single execution record for a routine. A FAILED run carries a class/code-only
    ``safe_error`` — never raw exception text."""
    model_config = ConfigDict(frozen=True)

    run_id: str
    routine_id: str
    status: RunStatus = RunStatus.pending
    started_at: datetime | None = None
    completed_at: datetime | None = None
    due_at: datetime | None = None
    triggered_by: str = "manual"             # manual | scheduler:due
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    error_code: str | None = None
    safe_error: str | None = None
    ledger_refs: list[str] = Field(default_factory=list)


class RoutineOutput(BaseModel):
    """A cited internal output of a routine run (a digest/summary). It must cite its
    sources (no orphan outputs) and invents no facts; it is stored as a workspace
    artifact and is never sent."""
    model_config = ConfigDict(frozen=True)

    output_id: str
    routine_id: str
    run_id: str
    output_type: OutputType
    title: str
    body: str
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    draft_refs: list[str] = Field(default_factory=list)
    recommendation_refs: list[str] = Field(default_factory=list)
    created_at: datetime


# Boundary note attached to routine results.
ROUTINE_BOUNDARY = (
    "Local, deterministic routine. ARIA can schedule, run, summarize, review, and "
    "recommend — it cannot live-browse, monitor uncontrolled sources, send messages, "
    "mutate external systems, or run external agents. World checks are fixture-only."
)
