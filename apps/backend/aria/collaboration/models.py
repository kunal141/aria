"""
Typed models for V3.7 — Team Collaboration Layer.

ARIA prepares communication the way a reliable team member would: manager/team
updates, stakeholder questions, handoff notes, approval requests, risk escalations,
and summaries. Every artifact here is a **DRAFT** — internal, source-cited, and
never sent/posted/emailed. Even an ``approved`` draft is approved *as an artifact*;
V3.7 performs no external send and mutates no external system.

All models are frozen Pydantic (immutable records), consistent with the platform's
typed-contract rule.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DraftType(str, Enum):
    manager_update = "manager_update"
    team_update = "team_update"
    stakeholder_question = "stakeholder_question"
    handoff_note = "handoff_note"
    approval_request = "approval_request"
    risk_escalation = "risk_escalation"
    daily_summary = "daily_summary"
    weekly_summary = "weekly_summary"
    decision_memo = "decision_memo"
    blocker_note = "blocker_note"


class Channel(str, Enum):
    internal_note = "internal_note"
    teams_draft = "teams_draft"
    slack_draft = "slack_draft"
    email_draft = "email_draft"
    jira_comment_draft = "jira_comment_draft"
    github_comment_draft = "github_comment_draft"


class DraftStatus(str, Enum):
    draft = "draft"
    ready_for_review = "ready_for_review"
    approved = "approved"          # approved AS A DRAFT ARTIFACT — never sent
    rejected = "rejected"
    archived = "archived"


class ApprovalRequestStatus(str, Enum):
    draft = "draft"
    ready_for_review = "ready_for_review"
    approved = "approved"          # the request artifact is approved; nothing executes
    rejected = "rejected"
    archived = "archived"


class CollaborationDraft(BaseModel):
    """A draft communication artifact. DRAFT-ONLY: it is never sent/posted/emailed,
    and it must cite its sources (no orphan/invented communication)."""
    model_config = ConfigDict(frozen=True)

    draft_id: str
    draft_type: DraftType
    title: str
    body: str
    audience: str = "manager"
    channel: Channel = Channel.internal_note
    goal_id: str | None = None
    task_id: str | None = None
    workspace_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    approval_required: bool = True
    status: DraftStatus = DraftStatus.draft
    created_by: str = "aria"
    created_at: datetime
    updated_at: datetime

    @property
    def is_sendable(self) -> bool:
        """V3.7 has NO send path. This is always False — drafts are artifacts only."""
        return False


class CollaborationContext(BaseModel):
    """A read-only snapshot of a goal's collaboration-relevant state, assembled from
    goal/task/agent/memory records. It is the deterministic input to draft
    generation — it asserts no new facts of its own."""
    model_config = ConfigDict(frozen=True)

    context_id: str
    goal_id: str
    task_id: str | None = None
    workspace_id: str | None = None
    active_blockers: list[str] = Field(default_factory=list)
    recent_progress: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    decisions_needed: list[str] = Field(default_factory=list)
    relevant_lessons: list[str] = Field(default_factory=list)
    agent_outputs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    created_at: datetime


class ApprovalRequestDraft(BaseModel):
    """A drafted human-approval request: a decision, options, a recommended option,
    and the evidence behind it. It RECORDS a request for a human; it executes
    nothing and sends nothing."""
    model_config = ConfigDict(frozen=True)

    approval_request_id: str
    title: str
    reason: str
    requested_decision: str
    options: list[str] = Field(default_factory=list)
    recommended_option: str = ""
    risk_level: str = "low"
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    draft_id: str | None = None
    status: ApprovalRequestStatus = ApprovalRequestStatus.draft
    created_at: datetime


# Boundary note attached to every draft-generation result.
DRAFT_ONLY_BOUNDARY = (
    "Draft-only collaboration artifact. ARIA can draft, summarize, ask, escalate, and "
    "hand off — it cannot send, post, comment, email, or mutate any external system. "
    "Approval marks the draft approved as an artifact; it triggers no external send."
)
