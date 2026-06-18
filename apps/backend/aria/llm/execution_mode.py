"""
Execution Mode Contract — Week 31 item 1 (V2 plan §6.1).

V2 has exactly three named execution modes, and **no mode is ever auto-selected
as a fallback**:

  - ``offline_mock``  deterministic local mock (V1.1 keyword router + mock skill
                      outputs). No Ollama required. No cloud. Selected ONLY
                      explicitly or by the test harness — never because Ollama
                      happens to be down.
  - ``local_ollama``  localhost Ollama only. No cloud provider, ever. If Ollama
                      or the model is unavailable it must FAIL LOUDLY
                      (``aria.llm.readiness``), never downgrade to mock or cloud.
  - ``cloud_opt_in``  explicit paid/cloud mode. Reached ONLY when this mode is
                      explicitly selected. The mere presence of cloud
                      credentials must never trigger cloud usage.

Resolution (``resolve_execution_mode``) is explicit-first and has a SAFE default:
an explicit argument wins, else ``ARIA_EXECUTION_MODE`` env, else ``offline_mock``.
The safe default guarantees that an *unset* environment never selects Ollama or
cloud — those are always a deliberate choice. (The Week 32 interactive chat
surface will pass ``local_ollama`` explicitly; this module never picks it for
you.)

This module is import-safe: it has NO import-time side effects and never contacts
Ollama or any cloud provider. Provider construction lives in
``aria.llm.active_llm``; readiness probing lives in ``aria.llm.readiness``.
"""
from __future__ import annotations

import os
from enum import Enum

_ENV_VAR = "ARIA_EXECUTION_MODE"


class ExecutionMode(str, Enum):
    offline_mock = "offline_mock"
    local_ollama = "local_ollama"
    cloud_opt_in = "cloud_opt_in"


# The library default when nothing is specified. Deliberately the only mode that
# needs neither Ollama nor a cloud key, so an unset env can never escalate.
DEFAULT_MODE = ExecutionMode.offline_mock


class InvalidExecutionModeError(ValueError):
    """An execution mode string did not match one of the three named modes.

    Raised loudly rather than silently falling back, so a typo in
    ``ARIA_EXECUTION_MODE`` (or an explicit argument) surfaces immediately
    instead of degrading behaviour.
    """

    def __init__(self, value: object) -> None:
        valid = ", ".join(m.value for m in ExecutionMode)
        super().__init__(
            f"Invalid execution mode {value!r}. "
            f"Valid modes: {valid}. No implicit fallback is applied."
        )
        self.value = value


def coerce_execution_mode(value: ExecutionMode | str) -> ExecutionMode:
    """Coerce a string/enum to ``ExecutionMode``; raise loudly on anything else."""
    if isinstance(value, ExecutionMode):
        return value
    if isinstance(value, str):
        try:
            return ExecutionMode(value.strip())
        except ValueError as exc:
            raise InvalidExecutionModeError(value) from exc
    raise InvalidExecutionModeError(value)


def resolve_execution_mode(
    explicit: ExecutionMode | str | None = None,
) -> ExecutionMode:
    """Resolve the active execution mode — explicit-first, safe default.

    Order:
      1. ``explicit`` argument, if given (validated, raises on invalid).
      2. ``ARIA_EXECUTION_MODE`` environment variable, if set (validated).
      3. ``DEFAULT_MODE`` (``offline_mock``) — the only safe, no-credential mode.

    There is **no implicit fallback between modes**: an invalid explicit value or
    an invalid env value raises ``InvalidExecutionModeError`` instead of quietly
    selecting another mode. Cloud is reached only via an explicit
    ``cloud_opt_in``; credentials alone never select it.
    """
    if explicit is not None:
        return coerce_execution_mode(explicit)
    env_value = os.getenv(_ENV_VAR)
    if env_value is not None and env_value.strip() != "":
        return coerce_execution_mode(env_value)
    return DEFAULT_MODE


# ── Mode predicates (used by the provider/readiness layers and by tests) ───────

def mode_uses_mock(mode: ExecutionMode) -> bool:
    """True only for ``offline_mock`` — the deterministic, no-Ollama path."""
    return mode is ExecutionMode.offline_mock


def mode_requires_ollama(mode: ExecutionMode) -> bool:
    """True only for ``local_ollama`` — the only mode that needs a live daemon."""
    return mode is ExecutionMode.local_ollama


def mode_allows_cloud(mode: ExecutionMode) -> bool:
    """True only for ``cloud_opt_in`` — the only mode permitted to call cloud."""
    return mode is ExecutionMode.cloud_opt_in
