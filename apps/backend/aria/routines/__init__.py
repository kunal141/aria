"""
aria.routines — V3.8 Scheduled Routines + Approved Monitoring.

A governed, LOCAL, deterministic layer that lets ARIA run recurring INTERNAL work
loops (daily/weekly goal reviews, blocker/risk reviews, memory and collaboration
reviews, fixture-only world checks) on a manual-trigger or due-run basis against an
injected clock — no OS cron, no cloud scheduler, no background daemon, no network.

ARIA can schedule, run, summarize, review, and recommend. ARIA cannot live-browse,
monitor uncontrolled sources, send messages, mutate external systems, or run external
agents. World checks are fixture-only; follow-ups are V3.7 drafts; improvement
suggestions route through V3.5 as proposals only (never activated).

A SEPARATE package — importing it never drags in V1 LLM skills, and importing a V1
skill never loads this layer.
"""
from aria.routines.models import (
    ROUTINE_BOUNDARY,
    Cadence,
    OutputType,
    RoutineDefinition,
    RoutineOutput,
    RoutineRun,
    RoutineType,
    RunStatus,
)
from aria.routines.scheduler import DueState, due_at, evaluate, is_due
from aria.routines.service import RoutineService
from aria.routines.store import (
    RoutineDisabledError,
    RoutineIntegrityError,
    RoutineNotFound,
    RoutineSecurityError,
    RoutineStore,
)

__all__ = [
    "RoutineService",
    "RoutineStore",
    "RoutineNotFound",
    "RoutineDisabledError",
    "RoutineSecurityError",
    "RoutineIntegrityError",
    "RoutineDefinition",
    "RoutineRun",
    "RoutineOutput",
    "RoutineType",
    "Cadence",
    "RunStatus",
    "OutputType",
    "ROUTINE_BOUNDARY",
    "DueState",
    "evaluate",
    "is_due",
    "due_at",
]
