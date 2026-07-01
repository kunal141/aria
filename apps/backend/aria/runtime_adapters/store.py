"""
SQLite runtime-adapter store (V4.1).

Persists adapter definitions, capabilities, requests, receipts, and (source-linked)
evaluation records. Same discipline as the V2/V3 stores: confined to
``${ARIA_DATA_DIR}/runtime_adapters/store.sqlite`` (gitignored, never inside the
importable ``aria`` source package), no import-time DB creation, lazy schema,
restart-safe, and every state change emits a Work Ledger event through a transactional
**audit outbox**.

MOCK/LOCAL-ONLY: nothing here calls a real external runtime, model, network, SDK, or
credential. Free text + payload values are masked for secrets; structural ids /
provenance refs that carry a credential shape are rejected; eval records must be
source-linked; duplicate adapter ids are rejected.
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
from aria.memory_v2.paths import ensure_confined, runtime_adapters_db_path
from aria.runtime_adapters.audit import build_adapter_event
from aria.runtime_adapters.harness import EvalOutcome, EvaluationRecord
from aria.runtime_adapters.models import (
    AdapterStatus,
    AdapterType,
    ExecutionMode,
    ReceiptStatus,
    RequestStatus,
    RiskLevel,
    RuntimeAdapterCapability,
    RuntimeAdapterDefinition,
    RuntimeAdapterReceipt,
    RuntimeAdapterRequest,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adapter_definition (
    adapter_id        TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    vendor            TEXT NOT NULL DEFAULT 'internal',
    adapter_type      TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    supported_task_types      TEXT NOT NULL DEFAULT '[]',
    supported_execution_modes TEXT NOT NULL DEFAULT '[]',
    required_permissions      TEXT NOT NULL DEFAULT '[]',
    allowed_scopes            TEXT NOT NULL DEFAULT '[]',
    risk_level        TEXT NOT NULL DEFAULT 'low',
    enabled           INTEGER NOT NULL DEFAULT 1,
    status            TEXT NOT NULL DEFAULT 'registered',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adapter_capability (
    capability_id     TEXT PRIMARY KEY,
    adapter_id        TEXT NOT NULL,
    capability_name   TEXT NOT NULL,
    task_type         TEXT NOT NULL,
    input_schema      TEXT NOT NULL DEFAULT '{}',
    output_schema     TEXT NOT NULL DEFAULT '{}',
    permission_scope  TEXT NOT NULL DEFAULT '',
    risk_level        TEXT NOT NULL DEFAULT 'low',
    requires_approval INTEGER NOT NULL DEFAULT 1,
    evidence_required INTEGER NOT NULL DEFAULT 1,
    status            TEXT NOT NULL DEFAULT 'declared'
);
CREATE INDEX IF NOT EXISTS idx_cap_adapter ON adapter_capability(adapter_id);
CREATE TABLE IF NOT EXISTS adapter_request (
    request_id        TEXT PRIMARY KEY,
    adapter_id        TEXT NOT NULL,
    goal_id           TEXT,
    task_id           TEXT,
    workspace_id      TEXT,
    task_type         TEXT NOT NULL,
    input_payload     TEXT NOT NULL DEFAULT '{}',
    source_refs       TEXT NOT NULL DEFAULT '[]',
    evidence_refs     TEXT NOT NULL DEFAULT '[]',
    requested_by      TEXT NOT NULL DEFAULT 'aria',
    execution_mode    TEXT NOT NULL DEFAULT 'preview',
    status            TEXT NOT NULL DEFAULT 'created',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_req_adapter ON adapter_request(adapter_id);
CREATE TABLE IF NOT EXISTS adapter_receipt (
    receipt_id        TEXT PRIMARY KEY,
    request_id        TEXT NOT NULL,
    adapter_id        TEXT NOT NULL,
    execution_mode    TEXT NOT NULL,
    status            TEXT NOT NULL,
    output_summary    TEXT NOT NULL DEFAULT '',
    output_payload    TEXT NOT NULL DEFAULT '{}',
    source_refs       TEXT NOT NULL DEFAULT '[]',
    evidence_refs     TEXT NOT NULL DEFAULT '[]',
    external_ref      TEXT,
    safe_error        TEXT,
    created_at        TEXT NOT NULL,
    ledger_refs       TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_rcpt_request ON adapter_receipt(request_id);
CREATE TABLE IF NOT EXISTS eval_record (
    eval_id           TEXT PRIMARY KEY,
    goal_id           TEXT,
    task_id           TEXT,
    adapter_id        TEXT,
    model_id          TEXT,
    prompt_version    TEXT NOT NULL DEFAULT 'v0',
    skill_version     TEXT NOT NULL DEFAULT 'v0',
    input_ref         TEXT NOT NULL,
    output_ref        TEXT NOT NULL,
    expected_behavior TEXT NOT NULL DEFAULT '',
    actual_behavior   TEXT NOT NULL DEFAULT '',
    score             REAL NOT NULL DEFAULT 0,
    pass_fail         TEXT NOT NULL DEFAULT 'not_evaluated',
    failure_reason    TEXT NOT NULL DEFAULT '',
    human_label       TEXT NOT NULL DEFAULT '',
    cost_estimate     REAL,
    latency_ms        INTEGER NOT NULL DEFAULT 0,
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

# Request status → the lifecycle event emitted when a receipt records that outcome.
_OUTCOME_EVENT = {
    ReceiptStatus.previewed:         LedgerEventType.runtime_adapter_previewed,
    ReceiptStatus.blocked:           LedgerEventType.runtime_adapter_blocked,
    ReceiptStatus.dry_run_completed: LedgerEventType.runtime_adapter_dry_run_completed,
    ReceiptStatus.mock_completed:    LedgerEventType.runtime_adapter_mock_completed,
    ReceiptStatus.failed:            LedgerEventType.runtime_adapter_execution_failed,
}
_RECEIPT_TO_REQUEST_STATUS = {
    ReceiptStatus.previewed:         RequestStatus.previewed,
    ReceiptStatus.blocked:           RequestStatus.blocked,
    ReceiptStatus.dry_run_completed: RequestStatus.dry_run_completed,
    ReceiptStatus.mock_completed:    RequestStatus.mock_completed,
    ReceiptStatus.failed:            RequestStatus.failed,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _slist(items: list[str]) -> str:
    return json.dumps([sanitize_text(x) or "" for x in items])


def _jlist(items: list) -> str:
    return json.dumps([x.value if hasattr(x, "value") else str(x) for x in items])


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
    return _sanitize_value(payload or {})


class AdapterNotFound(ValueError):
    """An adapter / request / receipt id did not resolve."""


class AdapterAlreadyExists(ValueError):
    """A duplicate adapter id was registered."""


class AdapterSecurityError(ValueError):
    """A structural id / provenance ref carries a credential-shaped value — rejected."""


class AdapterIntegrityError(ValueError):
    """A record violates the source-linked discipline (e.g. an eval with no input/output
    reference)."""


class AdapterExecutionViolation(ValueError):
    """A direct store caller attempted to persist an impossible execution result."""


def _guard_ids(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None and _has_secret(str(value)):
            raise AdapterSecurityError(
                f"structural identifier {name!r} carries a credential-shaped value")


def _guard_id_lists(**fields: list[str] | None) -> None:
    for name, values in fields.items():
        for v in values or []:
            if _has_secret(str(v)):
                raise AdapterSecurityError(
                    f"structural identifier list {name!r} carries a credential-shaped value")


class RuntimeAdapterStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None,
                 execution_mode: str | None = None) -> None:
        resolved = Path(db_path) if db_path is not None else runtime_adapters_db_path()
        self._db_path = ensure_confined(resolved)
        self._writer = writer
        self._execution_mode = execution_mode
        self._conn: sqlite3.Connection | None = None

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
        event = build_adapter_event(event_type, **fields)
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

    def register_definition(self, d: RuntimeAdapterDefinition, *, actor: str = "aria"
                            ) -> RuntimeAdapterDefinition:
        if self.get_definition(d.adapter_id) is not None:
            raise AdapterAlreadyExists(f"adapter {d.adapter_id!r} already registered")
        _guard_ids(adapter_id=d.adapter_id)
        _guard_id_lists(required_permissions=d.required_permissions, allowed_scopes=d.allowed_scopes)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO adapter_definition (adapter_id, name, vendor, adapter_type, description, "
                "supported_task_types, supported_execution_modes, required_permissions, allowed_scopes, "
                "risk_level, enabled, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    d.adapter_id, sanitize_text(d.name), sanitize_text(d.vendor), d.adapter_type.value,
                    sanitize_text(d.description), _slist(d.supported_task_types),
                    _jlist(d.supported_execution_modes), _jlist(d.required_permissions),
                    _jlist(d.allowed_scopes), d.risk_level.value, 1 if d.enabled else 0,
                    d.status.value, _iso(d.created_at), _iso(d.updated_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.runtime_adapter_registered, task_id=d.adapter_id,
                          actor=actor, actor_type=ActorType.aria, adapter_id=d.adapter_id,
                          adapter_type=d.adapter_type.value, correlation_id=d.adapter_id,
                          status=d.status.value, risk_level=d.risk_level.value, outcome="registered")
        self.flush_outbox()
        return self.get_definition(d.adapter_id)  # type: ignore[return-value]

    def get_definition(self, adapter_id: str) -> RuntimeAdapterDefinition | None:
        row = self._connect().execute("SELECT * FROM adapter_definition WHERE adapter_id=?",
                                      (adapter_id,)).fetchone()
        return self._row_to_definition(row) if row else None

    def list_definitions(self, *, enabled: bool | None = None,
                        adapter_type: str | None = None) -> list[RuntimeAdapterDefinition]:
        conn = self._connect()
        clauses, params = [], []
        if enabled is not None:
            clauses.append("enabled=?"); params.append(1 if enabled else 0)
        if adapter_type is not None:
            clauses.append("adapter_type=?"); params.append(adapter_type)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM adapter_definition{where} ORDER BY created_at, adapter_id",
                            params).fetchall()
        return [self._row_to_definition(r) for r in rows]

    def set_enabled(self, adapter_id: str, enabled: bool, *, actor: str = "aria"
                    ) -> RuntimeAdapterDefinition:
        conn = self._connect()
        d = self.get_definition(adapter_id)
        if d is None:
            raise AdapterNotFound(f"adapter {adapter_id!r} not found")
        event = (LedgerEventType.runtime_adapter_enabled if enabled
                 else LedgerEventType.runtime_adapter_disabled)
        # A future-stub adapter stays a future_stub even when 'enabled' (it still can't run).
        new_status = d.status
        if d.adapter_type is AdapterType.internal_mock:
            new_status = AdapterStatus.enabled if enabled else AdapterStatus.disabled
        with conn:
            conn.execute("UPDATE adapter_definition SET enabled=?, status=?, updated_at=? "
                         "WHERE adapter_id=?",
                         (1 if enabled else 0, new_status.value, _iso(_now()), adapter_id))
            self._enqueue(conn, event, task_id=adapter_id, actor=actor, actor_type=ActorType.aria,
                          adapter_id=adapter_id, adapter_type=d.adapter_type.value,
                          correlation_id=adapter_id, status=new_status.value,
                          outcome="enabled" if enabled else "disabled")
        self.flush_outbox()
        return self.get_definition(adapter_id)  # type: ignore[return-value]

    # ── Capabilities ─────────────────────────────────────────────────────────

    def add_capability(self, c: RuntimeAdapterCapability) -> RuntimeAdapterCapability:
        _guard_ids(capability_id=c.capability_id, adapter_id=c.adapter_id)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO adapter_capability (capability_id, adapter_id, capability_name, task_type, "
                "input_schema, output_schema, permission_scope, risk_level, requires_approval, "
                "evidence_required, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    c.capability_id, c.adapter_id, sanitize_text(c.capability_name), c.task_type,
                    json.dumps(_sanitize_payload(c.input_schema)),
                    json.dumps(_sanitize_payload(c.output_schema)), sanitize_text(c.permission_scope),
                    c.risk_level.value, 1 if c.requires_approval else 0,
                    1 if c.evidence_required else 0, c.status,
                ),
            )
        return c

    def list_capabilities(self, adapter_id: str) -> list[RuntimeAdapterCapability]:
        rows = self._connect().execute(
            "SELECT * FROM adapter_capability WHERE adapter_id=? ORDER BY capability_id",
            (adapter_id,)).fetchall()
        return [self._row_to_capability(r) for r in rows]

    # ── Requests ─────────────────────────────────────────────────────────────

    def create_request(self, r: RuntimeAdapterRequest, *, actor: str = "aria"
                        ) -> RuntimeAdapterRequest:
        _guard_ids(request_id=r.request_id, adapter_id=r.adapter_id, goal_id=r.goal_id,
                   task_id=r.task_id, workspace_id=r.workspace_id)
        _guard_id_lists(source_refs=r.source_refs, evidence_refs=r.evidence_refs)
        if self.get_definition(r.adapter_id) is None:
            raise AdapterNotFound(f"adapter {r.adapter_id!r} not found")
        if not r.source_refs:
            raise AdapterIntegrityError("a runtime adapter request must cite source_refs")
        if r.status is not RequestStatus.created:
            raise AdapterExecutionViolation("a new runtime adapter request must start as created")
        if r.execution_mode is not ExecutionMode.preview:
            raise AdapterExecutionViolation(
                "a new runtime adapter request must start in preview mode")
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO adapter_request (request_id, adapter_id, goal_id, task_id, workspace_id, "
                "task_type, input_payload, source_refs, evidence_refs, requested_by, execution_mode, "
                "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r.request_id, r.adapter_id, r.goal_id, r.task_id, r.workspace_id, r.task_type,
                    json.dumps(_sanitize_payload(r.input_payload)), _jlist(r.source_refs),
                    _jlist(r.evidence_refs), sanitize_text(r.requested_by), r.execution_mode.value,
                    r.status.value, _iso(r.created_at), _iso(r.updated_at),
                ),
            )
            self._enqueue(conn, LedgerEventType.runtime_adapter_request_created, task_id=r.request_id,
                          actor=actor, actor_type=ActorType.aria, request_id=r.request_id,
                          adapter_id=r.adapter_id, goal_id=r.goal_id, task_ref=r.task_id,
                          workspace_id=r.workspace_id, execution_mode=r.execution_mode.value,
                          correlation_id=r.request_id, status=r.status.value, outcome="request_created")
        self.flush_outbox()
        return self.get_request(r.request_id)  # type: ignore[return-value]

    def get_request(self, request_id: str) -> RuntimeAdapterRequest | None:
        row = self._connect().execute("SELECT * FROM adapter_request WHERE request_id=?",
                                      (request_id,)).fetchone()
        return self._row_to_request(row) if row else None

    def list_requests(self, *, adapter_id: str | None = None) -> list[RuntimeAdapterRequest]:
        conn = self._connect()
        if adapter_id is not None:
            rows = conn.execute("SELECT * FROM adapter_request WHERE adapter_id=? "
                               "ORDER BY created_at, request_id", (adapter_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM adapter_request ORDER BY created_at, "
                               "request_id").fetchall()
        return [self._row_to_request(r) for r in rows]

    # ── Receipts (records an outcome + advances request status, one txn) ──────

    def record_receipt(self, receipt: RuntimeAdapterReceipt, *, adapter_type: str | None = None,
                      goal_id: str | None = None, workspace_id: str | None = None,
                      actor: str = "aria") -> RuntimeAdapterReceipt:
        _guard_ids(receipt_id=receipt.receipt_id, request_id=receipt.request_id,
                   adapter_id=receipt.adapter_id)
        _guard_id_lists(source_refs=receipt.source_refs, evidence_refs=receipt.evidence_refs,
                        ledger_refs=receipt.ledger_refs)
        conn = self._connect()
        request = self.get_request(receipt.request_id)
        if request is None:
            raise AdapterNotFound(f"request {receipt.request_id!r} not found")
        definition = self.get_definition(request.adapter_id)
        if definition is None:
            raise AdapterNotFound(f"adapter {request.adapter_id!r} not found")
        self._validate_receipt_authority(receipt, request, definition)
        req_status = _RECEIPT_TO_REQUEST_STATUS[receipt.status]
        lifecycle_event = _OUTCOME_EVENT[receipt.status]
        resolved_goal_id = goal_id if goal_id is not None else request.goal_id
        resolved_workspace_id = workspace_id if workspace_id is not None else request.workspace_id
        with conn:
            conn.execute(
                "INSERT INTO adapter_receipt (receipt_id, request_id, adapter_id, execution_mode, "
                "status, output_summary, output_payload, source_refs, evidence_refs, external_ref, "
                "safe_error, created_at, ledger_refs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt.receipt_id, receipt.request_id, receipt.adapter_id,
                    receipt.execution_mode.value, receipt.status.value,
                    sanitize_text(receipt.output_summary),
                    json.dumps(_sanitize_payload(receipt.output_payload)), _jlist(receipt.source_refs),
                    _jlist(receipt.evidence_refs), sanitize_text(receipt.external_ref),
                    sanitize_text(receipt.safe_error), _iso(receipt.created_at),
                    _jlist(receipt.ledger_refs),
                ),
            )
            conn.execute("UPDATE adapter_request SET status=?, updated_at=? WHERE request_id=?",
                         (req_status.value, _iso(_now()), receipt.request_id))
            risk = "medium" if receipt.status is ReceiptStatus.failed else "low"
            self._enqueue(conn, lifecycle_event, task_id=receipt.request_id, actor=actor,
                          actor_type=ActorType.aria, request_id=receipt.request_id,
                          adapter_id=receipt.adapter_id, adapter_type=definition.adapter_type.value,
                          receipt_id=receipt.receipt_id, goal_id=resolved_goal_id,
                          workspace_id=resolved_workspace_id,
                          execution_mode=receipt.execution_mode.value, correlation_id=receipt.request_id,
                          status=receipt.status.value, safe_error=receipt.safe_error, risk_level=risk,
                          outcome=receipt.status.value)
            self._enqueue(conn, LedgerEventType.runtime_adapter_receipt_created,
                          task_id=receipt.receipt_id, actor=actor, actor_type=ActorType.aria,
                          request_id=receipt.request_id, adapter_id=receipt.adapter_id,
                          receipt_id=receipt.receipt_id, execution_mode=receipt.execution_mode.value,
                          correlation_id=receipt.request_id, status=receipt.status.value,
                          outcome="receipt_created")
        self.flush_outbox()
        return self.get_receipt(receipt.receipt_id)  # type: ignore[return-value]

    @staticmethod
    def _validate_receipt_authority(receipt: RuntimeAdapterReceipt,
                                    request: RuntimeAdapterRequest,
                                    definition: RuntimeAdapterDefinition) -> None:
        if receipt.adapter_id != request.adapter_id:
            raise AdapterExecutionViolation(
                "receipt adapter_id must match the stored request adapter_id")
        if receipt.execution_mode is ExecutionMode.live:
            raise AdapterExecutionViolation("live runtime adapter receipts are disabled in V4.1")
        if receipt.status is ReceiptStatus.previewed:
            if receipt.execution_mode is not ExecutionMode.preview:
                raise AdapterExecutionViolation("previewed receipts must use preview mode")
            if receipt.external_ref is not None:
                raise AdapterExecutionViolation("preview receipts cannot carry external_ref")
            return
        if receipt.status is ReceiptStatus.blocked:
            if receipt.external_ref is not None:
                raise AdapterExecutionViolation("blocked receipts cannot carry external_ref")
            return
        if receipt.status is ReceiptStatus.failed:
            if receipt.external_ref is not None:
                raise AdapterExecutionViolation("failed receipts cannot carry external_ref")
            return
        if definition.adapter_type is not AdapterType.internal_mock:
            raise AdapterExecutionViolation(
                "only internal_mock can persist completed runtime adapter receipts in V4.1")
        if not receipt.evidence_refs:
            raise AdapterIntegrityError("completed runtime adapter receipts must cite evidence_refs")
        if receipt.status is ReceiptStatus.dry_run_completed:
            if receipt.execution_mode is not ExecutionMode.dry_run:
                raise AdapterExecutionViolation("dry_run_completed receipts must use dry_run mode")
            if receipt.external_ref is not None:
                raise AdapterExecutionViolation("dry-run receipts cannot carry external_ref")
            return
        if receipt.status is ReceiptStatus.mock_completed:
            expected_ref = f"mock://internal_mock/{request.request_id}"
            if receipt.execution_mode is not ExecutionMode.mock:
                raise AdapterExecutionViolation("mock_completed receipts must use mock mode")
            if receipt.external_ref != expected_ref:
                raise AdapterExecutionViolation(
                    "mock receipts must carry the canonical internal_mock external_ref")
            return
        raise AdapterExecutionViolation(f"unsupported receipt status {receipt.status.value!r}")

    def get_receipt(self, receipt_id: str) -> RuntimeAdapterReceipt | None:
        row = self._connect().execute("SELECT * FROM adapter_receipt WHERE receipt_id=?",
                                      (receipt_id,)).fetchone()
        return self._row_to_receipt(row) if row else None

    def list_receipts(self, *, request_id: str | None = None,
                    adapter_id: str | None = None) -> list[RuntimeAdapterReceipt]:
        conn = self._connect()
        clauses, params = [], []
        if request_id is not None:
            clauses.append("request_id=?"); params.append(request_id)
        if adapter_id is not None:
            clauses.append("adapter_id=?"); params.append(adapter_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM adapter_receipt{where} ORDER BY created_at, receipt_id",
                            params).fetchall()
        return [self._row_to_receipt(r) for r in rows]

    # ── Evaluation records (source-linked; no ledger event) ──────────────────

    def create_eval_record(self, e: EvaluationRecord) -> EvaluationRecord:
        if not e.input_ref or not e.output_ref:
            raise AdapterIntegrityError("an evaluation record must be source-linked "
                                        "(input_ref and output_ref required)")
        _guard_ids(eval_id=e.eval_id, input_ref=e.input_ref, output_ref=e.output_ref,
                   adapter_id=e.adapter_id, model_id=e.model_id)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO eval_record (eval_id, goal_id, task_id, adapter_id, model_id, "
                "prompt_version, skill_version, input_ref, output_ref, expected_behavior, "
                "actual_behavior, score, pass_fail, failure_reason, human_label, cost_estimate, "
                "latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    e.eval_id, e.goal_id, e.task_id, e.adapter_id, e.model_id, e.prompt_version,
                    e.skill_version, e.input_ref, e.output_ref, sanitize_text(e.expected_behavior),
                    sanitize_text(e.actual_behavior), e.score, e.pass_fail.value,
                    sanitize_text(e.failure_reason), sanitize_text(e.human_label), e.cost_estimate,
                    e.latency_ms, _iso(e.created_at),
                ),
            )
        return e

    def list_eval_records(self, *, adapter_id: str | None = None) -> list[EvaluationRecord]:
        conn = self._connect()
        if adapter_id is not None:
            rows = conn.execute("SELECT * FROM eval_record WHERE adapter_id=? ORDER BY created_at",
                               (adapter_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM eval_record ORDER BY created_at").fetchall()
        return [self._row_to_eval(r) for r in rows]

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_definition(row: sqlite3.Row) -> RuntimeAdapterDefinition:
        return RuntimeAdapterDefinition(
            adapter_id=row["adapter_id"], name=row["name"], vendor=row["vendor"],
            adapter_type=AdapterType(row["adapter_type"]), description=row["description"],
            supported_task_types=json.loads(row["supported_task_types"]),
            supported_execution_modes=[ExecutionMode(m) for m in
                                       json.loads(row["supported_execution_modes"])],
            required_permissions=json.loads(row["required_permissions"]),
            allowed_scopes=json.loads(row["allowed_scopes"]), risk_level=RiskLevel(row["risk_level"]),
            enabled=bool(row["enabled"]), status=AdapterStatus(row["status"]),
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_capability(row: sqlite3.Row) -> RuntimeAdapterCapability:
        return RuntimeAdapterCapability(
            capability_id=row["capability_id"], adapter_id=row["adapter_id"],
            capability_name=row["capability_name"], task_type=row["task_type"],
            input_schema=json.loads(row["input_schema"]), output_schema=json.loads(row["output_schema"]),
            permission_scope=row["permission_scope"], risk_level=RiskLevel(row["risk_level"]),
            requires_approval=bool(row["requires_approval"]),
            evidence_required=bool(row["evidence_required"]), status=row["status"],
        )

    @staticmethod
    def _row_to_request(row: sqlite3.Row) -> RuntimeAdapterRequest:
        return RuntimeAdapterRequest(
            request_id=row["request_id"], adapter_id=row["adapter_id"], goal_id=row["goal_id"],
            task_id=row["task_id"], workspace_id=row["workspace_id"], task_type=row["task_type"],
            input_payload=json.loads(row["input_payload"]), source_refs=json.loads(row["source_refs"]),
            evidence_refs=json.loads(row["evidence_refs"]), requested_by=row["requested_by"],
            execution_mode=ExecutionMode(row["execution_mode"]), status=RequestStatus(row["status"]),
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_receipt(row: sqlite3.Row) -> RuntimeAdapterReceipt:
        return RuntimeAdapterReceipt(
            receipt_id=row["receipt_id"], request_id=row["request_id"], adapter_id=row["adapter_id"],
            execution_mode=ExecutionMode(row["execution_mode"]), status=ReceiptStatus(row["status"]),
            output_summary=row["output_summary"], output_payload=json.loads(row["output_payload"]),
            source_refs=json.loads(row["source_refs"]), evidence_refs=json.loads(row["evidence_refs"]),
            external_ref=row["external_ref"], safe_error=row["safe_error"],
            created_at=_parse_dt(row["created_at"]), ledger_refs=json.loads(row["ledger_refs"]),
        )

    @staticmethod
    def _row_to_eval(row: sqlite3.Row) -> EvaluationRecord:
        return EvaluationRecord(
            eval_id=row["eval_id"], goal_id=row["goal_id"], task_id=row["task_id"],
            adapter_id=row["adapter_id"], model_id=row["model_id"], prompt_version=row["prompt_version"],
            skill_version=row["skill_version"], input_ref=row["input_ref"], output_ref=row["output_ref"],
            expected_behavior=row["expected_behavior"], actual_behavior=row["actual_behavior"],
            score=row["score"], pass_fail=EvalOutcome(row["pass_fail"]),
            failure_reason=row["failure_reason"], human_label=row["human_label"],
            cost_estimate=row["cost_estimate"], latency_ms=row["latency_ms"],
            created_at=_parse_dt(row["created_at"]),
        )
