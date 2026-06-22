"""
SQLite controlled-action store (V3.9).

Persists action intents, approval decisions, and execution receipts for the governed
action gate. Same discipline as the V2/V3 stores: confined to
``${ARIA_DATA_DIR}/actions/store.sqlite`` (gitignored, never inside the importable
``aria`` source package), no import-time DB creation, lazy schema, restart-safe, and
every state change emits a Work Ledger event through a transactional **audit outbox**
(state + audit can never diverge).

DENY-BY-DEFAULT: nothing here performs an external write. Free text + payload values
are masked for secrets; structural identifiers / provenance refs that carry a
credential shape are REJECTED; an intent with no source reference (or an external
intent with no evidence) is rejected at creation.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.actions.audit import build_action_event
from aria.actions.models import (
    ActionApproval,
    ActionIntent,
    ActionReceipt,
    ActionStatus,
    ActionType,
    ApprovalDecision,
    ExecutionMode,
    RiskLevel,
    TargetSystem,
)
from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.paths import actions_db_path, ensure_confined

_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_intent (
    action_id         TEXT PRIMARY KEY,
    action_type       TEXT NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    requested_by      TEXT NOT NULL DEFAULT 'aria',
    goal_id           TEXT,
    task_id           TEXT,
    workspace_id      TEXT,
    source_refs       TEXT NOT NULL DEFAULT '[]',
    evidence_refs     TEXT NOT NULL DEFAULT '[]',
    draft_refs        TEXT NOT NULL DEFAULT '[]',
    target_system     TEXT NOT NULL DEFAULT 'internal_mock',
    payload_preview   TEXT NOT NULL DEFAULT '{}',
    risk_level        TEXT NOT NULL DEFAULT 'low',
    permission_scope  TEXT NOT NULL DEFAULT '',
    approval_required  INTEGER NOT NULL DEFAULT 1,
    status            TEXT NOT NULL DEFAULT 'draft',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intent_status ON action_intent(status);
CREATE TABLE IF NOT EXISTS action_approval (
    approval_id    TEXT PRIMARY KEY,
    action_id      TEXT NOT NULL,
    approver       TEXT NOT NULL,
    decision       TEXT NOT NULL,
    reason         TEXT NOT NULL DEFAULT '',
    decided_at     TEXT NOT NULL,
    approval_scope TEXT NOT NULL DEFAULT '',
    payload_hash   TEXT NOT NULL DEFAULT '',
    expires_at     TEXT,
    source_refs    TEXT NOT NULL DEFAULT '[]',
    evidence_refs  TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_approval_action ON action_approval(action_id);
CREATE TABLE IF NOT EXISTS action_receipt (
    receipt_id        TEXT PRIMARY KEY,
    action_id         TEXT NOT NULL,
    target_system     TEXT NOT NULL,
    execution_mode    TEXT NOT NULL,
    executed_at       TEXT NOT NULL,
    executed_by       TEXT NOT NULL DEFAULT 'aria',
    result_status     TEXT NOT NULL DEFAULT 'dry_run_ok',
    external_ref      TEXT,
    receipt_summary   TEXT NOT NULL DEFAULT '',
    rollback_note     TEXT NOT NULL DEFAULT '',
    compensation_note TEXT NOT NULL DEFAULT '',
    ledger_refs       TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_receipt_action ON action_receipt(action_id);
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


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _slist(items: list[str]) -> str:
    return json.dumps([sanitize_text(x) or "" for x in items])


def _jlist(items: list[str]) -> str:
    return json.dumps([str(x) for x in items])


def _has_secret(value: str) -> bool:
    return bool(value) and sanitize_text(value) != value


def _sanitize_value(v: Any) -> Any:
    if isinstance(v, str):
        return sanitize_text(v) or ""
    if isinstance(v, dict):
        return {k: _sanitize_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_sanitize_value(x) for x in v]
    return v


def _sanitize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Mask secret-shaped values inside a payload (redact, not reject — the payload is
    descriptive content, not a join key)."""
    return _sanitize_value(payload or {})


