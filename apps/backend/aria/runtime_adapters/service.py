"""
Runtime Adapter Service (V4.1) — governed adapter lifecycle.

Ties the V4.1 pieces together: register/enable/disable adapter definitions, create
bounded requests, and run them through the deny-by-default policy gate and the adapter
interface (preview / dry-run / mock). ONLY the internal_mock adapter executes; every
other adapter type hard-blocks. It also exposes the deterministic model router
(decision-only) and emits source-linked evaluation records via the hook.

No real external runtime, model API, network, SDK, subprocess, or credential is ever
used. ``ARIA_USER_ID`` is attribution only.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.runtime_adapters import receipts
from aria.runtime_adapters.harness import EvaluationHook
from aria.runtime_adapters.interface import get_adapter
from aria.runtime_adapters.model_router import MockModelRouter, RouteDecision, SovereigntyPolicy
from aria.runtime_adapters.models import (
    ADAPTER_BOUNDARY,
    AdapterStatus,
    AdapterType,
    ExecutionMode,
    ReceiptStatus,
    RiskLevel,
    RuntimeAdapterDefinition,
    RuntimeAdapterReceipt,
    RuntimeAdapterRequest,
)
from aria.runtime_adapters.policy import AdapterPolicyGate
from aria.runtime_adapters.store import AdapterNotFound, RuntimeAdapterStore

# Default execution modes granted at registration, by whether the type is executable.
_INTERNAL_MODES = [ExecutionMode.preview, ExecutionMode.dry_run, ExecutionMode.mock]
_FUTURE_MODES = [ExecutionMode.preview]

# The future/stub adapter types registered by ``register_default_adapters``.
_FUTURE_TYPES = (
    AdapterType.claude_managed_agent, AdapterType.launch_your_agent, AdapterType.openai_agents_sdk,
    AdapterType.mcp_server, AdapterType.rest_agent, AdapterType.docker_agent, AdapterType.cli_agent,
)
_EVAL_STATUSES = {ReceiptStatus.dry_run_completed, ReceiptStatus.mock_completed, ReceiptStatus.failed}


def _now() -> datetime:
    return datetime.now(UTC)


class RuntimeAdapterService:
    def __init__(self, store: RuntimeAdapterStore, *, workspace_store: Any = None,
                 execution_mode: str | None = None, actor: str = "aria") -> None:
        self._store = store
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor
        self._policy = AdapterPolicyGate()
        self._hook = EvaluationHook()
        self._router = MockModelRouter()

    # ── Registry ──────────────────────────────────────────────────────────────

    def register_adapter(self, *, name: str, adapter_type: str | AdapterType,
                        adapter_id: str | None = None, vendor: str = "internal",
                        description: str = "", supported_task_types: list[str] | None = None,
                        supported_execution_modes: list[ExecutionMode] | None = None,
                        required_permissions: list[str] | None = None,
                        allowed_scopes: list[str] | None = None,
                        risk_level: str | RiskLevel = RiskLevel.low, enabled: bool = True,
                        actor: str | None = None) -> RuntimeAdapterDefinition:
        actor = actor or self._actor
        atype = adapter_type if isinstance(adapter_type, AdapterType) else AdapterType(adapter_type)
        rlvl = risk_level if isinstance(risk_level, RiskLevel) else RiskLevel(risk_level)
        executable = atype is AdapterType.internal_mock
        modes = supported_execution_modes or (list(_INTERNAL_MODES) if executable else list(_FUTURE_MODES))
        status = (AdapterStatus.enabled if executable and enabled
                  else AdapterStatus.disabled if executable
                  else AdapterStatus.future_stub)
        now = _now()
        d = RuntimeAdapterDefinition(
            adapter_id=adapter_id or f"rta-{uuid.uuid4().hex}", name=name, vendor=vendor,
            adapter_type=atype, description=description,
            supported_task_types=list(supported_task_types or ["analysis"]),
            supported_execution_modes=modes, required_permissions=list(required_permissions or []),
            allowed_scopes=list(allowed_scopes or []), risk_level=rlvl, enabled=enabled,
            status=status, created_at=now, updated_at=now,
        )
        created = self._store.register_definition(d, actor=actor)
        self._attach_ws(d.adapter_id, None, [f"runtime_adapter:{created.adapter_id}"],
                        "runtime_adapter_registered", actor=actor)
        return created

    def register_default_adapters(self, *, actor: str | None = None) -> list[RuntimeAdapterDefinition]:
        """Register the one executable internal_mock adapter + the future/stub adapters."""
        actor = actor or self._actor
        out = [self.register_adapter(name="Internal Mock Runtime",
                                    adapter_type=AdapterType.internal_mock,
                                    adapter_id="rta-internal-mock",
                                    supported_task_types=["analysis", "summarization"], actor=actor)]
        for t in _FUTURE_TYPES:
            out.append(self.register_adapter(name=f"{t.value} (future stub)", adapter_type=t,
                                            adapter_id=f"rta-{t.value}",
                                            supported_task_types=["analysis"], enabled=True, actor=actor))
        return out

    def list_adapters(self, *, enabled: bool | None = None,
                     adapter_type: str | None = None) -> list[RuntimeAdapterDefinition]:
        return self._store.list_definitions(enabled=enabled, adapter_type=adapter_type)

    def get_adapter_definition(self, adapter_id: str) -> RuntimeAdapterDefinition | None:
        return self._store.get_definition(adapter_id)

    def enable(self, adapter_id: str, *, actor: str | None = None) -> RuntimeAdapterDefinition:
        return self._store.set_enabled(adapter_id, True, actor=actor or self._actor)

    def disable(self, adapter_id: str, *, actor: str | None = None) -> RuntimeAdapterDefinition:
        return self._store.set_enabled(adapter_id, False, actor=actor or self._actor)

    def list_capabilities(self, adapter_id: str):
        return self._store.list_capabilities(adapter_id)

    # ── Requests + lifecycle ──────────────────────────────────────────────────

    def create_request(self, *, adapter_id: str, task_type: str, goal_id: str | None = None,
                       task_id: str | None = None, workspace_id: str | None = None,
                       input_payload: dict[str, Any] | None = None,
                       source_refs: list[str] | None = None, evidence_refs: list[str] | None = None,
                       requested_by: str | None = None, actor: str | None = None
                       ) -> RuntimeAdapterRequest:
        actor = actor or self._actor
        now = _now()
        req = RuntimeAdapterRequest(
            request_id=f"rtreq-{uuid.uuid4().hex}", adapter_id=adapter_id, goal_id=goal_id,
            task_id=task_id, workspace_id=workspace_id, task_type=task_type,
            input_payload=input_payload or {}, source_refs=list(source_refs or []),
            evidence_refs=list(evidence_refs or []), requested_by=requested_by or actor,
            execution_mode=ExecutionMode.preview, created_at=now, updated_at=now,
        )
        created = self._store.create_request(req, actor=actor)
        self._attach_ws(None, workspace_id, [f"runtime_adapter_request:{created.request_id}"],
                        "runtime_adapter_request_created", actor=actor)
        return created

    def preview(self, request_id: str, *, actor: str | None = None) -> RuntimeAdapterReceipt:
        return self._run(request_id, ExecutionMode.preview, "preview", actor=actor or self._actor)

    def execute_dry_run(self, request_id: str, *, actor: str | None = None) -> RuntimeAdapterReceipt:
        return self._run(request_id, ExecutionMode.dry_run, "execute_dry_run", actor=actor or self._actor)

    def execute_mock(self, request_id: str, *, actor: str | None = None) -> RuntimeAdapterReceipt:
        return self._run(request_id, ExecutionMode.mock, "execute_mock", actor=actor or self._actor)

    def _run(self, request_id: str, mode: ExecutionMode, method: str, *, actor: str
             ) -> RuntimeAdapterReceipt:
        request = self._store.get_request(request_id)
        if request is None:
            raise AdapterNotFound(f"request {request_id!r} not found")
        definition = self._store.get_definition(request.adapter_id)
        eff = request.model_copy(update={"execution_mode": mode})
        decision = self._policy.evaluate(definition, eff)
        now = _now()

        if mode is ExecutionMode.preview:
            if not decision.allowed or definition is None:
                receipt = receipts.blocked_receipt(eff, mode=mode, reasons=decision.blocked_reasons,
                                                  now=now)
            else:
                receipt = get_adapter(definition).preview(eff, decision)
            return self._persist(receipt, request, definition)

        # dry_run / mock: execute only if policy permits an executable mode.
        if definition is None or not decision.can_execute():
            receipt = receipts.blocked_receipt(
                eff, mode=mode, reasons=decision.blocked_reasons or ["not executable"], now=now)
            return self._persist(receipt, request, definition)
        try:
            receipt = getattr(get_adapter(definition), method)(eff, decision)
        except Exception as exc:  # safe failure — class/code only, never raw text
            receipt = receipts.failed_receipt(eff, mode=mode, safe_error=type(exc).__name__, now=now)
        return self._persist(receipt, request, definition)

    def _persist(self, receipt: RuntimeAdapterReceipt, request: RuntimeAdapterRequest,
                definition: RuntimeAdapterDefinition | None, *, actor: str = "aria"
                ) -> RuntimeAdapterReceipt:
        created = self._store.record_receipt(
            receipt, adapter_type=(definition.adapter_type.value if definition else None),
            goal_id=request.goal_id, workspace_id=request.workspace_id, actor=self._actor)
        self._attach_ws(None, request.workspace_id, [f"runtime_adapter_receipt:{created.receipt_id}"],
                        f"runtime_adapter_{created.status.value}", actor=self._actor)
        # Emit a source-linked evaluation record for real run outcomes (hook, no external API).
        if created.status in _EVAL_STATUSES:
            try:
                record = self._hook.evaluate_receipt(created, request)
                self._store.create_eval_record(record)
            except Exception:  # pragma: no cover - eval is best-effort, never fatal
                pass
        return created

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_request(self, request_id: str) -> RuntimeAdapterRequest | None:
        return self._store.get_request(request_id)

    def list_requests(self, *, adapter_id: str | None = None) -> list[RuntimeAdapterRequest]:
        return self._store.list_requests(adapter_id=adapter_id)

    def get_receipt(self, receipt_id: str) -> RuntimeAdapterReceipt | None:
        return self._store.get_receipt(receipt_id)

    def list_receipts(self, *, request_id: str | None = None,
                    adapter_id: str | None = None) -> list[RuntimeAdapterReceipt]:
        return self._store.list_receipts(request_id=request_id, adapter_id=adapter_id)

    def list_eval_records(self, *, adapter_id: str | None = None):
        return self._store.list_eval_records(adapter_id=adapter_id)

    # ── Model router (decision-only; no model call, no keys) ───────────────────

    def route_model(self, *, intent: str, task_type: str | None = None,
                   sovereignty: SovereigntyPolicy | None = None) -> RouteDecision:
        return self._router.route(intent=intent, task_type=task_type, sovereignty=sovereignty)

    @staticmethod
    def boundary_note() -> str:
        return ADAPTER_BOUNDARY

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _attach_ws(self, _adapter_id, ws_id: str | None, refs: list[str], status: str, *, actor: str
                   ) -> None:
        if self._workspace_store is None or not ws_id or not refs:
            return
        try:
            self._workspace_store.update_workspace(
                ws_id, status=status, add_ledger_refs=list(refs), actor=actor)
        except Exception:  # pragma: no cover - workspace bookkeeping is best-effort
            pass
