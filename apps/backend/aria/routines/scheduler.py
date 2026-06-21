"""
Deterministic local scheduler for V3.8 routines.

Pure cadence math — NO OS cron, NO cloud scheduler, NO background thread, NO network.
A routine's due-ness is computed against an injected ``now`` so tests are fully
deterministic. A routine overdue beyond its grace window is "missed" (ARIA does not
silently run very stale work).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from aria.routines.models import Cadence, RoutineDefinition

# A routine overdue by MORE than this many windows is recorded as missed, not run.
_GRACE_WINDOWS = 2


class DueState(str, Enum):
    not_due = "not_due"          # cadence window has not elapsed
    due = "due"                  # due now and within the grace window — run it
    missed = "missed"           # overdue beyond grace — record missed, don't run stale
    manual_only = "manual_only"  # cadence == manual — never auto-due


def _baseline(definition: RoutineDefinition) -> datetime:
    """The reference point for the next-due calculation: the last run, else creation."""
    return definition.last_run_at or definition.created_at


def due_at(definition: RoutineDefinition) -> datetime | None:
    """The next time this routine becomes due, or None for manual routines."""
    window = definition.window_hours()
    if window is None:
        return None
    return _baseline(definition) + timedelta(hours=window)


def evaluate(definition: RoutineDefinition, now: datetime) -> DueState:
    """Deterministically classify a routine's due-state at ``now``."""
    if not definition.enabled:
        return DueState.not_due
    window = definition.window_hours()
    if window is None:
        return DueState.manual_only
    elapsed = now - _baseline(definition)
    win = timedelta(hours=window)
    if elapsed < win:
        return DueState.not_due
    # last_run_at is None means a first run — never "missed", always a normal due.
    if definition.last_run_at is not None and elapsed >= win * _GRACE_WINDOWS:
        return DueState.missed
    return DueState.due


def is_due(definition: RoutineDefinition, now: datetime) -> bool:
    return evaluate(definition, now) is DueState.due