class ActionNotFound(ValueError):
    """An action / approval / receipt id did not resolve."""


class ActionSecurityError(ValueError):
    """A structural identifier / provenance ref carries a credential-shaped value —
    rejected at the persistence boundary (never masked: it would corrupt a join key)."""


class ActionIntegrityError(ValueError):
    """An intent violates the deny-by-default discipline (no source reference, or an
    external action with no evidence)."""


class InvalidActionTransition(ValueError):
    """An illegal action status transition was attempted at the store authority
    boundary (e.g. jumping straight to ``executed`` without going through the
    governed execution path)."""


class ActionExecutionViolation(ValueError):
    """A receipt would assert an execution that V3.9 forbids — a live mode, a real/
    external reference, a live result status, or a mock against a non-internal target.
    The store is the final authority: it refuses to record such a claim."""


# Status → the (fixed) event emitted when the store moves an action to it. Approval
# (approved/rejected) and blocked have their own dedicated methods.
_STATUS_EVENT = {
    ActionStatus.previewed:         LedgerEventType.action_previewed,
    ActionStatus.awaiting_approval: LedgerEventType.action_approval_requested,
    ActionStatus.executing:         LedgerEventType.action_execution_started,
    ActionStatus.executed:          LedgerEventType.action_executed,
    ActionStatus.failed:            LedgerEventType.action_execution_failed,
}
# Legal predecessors for each governed status. Crucially ``executed`` / ``failed`` are
# reachable ONLY from ``executing`` — a direct caller cannot fabricate an execution.
_TERMINAL = {ActionStatus.rejected, ActionStatus.cancelled, ActionStatus.rolled_back}
_PRE_EXECUTION = {ActionStatus.draft, ActionStatus.previewed, ActionStatus.blocked,
                  ActionStatus.awaiting_approval, ActionStatus.approved, ActionStatus.executed,
                  ActionStatus.failed}
_VALID_FROM = {
    ActionStatus.previewed:         _PRE_EXECUTION,
    ActionStatus.awaiting_approval: {ActionStatus.draft, ActionStatus.previewed, ActionStatus.blocked},
    ActionStatus.executing:         _PRE_EXECUTION,
    ActionStatus.executed:          {ActionStatus.executing},
    ActionStatus.failed:            {ActionStatus.executing},
}

# Receipts may only ever assert one of these — never a live result.
_ALLOWED_RESULT_STATUS = {"dry_run_ok", "mock_executed", "blocked", "failed"}
_EXECUTABLE_MODES = {ExecutionMode.dry_run, ExecutionMode.mock_live}

# An approval DECISION binds the resulting intent status — it can never be an execution
# status, so the approval path cannot drive an action to executing/executed/failed.
_DECISION_STATUS = {
    ApprovalDecision.approved:  ActionStatus.approved,
    ApprovalDecision.rejected:  ActionStatus.rejected,
    ApprovalDecision.cancelled: ActionStatus.cancelled,
    ApprovalDecision.expired:   ActionStatus.rejected,
}
_EXECUTION_STATUSES = {ActionStatus.executing, ActionStatus.executed, ActionStatus.failed}
# A decision may only be recorded on an action still in its pre-execution lifecycle.
_DECISION_VALID_FROM = {ActionStatus.draft, ActionStatus.previewed, ActionStatus.blocked,
                        ActionStatus.awaiting_approval, ActionStatus.approved}


