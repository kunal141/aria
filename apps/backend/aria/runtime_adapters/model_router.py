"""
Model Router + Sovereignty — CONTRACTS + deterministic MOCK router (V4.1).

AI architecture is moving from "one best model" to governed model/runtime
orchestration. ARIA must not hard-depend on one cloud provider or one model. This
module defines the *contracts* (provider registry, capability/cost/risk profiles,
fallback + sovereignty policies) and a **deterministic MockModelRouter that only makes
route DECISIONS** — it NEVER calls a model, uses NO API key, NO SDK, and NO network.

All models here are declared metadata / decisions — nothing executes a model.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ModelCategory(str, Enum):
    frontier_cloud_model = "frontier_cloud_model"
    open_cloud_model = "open_cloud_model"
    local_open_model = "local_open_model"
    coding_model = "coding_model"
    reasoning_model = "reasoning_model"
    embedding_model = "embedding_model"
    reranker_model = "reranker_model"
    fallback_model = "fallback_model"


# Categories that leave the local boundary (cloud). Sovereignty policy can forbid these.
_CLOUD_CATEGORIES = frozenset({
    ModelCategory.frontier_cloud_model, ModelCategory.open_cloud_model,
})
# Local/offline-capable categories used when data must not egress.
_LOCAL_CATEGORIES = frozenset({ModelCategory.local_open_model, ModelCategory.fallback_model})


class TrustBoundary(str, Enum):
    any_cloud = "any_cloud"        # cloud models permitted
    private_only = "private_only"  # no data egress; local/open only
    local_only = "local_only"      # strictly local


class ModelProvider(BaseModel):
    """A model provider/model registry entry — DATA ONLY. Never a live SDK client; no
    credential is stored or required."""
    model_config = ConfigDict(frozen=True)

    provider_id: str
    vendor: str
    model_id: str
    category: ModelCategory
    enabled: bool = True
    status: str = "declared"       # declared registry entry; not a live connection


class ModelCapabilityProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    model_id: str
    categories: list[ModelCategory] = Field(default_factory=list)
    context_window: int = 8192
    modalities: list[str] = Field(default_factory=lambda: ["text"])
    strengths: list[str] = Field(default_factory=list)


class ModelCostLatencyProfile(BaseModel):
    """Declared cost/latency bands used for routing + ROI/eval — NOT billing, no live
    metering."""
    model_config = ConfigDict(frozen=True)
    model_id: str
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    typical_latency_ms: int = 0


class ModelRiskProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    model_id: str
    data_egress_risk: str = "low"
    privacy_risk: str = "low"
    output_risk: str = "low"
    notes: str = ""


class FallbackPolicy(BaseModel):
    """Ordered fallback chain per category (e.g. frontier → open_cloud → local_open)."""
    model_config = ConfigDict(frozen=True)
    category: ModelCategory
    ordered_fallback: list[ModelCategory] = Field(default_factory=list)


class SovereigntyPolicy(BaseModel):
    """When data may NOT leave a boundary (privacy / residency / export-control),
    forcing a local/open route or a hard block."""
    model_config = ConfigDict(frozen=True)
    name: str = "default"
    boundary: TrustBoundary = TrustBoundary.any_cloud
    forbid_data_egress: bool = False
    reason: str = ""


class RouteDecision(BaseModel):
    """A DECISION about which model category/model to use — never an execution."""
    model_config = ConfigDict(frozen=True)
    intent: str
    task_type: str | None = None
    chosen_category: ModelCategory
    chosen_model_id: str | None = None
    fallback_chain: list[ModelCategory] = Field(default_factory=list)
    sovereignty_boundary: TrustBoundary = TrustBoundary.any_cloud
    allowed: bool = True
    blocked_reasons: list[str] = Field(default_factory=list)
    note: str = ""
    executed: bool = False         # ALWAYS False in V4.1 — routing decides, never runs


# Intent → target category (deterministic). Mirrors the V4.1 scope routing examples.
_INTENT_CATEGORY = {
    "hard_reasoning": ModelCategory.reasoning_model,
    "high_risk_planning": ModelCategory.frontier_cloud_model,
    "coding": ModelCategory.coding_model,
    "summarization": ModelCategory.open_cloud_model,
    "embedding": ModelCategory.embedding_model,
    "retrieval": ModelCategory.embedding_model,
    "rerank": ModelCategory.reranker_model,
    "private": ModelCategory.local_open_model,
    "offline": ModelCategory.local_open_model,
    "fallback": ModelCategory.fallback_model,
}

# A default, offline, MOCK provider registry — declared data only (no real vendors,
# no keys). Used so the router is testable without any provider configuration.
DEFAULT_MOCK_PROVIDERS: tuple[ModelProvider, ...] = (
    ModelProvider(provider_id="mock:frontier", vendor="mock", model_id="mock-frontier-x",
                  category=ModelCategory.frontier_cloud_model),
    ModelProvider(provider_id="mock:open", vendor="mock", model_id="mock-open-x",
                  category=ModelCategory.open_cloud_model),
    ModelProvider(provider_id="mock:coding", vendor="mock", model_id="mock-coding-x",
                  category=ModelCategory.coding_model),
    ModelProvider(provider_id="mock:reasoning", vendor="mock", model_id="mock-reasoning-x",
                  category=ModelCategory.reasoning_model),
    ModelProvider(provider_id="mock:embed", vendor="mock", model_id="mock-embed-x",
                  category=ModelCategory.embedding_model),
    ModelProvider(provider_id="mock:rerank", vendor="mock", model_id="mock-rerank-x",
                  category=ModelCategory.reranker_model),
    ModelProvider(provider_id="mock:local", vendor="mock", model_id="mock-local-open-x",
                  category=ModelCategory.local_open_model),
    ModelProvider(provider_id="mock:fallback", vendor="mock", model_id="mock-fallback-x",
                  category=ModelCategory.fallback_model),
)

DEFAULT_FALLBACK_POLICIES: dict[ModelCategory, list[ModelCategory]] = {
    ModelCategory.frontier_cloud_model: [ModelCategory.open_cloud_model,
                                         ModelCategory.local_open_model,
                                         ModelCategory.fallback_model],
    ModelCategory.reasoning_model: [ModelCategory.frontier_cloud_model,
                                    ModelCategory.local_open_model, ModelCategory.fallback_model],
    ModelCategory.coding_model: [ModelCategory.open_cloud_model, ModelCategory.local_open_model,
                                 ModelCategory.fallback_model],
    ModelCategory.open_cloud_model: [ModelCategory.local_open_model, ModelCategory.fallback_model],
    ModelCategory.embedding_model: [ModelCategory.local_open_model, ModelCategory.fallback_model],
    ModelCategory.reranker_model: [ModelCategory.local_open_model, ModelCategory.fallback_model],
    ModelCategory.local_open_model: [ModelCategory.fallback_model],
    ModelCategory.fallback_model: [],
}


class MockModelRouter:
    """Deterministic, OFFLINE route decisions only. It makes NO model call, uses NO API
    key, NO SDK, and NO network. It picks a category from the intent, honours the
    sovereignty policy (downgrading a cloud route to a local one when data egress is
    forbidden), resolves a declared model id from the (mock) provider registry, and
    returns a :class:`RouteDecision` — never executing a model."""

    def __init__(self, providers=None, fallback_policies=None) -> None:
        self._providers = list(providers if providers is not None else DEFAULT_MOCK_PROVIDERS)
        self._fallback = dict(fallback_policies if fallback_policies is not None
                              else DEFAULT_FALLBACK_POLICIES)

    def _model_for(self, category: ModelCategory) -> str | None:
        for p in self._providers:
            if p.category is category and p.enabled:
                return p.model_id
        return None

    def route(self, *, intent: str, task_type: str | None = None,
              sovereignty: SovereigntyPolicy | None = None) -> RouteDecision:
        sovereignty = sovereignty or SovereigntyPolicy()
        category = _INTENT_CATEGORY.get(intent, ModelCategory.fallback_model)
        blocked: list[str] = []
        note = f"intent '{intent}' → {category.value}"

        # Sovereignty: if data must not egress, a cloud category is downgraded to local.
        egress_forbidden = (sovereignty.forbid_data_egress
                            or sovereignty.boundary in (TrustBoundary.private_only,
                                                        TrustBoundary.local_only))
        if egress_forbidden and category in _CLOUD_CATEGORIES:
            local = ModelCategory.local_open_model
            if self._model_for(local) is not None:
                note += f"; sovereignty ({sovereignty.boundary.value}) forbids cloud egress "
                note += f"→ downgraded to {local.value}"
                category = local
            else:
                blocked.append("sovereignty forbids cloud egress and no local/open model "
                               "is available (outage/export-control fallback needed)")

        chosen = self._model_for(category)
        if chosen is None and not blocked:
            # Provider outage / export-control fallback: walk the fallback chain.
            for fb in self._fallback.get(category, []):
                if egress_forbidden and fb in _CLOUD_CATEGORIES:
                    continue
                chosen = self._model_for(fb)
                if chosen is not None:
                    note += f"; primary unavailable → fell back to {fb.value}"
                    category = fb
                    break
            if chosen is None:
                blocked.append(f"no model available for {category.value} or its fallbacks")

        return RouteDecision(
            intent=intent, task_type=task_type, chosen_category=category, chosen_model_id=chosen,
            fallback_chain=list(self._fallback.get(category, [])),
            sovereignty_boundary=sovereignty.boundary, allowed=not blocked,
            blocked_reasons=blocked, note=note, executed=False,
        )
