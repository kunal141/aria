"""
SQLite manager-dashboard store (V3.10).

Persists READ-ONLY aggregate artifacts: dashboard snapshots, ROI summaries, and V3
proof records. Same discipline as the V2/V3 stores: confined to
``${ARIA_DATA_DIR}/dashboard/store.sqlite`` (gitignored, never inside the importable
``aria`` source package), no import-time DB creation, lazy schema, restart-safe, and
every write emits a Work Ledger event through a transactional **audit outbox**.

Nothing here executes work, approves anything, or performs an external action. Free
text + JSON blobs are masked for secrets; structural ids / provenance refs that carry
a credential shape are rejected; a snapshot/proof with no source reference is rejected.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.dashboard.audit import build_dashboard_event
from aria.dashboard.models import ManagerDashboardSnapshot, ROISummary
from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.paths import dashboard_db_path, ensure_confined

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboard_snapshot (
    snapshot_id   TEXT PRIMARY KEY,
    generated_at  TEXT NOT NULL,
    workspace_id  TEXT,
    snapshot_json TEXT NOT NULL,
    source_refs   TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roi_summary (
    roi_summary_id          TEXT PRIMARY KEY,
    snapshot_id             TEXT,
    estimated_minutes_saved INTEGER NOT NULL DEFAULT 0,
    estimated_cost_saved    REAL,
    roi_json                TEXT NOT NULL,
    evidence_refs           TEXT NOT NULL DEFAULT '[]',
    created_at              TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proof_run (
    proof_id     TEXT PRIMARY KEY,
    workspace_id TEXT,
    summary      TEXT NOT NULL DEFAULT '',
    proof_json   TEXT NOT NULL,
    source_refs  TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL
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


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _jlist(items: list[str]) -> str:
    return json.dumps([str(x) for x in items])


def _has_secret(value: str) -> bool:
    return bool(value) and sanitize_text(value) != value


def _sanitize_json(blob: str) -> str:
    """Defensively mask any credential-shaped substring in an aggregated JSON blob.
    Dashboard data comes from already-sanitised stores, so this is normally a no-op."""
    return sanitize_text(blob) or "{}"


class DashboardNotFound(ValueError):
    """A snapshot / roi / proof id did not resolve."""


class DashboardSecurityError(ValueError):
    """A structural id / provenance ref carries a credential-shaped value — rejected."""


class DashboardIntegrityError(ValueError):
    """A snapshot / proof violates the source-cited discipline (no source reference)."""


def _guard_ids(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None and _has_secret(str(value)):
            raise DashboardSecurityError(
                f"structural identifier {name!r} carries a credential-shaped value")


def _guard_id_lists(**fields: list[str] | None) -> None:
    for name, values in fields.items():
        for v in values or []:
            if _has_secret(str(v)):
                raise DashboardSecurityError(
                    f"structural identifier list {name!r} carries a credential-shaped value")


def _validate_roi(roi: ROISummary) -> None:
    """The store is the FINAL proof authority for ROI: it refuses to persist a claim
    that is not estimated, is negative, claims value without evidence, or whose method
    did not come from the approved calculator (``aria.dashboard.roi``)."""
    from aria.dashboard.roi import ROI_COST_MARKER, ROI_METHOD_MARKER

    if roi.estimated is not True:
        raise DashboardIntegrityError("ROI must be marked estimated=True (transparent estimate only)")
    if roi.estimated_minutes_saved < 0:
        raise DashboardIntegrityError("ROI estimated_minutes_saved cannot be negative")
    for field in ("tasks_completed", "drafts_created", "routines_completed",
                  "action_previews_created", "approvals_prepared"):
        if getattr(roi, field) < 0:
            raise DashboardIntegrityError(f"ROI {field} cannot be negative")
    if roi.estimated_cost_saved is not None and roi.estimated_cost_saved < 0:
        raise DashboardIntegrityError("ROI estimated_cost_saved cannot be negative")
    if ROI_METHOD_MARKER not in (roi.calculation_method or ""):
        raise DashboardIntegrityError(
            "ROI calculation_method must come from the approved estimated-minutes calculator")
    if roi.estimated_cost_saved is not None and ROI_COST_MARKER not in roi.calculation_method:
        raise DashboardIntegrityError(
            "ROI cost must be derived through the approved calculator (minutes/60 × hourly_cost)")
    if (roi.estimated_minutes_saved > 0 or roi.estimated_cost_saved is not None) and not roi.evidence_refs:
        raise DashboardIntegrityError("a value-claiming ROI must cite evidence references")


def _validate_snapshot(s: ManagerDashboardSnapshot) -> None:
    """The store refuses to persist a snapshot that contradicts a V3 boundary —
    notably a non-zero ``live_receipts`` (no real live execution exists in V3.10)."""
    if s.action_summary.live_receipts != 0:
        raise DashboardIntegrityError(
            "live_receipts must be 0 — no real live execution exists in V3.10")
    if "external write" not in (s.boundary_note or "").lower():
        raise DashboardIntegrityError(
            "snapshot boundary note must preserve the no-external-write boundary")
    if s.roi_summary is not None:
        _validate_roi(s.roi_summary)


# A final V3 proof must preserve these boundary claims; a contradictory proof is refused.
_PROOF_BOUNDARY_MARKERS = ("no external write", "no network", "no live execution")


def _validate_proof_json(proof_json: str) -> None:
    """The store is the FINAL acceptance authority: it refuses to persist a proof
    package that contradicts a V3 boundary (live receipts, external writes), is
    malformed, or drops its no-network / no-external-write / no-live-execution claims —
    even on a direct store call."""
    try:
        data = json.loads(proof_json)
    except (ValueError, TypeError):
        raise DashboardIntegrityError("proof JSON is malformed")
    if not isinstance(data, dict):
        raise DashboardIntegrityError("a V3 proof must be a JSON object")
    snap = data.get("snapshot")
    if isinstance(snap, dict):
        action = snap.get("action_summary")
        if isinstance(action, dict) and (action.get("live_receipts") or 0) != 0:
            raise DashboardIntegrityError("proof snapshot claims live_receipts != 0")
    boundary = str(data.get("boundary", "")).lower()
    if not all(m in boundary for m in _PROOF_BOUNDARY_MARKERS):
        raise DashboardIntegrityError(
            "proof boundary must preserve the no-network / no-external-write / "
            "no-live-execution claims")
    src = data.get("source_refs")
    if src is not None and not src:
        raise DashboardIntegrityError("proof source_refs, if present, must be non-empty")


class DashboardStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None,
                 execution_mode: str | None = None) -> None:
        resolved = Path(db_path) if db_path is not None else dashboard_db_path()
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
        fields.setdefault("execution_mode", self._execution_mode)
        event = build_dashboard_event(event_type, **fields)
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

    # ── Snapshots ────────────────────────────────────────────────────────────

    def create_snapshot(self, s: ManagerDashboardSnapshot, *, actor: str = "aria"
                        ) -> ManagerDashboardSnapshot:
        if not s.source_refs:
            raise DashboardIntegrityError("a dashboard snapshot must cite at least one source reference")
        _validate_snapshot(s)
        _guard_ids(snapshot_id=s.snapshot_id, workspace_id=s.workspace_id)
        _guard_id_lists(source_refs=s.source_refs, ledger_refs=s.ledger_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO dashboard_snapshot (snapshot_id, generated_at, workspace_id, "
                "snapshot_json, source_refs, created_at) VALUES (?,?,?,?,?,?)",
                (s.snapshot_id, _iso(s.generated_at), s.workspace_id,
                 _sanitize_json(s.model_dump_json()), _jlist(s.source_refs), _iso(_now())),
            )
            self._enqueue(conn, LedgerEventType.dashboard_snapshot_created, task_id=s.snapshot_id,
                          actor=actor, actor_type=ActorType.aria, snapshot_id=s.snapshot_id,
                          workspace_id=s.workspace_id, correlation_id=s.snapshot_id, status="created",
                          outcome="snapshot_created")
        self.flush_outbox()
        return self.get_snapshot(s.snapshot_id)  # type: ignore[return-value]

    def get_snapshot(self, snapshot_id: str) -> ManagerDashboardSnapshot | None:
        row = self._connect().execute("SELECT snapshot_json FROM dashboard_snapshot WHERE snapshot_id=?",
                                      (snapshot_id,)).fetchone()
        return ManagerDashboardSnapshot.model_validate_json(row["snapshot_json"]) if row else None

    def list_snapshots(self) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            "SELECT snapshot_id, generated_at, workspace_id FROM dashboard_snapshot "
            "ORDER BY generated_at, snapshot_id").fetchall()
        return [{"snapshot_id": r["snapshot_id"], "generated_at": r["generated_at"],
                 "workspace_id": r["workspace_id"]} for r in rows]

    # ── ROI ──────────────────────────────────────────────────────────────────

    def create_roi(self, roi: ROISummary, *, snapshot_id: str | None = None,
                  workspace_id: str | None = None, actor: str = "aria") -> ROISummary:
        _validate_roi(roi)
        _guard_ids(roi_summary_id=roi.roi_summary_id, snapshot_id=snapshot_id)
        _guard_id_lists(evidence_refs=roi.evidence_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO roi_summary (roi_summary_id, snapshot_id, estimated_minutes_saved, "
                "estimated_cost_saved, roi_json, evidence_refs, created_at) VALUES (?,?,?,?,?,?,?)",
                (roi.roi_summary_id, snapshot_id, roi.estimated_minutes_saved, roi.estimated_cost_saved,
                 _sanitize_json(roi.model_dump_json()), _jlist(roi.evidence_refs), _iso(_now())),
            )
            self._enqueue(conn, LedgerEventType.roi_summary_created, task_id=roi.roi_summary_id,
                          actor=actor, actor_type=ActorType.aria, roi_summary_id=roi.roi_summary_id,
                          snapshot_id=snapshot_id, workspace_id=workspace_id,
                          correlation_id=snapshot_id or roi.roi_summary_id, status="estimated",
                          outcome=f"minutes_saved={roi.estimated_minutes_saved}")
        self.flush_outbox()
        return roi

    def get_roi(self, roi_summary_id: str) -> ROISummary | None:
        row = self._connect().execute("SELECT roi_json FROM roi_summary WHERE roi_summary_id=?",
                                      (roi_summary_id,)).fetchone()
        return ROISummary.model_validate_json(row["roi_json"]) if row else None

    # ── Approval-queue / risk summary events (computed on read; emit-only) ────

    def emit_approval_queue(self, *, count: int, snapshot_id: str | None = None,
                           workspace_id: str | None = None, actor: str = "aria") -> None:
        conn = self._connect()
        task_id = snapshot_id or "dashboard:approval_queue"   # stable, deterministic
        with conn:
            self._enqueue(conn, LedgerEventType.approval_queue_summarized, task_id=task_id, actor=actor,
                          actor_type=ActorType.aria, snapshot_id=snapshot_id, workspace_id=workspace_id,
                          correlation_id=task_id, status="read_only", outcome=f"pending={count}")
        self.flush_outbox()

    def emit_risk_summary(self, *, count: int, high: int, snapshot_id: str | None = None,
                         workspace_id: str | None = None, actor: str = "aria") -> None:
        conn = self._connect()
        task_id = snapshot_id or "dashboard:risk_summary"     # stable, deterministic
        with conn:
            self._enqueue(conn, LedgerEventType.risk_summary_created, task_id=task_id, actor=actor,
                          actor_type=ActorType.aria, snapshot_id=snapshot_id, workspace_id=workspace_id,
                          correlation_id=task_id, status="read_only",
                          outcome=f"risks={count};high={high}")
        self.flush_outbox()

    # ── Proof / acceptance ────────────────────────────────────────────────────

    def create_proof(self, *, proof_id: str, summary: str, proof_json: str,
                    source_refs: list[str], workspace_id: str | None = None,
                    actor: str = "aria") -> dict[str, Any]:
        if not source_refs:
            raise DashboardIntegrityError("a V3 proof record must cite at least one source reference")
        _validate_proof_json(proof_json)
        _guard_ids(proof_id=proof_id, workspace_id=workspace_id)
        _guard_id_lists(source_refs=source_refs)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO proof_run (proof_id, workspace_id, summary, proof_json, source_refs, "
                "created_at) VALUES (?,?,?,?,?,?)",
                (proof_id, workspace_id, sanitize_text(summary), _sanitize_json(proof_json),
                 _jlist(source_refs), _iso(_now())),
            )
            self._enqueue(conn, LedgerEventType.v3_proof_demo_generated, task_id=proof_id, actor=actor,
                          actor_type=ActorType.aria, proof_id=proof_id, workspace_id=workspace_id,
                          correlation_id=proof_id, status="generated", outcome="proof_generated")
        self.flush_outbox()
        return self.get_proof(proof_id)  # type: ignore[return-value]

    def get_proof(self, proof_id: str) -> dict[str, Any] | None:
        row = self._connect().execute("SELECT * FROM proof_run WHERE proof_id=?", (proof_id,)).fetchone()
        if row is None:
            return None
        return {"proof_id": row["proof_id"], "workspace_id": row["workspace_id"],
                "summary": row["summary"], "proof": json.loads(row["proof_json"]),
                "source_refs": json.loads(row["source_refs"])}

    def emit_acceptance(self, *, proof_id: str | None = None, workspace_id: str | None = None,
                       outcome: str = "acceptance_package", actor: str = "aria") -> None:
        conn = self._connect()
        with conn:
            task_id = proof_id or "dashboard:acceptance_package"   # stable, deterministic
            self._enqueue(conn, LedgerEventType.v3_acceptance_package_created, task_id=task_id,
                          actor=actor, actor_type=ActorType.aria, proof_id=proof_id,
                          workspace_id=workspace_id, correlation_id=task_id, status="recorded",
                          outcome=outcome)
        self.flush_outbox()
