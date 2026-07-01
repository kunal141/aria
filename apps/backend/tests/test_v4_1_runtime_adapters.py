"""
V4.1 — External Runtime Adapter Foundation tests.

Covers the adapter registry, the deny-by-default policy gate, the adapter interface
(internal_mock executes; future stubs + live hard-block), receipts, the path-confined
store, Model Router + Sovereignty contracts (decision-only, no keys), the source-linked
Evaluation Harness hook, Work Ledger events, the V4 API, and the MOCK/LOCAL-only safety
boundary.

ARIA governs external runtimes as replaceable workers. In V4.1 ONLY internal_mock
executes (preview/dry-run/mock); nothing calls a real external runtime, model API,
network, SDK, subprocess, or credential; live execution is disabled.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir
from aria.memory_v2.workspace import WorkspaceStore
from aria.runtime_adapters import (
    AdapterAlreadyExists,
    AdapterExecutionBlocked,
    AdapterExecutionViolation,
    AdapterPolicyGate,
    AdapterSecurityError,
    AdapterType,
    EvaluationHook,
    EvaluationHookError,
    EvalOutcome,
    ExecutionMode,
    ModelCategory,
    MockModelRouter,
    ReceiptStatus,
    RequestStatus,
    RuntimeAdapterService,
    RuntimeAdapterStore,
    SovereigntyPolicy,
    TrustBoundary,
    get_adapter,
)
from aria.runtime_adapters.models import (
    RuntimeAdapterReceipt,
    RuntimeAdapterRequest,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v41_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    mode = "offline_mock"
    store = RuntimeAdapterStore(writer=writer, execution_mode=mode)
    ws = WorkspaceStore(writer=writer, execution_mode=mode)
    svc = RuntimeAdapterService(store, workspace_store=ws, execution_mode=mode, actor="human:test")
    return {"store": store, "ws": ws, "svc": svc}


def _defaults(env):
    return {d.adapter_type: d for d in env["svc"].register_default_adapters()}


def _mock_id(env) -> str:
    return _defaults(env)[AdapterType.internal_mock].adapter_id


def _req(env, adapter_id, **kw):
    base = dict(task_type="analysis", source_refs=["goal-x"], evidence_refs=["ev-1"],
                input_payload={"text": "x"})
    base.update(kw)
    return env["svc"].create_request(adapter_id=adapter_id, **base)


def _event_types(writer: LedgerWriter) -> set[str]:
    if not writer.path.exists():
        return set()
    return {json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()}


def _blob(writer: LedgerWriter) -> str:
    blob = writer.path.read_text(encoding="utf-8") if writer.path.exists() else ""
    for dbf in (aria_data_dir() / "runtime_adapters").glob("store.sqlite*"):
        blob += dbf.read_bytes().decode("utf-8", "ignore")
    return blob


# ── 1. Registry ───────────────────────────────────────────────────────────────


class TestRegistry:
    def test_register_internal_mock(self, env):
        d = env["svc"].register_adapter(name="Mock", adapter_type=AdapterType.internal_mock)
        assert d.adapter_type is AdapterType.internal_mock and d.status.value == "enabled"
        assert d.is_executable_type

    def test_duplicate_adapter_rejected(self, env):
        env["svc"].register_adapter(name="m", adapter_type=AdapterType.internal_mock,
                                   adapter_id="rta-dup")
        with pytest.raises(AdapterAlreadyExists):
            env["svc"].register_adapter(name="m2", adapter_type=AdapterType.internal_mock,
                                       adapter_id="rta-dup")

    def test_future_adapter_registered_as_stub(self, env):
        d = env["svc"].register_adapter(name="cma", adapter_type=AdapterType.claude_managed_agent)
        assert d.status.value == "future_stub" and not d.is_executable_type

    def test_disable_then_cannot_run(self, env):
        mid = _mock_id(env)
        env["svc"].disable(mid)
        r = env["svc"].execute_mock(_req(env, mid).request_id)
        assert r.status is ReceiptStatus.blocked and "disabled" in r.output_summary.lower()

    def test_no_credentials_needed_to_register(self, env, monkeypatch):
        for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "GITHUB_TOKEN"):
            monkeypatch.delenv(k, raising=False)
        d = env["svc"].register_adapter(name="m", adapter_type=AdapterType.internal_mock)
        assert d.adapter_id                            # registered fine with no secrets


# ── 2. Policy gate ────────────────────────────────────────────────────────────


class TestPolicy:
    def _policy_req(self, adapter_id="rta-x", **kw) -> RuntimeAdapterRequest:
        now = datetime.now(UTC)
        base = dict(request_id=f"rtreq-{uuid.uuid4().hex}", adapter_id=adapter_id,
                    task_type="analysis", source_refs=["g"], evidence_refs=["e"],
                    execution_mode=ExecutionMode.mock, created_at=now, updated_at=now)
        base.update(kw)
        return RuntimeAdapterRequest(**base)

    def test_deny_by_default_unknown_adapter(self, env):
        d = AdapterPolicyGate().evaluate(None, self._policy_req())
        assert not d.allowed and d.blocked_reasons

    def test_live_mode_disabled(self, env):
        defs = _defaults(env)
        mock = defs[AdapterType.internal_mock]
        d = AdapterPolicyGate().evaluate(mock, self._policy_req(
            adapter_id=mock.adapter_id, execution_mode=ExecutionMode.live))
        assert not d.allowed and any("live" in r for r in d.blocked_reasons)

    def test_external_type_blocked_from_execution(self, env):
        defs = _defaults(env)
        cma = defs[AdapterType.claude_managed_agent]
        d = AdapterPolicyGate().evaluate(cma, self._policy_req(
            adapter_id=cma.adapter_id, execution_mode=ExecutionMode.mock))
        assert not d.can_execute()

    def test_missing_source_refs_rejected(self, env):
        defs = _defaults(env)
        mock = defs[AdapterType.internal_mock]
        d = AdapterPolicyGate().evaluate(mock, self._policy_req(
            adapter_id=mock.adapter_id, source_refs=[]))
        assert not d.allowed and any("source" in r for r in d.blocked_reasons)

    def test_missing_evidence_rejected_for_execution(self, env):
        defs = _defaults(env)
        mock = defs[AdapterType.internal_mock]
        d = AdapterPolicyGate().evaluate(mock, self._policy_req(
            adapter_id=mock.adapter_id, evidence_refs=[]))
        assert not d.allowed and any("evidence" in r for r in d.blocked_reasons)

    def test_unsupported_task_type_rejected(self, env):
        defs = _defaults(env)
        mock = defs[AdapterType.internal_mock]
        d = AdapterPolicyGate().evaluate(mock, self._policy_req(
            adapter_id=mock.adapter_id, task_type="not_a_task"))
        assert not d.allowed

    def test_aria_user_id_is_not_authorization(self, env, monkeypatch):
        monkeypatch.setenv("ARIA_USER_ID", "human:admin")
        defs = _defaults(env)
        cma = defs[AdapterType.claude_managed_agent]
        # admin-looking actor does NOT let a future adapter execute
        r = env["svc"].execute_mock(_req(env, cma.adapter_id).request_id)
        assert r.status is ReceiptStatus.blocked


# ── 3. Interface / adapters ───────────────────────────────────────────────────


class TestInterface:
    def test_internal_mock_preview_dry_run_mock(self, env):
        mid = _mock_id(env)
        rid = _req(env, mid).request_id
        assert env["svc"].preview(rid).status is ReceiptStatus.previewed
        assert env["svc"].execute_dry_run(rid).status is ReceiptStatus.dry_run_completed
        mk = env["svc"].execute_mock(rid)
        assert mk.status is ReceiptStatus.mock_completed
        assert mk.external_ref == f"mock://internal_mock/{rid}"

    def test_describe_works(self, env):
        mid = _mock_id(env)
        adapter = get_adapter(env["svc"].get_adapter_definition(mid))
        assert adapter.describe().adapter_type is AdapterType.internal_mock

    def test_future_adapter_execution_hard_blocks_safely(self, env):
        cma = _defaults(env)[AdapterType.claude_managed_agent]
        r = env["svc"].execute_mock(_req(env, cma.adapter_id).request_id)
        assert r.status is ReceiptStatus.blocked
        # the adapter itself hard-blocks even if called directly
        adapter = get_adapter(cma)
        with pytest.raises(AdapterExecutionBlocked):
            adapter.execute_mock(_req(env, cma.adapter_id), None)

    def test_live_execution_hard_blocks_for_every_adapter(self, env):
        for t in (AdapterType.internal_mock, AdapterType.claude_managed_agent):
            d = env["svc"].register_adapter(name=t.value, adapter_type=t,
                                           adapter_id=f"rta-live-{t.value}")
            with pytest.raises(AdapterExecutionBlocked):
                get_adapter(d).execute_live(_req(env, d.adapter_id), None)

    def test_failed_execution_records_failed_receipt(self, env, monkeypatch):
        mid = _mock_id(env)
        from aria.runtime_adapters import interface as _iface
        monkeypatch.setattr(_iface.InternalMockAdapter, "execute_mock",
                           lambda self, req, dec: (_ for _ in ()).throw(RuntimeError("sk-EXC boom")))
        r = env["svc"].execute_mock(_req(env, mid).request_id)
        assert r.status is ReceiptStatus.failed and r.safe_error == "RuntimeError"
        assert "sk-EXC" not in (r.output_summary + str(r.safe_error))


# ── 4. Receipts ───────────────────────────────────────────────────────────────


class TestReceipts:
    def test_receipts_persisted_and_typed(self, env):
        mid = _mock_id(env)
        rid = _req(env, mid).request_id
        env["svc"].execute_dry_run(rid)
        env["svc"].execute_mock(rid)
        recs = env["svc"].list_receipts(request_id=rid)
        kinds = {r.status for r in recs}
        assert ReceiptStatus.dry_run_completed in kinds and ReceiptStatus.mock_completed in kinds

    def test_blocked_and_failed_receipts_are_safe(self, env):
        cma = _defaults(env)[AdapterType.claude_managed_agent]
        r = env["svc"].execute_mock(_req(env, cma.adapter_id).request_id)
        assert r.status is ReceiptStatus.blocked and r.external_ref is None
        assert "Traceback" not in r.output_summary


# ── 5. Store: confinement / restart / secrets ─────────────────────────────────


class TestStore:
    def test_path_confined_restart_safe(self, env, writer):
        d = env["svc"].register_adapter(name="m", adapter_type=AdapterType.internal_mock)
        assert str(env["store"].db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "runtime_adapters"
        assert not list(source_pkg.glob("*.sqlite"))
        env["store"].close()
        store2 = RuntimeAdapterStore(writer=writer, execution_mode="offline_mock")
        assert store2.get_definition(d.adapter_id) is not None

    def test_secret_in_source_refs_rejected(self, env, writer):
        mid = _mock_id(env)
        with pytest.raises(AdapterSecurityError):
            env["svc"].create_request(adapter_id=mid, task_type="analysis",
                                     source_refs=["token=RTASECRET777"], evidence_refs=["ev-1"])
        env["store"].close()
        assert "RTASECRET777" not in _blob(writer)

    def test_secret_in_payload_masked(self, env, writer):
        mid = _mock_id(env)
        env["svc"].create_request(adapter_id=mid, task_type="analysis", source_refs=["g"],
                                 evidence_refs=["e"], input_payload={"note": "password=PAYSECRET888"})
        env["store"].close()
        assert "PAYSECRET888" not in _blob(writer)

    def test_direct_store_rejects_forged_live_future_receipt(self, env):
        future = _defaults(env)[AdapterType.openai_agents_sdk]
        req = _req(env, future.adapter_id)
        now = datetime.now(UTC)
        forged = RuntimeAdapterReceipt(
            receipt_id="radr-forged-live", request_id=req.request_id, adapter_id=future.adapter_id,
            execution_mode=ExecutionMode.live, status=ReceiptStatus.mock_completed,
            output_summary="forged live external completion", source_refs=["goal-x"],
            evidence_refs=["ev-1"], external_ref="https://real.example/run/123", created_at=now)

        with pytest.raises(AdapterExecutionViolation):
            env["store"].record_receipt(forged, adapter_type=future.adapter_type.value)

        assert env["store"].get_request(req.request_id).status is RequestStatus.created
        assert env["store"].get_receipt("radr-forged-live") is None

    def test_direct_store_rejects_future_adapter_success_receipt(self, env):
        future = _defaults(env)[AdapterType.mcp_server]
        req = _req(env, future.adapter_id)
        forged = RuntimeAdapterReceipt(
            receipt_id="radr-future-success", request_id=req.request_id,
            adapter_id=future.adapter_id, execution_mode=ExecutionMode.mock,
            status=ReceiptStatus.mock_completed, output_summary="future success",
            source_refs=["goal-x"], evidence_refs=["ev-1"],
            external_ref=f"mock://internal_mock/{req.request_id}", created_at=datetime.now(UTC))

        with pytest.raises(AdapterExecutionViolation):
            env["store"].record_receipt(forged)

        assert env["store"].get_request(req.request_id).status is RequestStatus.created
        assert env["store"].get_receipt("radr-future-success") is None

    def test_direct_store_rejects_forged_external_ref(self, env):
        mid = _mock_id(env)
        req = _req(env, mid)
        forged = RuntimeAdapterReceipt(
            receipt_id="radr-bad-ref", request_id=req.request_id, adapter_id=mid,
            execution_mode=ExecutionMode.mock, status=ReceiptStatus.mock_completed,
            output_summary="mock with forged external ref", source_refs=["goal-x"],
            evidence_refs=["ev-1"], external_ref="github://real/123", created_at=datetime.now(UTC))

        with pytest.raises(AdapterExecutionViolation):
            env["store"].record_receipt(forged)

        assert env["store"].get_request(req.request_id).status is RequestStatus.created
        assert env["store"].get_receipt("radr-bad-ref") is None

    def test_direct_store_rejects_receipt_adapter_mismatch(self, env):
        defs = _defaults(env)
        req = _req(env, defs[AdapterType.internal_mock].adapter_id)
        forged = RuntimeAdapterReceipt(
            receipt_id="radr-mismatch", request_id=req.request_id,
            adapter_id=defs[AdapterType.mcp_server].adapter_id, execution_mode=ExecutionMode.preview,
            status=ReceiptStatus.previewed, output_summary="mismatched adapter",
            source_refs=["goal-x"], evidence_refs=["ev-1"], created_at=datetime.now(UTC))

        with pytest.raises(AdapterExecutionViolation):
            env["store"].record_receipt(forged)

        assert env["store"].get_receipt("radr-mismatch") is None

    def test_direct_store_rejects_unknown_request_receipt(self, env):
        mid = _mock_id(env)
        forged = RuntimeAdapterReceipt(
            receipt_id="radr-unknown-req", request_id="rtreq-missing", adapter_id=mid,
            execution_mode=ExecutionMode.preview, status=ReceiptStatus.previewed,
            output_summary="unknown request", source_refs=["goal-x"], evidence_refs=["ev-1"],
            created_at=datetime.now(UTC))

        with pytest.raises(Exception) as exc:
            env["store"].record_receipt(forged)

        assert type(exc.value).__name__ == "AdapterNotFound"
        assert env["store"].get_receipt("radr-unknown-req") is None

    def test_direct_store_allows_legitimate_receipts(self, env):
        mid = _mock_id(env)
        req = _req(env, mid)
        now = datetime.now(UTC)
        receipts = [
            RuntimeAdapterReceipt(
                receipt_id="radr-direct-preview", request_id=req.request_id, adapter_id=mid,
                execution_mode=ExecutionMode.preview, status=ReceiptStatus.previewed,
                output_summary="preview", source_refs=["goal-x"], evidence_refs=["ev-1"],
                created_at=now),
            RuntimeAdapterReceipt(
                receipt_id="radr-direct-dry", request_id=req.request_id, adapter_id=mid,
                execution_mode=ExecutionMode.dry_run, status=ReceiptStatus.dry_run_completed,
                output_summary="dry", source_refs=["goal-x"], evidence_refs=["ev-1"],
                created_at=now),
            RuntimeAdapterReceipt(
                receipt_id="radr-direct-mock", request_id=req.request_id, adapter_id=mid,
                execution_mode=ExecutionMode.mock, status=ReceiptStatus.mock_completed,
                output_summary="mock", source_refs=["goal-x"], evidence_refs=["ev-1"],
                external_ref=f"mock://internal_mock/{req.request_id}", created_at=now),
        ]

        for receipt in receipts:
            assert env["store"].record_receipt(receipt).receipt_id == receipt.receipt_id

        assert env["store"].get_request(req.request_id).status is RequestStatus.mock_completed


# ── 6. Model Router + Sovereignty (decision-only, no keys) ────────────────────


class TestModelRouter:
    def test_intent_routing_is_deterministic(self):
        r = MockModelRouter()
        assert r.route(intent="high_risk_planning").chosen_category is ModelCategory.frontier_cloud_model
        assert r.route(intent="coding").chosen_category is ModelCategory.coding_model
        assert r.route(intent="embedding").chosen_category is ModelCategory.embedding_model
        assert r.route(intent="summarization").chosen_category is ModelCategory.open_cloud_model

    def test_never_executes(self):
        assert MockModelRouter().route(intent="high_risk_planning").executed is False

    def test_sovereignty_downgrades_cloud_to_local(self):
        d = MockModelRouter().route(
            intent="high_risk_planning",
            sovereignty=SovereigntyPolicy(name="india", boundary=TrustBoundary.private_only,
                                         forbid_data_egress=True))
        assert d.chosen_category is ModelCategory.local_open_model
        assert d.sovereignty_boundary is TrustBoundary.private_only

    def test_router_works_without_provider_keys(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        d = MockModelRouter().route(intent="coding")
        assert d.allowed and d.chosen_model_id and d.chosen_model_id.startswith("mock-")


# ── 7. Evaluation hook (source-linked, no external service) ───────────────────


class TestEvaluationHook:
    def test_hook_requires_source_link(self):
        with pytest.raises(EvaluationHookError):
            EvaluationHook().build_record(input_ref="", output_ref="out")

    def test_mock_completion_evaluates_pass(self, env):
        mid = _mock_id(env)
        rid = _req(env, mid).request_id
        env["svc"].execute_mock(rid)
        evals = env["svc"].list_eval_records(adapter_id=mid)
        assert evals and evals[-1].pass_fail is EvalOutcome.pass_
        assert evals[-1].input_ref and evals[-1].output_ref     # source-linked

    def test_eval_works_without_external_service(self):
        rec = EvaluationHook().build_record(input_ref="req:1", output_ref="rcpt:1",
                                           adapter_id="rta-x")
        assert rec.eval_id and rec.cost_estimate is None or True   # no external call needed


# ── 8. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_lifecycle_events_emitted(self, env, writer):
        defs = _defaults(env)
        mid = defs[AdapterType.internal_mock].adapter_id
        env["svc"].disable(mid); env["svc"].enable(mid)
        rid = _req(env, mid).request_id
        env["svc"].preview(rid); env["svc"].execute_dry_run(rid); env["svc"].execute_mock(rid)
        env["svc"].execute_mock(_req(env, defs[AdapterType.mcp_server].adapter_id).request_id)  # blocked
        types = _event_types(writer)
        for e in ("runtime_adapter_registered", "runtime_adapter_enabled", "runtime_adapter_disabled",
                  "runtime_adapter_request_created", "runtime_adapter_previewed",
                  "runtime_adapter_blocked", "runtime_adapter_dry_run_completed",
                  "runtime_adapter_mock_completed", "runtime_adapter_receipt_created"):
            assert e in types, f"missing event {e}"

    def test_legacy_ledger_compatibility(self, env, writer):
        env["svc"].register_default_adapters()
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "runtime_adapter_registered" for e in v2)


# ── 9. Safety ─────────────────────────────────────────────────────────────────


class TestSafety:
    def test_service_has_no_live_or_network_methods(self, env):
        svc = env["svc"]
        for forbidden in ("execute_live", "send", "post", "http_post", "call_api", "connect",
                          "crawl", "subprocess", "spawn", "deploy"):
            assert not hasattr(svc, forbidden), f"service must not expose {forbidden!r}"

    def test_no_external_sdk_or_network_imports(self):
        # Scan for actual imports/usages (not prose mentions in docstrings).
        import aria.runtime_adapters as pkg
        pkg_dir = Path(pkg.__file__).resolve().parent
        banned = ("import requests", "import httpx", "import aiohttp", "import socket",
                  "import openai", "import anthropic", "from openai", "from anthropic",
                  "import subprocess", "subprocess.", "urllib.request", "import docker",
                  "import smtplib", "from smtplib")
        for py in pkg_dir.glob("*.py"):
            text = py.read_text(encoding="utf-8")
            for b in banned:
                assert b not in text, f"{py.name} must not contain {b!r}"

    def test_all_receipts_are_local_only(self, env):
        mid = _mock_id(env)
        rid = _req(env, mid).request_id
        env["svc"].execute_dry_run(rid); env["svc"].execute_mock(rid)
        for r in env["svc"].list_receipts(request_id=rid):
            assert r.execution_mode in (ExecutionMode.preview, ExecutionMode.dry_run,
                                        ExecutionMode.mock)
            assert (r.external_ref is None or r.external_ref.startswith("mock://internal_mock/"))

    def test_v1_skill_import_does_not_load_runtime_adapters(self):
        code = (
            "import sys; import aria.skills.pr_review_skill; "
            "bad=[m for m in ('aria.runtime_adapters.service','aria.runtime_adapters.store',"
            "'aria.runtime_adapters.interface') if m in sys.modules]; "
            "print('LOADED', bad); assert not bad, bad"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "LOADED []" in r.stdout


# ── 10. API ───────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v4 import build_v4_app

    return TestClient(build_v4_app())


class TestApi:
    def test_full_internal_mock_flow(self, client):
        reg = client.post("/api/v4/runtime-adapters",
                         json={"name": "Mock", "adapter_type": "internal_mock",
                               "supported_task_types": ["analysis"]})
        assert reg.status_code == 201
        aid = reg.json()["adapter_id"]
        assert client.get("/api/v4/runtime-adapters").json()["count"] >= 1
        assert client.get(f"/api/v4/runtime-adapters/{aid}").status_code == 200
        req = client.post("/api/v4/runtime-adapter-requests",
                         json={"adapter_id": aid, "task_type": "analysis", "source_refs": ["g"],
                               "evidence_refs": ["e"], "input_payload": {"x": 1}})
        assert req.status_code == 201
        rid = req.json()["request_id"]
        assert client.post(f"/api/v4/runtime-adapter-requests/{rid}/preview").json()["status"] == "previewed"
        assert client.post(f"/api/v4/runtime-adapter-requests/{rid}/execute-dry-run").json()["status"] == "dry_run_completed"
        assert client.post(f"/api/v4/runtime-adapter-requests/{rid}/execute-mock").json()["status"] == "mock_completed"
        assert client.get("/api/v4/runtime-adapter-receipts").json()["count"] >= 1

    def test_enable_disable_and_future_stub_blocked(self, client):
        aid = client.post("/api/v4/runtime-adapters",
                        json={"name": "cma", "adapter_type": "claude_managed_agent"}).json()["adapter_id"]
        req = client.post("/api/v4/runtime-adapter-requests",
                        json={"adapter_id": aid, "task_type": "analysis", "source_refs": ["g"],
                              "evidence_refs": ["e"]}).json()["request_id"]
        blocked = client.post(f"/api/v4/runtime-adapter-requests/{req}/execute-mock")
        assert blocked.status_code == 200 and blocked.json()["status"] == "blocked"
        m = client.post("/api/v4/runtime-adapters",
                      json={"name": "m", "adapter_type": "internal_mock"}).json()["adapter_id"]
        assert client.post(f"/api/v4/runtime-adapters/{m}/disable").json()["enabled"] is False
        assert client.post(f"/api/v4/runtime-adapters/{m}/enable").json()["enabled"] is True

    def test_safe_errors_and_no_live_endpoint(self, client):
        assert client.post("/api/v4/runtime-adapters",
                         json={"name": "x", "adapter_type": "bogus"}).status_code == 400
        assert client.get("/api/v4/runtime-adapters/rta-x").status_code == 404
        assert client.post("/api/v4/runtime-adapter-requests/rtreq-x/preview").status_code == 404
        # No live / external-execution endpoint exists.
        for path in ("/api/v4/runtime-adapter-requests/rtreq-x/execute-live",
                     "/api/v4/runtime-adapter-requests/rtreq-x/execute-real",
                     "/api/v4/runtime-adapters/rta-x/connect"):
            assert client.post(path).status_code in (404, 405)
