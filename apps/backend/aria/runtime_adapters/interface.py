"""
Runtime adapter interface + the ONLY executable adapter (internal_mock) + future stubs.

V4.1 delivers a base :class:`RuntimeAdapter` contract, one executable adapter
(:class:`InternalMockAdapter` — deterministic, offline, no network, no subprocess, no
external write), and :class:`FutureStubAdapter` for every non-internal adapter type
(Claude Managed Agents, launch-your-agent, OpenAI Agents SDK, MCP, REST, Docker, CLI,
custom) which **hard-blocks** all execution.

No adapter here imports an external SDK, makes a network call, spawns a subprocess, or
uses any credential. ``execute_live`` hard-blocks by default for every adapter.
"""
from __future__ import annotations

from datetime import UTC, datetime

from aria.runtime_adapters import receipts
from aria.runtime_adapters.models import (
    AdapterType,
    ExecutionMode,
    RuntimeAdapterDefinition,
    RuntimeAdapterReceipt,
    RuntimeAdapterRequest,
)
from aria.runtime_adapters.policy import AdapterPolicyDecision


class AdapterError(RuntimeError):
    """Base class for adapter failures (safe — class/code only is ever surfaced)."""


class AdapterExecutionBlocked(AdapterError):
    """Execution was attempted on an adapter/mode that is not permitted in V4.1."""


def _now() -> datetime:
    return datetime.now(UTC)


class RuntimeAdapter:
    """Base runtime adapter contract. Subclasses MUST NOT perform any external write,
    network call, subprocess, or credential access."""

    def __init__(self, definition: RuntimeAdapterDefinition) -> None:
        self._definition = definition

    def describe(self) -> RuntimeAdapterDefinition:
        return self._definition

    def validate_request(self, request: RuntimeAdapterRequest) -> list[str]:
        """Adapter-level defence-in-depth validation (policy is authoritative). Returns
        a list of blocked reasons — empty means structurally acceptable."""
        problems: list[str] = []
        if request.adapter_id != self._definition.adapter_id:
            problems.append("request adapter_id does not match this adapter")
        if not request.source_refs:
            problems.append("missing source references")
        if request.task_type not in self._definition.supported_task_types:
            problems.append(f"unsupported task type '{request.task_type}'")
        return problems

    def preview(self, request: RuntimeAdapterRequest,
                decision: AdapterPolicyDecision) -> RuntimeAdapterReceipt:
        summary = (f"PREVIEW: adapter '{self._definition.adapter_id}' "
                   f"({self._definition.adapter_type.value}) for task '{request.task_type}'. "
                   f"risk={decision.risk_level.value}; approval_required={decision.required_approval}; "
                   f"evidence_required={decision.evidence_required}. "
                   + (decision.safe_message if decision.safe_message else "No external execution."))
        return receipts.preview_receipt(request, summary=summary, now=_now())

    def execute_dry_run(self, request: RuntimeAdapterRequest,
                        decision: AdapterPolicyDecision) -> RuntimeAdapterReceipt:
        raise AdapterExecutionBlocked(
            f"adapter '{self._definition.adapter_type.value}' cannot dry-run in V4.1")

    def execute_mock(self, request: RuntimeAdapterRequest,
                     decision: AdapterPolicyDecision) -> RuntimeAdapterReceipt:
        raise AdapterExecutionBlocked(
            f"adapter '{self._definition.adapter_type.value}' cannot mock-run in V4.1")

    def execute_live(self, request: RuntimeAdapterRequest,
                     decision: AdapterPolicyDecision) -> RuntimeAdapterReceipt:
        # Live is disabled in V4.1 for EVERY adapter — hard-block, always.
        raise AdapterExecutionBlocked("live execution is disabled in V4.1; no external run is permitted")


class InternalMockAdapter(RuntimeAdapter):
    """The ONLY executable adapter in V4.1. Deterministic, offline: it summarizes the
    bounded task and returns a receipt. It never calls a network, never uses a
    subprocess, never writes outside ARIA_DATA_DIR, and never mutates an external
    system."""

    def _summary(self, request: RuntimeAdapterRequest, mode: str) -> str:
        keys = sorted(request.input_payload.keys())
        return ("Mock runtime completed bounded task:\n"
                f"- task_type: {request.task_type}\n"
                f"- input summarized (fields: {', '.join(keys) if keys else 'none'})\n"
                f"- mode: {mode}\n"
                "- no external execution performed\n"
                "- receipt created")

    def execute_dry_run(self, request: RuntimeAdapterRequest,
                        decision: AdapterPolicyDecision) -> RuntimeAdapterReceipt:
        return receipts.dry_run_receipt(
            request, summary=self._summary(request, "dry_run"),
            output_payload={"would_execute": request.task_type, "external_write": False}, now=_now())

    def execute_mock(self, request: RuntimeAdapterRequest,
                     decision: AdapterPolicyDecision) -> RuntimeAdapterReceipt:
        return receipts.mock_receipt(
            request, summary=self._summary(request, "mock"),
            output_payload={"executed": request.task_type, "external_write": False,
                            "simulated": True}, now=_now())


class FutureStubAdapter(RuntimeAdapter):
    """A future/stub adapter for a non-internal runtime (Claude Managed Agents,
    launch-your-agent, OpenAI Agents SDK, MCP, REST, Docker, CLI, custom). It exists so
    ARIA can *describe* and *preview* the target — but it HARD-BLOCKS all execution in
    V4.1. It imports no external SDK, makes no network call, and spawns no process."""

    def preview(self, request: RuntimeAdapterRequest,
                decision: AdapterPolicyDecision) -> RuntimeAdapterReceipt:
        summary = (f"PREVIEW (future stub): '{self._definition.adapter_type.value}' is a "
                   "future runtime target and CANNOT execute in V4.1. It is described and "
                   "governed here as a worker/backend; execution is blocked by policy. No "
                   "external SDK, network, subprocess, or credential is involved.")
        return receipts.preview_receipt(request, summary=summary, now=_now())

    def execute_dry_run(self, request, decision):
        raise AdapterExecutionBlocked(
            f"'{self._definition.adapter_type.value}' is a future stub; execution is blocked in V4.1")

    def execute_mock(self, request, decision):
        raise AdapterExecutionBlocked(
            f"'{self._definition.adapter_type.value}' is a future stub; execution is blocked in V4.1")


def get_adapter(definition: RuntimeAdapterDefinition) -> RuntimeAdapter:
    """Return the adapter implementation for a definition. ``internal_mock`` is the only
    executable adapter; every other type is a hard-blocking future stub."""
    if definition.adapter_type is AdapterType.internal_mock:
        return InternalMockAdapter(definition)
    return FutureStubAdapter(definition)
