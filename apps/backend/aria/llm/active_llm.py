"""
Active-LLM construction per execution mode — Week 31 item 5 (V2 plan §6.1).

This is the single structural choke point that makes "no cloud fallback"
*structural, not documented*:

  - ``offline_mock``  → returns ``None``. There is no live LLM; the caller uses
                       the deterministic mock path. Never probes Ollama, never
                       touches cloud.
  - ``local_ollama``  → forces ``provider="ollama"`` REGARDLESS of
                       ``LLM_PROVIDER`` and regardless of which cloud credentials
                       are present. Readiness is verified first (fail loud). The
                       cloud branch of the factory is unreachable from here.
  - ``cloud_opt_in``  → uses the configured cloud provider — reached ONLY when
                       this mode was explicitly selected.

Because ``local_ollama`` hard-codes the ollama provider, the presence of
``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` / etc. can never cause a cloud call.
``config.get_llm`` is imported lazily inside the function so importing this
module contacts nothing.
"""
from __future__ import annotations

from typing import Any

from aria.llm.execution_mode import ExecutionMode, resolve_execution_mode
from aria.llm.readiness import (
    Prober,
    configured_local_model,
    ensure_local_model_available,
)


def resolve_provider_for_mode(mode: ExecutionMode) -> str | None:
    """Provider name a mode is permitted to use.

    ``offline_mock`` → ``None`` (no provider — mock path). ``local_ollama`` →
    always ``"ollama"`` (cloud is structurally unreachable). ``cloud_opt_in`` →
    the env ``LLM_PROVIDER`` (the deliberate cloud choice).
    """
    if mode is ExecutionMode.offline_mock:
        return None
    if mode is ExecutionMode.local_ollama:
        return "ollama"
    # cloud_opt_in — explicit cloud; honour the configured provider.
    import os

    return os.getenv("LLM_PROVIDER", "anthropic").lower()


def build_active_llm(
    mode: ExecutionMode | str | None = None,
    *,
    model: str | None = None,
    host: str | None = None,
    ensure: bool = True,
    prober: Prober | None = None,
    **kwargs: Any,
):
    """Build the live chat model for the resolved execution mode, or ``None``.

    - ``offline_mock`` → ``None`` (mock path; no Ollama, no cloud).
    - ``local_ollama`` → verifies the local model (unless ``ensure=False``) then
      builds an **ollama** model. Never builds a cloud client even if cloud
      credentials are present. Readiness failure raises (no fallback).
    - ``cloud_opt_in`` → builds the configured cloud provider's model.

    ``config.get_llm`` is imported lazily so this module stays import-safe.
    """
    resolved = resolve_execution_mode(mode)

    if resolved is ExecutionMode.offline_mock:
        return None

    from aria.config import get_llm  # lazy: no import-time provider construction

    if resolved is ExecutionMode.local_ollama:
        target_model = model or configured_local_model()
        if ensure:
            # Fail loud if the daemon/model is unavailable — no downgrade.
            ensure_local_model_available(target_model, host, prober=prober)
        # Provider is hard-coded to ollama: the cloud branch is unreachable here,
        # so credentials present cannot trigger a cloud call.
        return get_llm(provider="ollama", model=target_model, **kwargs)

    # cloud_opt_in — explicit, deliberate cloud usage.
    return get_llm(**kwargs)
