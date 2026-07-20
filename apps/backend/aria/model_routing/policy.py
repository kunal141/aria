"""
Routing Policy Gate (V4.2) — DENY-BY-DEFAULT pre-check for a route request.

A route request must be attributable (cite at least one source ref) before ARIA will make a
governed model choice. The gate also resolves the sovereignty posture (whether data egress
is forbidden) so the selection layer can enforce it. This is the FIRST governance boundary;
``ModelRoutingStore`` is the second, hard boundary that re-checks every persisted decision.

Stateless and deterministic — no I/O, no network, no model call, no credentials.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aria.model_routing.models import RouteRequest
from aria.runtime_adapters.model_router import SovereigntyPolicy, TrustBoundary


class RoutingPolicyDecision(BaseModel):
    """The governed verdict for a route request. ``allowed`` means 'not hard-blocked'; a
    blocked route is still recorded (as a blocked decision) for audit."""
    model_config = ConfigDict(frozen=True)

    allowed: bool
    egress_forbidden: bool
    sovereignty_boundary: TrustBoundary
    blocked_reasons: list[str] = Field(default_factory=list)
    safe_message: str = ""


class RoutingPolicyGate:
    """Deny-by-default evaluation of a route request against its sovereignty policy."""

    def evaluate(self, request: RouteRequest,
                 sovereignty: SovereigntyPolicy | None = None) -> RoutingPolicyDecision:
        sovereignty = sovereignty or SovereigntyPolicy()
        blocked: list[str] = []

        # Deny-by-default: a route must cite its sources (attribution / provenance).
        if not request.source_refs:
            blocked.append("missing source references (deny-by-default)")
        if not request.intent or not request.intent.strip():
            blocked.append("missing routing intent")

        egress_forbidden = (
            sovereignty.forbid_data_egress
            or sovereignty.boundary in (TrustBoundary.private_only, TrustBoundary.local_only)
        )
        allowed = not blocked
        safe = ("Route decision permitted (deterministic, decision-only)." if allowed
                else "Blocked by policy (deny-by-default): " + "; ".join(blocked))
        return RoutingPolicyDecision(
            allowed=allowed, egress_forbidden=egress_forbidden,
            sovereignty_boundary=sovereignty.boundary, blocked_reasons=blocked,
            safe_message=safe[:500])
