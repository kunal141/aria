"""
Test-suite-wide isolation for the Work Ledger v2 singleton.

Round-2 finding [P1]: graph tests that called ``respond()`` were
silently appending to the runtime ``apps/backend/work_ledger_v2.jsonl``
file, doubling its size during a single test run and corrupting any
ROI metrics derived from it.

This autouse fixture redirects the singleton writer to a per-test
tmp_path BEFORE every test runs, and resets the singleton afterwards.
No test should ever need to call the env-vars directly — the fixture
handles them.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_ledger_v2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Point the v2 ledger singleton at a temp file for the duration of each
    test. Any code that calls ``aria.ledger.get_default_writer()`` (e.g.
    ``aria.nodes.respond._emit_v2_responded``) writes here, not into the
    runtime file checked into the repo.
    """
    # Lazy import — avoids initialising the v2 writer if it isn't loaded
    # by the test target (keeps pytest startup fast).
    from aria.ledger import writer as ledger_writer

    isolated_path = tmp_path / "test_work_ledger_v2.jsonl"
    monkeypatch.setenv("ARIA_LEDGER_V2_PATH", str(isolated_path))
    ledger_writer.reset_default_writer()
    try:
        yield isolated_path
    finally:
        ledger_writer.reset_default_writer()


@pytest.fixture(autouse=True)
def _isolate_deployment_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Redirect the evolution UpdateManager deployment root to a per-test temp dir
    so NO test — now or in future — writes deployed-prompt artifacts into the
    real ``apps/backend/deployments/`` tree (Codex Round-13 Finding 3).

    ``operations.DEPLOYMENT_ROOT`` is resolved at *write* time both by the
    pipeline (artifact_path) and by ``UpdateManager`` when no explicit
    ``deployment_root`` was passed, so monkeypatching this single module global
    covers every promotion path. Tests that pass an explicit
    ``deployment_root=tmp_path`` keep that precedence; tests that set
    ``ops.DEPLOYMENT_ROOT`` themselves override this value (later wins).
    """
    from aria.evolution.update_manager import operations as ops

    isolated_root = tmp_path / "deployments"
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", isolated_root)
    yield isolated_root
