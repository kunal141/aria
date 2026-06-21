"""
SQLite scheduled-routines store (V3.8).

Persists routine definitions, runs, and cited outputs. Same discipline as the V2/V3
stores: confined to ``${ARIA_DATA_DIR}/routines/store.sqlite`` (gitignored, never
inside the importable ``aria`` source package), no import-time DB creation, lazy
schema, restart-safe, and every state change emits a Work Ledger event through a
transactional **audit outbox** (state + audit can never diverge).

LOCAL / DETERMINISTIC ONLY: nothing here runs a daemon, browses the web, or performs
an external action. Free text is masked for secrets; structural identifiers /
provenance refs that carry a credential shape are REJECTED (never silently masked); a
routine output with no source reference is rejected (no orphan outputs).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.paths import ensure_confined, routines_db_path
from aria.routines.audit import build_routine_event
from aria.routines.models import (
    Cadence,
    OutputType,
    RoutineDefinition,
    RoutineOutput,
    RoutineRun,
    RoutineType,
    RunStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routine_definition (
    routine_id        TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    routine_type      TEXT NOT NULL,
    cadence           TEXT NOT NULL DEFAULT 'manual',
    interval_hours    INTEGER NOT NULL DEFAULT 24,
    timezone          TEXT NOT NULL DEFAULT 'UTC',
    enabled           INTEGER NOT NULL DEFAULT 1,
    source_scope      TEXT NOT NULL DEFAULT 'internal',
    goal_ids          TEXT NOT NULL DEFAULT '[]',
    workspace_id      TEXT,
    allowed_inputs    TEXT NOT NULL DEFAULT '[]',
    output_policy     TEXT NOT NULL DEFAULT 'draft_only',
    approval_required INTEGER NOT NULL DEFAULT 1,
    last_run_at       TEXT,
    created_by        TEXT NOT NULL DEFAULT 'aria',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_routine_enabled ON routine_definition(enabled);
CREATE TABLE IF NOT EXISTS routine_run (
    run_id          TEXT PRIMARY KEY,
    routine_id      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TEXT,
    completed_at    TEXT,
    due_at          TEXT,
    triggered_by    TEXT NOT NULL DEFAULT 'manual',
    input_refs      TEXT NOT NULL DEFAULT '[]',
    output_refs     TEXT NOT NULL DEFAULT '[]',
    workspace_id    TEXT,
    summary         TEXT NOT NULL DEFAULT '',
    findings        TEXT NOT NULL DEFAULT '[]',
    recommendations TEXT NOT NULL DEFAULT '[]',
    error_code      TEXT,
    safe_error      TEXT,
    ledger_refs     TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_run_routine ON routine_run(routine_id);
CREATE TABLE IF NOT EXISTS routine_output (
    output_id           TEXT PRIMARY KEY,
    routine_id          TEXT NOT NULL,
    run_id              TEXT NOT NULL,
    output_type         TEXT NOT NULL,
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,
    source_refs         TEXT NOT NULL DEFAULT '[]',
    evidence_refs       TEXT NOT NULL DEFAULT '[]',
    memory_refs         TEXT NOT NULL DEFAULT '[]',
    draft_refs          TEXT NOT NULL DEFAULT '[]',
    recommendation_refs TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_output_run ON routine_output(run_id);
CREATE TABLE IF NOT EXISTS audit_outbox (
    outbox_id   TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    event_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    flushed_at  TEXT
);
"""

# Run status → the event emitted when a run reaches it.
_RUN_FINISH_EVENT = {
    RunStatus.completed: LedgerEventType.routine_run_completed,
    RunStatus.failed:    LedgerEventType.routine_run_failed,
    RunStatus.missed:    LedgerEventType.routine_run_missed,
}
# Terminal statuses that advance the cadence window (so the routine is not re-due now).
_ADVANCE_WINDOW = {RunStatus.completed, RunStatus.failed, RunStatus.missed}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _slist(items: list[str]) -> str:
    """Persist a DESCRIPTIVE text list — secrets masked, text stays usable."""
    return json.dumps([sanitize_text(x) or "" for x in items])


