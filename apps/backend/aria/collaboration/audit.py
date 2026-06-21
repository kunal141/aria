"""
Work Ledger event construction for the V3.7 team-collaboration store.

Mirrors the other audit modules: every event is built here, then enqueued into the
collaboration store's transactional **audit outbox** in the same SQLite transaction
as the state change and flushed to the Work Ledger — so state and audit can never
diverge. Identifiers (draft/context/approval-request ids, goal/task/workspace ids,
draft_type, status) ride in the sanitised ``metadata`` dict; ``source_refs`` are
sanitised here as defence-in-depth (the writer re-validates + redacts as the final
boundary). Nothing here sends, posts, or mutates any external system.
"""
from __future__ import annotations

from typing import Any

from aria.goals.sanitize import sanitize_text
from aria.ledger import (
    ActorType,
    ApprovalRequestDrafted,
    CollaborationContextCreated,
    CollaborationDraftCreated,
    CollaborationDraftUpdated,
    HandoffNoteCreated,
    LedgerEventType,
    RiskEscalationDrafted,
    StakeholderQuestionCreated,
)
from aria.ledger.events import RiskLevel, make_envelope

_EVENT_CLASSES = {
    LedgerEventType.collaboration_context_created: CollaborationContextCreated,
    LedgerEventType.collaboration_draft_created:   CollaborationDraftCreated,
    LedgerEventType.collaboration_draft_updated:   CollaborationDraftUpdated,
    LedgerEventType.approval_request_drafted:      ApprovalRequestDrafted,
    LedgerEventType.handoff_note_created:          HandoffNoteCreated,
    LedgerEventType.stakeholder_question_created:  StakeholderQuestionCreated,
    LedgerEventType.risk_escalation_drafted:       RiskEscalationDrafted,
}

_RISK_LEVELS = {r.value: r for r in RiskLevel}


def _coerce_risk(value: str | RiskLevel | None) -> RiskLevel | None:
    if value is None or isinstance(value, RiskLevel):
        return value
    return _RISK_LEVELS.get(str(value).strip().lower(), RiskLevel.low)


def build_collaboration_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    draft_id: str | None = None,
    context_id: str | None = None,
    approval_request_id: str | None = None,
    draft_type: str | None = None,
    goal_id: str | None = None,
    task_ref: str | None = None,
    workspace_id: str | None = None,
    status: str | None = None,
    source_refs: list[str] | None = None,
    execution_mode: str | None = None,
    outcome: str | None = None,
    risk_level: str | RiskLevel | None = "low",
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("draft_id", draft_id),
        ("context_id", context_id),
        ("approval_request_id", approval_request_id),
        ("draft_type", draft_type),
        ("goal_id", goal_id),
        ("task_id", task_ref),
        ("workspace_id", workspace_id),
        ("status", status),
        ("execution_mode", execution_mode),
    ):
        if value is not None:
            meta[key] = value
    if source_refs:
        meta["source_refs"] = [sanitize_text(r) or "" for r in source_refs]
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or goal_id or draft_id or task_id,
        outcome=outcome,
        risk_level=_coerce_risk(risk_level),
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
