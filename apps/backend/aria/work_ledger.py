"""
Work Ledger v0 — Week 4

Logs every task as a single JSON line to work_ledger.jsonl.
This is the seed of Pillar 16 (AI Work Ledger).

By Week 29, this file will have 25 weeks of entries and feed
the ROI dashboard: "ARIA completed 847 tasks, saving ~340 hours."

Week 4:  task_id, task_type, routing_reason, timestamp
Week 8:  + artifact_id (what ARIA produced)
Week 13: + langsmith_trace_id (link every task to its trace)
Week 15: + approval_id (governance actions)
Week 22: + outcome (was the task useful? accepted/rejected?)
Week 27: + error, platform_evidence (drive EvolutionMonitor signal detection)
Week 28: + typed evolution lifecycle events (EvolutionLedgerEvent)
Week 29: full ROI dashboard built from all accumulated entries
"""
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

LEDGER_FILE = Path(__file__).parent.parent / "work_ledger.jsonl"
EVOLUTION_EVENTS_FILE = Path(__file__).parent.parent / "evolution_events.jsonl"


# ── Typed evolution lifecycle events ──────────────────────────────────────────

class EvolutionEventType(str, Enum):
    proposal         = "proposal"
    generation       = "generation"
    sandbox          = "sandbox"
    approval_request = "approval_request"
    approval         = "approval"
    canary           = "canary"
    verification     = "verification"
    promotion        = "promotion"
    activation       = "activation"
    failure          = "failure"    # covers rejection, rollback, and all error paths


class EvolutionLedgerEvent(BaseModel):
    """Typed record for one step in the evolution lifecycle.

    All correlation fields must be present when the information is known.
    Invalid event_type values are rejected by Pydantic at construction time.
    """
    event_type:     EvolutionEventType
    task_id:        str
    proposal_id:    Optional[str] = None
    update_id:      Optional[str] = None
    component_name: Optional[str] = None
    version:        Optional[str] = None
    timestamp:      str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    actor:          Optional[str] = None   # human approver, proposer, etc.
    outcome:        Optional[str] = None   # "approved", "rejected", "passed", etc.
    detail:         Optional[str] = None   # additional free-text context


def log_evolution_event(event: EvolutionLedgerEvent) -> None:
    """Append a typed evolution lifecycle event to evolution_events.jsonl."""
    with open(EVOLUTION_EVENTS_FILE, "a", encoding="utf-8") as fh:
        fh.write(event.model_dump_json() + "\n")


def read_evolution_events() -> list[EvolutionLedgerEvent]:
    """Read all evolution events from disk; skip malformed lines."""
    if not EVOLUTION_EVENTS_FILE.exists():
        return []
    events: list[EvolutionLedgerEvent] = []
    with open(EVOLUTION_EVENTS_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(EvolutionLedgerEvent.model_validate_json(line))
            except Exception:
                pass
    return events


def log_task(
    task_id: str,
    task_type: str,
    routing_reason: str,
    *,
    error: Optional[str] = None,
    platform_evidence: Optional[str] = None,
) -> None:
    """
    Append one task record to the work ledger.

    error            : error message if the task failed; None on success.
    platform_evidence: JSON-serialized EvidencedAnswer (from state.platform_evidence);
                       used by EvolutionMonitor to detect low support rates.
    """
    entry: dict = {
        "task_id":          task_id,
        "task_type":        task_type,
        "routing_reason":   routing_reason,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "error":            error,
        "platform_evidence": platform_evidence,
        "week":             4,
    }
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_ledger() -> list[dict]:
    if not LEDGER_FILE.exists():
        return []
    with open(LEDGER_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ── Week 29 — v2 ledger reachable from the same module ───────────────────────
#
# The v2 ledger lives at ``aria.ledger`` and is what new code should use.  We
# keep this module intact so every existing import (log_task, log_evolution_event,
# EvolutionEventType, EvolutionLedgerEvent, read_ledger, read_evolution_events)
# still works without change. The lines below just expose the v2 namespace
# from the same place for callers that prefer "from aria.work_ledger import ...".
#
# Convenience re-exports — do NOT add new V1 callers here.  New code should
# import directly from ``aria.ledger``.
try:  # pragma: no cover — pure re-export; v2 module owns its own tests
    from aria.ledger import (
        LedgerEvent,
        LedgerEventType,
        LedgerReader,
        LedgerWriter,
        LedgerMetrics,
        ActorType,
    )
except Exception:
    # If aria.ledger fails to import for any reason (e.g. circular import
    # during test teardown), the legacy API above remains fully functional.
    pass
