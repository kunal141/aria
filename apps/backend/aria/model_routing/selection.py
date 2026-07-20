"""
Governed model-route selection (V4.2) — deterministic, profile-aware, DECISION-ONLY.

Builds on the V4.1 pure router logic (intent→category map, sovereignty downgrade, fallback
chain) and adds the piece V4.1 never had: it actually CONSUMES the cost/latency/risk
profiles. Among the eligible providers in the target category it selects the **cheapest
eligible provider** (tie-break: typical latency, then ``provider_id`` for determinism),
after hard-excluding disabled / outage / export-restricted providers and — when sovereignty
forbids egress — high-data-egress-risk providers.

It makes NO model call, uses NO API key, NO SDK, and NO network. Every result carries
``executed=False``.
"""
from __future__ import annotations

from math import inf

from pydantic import BaseModel, ConfigDict, Field

from aria.model_routing.models import ELIGIBLE_PROVIDER_STATUSES, ProviderStatus
from aria.runtime_adapters.model_router import (
    _CLOUD_CATEGORIES,
    _INTENT_CATEGORY,
    DEFAULT_FALLBACK_POLICIES,
    ModelCategory,
    ModelCostLatencyProfile,
    ModelProvider,
    ModelRiskProfile,
    RouteDecision,
    SovereigntyPolicy,
    TrustBoundary,
)

_LOCAL_CATEGORY = ModelCategory.local_open_model


class RouteSelection(BaseModel):
    """The full selection result — the pure ``RouteDecision`` plus provider-level provenance
    the persisted decision records for audit."""
    model_config = ConfigDict(frozen=True)

    decision: RouteDecision
    chosen_provider_id: str | None = None
    providers_considered: list[str] = Field(default_factory=list)
    cost_estimate: float | None = None
    risk_summary: str = ""
    fallback_used: bool = False
    sovereignty_applied: bool = False


def _status_of(provider: ModelProvider) -> ProviderStatus:
    try:
        status = ProviderStatus(provider.status)
    except ValueError:
        status = ProviderStatus.declared
    return status


def _egress_forbidden(sovereignty: SovereigntyPolicy) -> bool:
    return (sovereignty.forbid_data_egress
            or sovereignty.boundary in (TrustBoundary.private_only, TrustBoundary.local_only))


