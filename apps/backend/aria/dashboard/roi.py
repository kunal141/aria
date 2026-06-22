"""
Deterministic ROI estimation (V3.10).

ROI is always ESTIMATED and transparent. Each kind of artifact ARIA produced is
credited a conservative minutes-saved default; the calculation method is always
exposed. Cost is computed ONLY if an hourly rate is configured — ARIA never invents a
salary/cost. Blocked unsafe actions are recorded as risk-reduction notes, not money.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from aria.dashboard.models import ROISummary

# Canonical markers the dashboard store uses to verify an ROI came from THIS approved
# calculator (not arbitrary caller text). Changing these requires updating the store.
ROI_METHOD_MARKER = "conservative minutes-saved per artifact"
ROI_COST_MARKER = "Cost = minutes/60"

# Conservative minutes-saved defaults (per artifact). Documented in calculation_method.
MINUTES_SAVED = {
    "manager_update": 10,
    "stakeholder_question": 8,
    "handoff_note": 12,
    "daily_goal_review": 15,
    "blocker_review": 15,
    "world_fixture_check": 10,
    "action_preview": 5,
    "reusable_lesson": 20,           # future leverage
}


def _now() -> datetime:
    return datetime.now(UTC)


def estimate_roi(counts: dict[str, int], *, hourly_cost: float | None = None,
                 blocked_unsafe_actions: int = 0, evidence_refs: list[str] | None = None,
                 tasks_completed: int = 0, drafts_created: int = 0, routines_completed: int = 0,
                 action_previews_created: int = 0, approvals_prepared: int = 0) -> ROISummary:
    """Deterministically estimate ROI from artifact counts.

    ``counts`` maps a :data:`MINUTES_SAVED` key to how many of that artifact exist.
    ``hourly_cost`` is optional; when absent, only minutes saved are reported.
    """
    minutes = sum(MINUTES_SAVED.get(k, 0) * max(0, int(v)) for k, v in (counts or {}).items())
    parts = [f"{k}={MINUTES_SAVED[k]}min×{int(counts.get(k, 0))}"
             for k in MINUTES_SAVED if counts.get(k)]
    method = (f"Estimated, {ROI_METHOD_MARKER}: "
              + ("; ".join(parts) if parts else "no creditable artifacts yet")
              + ". Blocked unsafe actions are risk-reduction notes, not money.")

    cost_saved: float | None = None
    if hourly_cost is not None and hourly_cost > 0:
        cost_saved = round((minutes / 60.0) * float(hourly_cost), 2)
        method += f" {ROI_COST_MARKER} × hourly_cost({hourly_cost})."
    else:
        method += " No hourly cost configured — minutes saved only."

    notes: list[str] = []
    if blocked_unsafe_actions:
        notes.append(f"{blocked_unsafe_actions} unsafe action(s) blocked by the governed gate "
                     "(risk avoided, not money saved).")

    return ROISummary(
        roi_summary_id=f"roi-{uuid.uuid4().hex}", tasks_completed=tasks_completed,
        drafts_created=drafts_created, routines_completed=routines_completed,
        action_previews_created=action_previews_created, approvals_prepared=approvals_prepared,
        estimated_minutes_saved=minutes, estimated_cost_saved=cost_saved,
        risk_reduction_notes=notes, evidence_refs=list(evidence_refs or []),
        calculation_method=method, estimated=True, created_at=_now(),
    )
