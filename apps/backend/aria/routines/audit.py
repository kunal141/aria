"""
Work Ledger event construction for the V3.8 scheduled-routines store.

Mirrors the other audit modules: every event is built here, then enqueued into the
routine store's transactional **audit outbox** in the same SQLite transaction as the
state change and flushed to the Work Ledger — so state and audit can never diverge.
Identifiers (routine/run/output/draft/goal/workspace ids, routine_type, status) ride
in the sanitised ``metadata`` dict; ``safe_error`` is class/code-only (never raw
exception text). Nothing here runs a daemon or performs an external action.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    LedgerEventType,
    RoutineDefined,
    RoutineDisabled,
    RoutineDue,
    RoutineEnabled,
    RoutineFollowupDrafted,
    RoutineOutputCreated,
    RoutineRunCompleted,
    RoutineRunFailed,
    RoutineRunMissed,
    RoutineRunStarted,
)
from aria.ledger.events import RiskLevel, make_envelope

_EVENT_CLASSES = {
    LedgerEventType.routine_defined:          RoutineDefined,
    LedgerEventType.routine_enabled:          RoutineEnabled,
    LedgerEventType.routine_disabled:         RoutineDisabled,
    LedgerEventType.routine_due:              RoutineDue,
    LedgerEventType.routine_run_started:      RoutineRunStarted,
    LedgerEventType.routine_run_completed:    RoutineRunCompleted,
    LedgerEventType.routine_run_failed:       RoutineRunFailed,
    LedgerEventType.routine_run_missed:       RoutineRunMissed,
    LedgerEventType.routine_output_created:   RoutineOutputCreated,
    LedgerEventType.routine_followup_drafted: RoutineFollowupDrafted,
}

_RISK_LEVELS = {r.value: r for r in RiskLevel}


def _coerce_risk(value: str | RiskLevel | None) -> RiskLevel | None:
    if value is None or isinstance(value, RiskLevel):
        return value
    return _RISK_LEVELS.get(str(value).strip().lower(), RiskLevel.low)


def build_routine_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    routine_id: str | None = None,
    run_id: str | None = None,
    output_id: str | None = None,
    draft_id: str | None = None,
    routine_type: str | None = None,
    goal_id: str | None = None,
    workspace_id: str | None = None,
    status: str | None = None,
    safe_error: str | None = None,
    execution_mode: str | None = None,
    outcome: str | None = None,
    risk_level: str | RiskLevel | None = "low",
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("routine_id", routine_id),
        ("run_id", run_id),
        ("output_id", output_id),
        ("draft_id", draft_id),
        ("routine_type", routine_type),
        ("goal_id", goal_id),
        ("workspace_id", workspace_id),
        ("status", status),
        ("safe_error", safe_error),
        ("execution_mode", execution_mode),
    ):
        if value is not None:
            meta[key] = value
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or routine_id or run_id or task_id,
        outcome=outcome,
        risk_level=_coerce_risk(risk_level),
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
