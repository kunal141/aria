"""
Work Ledger event construction for the V4.2 model-routing store.

Mirrors the other audit modules: events are built here, enqueued into the store's
transactional **audit outbox** in the same SQLite transaction as the state change, and
flushed to the Work Ledger — so state and audit can never diverge. Identifiers
(provider/request/decision ids, category, status, sovereignty boundary) ride in the
sanitised ``metadata`` dict. Nothing here calls a model, provider, network, or credential.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    LedgerEventType,
    ModelProviderRegistered,
    ModelProviderStatusChanged,
    ModelRouteBlocked,
    ModelRouteDecided,
    ModelRouteFallbackApplied,
    ModelRouteRequested,
)
from aria.ledger.events import RiskLevel, make_envelope

_EVENT_CLASSES = {
    LedgerEventType.model_provider_registered:     ModelProviderRegistered,
    LedgerEventType.model_provider_status_changed: ModelProviderStatusChanged,
    LedgerEventType.model_route_requested:         ModelRouteRequested,
    LedgerEventType.model_route_decided:           ModelRouteDecided,
    LedgerEventType.model_route_blocked:           ModelRouteBlocked,
    LedgerEventType.model_route_fallback_applied:  ModelRouteFallbackApplied,
}

_RISK_LEVELS = {r.value: r for r in RiskLevel}


def _coerce_risk(value: str | RiskLevel | None) -> RiskLevel | None:
    if value is None or isinstance(value, RiskLevel):
        return value
    return _RISK_LEVELS.get(str(value).strip().lower(), RiskLevel.low)


def build_route_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    category: str | None = None,
    request_id: str | None = None,
    decision_id: str | None = None,
    chosen_provider_id: str | None = None,
    adapter_request_id: str | None = None,
    sovereignty_boundary: str | None = None,
    fallback_used: bool | None = None,
    cost_estimate: float | None = None,
    status: str | None = None,
    runtime_mode: str | None = None,
    outcome: str | None = None,
    risk_level: str | RiskLevel | None = "low",
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("provider_id", provider_id),
        ("model_id", model_id),
        ("category", category),
        ("request_id", request_id),
        ("decision_id", decision_id),
        ("chosen_provider_id", chosen_provider_id),
        ("adapter_request_id", adapter_request_id),
        ("sovereignty_boundary", sovereignty_boundary),
        ("fallback_used", fallback_used),
        ("cost_estimate", cost_estimate),
        ("status", status),
        ("runtime_mode", runtime_mode),
    ):
        if value is not None:
            meta[key] = value
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or request_id or provider_id or task_id,
        outcome=outcome,
        risk_level=_coerce_risk(risk_level),
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
