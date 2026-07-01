"""
aria.runtime_adapters — V4.1 External Runtime Adapter Foundation.

ARIA governs external runtimes as **replaceable workers/backends** without giving up
control. In V4.1 this is a governed *description + gate + mock* layer: ONLY the
``internal_mock`` adapter executes (preview / dry-run / mock); every other adapter type
(Claude Managed Agents, launch-your-agent, OpenAI Agents SDK, MCP, REST, Docker, CLI,
custom) is a **future stub that hard-blocks execution**. It also carries the Model
Router + Sovereignty *contracts* (decision-only) and the Evaluation Harness *hook*.

No real external runtime, model API, network call, SDK, subprocess, or credential is
ever used. Live execution is disabled. ``ARIA_USER_ID`` is attribution only.

A SEPARATE package — importing it never drags in V1 LLM skills, and importing a V1
skill never loads this layer.
"""
from aria.runtime_adapters.harness import (
    EvaluationHook,
    EvaluationHookError,
    EvaluationRecord,
    EvalOutcome,
)
from aria.runtime_adapters.interface import (
    AdapterError,
    AdapterExecutionBlocked,
    FutureStubAdapter,
    InternalMockAdapter,
    RuntimeAdapter,
    get_adapter,
)
from aria.runtime_adapters.model_router import (
    DEFAULT_MOCK_PROVIDERS,
    FallbackPolicy,
    ModelCapabilityProfile,
    ModelCategory,
    ModelCostLatencyProfile,
    ModelProvider,
    ModelRiskProfile,
    MockModelRouter,
    RouteDecision,
    SovereigntyPolicy,
    TrustBoundary,
)
from aria.runtime_adapters.models import (
    ADAPTER_BOUNDARY,
    EXECUTABLE_ADAPTER_TYPES,
    EXECUTABLE_MODES,
    FUTURE_ADAPTER_TYPES,
    AdapterStatus,
    AdapterType,
    ExecutionMode,
    ReceiptStatus,
    RequestStatus,
    RiskLevel,
    RuntimeAdapterCapability,
    RuntimeAdapterDefinition,
    RuntimeAdapterReceipt,
    RuntimeAdapterRequest,
)
from aria.runtime_adapters.policy import AdapterPolicyDecision, AdapterPolicyGate
from aria.runtime_adapters.service import RuntimeAdapterService
from aria.runtime_adapters.store import (
    AdapterAlreadyExists,
    AdapterExecutionViolation,
    AdapterIntegrityError,
    AdapterNotFound,
    AdapterSecurityError,
    RuntimeAdapterStore,
)

__all__ = [
    # service + store
    "RuntimeAdapterService",
    "RuntimeAdapterStore",
    "AdapterNotFound",
    "AdapterAlreadyExists",
    "AdapterSecurityError",
    "AdapterIntegrityError",
    "AdapterExecutionViolation",
    # models
    "RuntimeAdapterDefinition",
    "RuntimeAdapterCapability",
    "RuntimeAdapterRequest",
    "RuntimeAdapterReceipt",
    "AdapterType",
    "ExecutionMode",
    "AdapterStatus",
    "RequestStatus",
    "ReceiptStatus",
    "RiskLevel",
    "EXECUTABLE_ADAPTER_TYPES",
    "FUTURE_ADAPTER_TYPES",
    "EXECUTABLE_MODES",
    "ADAPTER_BOUNDARY",
    # interface + adapters
    "RuntimeAdapter",
    "InternalMockAdapter",
    "FutureStubAdapter",
    "get_adapter",
    "AdapterError",
    "AdapterExecutionBlocked",
    # policy
    "AdapterPolicyGate",
    "AdapterPolicyDecision",
    # model router
    "MockModelRouter",
    "RouteDecision",
    "ModelCategory",
    "ModelProvider",
    "ModelCapabilityProfile",
    "ModelCostLatencyProfile",
    "ModelRiskProfile",
    "FallbackPolicy",
    "SovereigntyPolicy",
    "TrustBoundary",
    "DEFAULT_MOCK_PROVIDERS",
    # evaluation hook
    "EvaluationHook",
    "EvaluationRecord",
    "EvalOutcome",
    "EvaluationHookError",
]
