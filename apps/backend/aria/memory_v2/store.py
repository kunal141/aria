"""
SQLite Domain Memory Authority (Week 32 §3/§4/§5).

The authoritative V2 memory store. Approval-gated, versioned, immutable-by-version,
scope-isolated, restart-safe, and confined to ``${ARIA_DATA_DIR}/memory/store.sqlite``.

Design notes
------------
- **No import-time DB creation.** The DB file + schema are created lazily on the
  first connection (i.e. first method call), never at import.
- **Immutability by version.** ``approved_value`` is written once per version row
  and never updated in place. Updates/deletes/rollbacks INSERT new version rows;
  only the lifecycle pointers (``is_active`` / ``superseded_by``) on prior rows
  are toggled.
- **Transactional writes.** Multi-row state transitions (approve → supersede →
  decide proposal) run inside one SQLite transaction.
- **Scope isolation.** Recall filters on an exact ``scope`` match.
- **Sensitive boundary.** Sensitive/confidential/restricted memory is refused on
  persist and never returned on recall (V2 has no authenticated identity).
- **Audit.** Every state transition emits a Work Ledger memory event.

Old JSON memory (``aria.memory``) remains compatibility-only — this store is the
authoritative V2 memory. Neo4j is not used as authoritative memory in V2.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.audit import build_memory_event
from aria.memory_v2.models import (
    ChatSession,
    ChatTurn,
    DomainMemoryProposal,
    DomainMemoryVersion,
    MemoryCitation,
    MemoryOperation,
    ProposalStatus,
)
from aria.memory_v2.paths import ensure_confined, memory_db_path
from aria.memory_v2.sensitivity import (
    SensitiveMemoryError,
    classify,
    is_sensitive,
    redact_chat_content,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_session (
    session_id TEXT PRIMARY KEY,
    owner      TEXT NOT NULL,
    scope      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_turn (
    turn_id        TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    role           TEXT NOT NULL,
    content        TEXT NOT NULL,
    model          TEXT,
    task_id        TEXT,
    correlation_id TEXT,
    timestamp      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS domain_memory_proposal (
    proposal_id      TEXT PRIMARY KEY,
    operation        TEXT NOT NULL,
    structured_value TEXT NOT NULL,
    source_turn_id   TEXT,
    owner            TEXT NOT NULL,
    scope            TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_at       TEXT NOT NULL,
    decided_at       TEXT,
    target_memory_id TEXT
);
CREATE TABLE IF NOT EXISTS domain_memory_version (
    memory_id       TEXT NOT NULL,
    version         INTEGER NOT NULL,
    approved_value  TEXT,
    source_turn_id  TEXT,
    proposal_id     TEXT NOT NULL,
    owner           TEXT NOT NULL,
    approver        TEXT NOT NULL,
    scope           TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    superseded_by   INTEGER,
    rollback_target INTEGER,
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_tombstone    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (memory_id, version)
);
CREATE TABLE IF NOT EXISTS memory_citation (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id        TEXT NOT NULL,
    version          INTEGER NOT NULL,
    relevant_fields  TEXT,
    retrieval_reason TEXT NOT NULL,
    cited_at         TEXT NOT NULL
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
    if value is None:
        return None
    return datetime.fromisoformat(value)


class ProposalNotPending(ValueError):
    """A decision was attempted on a proposal that is not pending."""


class MemoryNotFound(ValueError):
    """An update/delete/rollback referenced a memory_id that does not exist."""


class DomainMemoryStore:
    """SQLite-backed authoritative domain-memory store."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        writer: Any = None,
        execution_mode: str | None = None,
    ) -> None:
        # Enforce path confinement: the resolved DB path MUST be under
        # ARIA_DATA_DIR. An explicit db_path that escapes the root (including via
        # ``..`` traversal) is refused — it cannot silently write outside the
        # confined runtime tree. The default (memory_db_path()) is always under it.
        resolved = Path(db_path) if db_path is not None else memory_db_path()
        self._db_path = ensure_confined(resolved)
        self._writer = writer                      # injectable for tests
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
    #
    # State mutation and audit evidence MUST NOT diverge. So every audit event is
    # ENQUEUED into the ``audit_outbox`` table inside the SAME SQLite transaction
    # that mutates memory state — they commit atomically. A separate flush drains
    # the outbox to the Work Ledger. If the ledger write fails (e.g. disk error),
    # the event stays durably queued in SQLite and is retried by ``flush_outbox``;
    # the state change is never left without a durable audit record, and the
    # caller is not handed a divergence-inducing exception.

    def _enqueue(self, conn: sqlite3.Connection, event_type: LedgerEventType, **fields) -> None:
        """Build + validate the audit event and persist it to the outbox WITHIN
        the caller's open transaction. The stored JSON is already redacted by the
        ledger envelope validators — no raw exception text is ever placed here."""
        fields.setdefault("execution_mode", self._execution_mode)
        event = build_memory_event(event_type, **fields)
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
        """Drain pending audit events to the Work Ledger in insertion order.

        Returns the count flushed. On the first append failure it STOPS, leaving
        that event and all later events durably queued (so a transient ledger
        outage never loses or reorders audit). Safe to call repeatedly (the writer
        de-duplicates by ``event_id``). This is the recovery path."""
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
                break  # ledger unavailable — leave this + remaining events queued
            with conn:
                conn.execute(
                    "UPDATE audit_outbox SET flushed_at=? WHERE outbox_id=?",
                    (_iso(_now()), row["outbox_id"]),
                )
            flushed += 1
        return flushed

    def pending_audit_count(self) -> int:
        """Number of audit events durably queued but not yet on the Work Ledger."""
        row = self._connect().execute(
            "SELECT COUNT(*) AS c FROM audit_outbox WHERE flushed_at IS NULL"
        ).fetchone()
        return int(row["c"])

    # ── Sessions ─────────────────────────────────────────────────────────────

    def create_session(self, *, owner: str, scope: str) -> ChatSession:
        conn = self._connect()
        session_id = f"sess-{uuid.uuid4().hex}"
        now = _now()
        with conn:
            conn.execute(
                "INSERT INTO chat_session (session_id, owner, scope, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (session_id, owner, scope, _iso(now), _iso(now)),
            )
        return ChatSession(
            session_id=session_id, owner=owner, scope=scope, created_at=now, updated_at=now
        )

    def get_session(self, session_id: str) -> ChatSession | None:
        row = self._connect().execute(
            "SELECT * FROM chat_session WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return ChatSession(
            session_id=row["session_id"], owner=row["owner"], scope=row["scope"],
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    def add_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        model: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ChatTurn:
        conn = self._connect()
        turn_id = f"turn-{uuid.uuid4().hex}"
        now = _now()
        # Redaction boundary: chat history must never persist secrets. Sensitive
        # turns are stored as a safe placeholder; credential-shaped substrings are
        # masked everywhere else. This runs HERE (the persistence boundary) so no
        # caller can write a raw secret into chat_turn (Week 32 §5 / P1).
        safe_content = redact_chat_content(content)
        with conn:
            conn.execute(
                "INSERT INTO chat_turn (turn_id, session_id, role, content, model, task_id, "
                "correlation_id, timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (turn_id, session_id, role, safe_content, model, task_id, correlation_id, _iso(now)),
            )
            conn.execute(
                "UPDATE chat_session SET updated_at=? WHERE session_id=?",
                (_iso(now), session_id),
            )
        return ChatTurn(
            turn_id=turn_id, session_id=session_id, role=role, content=safe_content, model=model,
            task_id=task_id, correlation_id=correlation_id, timestamp=now,
        )

    def get_turns(self, session_id: str) -> list[ChatTurn]:
        rows = self._connect().execute(
            "SELECT * FROM chat_turn WHERE session_id=? ORDER BY timestamp, turn_id", (session_id,)
        ).fetchall()
        return [
            ChatTurn(
                turn_id=r["turn_id"], session_id=r["session_id"], role=r["role"],
                content=r["content"], model=r["model"], task_id=r["task_id"],
                correlation_id=r["correlation_id"], timestamp=_parse_dt(r["timestamp"]),
            )
            for r in rows
        ]

    # ── Proposals ────────────────────────────────────────────────────────────

    def propose_memory(
        self,
        *,
        operation: MemoryOperation | str,
        structured_value: dict[str, Any],
        owner: str,
        scope: str,
        source_turn_id: str | None = None,
        confidence: float = 0.0,
        target_memory_id: str | None = None,
        declared_sensitivity: str | None = None,
        session_id: str | None = None,
        actor: str | None = None,
    ) -> DomainMemoryProposal:
        """Create a pending proposal. Refuses sensitive memory (§5)."""
        operation = MemoryOperation(operation) if not isinstance(operation, MemoryOperation) else operation

        sensitive, reason = classify(
            scope=scope, structured_value=structured_value, declared=declared_sensitivity
        )
        conn = self._connect()
        if sensitive:
            # Log the refusal as a rejection HERE (no caller can bypass it), then
            # raise. Nothing is persisted — the secret never reaches SQLite. The
            # refusal audit is enqueued durably in the same outbox.
            synthetic = f"sensitive-refusal-{source_turn_id or uuid.uuid4().hex}"
            with conn:
                self._enqueue(
                    conn, LedgerEventType.rejected, task_id=synthetic, actor=owner,
                    actor_type=ActorType.human, approval_id=synthetic, session_id=session_id,
                    scope=scope, outcome="sensitive_refused",
                )
            self.flush_outbox()
            raise SensitiveMemoryError(reason)

        if operation in (MemoryOperation.update, MemoryOperation.delete):
            if not target_memory_id:
                raise MemoryNotFound(f"{operation.value} requires target_memory_id")
            if self.get_active_version(target_memory_id) is None:
                raise MemoryNotFound(
                    f"{operation.value} target memory {target_memory_id!r} has no active version"
                )

        proposal_id = f"prop-{uuid.uuid4().hex}"
        now = _now()
        with conn:
            conn.execute(
                "INSERT INTO domain_memory_proposal (proposal_id, operation, structured_value, "
                "source_turn_id, owner, scope, confidence, status, created_at, decided_at, "
                "target_memory_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (proposal_id, operation.value, json.dumps(structured_value), source_turn_id,
                 owner, scope, confidence, ProposalStatus.pending.value, _iso(now), None,
                 target_memory_id),
            )
            # Audit enqueued in the SAME transaction as the proposal insert.
            self._enqueue(
                conn, LedgerEventType.memory_proposed, task_id=proposal_id, actor=actor or owner,
                actor_type=ActorType.aria, session_id=session_id, scope=scope,
                proposal_id=proposal_id, outcome=operation.value,
            )
            # Proposal awaiting a human decision → reuse approval_requested. In the
            # store so the decision audit fires for ANY caller (P2).
            self._enqueue(
                conn, LedgerEventType.approval_requested, task_id=proposal_id, actor=actor or owner,
                actor_type=ActorType.aria, session_id=session_id, scope=scope,
                proposal_id=proposal_id, approval_id=proposal_id, outcome="memory_proposal",
            )
        self.flush_outbox()
        return self.get_proposal(proposal_id)  # type: ignore[return-value]

    def get_proposal(self, proposal_id: str) -> DomainMemoryProposal | None:
        row = self._connect().execute(
            "SELECT * FROM domain_memory_proposal WHERE proposal_id=?", (proposal_id,)
        ).fetchone()
        return self._row_to_proposal(row) if row else None

    def reject_proposal(
        self, proposal_id: str, *, session_id: str | None = None, actor: str = "human:local",
    ) -> DomainMemoryProposal:
        conn = self._connect()
        prop = self.get_proposal(proposal_id)
        if prop is None:
            raise MemoryNotFound(f"proposal {proposal_id!r} not found")
        if prop.status is not ProposalStatus.pending:
            raise ProposalNotPending(f"proposal {proposal_id!r} is {prop.status.value}, not pending")
        now = _now()
        with conn:
            conn.execute(
                "UPDATE domain_memory_proposal SET status=?, decided_at=? WHERE proposal_id=?",
                (ProposalStatus.rejected.value, _iso(now), proposal_id),
            )
            # Decision audit enqueued in the same transaction (P2); fires for any caller.
            self._enqueue(
                conn, LedgerEventType.rejected, task_id=proposal_id, actor=actor,
                actor_type=ActorType.human, approval_id=proposal_id, session_id=session_id,
                scope=prop.scope, proposal_id=proposal_id, outcome="memory_rejected",
            )
        self.flush_outbox()
        return self.get_proposal(proposal_id)  # type: ignore[return-value]

    # ── Approval → versions (transactional) ──────────────────────────────────

    def approve_proposal(
        self, proposal_id: str, *, approver: str, session_id: str | None = None,
    ) -> DomainMemoryVersion:
        conn = self._connect()
        prop = self.get_proposal(proposal_id)
        if prop is None:
            raise MemoryNotFound(f"proposal {proposal_id!r} not found")
        if prop.status is not ProposalStatus.pending:
            raise ProposalNotPending(f"proposal {proposal_id!r} is {prop.status.value}, not pending")

        # Defence in depth: never apply a sensitive proposal even if one slipped in.
        if is_sensitive(scope=prop.scope, structured_value=prop.structured_value):
            with conn:
                conn.execute(
                    "UPDATE domain_memory_proposal SET status=?, decided_at=? WHERE proposal_id=?",
                    (ProposalStatus.rejected.value, _iso(_now()), proposal_id),
                )
                self._enqueue(
                    conn, LedgerEventType.rejected, task_id=proposal_id, actor=approver,
                    actor_type=ActorType.human, approval_id=proposal_id, session_id=session_id,
                    scope=prop.scope, proposal_id=proposal_id, outcome="sensitive_refused",
                )
            self.flush_outbox()
            raise SensitiveMemoryError("sensitive proposal cannot be approved")

        now = _now()
        # State mutation AND all audit events commit in ONE transaction, so they
        # can never diverge. Causal order: ``approved`` (the decision) is enqueued
        # BEFORE the effect events (memory_applied / superseded / deleted), fixing
        # the weak ordering Codex flagged.
        with conn:
            if prop.operation is MemoryOperation.create:
                memory_id, new_version = self._create_rows(conn, prop, approver, now)
                effects = [(LedgerEventType.memory_applied, "create")]
            elif prop.operation is MemoryOperation.update:
                memory_id, new_version = self._update_rows(conn, prop, approver, now)
                effects = [
                    (LedgerEventType.memory_superseded, "update"),
                    (LedgerEventType.memory_applied, "update"),
                ]
            else:  # delete
                memory_id, new_version = self._delete_rows(conn, prop, approver, now)
                effects = [(LedgerEventType.memory_deleted, "delete")]

            # Decision audit (reused ``approved``) — emitted by the store so it
            # fires for ANY caller (orchestrator OR a direct API/inbox) (P2).
            self._enqueue(
                conn, LedgerEventType.approved, task_id=proposal_id, actor=approver,
                actor_type=ActorType.human, approval_id=proposal_id, session_id=session_id,
                scope=prop.scope, memory_id=memory_id, memory_version=new_version,
                proposal_id=proposal_id, outcome="memory_approved",
            )
            for event_type, outcome in effects:
                self._enqueue(
                    conn, event_type, task_id=memory_id, actor=approver,
                    actor_type=ActorType.human, session_id=session_id, scope=prop.scope,
                    memory_id=memory_id, memory_version=new_version, proposal_id=proposal_id,
                    outcome=outcome,
                )
        self.flush_outbox()
        return self.get_version(memory_id, new_version)  # type: ignore[return-value]

    # Row-only helpers: they execute statements on the caller's open transaction
    # (no ``with conn:``) so state mutation + audit enqueue commit atomically.

    def _create_rows(self, conn, prop, approver, now) -> tuple[str, int]:
        memory_id = f"mem-{uuid.uuid4().hex}"
        conn.execute(
            "INSERT INTO domain_memory_version (memory_id, version, approved_value, "
            "source_turn_id, proposal_id, owner, approver, scope, created_at, superseded_by, "
            "rollback_target, is_active, is_tombstone) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (memory_id, 1, json.dumps(prop.structured_value), prop.source_turn_id,
             prop.proposal_id, prop.owner, approver, prop.scope, _iso(now), None, None, 1, 0),
        )
        conn.execute(
            "UPDATE domain_memory_proposal SET status=?, decided_at=? WHERE proposal_id=?",
            (ProposalStatus.approved.value, _iso(now), prop.proposal_id),
        )
        return memory_id, 1

    def _update_rows(self, conn, prop, approver, now) -> tuple[str, int]:
        memory_id = prop.target_memory_id
        current = self.get_active_version(memory_id)
        if current is None:
            raise MemoryNotFound(f"update target {memory_id!r} has no active version")
        new_version = self._max_version(memory_id) + 1
        conn.execute(
            "INSERT INTO domain_memory_version (memory_id, version, approved_value, "
            "source_turn_id, proposal_id, owner, approver, scope, created_at, superseded_by, "
            "rollback_target, is_active, is_tombstone) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (memory_id, new_version, json.dumps(prop.structured_value), prop.source_turn_id,
             prop.proposal_id, prop.owner, approver, prop.scope, _iso(now), None, None, 1, 0),
        )
        conn.execute(
            "UPDATE domain_memory_version SET is_active=0, superseded_by=? "
            "WHERE memory_id=? AND version=?",
            (new_version, memory_id, current.version),
        )
        conn.execute(
            "UPDATE domain_memory_proposal SET status=?, decided_at=? WHERE proposal_id=?",
            (ProposalStatus.approved.value, _iso(now), prop.proposal_id),
        )
        return memory_id, new_version

    def _delete_rows(self, conn, prop, approver, now) -> tuple[str, int]:
        memory_id = prop.target_memory_id
        current = self.get_active_version(memory_id)
        if current is None:
            raise MemoryNotFound(f"delete target {memory_id!r} has no active version")
        new_version = self._max_version(memory_id) + 1
        # Tombstone: inactive, no value — recall returns nothing afterward.
        conn.execute(
            "INSERT INTO domain_memory_version (memory_id, version, approved_value, "
            "source_turn_id, proposal_id, owner, approver, scope, created_at, superseded_by, "
            "rollback_target, is_active, is_tombstone) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (memory_id, new_version, None, prop.source_turn_id, prop.proposal_id, prop.owner,
             approver, prop.scope, _iso(now), None, None, 0, 1),
        )
        conn.execute(
            "UPDATE domain_memory_version SET is_active=0, superseded_by=? "
            "WHERE memory_id=? AND version=?",
            (new_version, memory_id, current.version),
        )
        conn.execute(
            "UPDATE domain_memory_proposal SET status=?, decided_at=? WHERE proposal_id=?",
            (ProposalStatus.approved.value, _iso(now), prop.proposal_id),
        )
        return memory_id, new_version

    # ── Rollback ─────────────────────────────────────────────────────────────

    def rollback(
        self, memory_id: str, target_version: int, *, approver: str,
        session_id: str | None = None, source_turn_id: str | None = None,
    ) -> DomainMemoryVersion:
        """Restore a prior approved (non-tombstone) version as the new active version."""
        conn = self._connect()
        target = self.get_version(memory_id, target_version)
        if target is None or target.is_tombstone or target.approved_value is None:
            raise MemoryNotFound(
                f"rollback target {memory_id!r} v{target_version} is not a restorable version"
            )
        current = self.get_active_version(memory_id)
        new_version = self._max_version(memory_id) + 1
        now = _now()
        # Synthetic proposal id documents the rollback in the version's audit trail.
        synthetic_proposal = f"rollback:{memory_id}:{target_version}:{uuid.uuid4().hex[:8]}"
        with conn:
            conn.execute(
                "INSERT INTO domain_memory_version (memory_id, version, approved_value, "
                "source_turn_id, proposal_id, owner, approver, scope, created_at, superseded_by, "
                "rollback_target, is_active, is_tombstone) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (memory_id, new_version, json.dumps(target.approved_value), source_turn_id,
                 synthetic_proposal, target.owner, approver, target.scope, _iso(now), None,
                 target_version, 1, 0),
            )
            if current is not None:
                conn.execute(
                    "UPDATE domain_memory_version SET is_active=0, superseded_by=? "
                    "WHERE memory_id=? AND version=?",
                    (new_version, memory_id, current.version),
                )
            self._enqueue(
                conn, LedgerEventType.memory_rolled_back, task_id=memory_id, actor=approver,
                actor_type=ActorType.human, session_id=session_id, scope=target.scope,
                memory_id=memory_id, memory_version=new_version,
                outcome=f"restored_v{target_version}",
            )
        self.flush_outbox()
        return self.get_version(memory_id, new_version)  # type: ignore[return-value]

    # ── Recall (scope-isolated, cited) ───────────────────────────────────────

    def recall(
        self,
        *,
        scope: str,
        table: str | None = None,
        field: str | None = None,
        query: str | None = None,
        session_id: str | None = None,
        actor: str = "aria",
    ) -> tuple[DomainMemoryVersion, MemoryCitation] | None:
        """Return the best matching active memory version + a citation, or None.

        Scope-isolated (exact ``scope`` match). Sensitive scopes never return.
        Records a ``MemoryCitation`` and emits a ``memory_recalled`` event on a hit.
        """
        if is_sensitive(scope=scope):
            return None
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM domain_memory_version "
            "WHERE scope=? AND is_active=1 AND is_tombstone=0 ORDER BY memory_id, version",
            (scope,),
        ).fetchall()

        best: sqlite3.Row | None = None
        reason = ""
        for r in rows:
            value = json.loads(r["approved_value"]) if r["approved_value"] else {}
            if table is not None and field is not None:
                if value.get("table") == table and value.get("field") == field:
                    best, reason = r, f"matched table={table} field={field} in scope {scope}"
                    break
            elif query:
                blob = json.dumps(value, default=str).lower()
                if any(tok in blob for tok in query.lower().split() if len(tok) > 2):
                    best, reason = r, f"keyword match in scope {scope}"
                    break
            else:
                best, reason = r, f"only memory in scope {scope}"
                break

        if best is None:
            return None

        version = self._row_to_version(best)
        relevant = sorted((version.approved_value or {}).keys())
        now = _now()
        with conn:
            conn.execute(
                "INSERT INTO memory_citation (memory_id, version, relevant_fields, "
                "retrieval_reason, cited_at) VALUES (?,?,?,?,?)",
                (version.memory_id, version.version, json.dumps(relevant), reason, _iso(now)),
            )
            self._enqueue(
                conn, LedgerEventType.memory_recalled, task_id=version.memory_id, actor=actor,
                actor_type=ActorType.aria, session_id=session_id, scope=scope,
                memory_id=version.memory_id, memory_version=version.version, outcome="recalled",
            )
        self.flush_outbox()
        citation = MemoryCitation(
            memory_id=version.memory_id, version=version.version,
            relevant_fields=relevant, retrieval_reason=reason,
        )
        return version, citation

    # ── Read helpers ─────────────────────────────────────────────────────────

    def get_version(self, memory_id: str, version: int) -> DomainMemoryVersion | None:
        row = self._connect().execute(
            "SELECT * FROM domain_memory_version WHERE memory_id=? AND version=?",
            (memory_id, version),
        ).fetchone()
        return self._row_to_version(row) if row else None

    def get_active_version(self, memory_id: str) -> DomainMemoryVersion | None:
        row = self._connect().execute(
            "SELECT * FROM domain_memory_version WHERE memory_id=? AND is_active=1 "
            "AND is_tombstone=0 ORDER BY version DESC LIMIT 1",
            (memory_id,),
        ).fetchone()
        return self._row_to_version(row) if row else None

    def list_versions(self, memory_id: str) -> list[DomainMemoryVersion]:
        rows = self._connect().execute(
            "SELECT * FROM domain_memory_version WHERE memory_id=? ORDER BY version", (memory_id,)
        ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def _max_version(self, memory_id: str) -> int:
        row = self._connect().execute(
            "SELECT MAX(version) AS m FROM domain_memory_version WHERE memory_id=?", (memory_id,)
        ).fetchone()
        return int(row["m"]) if row and row["m"] is not None else 0

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_proposal(row: sqlite3.Row) -> DomainMemoryProposal:
        return DomainMemoryProposal(
            proposal_id=row["proposal_id"], operation=MemoryOperation(row["operation"]),
            structured_value=json.loads(row["structured_value"]),
            source_turn_id=row["source_turn_id"], owner=row["owner"], scope=row["scope"],
            confidence=row["confidence"], status=ProposalStatus(row["status"]),
            created_at=_parse_dt(row["created_at"]), decided_at=_parse_dt(row["decided_at"]),
            target_memory_id=row["target_memory_id"],
        )

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> DomainMemoryVersion:
        return DomainMemoryVersion(
            memory_id=row["memory_id"], version=row["version"],
            approved_value=json.loads(row["approved_value"]) if row["approved_value"] else None,
            source_turn_id=row["source_turn_id"], proposal_id=row["proposal_id"],
            owner=row["owner"], approver=row["approver"], scope=row["scope"],
            created_at=_parse_dt(row["created_at"]), superseded_by=row["superseded_by"],
            rollback_target=row["rollback_target"], is_active=bool(row["is_active"]),
            is_tombstone=bool(row["is_tombstone"]),
        )
