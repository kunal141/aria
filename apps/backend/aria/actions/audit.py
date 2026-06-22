"""
Work Ledger event construction for the V3.9 controlled-action store.

Mirrors the other audit modules: every event is built here, then enqueued into the
action store's transactional **audit outbox** in the same SQLite transaction as the
state change and flushed to the Work Ledger — so state and audit can never diverge.
Identifiers (action/approval/receipt ids, action_type, target_system, execution_mode,
status) ride in the sanitised ``metadata`` dict; ``safe_error`` is class/code-only.
Nothing here performs an external action.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActionApprovalRequested,
    ActionApproved,
    ActionBlocked,
    ActionExecuted,
    ActionExecutionFailed,
    ActionExecutionStarted,
    ActionIntentCreated,
    ActionPreviewed,
    ActionReceiptCreated,
    ActionRejected,
    ActorType,
    LedgerEventType,
)
from aria.ledger.events import RiskLevel, make_envelope

_EVENT_CLASSES = {
    LedgerEventType.action_intent_created:     ActionIntentCreated,
    LedgerEventType.action_previewed:          ActionPreviewed,
    LedgerEventType.action_blocked:            ActionBlocked,
    LedgerEventType.action_approval_requested: ActionApprovalRequested,
    LedgerEventType.action_approved:           ActionApproved,
    LedgerEventType.action_rejected:           ActionRejected,
    LedgerEventType.action_execution_started:  ActionExecutionStarted,
    LedgerEventType.action_executed:           ActionExecuted,
    LedgerEventType.action_execution_failed:   ActionExecutionFailed,
    LedgerEventType.action_receipt_created:    ActionReceiptCreated,
}

_RISK_LEVELS = {r.value: r for r in RiskLevel}


def _coerce_risk(value: str | RiskLevel | None) -> RiskLevel | None:
    if value is None or isinstance(value, RiskLevel):
        return value
    return _RISK_LEVELS.get(str(value).strip().lower(), RiskLevel.low)


def build_action_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    action_id: str | None = None,
    action_type: str | None = None,
    target_system: str | None = None,
    execution_mode: str | None = None,
    goal_id: str | None = None,
    task_ref: str | None = None,
    workspace_id: str | None = None,
    approval_id: str | None = None,
    receipt_id: str | None = None,
    status: str | None = None,
    safe_error: str | None = None,
    runtime_mode: str | None = None,
    outcome: str | None = None,
    risk_level: str | RiskLevel | None = "low",
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("action_id", action_id),
        ("action_type", action_type),
        ("target_system", target_system),
        ("execution_mode", execution_mode),
        ("goal_id", goal_id),
        ("task_id", task_ref),
        ("workspace_id", workspace_id),
        ("approval_id", approval_id),
        ("receipt_id", receipt_id),
        ("status", status),
        ("safe_error", safe_error),
        ("runtime_mode", runtime_mode),
    ):
        if value is not None:
            meta[key] = value
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or action_id or task_id,
        outcome=outcome,
        risk_level=_coerce_risk(risk_level),
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
