"""
Model Routing Service (V4.2) — governed route lifecycle.

Ties the V4.2 pieces together: seed/register the (mock) provider registry + profiles +
policies; create a bounded route request; run it through the deny-by-default policy gate and
the profile-aware :class:`GovernedModelRouter`; persist a governed :class:`PersistedRouteDecision`
through the hardened store; optionally emit a source-linked evaluation record; and soft-link
the decision to a V4.1 runtime-adapter request via ``adapter_request_id`` / ``correlation_id``.

DECISION-ONLY / MOCK-LOCAL: nothing here calls a model, provider, network, SDK, or credential.
``ARIA_USER_ID`` is attribution only. Every decision carries ``executed=False``.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from aria.model_routing.models import (
    PersistedRouteDecision,
    ProviderStatus,
    RouteRequest,
    RouteStatus,
)
from aria.model_routing.policy import RoutingPolicyGate
from aria.model_routing.selection import GovernedModelRouter, RouteSelection
from aria.model_routing.store import ModelRoutingStore
from aria.runtime_adapters.harness import EvalOutcome, EvaluationHook
from aria.runtime_adapters.model_router import (
    DEFAULT_MOCK_PROVIDERS,
    FallbackPolicy,
    ModelCategory,
    ModelCostLatencyProfile,
    ModelProvider,
    ModelRiskProfile,
    SovereigntyPolicy,
    TrustBoundary,
)

# Deterministic mock cost/latency profiles per default model (declared bands — NOT billing).
_SEED_COSTS: dict[str, tuple[float, float, int]] = {
    "mock-frontier-x":   (0.010, 0.030, 900),
    "mock-open-x":       (0.001, 0.002, 400),
    "mock-coding-x":     (0.0008, 0.0016, 350),
    "mock-reasoning-x":  (0.006, 0.018, 800),
    "mock-embed-x":      (0.0001, 0.0, 120),
    "mock-rerank-x":     (0.0002, 0.0, 150),
    "mock-local-open-x": (0.0, 0.0, 250),
    "mock-fallback-x":   (0.0, 0.0, 500),
}
# Deterministic mock risk profiles. Cloud models carry higher data-egress risk.
_SEED_RISKS: dict[str, tuple[str, str, str]] = {
    "mock-frontier-x":   ("high", "medium", "medium"),
    "mock-open-x":       ("medium", "low", "low"),
    "mock-coding-x":     ("medium", "low", "low"),
    "mock-reasoning-x":  ("high", "medium", "medium"),
    "mock-embed-x":      ("low", "low", "low"),
    "mock-rerank-x":     ("low", "low", "low"),
    "mock-local-open-x": ("low", "low", "low"),
    "mock-fallback-x":   ("low", "low", "low"),
}


def _now() -> datetime:
    return datetime.now(UTC)


class ModelRoutingService:
    def __init__(self, store: ModelRoutingStore, *, execution_mode: str | None = None,
                 actor: str = "aria") -> None:
        self._store = store
        self._execution_mode = execution_mode
        self._actor = actor
        self._policy = RoutingPolicyGate()
        self._hook = EvaluationHook()

    def _router_for(self, store: ModelRoutingStore) -> GovernedModelRouter:
        # Use the store's persisted fallback policies when present; else the V4.1 defaults.
        return GovernedModelRouter(fallback_policies=store.get_fallback_policies() or None)

    # ── Registry seeding + passthroughs ────────────────────────────────────────

    def register_provider(self, provider: ModelProvider, *, status: ProviderStatus | None = None,
                          actor: str | None = None) -> ModelProvider:
        return self._store.register_provider(provider, status=status, actor=actor or self._actor)

    def set_provider_status(self, provider_id: str, status: ProviderStatus, *,
                            actor: str | None = None) -> ModelProvider:
        return self._store.set_provider_status(provider_id, status, actor=actor or self._actor)

    def list_providers(self, *, category: str | None = None, status: str | None = None):
        return self._store.list_providers(category=category, status=status)

    def get_provider(self, provider_id: str):
        return self._store.get_provider(provider_id)

    def register_default_providers(self, *, actor: str | None = None) -> list[ModelProvider]:
        """Seed the 8 declared mock providers + their cost/risk profiles + fallback policies +
        a default (any_cloud) and a private_only sovereignty policy. No real vendor, no key."""
        actor = actor or self._actor
        out: list[ModelProvider] = []
        for p in DEFAULT_MOCK_PROVIDERS:
            out.append(self._store.register_provider(p, status=ProviderStatus.declared, actor=actor))
            cin, cout, lat = _SEED_COSTS.get(p.model_id, (0.0, 0.0, 0))
            self._store.register_cost_profile(ModelCostLatencyProfile(
                model_id=p.model_id, cost_per_1k_input=cin, cost_per_1k_output=cout,
                typical_latency_ms=lat))
            egress, priv, outp = _SEED_RISKS.get(p.model_id, ("low", "low", "low"))
            self._store.register_risk_profile(ModelRiskProfile(
                model_id=p.model_id, data_egress_risk=egress, privacy_risk=priv, output_risk=outp))
        # Fallback policies (reuse the V4.1 defaults).
        from aria.runtime_adapters.model_router import DEFAULT_FALLBACK_POLICIES
        for category, chain in DEFAULT_FALLBACK_POLICIES.items():
            self._store.register_fallback_policy(FallbackPolicy(category=category,
                                                              ordered_fallback=chain))
        # Named sovereignty policies.
        self._store.register_sovereignty_policy(SovereigntyPolicy(name="default"))
        self._store.register_sovereignty_policy(SovereigntyPolicy(
            name="private_only", boundary=TrustBoundary.private_only, forbid_data_egress=True,
            reason="data residency / no cloud egress"))
        return out

    # ── Route lifecycle ─────────────────────────────────────────────────────────

    def create_route_request(self, *, intent: str, task_type: str | None = None,
                            sovereignty_name: str = "default", adapter_request_id: str | None = None,
                            source_refs: list[str] | None = None,
                            evidence_refs: list[str] | None = None,
                            actor: str | None = None) -> RouteRequest:
        actor = actor or self._actor
        req = RouteRequest(
            request_id=f"rtr-{uuid.uuid4().hex}", intent=intent, task_type=task_type,
            sovereignty_name=sovereignty_name, adapter_request_id=adapter_request_id,
            source_refs=list(source_refs or []), evidence_refs=list(evidence_refs or []),
            status=RouteStatus.requested, created_at=_now(),
        )
        return self._store.create_route_request(req, actor=actor)

    def decide(self, request_id: str, *, actor: str | None = None) -> PersistedRouteDecision:
        """Run the governed decision for an existing route request and persist it."""
        actor = actor or self._actor
        request = self._store.get_route_request(request_id)
        if request is None:
            raise ValueError(f"route request {request_id!r} not found")
        sovereignty = (self._store.get_sovereignty_policy(request.sovereignty_name)
                       or SovereigntyPolicy())

        gate = self._policy.evaluate(request, sovereignty)
        correlation_id = request.adapter_request_id or request.request_id
        now = _now()

        if not gate.allowed:
            decision = PersistedRouteDecision(
                decision_id=f"rtd-{uuid.uuid4().hex}", route_request_id=request.request_id,
                correlation_id=correlation_id, adapter_request_id=request.adapter_request_id,
                intent=request.intent, task_type=request.task_type,
                chosen_category=ModelCategory.fallback_model, chosen_model_id=None,
                chosen_provider_id=None, providers_considered=[], fallback_chain=[],
                sovereignty_boundary=gate.sovereignty_boundary, sovereignty_applied=False,
                fallback_used=False, cost_estimate=None, risk_summary="unknown", allowed=False,
                blocked_reasons=list(gate.blocked_reasons), note=gate.safe_message, executed=False,
                source_refs=list(request.source_refs), evidence_refs=list(request.evidence_refs),
                created_at=now,
            )
            return self._persist(decision, request)

        selection = self._router_for(self._store).route(
            intent=request.intent, task_type=request.task_type,
            providers=self._store.list_providers(), cost_profiles=self._store.list_cost_profiles(),
            risk_profiles=self._store.list_risk_profiles(), sovereignty=sovereignty)
        decision = self._to_persisted(selection, request, correlation_id, now)
        return self._persist(decision, request)

    def route(self, *, intent: str, task_type: str | None = None, sovereignty_name: str = "default",
              adapter_request_id: str | None = None, source_refs: list[str] | None = None,
              evidence_refs: list[str] | None = None,
              actor: str | None = None) -> PersistedRouteDecision:
        """Create a route request and immediately decide it (the common one-shot path)."""
        request = self.create_route_request(
            intent=intent, task_type=task_type, sovereignty_name=sovereignty_name,
            adapter_request_id=adapter_request_id, source_refs=source_refs,
            evidence_refs=evidence_refs, actor=actor)
        return self.decide(request.request_id, actor=actor)

    def _to_persisted(self, selection: RouteSelection, request: RouteRequest, correlation_id: str,
                      now: datetime) -> PersistedRouteDecision:
        d = selection.decision
        return PersistedRouteDecision(
            decision_id=f"rtd-{uuid.uuid4().hex}", route_request_id=request.request_id,
            correlation_id=correlation_id, adapter_request_id=request.adapter_request_id,
            intent=d.intent, task_type=d.task_type, chosen_category=d.chosen_category,
            chosen_model_id=d.chosen_model_id, chosen_provider_id=selection.chosen_provider_id,
            providers_considered=list(selection.providers_considered),
            fallback_chain=list(d.fallback_chain), sovereignty_boundary=d.sovereignty_boundary,
            sovereignty_applied=selection.sovereignty_applied, fallback_used=selection.fallback_used,
            cost_estimate=selection.cost_estimate, risk_summary=selection.risk_summary,
            allowed=d.allowed, blocked_reasons=list(d.blocked_reasons), note=d.note, executed=False,
            source_refs=list(request.source_refs), evidence_refs=list(request.evidence_refs),
            created_at=now,
        )

    def _persist(self, decision: PersistedRouteDecision, request: RouteRequest
                 ) -> PersistedRouteDecision:
        created = self._store.record_route_decision(decision, actor=self._actor)
        # Source-linked evaluation of the ROUTING DECISION (not model output). Best-effort.
        try:
            record = self._hook.build_record(
                input_ref=f"route_request:{request.request_id}",
                output_ref=f"route_decision:{created.decision_id}",
                model_id=created.chosen_model_id, task_id=request.adapter_request_id,
                expected_behavior="deterministic policy route, no model execution",
                actual_behavior=(created.note or created.chosen_category.value)[:200],
                score=1.0 if created.allowed else 0.0,
                pass_fail=EvalOutcome.pass_ if created.allowed else EvalOutcome.fail,
                failure_reason="" if created.allowed else "; ".join(created.blocked_reasons)[:200],
                cost_estimate=created.cost_estimate if created.cost_estimate is not None else 0.0,
                latency_ms=0)
            self._store.create_eval_record(record)
        except Exception:  # pragma: no cover - eval is best-effort, never fatal
            pass
        return created

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_route_request(self, request_id: str) -> RouteRequest | None:
        return self._store.get_route_request(request_id)

    def get_route_decision(self, decision_id: str) -> PersistedRouteDecision | None:
        return self._store.get_route_decision(decision_id)

    def list_route_decisions(self, *, route_request_id: str | None = None,
                            adapter_request_id: str | None = None) -> list[PersistedRouteDecision]:
        return self._store.list_route_decisions(route_request_id=route_request_id,
                                               adapter_request_id=adapter_request_id)

    def list_eval_records(self, *, model_id: str | None = None):
        return self._store.list_eval_records(model_id=model_id)
