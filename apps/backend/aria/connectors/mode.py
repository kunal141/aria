"""Fixture-first connector mode contract.

``fixtures`` is the deterministic, no-network default. ``read_only_live`` is an
optional provider-specific mode and fails closed unless both the mode and the
provider allowlist are configured explicitly. Credentials alone never activate
live mode. Provider connectors must add their own credential, target, transport,
and read-only policy enforcement.
"""
from __future__ import annotations

import os
from enum import StrEnum

_MODE_ENV = "CONNECTOR_MODE"
_ALLOWLIST_ENV = "CONNECTOR_PROVIDER_ALLOWLIST"


class ConnectorMode(StrEnum):
    fixtures = "fixtures"
    read_only_live = "read_only_live"


DEFAULT_MODE = ConnectorMode.fixtures


class ConnectorModeError(RuntimeError):
    """A live read-only connector was requested without valid explicit config."""


def resolve_connector_mode() -> ConnectorMode:
    """Resolve the mode, defaulting unknown and unset values to fixtures."""
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
    """Require explicit live mode and an explicitly allowlisted provider.

    Passing this shared gate is necessary but not sufficient. A provider-specific
    connector must still enforce its credential, target, and transport policy.
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
