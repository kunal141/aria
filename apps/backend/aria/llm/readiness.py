"""
Ollama readiness boundary + model availability verification —
Week 31 items 2 & 3 (V2 plan §6.2 / §6.3).

Readiness boundary (item 2)
---------------------------
The functions here probe the Ollama daemon and the installed-model list. They
run **only when called explicitly** — at V2 chat/API startup, from the
``aria.llm.check`` readiness command, or from a future health/readiness
endpoint. Nothing in this module runs at import time, and importing it (or any
``aria.*`` module) must not contact Ollama. The actual network call is a lazy,
stdlib-only HTTP GET, injectable via ``prober`` so tests never need a real
daemon.

Model availability verification (item 3)
----------------------------------------
``ensure_local_model_available`` verifies the configured model (default
``gemma4:e4b``, overridable via ``LLM_MODEL``) is present in Ollama. If the
daemon is unreachable or the model is absent it FAILS LOUDLY with a controlled
error that tells the user exactly what to run (``ollama pull <configured-model>``).
It NEVER auto-downloads a model, NEVER silently falls back to ``offline_mock``,
and NEVER falls back to a cloud provider.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

# A "prober" takes (host, timeout_seconds) and returns the list of installed
# model tags, or raises on an unreachable daemon.
Prober = Callable[[str, float], list[str]]

DEFAULT_LOCAL_MODEL = "gemma4:e4b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT_S = 5.0


class OllamaUnavailableError(RuntimeError):
    """The Ollama daemon could not be reached.

    Carries remediation text and is explicit that ARIA will not fall back to a
    cloud provider — a failed local brain is a loud failure, not a silent
    downgrade.
    """


class LocalModelUnavailableError(OllamaUnavailableError):
    """The Ollama daemon is reachable but the configured model is not installed.

    The message includes the exact ``ollama pull <configured-model>`` command,
    interpolated from the configured model so substitute models get correct
    guidance.
    """


@dataclass(frozen=True)
class ReadinessReport:
    """Result of a successful readiness check (raised on failure, so ``ok`` is
    always True here; it exists for callers/telemetry that want the resolved
    facts)."""

    ok: bool
    model: str
    host: str
    available_models: list[str] = field(default_factory=list)


def configured_local_model() -> str:
    """The configured local model: ``LLM_MODEL`` env, else ``gemma4:e4b``."""
    value = os.getenv("LLM_MODEL")
    return value if value and value.strip() else DEFAULT_LOCAL_MODEL


def configured_ollama_host() -> str:
    """The configured Ollama host: ``OLLAMA_HOST`` env, else localhost:11434."""
    value = os.getenv("OLLAMA_HOST")
    return value if value and value.strip() else DEFAULT_OLLAMA_HOST


def _default_probe(host: str, timeout: float) -> list[str]:
    """Lazy, dependency-free probe of the Ollama daemon's installed models.

    Uses the Ollama REST API ``GET {host}/api/tags`` via stdlib ``urllib`` so no
    extra package (or the ``ollama`` client) is required, and so importing this
    module pulls in nothing that touches the network. Raises on an unreachable
    daemon; the caller converts that to ``OllamaUnavailableError``.
    """
    import json
    import urllib.request

    url = host.rstrip("/") + "/api/tags"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost)
        payload = json.loads(resp.read().decode("utf-8"))
    models = payload.get("models", []) if isinstance(payload, dict) else []
    names: list[str] = []
    for entry in models:
        name = entry.get("name") or entry.get("model") if isinstance(entry, dict) else None
        if name:
            names.append(str(name))
    return names


def _model_present(configured: str, available: list[str]) -> bool:
    """Match the configured model against installed tags.

    Exact match wins. If the configured name has no explicit ``:tag``, also
    accept the ``:latest`` tag, since ``ollama pull gemma4`` installs
    ``gemma4:latest``. We never fuzzy-match across different models.
    """
    if configured in available:
        return True
    if ":" not in configured and f"{configured}:latest" in available:
        return True
    return False


def check_ollama_daemon(
    host: str | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    prober: Prober | None = None,
) -> list[str]:
    """Return installed model tags, or raise ``OllamaUnavailableError``.

    Explicitly-called only. Never auto-starts the daemon, never downloads.
    """
    host = host or configured_ollama_host()
    prober = prober or _default_probe
    try:
        return prober(host, timeout)
    except Exception as exc:  # URLError / OSError / socket errors / parse errors
        raise OllamaUnavailableError(
            f"Ollama daemon is not reachable at {host} "
            f"(probe failed: {type(exc).__name__}). "
            f"Start it (e.g. `ollama serve`). "
            f"ARIA will not fall back to a cloud provider."
        ) from exc


def ensure_local_model_available(
    model: str | None = None,
    host: str | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    prober: Prober | None = None,
) -> ReadinessReport:
    """Verify the configured local model is available; fail loudly otherwise.

    Item 3 contract:
      - daemon unreachable  → ``OllamaUnavailableError`` (no cloud fallback)
      - model not installed → ``LocalModelUnavailableError`` with
                              ``ollama pull <configured-model>``
      - never auto-downloads, never downgrades to ``offline_mock``,
        never falls back to cloud.

    Returns a :class:`ReadinessReport` on success.
    """
    model = model or configured_local_model()
    host = host or configured_ollama_host()
    available = check_ollama_daemon(host, timeout=timeout, prober=prober)
    if not _model_present(model, available):
        raise LocalModelUnavailableError(
            f"Configured local model {model!r} is not available in Ollama at {host}. "
            f"Run:\n    ollama pull {model}\n"
            f"ARIA will not auto-download models, will not fall back to offline_mock, "
            f"and will not fall back to a cloud provider."
        )
    return ReadinessReport(ok=True, model=model, host=host, available_models=available)