def _jlist(items: list[str]) -> str:
    """Persist a STRUCTURAL identifier/reference list verbatim (join keys must not be
    silently redacted). Secrets are rejected upstream by ``_guard_id_lists``."""
    return json.dumps([str(x) for x in items])


def _has_secret(value: str) -> bool:
    return bool(value) and sanitize_text(value) != value


class RoutineNotFound(ValueError):
    """A routine / run / output id did not resolve."""


class RoutineSecurityError(ValueError):
    """A structural identifier / provenance ref carries a credential-shaped value.
    Rejected at the persistence boundary — never masked (masking would corrupt a
    join key)."""


class RoutineIntegrityError(ValueError):
    """A routine output violates the source-cited discipline (no source reference)."""


class RoutineDisabledError(ValueError):
    """A disabled routine cannot run — disabled is an absolute gate."""


def _guard_ids(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None and _has_secret(str(value)):
            raise RoutineSecurityError(
                f"structural identifier {name!r} carries a credential-shaped value")


def _guard_id_lists(**fields: list[str] | None) -> None:
    for name, values in fields.items():
        for v in values or []:
            if _has_secret(str(v)):
                raise RoutineSecurityError(
                    f"structural identifier list {name!r} carries a credential-shaped value")


def _check_output(o: RoutineOutput) -> None:
    """Validate a routine output WITHOUT persisting it: no-orphan source discipline +
    structural-secret rejection. Used to stage/validate all outputs of a run before
    any is persisted, so a malformed output cannot create partial rows."""
    if not o.source_refs:
        raise RoutineIntegrityError("a routine output must cite at least one source reference")
    _guard_ids(output_id=o.output_id, routine_id=o.routine_id, run_id=o.run_id)
    _guard_id_lists(source_refs=o.source_refs, evidence_refs=o.evidence_refs,
                    memory_refs=o.memory_refs, draft_refs=o.draft_refs,
                    recommendation_refs=o.recommendation_refs)


class RoutineStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None,
                 execution_mode: str | None = None) -> None:
        resolved = Path(db_path) if db_path is not None else routines_db_path()
        self._db_path = ensure_confined(resolved)
        self._writer = writer
        self._execution_mode = execution_mode
        self._conn: sqlite3.Connection | None = None

    # ── Connection / schema (lazy — never at import) ─────────────────────────

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── Transactional audit outbox ───────────────────────────────────────────

    def _enqueue(self, conn: sqlite3.Connection, event_type: LedgerEventType, **fields) -> None:
        fields.setdefault("execution_mode", self._execution_mode)
        event = build_routine_event(event_type, **fields)
        conn.execute(
            "INSERT INTO audit_outbox (outbox_id, event_type, event_json, created_at, flushed_at) "
            "VALUES (?,?,?,?,NULL)",
            (f"obx-{uuid.uuid4().hex}", event_type.value, event.model_dump_json(), _iso(_now())),
        )

    def _resolve_writer(self, writer: Any = None):
        if writer is not None:
            return writer
        if self._writer is not None:
            return self._writer
        from aria.ledger.writer import get_default_writer

        return get_default_writer()

    def flush_outbox(self, writer: Any = None) -> int:
        conn = self._connect()
        target = self._resolve_writer(writer)
        rows = conn.execute(
            "SELECT outbox_id, event_json FROM audit_outbox WHERE flushed_at IS NULL ORDER BY rowid"
        ).fetchall()
        flushed = 0
        for row in rows:
            try:
                target.append(json.loads(row["event_json"]))
            except Exception:
                break
            with conn:
                conn.execute("UPDATE audit_outbox SET flushed_at=? WHERE outbox_id=?",
                             (_iso(_now()), row["outbox_id"]))
            flushed += 1
        return flushed

    def pending_audit_count(self) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS c FROM audit_outbox WHERE flushed_at IS NULL").fetchone()
        return int(row["c"])

    # ── Definitions ──────────────────────────────────────────────────────────

    def create_definition(self, d: RoutineDefinition, *, actor: str = "aria") -> RoutineDefinition:
        _guard_ids(routine_id=d.routine_id, workspace_id=d.workspace_id)
        _guard_id_lists(goal_ids=d.goal_ids)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO routine_definition (routine_id, name, description, routine_type, cadence, "
                "interval_hours, timezone, enabled, source_scope, goal_ids, workspace_id, allowed_inputs, "
                "output_policy, approval_required, last_run_at, created_by, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    d.routine_id, sanitize_text(d.name), sanitize_text(d.description),
                    d.routine_type.value, d.cadence.value, d.interval_hours, sanitize_text(d.timezone),
                    1 if d.enabled else 0, sanitize_text(d.source_scope), _jlist(d.goal_ids),
                    d.workspace_id, _slist(d.allowed_inputs), sanitize_text(d.output_policy),
                    1 if d.approval_required else 0, _iso(d.last_run_at), sanitize_text(d.created_by),
                    _iso(d.created_at), _iso(d.updated_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.routine_defined, task_id=d.routine_id, actor=actor,
                          actor_type=ActorType.aria, routine_id=d.routine_id,
                          routine_type=d.routine_type.value, workspace_id=d.workspace_id,
                          goal_id=(d.goal_ids[0] if d.goal_ids else None),
                          correlation_id=d.routine_id, status="enabled" if d.enabled else "disabled",
                          outcome=d.cadence.value)
        self.flush_outbox()
        return self.get_definition(d.routine_id)  # type: ignore[return-value]

    def get_definition(self, routine_id: str) -> RoutineDefinition | None:
        row = self._connect().execute("SELECT * FROM routine_definition WHERE routine_id=?",
                                      (routine_id,)).fetchone()
        return self._row_to_definition(row) if row else None

    def list_definitions(self, *, enabled: bool | None = None,
                         routine_type: str | None = None) -> list[RoutineDefinition]:
        conn = self._connect()
        clauses, params = [], []
        if enabled is not None:
            clauses.append("enabled=?"); params.append(1 if enabled else 0)
        if routine_type is not None:
            clauses.append("routine_type=?"); params.append(routine_type)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM routine_definition{where} ORDER BY created_at, routine_id",
                            params).fetchall()
        return [self._row_to_definition(r) for r in rows]

    def set_enabled(self, routine_id: str, enabled: bool, *, actor: str = "aria") -> RoutineDefinition:
        conn = self._connect()
        d = self.get_definition(routine_id)
        if d is None:
            raise RoutineNotFound(f"routine {routine_id!r} not found")
        event = LedgerEventType.routine_enabled if enabled else LedgerEventType.routine_disabled
        with conn:
            conn.execute("UPDATE routine_definition SET enabled=?, updated_at=? WHERE routine_id=?",
                         (1 if enabled else 0, _iso(_now()), routine_id))
            self._enqueue(conn, event, task_id=routine_id, actor=actor, actor_type=ActorType.aria,
                          routine_id=routine_id, routine_type=d.routine_type.value,
                          workspace_id=d.workspace_id, correlation_id=routine_id,
                          status="enabled" if enabled else "disabled",
                          outcome="enabled" if enabled else "disabled")
        self.flush_outbox()
        return self.get_definition(routine_id)  # type: ignore[return-value]

    def emit_due(self, d: RoutineDefinition, *, due_at: datetime | None, actor: str = "aria") -> None:
        conn = self._connect()
        with conn:
            self._enqueue(conn, LedgerEventType.routine_due, task_id=d.routine_id, actor=actor,
                          actor_type=ActorType.aria, routine_id=d.routine_id,
                          routine_type=d.routine_type.value, workspace_id=d.workspace_id,
                          correlation_id=d.routine_id, status="due",
                          outcome=_iso(due_at) or "due")
        self.flush_outbox()

    def _set_last_run(self, conn: sqlite3.Connection, routine_id: str, when: datetime | None) -> None:
        conn.execute("UPDATE routine_definition SET last_run_at=?, updated_at=? WHERE routine_id=?",
                     (_iso(when), _iso(_now()), routine_id))

    # ── Runs ─────────────────────────────────────────────────────────────────

    def record_run_started(self, r: RoutineRun, *, routine_type: str | None = None,
                          actor: str = "aria") -> RoutineRun:
        _guard_ids(run_id=r.run_id, routine_id=r.routine_id, workspace_id=r.workspace_id)
        _guard_id_lists(input_refs=r.input_refs, output_refs=r.output_refs, ledger_refs=r.ledger_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO routine_run (run_id, routine_id, status, started_at, completed_at, due_at, "
                "triggered_by, input_refs, output_refs, workspace_id, summary, findings, recommendations, "
                "error_code, safe_error, ledger_refs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r.run_id, r.routine_id, r.status.value, _iso(r.started_at), _iso(r.completed_at),
                    _iso(r.due_at), sanitize_text(r.triggered_by), _jlist(r.input_refs),
                    _jlist(r.output_refs), r.workspace_id, sanitize_text(r.summary),
                    _slist(r.findings), _slist(r.recommendations), r.error_code,
                    sanitize_text(r.safe_error), _jlist(r.ledger_refs),
                ),
            )
            self._enqueue(conn, LedgerEventType.routine_run_started, task_id=r.run_id, actor=actor,
                          actor_type=ActorType.aria, routine_id=r.routine_id, run_id=r.run_id,
                          routine_type=routine_type, workspace_id=r.workspace_id,
                          correlation_id=r.routine_id, status=r.status.value, outcome=r.triggered_by)
        self.flush_outbox()
        return self.get_run(r.run_id)  # type: ignore[return-value]

    def record_run_finished(self, r: RoutineRun, *, routine_type: str | None = None,
                           actor: str = "aria") -> RoutineRun:
        _guard_id_lists(input_refs=r.input_refs, output_refs=r.output_refs, ledger_refs=r.ledger_refs)
        conn = self._connect()
        event = _RUN_FINISH_EVENT.get(r.status, LedgerEventType.routine_run_completed)
        with conn:
            conn.execute(
                "UPDATE routine_run SET status=?, completed_at=?, due_at=?, output_refs=?, summary=?, "
                "findings=?, recommendations=?, error_code=?, safe_error=?, ledger_refs=? WHERE run_id=?",
                (
                    r.status.value, _iso(r.completed_at), _iso(r.due_at), _jlist(r.output_refs),
                    sanitize_text(r.summary), _slist(r.findings), _slist(r.recommendations),
                    r.error_code, sanitize_text(r.safe_error), _jlist(r.ledger_refs), r.run_id,
                ),
            )
            if r.status in _ADVANCE_WINDOW:
                self._set_last_run(conn, r.routine_id, r.completed_at or _now())
            self._enqueue(conn, event, task_id=r.run_id, actor=actor, actor_type=ActorType.aria,
                          routine_id=r.routine_id, run_id=r.run_id, routine_type=routine_type,
                          workspace_id=r.workspace_id, correlation_id=r.routine_id,
                          status=r.status.value, safe_error=r.safe_error,
                          risk_level="medium" if r.status is RunStatus.failed else "low",
                          outcome=r.status.value)
        self.flush_outbox()
        return self.get_run(r.run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> RoutineRun | None:
        row = self._connect().execute("SELECT * FROM routine_run WHERE run_id=?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def list_runs(self, *, routine_id: str | None = None, status: str | None = None) -> list[RoutineRun]:
        conn = self._connect()
        clauses, params = [], []
        if routine_id is not None:
            clauses.append("routine_id=?"); params.append(routine_id)
        if status is not None:
            clauses.append("status=?"); params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM routine_run{where} ORDER BY started_at, run_id",
                            params).fetchall()
        return [self._row_to_run(r) for r in rows]

    # ── Outputs ──────────────────────────────────────────────────────────────

    @staticmethod
    def validate_output(o: RoutineOutput) -> None:
        """Pre-persist validation (no-orphan + structural-secret). Raises the same
        errors ``create_output`` would, without touching the DB — so a run can stage
        and validate ALL its outputs before persisting any of them."""
        _check_output(o)

    def create_output(self, o: RoutineOutput, *, actor: str = "aria") -> RoutineOutput:
        # No-orphan + structural-secret discipline (also runnable standalone above).
        _check_output(o)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO routine_output (output_id, routine_id, run_id, output_type, title, body, "
                "source_refs, evidence_refs, memory_refs, draft_refs, recommendation_refs, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    o.output_id, o.routine_id, o.run_id, o.output_type.value, sanitize_text(o.title),
                    sanitize_text(o.body), _jlist(o.source_refs), _jlist(o.evidence_refs),
                    _jlist(o.memory_refs), _jlist(o.draft_refs), _jlist(o.recommendation_refs),
                    _iso(o.created_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.routine_output_created, task_id=o.output_id, actor=actor,
                          actor_type=ActorType.aria, routine_id=o.routine_id, run_id=o.run_id,
                          output_id=o.output_id, correlation_id=o.routine_id, status="created",
                          outcome=o.output_type.value)
        self.flush_outbox()
        return self.get_output(o.output_id)  # type: ignore[return-value]

    def emit_followup(self, *, routine_id: str, run_id: str, draft_id: str, goal_id: str | None = None,
                     workspace_id: str | None = None, actor: str = "aria") -> None:
        conn = self._connect()
        with conn:
            self._enqueue(conn, LedgerEventType.routine_followup_drafted, task_id=run_id, actor=actor,
                          actor_type=ActorType.aria, routine_id=routine_id, run_id=run_id,
                          draft_id=draft_id, goal_id=goal_id, workspace_id=workspace_id,
                          correlation_id=routine_id, status="drafted", outcome="followup_drafted")
        self.flush_outbox()

    def get_output(self, output_id: str) -> RoutineOutput | None:
        row = self._connect().execute("SELECT * FROM routine_output WHERE output_id=?",
                                      (output_id,)).fetchone()
        return self._row_to_output(row) if row else None

    def list_outputs(self, *, run_id: str | None = None,
                    routine_id: str | None = None) -> list[RoutineOutput]:
        conn = self._connect()
        clauses, params = [], []
        if run_id is not None:
            clauses.append("run_id=?"); params.append(run_id)
        if routine_id is not None:
            clauses.append("routine_id=?"); params.append(routine_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM routine_output{where} ORDER BY created_at, output_id",
                            params).fetchall()
        return [self._row_to_output(r) for r in rows]

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_definition(row: sqlite3.Row) -> RoutineDefinition:
        return RoutineDefinition(
            routine_id=row["routine_id"], name=row["name"], description=row["description"],
            routine_type=RoutineType(row["routine_type"]), cadence=Cadence(row["cadence"]),
            interval_hours=row["interval_hours"], timezone=row["timezone"], enabled=bool(row["enabled"]),
            source_scope=row["source_scope"], goal_ids=json.loads(row["goal_ids"]),
            workspace_id=row["workspace_id"], allowed_inputs=json.loads(row["allowed_inputs"]),
            output_policy=row["output_policy"], approval_required=bool(row["approval_required"]),
            last_run_at=_parse_dt(row["last_run_at"]), created_by=row["created_by"],
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RoutineRun:
        return RoutineRun(
            run_id=row["run_id"], routine_id=row["routine_id"], status=RunStatus(row["status"]),
            started_at=_parse_dt(row["started_at"]), completed_at=_parse_dt(row["completed_at"]),
            due_at=_parse_dt(row["due_at"]), triggered_by=row["triggered_by"],
            input_refs=json.loads(row["input_refs"]), output_refs=json.loads(row["output_refs"]),
            workspace_id=row["workspace_id"], summary=row["summary"],
            findings=json.loads(row["findings"]), recommendations=json.loads(row["recommendations"]),
            error_code=row["error_code"], safe_error=row["safe_error"],
            ledger_refs=json.loads(row["ledger_refs"]),
        )

    @staticmethod
    def _row_to_output(row: sqlite3.Row) -> RoutineOutput:
        return RoutineOutput(
            output_id=row["output_id"], routine_id=row["routine_id"], run_id=row["run_id"],
            output_type=OutputType(row["output_type"]), title=row["title"], body=row["body"],
            source_refs=json.loads(row["source_refs"]), evidence_refs=json.loads(row["evidence_refs"]),
            memory_refs=json.loads(row["memory_refs"]), draft_refs=json.loads(row["draft_refs"]),
            recommendation_refs=json.loads(row["recommendation_refs"]),
            created_at=_parse_dt(row["created_at"]),
        )
