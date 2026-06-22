"""
Typed models for V3.9 — Controlled Live Execution Layer.

A governed ACTION GATE. ARIA can propose external-action *intents*, *preview* them,
get them *approved*, and *execute* them — but in V3.9 execution is DENY-BY-DEFAULT and
runs only in ``dry_run`` (writes nothing) or ``mock_live`` (writes only to ARIA's own
receipt store, target ``internal_mock``). ``live`` mode is disabled; no real connector
write, network call, or external send happens.

Approval is bound to an action's ``action_id`` + payload hash + permission scope, so a
changed payload or widened scope silently invalidates the approval (re-approval
required). All models are frozen Pydantic (immutable records).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionType(str, Enum):
    send_message = "send_message"
    create_ticket = "create_ticket"
    post_comment = "post_comment"
    update_status = "update_status"
    trigger_webhook = "trigger_webhook"
    archive_item = "archive_item"
    apply_label = "apply_label"
    mark_done = "mark_done"
    mock_external_action = "mock_external_action"


class TargetSystem(str, Enum):
    internal_mock = "internal_mock"
    teams = "teams"
    slack = "slack"
    gmail = "gmail"
    jira = "jira"
    github = "github"
    webhook = "webhook"
    calendar = "calendar"


class ActionStatus(str, Enum):
    draft = "draft"
    previewed = "previewed"
    blocked = "blocked"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    executing = "executing"
    executed = "executed"
    failed = "failed"
    cancelled = "cancelled"
    rolled_back = "rolled_back"


class ApprovalDecision(str, Enum):
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"
    expired = "expired"


class ExecutionMode(str, Enum):
    dry_run = "dry_run"
    mock_live = "mock_live"
    live = "live"           # DISABLED in V3.9 — always hard-blocked


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# The ONLY target a mock-live execution may touch; everything else is external and
# blocked from mock/live execution by default.
INTERNAL_TARGET = TargetSystem.internal_mock
EXTERNAL_TARGETS = frozenset(t for t in TargetSystem if t is not TargetSystem.internal_mock)


def canonical_payload(payload: dict[str, Any] | None) -> str:
    """Deterministic JSON encoding of a payload, for hashing/approval binding."""
    return json.dumps(payload or {}, sort_keys=True, ensure_ascii=True, default=str)


def payload_hash(payload: dict[str, Any] | None) -> str:
    """A stable hash of the payload. Approval is bound to this — a changed payload
    yields a different hash and silently invalidates a prior approval."""
    return hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()


def permission_scope_for(action_type: ActionType, target_system: TargetSystem) -> str:
    """The minimal permission scope an action requires: ``<target>:<action>``."""
    return f"{target_system.value}:{action_type.value}"


class ActionIntent(BaseModel):
    """A typed proposal to perform an external action. A proposal is NOT an act —
    creating an intent never touches any external system."""
    model_config = ConfigDict(frozen=True)

    action_id: str
    action_type: ActionType
    title: str
    description: str = ""
    requested_by: str = "aria"
    goal_id: str | None = None
    task_id: str | None = None
    workspace_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    draft_refs: list[str] = Field(default_factory=list)
    target_system: TargetSystem = TargetSystem.internal_mock
    payload_preview: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.low
    permission_scope: str = ""
    approval_required: bool = True
    status: ActionStatus = ActionStatus.draft
    created_at: datetime
    updated_at: datetime

    @property
    def payload_hash(self) -> str:
        return payload_hash(self.payload_preview)

    @property
    def is_external(self) -> bool:
        return self.target_system in EXTERNAL_TARGETS


class ActionApproval(BaseModel):
    """A recorded human approval/rejection decision, BOUND to an action_id + payload
    hash + scope. It authorizes (at most) a governed mock/dry-run execution — never a
    real external send."""
    model_config = ConfigDict(frozen=True)

    approval_id: str
    action_id: str
    approver: str
    decision: ApprovalDecision
    reason: str = ""
    decided_at: datetime
    approval_scope: str = ""
    payload_hash: str = ""           # the exact payload the approval was granted for
    expires_at: datetime | None = None
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    def is_valid_for(self, intent: ActionIntent, *, now: datetime) -> bool:
        """An approval authorizes execution only if it approved THIS action, THIS
        payload, THIS scope, and has not expired."""
        if self.decision is not ApprovalDecision.approved:
            return False
        if self.action_id != intent.action_id:
            return False
        if self.payload_hash != intent.payload_hash:
            return False
        if self.approval_scope and self.approval_scope != intent.permission_scope:
            return False
        if self.expires_at is not None and now > self.expires_at:
            return False
        return True


class ActionReceipt(BaseModel):
    """A record of an execution attempt. In V3.9 the result is always dry-run, mock,
    blocked, or failed — never a real external write. The receipt IS the artifact."""
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    action_id: str
    target_system: TargetSystem
    execution_mode: ExecutionMode
    executed_at: datetime
    executed_by: str = "aria"
    result_status: str = "dry_run_ok"   # dry_run_ok | mock_executed | blocked | failed
    external_ref: str | None = None     # mock://… for mock; never a real id
    receipt_summary: str = ""
    rollback_note: str = ""
    compensation_note: str = ""
    ledger_refs: list[str] = Field(default_factory=list)


# Boundary note attached to action results.
ACTION_BOUNDARY = (
    "Governed action gate. Live execution is BLOCKED by default; only explicitly "
    "approved, policy-allowed actions run, and only in dry-run or internal_mock mode. "
    "No real connector write, network call, or external send occurs in V3.9."
)
