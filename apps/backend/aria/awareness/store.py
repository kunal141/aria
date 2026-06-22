"""
SQLite Work-Memory + World-Awareness store (V3.6).

Persists the work-memory graph (nodes/edges/lessons), the world-awareness registry
(sources/updates), and improvement proposals. Same discipline as the other V2/V3
stores: confined to ``${ARIA_DATA_DIR}/awareness/store.sqlite`` (gitignored, never
inside the source package), no import-time DB creation, lazy schema, restart-safe,
and every state transition emits a Work Ledger event through a transactional **audit
outbox** (state + audit can never diverge).

Advisory/contextual ONLY — nothing here approves actions, activates skills, or proves
facts. Secrets are sanitised out of every persisted string (incl. list fields).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.awareness.audit import build_awareness_event
from aria.awareness.models import (
    ImprovementOrigin,
    ImprovementProposal,
    LessonApprovalStatus,
    NodeStatus,
    NodeType,
    RelationType,
    TrustLevel,
    UpdateStatus,
    WorkLesson,
    WorkMemoryEdge,
    WorkMemoryNode,
    WorldSource,
    WorldSourceType,
    WorldUpdate,
)
from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.paths import awareness_db_path, ensure_confined

_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_memory_node (
    node_id       TEXT PRIMARY KEY,
    node_type     TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL,
    source_refs   TEXT NOT NULL DEFAULT '[]',
    goal_ids      TEXT NOT NULL DEFAULT '[]',
    task_ids      TEXT NOT NULL DEFAULT '[]',
    agent_ids     TEXT NOT NULL DEFAULT '[]',
    skill_ids     TEXT NOT NULL DEFAULT '[]',
    workspace_ids TEXT NOT NULL DEFAULT '[]',
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    memory_refs   TEXT NOT NULL DEFAULT '[]',
    confidence    REAL NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_node_type ON work_memory_node(node_type);
CREATE TABLE IF NOT EXISTS work_memory_edge (
    edge_id       TEXT PRIMARY KEY,
    from_node_id  TEXT NOT NULL,
    to_node_id    TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    source_refs   TEXT NOT NULL DEFAULT '[]',
    confidence    REAL NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edge_from ON work_memory_edge(from_node_id);
CREATE TABLE IF NOT EXISTS work_lesson (
    lesson_id         TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    lesson            TEXT NOT NULL,
    applies_to        TEXT NOT NULL DEFAULT '[]',
    source_node_ids   TEXT NOT NULL DEFAULT '[]',
    source_refs       TEXT NOT NULL DEFAULT '[]',
    required_evidence TEXT NOT NULL DEFAULT '[]',
    confidence        REAL NOT NULL DEFAULT 0,
    recommended_use   TEXT NOT NULL DEFAULT '',
    approval_status   TEXT NOT NULL DEFAULT 'pending',
    status            TEXT NOT NULL DEFAULT 'active',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS world_source (
    source_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    url             TEXT NOT NULL DEFAULT '',
    allowed         INTEGER NOT NULL DEFAULT 1,
    trust_level     TEXT NOT NULL DEFAULT 'low',
    topic_tags      TEXT NOT NULL DEFAULT '[]',
    last_checked_at TEXT,
    policy_notes    TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS world_update (
    update_id       TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    published_at    TEXT,
    captured_at     TEXT NOT NULL,
    source_url      TEXT NOT NULL DEFAULT '',
    citations       TEXT NOT NULL DEFAULT '[]',
    topic_tags      TEXT NOT NULL DEFAULT '[]',
    trust_level     TEXT NOT NULL DEFAULT 'low',
    relevance_score REAL NOT NULL DEFAULT 0,
    risk_level      TEXT NOT NULL DEFAULT 'low',
    status          TEXT NOT NULL DEFAULT 'ingested',
    recommendation  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_update_source ON world_update(source_id);
CREATE TABLE IF NOT EXISTS improvement_proposal (
    proposal_id       TEXT PRIMARY KEY,
    origin_type       TEXT NOT NULL,
    origin_ref        TEXT NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL,
    source_refs       TEXT NOT NULL DEFAULT '[]',
    skill_gap_id      TEXT,
    skill_proposal_id TEXT,
    relevance_score   REAL NOT NULL DEFAULT 0,
    risk_level        TEXT NOT NULL DEFAULT 'low',
    status            TEXT NOT NULL DEFAULT 'pending',
    created_at        TEXT NOT NULL
);
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


def _slist(items: list[str]) -> str:
    """Persist a DESCRIPTIVE text list — secrets are masked (the text stays usable)."""
    return json.dumps([sanitize_text(x) or "" for x in items])


def _jlist(items: list[str]) -> str:
    """Persist a STRUCTURAL identifier/reference list verbatim (join keys must not be
    silently redacted). Secrets are rejected upstream by ``_guard_id_lists`` — never
    masked here, so referential meaning is preserved."""
    return json.dumps([str(x) for x in items])


def _has_secret(value: str) -> bool:
    """True iff ``value`` carries a credential shape / secret assignment. Relies on
    the idempotent ``sanitize_text`` (it only changes a string that holds a secret)."""
    return bool(value) and sanitize_text(value) != value


class AwarenessNotFound(ValueError):
    """A node / lesson / source / update id did not resolve."""


class AwarenessSecurityError(ValueError):
    """A STRUCTURAL identifier (id / join-key / provenance ref) carries a credential-
    shaped value. Such records are REJECTED at the persistence boundary — they are
    never masked, because masking a join key would corrupt referential meaning."""


class AwarenessIntegrityError(ValueError):
    """A record violates the source-linked / no-orphan discipline (a node without
    source records, or a lesson without source nodes / evidence)."""


def _guard_ids(**fields: str | None) -> None:
    """Reject any scalar structural identifier that carries a secret shape."""
    for name, value in fields.items():
        if value is not None and _has_secret(str(value)):
            raise AwarenessSecurityError(
                f"structural identifier {name!r} carries a credential-shaped value")


def _guard_id_lists(**fields: list[str] | None) -> None:
    """Reject any structural identifier/reference LIST element that carries a secret."""
    for name, values in fields.items():
        for v in values or []:
            if _has_secret(str(v)):
                raise AwarenessSecurityError(
                    f"structural identifier list {name!r} carries a credential-shaped value")


def _require_nonempty(**fields: list[str]) -> None:
    """Enforce the no-orphan / source-linked discipline at the authority boundary."""
    for name, values in fields.items():
        if not values:
            raise AwarenessIntegrityError(
                f"{name} must be non-empty — no orphan / source-less memory records")


class AwarenessStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None,
                 execution_mode: str | None = None) -> None:
        resolved = Path(db_path) if db_path is not None else awareness_db_path()
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
        event = build_awareness_event(event_type, **fields)
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

    # ── Nodes ────────────────────────────────────────────────────────────────

    def create_node(self, n: WorkMemoryNode, *, actor: str = "aria") -> WorkMemoryNode:
        # No-orphan discipline: a node must cite the records it was distilled from.
        _require_nonempty(source_refs=n.source_refs)
        # Structural identifiers / provenance refs are join keys — reject (never mask).
        _guard_ids(node_id=n.node_id)
        _guard_id_lists(source_refs=n.source_refs, goal_ids=n.goal_ids, task_ids=n.task_ids,
                        agent_ids=n.agent_ids, skill_ids=n.skill_ids, workspace_ids=n.workspace_ids,
                        evidence_refs=n.evidence_refs, memory_refs=n.memory_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO work_memory_node (node_id, node_type, title, summary, source_refs, "
                "goal_ids, task_ids, agent_ids, skill_ids, workspace_ids, evidence_refs, memory_refs, "
                "confidence, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    n.node_id, n.node_type.value, sanitize_text(n.title), sanitize_text(n.summary),
                    _jlist(n.source_refs), _jlist(n.goal_ids), _jlist(n.task_ids), _jlist(n.agent_ids),
                    _jlist(n.skill_ids), _jlist(n.workspace_ids), _jlist(n.evidence_refs),
                    _jlist(n.memory_refs), n.confidence, n.status.value,
                    _iso(n.created_at), _iso(n.updated_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.work_memory_node_created, task_id=n.node_id,
                          actor=actor, actor_type=ActorType.aria, node_id=n.node_id,
                          goal_id=(n.goal_ids[0] if n.goal_ids else None),
                          workspace_id=(n.workspace_ids[0] if n.workspace_ids else None),
                          correlation_id=(n.goal_ids[0] if n.goal_ids else n.node_id),
                          outcome=f"{n.node_type.value};confidence={n.confidence:.2f}")
        self.flush_outbox()
        return self.get_node(n.node_id)  # type: ignore[return-value]

    def get_node(self, node_id: str) -> WorkMemoryNode | None:
        row = self._connect().execute("SELECT * FROM work_memory_node WHERE node_id=?",
                                      (node_id,)).fetchone()
        return self._row_to_node(row) if row else None

    def list_nodes(self, *, node_type: str | None = None, status: str | None = None) -> list[WorkMemoryNode]:
        conn = self._connect()
        clauses, params = [], []
        if node_type is not None:
            clauses.append("node_type=?"); params.append(node_type)
        if status is not None:
            clauses.append("status=?"); params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM work_memory_node{where} ORDER BY created_at, node_id",
                            params).fetchall()
        return [self._row_to_node(r) for r in rows]

    def redact_node(self, node_id: str, *, actor: str = "aria") -> WorkMemoryNode:
        """Redact a node's content while PRESERVING the audit trail (the row + its
        source_refs remain; only the human-readable summary is withheld). The
        redaction is itself a durable, audited state change."""
        conn = self._connect()
        n = self.get_node(node_id)
        if n is None:
            raise AwarenessNotFound(f"node {node_id!r} not found")
        with conn:
            conn.execute(
                "UPDATE work_memory_node SET status=?, summary=?, title=?, updated_at=? WHERE node_id=?",
                (NodeStatus.redacted.value, "[redacted by local policy]", "[redacted]",
                 _iso(_now()), node_id),
            )
            self._enqueue(conn, LedgerEventType.work_memory_node_redacted, task_id=node_id,
                          actor=actor, actor_type=ActorType.aria, node_id=node_id,
                          goal_id=(n.goal_ids[0] if n.goal_ids else None),
                          workspace_id=(n.workspace_ids[0] if n.workspace_ids else None),
                          correlation_id=(n.goal_ids[0] if n.goal_ids else node_id),
                          outcome="redacted")
        self.flush_outbox()
        return self.get_node(node_id)  # type: ignore[return-value]

    # ── Edges ────────────────────────────────────────────────────────────────

    def create_edge(self, e: WorkMemoryEdge, *, actor: str = "aria") -> WorkMemoryEdge:
        # An edge is a provenance record — it must cite the source(s) it derives from.
        _require_nonempty(source_refs=e.source_refs)
        _guard_ids(edge_id=e.edge_id, from_node_id=e.from_node_id, to_node_id=e.to_node_id)
        _guard_id_lists(source_refs=e.source_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO work_memory_edge (edge_id, from_node_id, to_node_id, relation_type, "
                "source_refs, confidence, created_at) VALUES (?,?,?,?,?,?,?)",
                (e.edge_id, e.from_node_id, e.to_node_id, e.relation_type.value,
                 _jlist(e.source_refs), e.confidence, _iso(e.created_at)),
            )
            self._enqueue(conn, LedgerEventType.work_memory_edge_created, task_id=e.edge_id,
                          actor=actor, actor_type=ActorType.aria, edge_id=e.edge_id,
                          node_id=e.from_node_id, correlation_id=e.from_node_id,
                          outcome=e.relation_type.value)
        self.flush_outbox()
        return e

    def list_edges(self, *, from_node_id: str | None = None) -> list[WorkMemoryEdge]:
        conn = self._connect()
        if from_node_id is not None:
            rows = conn.execute("SELECT * FROM work_memory_edge WHERE from_node_id=? ORDER BY created_at",
                               (from_node_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM work_memory_edge ORDER BY created_at").fetchall()
        return [self._row_to_edge(r) for r in rows]

    # ── Lessons ──────────────────────────────────────────────────────────────

    def create_lesson(self, lesson: WorkLesson, *, actor: str = "aria",
                     workspace_id: str | None = None) -> WorkLesson:
        # No-orphan discipline: a lesson must cite source nodes, source records, and
        # the evidence a future user must verify before relying on it.
        _require_nonempty(source_node_ids=lesson.source_node_ids, source_refs=lesson.source_refs,
                          required_evidence=lesson.required_evidence)
        _guard_ids(lesson_id=lesson.lesson_id)
        _guard_id_lists(source_node_ids=lesson.source_node_ids, source_refs=lesson.source_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO work_lesson (lesson_id, title, lesson, applies_to, source_node_ids, "
                "source_refs, required_evidence, confidence, recommended_use, approval_status, status, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lesson.lesson_id, sanitize_text(lesson.title), sanitize_text(lesson.lesson),
                    _slist(lesson.applies_to), _jlist(lesson.source_node_ids),
                    _jlist(lesson.source_refs), _slist(lesson.required_evidence), lesson.confidence,
                    sanitize_text(lesson.recommended_use), lesson.approval_status.value,
                    lesson.status.value, _iso(lesson.created_at), _iso(lesson.updated_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.work_lesson_created, task_id=lesson.lesson_id,
                          actor=actor, actor_type=ActorType.aria, lesson_id=lesson.lesson_id,
                          node_id=(lesson.source_node_ids[0] if lesson.source_node_ids else None),
                          workspace_id=workspace_id, correlation_id=lesson.lesson_id,
                          outcome=f"confidence={lesson.confidence:.2f}")
        self.flush_outbox()
        return self.get_lesson(lesson.lesson_id)  # type: ignore[return-value]

    def get_lesson(self, lesson_id: str) -> WorkLesson | None:
        row = self._connect().execute("SELECT * FROM work_lesson WHERE lesson_id=?",
                                      (lesson_id,)).fetchone()
        return self._row_to_lesson(row) if row else None

    def list_lessons(self, *, usable_only: bool = False) -> list[WorkLesson]:
        rows = self._connect().execute("SELECT * FROM work_lesson ORDER BY created_at, lesson_id").fetchall()
        lessons = [self._row_to_lesson(r) for r in rows]
        return [l for l in lessons if l.is_usable] if usable_only else lessons

    def set_lesson_status(self, lesson_id: str, *, approval_status: LessonApprovalStatus,
                         status: NodeStatus, event: LedgerEventType, actor: str = "aria",
                         workspace_id: str | None = None) -> WorkLesson:
        conn = self._connect()
        lesson = self.get_lesson(lesson_id)
        if lesson is None:
            raise AwarenessNotFound(f"lesson {lesson_id!r} not found")
        with conn:
            conn.execute("UPDATE work_lesson SET approval_status=?, status=?, updated_at=? WHERE lesson_id=?",
                         (approval_status.value, status.value, _iso(_now()), lesson_id))
            self._enqueue(conn, event, task_id=lesson_id, actor=actor, actor_type=ActorType.aria,
                          lesson_id=lesson_id, workspace_id=workspace_id, correlation_id=lesson_id,
                          outcome=approval_status.value)
        self.flush_outbox()
        return self.get_lesson(lesson_id)  # type: ignore[return-value]

    def emit_consolidated(self, goal_id: str, *, outcome: str, actor: str = "aria",
                         workspace_id: str | None = None) -> None:
        conn = self._connect()
        with conn:
            self._enqueue(conn, LedgerEventType.work_memory_consolidated, task_id=goal_id, actor=actor,
                          actor_type=ActorType.aria, goal_id=goal_id, workspace_id=workspace_id,
                          correlation_id=goal_id, outcome=outcome)
        self.flush_outbox()

    # ── World sources / updates ──────────────────────────────────────────────

    def register_source(self, s: WorldSource, *, actor: str = "aria") -> WorldSource:
        _guard_ids(source_id=s.source_id)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO world_source (source_id, name, source_type, url, allowed, trust_level, "
                "topic_tags, last_checked_at, policy_notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    s.source_id, sanitize_text(s.name), s.source_type.value, sanitize_text(s.url),
                    1 if s.allowed else 0, s.trust_level.value, _slist(s.topic_tags),
                    _iso(s.last_checked_at) if s.last_checked_at else None,
                    sanitize_text(s.policy_notes), _iso(s.created_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.world_source_registered, task_id=s.source_id, actor=actor,
                          actor_type=ActorType.aria, source_id=s.source_id, correlation_id=s.source_id,
                          trust_level=s.trust_level.value, outcome=s.source_type.value)
        self.flush_outbox()
        return self.get_source(s.source_id)  # type: ignore[return-value]

    def get_source(self, source_id: str) -> WorldSource | None:
        row = self._connect().execute("SELECT * FROM world_source WHERE source_id=?",
                                      (source_id,)).fetchone()
        return self._row_to_source(row) if row else None

    def list_sources(self) -> list[WorldSource]:
        rows = self._connect().execute("SELECT * FROM world_source ORDER BY created_at, source_id").fetchall()
        return [self._row_to_source(r) for r in rows]

    def ingest_update(self, u: WorldUpdate, *, actor: str = "aria") -> WorldUpdate:
        # A world update is a provenance record — it must carry a source citation.
        _require_nonempty(citations=u.citations)
        _guard_ids(update_id=u.update_id, source_id=u.source_id)
        _guard_id_lists(citations=u.citations)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO world_update (update_id, source_id, title, summary, published_at, "
                "captured_at, source_url, citations, topic_tags, trust_level, relevance_score, "
                "risk_level, status, recommendation) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    u.update_id, u.source_id, sanitize_text(u.title), sanitize_text(u.summary),
                    _iso(u.published_at) if u.published_at else None, _iso(u.captured_at),
                    sanitize_text(u.source_url), _jlist(u.citations), _slist(u.topic_tags),
                    u.trust_level.value, u.relevance_score, u.risk_level, u.status.value,
                    sanitize_text(u.recommendation),
                ),
            )
            self._enqueue(conn, LedgerEventType.world_update_ingested, task_id=u.update_id, actor=actor,
                          actor_type=ActorType.aria, update_id=u.update_id, source_id=u.source_id,
                          correlation_id=u.update_id, trust_level=u.trust_level.value,
                          risk_level=u.risk_level, outcome="ingested")
        self.flush_outbox()
        return self.get_update(u.update_id)  # type: ignore[return-value]

    def score_update(self, update_id: str, *, relevance_score: float, risk_level: str,
                    status: UpdateStatus, recommendation: str, actor: str = "aria") -> WorldUpdate:
        conn = self._connect()
        u = self.get_update(update_id)
        if u is None:
            raise AwarenessNotFound(f"update {update_id!r} not found")
        with conn:
            conn.execute(
                "UPDATE world_update SET relevance_score=?, risk_level=?, status=?, recommendation=? "
                "WHERE update_id=?",
                (relevance_score, risk_level, status.value, sanitize_text(recommendation), update_id),
            )
            self._enqueue(conn, LedgerEventType.world_update_scored, task_id=update_id, actor=actor,
                          actor_type=ActorType.aria, update_id=update_id, source_id=u.source_id,
                          correlation_id=update_id, trust_level=u.trust_level.value,
                          risk_level=risk_level, relevance_score=relevance_score, outcome=status.value)
        self.flush_outbox()
        return self.get_update(update_id)  # type: ignore[return-value]

    def get_update(self, update_id: str) -> WorldUpdate | None:
        row = self._connect().execute("SELECT * FROM world_update WHERE update_id=?",
                                      (update_id,)).fetchone()
        return self._row_to_update(row) if row else None

    def list_updates(self) -> list[WorldUpdate]:
        rows = self._connect().execute("SELECT * FROM world_update ORDER BY captured_at, update_id").fetchall()
        return [self._row_to_update(r) for r in rows]

    # ── Improvement proposals ────────────────────────────────────────────────

    def create_improvement(self, imp: ImprovementProposal, *, actor: str = "aria",
                          workspace_id: str | None = None) -> ImprovementProposal:
        # ``origin_ref`` (a node/update id) + the skill gap/proposal ids are join keys.
        _guard_ids(proposal_id=imp.proposal_id, origin_ref=imp.origin_ref,
                   skill_gap_id=imp.skill_gap_id, skill_proposal_id=imp.skill_proposal_id)
        _guard_id_lists(source_refs=imp.source_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO improvement_proposal (proposal_id, origin_type, origin_ref, title, "
                "description, source_refs, skill_gap_id, skill_proposal_id, relevance_score, risk_level, "
                "status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    imp.proposal_id, imp.origin_type.value, imp.origin_ref, sanitize_text(imp.title),
                    sanitize_text(imp.description), _jlist(imp.source_refs), imp.skill_gap_id,
                    imp.skill_proposal_id, imp.relevance_score, imp.risk_level, imp.status,
                    _iso(imp.created_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.improvement_proposal_created, task_id=imp.proposal_id,
                          actor=actor, actor_type=ActorType.aria, skill_gap_id=imp.skill_gap_id,
                          skill_proposal_id=imp.skill_proposal_id, workspace_id=workspace_id,
                          correlation_id=imp.proposal_id, relevance_score=imp.relevance_score,
                          risk_level=imp.risk_level, outcome=f"{imp.origin_type.value};pending")
        self.flush_outbox()
        return imp

    def list_improvements(self) -> list[ImprovementProposal]:
        rows = self._connect().execute(
            "SELECT * FROM improvement_proposal ORDER BY created_at, proposal_id").fetchall()
        return [self._row_to_improvement(r) for r in rows]

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> WorkMemoryNode:
        return WorkMemoryNode(
            node_id=row["node_id"], node_type=NodeType(row["node_type"]), title=row["title"],
            summary=row["summary"], source_refs=json.loads(row["source_refs"]),
            goal_ids=json.loads(row["goal_ids"]), task_ids=json.loads(row["task_ids"]),
            agent_ids=json.loads(row["agent_ids"]), skill_ids=json.loads(row["skill_ids"]),
            workspace_ids=json.loads(row["workspace_ids"]), evidence_refs=json.loads(row["evidence_refs"]),
            memory_refs=json.loads(row["memory_refs"]), confidence=row["confidence"],
            status=NodeStatus(row["status"]),
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> WorkMemoryEdge:
        return WorkMemoryEdge(
            edge_id=row["edge_id"], from_node_id=row["from_node_id"], to_node_id=row["to_node_id"],
            relation_type=RelationType(row["relation_type"]), source_refs=json.loads(row["source_refs"]),
            confidence=row["confidence"], created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_lesson(row: sqlite3.Row) -> WorkLesson:
        return WorkLesson(
            lesson_id=row["lesson_id"], title=row["title"], lesson=row["lesson"],
            applies_to=json.loads(row["applies_to"]), source_node_ids=json.loads(row["source_node_ids"]),
            source_refs=json.loads(row["source_refs"]), required_evidence=json.loads(row["required_evidence"]),
            confidence=row["confidence"], recommended_use=row["recommended_use"],
            approval_status=LessonApprovalStatus(row["approval_status"]), status=NodeStatus(row["status"]),
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> WorldSource:
        return WorldSource(
            source_id=row["source_id"], name=row["name"], source_type=WorldSourceType(row["source_type"]),
            url=row["url"], allowed=bool(row["allowed"]), trust_level=TrustLevel(row["trust_level"]),
            topic_tags=json.loads(row["topic_tags"]), last_checked_at=_parse_dt(row["last_checked_at"]),
            policy_notes=row["policy_notes"], created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_update(row: sqlite3.Row) -> WorldUpdate:
        return WorldUpdate(
            update_id=row["update_id"], source_id=row["source_id"], title=row["title"],
            summary=row["summary"], published_at=_parse_dt(row["published_at"]),
            captured_at=_parse_dt(row["captured_at"]), source_url=row["source_url"],
            citations=json.loads(row["citations"]), topic_tags=json.loads(row["topic_tags"]),
            trust_level=TrustLevel(row["trust_level"]), relevance_score=row["relevance_score"],
            risk_level=row["risk_level"], status=UpdateStatus(row["status"]),
            recommendation=row["recommendation"],
        )

    @staticmethod
    def _row_to_improvement(row: sqlite3.Row) -> ImprovementProposal:
        return ImprovementProposal(
            proposal_id=row["proposal_id"], origin_type=ImprovementOrigin(row["origin_type"]),
            origin_ref=row["origin_ref"], title=row["title"], description=row["description"],
            source_refs=json.loads(row["source_refs"]), skill_gap_id=row["skill_gap_id"],
            skill_proposal_id=row["skill_proposal_id"], relevance_score=row["relevance_score"],
            risk_level=row["risk_level"], status=row["status"], created_at=_parse_dt(row["created_at"]),
        )
