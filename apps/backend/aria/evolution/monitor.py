"""
Evolution Monitor — Week 27

Scans ARIA's Work Ledger and operational signals to detect capability gaps
and surface ranked EvolutionProposal candidates.

Does NOT create proposals autonomously — it returns candidates for human review.
Production integration point: called by a scheduled job (e.g. daily cron).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from aria.evolution.models import (
    RISK_CEILING,
    EvolutionProposal,
    EvolutionType,
    ProposalStatus,
    utc_now,
)


@dataclass
class MonitorSignal:
    """A single detected signal that may warrant a capability proposal."""
    signal_type: str           # "low_support_rate" | "high_error_rate" | "repeated_pattern" etc.
    task_type:   str
    evidence:    list[str]
    severity:    float         # 0.0–1.0; higher = more urgent
    source:      str           # where this was detected: "work_ledger" | "error_log" | "skill_metrics"


@dataclass
class MonitorSummary:
    """Aggregated result from one monitor scan."""
    signals:         list[MonitorSignal] = field(default_factory=list)
    proposals_draft: list[EvolutionProposal] = field(default_factory=list)
    scanned_tasks:   int = 0
    scan_timestamp:  str = ""

    def ranked_proposals(self) -> list[EvolutionProposal]:
        """Return proposals sorted by risk_score descending (highest urgency first)."""
        return sorted(self.proposals_draft, key=lambda p: p.risk_score, reverse=True)


class EvolutionMonitor:
    """
    Scans the work ledger JSONL file and surfaces evolution proposals.

    Heuristics (V1):
      - Skill with unsupported_claims > 50 % of recent runs → rag or evaluation proposal
      - Skill with error_rate > 20 % → skill proposal
      - Repeated task_type cluster with no automation → workflow proposal

    All proposals are DRAFT status — none are auto-submitted.
    """

    def __init__(
        self,
        ledger_path: Optional[str] = None,
        proposed_by: str = "monitor:work_ledger",
        lookback_tasks: int = 100,
    ) -> None:
        self._ledger_path = Path(ledger_path) if ledger_path else None
        self._proposed_by = proposed_by
        self._lookback_tasks = lookback_tasks

    # ── Public API ─────────────────────────────────────────────────────────────

    def scan(self) -> MonitorSummary:
        summary = MonitorSummary(scan_timestamp=utc_now())
        tasks = self._load_recent_tasks()
        summary.scanned_tasks = len(tasks)

        signals = self._detect_signals(tasks)
        summary.signals = signals

        for sig in signals:
            proposal = self._signal_to_proposal(sig)
            if proposal is not None:
                summary.proposals_draft.append(proposal)

        return summary

    # ── Internals ──────────────────────────────────────────────────────────────

    def _load_recent_tasks(self) -> list[dict]:
        if self._ledger_path is None or not self._ledger_path.exists():
            return []
        tasks: list[dict] = []
        try:
            with self._ledger_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            tasks.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            return []
        return tasks[-self._lookback_tasks:]

    def _detect_signals(self, tasks: list[dict]) -> list[MonitorSignal]:
        if not tasks:
            return []

        # Aggregate per task_type
        counts: dict[str, dict] = {}
        for t in tasks:
            tt = t.get("task_type") or "unknown"
            rec = counts.setdefault(tt, {"total": 0, "errors": 0, "unsupported": 0})
            rec["total"] += 1
            if t.get("error"):
                rec["errors"] += 1
            if t.get("platform_evidence"):
                try:
                    ev = json.loads(t["platform_evidence"])
                    if not ev.get("is_safe_to_surface", True):
                        rec["unsupported"] += 1
                except (json.JSONDecodeError, AttributeError):
                    pass

        signals: list[MonitorSignal] = []
        for task_type, rec in counts.items():
            total = rec["total"]
            if total < 3:
                continue

            error_rate   = rec["errors"]      / total
            support_rate = rec["unsupported"] / total

            if error_rate > 0.20:
                signals.append(MonitorSignal(
                    signal_type="high_error_rate",
                    task_type=task_type,
                    evidence=[
                        f"{rec['errors']} of {total} recent '{task_type}' tasks failed",
                        f"Error rate: {error_rate:.0%}",
                    ],
                    severity=min(error_rate, 1.0),
                    source="work_ledger",
                ))

            if support_rate > 0.50:
                signals.append(MonitorSignal(
                    signal_type="low_support_rate",
                    task_type=task_type,
                    evidence=[
                        f"{rec['unsupported']} of {total} recent '{task_type}' tasks had unsupported claims",
                        f"Unsupported rate: {support_rate:.0%} — retrieval may be stale or irrelevant",
                    ],
                    severity=min(support_rate * 0.8, 1.0),
                    source="work_ledger",
                ))

            if total >= 10:
                signals.append(MonitorSignal(
                    signal_type="repeated_pattern",
                    task_type=task_type,
                    evidence=[
                        f"'{task_type}' tasks appear {total} times in recent {self._lookback_tasks} entries",
                        "High-frequency pattern may be a candidate for workflow automation",
                    ],
                    severity=0.25,
                    source="work_ledger",
                ))

        return signals

    def _signal_to_proposal(self, sig: MonitorSignal) -> Optional[EvolutionProposal]:
        etype, risk = _SIGNAL_TO_EVOLUTION.get(sig.signal_type, (None, None))
        if etype is None:
            return None

        # Use severity to modulate risk, but cap at type ceiling
        ceiling = RISK_CEILING.get(etype.value, 0.75)
        risk_score = round(min(sig.severity * ceiling, ceiling), 3)

        pid = _stable_id(sig.signal_type, sig.task_type, sig.source)
        return EvolutionProposal(
            proposal_id=pid,
            title=f"Improve {sig.task_type} capability — {sig.signal_type}",
            description=(
                f"Monitor detected {sig.signal_type} for task_type='{sig.task_type}'. "
                f"Signal source: {sig.source}. "
                f"Severity: {sig.severity:.2f}. "
                "Review evidence and propose a concrete improvement."
            ),
            evolution_type=etype,
            status=ProposalStatus.draft,
            evidence=sig.evidence,
            risk_score=risk_score,
            expected_gain=(
                f"Reduce {sig.signal_type} for '{sig.task_type}' tasks by improving "
                f"{etype.value} layer"
            ),
            proposed_at=utc_now(),
            proposed_by=self._proposed_by,
        )


# Map signal type → (EvolutionType, base_risk)
_SIGNAL_TO_EVOLUTION: dict[str, tuple[EvolutionType, float]] = {
    "high_error_rate":   (EvolutionType.skill,    0.55),
    "low_support_rate":  (EvolutionType.rag,      0.45),
    "repeated_pattern":  (EvolutionType.workflow, 0.30),
}


def _stable_id(signal_type: str, task_type: str, source: str) -> str:
    """Deterministic proposal ID so re-running the monitor doesn't create duplicates."""
    raw = f"{signal_type}:{task_type}:{source}"
    return "mon-" + hashlib.sha256(raw.encode()).hexdigest()[:16]
