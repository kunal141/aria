"""
Persistent Task / Session Workspace (Week 33 §5).

A workspace is the durable record of a serious session: its metadata lives in
SQLite (the authoritative record) and any artifact *bytes* live in a confined
runtime directory ``${ARIA_DATA_DIR}/workspaces/<workspace_id>/``. Same discipline
as the domain-memory store: gitignored, path-confined, lazy (no import-time
creation), restart-safe, test-isolated, and audited through a **transactional
outbox** so workspace state and its Work Ledger audit can never diverge.

Workspaces are created for *serious* turns (a workflow ran, or a memory proposal /
recall happened) — not for every trivial empty/greeting input (the API decides).

Metadata never stores secrets in filenames or raw exception text: artifact names
are sanitised to a confined basename, and the metadata holds references, not raw
content.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.audit import build_memory_event
from aria.memory_v2.paths import (
    ensure_confined,
    workspace_artifact_dir,
    workspaces_db_path,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace (
    workspace_id     TEXT PRIMARY KEY,
    session_id       TEXT,
    task_id          TEXT,
    correlation_id   TEXT,
    owner            TEXT NOT NULL,
    scope            TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',
    artifact_refs    TEXT NOT NULL DEFAULT '[]',
    memory_citations TEXT NOT NULL DEFAULT '[]',
    approval_refs    TEXT NOT NULL DEFAULT '[]',
    ledger_refs      TEXT NOT NULL DEFAULT '[]',
    final_outcome    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_session ON workspace(session_id);
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


def _safe_artifact_name(name: str) -> str:
    """Sanitise an artifact filename to a confined, secret-free basename.

    Two layers:
      1. strip traversal / path separators to a basename of safe characters.
      2. if the original OR cleaned name carries a sensitivity marker
         (password/secret/token/api_key/credential/…) or a credential-shaped
         substring, REPLACE the whole name with a generated safe name — a
         filename (and thus workspace metadata) must never embed a secret. A
         safe extension is preserved when the extension itself is clean.
    """
    from aria.ledger.privacy import contains_credential_pattern
    from aria.memory_v2.sensitivity import contains_sensitive_marker

    raw = str(name)
    base = Path(raw).name.replace("\\", "").replace("/", "").strip()
    base = "".join(c for c in base if c.isalnum() or c in ("-", "_", "."))
    if not base:
        return f"artifact-{uuid.uuid4().hex[:8]}"

    if (contains_sensitive_marker(raw) or contains_sensitive_marker(base)
            or contains_credential_pattern(raw) or contains_credential_pattern(base)):
        ext = Path(base).suffix
        safe = f"artifact-{uuid.uuid4().hex[:8]}"
        # Keep the extension only if it is itself free of markers.
        if ext and not contains_sensitive_marker(ext):
            return f"{safe}{ext}"
        return safe
    return base


class Workspace(BaseModel):
    model_config = ConfigDict(frozen=True)
    workspace_id: str
    session_id: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    owner: str
    scope: str
    status: str = "open"
    artifact_refs: list[str] = Field(default_factory=list)
    memory_citations: list[dict[str, Any]] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    ledger_refs: list[str] = Field(default_factory=list)
    final_outcome: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceStore:
    """SQLite-backed persistent workspace store, confined under ARIA_DATA_DIR."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        writer: Any = None,
        execution_mode: str | None = None,
    ) -> None:
        resolved = Path(db_path) if db_path is not None else workspaces_db_path()
        self._db_path = ensure_confined(resolved)
        self._writer = writer
        self._execution_mode = execution_mode
        self._conn: sqlite3.Connection | None = None

    # ── Connection (lazy — never at import) ──────────────────────────────────

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

    # ── Transactional audit outbox (same discipline as the memory store) ─────

    def _enqueue(self, conn: sqlite3.Connection, event_type: LedgerEventType, **fields) -> None:
        fields.setdefault("execution_mode", self._execution_mode)
        event = build_memory_event(event_type, **fields)
        conn.execute(
            "INSERT INTO audit_outbox (outbox_id, event_type, event_json, created_at, flushed_at) "
            "VALUES (?,?,?,?,NULL)",
            (f"obx-{uuid.uuid4().hex}", event_type.value, event.model_dump_json(), _iso(_now())),
        )

    def flush_outbox(self, writer: Any = None) -> int:
        conn = self._connect()
        target = writer or self._writer
        if target is None:
            from aria.ledger.writer import get_default_writer

            target = get_default_writer()
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

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def create_workspace(
        self, *, owner: str, scope: str, session_id: str | None = None,
        task_id: str | None = None, correlation_id: str | None = None,
    ) -> Workspace:
        conn = self._connect()
        workspace_id = f"ws-{uuid.uuid4().hex}"
        now = _now()
        with conn:
            conn.execute(
                "INSERT INTO workspace (workspace_id, session_id, task_id, correlation_id, owner, "
                "scope, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (workspace_id, session_id, task_id, correlation_id, owner, scope, "open",
                 _iso(now), _iso(now)),
            )
            self._enqueue(
                conn, LedgerEventType.workspace_created, task_id=workspace_id, actor=owner,
                actor_type=ActorType.human, session_id=session_id, scope=scope,
                workspace_id=workspace_id, correlation_id=correlation_id or session_id or workspace_id,
                outcome="created",
            )
        self.flush_outbox()
        return self.get_workspace(workspace_id)  # type: ignore[return-value]

    def update_workspace(
        self, workspace_id: str, *, status: str | None = None,
        add_artifact_ref: str | None = None, add_citation: dict[str, Any] | None = None,
        add_approval_ref: str | None = None, add_ledger_ref: str | None = None,
        final_outcome: str | None = None, actor: str = "aria",
    ) -> Workspace:
        conn = self._connect()
        ws = self.get_workspace(workspace_id)
        if ws is None:
            raise WorkspaceNotFound(f"workspace {workspace_id!r} not found")
        artifact_refs = list(ws.artifact_refs)
        citations = list(ws.memory_citations)
        approval_refs = list(ws.approval_refs)
        ledger_refs = list(ws.ledger_refs)
        if add_artifact_ref:
            artifact_refs.append(add_artifact_ref)
        if add_citation:
            citations.append(add_citation)
        if add_approval_ref:
            approval_refs.append(add_approval_ref)
        if add_ledger_ref:
            ledger_refs.append(add_ledger_ref)
        new_status = status or ws.status
        new_outcome = final_outcome if final_outcome is not None else ws.final_outcome
        now = _now()
        with conn:
            conn.execute(
                "UPDATE workspace SET status=?, artifact_refs=?, memory_citations=?, "
                "approval_refs=?, ledger_refs=?, final_outcome=?, updated_at=? WHERE workspace_id=?",
                (new_status, json.dumps(artifact_refs), json.dumps(citations),
                 json.dumps(approval_refs), json.dumps(ledger_refs), new_outcome,
                 _iso(now), workspace_id),
            )
            self._enqueue(
                conn, LedgerEventType.workspace_updated, task_id=workspace_id, actor=actor,
                actor_type=ActorType.aria, session_id=ws.session_id, scope=ws.scope,
                workspace_id=workspace_id, correlation_id=ws.correlation_id or workspace_id,
                outcome=new_status,
            )
        self.flush_outbox()
        return self.get_workspace(workspace_id)  # type: ignore[return-value]

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        row = self._connect().execute(
            "SELECT * FROM workspace WHERE workspace_id=?", (workspace_id,)
        ).fetchone()
        return self._row_to_workspace(row) if row else None

    def get_by_session(self, session_id: str) -> Workspace | None:
        """Most recently updated workspace for a session, or None."""
        row = self._connect().execute(
            "SELECT * FROM workspace WHERE session_id=? ORDER BY updated_at DESC, workspace_id "
            "LIMIT 1",
            (session_id,),
        ).fetchone()
        return self._row_to_workspace(row) if row else None

    # ── Artifact bytes (confined runtime dir) ────────────────────────────────

    def write_artifact(self, workspace_id: str, name: str, content: str) -> str:
        """Write artifact bytes into the confined workspace dir; return the safe
        relative reference (never an absolute path)."""
        safe_name = _safe_artifact_name(name)
        ws_dir = workspace_artifact_dir(workspace_id)
        ensure_confined(ws_dir)  # path-confinement guard
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / safe_name).write_text(content, encoding="utf-8")
        return f"{workspace_id}/{safe_name}"   # relative reference only — no raw path

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_workspace(row: sqlite3.Row) -> Workspace:
        return Workspace(
            workspace_id=row["workspace_id"], session_id=row["session_id"],
            task_id=row["task_id"], correlation_id=row["correlation_id"], owner=row["owner"],
            scope=row["scope"], status=row["status"],
            artifact_refs=json.loads(row["artifact_refs"]),
            memory_citations=json.loads(row["memory_citations"]),
            approval_refs=json.loads(row["approval_refs"]),
            ledger_refs=json.loads(row["ledger_refs"]),
            final_outcome=row["final_outcome"],
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )


class WorkspaceNotFound(ValueError):
    """A workspace_id did not resolve to a stored workspace."""
