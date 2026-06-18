"""
Connector Mode Contract (Week 34 §1).

Two modes, fixtures-first:

  - ``fixtures``        deterministic local fixtures (the ONLY fully-implemented
                        mode in Week 34). No network, ever. The default.
  - ``read_only_live``  OPTIONAL scaffold only. It must FAIL CLOSED unless
                        explicitly configured (explicit mode + provider
                        allowlist) and even then performs no real network read in
                        Week 34 (it raises ``NotImplementedError``).

Hard rules:
  - ``CONNECTOR_MODE=fixtures`` is the default; an unset/unknown value resolves to
    ``fixtures`` (fail-safe).
  - **Credentials alone NEVER activate live mode** — resolution looks only at
    ``CONNECTOR_MODE``, never at the presence of API keys.
  - ``read_only_live`` requires an explicit ``CONNECTOR_MODE=read_only_live`` AND
    a provider on the ``CONNECTOR_PROVIDER_ALLOWLIST``; otherwise it raises
    ``ConnectorModeError`` (fail closed).
  - No write methods exist anywhere; no external writes in any mode.
"""
from __future__ import annotations

import os
from enum import Enum

_MODE_ENV = "CONNECTOR_MODE"
_ALLOWLIST_ENV = "CONNECTOR_PROVIDER_ALLOWLIST"


class ConnectorMode(str, Enum):
    fixtures = "fixtures"
    read_only_live = "read_only_live"


DEFAULT_MODE = ConnectorMode.fixtures


class ConnectorModeError(RuntimeError):
    """A live read-only connector was requested without valid explicit config."""


def resolve_connector_mode() -> ConnectorMode:
    """Resolve the active connector mode. Default + fail-safe is ``fixtures``.

    Only an explicit, exact ``CONNECTOR_MODE=read_only_live`` selects live; any
    other value (including unset, blank, or unknown) resolves to ``fixtures``.
    Credentials are never consulted here.
    """
    raw = (os.getenv(_MODE_ENV) or "").strip().lower()
    if raw == ConnectorMode.read_only_live.value:
        return ConnectorMode.read_only_live
    return DEFAULT_MODE


def provider_allowlist() -> frozenset[str]:
    raw = os.getenv(_ALLOWLIST_ENV) or ""
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def is_live_mode() -> bool:
    return resolve_connector_mode() is ConnectorMode.read_only_live


def ensure_live_allowed(provider: str) -> None:
    """Fail closed unless live mode is explicitly + validly configured.

    Raises ``ConnectorModeError`` when:
      - the mode is not explicitly ``read_only_live``, or
      - the provider is not on the allowlist.

    NOTE: even when this passes, Week 34 performs no real network read — the live
    connector raises ``NotImplementedError`` (scaffold only).
    """
    if resolve_connector_mode() is not ConnectorMode.read_only_live:
        raise ConnectorModeError(
            "read_only_live is not active. Set CONNECTOR_MODE=read_only_live explicitly "
            "(credentials alone never activate live mode)."
        )
    allow = provider_allowlist()
    if provider.strip().lower() not in allow:
        raise ConnectorModeError(
            f"provider {provider!r} is not on CONNECTOR_PROVIDER_ALLOWLIST "
            f"({sorted(allow)}); refusing live read (fail closed)."
        )
