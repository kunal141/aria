"""
Action executors (V3.9) — dry-run and internal-mock ONLY.

Only two executors actually run, and neither performs any real external write,
network call, or connector invocation:

  - :class:`DryRunExecutor` — writes nothing; returns a preview-style receipt.
  - :class:`MockLiveExecutor` — simulates an external system by writing ONLY to ARIA's
    local receipt store; permitted only for the ``internal_mock`` target.

Real external execution (``live`` mode, or mock against a real target system) is
represented by :class:`BlockedLiveExecutor`, which HARD-BLOCKS with a safe error. No
Teams/Slack/Gmail/Jira/GitHub/webhook executor is implemented in V3.9.
"""
from __future__ import annotations

from datetime import datetime

from aria.actions import receipts
from aria.actions.models import (
    ActionIntent,
    ActionReceipt,
    ExecutionMode,
    TargetSystem,
)
from aria.actions.policy import PolicyDecision


class ExecutorError(RuntimeError):
    """Base class for executor failures (safe — class/code only is ever surfaced)."""


class LiveExecutionBlocked(ExecutorError):
    """A real/live execution was attempted — hard-blocked in V3.9."""


class DryRunExecutor:
    mode = ExecutionMode.dry_run

    def execute(self, intent: ActionIntent, decision: PolicyDecision, *, executed_by: str,
                now: datetime) -> ActionReceipt:
        # Writes nothing — a pure preview of what WOULD happen.
        return receipts.dry_run_receipt(
            intent, rollback_note=decision.rollback_note,
            compensation_note=decision.compensation_note, executed_by=executed_by, now=now)


class MockLiveExecutor:
    mode = ExecutionMode.mock_live

    def execute(self, intent: ActionIntent, decision: PolicyDecision, *, executed_by: str,
                now: datetime) -> ActionReceipt:
        # Defense-in-depth: mock-live is ONLY ever valid for internal_mock. The policy
        # already blocks external targets; this guard makes the executor itself safe.
        if intent.target_system is not TargetSystem.internal_mock:
            raise LiveExecutionBlocked(
                "mock-live execution is permitted only for the internal_mock target")
        return receipts.mock_receipt(
            intent, rollback_note=decision.rollback_note,
            compensation_note=decision.compensation_note, executed_by=executed_by, now=now)


class BlockedLiveExecutor:
    """Placeholder for real external execution — ALWAYS hard-blocks in V3.9."""
    mode = ExecutionMode.live

    def execute(self, intent: ActionIntent, decision: PolicyDecision, *, executed_by: str,
                now: datetime) -> ActionReceipt:
        raise LiveExecutionBlocked(
            "live execution is disabled in V3.9; no real external write is permitted")


_EXECUTORS = {
    ExecutionMode.dry_run: DryRunExecutor(),
    ExecutionMode.mock_live: MockLiveExecutor(),
    ExecutionMode.live: BlockedLiveExecutor(),
}


def get_executor(mode: ExecutionMode):
    """Return the executor for a mode. ``live`` returns a hard-blocking executor."""
    return _EXECUTORS[mode]
