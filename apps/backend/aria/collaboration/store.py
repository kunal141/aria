"""
SQLite team-collaboration store (V3.7).

Persists DRAFT-ONLY communication artifacts: collaboration contexts, drafts, and
approval-request drafts. Same discipline as the V2/V3 stores: confined to
``${ARIA_DATA_DIR}/collaboration/store.sqlite`` (gitignored, never inside the
importable ``aria`` source package), no import-time DB creation, lazy schema,
restart-safe, and every state change emits a Work Ledger event through a
transactional **audit outbox** (state + audit can never diverge).

DRAFT-ONLY: nothing here sends, posts, emails, or mutates any external system. Free
text is masked for secrets; structural identifiers / provenance refs that carry a
credential shape are REJECTED (never silently masked, which would corrupt a join
key); a draft with no source reference is rejected (no orphan communication).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.collaboration.audit import build_collaboration_event
from aria.collaboration.models import (
    ApprovalRequestDraft,
    ApprovalRequestStatus,
    Channel,
    CollaborationContext,
    CollaborationDraft,
    DraftStatus,
    DraftType,
)
from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.paths import collaboration_db_path, ensure_confined

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_context (
    context_id       TEXT PRIMARY KEY,
    goal_id          TEXT NOT NULL,
    task_id          TEXT,
    workspace_id     TEXT,
    active_blockers  TEXT NOT NULL DEFAULT '[]',
    recent_progress  TEXT NOT NULL DEFAULT '[]',
    open_questions   TEXT NOT NULL DEFAULT '[]',
    risks            TEXT NOT NULL DEFAULT '[]',
    decisions_needed TEXT NOT NULL DEFAULT '[]',
    relevant_lessons TEXT NOT NULL DEFAULT '[]',
    agent_outputs    TEXT NOT NULL DEFAULT '[]',
    evidence_refs    TEXT NOT NULL DEFAULT '[]',
    memory_refs      TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ctx_goal ON collaboration_context(goal_id);
CREATE TABLE IF NOT EXISTS collaboration_draft (
    draft_id          TEXT PRIMARY KEY,
    draft_type        TEXT NOT NULL,
    title             TEXT NOT NULL,
    body              TEXT NOT NULL,
    audience          TEXT NOT NULL DEFAULT 'manager',
    channel           TEXT NOT NULL DEFAULT 'internal_note',
    goal_id           TEXT,
    task_id           TEXT,
    workspace_id      TEXT,
    source_refs       TEXT NOT NULL DEFAULT '[]',
    evidence_refs     TEXT NOT NULL DEFAULT '[]',
    memory_refs       TEXT NOT NULL DEFAULT '[]',
    approval_required INTEGER NOT NULL DEFAULT 1,
    status            TEXT NOT NULL DEFAULT 'draft',
    created_by        TEXT NOT NULL DEFAULT 'aria',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_draft_goal ON collaboration_draft(goal_id);
CREATE INDEX IF NOT EXISTS idx_draft_status ON collaboration_draft(status);
CREATE TABLE IF NOT EXISTS approval_request_draft (
    approval_request_id TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    reason              TEXT NOT NULL,
    requested_decision  TEXT NOT NULL DEFAULT '',
    options             TEXT NOT NULL DEFAULT '[]',
    recommended_option  TEXT NOT NULL DEFAULT '',
    risk_level          TEXT NOT NULL DEFAULT 'low',
    evidence_refs       TEXT NOT NULL DEFAULT '[]',
    source_refs         TEXT NOT NULL DEFAULT '[]',
    draft_id            TEXT,
    status              TEXT NOT NULL DEFAULT 'draft',
    created_at          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_outbox (
    outbox_id   TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    event_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    flushed_at  TEXT
);
"""

