"""
SQLite Skill-Evolution store (V3.5).

Persists gaps, proposals, specs, test plans, and evaluations, and drives the
governed proposal lifecycle. Same discipline as the V2/V3 stores:
  - confined to ``${ARIA_DATA_DIR}/skills/store.sqlite`` (gitignored, never inside
    the importable ``aria`` source package);
  - **no import-time DB creation** — schema built lazily on first use;
  - restart-safe;
  - every state transition emits a Work Ledger event through a transactional
    **audit outbox** (state + audit can never diverge).

Documentation/config + registry status ONLY — no production code is modified here,
and nothing auto-activates. Secrets are sanitised out of every persisted string.
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
from aria.memory_v2.paths import ensure_confined, skills_db_path
from aria.skill_evolution.audit import build_skill_event
from aria.skill_evolution.models import (
    SAFE_THRESHOLD,
    GapSourceType,
    RecommendedDecision,
    SkillEvaluation,
    SkillGap,
    SkillProposal,
    SkillProposalStatus,
    SkillSpec,
    SkillTestPlan,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_gap (
    gap_id           TEXT PRIMARY KEY,
    source_type      TEXT NOT NULL,
    source_refs      TEXT NOT NULL DEFAULT '[]',
    description      TEXT NOT NULL,
    repeated_pattern TEXT NOT NULL,
    affected_goals   TEXT NOT NULL DEFAULT '[]',
    affected_tasks   TEXT NOT NULL DEFAULT '[]',
    evidence_refs    TEXT NOT NULL DEFAULT '[]',
    confidence       REAL NOT NULL DEFAULT 0,
    risk_level       TEXT NOT NULL DEFAULT 'low',
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_proposal (
    proposal_id          TEXT PRIMARY KEY,
    gap_id               TEXT NOT NULL,
    name                 TEXT NOT NULL,
    purpose              TEXT NOT NULL,
    target_domain        TEXT NOT NULL,
    expected_inputs      TEXT NOT NULL DEFAULT '[]',
    expected_outputs     TEXT NOT NULL DEFAULT '[]',
    required_tools       TEXT NOT NULL DEFAULT '[]',
    forbidden_tools      TEXT NOT NULL DEFAULT '[]',
    required_permissions TEXT NOT NULL DEFAULT '[]',
    risk_level           TEXT NOT NULL DEFAULT 'low',
    approval_required     INTEGER NOT NULL DEFAULT 1,
    status               TEXT NOT NULL DEFAULT 'proposed',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proposal_status ON skill_proposal(status);
CREATE TABLE IF NOT EXISTS skill_spec (
    spec_id               TEXT PRIMARY KEY,
    proposal_id           TEXT NOT NULL,
    skill_name            TEXT NOT NULL,
    problem_solved        TEXT NOT NULL,
    target_users          TEXT NOT NULL DEFAULT '[]',
    input_schema          TEXT NOT NULL DEFAULT '{}',
    output_schema         TEXT NOT NULL DEFAULT '{}',
    allowed_tools         TEXT NOT NULL DEFAULT '[]',
    forbidden_tools       TEXT NOT NULL DEFAULT '[]',
    memory_access_policy  TEXT NOT NULL DEFAULT 'read-approved-only',
    evidence_requirements TEXT NOT NULL DEFAULT '[]',
    approval_requirements TEXT NOT NULL DEFAULT '',
    risk_classification   TEXT NOT NULL DEFAULT 'low',
    failure_modes         TEXT NOT NULL DEFAULT '[]',
    rollback_plan         TEXT NOT NULL DEFAULT '',
    acceptance_criteria   TEXT NOT NULL DEFAULT '[]',
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spec_proposal ON skill_spec(proposal_id);
CREATE TABLE IF NOT EXISTS skill_test_plan (
    test_plan_id TEXT PRIMARY KEY,
    proposal_id  TEXT NOT NULL,
    spec_id      TEXT NOT NULL,
    test_cases   TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_testplan_proposal ON skill_test_plan(proposal_id);
CREATE TABLE IF NOT EXISTS skill_evaluation (
    evaluation_id        TEXT PRIMARY KEY,
    proposal_id          TEXT NOT NULL,
    spec_id              TEXT NOT NULL,
    test_plan_id         TEXT NOT NULL,
    readiness_score      REAL NOT NULL DEFAULT 0,
    safety_score         REAL NOT NULL DEFAULT 0,
    expected_roi         TEXT NOT NULL DEFAULT 'unknown',
    risk_summary         TEXT NOT NULL DEFAULT 'low',
    missing_requirements TEXT NOT NULL DEFAULT '[]',
    recommended_decision TEXT NOT NULL DEFAULT 'needs_more_work',
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_proposal ON skill_evaluation(proposal_id);
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
    return json.dumps([sanitize_text(x) or "" for x in items])


class SkillNotFound(ValueError):
    """A skill gap / proposal / spec id did not resolve."""


class InvalidSkillTransition(ValueError):
    """An illegal proposal status transition was attempted (state-machine guard).

    Enforced at the STORE authority layer so no caller (service, API, or a direct
    store call) can bypass it — e.g. proposed→activated, reviving a rejected
    proposal, or mutating a terminal one."""

    def __init__(self, proposal_id: str, current: SkillProposalStatus, target: SkillProposalStatus) -> None:
        super().__init__(
            f"illegal skill transition for {proposal_id!r}: {current.value} → {target.value}"
        )
        self.proposal_id = proposal_id
        self.current = current
        self.target = target


# The authoritative skill-proposal state machine. Activation can ONLY be reached
# from a post-evaluation state (the service additionally enforces the safety gate).
# Terminal states (rejected/deprecated/rolled_back) allow NO transition.
_VALID_TRANSITIONS: dict[SkillProposalStatus, frozenset[SkillProposalStatus]] = {
    SkillProposalStatus.draft: frozenset({SkillProposalStatus.proposed, SkillProposalStatus.rejected}),
    SkillProposalStatus.proposed: frozenset({SkillProposalStatus.spec_generated, SkillProposalStatus.rejected}),
    SkillProposalStatus.spec_generated: frozenset({
        SkillProposalStatus.test_plan_generated, SkillProposalStatus.sandbox_ready,
        SkillProposalStatus.rejected,
    }),
    SkillProposalStatus.test_plan_generated: frozenset({
        SkillProposalStatus.sandbox_ready, SkillProposalStatus.rejected,
    }),
    SkillProposalStatus.sandbox_ready: frozenset({SkillProposalStatus.evaluated, SkillProposalStatus.rejected}),
    # NOTE: ``activated`` is DELIBERATELY NOT a valid generic target from any state.
    # The ONLY path to ``activated`` is ``SkillStore.activate_after_approval()``,
    # which re-enforces the approval + safety gate — so a direct ``transition(...)``
    # caller cannot bypass ``decide()`` to activate.
    SkillProposalStatus.evaluated: frozenset({
        SkillProposalStatus.awaiting_approval, SkillProposalStatus.rejected,
    }),
    SkillProposalStatus.awaiting_approval: frozenset({
        SkillProposalStatus.approved, SkillProposalStatus.rejected,
    }),
    SkillProposalStatus.approved: frozenset({SkillProposalStatus.rejected}),
    SkillProposalStatus.activated: frozenset({SkillProposalStatus.deprecated, SkillProposalStatus.rolled_back}),
    SkillProposalStatus.rejected: frozenset(),
    SkillProposalStatus.deprecated: frozenset(),
    SkillProposalStatus.rolled_back: frozenset(),
}

# Only these source states may activate (and only via ``activate_after_approval``).
_ACTIVATABLE_FROM = frozenset({SkillProposalStatus.awaiting_approval, SkillProposalStatus.approved})


def _check_transition(proposal_id: str, current: SkillProposalStatus, target: SkillProposalStatus) -> None:
    if target not in _VALID_TRANSITIONS.get(current, frozenset()):
        raise InvalidSkillTransition(proposal_id, current, target)


class SkillActivationDenied(ValueError):
    """Activation was attempted without a valid approval state or with a failing
    safety score. Enforced at the store authority so even a direct store caller
    cannot activate an unsafe / un-approved skill."""


class SkillStore:
    def __init__(
        self, db_path: Path | str | None = None, *, writer: Any = None,
        execution_mode: str | None = None,
    ) -> None:
        resolved = Path(db_path) if db_path is not None else skills_db_path()
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
        event = build_skill_event(event_type, **fields)
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

    # ── Gaps ─────────────────────────────────────────────────────────────────

    def create_gap(self, gap: SkillGap, *, actor: str = "aria", workspace_id: str | None = None) -> SkillGap:
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO skill_gap (gap_id, source_type, source_refs, description, "
                "repeated_pattern, affected_goals, affected_tasks, evidence_refs, confidence, "
                "risk_level, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    gap.gap_id, gap.source_type.value, _slist(gap.source_refs),
                    sanitize_text(gap.description), sanitize_text(gap.repeated_pattern),
                    _slist(gap.affected_goals), _slist(gap.affected_tasks),
                    _slist(gap.evidence_refs), gap.confidence, gap.risk_level,
                    _iso(gap.created_at),
                ),
            )
            self._enqueue(
                conn, LedgerEventType.skill_gap_detected, task_id=gap.gap_id, actor=actor,
                actor_type=ActorType.aria, gap_id=gap.gap_id, workspace_id=workspace_id,
                correlation_id=gap.gap_id, risk_level=gap.risk_level,
                outcome=f"{gap.source_type.value};confidence={gap.confidence:.2f}",
            )
        self.flush_outbox()
        return self.get_gap(gap.gap_id)  # type: ignore[return-value]

    def get_gap(self, gap_id: str) -> SkillGap | None:
        row = self._connect().execute("SELECT * FROM skill_gap WHERE gap_id=?", (gap_id,)).fetchone()
        return self._row_to_gap(row) if row else None

    def list_gaps(self) -> list[SkillGap]:
        rows = self._connect().execute("SELECT * FROM skill_gap ORDER BY created_at, gap_id").fetchall()
        return [self._row_to_gap(r) for r in rows]

    # ── Proposals ────────────────────────────────────────────────────────────

    def create_proposal(self, p: SkillProposal, *, actor: str = "aria",
                        workspace_id: str | None = None) -> SkillProposal:
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO skill_proposal (proposal_id, gap_id, name, purpose, target_domain, "
                "expected_inputs, expected_outputs, required_tools, forbidden_tools, "
                "required_permissions, risk_level, approval_required, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    p.proposal_id, p.gap_id, sanitize_text(p.name), sanitize_text(p.purpose),
                    sanitize_text(p.target_domain), _slist(p.expected_inputs),
                    _slist(p.expected_outputs), json.dumps(p.required_tools),
                    json.dumps(p.forbidden_tools), json.dumps(p.required_permissions),
                    p.risk_level, 1 if p.approval_required else 0, p.status.value,
                    _iso(p.created_at), _iso(p.updated_at),
                ),
            )
            self._enqueue(
                conn, LedgerEventType.skill_proposal_created, task_id=p.proposal_id, actor=actor,
                actor_type=ActorType.aria, gap_id=p.gap_id, proposal_id=p.proposal_id,
                workspace_id=workspace_id, correlation_id=p.proposal_id, risk_level=p.risk_level,
                approval_required=p.approval_required, outcome="proposed",
            )
        self.flush_outbox()
        return self.get_proposal(p.proposal_id)  # type: ignore[return-value]

    def get_proposal(self, proposal_id: str) -> SkillProposal | None:
        row = self._connect().execute(
            "SELECT * FROM skill_proposal WHERE proposal_id=?", (proposal_id,)
        ).fetchone()
        return self._row_to_proposal(row) if row else None

    def list_proposals(self, *, status: str | None = None) -> list[SkillProposal]:
        conn = self._connect()
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM skill_proposal WHERE status=? ORDER BY created_at, proposal_id",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM skill_proposal ORDER BY created_at, proposal_id"
            ).fetchall()
        return [self._row_to_proposal(r) for r in rows]

    def transition(
        self, proposal_id: str, new_status: SkillProposalStatus, event_type: LedgerEventType, *,
        actor: str = "aria", workspace_id: str | None = None, outcome: str | None = None,
        recommended_decision: str | None = None,
    ) -> SkillProposal:
        """Advance a proposal's status and emit the lifecycle event atomically.
        Rejects any illegal transition at the store authority layer."""
        conn = self._connect()
        p = self.get_proposal(proposal_id)
        if p is None:
            raise SkillNotFound(f"proposal {proposal_id!r} not found")
        _check_transition(proposal_id, p.status, new_status)
        with conn:
            conn.execute(
                "UPDATE skill_proposal SET status=?, updated_at=? WHERE proposal_id=?",
                (new_status.value, _iso(_now()), proposal_id),
            )
            self._enqueue(
                conn, event_type, task_id=proposal_id, actor=actor, actor_type=ActorType.aria,
                gap_id=p.gap_id, proposal_id=proposal_id, workspace_id=workspace_id,
                correlation_id=proposal_id, risk_level=p.risk_level,
                approval_required=p.approval_required, outcome=outcome or new_status.value,
                recommended_decision=recommended_decision,
            )
        self.flush_outbox()
        return self.get_proposal(proposal_id)  # type: ignore[return-value]

    def activate_after_approval(
        self, proposal_id: str, *, actor: str = "aria", workspace_id: str | None = None,
        recommended_decision: str | None = None,
    ) -> SkillProposal:
        """The ONLY path to ``activated``. Re-enforces the approval + safety gate at
        the store authority, so neither a direct store caller nor any non-decide path
        can activate an un-approved or unsafe skill. Emits ``skill_activated``."""
        conn = self._connect()
        p = self.get_proposal(proposal_id)
        if p is None:
            raise SkillNotFound(f"proposal {proposal_id!r} not found")
        if p.status not in _ACTIVATABLE_FROM:
            # e.g. proposed/evaluated/terminal — activation requires an approval state.
            raise InvalidSkillTransition(proposal_id, p.status, SkillProposalStatus.activated)
        ev = self.get_evaluation(proposal_id)
        if ev is None:
            raise SkillActivationDenied(f"proposal {proposal_id!r}: no evaluation; cannot activate")
        if ev.safety_score < SAFE_THRESHOLD:
            raise SkillActivationDenied(
                f"proposal {proposal_id!r}: safety {ev.safety_score:.2f} < {SAFE_THRESHOLD}; "
                "activation denied"
            )
        with conn:
            conn.execute(
                "UPDATE skill_proposal SET status=?, updated_at=? WHERE proposal_id=?",
                (SkillProposalStatus.activated.value, _iso(_now()), proposal_id),
            )
            self._enqueue(
                conn, LedgerEventType.skill_activated, task_id=proposal_id, actor=actor,
                actor_type=ActorType.aria, gap_id=p.gap_id, proposal_id=proposal_id,
                workspace_id=workspace_id, correlation_id=proposal_id, risk_level=p.risk_level,
                approval_required=p.approval_required, outcome="activated",
                recommended_decision=recommended_decision,
            )
        self.flush_outbox()
        return self.get_proposal(proposal_id)  # type: ignore[return-value]

    # ── Specs / test plans / evaluations (persist + advance + emit) ──────────

    def save_spec(self, spec: SkillSpec, new_status: SkillProposalStatus, *, actor: str = "aria",
                 workspace_id: str | None = None) -> SkillSpec:
        conn = self._connect()
        p = self.get_proposal(spec.proposal_id)
        if p is None:
            raise SkillNotFound(f"proposal {spec.proposal_id!r} not found")
        _check_transition(spec.proposal_id, p.status, new_status)   # blocks terminal/illegal revival
        with conn:
            conn.execute(
                "INSERT INTO skill_spec (spec_id, proposal_id, skill_name, problem_solved, "
                "target_users, input_schema, output_schema, allowed_tools, forbidden_tools, "
                "memory_access_policy, evidence_requirements, approval_requirements, "
                "risk_classification, failure_modes, rollback_plan, acceptance_criteria, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    spec.spec_id, spec.proposal_id, sanitize_text(spec.skill_name),
                    sanitize_text(spec.problem_solved), _slist(spec.target_users),
                    json.dumps(spec.input_schema), json.dumps(spec.output_schema),
                    json.dumps(spec.allowed_tools), json.dumps(spec.forbidden_tools),
                    spec.memory_access_policy, _slist(spec.evidence_requirements),
                    sanitize_text(spec.approval_requirements), spec.risk_classification,
                    _slist(spec.failure_modes), sanitize_text(spec.rollback_plan),
                    _slist(spec.acceptance_criteria), _iso(spec.created_at),
                ),
            )
            conn.execute("UPDATE skill_proposal SET status=?, updated_at=? WHERE proposal_id=?",
                         (new_status.value, _iso(_now()), spec.proposal_id))
            self._enqueue(
                conn, LedgerEventType.skill_spec_generated, task_id=spec.proposal_id, actor=actor,
                actor_type=ActorType.aria, gap_id=p.gap_id, proposal_id=spec.proposal_id,
                spec_id=spec.spec_id, workspace_id=workspace_id, correlation_id=spec.proposal_id,
                risk_level=spec.risk_classification, outcome="spec_generated",
            )
        self.flush_outbox()
        return self.get_spec(spec.proposal_id)  # type: ignore[return-value]

    def get_spec(self, proposal_id: str) -> SkillSpec | None:
        row = self._connect().execute(
            "SELECT * FROM skill_spec WHERE proposal_id=? ORDER BY created_at DESC LIMIT 1",
            (proposal_id,)
        ).fetchone()
        return self._row_to_spec(row) if row else None

    def save_test_plan(self, tp: SkillTestPlan, new_status: SkillProposalStatus, *,
                      actor: str = "aria", workspace_id: str | None = None) -> SkillTestPlan:
        conn = self._connect()
        p = self.get_proposal(tp.proposal_id)
        if p is None:
            raise SkillNotFound(f"proposal {tp.proposal_id!r} not found")
        _check_transition(tp.proposal_id, p.status, new_status)
        with conn:
            conn.execute(
                "INSERT INTO skill_test_plan (test_plan_id, proposal_id, spec_id, test_cases, "
                "created_at) VALUES (?,?,?,?,?)",
                (tp.test_plan_id, tp.proposal_id, tp.spec_id, json.dumps(tp.test_cases),
                 _iso(tp.created_at)),
            )
            conn.execute("UPDATE skill_proposal SET status=?, updated_at=? WHERE proposal_id=?",
                         (new_status.value, _iso(_now()), tp.proposal_id))
            self._enqueue(
                conn, LedgerEventType.skill_test_plan_generated, task_id=tp.proposal_id, actor=actor,
                actor_type=ActorType.aria, gap_id=p.gap_id, proposal_id=tp.proposal_id,
                spec_id=tp.spec_id, test_plan_id=tp.test_plan_id, workspace_id=workspace_id,
                correlation_id=tp.proposal_id, outcome=f"cases={len(tp.test_cases)}",
            )
        self.flush_outbox()
        return self.get_test_plan(tp.proposal_id)  # type: ignore[return-value]

    def get_test_plan(self, proposal_id: str) -> SkillTestPlan | None:
        row = self._connect().execute(
            "SELECT * FROM skill_test_plan WHERE proposal_id=? ORDER BY created_at DESC LIMIT 1",
            (proposal_id,)
        ).fetchone()
        return self._row_to_test_plan(row) if row else None

    def save_evaluation(self, ev: SkillEvaluation, new_status: SkillProposalStatus, *,
                       actor: str = "aria", workspace_id: str | None = None) -> SkillEvaluation:
        conn = self._connect()
        p = self.get_proposal(ev.proposal_id)
        if p is None:
            raise SkillNotFound(f"proposal {ev.proposal_id!r} not found")
        _check_transition(ev.proposal_id, p.status, new_status)
        with conn:
            conn.execute(
                "INSERT INTO skill_evaluation (evaluation_id, proposal_id, spec_id, test_plan_id, "
                "readiness_score, safety_score, expected_roi, risk_summary, missing_requirements, "
                "recommended_decision, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ev.evaluation_id, ev.proposal_id, ev.spec_id, ev.test_plan_id,
                    ev.readiness_score, ev.safety_score, ev.expected_roi, ev.risk_summary,
                    _slist(ev.missing_requirements), ev.recommended_decision.value,
                    _iso(ev.created_at),
                ),
            )
            conn.execute("UPDATE skill_proposal SET status=?, updated_at=? WHERE proposal_id=?",
                         (new_status.value, _iso(_now()), ev.proposal_id))
            self._enqueue(
                conn, LedgerEventType.skill_evaluated, task_id=ev.proposal_id, actor=actor,
                actor_type=ActorType.aria, gap_id=p.gap_id, proposal_id=ev.proposal_id,
                spec_id=ev.spec_id, evaluation_id=ev.evaluation_id, workspace_id=workspace_id,
                correlation_id=ev.proposal_id, risk_level=ev.risk_summary,
                recommended_decision=ev.recommended_decision.value,
                outcome=f"readiness={ev.readiness_score:.2f};safety={ev.safety_score:.2f}",
            )
        self.flush_outbox()
        return self.get_evaluation(ev.proposal_id)  # type: ignore[return-value]

    def get_evaluation(self, proposal_id: str) -> SkillEvaluation | None:
        row = self._connect().execute(
            "SELECT * FROM skill_evaluation WHERE proposal_id=? ORDER BY created_at DESC LIMIT 1",
            (proposal_id,)
        ).fetchone()
        return self._row_to_evaluation(row) if row else None

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_gap(row: sqlite3.Row) -> SkillGap:
        return SkillGap(
            gap_id=row["gap_id"], source_type=GapSourceType(row["source_type"]),
            source_refs=json.loads(row["source_refs"]), description=row["description"],
            repeated_pattern=row["repeated_pattern"], affected_goals=json.loads(row["affected_goals"]),
            affected_tasks=json.loads(row["affected_tasks"]), evidence_refs=json.loads(row["evidence_refs"]),
            confidence=row["confidence"], risk_level=row["risk_level"],
            created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_proposal(row: sqlite3.Row) -> SkillProposal:
        return SkillProposal(
            proposal_id=row["proposal_id"], gap_id=row["gap_id"], name=row["name"],
            purpose=row["purpose"], target_domain=row["target_domain"],
            expected_inputs=json.loads(row["expected_inputs"]),
            expected_outputs=json.loads(row["expected_outputs"]),
            required_tools=json.loads(row["required_tools"]),
            forbidden_tools=json.loads(row["forbidden_tools"]),
            required_permissions=json.loads(row["required_permissions"]),
            risk_level=row["risk_level"], approval_required=bool(row["approval_required"]),
            status=SkillProposalStatus(row["status"]),
            created_at=_parse_dt(row["created_at"]), updated_at=_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_spec(row: sqlite3.Row) -> SkillSpec:
        return SkillSpec(
            spec_id=row["spec_id"], proposal_id=row["proposal_id"], skill_name=row["skill_name"],
            problem_solved=row["problem_solved"], target_users=json.loads(row["target_users"]),
            input_schema=json.loads(row["input_schema"]), output_schema=json.loads(row["output_schema"]),
            allowed_tools=json.loads(row["allowed_tools"]), forbidden_tools=json.loads(row["forbidden_tools"]),
            memory_access_policy=row["memory_access_policy"],
            evidence_requirements=json.loads(row["evidence_requirements"]),
            approval_requirements=row["approval_requirements"],
            risk_classification=row["risk_classification"],
            failure_modes=json.loads(row["failure_modes"]), rollback_plan=row["rollback_plan"],
            acceptance_criteria=json.loads(row["acceptance_criteria"]),
            created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_test_plan(row: sqlite3.Row) -> SkillTestPlan:
        return SkillTestPlan(
            test_plan_id=row["test_plan_id"], proposal_id=row["proposal_id"], spec_id=row["spec_id"],
            test_cases=json.loads(row["test_cases"]), created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_evaluation(row: sqlite3.Row) -> SkillEvaluation:
        return SkillEvaluation(
            evaluation_id=row["evaluation_id"], proposal_id=row["proposal_id"], spec_id=row["spec_id"],
            test_plan_id=row["test_plan_id"], readiness_score=row["readiness_score"],
            safety_score=row["safety_score"], expected_roi=row["expected_roi"],
            risk_summary=row["risk_summary"], missing_requirements=json.loads(row["missing_requirements"]),
            recommended_decision=RecommendedDecision(row["recommended_decision"]),
            created_at=_parse_dt(row["created_at"]),
        )
