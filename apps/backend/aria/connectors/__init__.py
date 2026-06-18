"""
aria.connectors — Week 34 read-only connector layer.

Fixtures-first: ``fixtures`` mode (default) reads deterministic local data with no
network; ``read_only_live`` is an optional fail-closed scaffold. No write methods
exist in any mode.
"""
from aria.connectors.connector import FixtureConnector, LiveConnector, get_connector
from aria.connectors.mode import (
    ConnectorMode,
    ConnectorModeError,
    ensure_live_allowed,
    is_live_mode,
    provider_allowlist,
    resolve_connector_mode,
)

__all__ = [
    "ConnectorMode",
    "ConnectorModeError",
    "resolve_connector_mode",
    "is_live_mode",
    "ensure_live_allowed",
    "provider_allowlist",
    "FixtureConnector",
    "LiveConnector",
    "get_connector",
]
