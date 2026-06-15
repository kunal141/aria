"""
Week 30 — regression tests for the offline golden-path demo
(``aria.demo.golden_path``).

Codex Round-1 launch-readiness findings these tests lock down:

  [P1] no-pollution  — a full demo run must leave EVERY real runtime sink
        (notifications.jsonl, tool_audit.jsonl, the three ledger files,
        memory_store.json) byte-for-byte unchanged. Before the fix the live
        CI/CD + Jira runs leaked into the real notifications.jsonl and
        tool_audit.jsonl; ``test_demo_does_not_mutate_runtime_files`` fails
        against that pre-fix code and passes after.
  [P2] no automated coverage — the 370-line executable demo had no test.
        These cover routing + evidence withholding, deterministic ROI
        metrics, offline behaviour, temp-dir cleanup, and restoration of the
        repointed module globals.

Every test drives the real ``main()`` entry point. ``main()`` strips provider
keys and repoints module globals as a side effect, so the autouse
``_restore_environ`` fixture snapshots and restores ``os.environ`` around each
test to keep the rest of the suite clean.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from aria.demo import golden_path

# apps/backend — the dir the real runtime files live in.
_BACKEND_DIR = Path(golden_path.__file__).resolve().parents[2]

# Every real, gitignored runtime sink a graph invocation could touch. The demo
# must isolate all of them; the regression test asserts none of them changes.
_RUNTIME_SINKS = (
    _BACKEND_DIR / "notifications.jsonl",
    _BACKEND_DIR / "tool_audit.jsonl",
    _BACKEND_DIR / "work_ledger.jsonl",
    _BACKEND_DIR / "work_ledger_v2.jsonl",
    _BACKEND_DIR / "evolution_events.jsonl",
    _BACKEND_DIR / "memory_store.json",
)


@pytest.fixture(autouse=True)
def _restore_environ():
    """``main()`` pops provider keys from ``os.environ`` directly; restore it."""
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _snapshot(paths) -> dict[Path, bytes | None]:
    """Content of each path now, or ``None`` if it does not exist."""
    return {p: (p.read_bytes() if p.exists() else None) for p in paths}


def _parse_stage1(out: str) -> dict[str, bool]:
    """Map each live request's routed ``task_type`` -> evidence-gate fired?"""
    result: dict[str, bool] = {}
    current_type: str | None = None
    for line in out.splitlines():
        if line.startswith("TYPE    : "):
            current_type = line.split(": ", 1)[1].strip()
        elif line.startswith("GATE    : ") and current_type is not None:
            result[current_type] = "WITHHELD" in line
            current_type = None
    return result


# ── [P1] no-pollution regression ────────────────────────────────────────────────

def test_demo_does_not_mutate_runtime_files(capsys):
    """A full demo run leaves every real runtime sink byte-for-byte unchanged."""
    before = _snapshot(_RUNTIME_SINKS)

    rc = golden_path.main([])  # no --keep: also exercises temp cleanup
    capsys.readouterr()

    after = _snapshot(_RUNTIME_SINKS)
    assert rc == 0
    changed = [p.name for p in _RUNTIME_SINKS if before[p] != after[p]]
    assert not changed, f"demo mutated real runtime files: {changed}"


# ── [P2] routing + fail-closed evidence gate ────────────────────────────────────

def test_demo_routes_and_withholds(capsys):
    """KPI + CI/CD withhold (fail-closed); PR review + Jira surface."""
    rc = golden_path.main([])
    out = capsys.readouterr().out
    assert rc == 0

    gates = _parse_stage1(out)
    assert gates.get("kpi") is True, "KPI must be withheld by the evidence gate"
    assert gates.get("ci_cd") is True, "CI/CD must be withheld by the evidence gate"
    assert gates.get("pr_review") is False, "PR review must surface an artifact"
    assert gates.get("jira") is False, "Jira draft must surface (T4 gate, not evidence gate)"


# ── [P2] deterministic ROI metrics ──────────────────────────────────────────────

def test_demo_metrics_are_deterministic(capsys):
    """The seeded + live aggregate prints the documented deterministic ROI."""
    rc = golden_path.main([])
    out = capsys.readouterr().out
    assert rc == 0

    assert "tasks completed         : 6" in out
    assert "approvals granted/reject : 1 / 1" in out
    assert "failure_rate            : 0.14285714285714285" in out
    assert "v2 events / legacy / bad : 33 / 4 / 0" in out


# ── [P2] offline guarantee ──────────────────────────────────────────────────────

def test_demo_is_offline(capsys):
    """Run completes with no provider key (guard would abort otherwise) and
    prints the no-paid-call boundary line."""
    rc = golden_path.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no paid api call, no network call" in out.lower()


# ── [P2] temp-dir cleanup ───────────────────────────────────────────────────────

def test_demo_cleans_temp_dir(capsys):
    """Without --keep, the isolated temp ledger dir is removed on exit."""
    rc = golden_path.main([])
    out = capsys.readouterr().out
    assert rc == 0

    m = re.search(r"isolated ledger:\s*(.+)", out)
    assert m, "demo did not print the isolated ledger path"
    tmp = Path(m.group(1).strip())
    assert not tmp.exists(), f"temp ledger dir was not cleaned up: {tmp}"


# ── [P1] module globals restored (no in-process pollution) ──────────────────────

def test_demo_restores_module_globals(capsys):
    """The demo repoints runtime-sink globals for the run, then restores them."""
    import aria.notifications.notifier as notifier
    import aria.security.audit_log as audit_log
    import aria.work_ledger as wl

    notifier_before = notifier._LOG_PATH
    audit_before = audit_log._AUDIT_FILE
    ledger_before = wl.LEDGER_FILE
    evo_before = wl.EVOLUTION_EVENTS_FILE

    golden_path.main([])
    capsys.readouterr()

    # The contract is: restore each global to exactly what it was on entry, and
    # never leave it pointing at the demo's temp dir. (We deliberately do NOT
    # assert a canonical filename — suite ordering can legitimately leave a prior
    # value, e.g. 'nul'; the demo's job is to restore it, whatever it is.)
    assert notifier._LOG_PATH == notifier_before
    assert audit_log._AUDIT_FILE == audit_before
    assert wl.LEDGER_FILE == ledger_before
    assert wl.EVOLUTION_EVENTS_FILE == evo_before
    for value in (notifier._LOG_PATH, audit_log._AUDIT_FILE,
                  wl.LEDGER_FILE, wl.EVOLUTION_EVENTS_FILE):
        assert "aria_golden_" not in str(value)