# A specialized draft type emits its own event; everything else is a generic draft.
_DRAFT_EVENT = {
    DraftType.handoff_note: LedgerEventType.handoff_note_created,
    DraftType.stakeholder_question: LedgerEventType.stakeholder_question_created,
    DraftType.risk_escalation: LedgerEventType.risk_escalation_drafted,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


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


class CollaborationNotFound(ValueError):
    """A draft / context / approval-request id did not resolve."""


class CollaborationSecurityError(ValueError):
    """A structural identifier / provenance ref carries a credential-shaped value.
    Rejected at the persistence boundary — never masked (masking would corrupt a
    join key)."""


class CollaborationIntegrityError(ValueError):
    """A draft violates the source-cited discipline (no source reference at all)."""


def _guard_ids(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None and _has_secret(str(value)):
            raise CollaborationSecurityError(
                f"structural identifier {name!r} carries a credential-shaped value")


def _guard_id_lists(**fields: list[str] | None) -> None:
    for name, values in fields.items():
        for v in values or []:
            if _has_secret(str(v)):
                raise CollaborationSecurityError(
                    f"structural identifier list {name!r} carries a credential-shaped value")


class CollaborationStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None,
                 execution_mode: str | None = None) -> None:
        resolved = Path(db_path) if db_path is not None else collaboration_db_path()
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
        event = build_collaboration_event(event_type, **fields)
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

    # ── Contexts ─────────────────────────────────────────────────────────────

    def create_context(self, c: CollaborationContext, *, actor: str = "aria") -> CollaborationContext:
        _guard_ids(context_id=c.context_id, goal_id=c.goal_id, task_id=c.task_id,
                   workspace_id=c.workspace_id)
        _guard_id_lists(evidence_refs=c.evidence_refs, memory_refs=c.memory_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO collaboration_context (context_id, goal_id, task_id, workspace_id, "
                "active_blockers, recent_progress, open_questions, risks, decisions_needed, "
                "relevant_lessons, agent_outputs, evidence_refs, memory_refs, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    c.context_id, c.goal_id, c.task_id, c.workspace_id,
                    _slist(c.active_blockers), _slist(c.recent_progress), _slist(c.open_questions),
                    _slist(c.risks), _slist(c.decisions_needed), _slist(c.relevant_lessons),
                    _slist(c.agent_outputs), _jlist(c.evidence_refs), _jlist(c.memory_refs),
                    _iso(c.created_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.collaboration_context_created, task_id=c.context_id,
                          actor=actor, actor_type=ActorType.aria, context_id=c.context_id,
                          goal_id=c.goal_id, task_ref=c.task_id, workspace_id=c.workspace_id,
                          correlation_id=c.goal_id or c.context_id, outcome="context_assembled")
        self.flush_outbox()
        return self.get_context(c.context_id)  # type: ignore[return-value]

    def get_context(self, context_id: str) -> CollaborationContext | None:
        row = self._connect().execute("SELECT * FROM collaboration_context WHERE context_id=?",
                                      (context_id,)).fetchone()
        return self._row_to_context(row) if row else None

    def list_contexts(self, *, goal_id: str | None = None) -> list[CollaborationContext]:
        conn = self._connect()
        if goal_id is not None:
            rows = conn.execute("SELECT * FROM collaboration_context WHERE goal_id=? "
                               "ORDER BY created_at, context_id", (goal_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM collaboration_context ORDER BY created_at, "
                               "context_id").fetchall()
        return [self._row_to_context(r) for r in rows]

    # ── Drafts ───────────────────────────────────────────────────────────────

    def create_draft(self, d: CollaborationDraft, *, actor: str = "aria") -> CollaborationDraft:
        # Source-cited discipline: a draft must reference what it was built from.
        if not d.source_refs:
            raise CollaborationIntegrityError(
                "a collaboration draft must cite at least one source reference")
        _guard_ids(draft_id=d.draft_id, goal_id=d.goal_id, task_id=d.task_id,
                   workspace_id=d.workspace_id)
        _guard_id_lists(source_refs=d.source_refs, evidence_refs=d.evidence_refs,
                        memory_refs=d.memory_refs)
        conn = self._connect()
        event_type = _DRAFT_EVENT.get(d.draft_type, LedgerEventType.collaboration_draft_created)
        with conn:
            conn.execute(
                "INSERT INTO collaboration_draft (draft_id, draft_type, title, body, audience, "
                "channel, goal_id, task_id, workspace_id, source_refs, evidence_refs, memory_refs, "
                "approval_required, status, created_by, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    d.draft_id, d.draft_type.value, sanitize_text(d.title), sanitize_text(d.body),
                    sanitize_text(d.audience), d.channel.value, d.goal_id, d.task_id, d.workspace_id,
                    _jlist(d.source_refs), _jlist(d.evidence_refs), _jlist(d.memory_refs),
                    1 if d.approval_required else 0, d.status.value, sanitize_text(d.created_by),
                    _iso(d.created_at), _iso(d.updated_at),
                ),
            )
            self._enqueue(conn, event_type, task_id=d.draft_id, actor=actor,
                          actor_type=ActorType.aria, draft_id=d.draft_id,
                          draft_type=d.draft_type.value, goal_id=d.goal_id, task_ref=d.task_id,
                          workspace_id=d.workspace_id, status=d.status.value,
                          source_refs=list(d.source_refs),
                          correlation_id=d.goal_id or d.draft_id, outcome="drafted")
        self.flush_outbox()
        return self.get_draft(d.draft_id)  # type: ignore[return-value]

    def get_draft(self, draft_id: str) -> CollaborationDraft | None:
        row = self._connect().execute("SELECT * FROM collaboration_draft WHERE draft_id=?",
                                      (draft_id,)).fetchone()
        return self._row_to_draft(row) if row else None

    def list_drafts(self, *, goal_id: str | None = None, status: str | None = None,
                    draft_type: str | None = None) -> list[CollaborationDraft]:
        conn = self._connect()
        clauses, params = [], []
        if goal_id is not None:
            clauses.append("goal_id=?"); params.append(goal_id)
        if status is not None:
            clauses.append("status=?"); params.append(status)
        if draft_type is not None:
            clauses.append("draft_type=?"); params.append(draft_type)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM collaboration_draft{where} ORDER BY created_at, draft_id",
                            params).fetchall()
        return [self._row_to_draft(r) for r in rows]

    def update_draft_status(self, draft_id: str, *, status: DraftStatus, actor: str = "aria"
                            ) -> CollaborationDraft:
        conn = self._connect()
        d = self.get_draft(draft_id)
        if d is None:
            raise CollaborationNotFound(f"draft {draft_id!r} not found")
        with conn:
            conn.execute("UPDATE collaboration_draft SET status=?, updated_at=? WHERE draft_id=?",
                         (status.value, _iso(_now()), draft_id))
            self._enqueue(conn, LedgerEventType.collaboration_draft_updated, task_id=draft_id,
                          actor=actor, actor_type=ActorType.aria, draft_id=draft_id,
                          draft_type=d.draft_type.value, goal_id=d.goal_id, task_ref=d.task_id,
                          workspace_id=d.workspace_id, status=status.value,
                          correlation_id=d.goal_id or draft_id, outcome=status.value)
        self.flush_outbox()
        return self.get_draft(draft_id)  # type: ignore[return-value]

    # ── Approval requests ────────────────────────────────────────────────────

    def create_approval_request(self, a: ApprovalRequestDraft, *, actor: str = "aria",
                                goal_id: str | None = None, workspace_id: str | None = None
                                ) -> ApprovalRequestDraft:
        # An approval request is a GOVERNANCE artifact: it must cite both what it was
        # built from (source) AND the evidence basis for the decision. No orphan /
        # evidence-less approval request may exist, even on a direct store call. These
        # checks run BEFORE any DB work, so a rejected request leaves no SQLite/WAL/
        # ledger residue.
        if not a.source_refs:
            raise CollaborationIntegrityError(
                "an approval-request draft must cite at least one source reference")
        if not a.evidence_refs:
            raise CollaborationIntegrityError(
                "an approval-request draft must cite an evidence basis (no evidence-less "
                "approval request)")
        _guard_ids(approval_request_id=a.approval_request_id, draft_id=a.draft_id)
        _guard_id_lists(evidence_refs=a.evidence_refs, source_refs=a.source_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO approval_request_draft (approval_request_id, title, reason, "
                "requested_decision, options, recommended_option, risk_level, evidence_refs, "
                "source_refs, draft_id, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    a.approval_request_id, sanitize_text(a.title), sanitize_text(a.reason),
                    sanitize_text(a.requested_decision), _slist(a.options),
                    sanitize_text(a.recommended_option), a.risk_level, _jlist(a.evidence_refs),
                    _jlist(a.source_refs), a.draft_id, a.status.value, _iso(a.created_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.approval_request_drafted,
                          task_id=a.approval_request_id, actor=actor, actor_type=ActorType.aria,
                          approval_request_id=a.approval_request_id, draft_id=a.draft_id,
                          goal_id=goal_id, workspace_id=workspace_id, status=a.status.value,
                          source_refs=list(a.source_refs), risk_level=a.risk_level,
                          correlation_id=goal_id or a.approval_request_id, outcome="approval_requested")
        self.flush_outbox()
        return self.get_approval_request(a.approval_request_id)  # type: ignore[return-value]

    def get_approval_request(self, approval_request_id: str) -> ApprovalRequestDraft | None:
        row = self._connect().execute(
            "SELECT * FROM approval_request_draft WHERE approval_request_id=?",
            (approval_request_id,)).fetchone()
        return self._row_to_approval(row) if row else None

    def list_approval_requests(self) -> list[ApprovalRequestDraft]:
        rows = self._connect().execute(
            "SELECT * FROM approval_request_draft ORDER BY created_at, approval_request_id").fetchall()
        return [self._row_to_approval(r) for r in rows]

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_context(row: sqlite3.Row) -> CollaborationContext:
        return CollaborationContext(
            context_id=row["context_id"], goal_id=row["goal_id"], task_id=row["task_id"],
            workspace_id=row["workspace_id"], active_blockers=json.loads(row["active_blockers"]),
            recent_progress=json.loads(row["recent_progress"]),
            open_questions=json.loads(row["open_questions"]), risks=json.loads(row["risks"]),
            decisions_needed=json.loads(row["decisions_needed"]),
            relevant_lessons=json.loads(row["relevant_lessons"]),
            agent_outputs=json.loads(row["agent_outputs"]), evidence_refs=json.loads(row["evidence_refs"]),
            memory_refs=json.loads(row["memory_refs"]), created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_draft(row: sqlite3.Row) -> CollaborationDraft:
        return CollaborationDraft(
            draft_id=row["draft_id"], draft_type=DraftType(row["draft_type"]), title=row["title"],
            body=row["body"], audience=row["audience"], channel=Channel(row["channel"]),
            goal_id=row["goal_id"], task_id=row["task_id"], workspace_id=row["workspace_id"],
            source_refs=json.loads(row["source_refs"]), evidence_refs=json.loads(row["evidence_refs"]),
            memory_refs=json.loads(row["memory_refs"]), approval_required=bool(row["approval_required"]),
            status=DraftStatus(row["status"]), created_by=row["created_by"],
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_approval(row: sqlite3.Row) -> ApprovalRequestDraft:
        return ApprovalRequestDraft(
            approval_request_id=row["approval_request_id"], title=row["title"], reason=row["reason"],
            requested_decision=row["requested_decision"], options=json.loads(row["options"]),
            recommended_option=row["recommended_option"], risk_level=row["risk_level"],
            evidence_refs=json.loads(row["evidence_refs"]), source_refs=json.loads(row["source_refs"]),
            draft_id=row["draft_id"], status=ApprovalRequestStatus(row["status"]),
            created_at=_parse_dt(row["created_at"]),
        )
