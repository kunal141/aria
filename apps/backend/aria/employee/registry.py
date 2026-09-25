"""
Persistent employee identity and the derived employment record.

Closes the audit finding that made "hire an AI employee" impossible to claim: agents
were minted with ``uuid4()`` per goal and every read was scoped ``WHERE goal_id=?``, so
an employee was destroyed after each task. Nothing survived to review, and therefore
nothing could be earned.

Two design choices carry most of the weight:

1. **The record is derived, never stored.** Rates are recomputed from persisted
   outcomes on every read, so a summary can never drift from the work that produced it
   — the failure mode that makes performance dashboards untrustworthy.
2. **An empty record reports ``None``, not zero.** "No data" and "zero percent" are
   different claims, and only one of them is honest about a new hire.

A new employee starts on probation at tier 1 (read-only). Nothing here promotes
anybody: authority changes are a separate, human-signed decision.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aria.goals.sanitize import sanitize_text
from aria.memory_v2.paths import employee_registry_db_path, ensure_confined

_SCHEMA = """
CREATE TABLE IF NOT EXISTS employee (
    employee_id     TEXT PRIMARY KEY,
    role_key        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    human_sponsor   TEXT NOT NULL,
    department      TEXT NOT NULL DEFAULT 'engineering',
    status          TEXT NOT NULL DEFAULT 'probation',
    authority_tier  INTEGER NOT NULL DEFAULT 1,
    hired_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employee_status_event (
    event_id    TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    status      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status_employee ON employee_status_event(employee_id);
CREATE TABLE IF NOT EXISTS employee_outcome (
    employee_id TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    passed      INTEGER NOT NULL,
    corrected   INTEGER NOT NULL DEFAULT 0,
    escalated   INTEGER NOT NULL DEFAULT 0,
    cost        REAL NOT NULL DEFAULT 0,
    latency_ms  INTEGER NOT NULL DEFAULT 0,
    at          TEXT NOT NULL,
    PRIMARY KEY (employee_id, run_id)
);
"""


class EmploymentStatus(str, Enum):
    probation = "probation"
    active = "active"
    restricted = "restricted"
    suspended = "suspended"
    retired = "retired"


#: Only these may be assigned new work. Probation can work — supervised, at tier 1.
_WORKING_STATUSES = {EmploymentStatus.probation, EmploymentStatus.active}


class EmployeeNotFound(KeyError):
    """No employee with that id in this tenant."""


class EmployeeAlreadyHired(ValueError):
    """A role key is already filled."""


def _now() -> datetime:
    return datetime.now(UTC)


def _safe(value: str, field: str) -> str:
    """Reject credential-shaped structural values; sanitize the rest."""
    cleaned = sanitize_text(value) or ""
    if cleaned != value:
        raise ValueError(f"{field} cannot contain credential-shaped text")
    return cleaned.strip()


class Employee(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    role_key: str
    display_name: str
    human_sponsor: str
    department: str
    status: EmploymentStatus
    authority_tier: int
    hired_at: datetime

    @property
    def can_accept_work(self) -> bool:
        return self.status in _WORKING_STATUSES


class StatusEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    status: EmploymentStatus
    actor: str
    reason: str
    at: datetime


class EmploymentRecord(BaseModel):
    """Derived performance history. Recomputed on read, never stored."""
    model_config = ConfigDict(frozen=True)

    employee_id: str
    total_runs: int
    passed_runs: int
    correction_count: int
    escalation_count: int
    total_cost: float
    median_latency_ms: int | None
    #: ``None`` when there is no work yet — "no data" is not "zero percent".
    quality_pass_rate: float | None


class EmployeeRegistry:
    """Tenant-scoped employee store. One SQLite file per tenant root."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = ensure_confined(
            Path(db_path) if db_path is not None else employee_registry_db_path()
        )
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Hiring and lifecycle ─────────────────────────────────────────────────

    def hire(
        self, *, role_key: str, display_name: str, human_sponsor: str,
        department: str = "engineering",
    ) -> Employee:
        role_key = _safe(role_key, "role_key")
        sponsor = _safe(human_sponsor, "human_sponsor")
        name = sanitize_text(display_name) or role_key
        conn = self._connect()
        if conn.execute("SELECT 1 FROM employee WHERE role_key=?", (role_key,)).fetchone():
            raise EmployeeAlreadyHired(f"role {role_key!r} is already filled")
        employee = Employee(
            employee_id=f"emp-{uuid.uuid4().hex[:12]}", role_key=role_key,
            display_name=name, human_sponsor=sponsor,
            department=sanitize_text(department) or "engineering",
            status=EmploymentStatus.probation, authority_tier=1, hired_at=_now(),
        )
        with conn:
            conn.execute(
                "INSERT INTO employee (employee_id, role_key, display_name, human_sponsor,"
                " department, status, authority_tier, hired_at) VALUES (?,?,?,?,?,?,?,?)",
                (employee.employee_id, employee.role_key, employee.display_name,
                 employee.human_sponsor, employee.department, employee.status.value,
                 employee.authority_tier, employee.hired_at.isoformat()),
            )
            self._append_status(conn, employee.employee_id, employee.status,
                                actor=sponsor, reason="hired")
        return employee

    def get(self, employee_id: str) -> Employee:
        row = self._connect().execute(
            "SELECT * FROM employee WHERE employee_id=?", (employee_id,)).fetchone()
        if row is None:
            raise EmployeeNotFound(f"unknown employee {employee_id!r}")
        return Employee(
            employee_id=row["employee_id"], role_key=row["role_key"],
            display_name=row["display_name"], human_sponsor=row["human_sponsor"],
            department=row["department"], status=EmploymentStatus(row["status"]),
            authority_tier=row["authority_tier"],
            hired_at=datetime.fromisoformat(row["hired_at"]),
        )

    def list_employees(self) -> list[Employee]:
        rows = self._connect().execute(
            "SELECT employee_id FROM employee ORDER BY hired_at, employee_id").fetchall()
        return [self.get(row["employee_id"]) for row in rows]

    def set_status(
        self, employee_id: str, status: EmploymentStatus, *, actor: str, reason: str = "",
    ) -> Employee:
        self.get(employee_id)  # existence check
        conn = self._connect()
        with conn:
            conn.execute("UPDATE employee SET status=? WHERE employee_id=?",
                         (status.value, employee_id))
            self._append_status(conn, employee_id, status, actor=actor, reason=reason)
        return self.get(employee_id)

    @staticmethod
    def _append_status(
        conn: sqlite3.Connection, employee_id: str, status: EmploymentStatus,
        *, actor: str, reason: str,
    ) -> None:
        conn.execute(
            "INSERT INTO employee_status_event (event_id, employee_id, status, actor,"
            " reason, at) VALUES (?,?,?,?,?,?)",
            (f"evt-{uuid.uuid4().hex[:12]}", employee_id, status.value,
             sanitize_text(actor) or "unknown", sanitize_text(reason) or "",
             _now().isoformat()),
        )

    def status_history(self, employee_id: str) -> list[StatusEvent]:
        rows = self._connect().execute(
            "SELECT * FROM employee_status_event WHERE employee_id=? ORDER BY at, event_id",
            (employee_id,)).fetchall()
        return [
            StatusEvent(
                employee_id=row["employee_id"], status=EmploymentStatus(row["status"]),
                actor=row["actor"], reason=row["reason"],
                at=datetime.fromisoformat(row["at"]),
            )
            for row in rows
        ]

    # ── Outcomes and the derived record ──────────────────────────────────────

    def record_outcome(
        self, employee_id: str, *, run_id: str, passed: bool, corrected: bool,
        escalated: bool, cost: float, latency_ms: int,
    ) -> None:
        """Record one completed run. Idempotent per ``(employee_id, run_id)``."""
        self.get(employee_id)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO employee_outcome (employee_id, run_id, passed,"
                " corrected, escalated, cost, latency_ms, at) VALUES (?,?,?,?,?,?,?,?)",
                (employee_id, run_id, int(passed), int(corrected), int(escalated),
                 float(cost), int(latency_ms), _now().isoformat()),
            )

    def employment_record(
        self, employee_id: str, *, last_n: int | None = None
    ) -> EmploymentRecord:
        """Recompute the record from persisted outcomes.

        ``last_n`` limits to the most recent runs, so a manager can ask "how has this
        employee performed lately" rather than being anchored to its whole history.
        """
        self.get(employee_id)
        query = ("SELECT * FROM employee_outcome WHERE employee_id=?"
                 " ORDER BY at DESC, run_id DESC")
        params: tuple = (employee_id,)
        if last_n is not None:
            query += " LIMIT ?"
            params = (employee_id, int(last_n))
        rows = self._connect().execute(query, params).fetchall()

        total = len(rows)
        passed = sum(int(row["passed"]) for row in rows)
        latencies = [int(row["latency_ms"]) for row in rows]
        return EmploymentRecord(
            employee_id=employee_id,
            total_runs=total,
            passed_runs=passed,
            correction_count=sum(int(row["corrected"]) for row in rows),
            escalation_count=sum(int(row["escalated"]) for row in rows),
            total_cost=round(sum(float(row["cost"]) for row in rows), 6),
            median_latency_ms=int(statistics.median(latencies)) if latencies else None,
            quality_pass_rate=(passed / total) if total else None,
        )


__all__ = [
    "Employee",
    "EmployeeAlreadyHired",
    "EmployeeNotFound",
    "EmployeeRegistry",
    "EmploymentRecord",
    "EmploymentStatus",
    "StatusEvent",
]
