"""
SQLite Goal / Roadmap / Task store (V3.1 — Goal Ownership Foundation).

The authoritative V3.1 planning store. Same discipline as the V2 domain-memory and
workspace stores:
  - confined to ``${ARIA_DATA_DIR}/goals/store.sqlite`` (gitignored, never inside
    the importable ``aria`` source package);
  - **no import-time DB creation** — the schema is built lazily on first use;
  - restart-safe;
  - every state transition emits a Work Ledger planning event through a
    transactional **audit outbox**, so goal state and its audit can never diverge.

Planning layer ONLY: nothing here executes a tool, runs a workflow, or writes to
any external system. Moving a task changes a planning status, nothing else.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.goals.audit import build_goal_event
from aria.goals.sanitize import sanitize_goal_intake, sanitize_text
from aria.goals.models import (
    ClarificationRequest,
    Deliverable,
    ExecutionOutcome,
    ExecutionStep,
    GoalIntake,
    GoalProgress,
    GoalStatus,
    OwnerType,
    Priority,
    Roadmap,
    RoadmapPhase,
    TaskItem,
    TaskStatus,
)
from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.paths import ensure_confined, goals_db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goal (
    goal_id              TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    raw_request          TEXT NOT NULL,
    problem_statement    TEXT NOT NULL,
    goal                 TEXT NOT NULL,
    success_criteria     TEXT NOT NULL DEFAULT '[]',
    known_context        TEXT NOT NULL DEFAULT '[]',
    missing_context      TEXT NOT NULL DEFAULT '[]',
    clarifying_questions TEXT NOT NULL DEFAULT '[]',
    constraints          TEXT NOT NULL DEFAULT '[]',
    stakeholders         TEXT NOT NULL DEFAULT '[]',
    scope                TEXT NOT NULL,
    risk_level           TEXT NOT NULL DEFAULT 'low',
    status               TEXT NOT NULL DEFAULT 'intake',
    workspace_id         TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roadmap (
    roadmap_id      TEXT PRIMARY KEY,
    goal_id         TEXT NOT NULL,
    phases          TEXT NOT NULL DEFAULT '[]',
    milestones      TEXT NOT NULL DEFAULT '[]',
    dependencies    TEXT NOT NULL DEFAULT '[]',
    risks           TEXT NOT NULL DEFAULT '[]',
    evidence_needed TEXT NOT NULL DEFAULT '[]',
    deliverables    TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_roadmap_goal ON roadmap(goal_id);
CREATE TABLE IF NOT EXISTS task_item (
    task_id           TEXT PRIMARY KEY,
    goal_id           TEXT NOT NULL,
    roadmap_id        TEXT,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'planned',
    priority          TEXT NOT NULL DEFAULT 'medium',
    owner_type        TEXT NOT NULL DEFAULT 'aria',
    required_skill    TEXT,
    required_evidence TEXT NOT NULL DEFAULT '[]',
    approval_required INTEGER NOT NULL DEFAULT 0,
    blocked_by        TEXT NOT NULL DEFAULT '[]',
    output_artifact   TEXT,
    ordinal           INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_goal ON task_item(goal_id);
CREATE TABLE IF NOT EXISTS execution_step (
    step_id           TEXT PRIMARY KEY,
    goal_id           TEXT NOT NULL,
    task_id           TEXT,
    workspace_id      TEXT,
    selected_action   TEXT NOT NULL,
    reason            TEXT NOT NULL DEFAULT '',
    required_evidence TEXT NOT NULL DEFAULT '[]',
    approval_required INTEGER NOT NULL DEFAULT 0,
    produced_artifact TEXT,
    status_before     TEXT,
    status_after      TEXT,
    outcome           TEXT NOT NULL,
    safe_user_message TEXT NOT NULL DEFAULT '',
    ordinal           INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_step_goal ON execution_step(goal_id);
CREATE TABLE IF NOT EXISTS clarification (
    clarification_id TEXT PRIMARY KEY,
    goal_id          TEXT NOT NULL,
    task_id          TEXT,
    questions        TEXT NOT NULL DEFAULT '[]',
    answers          TEXT,
    status           TEXT NOT NULL DEFAULT 'open',
    created_at       TEXT NOT NULL,
    answered_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_clarif_goal ON clarification(goal_id);
CREATE TABLE IF NOT EXISTS goal_evidence (
    goal_id      TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    provided_by  TEXT NOT NULL,
    provided_at  TEXT NOT NULL,
    PRIMARY KEY (goal_id, evidence_ref)
);
CREATE TABLE IF NOT EXISTS deliverable (
    deliverable_id TEXT PRIMARY KEY,
    goal_id        TEXT NOT NULL,
    task_id        TEXT,
    kind           TEXT NOT NULL,
    title          TEXT NOT NULL,
    artifact_ref   TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deliverable_goal ON deliverable(goal_id);
CREATE TABLE IF NOT EXISTS audit_outbox (
    outbox_id   TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    event_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    flushed_at  TEXT
);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class GoalNotFound(ValueError):
    """A goal_id did not resolve to a stored goal."""


class TaskNotFound(ValueError):
    """A task_id did not resolve to a stored task."""


class GoalStore:
    """SQLite-backed planning store for goals / roadmaps / tasks."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        writer: Any = None,
        execution_mode: str | None = None,
    ) -> None:
        resolved = Path(db_path) if db_path is not None else goals_db_path()
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
        event = build_goal_event(event_type, **fields)
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
        """Drain pending audit events to the Work Ledger in insertion order. On the
        first append failure it STOPS, leaving that and later events durably queued
        (so a transient ledger outage never loses or reorders audit)."""
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
                conn.execute(
                    "UPDATE audit_outbox SET flushed_at=? WHERE outbox_id=?",
                    (_iso(_now()), row["outbox_id"]),
                )
            flushed += 1
        return flushed

    def pending_audit_count(self) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS c FROM audit_outbox WHERE flushed_at IS NULL"
        ).fetchone()
        return int(row["c"])

    # ── Goals ────────────────────────────────────────────────────────────────

    def create_goal(self, intake: GoalIntake, *, actor: str = "aria") -> GoalIntake:
        """Persist a goal intake and emit goal_created + problem_statement_generated
        in ONE transaction (state + audit atomic).

        SECURITY (P1): goal text is sanitised HERE, at the persistence boundary, so
        a secret in the request never reaches SQLite or workspace artifacts — and a
        direct store caller passing a hand-built secret-bearing GoalIntake cannot
        bypass it. Sanitisation is idempotent (intake may already be clean)."""
        intake = sanitize_goal_intake(intake)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO goal (goal_id, title, raw_request, problem_statement, goal, "
                "success_criteria, known_context, missing_context, clarifying_questions, "
                "constraints, stakeholders, scope, risk_level, status, workspace_id, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    intake.goal_id, intake.title, intake.raw_request, intake.problem_statement,
                    intake.goal, json.dumps(intake.success_criteria),
                    json.dumps(intake.known_context), json.dumps(intake.missing_context),
                    json.dumps(intake.clarifying_questions), json.dumps(intake.constraints),
                    json.dumps(intake.stakeholders), intake.scope, intake.risk_level,
                    intake.status.value, intake.workspace_id,
                    _iso(intake.created_at), _iso(intake.updated_at),
                ),
            )
            base = dict(
                actor=actor, actor_type=ActorType.aria, goal_id=intake.goal_id,
                scope=intake.scope, correlation_id=intake.goal_id, risk_level=intake.risk_level,
            )
            self._enqueue(conn, LedgerEventType.goal_created, task_id=intake.goal_id,
                          outcome="created", **base)
            self._enqueue(conn, LedgerEventType.problem_statement_generated,
                          task_id=intake.goal_id, outcome="generated", **base)
        self.flush_outbox()
        return self.get_goal(intake.goal_id)  # type: ignore[return-value]

    def get_goal(self, goal_id: str) -> GoalIntake | None:
        row = self._connect().execute(
            "SELECT * FROM goal WHERE goal_id=?", (goal_id,)
        ).fetchone()
        return self._row_to_goal(row) if row else None

    def list_goals(
        self, *, status: str | None = None, scope: str | None = None,
    ) -> list[GoalIntake]:
        conn = self._connect()
        clauses, params = [], []
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if scope is not None:
            clauses.append("scope=?")
            params.append(scope)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM goal{where} ORDER BY created_at, goal_id", params
        ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def set_goal_workspace(self, goal_id: str, workspace_id: str) -> GoalIntake:
        return self._update_goal_fields(goal_id, workspace_id=workspace_id)

    def update_goal_status(self, goal_id: str, status: GoalStatus | str) -> GoalIntake:
        status = GoalStatus(status) if not isinstance(status, GoalStatus) else status
        return self._update_goal_fields(goal_id, status=status.value)

    def _update_goal_fields(self, goal_id: str, **fields) -> GoalIntake:
        conn = self._connect()
        if self.get_goal(goal_id) is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        sets = ", ".join(f"{k}=?" for k in fields)
        params = list(fields.values()) + [_iso(_now()), goal_id]
        with conn:
            conn.execute(f"UPDATE goal SET {sets}, updated_at=? WHERE goal_id=?", params)
        return self.get_goal(goal_id)  # type: ignore[return-value]

    # ── Roadmaps ─────────────────────────────────────────────────────────────

    def create_roadmap(self, roadmap: Roadmap, *, actor: str = "aria") -> Roadmap:
        conn = self._connect()
        if self.get_goal(roadmap.goal_id) is None:
            raise GoalNotFound(f"goal {roadmap.goal_id!r} not found")
        with conn:
            conn.execute(
                "INSERT INTO roadmap (roadmap_id, goal_id, phases, milestones, dependencies, "
                "risks, evidence_needed, deliverables, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    roadmap.roadmap_id, roadmap.goal_id,
                    json.dumps([p.model_dump() for p in roadmap.phases]),
                    json.dumps(roadmap.milestones), json.dumps(roadmap.dependencies),
                    json.dumps(roadmap.risks), json.dumps(roadmap.evidence_needed),
                    json.dumps(roadmap.deliverables),
                    _iso(roadmap.created_at), _iso(roadmap.updated_at),
                ),
            )
            self._enqueue(
                conn, LedgerEventType.roadmap_created, task_id=roadmap.roadmap_id,
                actor=actor, actor_type=ActorType.aria, goal_id=roadmap.goal_id,
                roadmap_id=roadmap.roadmap_id, correlation_id=roadmap.goal_id,
                outcome=f"phases={len(roadmap.phases)}",
            )
        self.flush_outbox()
        return self.get_roadmap(roadmap.goal_id)  # type: ignore[return-value]

    def get_roadmap(self, goal_id: str) -> Roadmap | None:
        row = self._connect().execute(
            "SELECT * FROM roadmap WHERE goal_id=? ORDER BY created_at DESC, roadmap_id LIMIT 1",
            (goal_id,),
        ).fetchone()
        return self._row_to_roadmap(row) if row else None

    # ── Tasks ────────────────────────────────────────────────────────────────

    def create_tasks(self, tasks: list[TaskItem], *, actor: str = "aria") -> list[TaskItem]:
        """Persist a task list and emit ONE task_board_created event (atomic)."""
        if not tasks:
            return []
        conn = self._connect()
        goal_id = tasks[0].goal_id
        roadmap_id = tasks[0].roadmap_id
        with conn:
            for ordinal, t in enumerate(tasks):
                conn.execute(
                    "INSERT INTO task_item (task_id, goal_id, roadmap_id, title, description, "
                    "status, priority, owner_type, required_skill, required_evidence, "
                    "approval_required, blocked_by, output_artifact, ordinal, created_at, "
                    "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        t.task_id, t.goal_id, t.roadmap_id, t.title, t.description,
                        t.status.value, t.priority.value, t.owner_type.value, t.required_skill,
                        json.dumps(t.required_evidence), 1 if t.approval_required else 0,
                        json.dumps(t.blocked_by), t.output_artifact, ordinal,
                        _iso(t.created_at), _iso(t.updated_at),
                    ),
                )
            self._enqueue(
                conn, LedgerEventType.task_board_created, task_id=goal_id, actor=actor,
                actor_type=ActorType.aria, goal_id=goal_id, roadmap_id=roadmap_id,
                correlation_id=goal_id, outcome=f"tasks={len(tasks)}",
            )
        self.flush_outbox()
        return self.get_tasks(goal_id)

    def get_tasks(self, goal_id: str) -> list[TaskItem]:
        rows = self._connect().execute(
            "SELECT * FROM task_item WHERE goal_id=? ORDER BY ordinal, created_at, task_id",
            (goal_id,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_task(self, task_id: str) -> TaskItem | None:
        row = self._connect().execute(
            "SELECT * FROM task_item WHERE task_id=?", (task_id,)
        ).fetchone()
        return self._row_to_task(row) if row else None

    def update_task_status(
        self, task_id: str, status: TaskStatus | str, *,
        blocked_by: list[str] | None = None, output_artifact: str | None = None,
        actor: str = "aria",
    ) -> TaskItem:
        status = TaskStatus(status) if not isinstance(status, TaskStatus) else status
        conn = self._connect()
        task = self.get_task(task_id)
        if task is None:
            raise TaskNotFound(f"task {task_id!r} not found")
        new_blocked = blocked_by if blocked_by is not None else task.blocked_by
        new_artifact = output_artifact if output_artifact is not None else task.output_artifact
        now = _now()
        with conn:
            conn.execute(
                "UPDATE task_item SET status=?, blocked_by=?, output_artifact=?, updated_at=? "
                "WHERE task_id=?",
                (status.value, json.dumps(new_blocked), new_artifact, _iso(now), task_id),
            )
            self._enqueue(
                conn, LedgerEventType.task_status_updated, task_id=task_id, actor=actor,
                actor_type=ActorType.aria, goal_id=task.goal_id, roadmap_id=task.roadmap_id,
                task_ref=task_id, correlation_id=task.goal_id, outcome=status.value,
            )
        self.flush_outbox()
        return self.get_task(task_id)  # type: ignore[return-value]

    # ── Progress (computed) ──────────────────────────────────────────────────

    def compute_progress(self, goal_id: str) -> GoalProgress:
        goal = self.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        tasks = self.get_tasks(goal_id)
        completed = sum(1 for t in tasks if t.status is TaskStatus.completed)
        blocked = sum(1 for t in tasks if t.status is TaskStatus.blocked)
        awaiting = sum(1 for t in tasks if t.status is TaskStatus.awaiting_approval)
        cancelled = sum(1 for t in tasks if t.status is TaskStatus.cancelled)
        pending = sum(1 for t in tasks if t.status in (TaskStatus.planned, TaskStatus.in_progress))
        # Next action = first task not yet completed/cancelled.
        nxt = next((t for t in tasks if t.status not in (TaskStatus.completed, TaskStatus.cancelled)), None)
        last_update = max((t.updated_at for t in tasks), default=goal.updated_at)
        return GoalProgress(
            goal_id=goal_id, completed_tasks=completed, pending_tasks=pending,
            blocked_tasks=blocked, awaiting_approval_tasks=awaiting, cancelled_tasks=cancelled,
            total_tasks=len(tasks),
            current_phase=(nxt.title if nxt else "all tasks closed"),
            next_action=(nxt.title if nxt else None),
            last_update=last_update,
            risk_summary=("blocked" if blocked else goal.risk_level),
        )

    def report_progress(self, goal_id: str, *, actor: str = "aria") -> GoalProgress:
        """Compute progress AND emit a goal_progress_reported event."""
        progress = self.compute_progress(goal_id)
        goal = self.get_goal(goal_id)
        conn = self._connect()
        with conn:
            self._enqueue(
                conn, LedgerEventType.goal_progress_reported, task_id=goal_id, actor=actor,
                actor_type=ActorType.aria, goal_id=goal_id, scope=goal.scope if goal else None,
                correlation_id=goal_id,
                outcome=f"completed={progress.completed_tasks}/{progress.total_tasks}",
            )
        self.flush_outbox()
        return progress

    # ── V3.2: execution steps ────────────────────────────────────────────────

    def record_execution_step(
        self, step: ExecutionStep, *, actor: str = "aria", evidence_status: str | None = None,
    ) -> ExecutionStep:
        """Persist an execution step and emit work_step_started + the terminal event
        (work_step_completed | work_step_blocked) in ONE transaction. The stored
        ``safe_user_message`` is sanitised (defence in depth — it is already
        redacted by the service)."""
        conn = self._connect()
        env_task = step.task_id or step.goal_id
        terminal = (
            LedgerEventType.work_step_completed
            if step.outcome is ExecutionOutcome.completed_step
            else LedgerEventType.work_step_blocked
        )
        ordinal = self._next_step_ordinal(step.goal_id)
        safe_msg = sanitize_text(step.safe_user_message) or ""
        with conn:
            conn.execute(
                "INSERT INTO execution_step (step_id, goal_id, task_id, workspace_id, "
                "selected_action, reason, required_evidence, approval_required, produced_artifact, "
                "status_before, status_after, outcome, safe_user_message, ordinal, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    step.step_id, step.goal_id, step.task_id, step.workspace_id,
                    sanitize_text(step.selected_action), sanitize_text(step.reason),
                    json.dumps(step.required_evidence), 1 if step.approval_required else 0,
                    step.produced_artifact, step.status_before, step.status_after,
                    step.outcome.value, safe_msg, ordinal, _iso(step.created_at),
                ),
            )
            base = dict(
                actor=actor, actor_type=ActorType.aria, goal_id=step.goal_id,
                workspace_id=step.workspace_id, task_ref=step.task_id, step_id=step.step_id,
                correlation_id=step.goal_id, approval_required=step.approval_required,
                evidence_status=evidence_status,
            )
            self._enqueue(conn, LedgerEventType.work_step_started, task_id=env_task,
                          outcome="started", **base)
            self._enqueue(conn, terminal, task_id=env_task, outcome=step.outcome.value, **base)
        self.flush_outbox()
        return step

    def _next_step_ordinal(self, goal_id: str) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS c FROM execution_step WHERE goal_id=?", (goal_id,)
        ).fetchone()
        return int(row["c"])

    def get_execution_steps(self, goal_id: str) -> list[ExecutionStep]:
        rows = self._connect().execute(
            "SELECT * FROM execution_step WHERE goal_id=? ORDER BY ordinal, created_at", (goal_id,)
        ).fetchall()
        return [self._row_to_step(r) for r in rows]

    # ── V3.2: clarifications ─────────────────────────────────────────────────

    def create_clarification(
        self, goal_id: str, questions: list[str], *, task_id: str | None = None,
        actor: str = "aria",
    ) -> ClarificationRequest:
        conn = self._connect()
        clar_id = f"clar-{uuid.uuid4().hex}"
        now = _now()
        safe_q = [sanitize_text(q) or "" for q in questions]
        with conn:
            conn.execute(
                "INSERT INTO clarification (clarification_id, goal_id, task_id, questions, answers, "
                "status, created_at, answered_at) VALUES (?,?,?,?,?,?,?,?)",
                (clar_id, goal_id, task_id, json.dumps(safe_q), None, "open", _iso(now), None),
            )
            self._enqueue(
                conn, LedgerEventType.clarification_requested, task_id=task_id or goal_id,
                actor=actor, actor_type=ActorType.aria, goal_id=goal_id, task_ref=task_id,
                correlation_id=goal_id, outcome="clarification_requested",
                evidence_status="missing_context",
            )
        self.flush_outbox()
        return self.get_clarification(clar_id)  # type: ignore[return-value]

    def get_clarification(self, clarification_id: str) -> ClarificationRequest | None:
        row = self._connect().execute(
            "SELECT * FROM clarification WHERE clarification_id=?", (clarification_id,)
        ).fetchone()
        return self._row_to_clarification(row) if row else None

    def list_clarifications(self, goal_id: str, *, status: str | None = None) -> list[ClarificationRequest]:
        conn = self._connect()
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM clarification WHERE goal_id=? AND status=? ORDER BY created_at",
                (goal_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM clarification WHERE goal_id=? ORDER BY created_at", (goal_id,)
            ).fetchall()
        return [self._row_to_clarification(r) for r in rows]

    def answer_clarification(
        self, clarification_id: str, answers: dict[str, str], *, actor: str = "human:local",
    ) -> ClarificationRequest:
        conn = self._connect()
        clar = self.get_clarification(clarification_id)
        if clar is None:
            raise GoalNotFound(f"clarification {clarification_id!r} not found")
        safe_answers = {sanitize_text(k) or "": sanitize_text(v) or "" for k, v in answers.items()}
        now = _now()
        with conn:
            conn.execute(
                "UPDATE clarification SET answers=?, status='answered', answered_at=? "
                "WHERE clarification_id=?",
                (json.dumps(safe_answers), _iso(now), clarification_id),
            )
            # Durable audit in the SAME transaction (answer values are NOT logged —
            # only the clarification_id + actor + answer count).
            self._enqueue(
                conn, LedgerEventType.clarification_answered, task_id=clar.task_id or clar.goal_id,
                actor=actor, actor_type=ActorType.human, goal_id=clar.goal_id, task_ref=clar.task_id,
                clarification_id=clarification_id, correlation_id=clar.goal_id,
                outcome=f"answers={len(safe_answers)}", evidence_status="clarified",
            )
        self.flush_outbox()
        return self.get_clarification(clarification_id)  # type: ignore[return-value]

    # ── V3.2: evidence (human-provided refs; ARIA never fabricates) ──────────

    def provide_evidence(
        self, goal_id: str, evidence_refs: list[str], *, provided_by: str = "human:local",
    ) -> list[str]:
        conn = self._connect()
        now = _iso(_now())
        goal = self.get_goal(goal_id)
        safe_refs = [sanitize_text(ref) or "" for ref in evidence_refs]
        with conn:
            for safe_ref in safe_refs:
                conn.execute(
                    "INSERT OR IGNORE INTO goal_evidence (goal_id, evidence_ref, provided_by, "
                    "provided_at) VALUES (?,?,?,?)",
                    (goal_id, safe_ref, provided_by, now),
                )
            # Durable audit in the SAME transaction (refs are sanitised; actor recorded).
            self._enqueue(
                conn, LedgerEventType.evidence_provided, task_id=goal_id, actor=provided_by,
                actor_type=ActorType.human, goal_id=goal_id, scope=goal.scope if goal else None,
                correlation_id=goal_id, outcome=f"evidence_added={len(safe_refs)}",
                evidence_status="provided", evidence_refs=safe_refs,
            )
        self.flush_outbox()
        return self.list_evidence(goal_id)

    def list_evidence(self, goal_id: str) -> list[str]:
        rows = self._connect().execute(
            "SELECT evidence_ref FROM goal_evidence WHERE goal_id=? ORDER BY evidence_ref", (goal_id,)
        ).fetchall()
        return [r["evidence_ref"] for r in rows]

    # ── V3.2: deliverables ───────────────────────────────────────────────────

    def track_deliverable(
        self, goal_id: str, kind: str, title: str, *, task_id: str | None = None,
        artifact_ref: str | None = None, actor: str = "aria",
    ) -> Deliverable:
        conn = self._connect()
        deliverable_id = f"deliv-{uuid.uuid4().hex}"
        now = _now()
        with conn:
            conn.execute(
                "INSERT INTO deliverable (deliverable_id, goal_id, task_id, kind, title, "
                "artifact_ref, created_at) VALUES (?,?,?,?,?,?,?)",
                (deliverable_id, goal_id, task_id, kind, sanitize_text(title), artifact_ref, _iso(now)),
            )
            self._enqueue(
                conn, LedgerEventType.deliverable_tracked, task_id=task_id or goal_id, actor=actor,
                actor_type=ActorType.aria, goal_id=goal_id, task_ref=task_id, correlation_id=goal_id,
                outcome=kind,
            )
        self.flush_outbox()
        return self.get_deliverable(deliverable_id)  # type: ignore[return-value]

    def get_deliverable(self, deliverable_id: str) -> Deliverable | None:
        row = self._connect().execute(
            "SELECT * FROM deliverable WHERE deliverable_id=?", (deliverable_id,)
        ).fetchone()
        return self._row_to_deliverable(row) if row else None

    def list_deliverables(self, goal_id: str) -> list[Deliverable]:
        rows = self._connect().execute(
            "SELECT * FROM deliverable WHERE goal_id=? ORDER BY created_at, deliverable_id", (goal_id,)
        ).fetchall()
        return [self._row_to_deliverable(r) for r in rows]

    def emit_progress_report(self, goal_id: str, *, outcome: str, actor: str = "aria") -> None:
        """Emit a progress_report_created event for a computed report."""
        goal = self.get_goal(goal_id)
        conn = self._connect()
        with conn:
            self._enqueue(
                conn, LedgerEventType.progress_report_created, task_id=goal_id, actor=actor,
                actor_type=ActorType.aria, goal_id=goal_id, scope=goal.scope if goal else None,
                correlation_id=goal_id, outcome=outcome,
            )
        self.flush_outbox()

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> ExecutionStep:
        return ExecutionStep(
            step_id=row["step_id"], goal_id=row["goal_id"], task_id=row["task_id"],
            workspace_id=row["workspace_id"], selected_action=row["selected_action"],
            reason=row["reason"], required_evidence=json.loads(row["required_evidence"]),
            approval_required=bool(row["approval_required"]), produced_artifact=row["produced_artifact"],
            status_before=row["status_before"], status_after=row["status_after"],
            outcome=ExecutionOutcome(row["outcome"]), safe_user_message=row["safe_user_message"],
            created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_clarification(row: sqlite3.Row) -> ClarificationRequest:
        return ClarificationRequest(
            clarification_id=row["clarification_id"], goal_id=row["goal_id"], task_id=row["task_id"],
            questions=json.loads(row["questions"]),
            answers=json.loads(row["answers"]) if row["answers"] else None,
            status=row["status"], created_at=_parse_dt(row["created_at"]),
            answered_at=_parse_dt(row["answered_at"]),
        )

    @staticmethod
    def _row_to_deliverable(row: sqlite3.Row) -> Deliverable:
        return Deliverable(
            deliverable_id=row["deliverable_id"], goal_id=row["goal_id"], task_id=row["task_id"],
            kind=row["kind"], title=row["title"], artifact_ref=row["artifact_ref"],
            created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_goal(row: sqlite3.Row) -> GoalIntake:
        return GoalIntake(
            goal_id=row["goal_id"], title=row["title"], raw_request=row["raw_request"],
            problem_statement=row["problem_statement"], goal=row["goal"],
            success_criteria=json.loads(row["success_criteria"]),
            known_context=json.loads(row["known_context"]),
            missing_context=json.loads(row["missing_context"]),
            clarifying_questions=json.loads(row["clarifying_questions"]),
            constraints=json.loads(row["constraints"]),
            stakeholders=json.loads(row["stakeholders"]),
            scope=row["scope"], risk_level=row["risk_level"], status=GoalStatus(row["status"]),
            workspace_id=row["workspace_id"],
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_roadmap(row: sqlite3.Row) -> Roadmap:
        return Roadmap(
            roadmap_id=row["roadmap_id"], goal_id=row["goal_id"],
            phases=[RoadmapPhase(**p) for p in json.loads(row["phases"])],
            milestones=json.loads(row["milestones"]), dependencies=json.loads(row["dependencies"]),
            risks=json.loads(row["risks"]), evidence_needed=json.loads(row["evidence_needed"]),
            deliverables=json.loads(row["deliverables"]),
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskItem:
        return TaskItem(
            task_id=row["task_id"], goal_id=row["goal_id"], roadmap_id=row["roadmap_id"],
            title=row["title"], description=row["description"], status=TaskStatus(row["status"]),
            priority=Priority(row["priority"]), owner_type=OwnerType(row["owner_type"]),
            required_skill=row["required_skill"],
            required_evidence=json.loads(row["required_evidence"]),
            approval_required=bool(row["approval_required"]),
            blocked_by=json.loads(row["blocked_by"]), output_artifact=row["output_artifact"],
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )
