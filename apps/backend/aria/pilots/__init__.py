"""
aria.pilots — Week 34 read-only PR / CI-CD / Analytics investigation pilots.

Fixtures-first, read-only, draft-only. Pilots run behind the existing V2
orchestrator/workspace shell (no parallel agent runner) and produce
evidence-referenced reports plus draft-only actions (never executed).
"""
from aria.pilots.models import (
    DraftAction,
    DraftKind,
    EvidenceReference,
    Finding,
    PilotKind,
    PilotReport,
)
from aria.pilots.service import PilotRunResult, PilotService

__all__ = [
    "PilotService",
    "PilotRunResult",
    "PilotReport",
    "PilotKind",
    "Finding",
    "EvidenceReference",
    "DraftAction",
    "DraftKind",
]
