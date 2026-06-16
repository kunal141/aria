"""
aria.llm — V2 local-intelligence foundation (Week 31).

Public surface for the Week 31 local-intelligence foundation:

  - Execution Mode Contract       (``execution_mode``)
  - Ollama readiness boundary +   (``readiness``)
    model availability check
  - Active-LLM per mode /          (``active_llm``)
    structural no-cloud-fallback
  - Model-fitness gate             (``fitness``)
  - Frozen eval-only schemas       (``eval_schemas``)
  - Model telemetry events         (``telemetry``)

Import-safety: importing this package (and any submodule) has NO side effects and
contacts neither Ollama nor any cloud provider. All daemon probing and provider
construction happen only inside explicitly-called functions.
"""
from aria.llm.active_llm import build_active_llm, resolve_provider_for_mode
from aria.llm.eval_schemas import MinimalMemoryExtraction, MinimalRoutingDecision
from aria.llm.execution_mode import (
    DEFAULT_MODE,
    ExecutionMode,
    InvalidExecutionModeError,
    coerce_execution_mode,
    mode_allows_cloud,
    mode_requires_ollama,
    mode_uses_mock,
    resolve_execution_mode,
)
from aria.llm.fitness import FitnessCheck, FitnessReport, run_fitness_gate
from aria.llm.readiness import (
    DEFAULT_LOCAL_MODEL,
    DEFAULT_OLLAMA_HOST,
    LocalModelUnavailableError,
    OllamaUnavailableError,
    ReadinessReport,
    check_ollama_daemon,
    configured_local_model,
    configured_ollama_host,
    ensure_local_model_available,
)
from aria.llm.telemetry import build_model_telemetry_event, record_model_telemetry

__all__ = [
    # execution mode
    "ExecutionMode",
    "DEFAULT_MODE",
    "InvalidExecutionModeError",
    "resolve_execution_mode",
    "coerce_execution_mode",
    "mode_uses_mock",
    "mode_requires_ollama",
    "mode_allows_cloud",
    # readiness
    "ReadinessReport",
    "OllamaUnavailableError",
    "LocalModelUnavailableError",
    "ensure_local_model_available",
    "check_ollama_daemon",
    "configured_local_model",
    "configured_ollama_host",
    "DEFAULT_LOCAL_MODEL",
    "DEFAULT_OLLAMA_HOST",
    # active llm
    "build_active_llm",
    "resolve_provider_for_mode",
    # fitness
    "run_fitness_gate",
    "FitnessReport",
    "FitnessCheck",
    # eval schemas
    "MinimalRoutingDecision",
    "MinimalMemoryExtraction",
    # telemetry
    "build_model_telemetry_event",
    "record_model_telemetry",
]
