"""
V4.2 model-routing models — the *persisted* layer on top of the V4.1 contracts.

The routing **contracts** (categories, provider, capability/cost/risk profiles, fallback +
sovereignty policies, ``RouteDecision``) already live in
``aria.runtime_adapters.model_router`` and are REUSED, not duplicated. This module adds
only the V4.2-specific persisted models: a bounded ``RouteRequest``, a
``PersistedRouteDecision`` (a governed, auditable record of one route choice), and the two
status enums the store/router need.

Every route is a DECISION. ``PersistedRouteDecision.executed`` is structurally forced to
``False`` — the model itself refuses to hold ``executed=True``. Nothing here executes a
model, calls a provider, uses a network/SDK, or touches a credential.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aria.runtime_adapters.model_router import ModelCategory, TrustBoundary

ROUTING_BOUNDARY = (
    "V4.2 model routing is DECISION-ONLY: it chooses a model category/provider by policy "
    "using deterministic mock provider metadata. It never calls a model, never uses an API "
    "key, SDK, or network, and never executes anything. RouteDecision.executed is always False."
)


class RouteStatus(str, Enum):
    """Lifecycle of a route request."""
    requested = "requested"
    decided = "decided"
    blocked = "blocked"


class ProviderStatus(str, Enum):
    """Registry status of a model provider — governs routing ELIGIBILITY only.

    ``declared``/``enabled`` are eligible; ``disabled``/``outage``/``export_restricted``
    are hard-excluded from being chosen as a successful route.
    """
    declared = "declared"
    enabled = "enabled"
    disabled = "disabled"
    outage = "outage"
    export_restricted = "export_restricted"


# Provider statuses eligible to be *chosen* by a successful route.
ELIGIBLE_PROVIDER_STATUSES: frozenset[ProviderStatus] = frozenset(
    {ProviderStatus.declared, ProviderStatus.enabled}
)


class RouteRequest(BaseModel):
    """A bounded proposal to choose a model by policy — never a model call.

    ``adapter_request_id`` is the SOFT LINK to a V4.1 runtime-adapter request (which mock
    worker this route is for); it is a plain id reference — the V4.1 adapter storage is
    never read or migrated. ``sovereignty_name`` references a persisted sovereignty policy.
    """
    model_config = ConfigDict(frozen=True)

    request_id: str
    intent: str
    task_type: str | None = None
    sovereignty_name: str = "default"
    adapter_request_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    status: RouteStatus = RouteStatus.requested
    created_at: datetime


class PersistedRouteDecision(BaseModel):
    """A governed, auditable record of one route choice.

    Composes the pure ``RouteDecision`` (category/model/fallback/sovereignty/allowed) with
    persistence + provenance metadata (ids, chosen provider, cost, risk summary, considered
    providers, correlation + adapter soft-link, source refs). ``executed`` is structurally
    ``False`` — a validator refuses ``True`` so no persisted decision can ever claim a model ran.
    """
    model_config = ConfigDict(frozen=True)

    decision_id: str
    route_request_id: str
    correlation_id: str
    adapter_request_id: str | None = None

    intent: str
    task_type: str | None = None

    chosen_category: ModelCategory
    chosen_model_id: str | None = None
    chosen_provider_id: str | None = None
    providers_considered: list[str] = Field(default_factory=list)
    fallback_chain: list[ModelCategory] = Field(default_factory=list)

    sovereignty_boundary: TrustBoundary = TrustBoundary.any_cloud
    sovereignty_applied: bool = False
    fallback_used: bool = False

    cost_estimate: float | None = None
    risk_summary: str = ""

    allowed: bool = True
    blocked_reasons: list[str] = Field(default_factory=list)
    note: str = ""
    executed: bool = False

    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("executed")
    @classmethod
    def _never_executed(cls, v: bool) -> bool:
        # Structural guarantee: V4.2 routing decides, it never runs a model.
        if v:
            raise ValueError("PersistedRouteDecision.executed must be False — routing never "
                             "executes a model in V4.2")
        return v
