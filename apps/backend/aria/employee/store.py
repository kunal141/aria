"""Restart-safe authority store for integrated virtual-employee runs."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.employee.models import (
    AttemptStatus,
    EmployeeAttempt,
    EmployeeEvaluation,
    EmployeeRun,
    EmployeeRunStatus,
    RepairPlan,
)
from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType
from aria.ledger.events import (
    ActionTaken,
    ActionTier,
    ArtifactCreated,
    Failed,
    Responded,
    TaskCreated,
    make_envelope,
)
from aria.memory_v2.paths import employee_runs_db_path, ensure_confined

_SCHEMA = """
CREATE TABLE IF NOT EXISTS employee_run (
    run_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    status TEXT NOT NULL,
    current_attempt INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employee_attempt (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS employee_evaluation (
    evaluation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL UNIQUE,
    passed INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employee_repair_plan (
    repair_plan_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    failed_attempt_id TEXT NOT NULL UNIQUE,
    next_attempt_number INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_outbox (
    outbox_id TEXT PRIMARY KEY,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    flushed_at TEXT
);
"""


class EmployeeRunNotFound(ValueError):
    """An integrated run or attempt could not be resolved."""


class EmployeeRunIntegrityError(ValueError):
    """A caller attempted an impossible or uncorrelated lifecycle transition."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _has_secret(value: str | None) -> bool:
    if not value:
        return False
    # Artifact/source references are structural paths.  Inspect each segment so a
    # generated ``<hex>/<word>`` pair cannot be mistaken for a JWT-like token that
    # spans the separator.
    parts = value.replace("://", "/").split("/")
    return any(part and sanitize_text(part) != part for part in parts)


def _guard_ids(**values: str | None) -> None:
    for name, value in values.items():
        if value is None or not value.strip():
            raise EmployeeRunIntegrityError(f"{name} must be a non-empty identifier")
        if _has_secret(value):
            raise EmployeeRunIntegrityError(f"{name} carries credential-shaped content")


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        if "/" in value:
            return "/".join(sanitize_text(part) or "" for part in value.split("/"))
        return sanitize_text(value) or ""
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {(sanitize_text(str(key)) or "redacted"): _sanitize(item)
                for key, item in value.items()}
    return value


def _model_json(model) -> str:
    return json.dumps(_sanitize(model.model_dump(mode="json")), sort_keys=True)


class EmployeeRunStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None,
                 execution_mode: str | None = None, routing_store: Any = None,
                 adapter_store: Any = None, goal_store: Any = None,
                 workspace_store: Any = None, employee_registry: Any = None) -> None:
        self._db_path = ensure_confined(
            Path(db_path) if db_path is not None else employee_runs_db_path())
        self._writer = writer
        self._execution_mode = execution_mode
        self._routing_store = routing_store
        self._adapter_store = adapter_store
        self._goal_store = goal_store
        self._workspace_store = workspace_store
        self._employee_registry = employee_registry
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

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

    def _event(self, cls, *, run_id: str, actor: str, outcome: str,
               metadata: dict[str, Any], **extra):
        envelope = make_envelope(
            task_id=run_id, correlation_id=run_id, actor=actor,
            actor_type=ActorType.aria, component_name="employee_orchestrator",
            status=outcome, outcome=outcome,
            metadata={"execution_mode": self._execution_mode, **_sanitize(metadata)},
            **extra,
        )
        return cls(**envelope)

    def _enqueue(self, conn: sqlite3.Connection, event) -> None:
        conn.execute(
            "INSERT INTO audit_outbox (outbox_id,event_json,created_at,flushed_at) "
            "VALUES (?,?,?,NULL)",
            (f"obx-{uuid.uuid4().hex}", event.model_dump_json(), _iso(_now())),
        )

    def _resolve_writer(self, writer=None):
        if writer is not None:
            return writer
        if self._writer is not None:
            return self._writer
        from aria.ledger.writer import get_default_writer
        return get_default_writer()

    def flush_outbox(self, writer=None) -> int:
        conn = self._connect()
        target = self._resolve_writer(writer)
        rows = conn.execute(
            "SELECT outbox_id,event_json FROM audit_outbox WHERE flushed_at IS NULL ORDER BY rowid"
        ).fetchall()
        count = 0
        for row in rows:
            try:
                target.append(json.loads(row["event_json"]))
            except Exception:
                break
            with conn:
                conn.execute("UPDATE audit_outbox SET flushed_at=? WHERE outbox_id=?",
                             (_iso(_now()), row["outbox_id"]))
            count += 1
        return count

    def pending_audit_count(self) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS c FROM audit_outbox WHERE flushed_at IS NULL").fetchone()
        return int(row["c"])

    def create_run(self, run: EmployeeRun, *, actor: str = "aria") -> EmployeeRun:
        _guard_ids(run_id=run.run_id, correlation_id=run.correlation_id,
                   employee_id=run.employee_id, goal_id=run.goal_id,
                   workspace_id=run.workspace_id)
        if run.correlation_id != run.run_id or run.status is not EmployeeRunStatus.running:
            raise EmployeeRunIntegrityError(
                "a new employee run must be running and self-correlated")
        if (run.current_attempt != 0 or run.final_attempt_id or run.completed_at
                or run.approval_task_id or run.roi_minutes_saved or run.roi_evidence_refs):
            raise EmployeeRunIntegrityError("a new employee run cannot contain attempt results")
        if self._goal_store is None or self._goal_store.get_goal(run.goal_id) is None:
            raise EmployeeRunIntegrityError("employee run requires a persisted goal")
        if (self._workspace_store is None
                or self._workspace_store.get_workspace(run.workspace_id) is None):
            raise EmployeeRunIntegrityError("employee run requires a persisted workspace")
        if self._employee_registry is None:
            raise EmployeeRunIntegrityError("employee registry authority is unavailable")
        try:
            employee = self._employee_registry.get(run.employee_id)
        except Exception as exc:
            raise EmployeeRunIntegrityError(
                "employee run requires a persisted employee identity") from exc
        if not employee.can_accept_work:
            raise EmployeeRunIntegrityError("employee cannot accept new work")
        now = _now()
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO employee_run VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run.run_id, run.correlation_id, run.goal_id, run.workspace_id,
                 run.status.value, run.current_attempt, run.max_attempts, _model_json(run),
                 _iso(now), _iso(now)),
            )
            self._enqueue(conn, self._event(
                TaskCreated, run_id=run.run_id, actor=actor, outcome="employee_run_started",
                metadata={"goal_id": run.goal_id, "workspace_id": run.workspace_id,
                          "max_attempts": run.max_attempts},
            ))
        self.flush_outbox()
        return self.get_run(run.run_id)  # type: ignore[return-value]

    def set_route(self, run_id: str, *, decision_id: str, provider_id: str,
                  model_id: str, adapter_id: str, actor: str = "aria") -> EmployeeRun:
        _guard_ids(run_id=run_id, decision_id=decision_id, provider_id=provider_id,
                   model_id=model_id, adapter_id=adapter_id)
        run = self._require_running(run_id)
        if run.route_decision_id is not None:
            raise EmployeeRunIntegrityError("employee run already has a model route")
        decision = (self._routing_store.get_route_decision(decision_id)
                    if self._routing_store is not None else None)
        if (decision is None or not decision.allowed or decision.executed
                or decision.correlation_id != run_id
                or decision.chosen_provider_id != provider_id
                or decision.chosen_model_id != model_id
                or run.goal_id not in decision.source_refs
                or any(ref not in decision.source_refs for ref in run.dataset.source_refs)
                or any(ref not in decision.evidence_refs for ref in run.dataset.source_refs)):
            raise EmployeeRunIntegrityError(
                "employee run route must match a persisted, allowed decision")
        definition = (self._adapter_store.get_definition(adapter_id)
                      if self._adapter_store is not None else None)
        if definition is None or definition.adapter_type.value != "internal_mock":
            raise EmployeeRunIntegrityError("employee run requires the internal mock adapter")
        updated = run.model_copy(update={
            "route_decision_id": decision_id, "selected_provider_id": provider_id,
            "selected_model_id": model_id, "selected_adapter_id": adapter_id,
        })
        conn = self._connect()
        with conn:
            self._update_run_row(conn, updated)
            self._enqueue(conn, self._event(
                ActionTaken, run_id=run_id, actor=actor, outcome="model_route_selected",
                action_tier=ActionTier.T1,
                metadata={
                    "route_decision_id": decision_id,
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "adapter_id": adapter_id,
                },
            ))
        self.flush_outbox()
        return updated

    def record_attempt(self, attempt: EmployeeAttempt, *, actor: str = "aria") -> EmployeeAttempt:
        _guard_ids(attempt_id=attempt.attempt_id, run_id=attempt.run_id,
                   worker_assignment_id=attempt.worker_assignment_id,
                   route_decision_id=attempt.route_decision_id,
                   adapter_request_id=attempt.adapter_request_id,
                   preview_receipt_id=attempt.preview_receipt_id,
                   execution_receipt_id=attempt.execution_receipt_id,
                   artifact_ref=attempt.artifact_ref)
        run = self._require_running(attempt.run_id)
        if not run.route_decision_id or attempt.route_decision_id != run.route_decision_id:
            raise EmployeeRunIntegrityError("attempt route does not match its employee run")
        expected_number = run.current_attempt + 1
        if attempt.attempt_number != expected_number or attempt.attempt_number > run.max_attempts:
            raise EmployeeRunIntegrityError("attempt number is outside the bounded retry sequence")
        previous = self.list_attempts(attempt.run_id)
        retry_plan = None
        if attempt.attempt_number > 1:
            plans = self.list_repair_plans(attempt.run_id)
            retry_plan = plans[-1] if plans else None
            if (retry_plan is None
                    or retry_plan.next_attempt_number != attempt.attempt_number
                    or retry_plan.failed_attempt_id != previous[-1].attempt_id):
                raise EmployeeRunIntegrityError(
                    "a retry attempt requires its persisted repair plan")
        if any(item.adapter_request_id == attempt.adapter_request_id
               or item.preview_receipt_id == attempt.preview_receipt_id
               or item.execution_receipt_id == attempt.execution_receipt_id
               for item in previous):
            raise EmployeeRunIntegrityError("runtime request and receipts cannot be replayed")
        worker = (self._goal_store.get_agent_assignment(attempt.worker_assignment_id)
                  if self._goal_store is not None else None)
        if (worker is None or worker.goal_id != run.goal_id
                or worker.status.value != "completed" or not worker.output_summary):
            raise EmployeeRunIntegrityError(
                "attempt requires a completed evidence-backed worker assignment")
        request = (self._adapter_store.get_request(attempt.adapter_request_id)
                   if self._adapter_store is not None else None)
        preview = (self._adapter_store.get_receipt(attempt.preview_receipt_id)
                   if self._adapter_store is not None else None)
        execution = (self._adapter_store.get_receipt(attempt.execution_receipt_id)
                     if self._adapter_store is not None else None)
        if (request is None or request.task_id != attempt.run_id
                or request.goal_id != run.goal_id or request.workspace_id != run.workspace_id
                or request.adapter_id != run.selected_adapter_id
                or run.route_decision_id not in request.source_refs
                or attempt.worker_assignment_id not in request.source_refs
                or any(ref not in request.evidence_refs for ref in run.dataset.source_refs)):
            raise EmployeeRunIntegrityError("attempt request is not bound to the employee run")
        if (preview is None or preview.request_id != request.request_id
                or preview.status.value != "previewed"):
            raise EmployeeRunIntegrityError("attempt requires its persisted preview receipt")
        if (execution is None or execution.request_id != request.request_id
                or execution.status.value != "mock_completed"):
            raise EmployeeRunIntegrityError("attempt requires its persisted mock receipt")
        artifact_path = self._require_artifact(run.workspace_id, attempt.artifact_ref)
        from aria.employee.evaluation import render_report
        expected_artifact = render_report(
            attempt.report, run_id=run.run_id, attempt_number=attempt.attempt_number)
        if artifact_path.read_text(encoding="utf-8") != expected_artifact:
            raise EmployeeRunIntegrityError(
                "attempt artifact does not match the evaluated report")
        conn = self._connect()
        with conn:
            if retry_plan is not None:
                self._enqueue(conn, self._event(
                    ActionTaken, run_id=run.run_id, actor=actor,
                    outcome="retry_started", action_tier=ActionTier.T2,
                    metadata={"repair_plan_id": retry_plan.repair_plan_id,
                              "failed_attempt_id": retry_plan.failed_attempt_id,
                              "attempt_number": attempt.attempt_number},
                ))
            conn.execute(
                "INSERT INTO employee_attempt VALUES (?,?,?,?,?,?)",
                (attempt.attempt_id, attempt.run_id, attempt.attempt_number,
                 attempt.status.value, _model_json(attempt), _iso(attempt.created_at)),
            )
            updated = run.model_copy(update={"current_attempt": attempt.attempt_number})
            self._update_run_row(conn, updated)
            self._enqueue(conn, self._event(
                ArtifactCreated, run_id=run.run_id, actor=actor,
                outcome=f"attempt_{attempt.status.value}", artifact_id=attempt.artifact_ref,
                metadata={"attempt_id": attempt.attempt_id,
                          "attempt_number": attempt.attempt_number,
                          "worker_assignment_id": attempt.worker_assignment_id,
                          "adapter_request_id": attempt.adapter_request_id,
                          "execution_receipt_id": attempt.execution_receipt_id},
            ))
        self.flush_outbox()
        return self.get_attempt(attempt.attempt_id)  # type: ignore[return-value]

    def record_evaluation(self, evaluation: EmployeeEvaluation, *, actor: str = "aria"
                          ) -> EmployeeEvaluation:
        _guard_ids(evaluation_id=evaluation.evaluation_id, run_id=evaluation.run_id,
                   attempt_id=evaluation.attempt_id)
        attempt = self.get_attempt(evaluation.attempt_id)
        if attempt is None or attempt.run_id != evaluation.run_id:
            raise EmployeeRunIntegrityError("evaluation does not match a persisted attempt")
        expected_pass = attempt.status is AttemptStatus.passed
        from aria.employee.evaluation import evaluate_business_report
        authoritative = evaluate_business_report(
            run_id=evaluation.run_id, attempt_id=evaluation.attempt_id,
            report=attempt.report, dataset=self._require_running(evaluation.run_id).dataset)
        same_verdict = (
            evaluation.passed == authoritative.passed
            and evaluation.score == authoritative.score
            and evaluation.criteria == authoritative.criteria
            and evaluation.evidence_refs == authoritative.evidence_refs
            and [issue.model_dump() for issue in evaluation.issues]
            == [issue.model_dump() for issue in authoritative.issues]
        )
        if (evaluation.passed != expected_pass or evaluation.passed == bool(evaluation.issues)
                or not same_verdict):
            raise EmployeeRunIntegrityError("evaluation verdict disagrees with attempt quality")
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO employee_evaluation VALUES (?,?,?,?,?,?)",
                (evaluation.evaluation_id, evaluation.run_id, evaluation.attempt_id,
                 1 if evaluation.passed else 0, _model_json(evaluation),
                 _iso(evaluation.created_at)),
            )
            self._enqueue(conn, self._event(
                ActionTaken, run_id=evaluation.run_id, actor=actor,
                outcome="quality_passed" if evaluation.passed else "quality_failed",
                action_tier=ActionTier.T2,
                metadata={"evaluation_id": evaluation.evaluation_id,
                          "attempt_id": evaluation.attempt_id, "score": evaluation.score,
                          "failure_codes": [issue.code for issue in evaluation.issues]},
            ))
        self.flush_outbox()
        return evaluation

    def record_repair_plan(self, plan: RepairPlan, *, actor: str = "aria") -> RepairPlan:
        _guard_ids(repair_plan_id=plan.repair_plan_id, run_id=plan.run_id,
                   failed_attempt_id=plan.failed_attempt_id)
        run = self._require_running(plan.run_id)
        evaluation = self.get_evaluation_for_attempt(plan.failed_attempt_id)
        if evaluation is None or evaluation.passed:
            raise EmployeeRunIntegrityError("repair plan requires a persisted failed evaluation")
        if plan.next_attempt_number != run.current_attempt + 1 or run.current_attempt >= run.max_attempts:
            raise EmployeeRunIntegrityError("repair plan exceeds the bounded retry policy")
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO employee_repair_plan VALUES (?,?,?,?,?,?)",
                (plan.repair_plan_id, plan.run_id, plan.failed_attempt_id,
                 plan.next_attempt_number, _model_json(plan), _iso(plan.created_at)),
            )
            self._enqueue(conn, self._event(
                ActionTaken, run_id=plan.run_id, actor=actor, outcome="repair_planned",
                action_tier=ActionTier.T2,
                metadata={"repair_plan_id": plan.repair_plan_id,
                          "failed_attempt_id": plan.failed_attempt_id,
                          "next_attempt_number": plan.next_attempt_number,
                          "failure_codes": plan.failure_codes},
            ))
        self.flush_outbox()
        return plan

    def request_completion_approval(
        self, run_id: str, *, final_attempt_id: str, manager_report_ref: str,
        approval_task_id: str, proof_packet: Any | None = None,
        proof_packet_ref: str | None = None, actor: str = "aria",
    ) -> EmployeeRun:
        _guard_ids(run_id=run_id, final_attempt_id=final_attempt_id,
                   manager_report_ref=manager_report_ref, approval_task_id=approval_task_id)
        run = self._require_running(run_id)
        evaluation = self.get_evaluation_for_attempt(final_attempt_id)
        attempt = self.get_attempt(final_attempt_id)
        if evaluation is None or not evaluation.passed or attempt is None:
            raise EmployeeRunIntegrityError("only a quality-passed attempt can complete the run")
        final_path = self._require_artifact(run.workspace_id, manager_report_ref)
        from aria.employee.evaluation import render_report
        expected_report = render_report(
            attempt.report, run_id=run.run_id, attempt_number=attempt.attempt_number)
        if final_path.read_text(encoding="utf-8") != expected_report:
            raise EmployeeRunIntegrityError(
                "manager artifact does not match the quality-passed report")
        if proof_packet is None or proof_packet_ref is None:
            raise EmployeeRunIntegrityError("completion requires a work proof packet")
        _guard_ids(proof_packet_ref=proof_packet_ref)
        from aria.proof import WorkProofPacket, verify_evidence

        packet = WorkProofPacket.model_validate(proof_packet)
        if (packet.commitment_ref != run_id or packet.has_critical_failure
                or packet.manifest_completeness < 1.0):
            raise EmployeeRunIntegrityError(
                "completion requires a complete proof packet for this run")
        evidence_payloads = {
            "manager_report_artifact": expected_report.encode("utf-8"),
            **{
                source_ref: run.dataset.model_dump_json().encode("utf-8")
                for source_ref in run.dataset.source_refs
            },
        }
        for verdict in packet.verdicts:
            for evidence_ref in verdict.evidence_refs:
                payload = evidence_payloads.get(evidence_ref.source)
                if payload is None or not verify_evidence(evidence_ref, payload):
                    raise EmployeeRunIntegrityError(
                        "proof packet evidence does not match its cited source")
        proof_path = self._require_artifact(run.workspace_id, proof_packet_ref)
        if proof_path.read_text(encoding="utf-8") != packet.model_dump_json():
            raise EmployeeRunIntegrityError("proof artifact does not match the packet")
        tasks = self._goal_store.get_tasks(run.goal_id) if self._goal_store is not None else []
        approval = next((task for task in tasks if task.task_id == approval_task_id), None)
        if (approval is None or not approval.approval_required
                or approval.status.value != "awaiting_approval"):
            raise EmployeeRunIntegrityError(
                "completion requires its persisted approval-gate task")
        unfinished = [task for task in tasks
                      if task.task_id != approval_task_id
                      and task.status.value not in {"completed", "cancelled"}]
        goal = self._goal_store.get_goal(run.goal_id) if self._goal_store is not None else None
        if unfinished or goal is None or goal.status.value != "awaiting_approval":
            raise EmployeeRunIntegrityError(
                "completion approval requires all work tasks to be closed")
        updated = run.model_copy(update={
            "status": EmployeeRunStatus.awaiting_approval,
            "final_attempt_id": final_attempt_id,
            "manager_report_ref": manager_report_ref,
            "proof_packet_ref": proof_packet_ref,
            "proof_packet": {
                **packet.model_dump(mode="json"),
                "manifest_completeness": packet.manifest_completeness,
                "has_critical_failure": packet.has_critical_failure,
            },
            "approval_task_id": approval_task_id,
        })
        conn = self._connect()
        with conn:
            self._update_run_row(conn, updated)
            self._enqueue(conn, self._event(
                ArtifactCreated, run_id=run_id, actor=actor,
                outcome="manager_report_created", artifact_id=manager_report_ref,
                metadata={"final_attempt_id": final_attempt_id,
                          "approval_task_id": approval_task_id},
            ))
            self._enqueue(conn, self._event(
                ActionTaken, run_id=run_id, actor=actor,
                outcome="manager_approval_requested", action_tier=ActionTier.T3,
                metadata={"final_attempt_id": final_attempt_id,
                          "manager_report_ref": manager_report_ref,
                          "proof_packet_ref": proof_packet_ref,
                          "approval_task_id": approval_task_id,
                          "attempts": updated.current_attempt},
            ))
        self.flush_outbox()
        return updated

    def complete_run(self, run_id: str, *, actor: str = "human:local") -> EmployeeRun:
        _guard_ids(run_id=run_id)
        run = self.get_run(run_id)
        if (run is None or run.status is not EmployeeRunStatus.awaiting_approval
                or not run.final_attempt_id or not run.manager_report_ref
                or not run.proof_packet_ref or not run.proof_packet
                or not run.approval_task_id):
            raise EmployeeRunIntegrityError(
                "employee run must await an explicit completion approval")
        evaluation = self.get_evaluation_for_attempt(run.final_attempt_id)
        attempt = self.get_attempt(run.final_attempt_id)
        if evaluation is None or not evaluation.passed or attempt is None:
            raise EmployeeRunIntegrityError("completion requires its passed evaluation")
        tasks = self._goal_store.get_tasks(run.goal_id) if self._goal_store is not None else []
        approval = next((task for task in tasks if task.task_id == run.approval_task_id), None)
        goal = self._goal_store.get_goal(run.goal_id) if self._goal_store is not None else None
        if (approval is None or approval.status.value != "completed"
                or any(task.status.value not in {"completed", "cancelled"} for task in tasks)
                or goal is None or goal.status.value != "completed"):
            raise EmployeeRunIntegrityError(
                "goal and task authorities do not support completion")
        final_path = self._require_artifact(run.workspace_id, run.manager_report_ref)
        from aria.employee.evaluation import render_report
        expected = render_report(
            attempt.report, run_id=run_id, attempt_number=attempt.attempt_number)
        if final_path.read_text(encoding="utf-8") != expected:
            raise EmployeeRunIntegrityError(
                "manager artifact does not match the quality-passed report")
        work_tasks = [task for task in tasks if not task.approval_required
                      and task.status.value == "completed"]
        roi_minutes = len(work_tasks) * 5 + 5
        roi_method = (
            "Conservative estimate: 5 minutes per completed work task + 5 minutes for the "
            "manager report; not production ROI"
        )
        roi_refs = [task.task_id for task in work_tasks] + [
            attempt.artifact_ref, run.manager_report_ref]
        updated = run.model_copy(update={
            "status": EmployeeRunStatus.completed, "completed_at": _now(),
            "roi_minutes_saved": roi_minutes, "roi_method": roi_method,
            "roi_evidence_refs": roi_refs,
        })
        conn = self._connect()
        with conn:
            self._update_run_row(conn, updated)
            self._enqueue(conn, self._event(
                ActionTaken, run_id=run_id, actor=actor, outcome="goal_completed",
                action_tier=ActionTier.T3,
                metadata={"goal_id": run.goal_id, "approval_task_id": run.approval_task_id},
            ))
            self._enqueue(conn, self._event(
                ActionTaken, run_id=run_id, actor=actor, outcome="roi_estimated",
                action_tier=ActionTier.T1,
                metadata={"estimated_minutes_saved": roi_minutes,
                          "calculation_method": roi_method,
                          "evidence_refs": roi_refs},
            ))
            self._enqueue(conn, self._event(
                Responded, run_id=run_id, actor=actor, outcome="employee_run_completed",
                metadata={"final_attempt_id": run.final_attempt_id,
                          "manager_report_ref": run.manager_report_ref,
                          "proof_packet_ref": run.proof_packet_ref,
                          "attempts": updated.current_attempt,
                          "approval_task_id": run.approval_task_id},
            ))
        self.flush_outbox()
        self._record_employee_outcome(updated, passed=True, escalated=False)
        return updated

    def escalate_run(self, run_id: str, *, reason: str, actor: str = "aria") -> EmployeeRun:
        run = self._require_running(run_id)
        evaluation = self.get_evaluation_for_attempt(
            self.list_attempts(run_id)[-1].attempt_id if self.list_attempts(run_id) else "")
        if run.current_attempt < run.max_attempts or evaluation is None or evaluation.passed:
            raise EmployeeRunIntegrityError("escalation requires exhausted failed attempts")
        safe_reason = sanitize_text(reason) or "quality retries exhausted"
        updated = run.model_copy(update={
            "status": EmployeeRunStatus.escalated, "escalation_reason": safe_reason,
            "completed_at": _now(),
        })
        conn = self._connect()
        with conn:
            self._update_run_row(conn, updated)
            self._enqueue(conn, self._event(
                Failed, run_id=run_id, actor=actor, outcome="employee_run_escalated",
                error="quality_retry_exhausted",
                metadata={"attempts": updated.current_attempt,
                          "reason": safe_reason},
            ))
        self.flush_outbox()
        self._record_employee_outcome(updated, passed=False, escalated=True)
        return updated

    def fail_run(self, run_id: str, *, error_type: str, actor: str = "aria") -> EmployeeRun:
        """Close an unexpected internal failure with class-only error metadata."""
        run = self._require_running(run_id)
        safe_type = sanitize_text(error_type) or "InternalError"
        updated = run.model_copy(update={
            "status": EmployeeRunStatus.failed,
            "escalation_reason": f"internal_error:{safe_type}",
            "completed_at": _now(),
        })
        conn = self._connect()
        with conn:
            self._update_run_row(conn, updated)
            self._enqueue(conn, self._event(
                Failed, run_id=run_id, actor=actor, outcome="employee_run_failed",
                error=safe_type, metadata={"error_type": safe_type},
            ))
        self.flush_outbox()
        return updated

    def _require_running(self, run_id: str) -> EmployeeRun:
        run = self.get_run(run_id)
        if run is None:
            raise EmployeeRunNotFound(f"employee run {run_id!r} not found")
        if run.status is not EmployeeRunStatus.running:
            raise EmployeeRunIntegrityError(
                f"employee run is terminal ({run.status.value})")
        return run

    def _require_artifact(self, workspace_id: str, artifact_ref: str) -> Path:
        if self._workspace_store is None:
            raise EmployeeRunIntegrityError("workspace authority is unavailable")
        prefix = f"{workspace_id}/"
        if not artifact_ref.startswith(prefix):
            raise EmployeeRunIntegrityError("artifact is not bound to the run workspace")
        try:
            path = self._workspace_store.resolve_artifact_ref(workspace_id, artifact_ref)
        except ValueError as exc:
            raise EmployeeRunIntegrityError("artifact reference is not confined") from exc
        if not path.is_file():
            raise EmployeeRunIntegrityError("employee artifact is not persisted")
        return path

    def _save_run(self, run: EmployeeRun) -> None:
        conn = self._connect()
        with conn:
            self._update_run_row(conn, run)

    def _update_run_row(self, conn: sqlite3.Connection, run: EmployeeRun) -> None:
        conn.execute(
            "UPDATE employee_run SET status=?,current_attempt=?,max_attempts=?,payload_json=?,"
            "updated_at=? WHERE run_id=?",
            (run.status.value, run.current_attempt, run.max_attempts, _model_json(run),
             _iso(_now()), run.run_id),
        )

    def _record_employee_outcome(
        self, run: EmployeeRun, *, passed: bool, escalated: bool
    ) -> None:
        if self._employee_registry is None:
            return
        attempts = self.list_attempts(run.run_id)
        self._employee_registry.record_outcome(
            run.employee_id,
            run_id=run.run_id,
            passed=passed,
            corrected=len(attempts) > 1,
            escalated=escalated,
            cost=sum(attempt.declared_cost_estimate or 0.0 for attempt in attempts),
            latency_ms=sum(attempt.declared_latency_ms for attempt in attempts),
        )

    def get_run(self, run_id: str) -> EmployeeRun | None:
        row = self._connect().execute(
            "SELECT payload_json FROM employee_run WHERE run_id=?", (run_id,)).fetchone()
        return EmployeeRun.model_validate_json(row["payload_json"]) if row else None

    def list_runs(self) -> list[EmployeeRun]:
        rows = self._connect().execute(
            "SELECT payload_json FROM employee_run ORDER BY created_at,run_id").fetchall()
        return [EmployeeRun.model_validate_json(row["payload_json"]) for row in rows]

    def get_attempt(self, attempt_id: str) -> EmployeeAttempt | None:
        row = self._connect().execute(
            "SELECT payload_json FROM employee_attempt WHERE attempt_id=?", (attempt_id,)).fetchone()
        return EmployeeAttempt.model_validate_json(row["payload_json"]) if row else None

    def list_attempts(self, run_id: str) -> list[EmployeeAttempt]:
        rows = self._connect().execute(
            "SELECT payload_json FROM employee_attempt WHERE run_id=? ORDER BY attempt_number",
            (run_id,)).fetchall()
        return [EmployeeAttempt.model_validate_json(row["payload_json"]) for row in rows]

    def get_evaluation_for_attempt(self, attempt_id: str) -> EmployeeEvaluation | None:
        row = self._connect().execute(
            "SELECT payload_json FROM employee_evaluation WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        return EmployeeEvaluation.model_validate_json(row["payload_json"]) if row else None

    def list_evaluations(self, run_id: str) -> list[EmployeeEvaluation]:
        rows = self._connect().execute(
            "SELECT payload_json FROM employee_evaluation WHERE run_id=? ORDER BY created_at",
            (run_id,)).fetchall()
        return [EmployeeEvaluation.model_validate_json(row["payload_json"]) for row in rows]

    def list_repair_plans(self, run_id: str) -> list[RepairPlan]:
        rows = self._connect().execute(
            "SELECT payload_json FROM employee_repair_plan WHERE run_id=? "
            "ORDER BY next_attempt_number", (run_id,)).fetchall()
        return [RepairPlan.model_validate_json(row["payload_json"]) for row in rows]