class GovernedModelRouter:
    """Deterministic, offline, profile-aware route selection. No model call, no key, no
    SDK, no network. Providers/profiles are passed in (loaded by the service from the
    governed store) so this class stays pure and testable."""

    def __init__(self, fallback_policies: dict[ModelCategory, list[ModelCategory]] | None = None
                 ) -> None:
        self._fallback = dict(fallback_policies if fallback_policies is not None
                              else DEFAULT_FALLBACK_POLICIES)

    # ── eligibility + ranking ───────────────────────────────────────────────────

    def _eligible(self, provider: ModelProvider, *, egress_forbidden: bool,
                  risk_profiles: dict[str, ModelRiskProfile]) -> bool:
        if not provider.enabled:
            return False
        if _status_of(provider) not in ELIGIBLE_PROVIDER_STATUSES:
            return False  # disabled / outage / export_restricted
        if egress_forbidden:
            risk = risk_profiles.get(provider.model_id)
            if risk is not None and risk.data_egress_risk == "high":
                return False
        return True

    @staticmethod
    def _cost(model_id: str, cost_profiles: dict[str, ModelCostLatencyProfile]) -> float:
        p = cost_profiles.get(model_id)
        return inf if p is None else (p.cost_per_1k_input + p.cost_per_1k_output)

    @staticmethod
    def _latency(model_id: str, cost_profiles: dict[str, ModelCostLatencyProfile]) -> int:
        p = cost_profiles.get(model_id)
        return 10 ** 9 if p is None else p.typical_latency_ms

    def _pick(self, category: ModelCategory, providers: list[ModelProvider], *,
              egress_forbidden: bool, cost_profiles: dict[str, ModelCostLatencyProfile],
              risk_profiles: dict[str, ModelRiskProfile]) -> tuple[ModelProvider | None, list[str]]:
        """Return (cheapest eligible provider in ``category``, considered provider ids)."""
        candidates = [p for p in providers if p.category is category
                      and self._eligible(p, egress_forbidden=egress_forbidden,
                                         risk_profiles=risk_profiles)]
        considered = sorted(p.provider_id for p in candidates)
        if not candidates:
            return None, considered
        best = min(candidates, key=lambda p: (self._cost(p.model_id, cost_profiles),
                                              self._latency(p.model_id, cost_profiles),
                                              p.provider_id))
        return best, considered

    def _risk_summary(self, model_id: str | None,
                      risk_profiles: dict[str, ModelRiskProfile]) -> str:
        r = risk_profiles.get(model_id) if model_id else None
        if r is None:
            return "unknown"
        return (f"egress={r.data_egress_risk}, privacy={r.privacy_risk}, "
                f"output={r.output_risk}")

    # ── main entry ──────────────────────────────────────────────────────────────

    def route(self, *, intent: str, task_type: str | None, providers: list[ModelProvider],
              cost_profiles: dict[str, ModelCostLatencyProfile],
              risk_profiles: dict[str, ModelRiskProfile],
              sovereignty: SovereigntyPolicy | None = None) -> RouteSelection:
        sovereignty = sovereignty or SovereigntyPolicy()
        egress_forbidden = _egress_forbidden(sovereignty)
        target = _INTENT_CATEGORY.get(intent, ModelCategory.fallback_model)
        note = f"intent '{intent}' → {target.value}"
        blocked: list[str] = []
        sovereignty_applied = False

        # 1) Sovereignty: a cloud category is downgraded to local when egress is forbidden.
        if egress_forbidden and target in _CLOUD_CATEGORIES:
            note += (f"; sovereignty ({sovereignty.boundary.value}"
                     f"{', no-egress' if sovereignty.forbid_data_egress else ''}) "
                     f"forbids cloud egress → downgraded to {_LOCAL_CATEGORY.value}")
            target = _LOCAL_CATEGORY
            sovereignty_applied = True

        # 2) Profile-aware pick in the (possibly downgraded) target category.
        chosen, considered = self._pick(target, providers, egress_forbidden=egress_forbidden,
                                        cost_profiles=cost_profiles, risk_profiles=risk_profiles)
        fallback_used = False

        # 3) Fallback chain when the target has no eligible provider.
        if chosen is None:
            for fb in self._fallback.get(target, []):
                if egress_forbidden and fb in _CLOUD_CATEGORIES:
                    continue  # never fall back to a cloud category under sovereignty
                cand, cand_considered = self._pick(fb, providers, egress_forbidden=egress_forbidden,
                                                   cost_profiles=cost_profiles,
                                                   risk_profiles=risk_profiles)
                considered = sorted(set(considered) | set(cand_considered))
                if cand is not None:
                    note += f"; primary category unavailable → fell back to {fb.value}"
                    target = fb
                    chosen = cand
                    fallback_used = True
                    break

        # 4) Blocked when nothing eligible remains.
        if chosen is None:
            reason = ("sovereignty forbids cloud egress and no eligible local/open model is "
                      "available (outage/export-control fallback exhausted)" if egress_forbidden
                      else f"no eligible model available for {target.value} or its fallbacks")
            blocked.append(reason)

        chosen_model_id = chosen.model_id if chosen else None
        chosen_provider_id = chosen.provider_id if chosen else None
        cost_estimate = (self._cost(chosen_model_id, cost_profiles)
                         if chosen_model_id else None)
        if cost_estimate == inf:
            cost_estimate = None

        decision = RouteDecision(
            intent=intent, task_type=task_type, chosen_category=target,
            chosen_model_id=chosen_model_id,
            fallback_chain=list(self._fallback.get(target, [])),
            sovereignty_boundary=sovereignty.boundary, allowed=not blocked,
            blocked_reasons=blocked, note=note, executed=False,
        )
        return RouteSelection(
            decision=decision, chosen_provider_id=chosen_provider_id,
            providers_considered=considered, cost_estimate=cost_estimate,
            risk_summary=self._risk_summary(chosen_model_id, risk_profiles),
            fallback_used=fallback_used, sovereignty_applied=sovereignty_applied,
        )
