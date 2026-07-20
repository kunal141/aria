"""
V4.2 — Model Router + Sovereignty Mock Layer tests.

Covers the governed provider registry, the deny-by-default routing policy gate, the
profile-aware GovernedModelRouter (cheapest eligible provider; risk / sovereignty / outage /
export-control hard exclusions; fallback-chain walking), the hardened path-confined store
authority boundary, the source-linked eval hook + runtime-adapter soft-link, the new Work
Ledger events, the standalone V4.2 API, and the MOCK/LOCAL-only safety boundary.

ARIA chooses a model route BY POLICY without depending on one provider. Every route is a
DECISION — nothing here calls a model, provider, network, SDK, subprocess, or credential;
``RouteDecision.executed`` is structurally always ``False``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from aria.ledger import ActorType, LedgerEventType, LedgerReader
from aria.ledger.events import LedgerEvent
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import PathConfinementError, aria_data_dir
from aria.model_routing import (
    ModelCapabilityProfile,
    ModelCategory,
    ModelCostLatencyProfile,
    ModelProvider,
    ModelRiskProfile,
    ModelRoutingService,
    ModelRoutingStore,
    PersistedRouteDecision,
    ProviderAlreadyExists,
    ProviderStatus,
    RouteRequest,
    RouteStatus,
    RoutingIntegrityError,
    RoutingSecurityError,
    SovereigntyPolicy,
    TrustBoundary,
)
from aria.model_routing.audit import build_route_event

# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v42_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    mode = "offline_mock"
    store = ModelRoutingStore(writer=writer, execution_mode=mode)
    svc = ModelRoutingService(store, execution_mode=mode, actor="human:test")
    return {"store": store, "svc": svc, "writer": writer}


def _now() -> datetime:
    return datetime.now(UTC)


def _provider(provider_id: str, model_id: str, category: ModelCategory,
              status: str = "declared") -> ModelProvider:
    return ModelProvider(provider_id=provider_id, vendor="mock", model_id=model_id,
                         category=category, status=status)


def _seed(env):
    env["svc"].register_default_providers()


# ── Registry ──────────────────────────────────────────────────────────────────


class TestRegistry:
    def test_register_and_list_providers(self, env):
        env["svc"].register_provider(_provider("p1", "m1", ModelCategory.open_cloud_model))
        got = env["svc"].list_providers()
        assert [p.provider_id for p in got] == ["p1"]
        assert env["svc"].get_provider("p1").model_id == "m1"

    def test_duplicate_provider_rejected(self, env):
        env["svc"].register_provider(_provider("p1", "m1", ModelCategory.open_cloud_model))
        with pytest.raises(ProviderAlreadyExists):
            env["svc"].register_provider(_provider("p1", "m2", ModelCategory.open_cloud_model))

    def test_credential_shaped_provider_rejected(self, env):
        bad = _provider("sk-ant-api03-DEADBEEFDEADBEEFDEADBEEF", "m1", ModelCategory.open_cloud_model)
        with pytest.raises(RoutingSecurityError):
            env["svc"].register_provider(bad)

    def test_default_mock_providers_registered(self, env):
        created = env["svc"].register_default_providers()
        assert len(created) == 8
        cats = {p.category for p in env["svc"].list_providers()}
        assert ModelCategory.frontier_cloud_model in cats
        assert ModelCategory.local_open_model in cats


# ── Profiles + policies ─────────────────────────────────────────────────────────


class TestProfilesPolicies:
    def test_capability_profile_persists(self, env):
        env["store"].register_capability_profile(ModelCapabilityProfile(
            model_id="m1", categories=[ModelCategory.coding_model], context_window=32000))
        got = env["store"].get_capability_profile("m1")
        assert got.context_window == 32000 and got.categories == [ModelCategory.coding_model]

    def test_cost_profile_persists(self, env):
        env["store"].register_cost_profile(ModelCostLatencyProfile(
            model_id="m1", cost_per_1k_input=0.002, cost_per_1k_output=0.004, typical_latency_ms=250))
        got = env["store"].get_cost_profile("m1")
        assert got.cost_per_1k_input == 0.002 and got.typical_latency_ms == 250

    def test_risk_profile_persists(self, env):
        env["store"].register_risk_profile(ModelRiskProfile(model_id="m1", data_egress_risk="high"))
        assert env["store"].get_risk_profile("m1").data_egress_risk == "high"

    def test_fallback_policy_persists(self, env):
        _seed(env)
        policies = env["store"].get_fallback_policies()
        assert ModelCategory.local_open_model in policies[ModelCategory.frontier_cloud_model]

    def test_sovereignty_policy_persists(self, env):
        _seed(env)
        pol = env["store"].get_sovereignty_policy("private_only")
        assert pol.boundary is TrustBoundary.private_only and pol.forbid_data_egress is True

    @pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
    def test_invalid_cost_profiles_rejected(self, env, value):
        with pytest.raises(RoutingIntegrityError, match="finite and non-negative"):
            env["store"].register_cost_profile(ModelCostLatencyProfile(
                model_id="m1", cost_per_1k_input=value))

    def test_negative_latency_profile_rejected(self, env):
        with pytest.raises(RoutingIntegrityError, match="latency"):
            env["store"].register_cost_profile(ModelCostLatencyProfile(
                model_id="m1", typical_latency_ms=-1))

    def test_invalid_risk_level_rejected(self, env):
        with pytest.raises(RoutingIntegrityError, match="risk levels"):
            env["store"].register_risk_profile(ModelRiskProfile(
                model_id="m1", data_egress_risk="unknown"))

    def test_non_positive_context_window_rejected(self, env):
        with pytest.raises(RoutingIntegrityError, match="context_window"):
            env["store"].register_capability_profile(ModelCapabilityProfile(
                model_id="m1", context_window=0))


# ── Routing ─────────────────────────────────────────────────────────────────────


class TestRouting:
    @pytest.mark.parametrize("intent,category", [
        ("high_risk_planning", ModelCategory.frontier_cloud_model),
        ("hard_reasoning", ModelCategory.reasoning_model),
        ("coding", ModelCategory.coding_model),
        ("summarization", ModelCategory.open_cloud_model),
        ("embedding", ModelCategory.embedding_model),
        ("retrieval", ModelCategory.embedding_model),
        ("rerank", ModelCategory.reranker_model),
        ("private", ModelCategory.local_open_model),
        ("offline", ModelCategory.local_open_model),
    ])
    def test_routing_examples_map_correctly(self, env, intent, category):
        _seed(env)
        d = env["svc"].route(intent=intent, source_refs=["doc:x"])
        assert d.chosen_category is category
        assert d.allowed is True and d.executed is False

    def test_cheapest_eligible_selected(self, env):
        env["svc"].register_provider(_provider("cheap", "m-cheap", ModelCategory.coding_model))
        env["svc"].register_provider(_provider("pricey", "m-pricey", ModelCategory.coding_model))
        env["store"].register_cost_profile(ModelCostLatencyProfile(
            model_id="m-cheap", cost_per_1k_input=0.001, cost_per_1k_output=0.001))
        env["store"].register_cost_profile(ModelCostLatencyProfile(
            model_id="m-pricey", cost_per_1k_input=0.05, cost_per_1k_output=0.05))
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        assert d.chosen_provider_id == "cheap" and d.chosen_model_id == "m-cheap"

    def test_latency_tiebreak_deterministic(self, env):
        env["svc"].register_provider(_provider("slow", "m-slow", ModelCategory.coding_model))
        env["svc"].register_provider(_provider("fast", "m-fast", ModelCategory.coding_model))
        for mid, lat in (("m-slow", 900), ("m-fast", 100)):
            env["store"].register_cost_profile(ModelCostLatencyProfile(
                model_id=mid, cost_per_1k_input=0.001, cost_per_1k_output=0.001,
                typical_latency_ms=lat))
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        assert d.chosen_provider_id == "fast"

    def test_disabled_or_outage_provider_excluded(self, env):
        env["svc"].register_provider(_provider("out", "m-out", ModelCategory.coding_model))
        env["svc"].register_provider(_provider("ok", "m-ok", ModelCategory.coding_model))
        for mid in ("m-out", "m-ok"):
            env["store"].register_cost_profile(ModelCostLatencyProfile(
                model_id=mid, cost_per_1k_input=0.001, cost_per_1k_output=0.001))
        env["svc"].set_provider_status("out", ProviderStatus.outage)
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        assert d.chosen_provider_id == "ok"

    def test_export_restricted_provider_excluded(self, env):
        env["svc"].register_provider(_provider("restricted", "m-r", ModelCategory.coding_model))
        env["svc"].register_provider(_provider("ok", "m-ok", ModelCategory.coding_model))
        for mid in ("m-r", "m-ok"):
            env["store"].register_cost_profile(ModelCostLatencyProfile(
                model_id=mid, cost_per_1k_input=0.001, cost_per_1k_output=0.001))
        env["svc"].set_provider_status("restricted", ProviderStatus.export_restricted)
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        assert d.chosen_provider_id == "ok"

    def test_high_egress_excluded_under_no_egress(self, env):
        # Two embedding providers; the high-egress one is excluded when egress is forbidden.
        env["svc"].register_provider(_provider("leaky", "m-leaky", ModelCategory.embedding_model))
        env["svc"].register_provider(_provider("safe", "m-safe", ModelCategory.embedding_model))
        for mid in ("m-leaky", "m-safe"):
            env["store"].register_cost_profile(ModelCostLatencyProfile(
                model_id=mid, cost_per_1k_input=0.0001, cost_per_1k_output=0.0))
        env["store"].register_risk_profile(ModelRiskProfile(model_id="m-leaky", data_egress_risk="high"))
        env["store"].register_risk_profile(ModelRiskProfile(model_id="m-safe", data_egress_risk="low"))
        env["store"].register_sovereignty_policy(SovereigntyPolicy(
            name="no_egress", boundary=TrustBoundary.private_only, forbid_data_egress=True))
        d = env["svc"].route(intent="embedding", sovereignty_name="no_egress", source_refs=["doc:x"])
        assert d.chosen_provider_id == "safe"

    def test_fallback_chain_applied(self, env):
        # No frontier provider exists, but open_cloud (first fallback) does.
        env["svc"].register_provider(_provider("openp", "m-open", ModelCategory.open_cloud_model))
        env["store"].register_cost_profile(ModelCostLatencyProfile(
            model_id="m-open", cost_per_1k_input=0.001, cost_per_1k_output=0.001))
        from aria.runtime_adapters.model_router import DEFAULT_FALLBACK_POLICIES, FallbackPolicy
        for cat, chain in DEFAULT_FALLBACK_POLICIES.items():
            env["store"].register_fallback_policy(FallbackPolicy(category=cat, ordered_fallback=chain))
        d = env["svc"].route(intent="high_risk_planning", source_refs=["doc:x"])
        assert d.fallback_used is True
        assert d.chosen_category is ModelCategory.open_cloud_model

    def test_exhausted_fallback_blocks(self, env):
        # No providers at all → nothing eligible → blocked (still executed=False).
        from aria.runtime_adapters.model_router import DEFAULT_FALLBACK_POLICIES, FallbackPolicy
        for cat, chain in DEFAULT_FALLBACK_POLICIES.items():
            env["store"].register_fallback_policy(FallbackPolicy(category=cat, ordered_fallback=chain))
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        assert d.allowed is False and d.chosen_model_id is None and d.executed is False
        assert d.blocked_reasons


# ── Store authority (the hardened second boundary) ──────────────────────────────


class TestStoreAuthority:
    def _persisted_request(self, env, *, intent="coding", sovereignty="default",
                           adapter_request_id=None, source_refs=("doc:x",)) -> RouteRequest:
        return env["svc"].create_route_request(
            intent=intent, sovereignty_name=sovereignty, adapter_request_id=adapter_request_id,
            source_refs=list(source_refs))

    def _decision(self, req, **over):
        base = dict(
            decision_id="rtd-forge", route_request_id=req.request_id,
            correlation_id=req.adapter_request_id or req.request_id,
            adapter_request_id=req.adapter_request_id, intent=req.intent, task_type=req.task_type,
            chosen_category=ModelCategory.coding_model, chosen_model_id=None, chosen_provider_id=None,
            allowed=False, source_refs=list(req.source_refs), created_at=_now(),
        )
        base.update(over)
        return PersistedRouteDecision(**base)

    def test_model_forbids_executed_true(self):
        with pytest.raises(ValidationError):
            PersistedRouteDecision(decision_id="d", route_request_id="r", correlation_id="r",
                                   intent="coding", chosen_category=ModelCategory.coding_model,
                                   created_at=_now(), executed=True)

    def test_store_rejects_executed_true_via_construct(self, env):
        req = self._persisted_request(env)
        forged = PersistedRouteDecision.model_construct(
            decision_id="d", route_request_id=req.request_id, correlation_id=req.request_id,
            adapter_request_id=None, intent=req.intent, task_type=req.task_type,
            chosen_category=ModelCategory.coding_model, chosen_model_id=None, chosen_provider_id=None,
            providers_considered=[], fallback_chain=[], sovereignty_boundary=TrustBoundary.any_cloud,
            sovereignty_applied=False, fallback_used=False, cost_estimate=None, risk_summary="",
            allowed=False, blocked_reasons=[], note="", executed=True, source_refs=["doc:x"],
            evidence_refs=[], created_at=_now())
        with pytest.raises(RoutingIntegrityError):
            env["store"].record_route_decision(forged)

    def test_rejects_unknown_request(self, env):
        d = PersistedRouteDecision(decision_id="d", route_request_id="rtr-nope",
                                   correlation_id="rtr-nope", intent="coding",
                                   chosen_category=ModelCategory.coding_model, allowed=False,
                                   created_at=_now())
        with pytest.raises(RoutingIntegrityError):
            env["store"].record_route_decision(d)

    def test_rejects_mismatched_request(self, env):
        req = self._persisted_request(env, intent="coding")
        d = self._decision(req, intent="summarization")  # intent differs from the request
        with pytest.raises(RoutingIntegrityError):
            env["store"].record_route_decision(d)

    def test_rejects_request_created_in_non_requested_status(self, env):
        forged = RouteRequest(
            request_id="rtr-forged-status", intent="coding", source_refs=["doc:x"],
            status=RouteStatus.decided, created_at=_now(),
        )
        with pytest.raises(RoutingIntegrityError, match="must start in requested"):
            env["store"].create_route_request(forged)

    def test_rejects_unknown_named_sovereignty_policy(self, env):
        forged = RouteRequest(
            request_id="rtr-unknown-policy", intent="coding", source_refs=["doc:x"],
            sovereignty_name="misspelled_private_policy", created_at=_now(),
        )
        with pytest.raises(RoutingIntegrityError, match="unknown sovereignty policy"):
            env["store"].create_route_request(forged)

    def test_rejects_decision_with_borrowed_provenance(self, env):
        req = self._persisted_request(env, source_refs=())
        env["svc"].register_provider(_provider("cp", "m-cp", ModelCategory.coding_model))
        d = self._decision(
            req, allowed=True, chosen_model_id="m-cp", chosen_provider_id="cp",
            source_refs=["doc:borrowed"],
        )
        with pytest.raises(RoutingIntegrityError, match="provenance"):
            env["store"].record_route_decision(d)

    def test_rejects_second_decision_for_same_request(self, env):
        _seed(env)
        req = self._persisted_request(env)
        env["svc"].decide(req.request_id)
        with pytest.raises(RoutingIntegrityError, match="already decided"):
            env["svc"].decide(req.request_id)

    def test_store_rejects_non_policy_provider_choice(self, env):
        env["svc"].register_provider(_provider("cheap", "m-cheap", ModelCategory.coding_model))
        env["svc"].register_provider(_provider("pricey", "m-pricey", ModelCategory.coding_model))
        env["store"].register_cost_profile(ModelCostLatencyProfile(
            model_id="m-cheap", cost_per_1k_input=0.001, cost_per_1k_output=0.001))
        env["store"].register_cost_profile(ModelCostLatencyProfile(
            model_id="m-pricey", cost_per_1k_input=0.05, cost_per_1k_output=0.05))
        req = self._persisted_request(env)
        d = self._decision(
            req, allowed=True, chosen_model_id="m-pricey", chosen_provider_id="pricey",
            providers_considered=["cheap", "pricey"], cost_estimate=0.1,
        )
        with pytest.raises(RoutingIntegrityError, match="governed routing policy"):
            env["store"].record_route_decision(d)

    def test_store_rejects_forged_routing_metadata(self, env):
        env["svc"].register_provider(_provider("cp", "m-cp", ModelCategory.coding_model))
        req = self._persisted_request(env)
        d = self._decision(
            req, allowed=True, chosen_model_id="m-cp", chosen_provider_id="cp",
            providers_considered=["cp"], risk_summary="fabricated-safe",
            note="fabricated policy explanation",
        )
        with pytest.raises(RoutingIntegrityError, match="governed routing policy"):
            env["store"].record_route_decision(d)

    def test_rejects_provider_not_in_registry(self, env):
        req = self._persisted_request(env)
        d = self._decision(req, allowed=True, chosen_model_id="ghost",
                           chosen_provider_id="ghost-provider")
        with pytest.raises(RoutingIntegrityError):
            env["store"].record_route_decision(d)

    def test_rejects_disabled_chosen_provider(self, env):
        env["svc"].register_provider(_provider("dp", "m-dp", ModelCategory.coding_model))
        env["svc"].set_provider_status("dp", ProviderStatus.outage)
        req = self._persisted_request(env)
        d = self._decision(req, allowed=True, chosen_model_id="m-dp", chosen_provider_id="dp")
        with pytest.raises(RoutingSecurityError):
            env["store"].record_route_decision(d)

    def test_rejects_cloud_under_no_egress(self, env):
        env["svc"].register_provider(_provider("fp", "m-frontier", ModelCategory.frontier_cloud_model))
        env["store"].register_sovereignty_policy(SovereigntyPolicy(
            name="lockdown", boundary=TrustBoundary.local_only, forbid_data_egress=True))
        req = self._persisted_request(env, sovereignty="lockdown")
        d = self._decision(req, allowed=True, chosen_category=ModelCategory.frontier_cloud_model,
                           chosen_model_id="m-frontier", chosen_provider_id="fp",
                           sovereignty_boundary=TrustBoundary.local_only)
        with pytest.raises(RoutingSecurityError):
            env["store"].record_route_decision(d)

    def test_rejects_unsafe_refs(self, env):
        with pytest.raises(RoutingSecurityError):
            env["svc"].create_route_request(intent="coding",
                                            source_refs=["https://real.example/run/123"])

    def test_rejects_forged_credential_shaped_note_without_persistence(self, env):
        # Decision explanations are policy-derived. A caller cannot replace one with arbitrary
        # text, secret-bearing or otherwise, and no rejected value reaches SQLite.
        req = self._persisted_request(env)
        env["svc"].register_provider(_provider("cp", "m-cp", ModelCategory.coding_model))
        d = self._decision(req, allowed=True, chosen_model_id="m-cp", chosen_provider_id="cp",
                           note="use token sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA")
        with pytest.raises(RoutingIntegrityError, match="governed routing policy"):
            env["store"].record_route_decision(d)
        raw = Path(env["store"].db_path).read_bytes()
        assert b"sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA" not in raw

    def test_rejects_credential_shaped_provider_id_in_decision(self, env):
        # Structural ids ARE rejected (a secret-shaped id is never valid).
        req = self._persisted_request(env)
        with pytest.raises(RoutingSecurityError):
            env["store"].record_route_decision(self._decision(
                req, allowed=True, chosen_model_id="sk-ant-api03-BBBBBBBBBBBBBBBBBBBBBBBB",
                chosen_provider_id="cp"))

    def test_rejects_blocked_decision_with_chosen_model(self, env):
        req = self._persisted_request(env)
        d = self._decision(req, allowed=False, chosen_model_id="m-x")
        with pytest.raises(RoutingIntegrityError):
            env["store"].record_route_decision(d)

    def test_path_confinement(self, env):
        assert str(env["store"].db_path).startswith(str(aria_data_dir()))
        with pytest.raises(PathConfinementError):
            ModelRoutingStore(db_path=Path("C:/not/confined/store.sqlite")
                              if sys.platform == "win32" else Path("/tmp/not_confined.sqlite"))

    def test_restart_safe_retrieval(self, env, writer):
        _seed(env)
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        env["store"].close()
        reopened = ModelRoutingStore(writer=writer, execution_mode="offline_mock")
        assert reopened.get_route_decision(d.decision_id).chosen_model_id == d.chosen_model_id
        reopened.close()

    def test_no_secrets_in_sqlite(self, env):
        _seed(env)
        secret = "SUPERSECRETVALUE123"
        env["svc"].route(intent=f"summarize api_key={secret}", source_refs=["doc:x"])
        raw = Path(env["store"].db_path).read_bytes()
        assert secret.encode() not in raw


# ── Eval + runtime-adapter compatibility ────────────────────────────────────────


class TestEvalAndAdapterCompat:
    def test_route_decision_emits_eval_record(self, env):
        _seed(env)
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        evals = env["svc"].list_eval_records()
        assert len(evals) == 1
        e = evals[0]
        assert e.input_ref == f"route_request:{d.route_request_id}"
        assert e.output_ref == f"route_decision:{d.decision_id}"
        assert e.model_id == d.chosen_model_id and e.pass_fail.value == "pass"

    @pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf")])
    def test_store_rejects_invalid_evaluation_scores(self, env, score):
        from aria.runtime_adapters.harness import EvaluationRecord
        forged = EvaluationRecord(
            eval_id=f"eval-{str(score)}", input_ref="route_request:r1",
            output_ref="route_decision:d1", score=score, created_at=_now(),
        )
        with pytest.raises(RoutingIntegrityError, match="evaluation score"):
            env["store"].create_eval_record(forged)

    def test_adapter_soft_link_and_correlation(self, env):
        _seed(env)
        d = env["svc"].route(intent="coding", adapter_request_id="rtreq-adapter-1",
                             source_refs=["doc:x"])
        assert d.adapter_request_id == "rtreq-adapter-1"
        assert d.correlation_id == "rtreq-adapter-1"  # correlation == adapter request id
        linked = env["svc"].list_route_decisions(adapter_request_id="rtreq-adapter-1")
        assert [x.decision_id for x in linked] == [d.decision_id]

    def test_correlation_defaults_to_request_id(self, env):
        _seed(env)
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        assert d.correlation_id == d.route_request_id

    def test_no_v41_adapter_tables_in_routing_db(self, env):
        _seed(env)
        env["svc"].route(intent="coding", source_refs=["doc:x"])
        import sqlite3
        conn = sqlite3.connect(str(env["store"].db_path))
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "route_decision" in names and "model_provider" in names
        assert "adapter_definition" not in names and "adapter_receipt" not in names


# ── Ledger ──────────────────────────────────────────────────────────────────────


class TestLedger:
    def test_new_event_types_exist(self):
        for name in ("model_provider_registered", "model_provider_status_changed",
                     "model_route_requested", "model_route_decided", "model_route_blocked",
                     "model_route_fallback_applied"):
            assert hasattr(LedgerEventType, name)

    def test_envelopes_round_trip(self):
        adapter = TypeAdapter(LedgerEvent)
        for et in (LedgerEventType.model_provider_registered,
                   LedgerEventType.model_provider_status_changed,
                   LedgerEventType.model_route_requested, LedgerEventType.model_route_decided,
                   LedgerEventType.model_route_blocked,
                   LedgerEventType.model_route_fallback_applied):
            evt = build_route_event(et, task_id="t1", actor="human:test",
                                    actor_type=ActorType.aria, request_id="t1",
                                    provider_id="p1", model_id="m1", category="coding_model")
            reparsed = adapter.validate_python(json.loads(evt.model_dump_json()))
            assert reparsed.event_type is et

    def test_events_written_and_read_back(self, env, writer):
        _seed(env)
        env["svc"].route(intent="coding", source_refs=["doc:x"])
        events = LedgerReader(v2_path=writer.path).read_all()
        types = {getattr(e, "event_type", None) for e in events}
        assert LedgerEventType.model_route_decided in types
        assert LedgerEventType.model_provider_registered in types

    def test_legacy_compatibility_preserved(self, env, writer, tmp_path):
        # A pre-v2 legacy task line still reads alongside the new v4.2 events.
        legacy = tmp_path / "work_ledger.jsonl"
        legacy.write_text(json.dumps({"task_id": "legacy-1", "task_type": "kpi",
                                      "timestamp": "2026-01-01T00:00:00+00:00"}) + "\n",
                          encoding="utf-8")
        _seed(env)
        env["svc"].route(intent="coding", source_refs=["doc:x"])
        reader = LedgerReader(v2_path=writer.path, legacy_task_path=legacy)
        task_ids = {getattr(e, "task_id", None) for e in reader.read_all()}
        assert "legacy-1" in task_ids


# ── API ─────────────────────────────────────────────────────────────────────────


class TestApi:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from aria.api.v4_routing import build_v4_routing_app
        return TestClient(build_v4_routing_app())

    def test_register_and_list_providers(self, client):
        r = client.post("/api/v4/model-routing/providers",
                        json={"provider_id": "p1", "model_id": "m1", "category": "coding_model"})
        assert r.status_code == 201
        r2 = client.get("/api/v4/model-routing/providers")
        assert r2.status_code == 200 and r2.json()["count"] >= 1

    def test_create_and_decide_route(self, client):
        client.post("/api/v4/model-routing/providers",
                    json={"provider_id": "cp", "model_id": "m-cp", "category": "coding_model"})
        rr = client.post("/api/v4/model-routing/route-requests",
                         json={"intent": "coding", "source_refs": ["doc:x"]})
        assert rr.status_code == 201
        rid = rr.json()["request_id"]
        dec = client.post(f"/api/v4/model-routing/route-requests/{rid}/decide")
        assert dec.status_code == 200
        body = dec.json()
        assert body["allowed"] is True and body["executed"] is False
        assert body["chosen_provider_id"] == "cp"

    def test_list_decisions(self, client):
        client.post("/api/v4/model-routing/providers",
                    json={"provider_id": "cp", "model_id": "m-cp", "category": "coding_model"})
        rr = client.post("/api/v4/model-routing/route-requests",
                         json={"intent": "coding", "source_refs": ["doc:x"]})
        rid = rr.json()["request_id"]
        client.post(f"/api/v4/model-routing/route-requests/{rid}/decide")
        lst = client.get("/api/v4/model-routing/route-decisions")
        assert lst.status_code == 200 and lst.json()["count"] >= 1

    def test_safe_error_for_unknown_request(self, client):
        r = client.post("/api/v4/model-routing/route-requests/rtr-nope/decide")
        assert r.status_code == 404 and r.json()["error_code"] == "request_not_found"

    def test_unknown_sovereignty_policy_is_safe_client_error(self, client):
        r = client.post(
            "/api/v4/model-routing/route-requests",
            json={"intent": "coding", "sovereignty_name": "missing-policy",
                  "source_refs": ["doc:x"]},
        )
        assert r.status_code == 400
        assert r.json()["error_code"] == "invalid_route_request"

    def test_second_decision_is_safe_conflict(self, client):
        client.post("/api/v4/model-routing/providers",
                    json={"provider_id": "cp2", "model_id": "m-cp2",
                          "category": "coding_model"})
        rr = client.post("/api/v4/model-routing/route-requests",
                         json={"intent": "coding", "source_refs": ["doc:x"]})
        rid = rr.json()["request_id"]
        assert client.post(f"/api/v4/model-routing/route-requests/{rid}/decide").status_code == 200
        again = client.post(f"/api/v4/model-routing/route-requests/{rid}/decide")
        assert again.status_code == 409
        assert again.json()["error_code"] == "route_not_decidable"

    def test_no_execute_live_or_credential_endpoint(self):
        from aria.api.v4_routing import build_v4_routing_app
        paths = {r.path for r in build_v4_routing_app().routes}
        for banned in ("execute", "live", "credential", "invoke", "run"):
            assert not any(banned in p for p in paths), f"unexpected '{banned}' endpoint"


# ── Safety boundary ─────────────────────────────────────────────────────────────


class TestSafety:
    def test_all_decisions_executed_false(self, env):
        _seed(env)
        for intent in ("coding", "high_risk_planning", "private", "embedding", "unknown_intent"):
            d = env["svc"].route(intent=intent, source_refs=["doc:x"])
            assert d.executed is False

    def test_no_api_key_needed(self, env, monkeypatch):
        for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "GITHUB_TOKEN",
                  "SLACK_TOKEN"):
            monkeypatch.delenv(k, raising=False)
        _seed(env)
        d = env["svc"].route(intent="coding", source_refs=["doc:x"])
        assert d.allowed is True and d.chosen_model_id is not None

    def test_no_sdk_or_network_imports(self):
        pkg = Path(__file__).resolve().parents[1] / "aria" / "model_routing"
        banned = ("import requests", "import httpx", "import aiohttp", "import socket",
                  "import openai", "import anthropic", "import docker", "import smtplib",
                  "from smtplib", "import subprocess", "subprocess.", "urllib.request",
                  "load_dotenv", "os.getenv(\"OPENAI", "boto3")
        for py in pkg.glob("*.py"):
            text = py.read_text(encoding="utf-8")
            for token in banned:
                assert token not in text, f"{py.name} contains banned token {token!r}"

    def test_package_import_isolation(self):
        code = ("import sys; import aria.model_routing; "
                "mods = set(sys.modules); "
                "assert not any(m.startswith('aria.skills') for m in mods), 'V1 skills leaked'; "
                "assert 'langchain' not in mods and 'langchain_anthropic' not in mods, 'LLM leaked'; "
                "print('ISO_OK')")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert out.returncode == 0 and "ISO_OK" in out.stdout, out.stderr