def _guard_ids(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None and _has_secret(str(value)):
            raise ActionSecurityError(
                f"structural identifier {name!r} carries a credential-shaped value")


def _guard_id_lists(**fields: list[str] | None) -> None:
    for name, values in fields.items():
        for v in values or []:
            if _has_secret(str(v)):
                raise ActionSecurityError(
                    f"structural identifier list {name!r} carries a credential-shaped value")


class ActionStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None,
                 execution_mode: str | None = None) -> None:
        resolved = Path(db_path) if db_path is not None else actions_db_path()
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
        fields.setdefault("runtime_mode", self._execution_mode)
        event = build_action_event(event_type, **fields)
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

    # ── Intents ──────────────────────────────────────────────────────────────

    def create_intent(self, i: ActionIntent, *, actor: str = "aria") -> ActionIntent:
        # Deny-by-default at the persistence boundary.
        if not i.source_refs:
            raise ActionIntegrityError("an action intent must cite at least one source reference")
        if i.is_external and not i.evidence_refs:
            raise ActionIntegrityError("an external action intent must cite evidence references")
        _guard_ids(action_id=i.action_id, goal_id=i.goal_id, task_id=i.task_id,
                   workspace_id=i.workspace_id)
        _guard_id_lists(source_refs=i.source_refs, evidence_refs=i.evidence_refs,
                        draft_refs=i.draft_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO action_intent (action_id, action_type, title, description, requested_by, "
                "goal_id, task_id, workspace_id, source_refs, evidence_refs, draft_refs, target_system, "
                "payload_preview, risk_level, permission_scope, approval_required, status, created_at, "
                "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    i.action_id, i.action_type.value, sanitize_text(i.title), sanitize_text(i.description),
                    sanitize_text(i.requested_by), i.goal_id, i.task_id, i.workspace_id,
                    _jlist(i.source_refs), _jlist(i.evidence_refs), _jlist(i.draft_refs),
                    i.target_system.value, json.dumps(_sanitize_payload(i.payload_preview)),
                    i.risk_level.value, sanitize_text(i.permission_scope),
                    1 if i.approval_required else 0, i.status.value, _iso(i.created_at), _iso(i.updated_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.action_intent_created, task_id=i.action_id, actor=actor,
                          actor_type=ActorType.aria, action_id=i.action_id,
                          action_type=i.action_type.value, target_system=i.target_system.value,
                          goal_id=i.goal_id, task_ref=i.task_id, workspace_id=i.workspace_id,
                          correlation_id=i.action_id, status=i.status.value,
                          risk_level=i.risk_level.value, outcome="intent_created")
        self.flush_outbox()
        return self.get_intent(i.action_id)  # type: ignore[return-value]

    def get_intent(self, action_id: str) -> ActionIntent | None:
        row = self._connect().execute("SELECT * FROM action_intent WHERE action_id=?",
                                      (action_id,)).fetchone()
        return self._row_to_intent(row) if row else None

    def list_intents(self, *, status: str | None = None,
                    target_system: str | None = None) -> list[ActionIntent]:
        conn = self._connect()
        clauses, params = [], []
        if status is not None:
            clauses.append("status=?"); params.append(status)
        if target_system is not None:
            clauses.append("target_system=?"); params.append(target_system)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM action_intent{where} ORDER BY created_at, action_id",
                            params).fetchall()
        return [self._row_to_intent(r) for r in rows]

    def _transition(self, action_id: str, status: ActionStatus, *, actor: str,
                    receipt_id: str | None = None, execution_mode: str | None = None,
                    safe_error: str | None = None, risk_level: str | None = None,
                    outcome: str | None = None) -> ActionIntent:
        """Internal, AUTHORITY-CHECKED status move. Only the fixed status→event map is
        allowed, and only from a legal predecessor — so a direct caller can never jump
        to ``executed``/``failed`` without going through the governed execution path."""
        if status not in _STATUS_EVENT:
            raise InvalidActionTransition(f"{status.value!r} is not a store-managed transition")
        conn = self._connect()
        i = self.get_intent(action_id)
        if i is None:
            raise ActionNotFound(f"action {action_id!r} not found")
        if i.status in _TERMINAL:
            raise InvalidActionTransition(
                f"action is {i.status.value} (terminal); cannot move to {status.value}")
        allowed_from = _VALID_FROM.get(status, set())
        if i.status not in allowed_from:
            raise InvalidActionTransition(
                f"illegal transition {i.status.value} -> {status.value}")
        event = _STATUS_EVENT[status]
        with conn:
            conn.execute("UPDATE action_intent SET status=?, updated_at=? WHERE action_id=?",
                         (status.value, _iso(_now()), action_id))
            self._enqueue(conn, event, task_id=action_id, actor=actor, actor_type=ActorType.aria,
                          action_id=action_id, action_type=i.action_type.value,
                          target_system=i.target_system.value, execution_mode=execution_mode,
                          goal_id=i.goal_id, task_ref=i.task_id, workspace_id=i.workspace_id,
                          receipt_id=receipt_id, correlation_id=action_id, status=status.value,
                          safe_error=safe_error, risk_level=risk_level or i.risk_level.value,
                          outcome=outcome or status.value)
        self.flush_outbox()
        return self.get_intent(action_id)  # type: ignore[return-value]

    # Narrow, named transitions — the ONLY way to move an action through its lifecycle.
    def mark_previewed(self, action_id: str, *, actor: str = "aria") -> ActionIntent:
        return self._transition(action_id, ActionStatus.previewed, actor=actor, outcome="previewed")

    def mark_approval_requested(self, action_id: str, *, actor: str = "aria") -> ActionIntent:
        return self._transition(action_id, ActionStatus.awaiting_approval, actor=actor,
                               outcome="approval_requested")

    @staticmethod
    def _coerce_executable_mode(mode: ExecutionMode | str) -> ExecutionMode:
        """Coerce to a typed mode and reject anything that is not dry-run / mock-live
        (``live`` is disabled — it can never start an execution)."""
        m = mode if isinstance(mode, ExecutionMode) else ExecutionMode(mode)
        if m not in _EXECUTABLE_MODES:
            raise ActionExecutionViolation(
                f"execution_mode {m.value!r} is not permitted (live is disabled)")
        return m

    def _verified_receipt(self, action_id: str, receipt_id: str, *, expected: set[str]) -> ActionReceipt:
        """A status move to executed/failed must be backed by a REAL receipt that
        belongs to this action, uses a permitted mode, and records a matching result —
        so a named-method caller cannot fabricate an execution with a fake receipt."""
        r = self.get_receipt(receipt_id)
        if r is None:
            raise ActionExecutionViolation("execution status requires an existing receipt")
        if r.action_id != action_id:
            raise ActionExecutionViolation("receipt does not belong to this action")
        if r.execution_mode not in _EXECUTABLE_MODES:
            raise ActionExecutionViolation("receipt asserts a non-permitted execution mode")
        if r.result_status not in expected:
            raise ActionExecutionViolation(
                f"receipt result {r.result_status!r} does not match the status transition")
        return r

    def mark_execution_started(self, action_id: str, *, execution_mode: ExecutionMode | str,
                              actor: str = "aria") -> ActionIntent:
        mode = self._coerce_executable_mode(execution_mode)     # rejects 'live'
        return self._transition(action_id, ActionStatus.executing, actor=actor,
                               execution_mode=mode.value, outcome="executing")

    def mark_execution_succeeded(self, action_id: str, *, receipt_id: str, actor: str = "aria"
                                ) -> ActionIntent:
        # Mode + outcome are DERIVED from the verified receipt, never from the caller.
        receipt = self._verified_receipt(action_id, receipt_id, expected={"dry_run_ok", "mock_executed"})
        return self._transition(action_id, ActionStatus.executed, actor=actor,
                               execution_mode=receipt.execution_mode.value, receipt_id=receipt_id,
                               outcome=receipt.result_status)

    def mark_execution_failed(self, action_id: str, *, receipt_id: str, safe_error: str,
                             actor: str = "aria") -> ActionIntent:
        receipt = self._verified_receipt(action_id, receipt_id, expected={"failed"})
        return self._transition(action_id, ActionStatus.failed, actor=actor,
                               execution_mode=receipt.execution_mode.value, receipt_id=receipt_id,
                               safe_error=safe_error, risk_level="medium", outcome="failed")

    def mark_blocked(self, action_id: str, *, receipt_id: str | None = None, reason: str | None = None,
                    execution_mode: str | None = None, actor: str = "aria") -> ActionIntent:
        """Record an ``action_blocked`` event. A terminal intent (rejected/cancelled/
        rolled_back) KEEPS its status; otherwise the intent moves to ``blocked``."""
        conn = self._connect()
        i = self.get_intent(action_id)
        if i is None:
            raise ActionNotFound(f"action {action_id!r} not found")
        terminal = i.status in {ActionStatus.rejected, ActionStatus.cancelled, ActionStatus.rolled_back}
        new_status = i.status if terminal else ActionStatus.blocked
        with conn:
            if not terminal:
                conn.execute("UPDATE action_intent SET status=?, updated_at=? WHERE action_id=?",
                             (ActionStatus.blocked.value, _iso(_now()), action_id))
            self._enqueue(conn, LedgerEventType.action_blocked, task_id=action_id, actor=actor,
                          actor_type=ActorType.aria, action_id=action_id,
                          action_type=i.action_type.value, target_system=i.target_system.value,
                          execution_mode=execution_mode, receipt_id=receipt_id,
                          workspace_id=i.workspace_id, correlation_id=action_id,
                          status=new_status.value, risk_level=i.risk_level.value,
                          outcome=f"blocked:{reason}" if reason else "blocked")
        self.flush_outbox()
        return self.get_intent(action_id)  # type: ignore[return-value]

    def update_intent_payload(self, action_id: str, new_payload: dict[str, Any], *,
                             actor: str = "aria") -> ActionIntent:
        """Change an intent's payload — this invalidates any prior approval (status is
        reset to draft and the payload hash changes), so a re-approval is required."""
        conn = self._connect()
        i = self.get_intent(action_id)
        if i is None:
            raise ActionNotFound(f"action {action_id!r} not found")
        with conn:
            conn.execute("UPDATE action_intent SET payload_preview=?, status=?, updated_at=? "
                         "WHERE action_id=?",
                         (json.dumps(_sanitize_payload(new_payload)), ActionStatus.draft.value,
                          _iso(_now()), action_id))
        return self.get_intent(action_id)  # type: ignore[return-value]

    # ── Approvals ────────────────────────────────────────────────────────────

    def record_decision(self, a: ActionApproval, *, intent_status: ActionStatus,
                        actor: str = "aria") -> ActionApproval:
        _guard_ids(approval_id=a.approval_id, action_id=a.action_id)
        _guard_id_lists(source_refs=a.source_refs, evidence_refs=a.evidence_refs)
        # The resulting status is BOUND to the decision and may NEVER be an execution
        # status — a caller cannot drive an action to executing/executed/failed through
        # the approval path (which bypasses receipt verification + execution guards).
        if intent_status in _EXECUTION_STATUSES:
            raise InvalidActionTransition(
                "the approval path cannot set an execution status")
        expected = _DECISION_STATUS.get(a.decision)
        if expected is None or intent_status is not expected:
            raise InvalidActionTransition(
                f"intent_status {intent_status.value!r} does not match decision "
                f"{a.decision.value!r} (expected {expected.value if expected else None!r})")
        conn = self._connect()
        i = self.get_intent(a.action_id)
        if i is None:
            raise ActionNotFound(f"action {a.action_id!r} not found")
        if i.status not in _DECISION_VALID_FROM:
            raise InvalidActionTransition(
                f"cannot record a decision on an action that is {i.status.value}")
        event = (LedgerEventType.action_approved if a.decision is ApprovalDecision.approved
                 else LedgerEventType.action_rejected)
        with conn:
            conn.execute(
                "INSERT INTO action_approval (approval_id, action_id, approver, decision, reason, "
                "decided_at, approval_scope, payload_hash, expires_at, source_refs, evidence_refs) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    a.approval_id, a.action_id, sanitize_text(a.approver), a.decision.value,
                    sanitize_text(a.reason), _iso(a.decided_at), sanitize_text(a.approval_scope),
                    a.payload_hash, _iso(a.expires_at), _jlist(a.source_refs), _jlist(a.evidence_refs),
                ),
            )
            conn.execute("UPDATE action_intent SET status=?, updated_at=? WHERE action_id=?",
                         (intent_status.value, _iso(_now()), a.action_id))
            self._enqueue(conn, event, task_id=a.action_id, actor=actor, actor_type=ActorType.aria,
                          action_id=a.action_id, action_type=i.action_type.value,
                          target_system=i.target_system.value, approval_id=a.approval_id,
                          workspace_id=i.workspace_id, correlation_id=a.action_id,
                          status=intent_status.value, risk_level=i.risk_level.value,
                          outcome=a.decision.value)
        self.flush_outbox()
        return self.get_approval(a.approval_id)  # type: ignore[return-value]

    def get_approval(self, approval_id: str) -> ActionApproval | None:
        row = self._connect().execute("SELECT * FROM action_approval WHERE approval_id=?",
                                      (approval_id,)).fetchone()
        return self._row_to_approval(row) if row else None

    def list_approvals(self, *, action_id: str | None = None) -> list[ActionApproval]:
        conn = self._connect()
        if action_id is not None:
            rows = conn.execute("SELECT * FROM action_approval WHERE action_id=? ORDER BY decided_at",
                               (action_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM action_approval ORDER BY decided_at").fetchall()
        return [self._row_to_approval(r) for r in rows]

    def latest_approval(self, action_id: str) -> ActionApproval | None:
        rows = self.list_approvals(action_id=action_id)
        return rows[-1] if rows else None

    # ── Receipts ─────────────────────────────────────────────────────────────

    def _validate_receipt(self, r: ActionReceipt) -> None:
        """The store is the FINAL authority on what a receipt may claim. It refuses to
        record any receipt that asserts a live execution, a real/external reference, a
        live result status, or a mock against a non-internal target — even on a direct
        store call that bypassed the service/policy/executor gate."""
        if self.get_intent(r.action_id) is None:
            raise ActionNotFound(f"action {r.action_id!r} not found for receipt")
        if r.execution_mode not in _EXECUTABLE_MODES:
            raise ActionExecutionViolation(
                f"execution_mode {r.execution_mode.value!r} is not permitted (live is disabled)")
        if r.result_status not in _ALLOWED_RESULT_STATUS:
            raise ActionExecutionViolation(
                f"result_status {r.result_status!r} is not permitted (no live result)")
        mock_ref = f"mock://internal_mock/{r.action_id}"
        if r.result_status == "mock_executed":
            if r.execution_mode is not ExecutionMode.mock_live:
                raise ActionExecutionViolation("mock_executed requires mock_live mode")
            if r.target_system is not TargetSystem.internal_mock:
                raise ActionExecutionViolation("mock execution is only valid for internal_mock")
            if r.external_ref != mock_ref:
                raise ActionExecutionViolation(
                    "mock receipt external_ref must be the canonical mock://internal_mock ref")
        elif r.external_ref is not None:
            # dry-run / blocked / failed receipts must never carry an external reference.
            raise ActionExecutionViolation(
                "only a successful internal_mock receipt may carry an external_ref")

    def create_receipt(self, r: ActionReceipt, *, actor: str = "aria") -> ActionReceipt:
        _guard_ids(receipt_id=r.receipt_id, action_id=r.action_id)
        _guard_id_lists(ledger_refs=r.ledger_refs)
        self._validate_receipt(r)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO action_receipt (receipt_id, action_id, target_system, execution_mode, "
                "executed_at, executed_by, result_status, external_ref, receipt_summary, rollback_note, "
                "compensation_note, ledger_refs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r.receipt_id, r.action_id, r.target_system.value, r.execution_mode.value,
                    _iso(r.executed_at), sanitize_text(r.executed_by), r.result_status,
                    sanitize_text(r.external_ref), sanitize_text(r.receipt_summary),
                    sanitize_text(r.rollback_note), sanitize_text(r.compensation_note),
                    _jlist(r.ledger_refs),
                ),
            )
            self._enqueue(conn, LedgerEventType.action_receipt_created, task_id=r.receipt_id, actor=actor,
                          actor_type=ActorType.aria, action_id=r.action_id, receipt_id=r.receipt_id,
                          target_system=r.target_system.value, execution_mode=r.execution_mode.value,
                          correlation_id=r.action_id, status=r.result_status, outcome=r.result_status)
        self.flush_outbox()
        return self.get_receipt(r.receipt_id)  # type: ignore[return-value]

    def get_receipt(self, receipt_id: str) -> ActionReceipt | None:
        row = self._connect().execute("SELECT * FROM action_receipt WHERE receipt_id=?",
                                      (receipt_id,)).fetchone()
        return self._row_to_receipt(row) if row else None

    def list_receipts(self, *, action_id: str | None = None) -> list[ActionReceipt]:
        conn = self._connect()
        if action_id is not None:
            rows = conn.execute("SELECT * FROM action_receipt WHERE action_id=? ORDER BY executed_at",
                               (action_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM action_receipt ORDER BY executed_at").fetchall()
        return [self._row_to_receipt(r) for r in rows]

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_intent(row: sqlite3.Row) -> ActionIntent:
        return ActionIntent(
            action_id=row["action_id"], action_type=ActionType(row["action_type"]), title=row["title"],
            description=row["description"], requested_by=row["requested_by"], goal_id=row["goal_id"],
            task_id=row["task_id"], workspace_id=row["workspace_id"],
            source_refs=json.loads(row["source_refs"]), evidence_refs=json.loads(row["evidence_refs"]),
            draft_refs=json.loads(row["draft_refs"]), target_system=TargetSystem(row["target_system"]),
            payload_preview=json.loads(row["payload_preview"]), risk_level=RiskLevel(row["risk_level"]),
            permission_scope=row["permission_scope"], approval_required=bool(row["approval_required"]),
            status=ActionStatus(row["status"]), created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_approval(row: sqlite3.Row) -> ActionApproval:
        return ActionApproval(
            approval_id=row["approval_id"], action_id=row["action_id"], approver=row["approver"],
            decision=ApprovalDecision(row["decision"]), reason=row["reason"],
            decided_at=_parse_dt(row["decided_at"]), approval_scope=row["approval_scope"],
            payload_hash=row["payload_hash"], expires_at=_parse_dt(row["expires_at"]),
            source_refs=json.loads(row["source_refs"]), evidence_refs=json.loads(row["evidence_refs"]),
        )

    @staticmethod
    def _row_to_receipt(row: sqlite3.Row) -> ActionReceipt:
        return ActionReceipt(
            receipt_id=row["receipt_id"], action_id=row["action_id"],
            target_system=TargetSystem(row["target_system"]),
            execution_mode=ExecutionMode(row["execution_mode"]), executed_at=_parse_dt(row["executed_at"]),
            executed_by=row["executed_by"], result_status=row["result_status"],
            external_ref=row["external_ref"], receipt_summary=row["receipt_summary"],
            rollback_note=row["rollback_note"], compensation_note=row["compensation_note"],
            ledger_refs=json.loads(row["ledger_refs"]),
        )
