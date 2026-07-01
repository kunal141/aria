"""
Typed models for V4.1 — External Runtime Adapter Foundation.

ARIA governs external runtimes as **replaceable workers/backends** without giving up
control. In V4.1 this is a governed *description + gate + mock* layer: ONLY the
``internal_mock`` adapter executes (preview / dry-run / mock); every other adapter type
(Claude Managed Agents, launch-your-agent, OpenAI Agents SDK, MCP, REST, Docker, CLI,
custom) is a **future stub that hard-blocks execution**. No real external runtime,
model API, network call, SDK, or credential is involved.

All models are frozen Pydantic (immutable records), consistent with the platform's
typed-contract rule.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AdapterType(str, Enum):
    internal_mock = "internal_mock"        # the ONLY executable adapter in V4.1
    claude_managed_agent = "claude_managed_agent"
    launch_your_agent = "launch_your_agent"
    openai_agents_sdk = "openai_agents_sdk"
    mcp_server = "mcp_server"
    rest_agent = "rest_agent"
    docker_agent = "docker_agent"
    cli_agent = "cli_agent"
    custom = "custom"


# The only adapter type permitted to execute in V4.1; everything else is future/stub.
EXECUTABLE_ADAPTER_TYPES = frozenset({AdapterType.internal_mock})
FUTURE_ADAPTER_TYPES = frozenset(t for t in AdapterType if t is not AdapterType.internal_mock)


class ExecutionMode(str, Enum):
    preview = "preview"
    dry_run = "dry_run"
    mock = "mock"
    live = "live"                          # DISABLED in V4.1 — always hard-blocked


class AdapterStatus(str, Enum):
    registered = "registered"
    enabled = "enabled"
    disabled = "disabled"
    future_stub = "future_stub"            # non-internal types: cannot execute


class RequestStatus(str, Enum):
    created = "created"
    previewed = "previewed"
    blocked = "blocked"
    dry_run_completed = "dry_run_completed"
    mock_completed = "mock_completed"
    failed = "failed"


class ReceiptStatus(str, Enum):
    previewed = "previewed"
    blocked = "blocked"
    dry_run_completed = "dry_run_completed"
    mock_completed = "mock_completed"
    failed = "failed"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# The only execution modes that may actually run in V4.1 (live is never permitted).
EXECUTABLE_MODES = frozenset({ExecutionMode.dry_run, ExecutionMode.mock})


class RuntimeAdapterDefinition(BaseModel):
    """A governed description of an external runtime worker/backend. A definition is a
    *record*, never a live connection — registering one performs no external call."""
    model_config = ConfigDict(frozen=True)

    adapter_id: str
    name: str
    vendor: str = "internal"
    adapter_type: AdapterType
    description: str = ""
    supported_task_types: list[str] = Field(default_factory=list)
    supported_execution_modes: list[ExecutionMode] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.low
    enabled: bool = True
    status: AdapterStatus = AdapterStatus.registered
    created_at: datetime
    updated_at: datetime

    @property
    def is_executable_type(self) -> bool:
        return self.adapter_type in EXECUTABLE_ADAPTER_TYPES


class RuntimeAdapterCapability(BaseModel):
    """A declared capability of an adapter (typed I/O + permission/risk metadata)."""
    model_config = ConfigDict(frozen=True)

    capability_id: str
    adapter_id: str
    capability_name: str
    task_type: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permission_scope: str = ""
    risk_level: RiskLevel = RiskLevel.low
    requires_approval: bool = True
    evidence_required: bool = True
    status: str = "declared"


class RuntimeAdapterRequest(BaseModel):
    """A bounded request to run a worker through an adapter. A proposal to run — not a
    run. Must cite its sources; external actions never happen in V4.1."""
    model_config = ConfigDict(frozen=True)

    request_id: str
    adapter_id: str
    goal_id: str | None = None
    task_id: str | None = None
    workspace_id: str | None = None
    task_type: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    requested_by: str = "aria"
    execution_mode: ExecutionMode = ExecutionMode.preview
    status: RequestStatus = RequestStatus.created
    created_at: datetime
    updated_at: datetime


class RuntimeAdapterReceipt(BaseModel):
    """A record of an adapter interaction. In V4.1 the result is always previewed,
    blocked, dry-run, mock, or failed — never a real external run. The receipt is the
    artifact."""
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    request_id: str
    adapter_id: str
    execution_mode: ExecutionMode
    status: ReceiptStatus
    output_summary: str = ""
    output_payload: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    external_ref: str | None = None        # mock://… for mock; never a real id
    safe_error: str | None = None          # class/code only — never raw exception text
    created_at: datetime
    ledger_refs: list[str] = Field(default_factory=list)


# Boundary note attached to adapter results.
ADAPTER_BOUNDARY = (
    "External runtimes are workers; models are replaceable engines. ARIA remains the "
    "governance, memory, approval, Work Ledger, evaluation, action gate, and ROI control "
    "plane. In V4.1 only the internal_mock adapter executes (dry-run / mock); all other "
    "adapter types hard-block. No real external runtime, model API, network, SDK, or "
    "credential is used."
)
