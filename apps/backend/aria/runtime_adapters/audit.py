"""
Work Ledger event construction for the V4.1 runtime-adapter store.

Mirrors the other audit modules: events are built here, enqueued into the store's
transactional **audit outbox** in the same SQLite transaction as the state change, and
flushed to the Work Ledger — so state and audit can never diverge. Identifiers
(adapter/request/receipt ids, adapter_type, execution_mode, status) ride in the
sanitised ``metadata`` dict; ``safe_error`` is class/code-only. Nothing here calls a
real external runtime, model, network, or credential.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    LedgerEventType,
    RuntimeAdapterBlocked,
    RuntimeAdapterDisabled,
    RuntimeAdapterDryRunCompleted,
    RuntimeAdapterEnabled,
    RuntimeAdapterExecutionFailed,
    RuntimeAdapterMockCompleted,
    RuntimeAdapterPreviewed,
    RuntimeAdapterReceiptCreated,
    RuntimeAdapterRegistered,
    RuntimeAdapterRequestCreated,
)
from aria.ledger.events import RiskLevel, make_envelope

_EVENT_CLASSES = {
    LedgerEventType.runtime_adapter_registered:        RuntimeAdapterRegistered,
    LedgerEventType.runtime_adapter_enabled:           RuntimeAdapterEnabled,
    LedgerEventType.runtime_adapter_disabled:          RuntimeAdapterDisabled,
    LedgerEventType.runtime_adapter_request_created:   RuntimeAdapterRequestCreated,
    LedgerEventType.runtime_adapter_previewed:         RuntimeAdapterPreviewed,
    LedgerEventType.runtime_adapter_blocked:           RuntimeAdapterBlocked,
    LedgerEventType.runtime_adapter_dry_run_completed: RuntimeAdapterDryRunCompleted,
    LedgerEventType.runtime_adapter_mock_completed:    RuntimeAdapterMockCompleted,
    LedgerEventType.runtime_adapter_execution_failed:  RuntimeAdapterExecutionFailed,
    LedgerEventType.runtime_adapter_receipt_created:   RuntimeAdapterReceiptCreated,
}

_RISK_LEVELS = {r.value: r for r in RiskLevel}


def _coerce_risk(value: str | RiskLevel | None) -> RiskLevel | None:
    if value is None or isinstance(value, RiskLevel):
        return value
    return _RISK_LEVELS.get(str(value).strip().lower(), RiskLevel.low)


def build_adapter_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    adapter_id: str | None = None,
    adapter_type: str | None = None,
    request_id: str | None = None,
    receipt_id: str | None = None,
    goal_id: str | None = None,
    task_ref: str | None = None,
    workspace_id: str | None = None,
    execution_mode: str | None = None,
    status: str | None = None,
    safe_error: str | None = None,
    runtime_mode: str | None = None,
    outcome: str | None = None,
    risk_level: str | RiskLevel | None = "low",
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("adapter_id", adapter_id),
        ("adapter_type", adapter_type),
        ("request_id", request_id),
        ("receipt_id", receipt_id),
        ("goal_id", goal_id),
        ("task_id", task_ref),
        ("workspace_id", workspace_id),
        ("execution_mode", execution_mode),
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
        correlation_id=correlation_id or adapter_id or request_id or task_id,
        outcome=outcome,
        risk_level=_coerce_risk(risk_level),
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
