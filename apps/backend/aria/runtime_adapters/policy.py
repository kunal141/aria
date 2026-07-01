"""
Adapter Policy Gate (V4.1) — DENY-BY-DEFAULT.

Decides whether a runtime-adapter request may proceed and under what constraints. All
governing rules are enforced here, structurally:

  - **live mode is disabled** — never an allowed execution mode;
  - **external/future adapter types are blocked** from execution — only ``internal_mock``
    may run (dry-run / mock);
  - **deny by default** — missing source refs, or missing evidence for execution, blocks;
  - a **disabled** adapter can never run;
  - unsupported task types are rejected; risk is computed;
  - the engine NEVER consults caller identity (``ARIA_USER_ID`` is attribution only).

Stateless and deterministic — no I/O, no network, no credentials.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aria.runtime_adapters.models import (
    EXECUTABLE_MODES,
    AdapterType,
    ExecutionMode,
    RiskLevel,
    RuntimeAdapterDefinition,
    RuntimeAdapterRequest,
)

_RISK_ORDER = {RiskLevel.low: 0, RiskLevel.medium: 1, RiskLevel.high: 2}


def _max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    return a if _RISK_ORDER[a] >= _RISK_ORDER[b] else b


class AdapterPolicyDecision(BaseModel):
    """The governed verdict for an adapter request. ``allowed`` means 'not hard-blocked';
    an allowed request in an executable mode still runs only via internal_mock."""
    model_config = ConfigDict(frozen=True)

    allowed: bool
    risk_level: RiskLevel
    required_approval: bool
    evidence_required: bool
    execution_mode: ExecutionMode
    required_permissions: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    safe_message: str = ""

    def can_execute(self) -> bool:
        return (self.allowed and self.execution_mode in EXECUTABLE_MODES)


class AdapterPolicyGate:
    """Deny-by-default policy evaluation for a request against its adapter definition."""

    def evaluate(self, definition: RuntimeAdapterDefinition | None,
                 request: RuntimeAdapterRequest) -> AdapterPolicyDecision:
        mode = request.execution_mode
        blocked: list[str] = []

        if definition is None:
            return AdapterPolicyDecision(
                allowed=False, risk_level=RiskLevel.high, required_approval=True,
                evidence_required=True, execution_mode=mode,
                blocked_reasons=["unknown adapter"], safe_message="Unknown adapter.")

        risk = _max_risk(definition.risk_level,
                         RiskLevel.high if definition.adapter_type in
                         (AdapterType.docker_agent, AdapterType.cli_agent) else RiskLevel.low)

        # 1) live is never permitted in V4.1.
        if mode is ExecutionMode.live:
            blocked.append("live execution is disabled in V4.1")
        # 2) only internal_mock may execute; every other adapter type is a future stub.
        if not definition.is_executable_type and mode in EXECUTABLE_MODES:
            blocked.append(f"adapter type '{definition.adapter_type.value}' is a future stub "
                           "and cannot execute in V4.1 (preview only)")
        # 3) disabled adapters can never run.
        if not definition.enabled and mode in (*EXECUTABLE_MODES, ExecutionMode.live):
            blocked.append("adapter is disabled")
        # 4) deny-by-default: a request must cite its sources.
        if not request.source_refs:
            blocked.append("missing source references (deny-by-default)")
        # 5) execution requires evidence.
        evidence_required = mode in EXECUTABLE_MODES
        if evidence_required and not request.evidence_refs:
            blocked.append("execution requires evidence references")
        # 6) the task type must be supported by the adapter.
        if request.task_type not in definition.supported_task_types:
            blocked.append(f"task type '{request.task_type}' is not supported by this adapter")
        # 7) the requested mode must be one the adapter declares (preview always allowed).
        if mode is not ExecutionMode.preview and mode not in definition.supported_execution_modes:
            blocked.append(f"execution mode '{mode.value}' is not supported by this adapter")

        allowed = not blocked
        required_approval = (risk is not RiskLevel.low) or (mode in EXECUTABLE_MODES)
        safe = ("Preview permitted." if (allowed and mode is ExecutionMode.preview)
                else "Governed mock/dry-run permitted." if allowed
                else "Blocked by policy (deny-by-default): " + "; ".join(blocked))
        return AdapterPolicyDecision(
            allowed=allowed, risk_level=risk, required_approval=required_approval,
            evidence_required=evidence_required, execution_mode=mode,
            required_permissions=list(definition.required_permissions),
            blocked_reasons=blocked, safe_message=safe[:500])
