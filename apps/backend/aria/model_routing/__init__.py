"""
aria.model_routing — V4.2 Model Router + Sovereignty Mock Layer.

ARIA chooses a model route BY POLICY without depending on one provider, using deterministic
mock provider metadata only. This package is the *governed, persisted* layer on top of the
V4.1 routing **contracts** (which live in ``aria.runtime_adapters.model_router`` and are
REUSED here, never duplicated): a path-confined SQLite registry + decision store with a
transactional audit outbox → Work Ledger, a profile-aware ``GovernedModelRouter`` that
selects the *cheapest eligible provider within a category* (risk / sovereignty / outage /
export restriction as hard exclusions), a deny-by-default policy gate, a source-linked eval
hook, and a soft-link to V4.1 runtime-adapter requests.

DECISION-ONLY / MOCK-LOCAL: nothing here executes a model, calls a provider, uses a network,
SDK, or credential. ``RouteDecision.executed`` is structurally always ``False``.

A SEPARATE package — importing it never drags in V1 LLM skills, and importing a V1 skill
never loads this layer.
"""
# Reused V4.1 contracts (single source of truth — not redefined here).
from aria.model_routing.models import (
    ELIGIBLE_PROVIDER_STATUSES,
    ROUTING_BOUNDARY,
    PersistedRouteDecision,
    ProviderStatus,
    RouteRequest,
    RouteStatus,
)
from aria.model_routing.policy import RoutingPolicyDecision, RoutingPolicyGate
from aria.model_routing.selection import GovernedModelRouter, RouteSelection
from aria.model_routing.service import ModelRoutingService
from aria.model_routing.store import (
    ModelRoutingStore,
    ProviderAlreadyExists,
    ProviderNotFound,
    RoutingIntegrityError,
    RoutingSecurityError,
)
from aria.runtime_adapters.model_router import (
    DEFAULT_FALLBACK_POLICIES,
    DEFAULT_MOCK_PROVIDERS,
    FallbackPolicy,
    ModelCapabilityProfile,
    ModelCategory,
    ModelCostLatencyProfile,
    ModelProvider,
    ModelRiskProfile,
    RouteDecision,
    SovereigntyPolicy,
    TrustBoundary,
)

__all__ = [
    # service + store
    "ModelRoutingService",
    "ModelRoutingStore",
    "ProviderNotFound",
    "ProviderAlreadyExists",
    "RoutingSecurityError",
    "RoutingIntegrityError",
    # V4.2 models
    "RouteRequest",
    "PersistedRouteDecision",
    "RouteStatus",
    "ProviderStatus",
    "ELIGIBLE_PROVIDER_STATUSES",
    "ROUTING_BOUNDARY",
    # selection + policy
    "GovernedModelRouter",
    "RouteSelection",
    "RoutingPolicyGate",
    "RoutingPolicyDecision",
    # reused V4.1 contracts
    "ModelCategory",
    "TrustBoundary",
    "ModelProvider",
    "ModelCapabilityProfile",
    "ModelCostLatencyProfile",
    "ModelRiskProfile",
    "FallbackPolicy",
    "SovereigntyPolicy",
    "RouteDecision",
    "DEFAULT_MOCK_PROVIDERS",
    "DEFAULT_FALLBACK_POLICIES",
]
