"""
Read-only connectors (Week 34).

``FixtureConnector`` is the fully-implemented, deterministic, no-network reader
used in the default ``fixtures`` mode. ``LiveConnector`` is the OPTIONAL
``read_only_live`` scaffold: it fails closed (raises ``ConnectorModeError`` unless
explicitly configured) and, even when configured, performs no real network read in
Week 34 (raises ``NotImplementedError``).

Both expose **read-only** methods only — there are NO write/post/send/rerun
methods anywhere, in any mode.
"""
from __future__ import annotations

from aria.connectors.fixtures.data import (
    ANALYTICS_EVENTS,
    ANALYTICS_SCHEMA,
    CICD_FIXTURES,
    PR_FIXTURES,
)
from aria.connectors.mode import ConnectorMode, ensure_live_allowed, resolve_connector_mode


class FixtureConnector:
    """Deterministic, no-network read of local fixtures. Read-only."""

    mode = ConnectorMode.fixtures
    provider = "fixtures"

    def read_pr(self, pr_id: str = "default") -> tuple[dict, list[str]]:
        data = PR_FIXTURES.get(pr_id) or PR_FIXTURES["default"]
        return data, [f"fixture:pr:{data['pr_id']}"]

    def read_ci_run(self, run_id: str = "default") -> tuple[dict, list[str]]:
        data = CICD_FIXTURES.get(run_id) or CICD_FIXTURES["default"]
        return data, [f"fixture:ci:{data['run_id']}"]

    def read_schema(self, table: str) -> tuple[dict | None, list[str]]:
        data = ANALYTICS_SCHEMA.get(table)
        return data, ([f"fixture:analytics:{table}:schema"] if data else [])

    def read_events(self, table: str) -> tuple[list[dict] | None, list[str]]:
        rows = ANALYTICS_EVENTS.get(table)
        return rows, ([f"fixture:analytics:{table}:events"] if rows else [])


class LiveConnector:
    """``read_only_live`` scaffold — fails closed, no real network in Week 34."""

    mode = ConnectorMode.read_only_live

    def __init__(self, provider: str) -> None:
        self.provider = provider

    def _guard(self):
        # Fail closed unless explicitly configured (mode + allowlist) ...
        ensure_live_allowed(self.provider)
        # ... and even then, no real network read exists in Week 34.
        raise NotImplementedError(
            "read_only_live connector reads are scaffold-only in Week 34 (no live network reads)."
        )

    def read_pr(self, pr_id: str = "default"):
        self._guard()

    def read_ci_run(self, run_id: str = "default"):
        self._guard()

    def read_schema(self, table: str):
        self._guard()

    def read_events(self, table: str):
        self._guard()


def get_connector(provider: str = "github"):
    """Return the active read-only connector. ``fixtures`` (default) → fixtures;
    ``read_only_live`` → the fail-closed live scaffold. Credentials are never
    consulted to choose the mode."""
    if resolve_connector_mode() is ConnectorMode.read_only_live:
        return LiveConnector(provider)
    return FixtureConnector()
