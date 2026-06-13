"""
ROI metric helpers — Work Ledger v2.

Every metric below has its denominator and numerator nailed down so the
Week-29 ROI Dashboard, the dataset export, and the eventual fine-tuning
training set agree on what they count.

Semantics (mirrored in CLAUDE.md § 29)
--------------------------------------
- A **task** is a unique ``task_id`` appearing in any v2 event.
- **Completed task** = ≥1 ``Responded`` event.
- **Failed task**    = ≥1 ``Failed`` event AND no ``Responded`` event.
- **Terminal task**  = completed ∪ failed (disjoint).
- **approval_rate**  = approved / (approved + rejected).  Pending
                       requests are NOT in the denominator.
- **failure_rate**   = failed_tasks / terminal_tasks.
- **avg_time_to_resolution** = mean over completed tasks of
                       (last_event_ts − task_created_ts).  Tasks without
                       a ``TaskCreated`` event are excluded.
- **estimated_cost_per_task** = Σ CostRecorded.estimated_cost /
                       count(distinct task_ids with ≥1 CostRecorded).
- **human_intervention_rate** = count(tasks with ≥1 event whose
                       actor_type='human') / count(completed_tasks).

All cost math runs through ``Decimal``; no binary-float ambiguity.
Legacy task records are adapted to the same task-id namespace so the
metrics can include the 1k+ Week-4 entries already on disk — see
``include_legacy_tasks`` below.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional

from aria.ledger.events import (
    ActorType,
    LedgerEvent,
    LedgerEventType,
    LegacyEvolutionRecord,
    LegacyTaskRecord,
)
from aria.ledger.exceptions import MalformedLedgerRecord
from aria.ledger.reader import LedgerRecord


@dataclass(frozen=True)
class MetricsSummary:
    """Snapshot of every Week-29 ROI metric over one stream of records."""
    total_tasks_completed:   int
    tasks_by_skill:          dict[str, int]
    approval_rate:           Optional[float]
    approvals_granted:       int
    approvals_rejected:      int
    # Per-skill rates: skill_name -> rate (None when the per-skill
    # denominator is zero — e.g. no verdicts on a skill yet). The
    # dashboard MUST surface "no data" for those rather than 0.0.
    approval_rate_by_skill:  dict[str, Optional[float]]
    failure_rate:            Optional[float]
    failed_tasks:            int
    terminal_tasks:          int
    failure_rate_by_skill:   dict[str, Optional[float]]
    avg_time_to_resolution_ms: Optional[float]
    estimated_cost_total:    Decimal
    estimated_cost_per_task: Optional[Decimal]
    tasks_with_cost:         int
    human_intervention_rate: Optional[float]
    artifact_count:          int
    correction_count:        int
    model_usage_breakdown:   dict[str, int]
    # Compatibility / observability
    v2_event_count:          int
    legacy_task_count:       int
    legacy_evolution_count:  int
    malformed_count:         int


class LedgerMetrics:
    """
    Compute ROI metrics over a stream of records from ``LedgerReader``.

    Pass any iterable of records (v2 events, legacy records, malformed
    records).  Legacy task records can optionally count toward
    completion/failure metrics; legacy evolution records never do.
    """

    def __init__(
        self,
        records: Iterable[LedgerRecord],
        *,
        include_legacy_tasks: bool = True,
    ) -> None:
        # Materialise once — the source generator may be one-shot.
        self._records: list[LedgerRecord] = list(records)
        self._include_legacy_tasks = include_legacy_tasks

    # ── Public API ──────────────────────────────────────────────────────────

    def summary(self) -> MetricsSummary:
        v2 = [r for r in self._records if _is_v2_event(r)]
        legacy_tasks = [r for r in self._records if isinstance(r, LegacyTaskRecord)]
        legacy_evos  = [r for r in self._records if isinstance(r, LegacyEvolutionRecord)]
        malformed    = [r for r in self._records if isinstance(r, MalformedLedgerRecord)]

        tasks_by_event = _index_by_task(v2)

        completed_task_ids = _completed_task_ids(tasks_by_event)
        failed_task_ids    = _failed_task_ids(tasks_by_event, completed_task_ids)

        # Legacy contribution: a task that exists in BOTH ledgers (production
        # mirror) must NOT be double-counted in completion/failure totals.
        # task_id is the dedupe key.
        if self._include_legacy_tasks:
            for lr in legacy_tasks:
                if lr.task_id in completed_task_ids or lr.task_id in failed_task_ids:
                    continue   # already accounted for via v2 events
                if lr.error:
                    failed_task_ids.add(lr.task_id)
                else:
                    completed_task_ids.add(lr.task_id)

        terminal_task_ids = completed_task_ids | failed_task_ids

        legacy_for_skill = legacy_tasks if self._include_legacy_tasks else []

        # task_skills: dict[task_id, set[skill_name]] — ALL skills each task
        # invoked. A multi-skill workflow (PR Review + QA) contributes to
        # both skills' counts in tasks_by_skill (one (task_id, skill) pair
        # per skill).
        task_skills: dict[str, set[str]] = _build_task_skills(v2, legacy_for_skill)

        # task_attribution_skill: dict[task_id, str] — the ONE canonical
        # skill for task-level outcome attribution (failure / approval).
        # Resolution: earliest SkillInvoked, or legacy task_type fallback.
        # A task has at most one terminal outcome, so failure_rate_by_skill
        # / approval_rate_by_skill use this attribution map.
        task_attribution_skill: dict[str, str] = _build_attribution_map(
            v2, legacy_for_skill,
        )

        # tasks_by_skill = count of distinct (task_id, skill_name) pairs.
        # Cross-source dedup happens inside _build_task_skills.
        tasks_by_skill: dict[str, int] = {}
        for skill_set in task_skills.values():
            for skill in skill_set:
                tasks_by_skill[skill] = tasks_by_skill.get(skill, 0) + 1

        # The full universe of known skills — used so per-skill rate dicts
        # include EVERY skill, with None where the denominator is zero
        # (rather than silently omitting those skills).
        all_known_skills: set[str] = set(tasks_by_skill.keys())

        # Approvals.
        approvals_granted, approvals_rejected = _approvals(v2)
        approval_rate = _ratio(approvals_granted, approvals_granted + approvals_rejected)
        approval_rate_by_skill = _per_skill_approval_rates(
            v2, task_attribution_skill, all_known_skills,
        )

        # Failure rates.
        failure_rate = _ratio(len(failed_task_ids), len(terminal_task_ids))
        failure_rate_by_skill = _per_skill_failure_rates(
            task_attribution_skill, completed_task_ids, failed_task_ids,
            all_known_skills,
        )

        avg_resolution_ms = _avg_resolution_ms(tasks_by_event, completed_task_ids)

        cost_total, tasks_with_cost = _cost_total(v2)
        cost_per_task: Optional[Decimal] = (
            (cost_total / tasks_with_cost).quantize(Decimal("0.0001"))
            if tasks_with_cost > 0 else None
        )

        human_rate = _human_intervention_rate(tasks_by_event, completed_task_ids)

        artifact_count   = _count_event(v2, LedgerEventType.artifact_created)
        correction_count = _count_event(v2, LedgerEventType.correction_recorded)
        model_usage      = _model_usage(v2)

        return MetricsSummary(
            total_tasks_completed   = len(completed_task_ids),
            tasks_by_skill          = tasks_by_skill,
            approval_rate           = approval_rate,
            approvals_granted       = approvals_granted,
            approvals_rejected      = approvals_rejected,
            approval_rate_by_skill  = approval_rate_by_skill,
            failure_rate            = failure_rate,
            failed_tasks            = len(failed_task_ids),
            terminal_tasks          = len(terminal_task_ids),
            failure_rate_by_skill   = failure_rate_by_skill,
            avg_time_to_resolution_ms = avg_resolution_ms,
            estimated_cost_total    = cost_total,
            estimated_cost_per_task = cost_per_task,
            tasks_with_cost         = tasks_with_cost,
            human_intervention_rate = human_rate,
            artifact_count          = artifact_count,
            correction_count        = correction_count,
            model_usage_breakdown   = model_usage,
            v2_event_count          = len(v2),
            legacy_task_count       = len(legacy_tasks),
            legacy_evolution_count  = len(legacy_evos),
            malformed_count         = len(malformed),
        )

    # ── Individual metric methods (callable a la carte) ─────────────────────

    def total_tasks_completed(self) -> int:
        return self.summary().total_tasks_completed

    def tasks_by_skill(self) -> dict[str, int]:
        return self.summary().tasks_by_skill

    def approval_rate(self) -> Optional[float]:
        return self.summary().approval_rate

    def approval_rate_by_skill(self) -> dict[str, Optional[float]]:
        return self.summary().approval_rate_by_skill

    def failure_rate(self) -> Optional[float]:
        return self.summary().failure_rate

    def failure_rate_by_skill(self) -> dict[str, Optional[float]]:
        return self.summary().failure_rate_by_skill

    def avg_time_to_resolution_ms(self) -> Optional[float]:
        return self.summary().avg_time_to_resolution_ms

    def estimated_cost_per_task(self) -> Optional[Decimal]:
        return self.summary().estimated_cost_per_task

    def human_intervention_rate(self) -> Optional[float]:
        return self.summary().human_intervention_rate

    def artifact_count(self) -> int:
        return self.summary().artifact_count

    def correction_count(self) -> int:
        return self.summary().correction_count

    def model_usage_breakdown(self) -> dict[str, int]:
        return self.summary().model_usage_breakdown


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_v2_event(r: LedgerRecord) -> bool:
    return (
        not isinstance(r, MalformedLedgerRecord)
        and not isinstance(r, LegacyTaskRecord)
        and not isinstance(r, LegacyEvolutionRecord)
    )


def _index_by_task(v2: list[LedgerEvent]) -> dict[str, list[LedgerEvent]]:
    out: dict[str, list[LedgerEvent]] = {}
    for ev in v2:
        out.setdefault(ev.task_id, []).append(ev)
    return out


def _completed_task_ids(tasks: dict[str, list[LedgerEvent]]) -> set[str]:
    return {
        tid for tid, events in tasks.items()
        if any(e.event_type == LedgerEventType.responded for e in events)
    }


def _failed_task_ids(
    tasks: dict[str, list[LedgerEvent]],
    completed: set[str],
) -> set[str]:
    return {
        tid for tid, events in tasks.items()
        if tid not in completed
        and any(e.event_type == LedgerEventType.failed for e in events)
    }


def _build_task_skills(
    v2: list[LedgerEvent],
    legacy_tasks: list[LegacyTaskRecord],
) -> dict[str, set[str]]:
    """
    Map each ``task_id`` to the SET of all distinct ``skill_name`` values
    it touched, deduplicated across v2 SkillInvoked events AND legacy
    task records. A multi-skill workflow contributes one entry per skill;
    a task mirrored into both ledgers under the same skill contributes
    once. This is the dedup key for ``tasks_by_skill``.
    """
    out: dict[str, set[str]] = {}
    for ev in v2:
        if ev.event_type == LedgerEventType.skill_invoked and ev.skill_name:
            out.setdefault(ev.task_id, set()).add(ev.skill_name)
    for lr in legacy_tasks:
        if lr.task_type:
            out.setdefault(lr.task_id, set()).add(lr.task_type)
    return out


def _build_attribution_map(
    v2: list[LedgerEvent],
    legacy_tasks: list[LegacyTaskRecord],
) -> dict[str, str]:
    """
    Pick ONE canonical skill per ``task_id`` for task-level outcome
    attribution (``failure_rate_by_skill``, ``approval_rate_by_skill``).

    A task has at most one terminal outcome, so the outcome must be
    attributed to a single skill. This is an explicit policy — not the
    same operation as the multi-valued ``_build_task_skills`` above.

    Resolution (first match wins; ties broken by timestamp):
      1. earliest ``SkillInvoked.skill_name`` for that ``task_id`` in v2
      2. ``LegacyTaskRecord.task_type`` (fallback for legacy-only tasks)
    """
    first_skill_by_task: dict[str, tuple[str, datetime]] = {}
    for ev in v2:
        if ev.event_type == LedgerEventType.skill_invoked and ev.skill_name:
            existing = first_skill_by_task.get(ev.task_id)
            if existing is None or ev.timestamp < existing[1]:
                first_skill_by_task[ev.task_id] = (ev.skill_name, ev.timestamp)

    out: dict[str, str] = {tid: skill for tid, (skill, _ts) in first_skill_by_task.items()}
    for lr in legacy_tasks:
        if lr.task_id in out:
            continue
        if lr.task_type:
            out[lr.task_id] = lr.task_type
    return out


def _per_skill_approval_rates(
    v2: list[LedgerEvent],
    attribution: dict[str, str],
    all_known_skills: set[str],
) -> dict[str, Optional[float]]:
    """
    For each skill in ``all_known_skills`` return
    ``granted / (granted + rejected)`` over verdicts attributed to that
    skill. Skills with no verdicts return ``None`` — the dashboard
    surfaces "no data" rather than misleading 0.0.
    """
    granted_by_skill: dict[str, int] = {}
    rejected_by_skill: dict[str, int] = {}

    first_verdict: dict[str, tuple[LedgerEventType, datetime, str]] = {}
    for ev in v2:
        if ev.event_type not in (LedgerEventType.approved, LedgerEventType.rejected):
            continue
        if not ev.approval_id:
            continue
        existing = first_verdict.get(ev.approval_id)
        if existing is None or ev.timestamp < existing[1]:
            first_verdict[ev.approval_id] = (ev.event_type, ev.timestamp, ev.task_id)

    for _approval_id, (et, _ts, task_id) in first_verdict.items():
        skill = attribution.get(task_id)
        if skill is None:
            continue
        if et == LedgerEventType.approved:
            granted_by_skill[skill] = granted_by_skill.get(skill, 0) + 1
        else:
            rejected_by_skill[skill] = rejected_by_skill.get(skill, 0) + 1

    rates: dict[str, Optional[float]] = {}
    for skill in all_known_skills:
        g = granted_by_skill.get(skill, 0)
        r = rejected_by_skill.get(skill, 0)
        rates[skill] = _ratio(g, g + r)   # None when denominator is 0
    return rates


def _per_skill_failure_rates(
    attribution: dict[str, str],
    completed_task_ids: set[str],
    failed_task_ids: set[str],
    all_known_skills: set[str],
) -> dict[str, Optional[float]]:
    """
    For each skill in ``all_known_skills`` return
    ``failed_terminal / total_terminal`` where terminal =
    completed ∪ failed. Skills with no terminal tasks return ``None``.
    """
    failed_by_skill: dict[str, int] = {}
    terminal_by_skill: dict[str, int] = {}
    for tid, skill in attribution.items():
        is_failed = tid in failed_task_ids
        is_completed = tid in completed_task_ids
        if not (is_failed or is_completed):
            continue
        terminal_by_skill[skill] = terminal_by_skill.get(skill, 0) + 1
        if is_failed:
            failed_by_skill[skill] = failed_by_skill.get(skill, 0) + 1

    rates: dict[str, Optional[float]] = {}
    for skill in all_known_skills:
        denom = terminal_by_skill.get(skill, 0)
        rates[skill] = _ratio(failed_by_skill.get(skill, 0), denom)
    return rates


def _tasks_by_skill(v2: list[LedgerEvent]) -> dict[str, int]:
    """
    v2-only helper retained for the per-method LedgerMetrics.tasks_by_skill()
    API. The summary() path uses _build_task_to_skill_map for cross-source
    dedup; this helper is kept for tests/callers that want v2-only counts.
    """
    pairs: set[tuple[str, str]] = set()
    for ev in v2:
        if ev.event_type == LedgerEventType.skill_invoked and ev.skill_name:
            pairs.add((ev.task_id, ev.skill_name))
    out: dict[str, int] = {}
    for _tid, skill in pairs:
        out[skill] = out.get(skill, 0) + 1
    return out


def _approvals(v2: list[LedgerEvent]) -> tuple[int, int]:
    """
    Count DISTINCT ``approval_id`` per verdict type. Two events with the
    same approval_id and the same verdict (e.g. legitimate retry) count
    once. An ``approval_id`` that appears in both an ``Approved`` and a
    ``Rejected`` event is a data bug — we count the FIRST verdict by
    timestamp and ignore the contradiction in the totals (it surfaces in
    ``contradicting_approvals``).
    """
    first_verdict: dict[str, tuple[LedgerEventType, datetime]] = {}
    for ev in v2:
        if ev.event_type not in (LedgerEventType.approved, LedgerEventType.rejected):
            continue
        if not ev.approval_id:
            continue
        existing = first_verdict.get(ev.approval_id)
        if existing is None or ev.timestamp < existing[1]:
            first_verdict[ev.approval_id] = (ev.event_type, ev.timestamp)
    granted = sum(1 for et, _ in first_verdict.values() if et == LedgerEventType.approved)
    rejected = sum(1 for et, _ in first_verdict.values() if et == LedgerEventType.rejected)
    return granted, rejected


def _avg_resolution_ms(
    tasks: dict[str, list[LedgerEvent]],
    completed: set[str],
) -> Optional[float]:
    """
    Time from the FIRST ``TaskCreated`` to the FIRST ``Responded`` event
    for each completed task. Later events (corrections, outcomes,
    follow-up activity) are EXCLUDED — they happen after the task has
    been delivered and must not stretch the resolution metric.
    """
    durations: list[float] = []
    for tid in completed:
        events = tasks.get(tid, [])
        created = min(
            (e.timestamp for e in events if e.event_type == LedgerEventType.task_created),
            default=None,
        )
        if created is None:
            continue
        responded = min(
            (e.timestamp for e in events if e.event_type == LedgerEventType.responded),
            default=None,
        )
        if responded is None:
            continue
        durations.append((responded - created).total_seconds() * 1000.0)
    if not durations:
        return None
    return sum(durations) / len(durations)


def _cost_total(v2: list[LedgerEvent]) -> tuple[Decimal, int]:
    total = Decimal("0")
    tasks_with_cost: set[str] = set()
    for ev in v2:
        if ev.event_type == LedgerEventType.cost_recorded and ev.estimated_cost is not None:
            total += ev.estimated_cost
            tasks_with_cost.add(ev.task_id)
    return total, len(tasks_with_cost)


def _human_intervention_rate(
    tasks: dict[str, list[LedgerEvent]],
    completed: set[str],
) -> Optional[float]:
    if not completed:
        return None
    with_human = {
        tid for tid, events in tasks.items()
        if tid in completed and any(e.actor_type == ActorType.human for e in events)
    }
    return len(with_human) / len(completed)


def _count_event(v2: list[LedgerEvent], et: LedgerEventType) -> int:
    return sum(1 for e in v2 if e.event_type == et)


def _model_usage(v2: list[LedgerEvent]) -> dict[str, int]:
    out: dict[str, int] = {}
    for ev in v2:
        if ev.event_type == LedgerEventType.model_used and ev.model_name:
            label = (
                f"{ev.model_name}@{ev.model_version}"
                if ev.model_version else ev.model_name
            )
            out[label] = out.get(label, 0) + 1
    return out


def _ratio(num: int, den: int) -> Optional[float]:
    if den <= 0:
        return None
    return num / den
