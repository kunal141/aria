"""
ROI Dashboard backend — GET /api/v1/ledger/metrics.

Implements the Week 29 Priority 2 backend contract:

- Single metrics authority: ``LedgerMetrics.summary()``.
- Reads all three sources (v2 + legacy task + legacy evolution).
- Configurable paths via environment variables — tests inject tmp files.
- Stable typed response (``api_models.MetricsResponse``), not internal
  ``MetricsSummary``.
- Decimal cost serialised as strings.
- Filters: date range, skill, actor_type, workflow_id.
- ``None`` for unavailable rates / costs / durations (no fabricated zeros).
- Empty ledger → zero-safe response.
- Malformed records counted via ``sources.malformed_count`` and skipped.
- Permission / filesystem / config / unexpected failures → typed JSON
  error response, never silently coerced into ``malformed_count``.
- No raw events, metadata, error strings, prompts, credentials in the
  response shape.
- Bounded behaviour for oversized ledgers — see
  ``ARIA_LEDGER_API_MAX_RECORDS``.

Environment variables
---------------------
- ``ARIA_LEDGER_V2_PATH``                 default: ``apps/backend/work_ledger_v2.jsonl``
- ``ARIA_LEDGER_LEGACY_TASK_PATH``        default: ``apps/backend/work_ledger.jsonl``
- ``ARIA_LEDGER_LEGACY_EVOLUTION_PATH``   default: ``apps/backend/evolution_events.jsonl``
- ``ARIA_LEDGER_API_MAX_RECORDS``         default: ``100000``
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

_log = logging.getLogger("aria.ledger.api")


# Stable, sanitised client-facing messages. The full exception text is
# logged server-side (with traceback) but NEVER serialised into the
# response — exception strings can carry filesystem paths, usernames,
# embedded credentials, or provider details that have no business
# reaching a browser.
_GENERIC_CLIENT_MESSAGES: dict[str, str] = {
    "config_error":     "Ledger configuration error.",
    "filesystem_error": "Ledger could not be read.",
    "oversized_ledger": "Ledger record count exceeds the configured cap.",
    "invalid_filter":   "Invalid filter value.",
    "unexpected":       "Unexpected ledger error.",
}

from aria.ledger.api_models import (
    ApprovalPanel,
    ArtifactsPanel,
    CorrectionsPanel,
    CostPanel,
    ExecutionPanel,
    FailurePanel,
    FiltersApplied,
    HumanInterventionPanel,
    MetricsErrorResponse,
    MetricsResponse,
    ModelsPanel,
    ResolutionPanel,
    SourcesPanel,
)
from aria.ledger.events import (
    ActorType,
    LedgerEventType,
    LegacyEvolutionRecord,
    LegacyTaskRecord,
)
from aria.ledger.exceptions import MalformedLedgerRecord
from aria.ledger.metrics import LedgerMetrics, MetricsSummary
from aria.ledger.reader import LedgerReader


# ── Environment defaults ──────────────────────────────────────────────────────


_BACKEND_DIR = Path(__file__).parent.parent.parent
_DEFAULT_V2_PATH      = _BACKEND_DIR / "work_ledger_v2.jsonl"
_DEFAULT_LEGACY_TASK  = _BACKEND_DIR / "work_ledger.jsonl"
_DEFAULT_LEGACY_EVO   = _BACKEND_DIR / "evolution_events.jsonl"
_DEFAULT_MAX_RECORDS  = 100_000


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default)))


def _resolve_paths() -> tuple[Path, Path, Path]:
    return (
        _env_path("ARIA_LEDGER_V2_PATH",               _DEFAULT_V2_PATH),
        _env_path("ARIA_LEDGER_LEGACY_TASK_PATH",      _DEFAULT_LEGACY_TASK),
        _env_path("ARIA_LEDGER_LEGACY_EVOLUTION_PATH", _DEFAULT_LEGACY_EVO),
    )


def _resolve_max_records() -> int:
    raw = os.environ.get("ARIA_LEDGER_API_MAX_RECORDS")
    if not raw:
        return _DEFAULT_MAX_RECORDS
    try:
        n = int(raw)
        return n if n > 0 else _DEFAULT_MAX_RECORDS
    except ValueError:
        return _DEFAULT_MAX_RECORDS


# ── Error helper ──────────────────────────────────────────────────────────────


def _error(
    status_code: int,
    code: str,
    *,
    client_detail: Optional[str] = None,
    server_detail: Optional[str] = None,
    exc: Optional[BaseException] = None,
) -> JSONResponse:
    """
    Build a typed error response.

    ``client_detail`` is what the browser sees. When omitted the stable
    sanitised message for ``code`` is used. Raw exception text is NEVER
    placed in the client payload — it goes to the server log via
    ``server_detail`` / ``exc``.
    """
    safe = client_detail or _GENERIC_CLIENT_MESSAGES.get(code, "Ledger error.")
    if server_detail or exc is not None:
        _log.error(
            "Ledger API %s: %s",
            code,
            server_detail or repr(exc),
            exc_info=exc is not None,
        )
    body = MetricsErrorResponse(error_code=code, detail=safe).model_dump()
    return JSONResponse(status_code=status_code, content=body)


# ── Filter parsing ────────────────────────────────────────────────────────────


def _parse_iso8601(s: str) -> datetime:
    """Strict UTC ISO-8601. Rejects naive datetimes."""
    parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone (e.g. '+00:00' or 'Z').")
    return parsed.astimezone(timezone.utc)


def _validate_actor_type(value: str) -> ActorType:
    try:
        return ActorType(value)
    except ValueError as exc:
        raise ValueError(
            f"actor_type {value!r} not one of "
            f"{sorted(at.value for at in ActorType)}"
        ) from exc


# ── Record filtering ──────────────────────────────────────────────────────────


def _record_timestamp(record) -> Optional[datetime]:
    """Return the timestamp on a v2 event or legacy record. None for malformed."""
    ts = getattr(record, "timestamp", None)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    return None


def _record_actor_type(record) -> Optional[str]:
    at = getattr(record, "actor_type", None)
    if at is None:
        return None
    return at.value if hasattr(at, "value") else str(at)


def _legacy_evolution_iso_to_datetime(r) -> Optional[datetime]:
    ts = getattr(r, "timestamp", None)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def _task_anchor_timestamp(events_for_task: list) -> Optional[datetime]:
    """
    Anchor timestamp for date filtering, evaluated PER task:

      1. ``TaskCreated.timestamp`` when present (the canonical lifecycle
         start).
      2. otherwise the EARLIEST event timestamp for the task.

    This is the timestamp the date filter compares against. Picking the
    same anchor for every metric ensures that a task either survives the
    date filter with ITS WHOLE LIFECYCLE intact, or is fully excluded —
    never partially present, never producing an Approved without its
    TaskCreated.
    """
    if not events_for_task:
        return None
    for e in events_for_task:
        if getattr(e, "event_type", None) == LedgerEventType.task_created:
            return _record_timestamp(e)
    timestamps = [_record_timestamp(e) for e in events_for_task]
    timestamps = [t for t in timestamps if t is not None]
    return min(timestamps) if timestamps else None


def _filter_records(
    records: Iterable,
    *,
    start_date: Optional[datetime],
    end_date:   Optional[datetime],
    skill:      Optional[str],
    actor_type: Optional[ActorType],
    workflow_id: Optional[str],
) -> list:
    """
    Apply query filters to the raw record stream.

    Lifecycle-safe semantics
    ------------------------
    Every filter that is task-scoped (date, skill, actor_type,
    workflow_id) is implemented in TWO passes:

      1. **Selection pass** — compute the set of v2 task_ids that
         match the filter, using whatever per-task signal makes
         sense (anchor timestamp for date; matching SkillInvoked
         for skill; any event with matching actor_type / workflow_id).
      2. **Retention pass** — keep every v2 event whose ``task_id``
         is in the selected set. This guarantees a surviving task
         has its WHOLE LIFECYCLE intact — TaskCreated, SkillInvoked,
         the verdict, the cost record, and the terminal event. The
         metrics aggregator then sees consistent task histories and
         cannot produce contradictions like "approval_rate=1.0 with
         completed=0".

    Legacy records
    --------------
    Legacy task records are filtered individually (they ARE one task)
    using ``LegacyTaskRecord.timestamp`` for date and ``task_type`` for
    skill. They have no actor_type or workflow_id — when those filters
    are set, legacy task records are excluded. Legacy evolution records
    are filtered individually by their own timestamp.

    Malformed records
    -----------------
    ALWAYS pass through every filter so ``sources.malformed_count``
    surfaces the same number regardless of filter selection.
    """
    items = list(records)

    # ── 0. Partition by type so we filter each kind appropriately ──
    def _is_v2(r) -> bool:
        return (
            not isinstance(r, MalformedLedgerRecord)
            and not isinstance(r, LegacyTaskRecord)
            and not isinstance(r, LegacyEvolutionRecord)
        )

    v2_events = [r for r in items if _is_v2(r)]
    legacy_tasks = [r for r in items if isinstance(r, LegacyTaskRecord)]
    legacy_evos  = [r for r in items if isinstance(r, LegacyEvolutionRecord)]
    malformed    = [r for r in items if isinstance(r, MalformedLedgerRecord)]

    # Index v2 events by task_id so per-task selection is one pass.
    v2_by_task: dict[str, list] = {}
    for e in v2_events:
        v2_by_task.setdefault(getattr(e, "task_id", ""), []).append(e)

    # ── 1. Build the set of selected v2 task_ids ──
    # Initially all tasks pass. Each filter intersects.
    selected_task_ids: set[str] = set(v2_by_task.keys())

    if start_date is not None or end_date is not None:
        in_range: set[str] = set()
        for tid, events in v2_by_task.items():
            anchor = _task_anchor_timestamp(events)
            if anchor is None:
                continue
            if start_date is not None and anchor < start_date:
                continue
            if end_date is not None and anchor > end_date:
                continue
            in_range.add(tid)
        selected_task_ids &= in_range

    if skill is not None:
        skill_tasks: set[str] = set()
        for tid, events in v2_by_task.items():
            for e in events:
                if (getattr(e, "event_type", None) == LedgerEventType.skill_invoked
                        and getattr(e, "skill_name", None) == skill):
                    skill_tasks.add(tid)
                    break
        selected_task_ids &= skill_tasks

    if actor_type is not None:
        at_tasks: set[str] = set()
        for tid, events in v2_by_task.items():
            for e in events:
                if _record_actor_type(e) == actor_type.value:
                    at_tasks.add(tid)
                    break
        selected_task_ids &= at_tasks

    if workflow_id is not None:
        wf_tasks: set[str] = set()
        for tid, events in v2_by_task.items():
            for e in events:
                if getattr(e, "workflow_id", None) == workflow_id:
                    wf_tasks.add(tid)
                    break
        selected_task_ids &= wf_tasks

    # ── 2. Retain WHOLE lifecycles for selected v2 tasks ──
    kept_v2: list = []
    for tid in selected_task_ids:
        kept_v2.extend(v2_by_task[tid])

    # ── 3. Legacy task records (one record == one task; filter directly) ──
    kept_legacy_tasks: list = []
    for lr in legacy_tasks:
        # date
        if start_date is not None or end_date is not None:
            ts = _record_timestamp(lr)
            if ts is None:
                continue
            if start_date is not None and ts < start_date:
                continue
            if end_date is not None and ts > end_date:
                continue
        # skill
        if skill is not None and lr.task_type != skill:
            continue
        # actor_type — legacy records have none; excluded when set
        if actor_type is not None:
            continue
        # workflow_id — legacy records have none; excluded when set
        if workflow_id is not None:
            continue
        kept_legacy_tasks.append(lr)

    # ── 4. Legacy evolution records (filtered individually by ts) ──
    kept_legacy_evos: list = []
    for le in legacy_evos:
        if start_date is not None or end_date is not None:
            ts = _legacy_evolution_iso_to_datetime(le)
            if ts is None:
                continue
            if start_date is not None and ts < start_date:
                continue
            if end_date is not None and ts > end_date:
                continue
        # legacy evolution has no skill/actor_type/workflow_id concept
        if skill is not None or actor_type is not None or workflow_id is not None:
            continue
        kept_legacy_evos.append(le)

    # ── 5. Malformed records pass through every filter ──
    return kept_v2 + kept_legacy_tasks + kept_legacy_evos + malformed


# ── MetricsSummary → MetricsResponse ──────────────────────────────────────────


def _summary_to_response(
    summary: MetricsSummary, filters: FiltersApplied,
) -> MetricsResponse:
    return MetricsResponse(
        filters_applied=filters,
        execution=ExecutionPanel(
            total_tasks_completed=summary.total_tasks_completed,
            tasks_by_skill=summary.tasks_by_skill,
        ),
        approval=ApprovalPanel(
            approval_rate=summary.approval_rate,
            approvals_granted=summary.approvals_granted,
            approvals_rejected=summary.approvals_rejected,
            approval_rate_by_skill=summary.approval_rate_by_skill,
        ),
        failure=FailurePanel(
            failure_rate=summary.failure_rate,
            failed_tasks=summary.failed_tasks,
            terminal_tasks=summary.terminal_tasks,
            failure_rate_by_skill=summary.failure_rate_by_skill,
        ),
        resolution=ResolutionPanel(
            avg_time_to_resolution_ms=summary.avg_time_to_resolution_ms,
        ),
        cost=CostPanel(
            estimated_cost_total=summary.estimated_cost_total,
            estimated_cost_per_task=summary.estimated_cost_per_task,
            tasks_with_cost=summary.tasks_with_cost,
        ),
        human_intervention=HumanInterventionPanel(rate=summary.human_intervention_rate),
        artifacts=ArtifactsPanel(count=summary.artifact_count),
        corrections=CorrectionsPanel(count=summary.correction_count),
        models=ModelsPanel(usage_breakdown=summary.model_usage_breakdown),
        sources=SourcesPanel(
            v2_event_count=summary.v2_event_count,
            legacy_task_count=summary.legacy_task_count,
            legacy_evolution_count=summary.legacy_evolution_count,
            malformed_count=summary.malformed_count,
        ),
    )


# ── Router ────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/api/v1/ledger", tags=["ledger"])


@router.get("/metrics", responses={
    200: {"model": MetricsResponse},
    400: {"model": MetricsErrorResponse},
    413: {"model": MetricsErrorResponse},
    503: {"model": MetricsErrorResponse},
})
def get_ledger_metrics(
    start_date:  Optional[str] = Query(None, description="ISO-8601 UTC inclusive lower bound"),
    end_date:    Optional[str] = Query(None, description="ISO-8601 UTC inclusive upper bound"),
    skill:       Optional[str] = Query(None, description="Restrict to tasks whose canonical skill matches"),
    actor_type:  Optional[str] = Query(None, description="Restrict to events with matching actor_type"),
    workflow_id: Optional[str] = Query(None, description="Restrict to events with matching workflow_id"),
):
    """
    Return ROI metrics for the configured ledger sources.

    The endpoint NEVER coerces operational failures (config, IO,
    permission) into ``malformed_count`` — those return HTTP 5xx
    with a typed ``MetricsErrorResponse``. Only individual JSONL lines
    that fail to parse contribute to ``malformed_count``.
    """
    # ── 1. Parse filters ──
    # Filter-validation messages are intentionally surfaced to the
    # client because they describe what the CLIENT sent (e.g. bad
    # date format, unknown actor_type). They cannot leak system
    # internals.
    try:
        start_dt = _parse_iso8601(start_date) if start_date else None
        end_dt   = _parse_iso8601(end_date)   if end_date   else None
        at_enum  = _validate_actor_type(actor_type) if actor_type else None
    except ValueError as exc:
        return _error(400, "invalid_filter", client_detail=str(exc))

    if start_dt and end_dt and start_dt > end_dt:
        return _error(400, "invalid_filter",
                       client_detail="start_date must be on or before end_date")

    # ── 2. Resolve paths — generic detail to client; exc to log ──
    try:
        v2_path, legacy_task_path, legacy_evo_path = _resolve_paths()
    except Exception as exc:
        return _error(503, "config_error", exc=exc)

    # ── 3. Read records, catching FS / permission errors as 503 ──
    try:
        reader = LedgerReader(
            v2_path=v2_path,
            legacy_task_path=legacy_task_path,
            legacy_evolution_path=legacy_evo_path,
        )
        all_records = []
        max_records = _resolve_max_records()
        for r in reader.iter_all():
            all_records.append(r)
            if len(all_records) > max_records:
                return _error(
                    413, "oversized_ledger",
                    client_detail=(
                        f"Ledger record count exceeds the configured cap "
                        f"({max_records}). Narrow the date range or raise "
                        "ARIA_LEDGER_API_MAX_RECORDS."
                    ),
                )
    except PermissionError as exc:
        return _error(503, "filesystem_error", exc=exc)
    except OSError as exc:
        return _error(503, "filesystem_error", exc=exc)
    except Exception as exc:  # pragma: no cover - defensive
        return _error(503, "unexpected", exc=exc)

    # ── 4. Apply filters ──
    try:
        filtered = _filter_records(
            all_records,
            start_date=start_dt, end_date=end_dt,
            skill=skill, actor_type=at_enum, workflow_id=workflow_id,
        )
    except Exception as exc:  # pragma: no cover - filter logic is total
        return _error(503, "unexpected", exc=exc)

    # ── 5. Aggregate via the single metrics authority ──
    summary = LedgerMetrics(filtered, include_legacy_tasks=True).summary()

    filters = FiltersApplied(
        start_date=start_date,
        end_date=end_date,
        skill=skill,
        actor_type=actor_type,
        workflow_id=workflow_id,
    )
    return _summary_to_response(summary, filters)
