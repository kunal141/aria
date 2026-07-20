"""Unified governed goal-to-manager-output orchestration."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.employee.evaluation import build_repair_plan, evaluate_business_report, render_report
from aria.employee.models import (
    AttemptStatus,
    BusinessAnalysisReport,
    BusinessMetricPeriod,
    BusinessPerformanceDataset,
    EmployeeAttempt,
    EmployeeRun,
    EmployeeRunStatus,
    ManagerRunView,
)
from aria.employee.store import EmployeeRunNotFound, EmployeeRunStore
from aria.goals.models import GoalStatus, TaskStatus
from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType
from aria.runtime_adapters import AdapterType, ReceiptStatus


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_dataset(dataset: BusinessPerformanceDataset) -> BusinessPerformanceDataset:
    """Sanitize prose and reject secrets in structural dataset provenance."""
    structural = [dataset.dataset_id, dataset.metric_name, *dataset.source_refs]
    if any(sanitize_text(value) != value for value in structural):
        raise ValueError("dataset identifiers/source references cannot contain credentials")
    if not dataset.source_refs or any(not ref.startswith("fixture://")
                                      for ref in dataset.source_refs):
        raise ValueError(
            "the offline employee proof accepts fixture:// dataset sources only")
    return dataset.model_copy(update={
        "previous": dataset.previous.model_copy(
            update={"label": sanitize_text(dataset.previous.label) or "previous"}),
        "current": dataset.current.model_copy(
            update={"label": sanitize_text(dataset.current.label) or "current"}),
    })


def build_business_report(dataset: BusinessPerformanceDataset, *, attempt_number: int,
                          omit_risks: bool = False) -> BusinessAnalysisReport:
    """Pure deterministic worker used only after a governed internal-mock receipt."""
    previous_ctr = dataset.previous.ctr_percent
    current_ctr = dataset.current.ctr_percent
    delta = round(current_ctr - previous_ctr, 2)
    direction = "decreased" if delta < 0 else "increased" if delta > 0 else "was unchanged"
    risks = [] if omit_risks else [
        "The fixture proves a metric change, not its root cause.",
        "Segment-level data is required before targeting remediation.",
    ]
    return BusinessAnalysisReport(
        title="Business Performance Analysis",
        executive_summary=(
            f"{dataset.metric_name} {direction} from {previous_ctr:.2f}% to "
            f"{current_ctr:.2f}% in the supplied fixture. This is a governed local analysis."
        ),
        findings=[
            f"Previous period CTR: {previous_ctr:.2f}% "
            f"({dataset.previous.clicks}/{dataset.previous.impressions}).",
            f"Current period CTR: {current_ctr:.2f}% "
            f"({dataset.current.clicks}/{dataset.current.impressions}).",
            f"Verified change: {delta:+.2f} percentage points.",
        ],
        risks=risks,
        recommendations=[
            "Validate the decline by audience, channel and campaign using read-only evidence.",
            "Review notification timing and creative changes before proposing an intervention.",
            "Keep any external action draft-only until a manager approves it.",
        ],
        evidence_refs=list(dataset.source_refs),
    )


class EmployeeOrchestratorService:
    """Compose existing ARIA authorities into one bounded employee run."""

    def __init__(
        self, store: EmployeeRunStore, *, goal_service: Any, goal_store: Any,
        workforce_service: Any, supervisor_service: Any, routing_service: Any,
        routing_store: Any, adapter_service: Any, workspace_store: Any,
        adapter_store: Any,
        actor: str = "aria", execution_mode: str = "offline_mock",
    ) -> None:
        self._store = store
        self._goals = goal_service
        self._goal_store = goal_store
        self._workforce = workforce_service
        self._supervisor = supervisor_service
        self._routing = routing_service
        self._routing_store = routing_store
        self._adapters = adapter_service
        self._adapter_store = adapter_store
        self._workspace = workspace_store
        self._actor = actor
        self._execution_mode = execution_mode

    def run_business_analysis(
        self, *, goal_text: str, dataset: BusinessPerformanceDataset,
        max_attempts: int = 2, intentional_quality_failures: int = 1,
    ) -> ManagerRunView:
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if not 0 <= intentional_quality_failures <= max_attempts:
            raise ValueError("intentional_quality_failures is outside the bounded attempt policy")
        safe_dataset = _safe_dataset(dataset)

        plan = self._goals.own_goal(goal_text, scope="analytics.business_performance")
        run_id = f"erun-{uuid.uuid4().hex}"
        run = EmployeeRun(
            run_id=run_id, correlation_id=run_id, goal_id=plan.goal.goal_id,
            workspace_id=plan.goal.workspace_id or plan.workspace_id,
            goal_text=plan.goal.raw_request,
            dataset=safe_dataset,
            success_criteria=list(plan.goal.success_criteria), max_attempts=max_attempts,
            started_at=_now(),
        )
        run = self._store.create_run(run, actor=self._actor)
        try:
            if plan.goal.clarifying_questions:
                clarification = self._goal_store.create_clarification(
                    run.goal_id, plan.goal.clarifying_questions, actor=self._actor)
                supplied_context = (
                    f"The manager supplied dataset {safe_dataset.dataset_id} with previous and "
                    f"current impressions/clicks and cited sources: "
                    f"{', '.join(safe_dataset.source_refs)}. No root cause was supplied."
                )
                self._goal_store.answer_clarification(
                    clarification.clarification_id,
                    {question: supplied_context for question in clarification.questions},
                    actor="aria:structured-input", actor_type=ActorType.aria,
                )
            self._goal_store.provide_evidence(
                run.goal_id, safe_dataset.source_refs, provided_by=self._actor)
            self._workforce.plan_evidence_backed_analysis(
                run.goal_id, evidence_refs=list(safe_dataset.source_refs), actor=self._actor)
            supervision = self._supervisor.run(run.goal_id, actor=self._actor)
            completed_workers = [
                assignment for assignment in self._goal_store.get_agent_assignments(run.goal_id)
                if assignment.status.value == "completed" and assignment.output_summary
            ]
            if supervision.completed_assignments != 1 or len(completed_workers) != 1:
                raise RuntimeError("EvidenceBackedWorkerUnavailable")
            worker = completed_workers[0]

            self._ensure_routing_registry()
            route = self._routing.route(
                intent="summarization", task_type="business_analysis",
                adapter_request_id=run_id,
                source_refs=[run.goal_id, *safe_dataset.source_refs],
                evidence_refs=list(safe_dataset.source_refs), actor=self._actor,
            )
            if not route.allowed or not route.chosen_provider_id or not route.chosen_model_id:
                raise RuntimeError("ModelRouteUnavailable")

            adapter_id = self._ensure_internal_adapter()
            run = self._store.set_route(
                run_id, decision_id=route.decision_id, provider_id=route.chosen_provider_id,
                model_id=route.chosen_model_id, adapter_id=adapter_id, actor=self._actor,
            )

            for attempt_number in range(1, max_attempts + 1):
                attempt_id = f"eattempt-{uuid.uuid4().hex}"
                request = self._adapters.create_request(
                    adapter_id=adapter_id, task_type="analysis", goal_id=run.goal_id,
                    task_id=run_id, workspace_id=run.workspace_id,
                    input_payload={
                        "dataset_id": safe_dataset.dataset_id,
                        "metric_name": safe_dataset.metric_name,
                        "attempt_number": attempt_number,
                        "repair_plan": (
                            self._store.list_repair_plans(run_id)[-1].instructions
                            if self._store.list_repair_plans(run_id) else []),
                    },
                    source_refs=[run_id, route.decision_id, worker.assignment_id,
                                 *safe_dataset.source_refs],
                    evidence_refs=list(safe_dataset.source_refs), requested_by=self._actor,
                    actor=self._actor,
                )
                preview = self._adapters.preview(request.request_id, actor=self._actor)
                receipt = self._adapters.execute_mock(request.request_id, actor=self._actor)
                if preview.status is not ReceiptStatus.previewed:
                    raise RuntimeError("AdapterPreviewBlocked")
                if receipt.status is not ReceiptStatus.mock_completed:
                    raise RuntimeError("AdapterMockExecutionFailed")

                report = build_business_report(
                    safe_dataset, attempt_number=attempt_number,
                    omit_risks=attempt_number <= intentional_quality_failures,
                )
                evaluation = evaluate_business_report(
                    run_id=run_id, attempt_id=attempt_id, report=report, dataset=safe_dataset)
                artifact_ref = self._workspace.write_artifact(
                    run.workspace_id, f"business-analysis-attempt-{attempt_number}.md",
                    render_report(report, run_id=run_id, attempt_number=attempt_number),
                )
                cost = route.cost_estimate or 0.0
                cost_profile = self._routing_store.get_cost_profile(route.chosen_model_id)
                latency = cost_profile.typical_latency_ms if cost_profile else 0
                attempt = EmployeeAttempt(
                    attempt_id=attempt_id, run_id=run_id, attempt_number=attempt_number,
                    worker_assignment_id=worker.assignment_id,
                    route_decision_id=route.decision_id, adapter_request_id=request.request_id,
                    preview_receipt_id=preview.receipt_id,
                    execution_receipt_id=receipt.receipt_id,
                    status=(AttemptStatus.passed if evaluation.passed
                            else AttemptStatus.quality_failed),
                    report=report, artifact_ref=artifact_ref,
                    declared_cost_estimate=cost, declared_latency_ms=latency, created_at=_now(),
                )
                self._store.record_attempt(attempt, actor=self._actor)
                self._store.record_evaluation(evaluation, actor=self._actor)

                if evaluation.passed:
                    final_ref = self._workspace.write_artifact(
                        run.workspace_id, "manager-business-performance-report.md",
                        render_report(report, run_id=run_id, attempt_number=attempt_number),
                    )
                    tasks = self._goal_store.get_tasks(run.goal_id)
                    approval_tasks = [task for task in tasks if task.approval_required]
                    if len(approval_tasks) != 1:
                        raise RuntimeError("CompletionApprovalTaskUnavailable")
                    approval_task = approval_tasks[0]
                    for task in tasks:
                        if task.task_id == approval_task.task_id:
                            self._goal_store.update_task_status(
                                task.task_id, TaskStatus.awaiting_approval,
                                output_artifact=final_ref, actor=self._actor)
                        elif task.status not in (TaskStatus.completed, TaskStatus.cancelled):
                            self._goal_store.update_task_status(
                                task.task_id, TaskStatus.completed,
                                output_artifact=final_ref, actor=self._actor)
                    self._goal_store.update_goal_status(run.goal_id, GoalStatus.awaiting_approval)
                    self._workspace.update_workspace(
                        run.workspace_id, status="employee_run_awaiting_approval",
                        add_artifact_refs=[artifact_ref, final_ref],
                        add_ledger_refs=[f"employee_run:{run_id}",
                                         f"route_decision:{route.decision_id}",
                                         f"runtime_receipt:{receipt.receipt_id}"],
                        add_approval_refs=[f"employee_completion:{approval_task.task_id}"],
                        final_outcome="manager report evaluated; completion approval required",
                        actor=self._actor,
                    )
                    self._store.request_completion_approval(
                        run_id, final_attempt_id=attempt_id, manager_report_ref=final_ref,
                        approval_task_id=approval_task.task_id,
                        actor=self._actor,
                    )
                    return self.inspect_run(run_id)

                if attempt_number < max_attempts:
                    repair = build_repair_plan(
                        evaluation, next_attempt_number=attempt_number + 1)
                    self._store.record_repair_plan(repair, actor=self._actor)

            self._store.escalate_run(
                run_id, reason="quality criteria failed after bounded retries",
                actor=self._actor,
            )
            self._workspace.update_workspace(
                run.workspace_id, status="employee_run_escalated",
                add_ledger_refs=[f"employee_run:{run_id}:escalated"],
                final_outcome="human review required after retry exhaustion", actor=self._actor,
            )
            return self.inspect_run(run_id)
        except Exception as exc:
            latest = self._store.get_run(run_id)
            if latest is not None and latest.status is EmployeeRunStatus.running:
                self._store.fail_run(run_id, error_type=type(exc).__name__, actor=self._actor)
            raise

    def approve_completion(self, run_id: str, *, actor: str | None = None) -> ManagerRunView:
        """Record the manager's local decision. It performs no external action."""
        actor = actor or self._actor
        run = self._store.get_run(run_id)
        if run is None:
            raise EmployeeRunNotFound(f"employee run {run_id!r} not found")
        if run.status is not EmployeeRunStatus.awaiting_approval or not run.approval_task_id:
            raise ValueError("employee run is not awaiting completion approval")
        self._goal_store.update_task_status(
            run.approval_task_id, TaskStatus.completed,
            output_artifact=run.manager_report_ref, actor=actor)
        self._goal_store.update_goal_status(run.goal_id, GoalStatus.completed)
        completed = self._store.complete_run(run_id, actor=actor)
        self._workspace.update_workspace(
            completed.workspace_id, status="employee_run_completed",
            add_ledger_refs=[f"employee_run:{run_id}:approved"],
            final_outcome="manager approved the evaluated local deliverable",
            actor=actor,
        )
        return self.inspect_run(run_id)

    def inspect_run(self, run_id: str) -> ManagerRunView:
        run = self._store.get_run(run_id)
        if run is None:
            raise EmployeeRunNotFound(f"employee run {run_id!r} not found")
        attempts = self._store.list_attempts(run_id)
        evaluations = self._store.list_evaluations(run_id)
        repairs = self._store.list_repair_plans(run_id)
        final_attempt = next((a for a in attempts if a.attempt_id == run.final_attempt_id), None)
        score = evaluations[-1].score if evaluations else 0.0
        receipts = [ref for attempt in attempts for ref in
                    (attempt.preview_receipt_id, attempt.execution_receipt_id)]
        evidence = sorted({ref for a in attempts for ref in a.report.evidence_refs})
        goal = self._goal_store.get_goal(run.goal_id)
        roadmap = self._goal_store.get_roadmap(run.goal_id)
        tasks = self._goal_store.get_tasks(run.goal_id)
        clarifications = self._goal_store.list_clarifications(run.goal_id)
        workers = self._goal_store.get_agent_assignments(run.goal_id)
        supervision = self._goal_store.list_supervision_runs(run.goal_id)
        route = (self._routing_store.get_route_decision(run.route_decision_id)
                 if run.route_decision_id else None)
        requests = [self._adapter_store.get_request(attempt.adapter_request_id)
                    for attempt in attempts]
        workspace = self._workspace.get_workspace(run.workspace_id)
        approvals = [
            {"kind": "task", "id": task.task_id, "status": task.status.value,
             "title": task.title}
            for task in tasks if task.approval_required
        ] + [
            {"kind": "worker", "id": worker.assignment_id, "status": worker.status.value,
             "title": worker.agent_id}
            for worker in workers if worker.approval_required
        ]
        blocked = [
            {"kind": "task", "id": task.task_id, "status": task.status.value,
             "reason": list(task.blocked_by)}
            for task in tasks if task.status.value == "blocked"
        ] + [
            {"kind": "worker", "id": worker.assignment_id, "status": worker.status.value,
             "reason": worker.failure_reason}
            for worker in workers if worker.status.value in {"blocked", "failed", "killed"}
        ]
        return ManagerRunView(
            run=run, attempts=attempts, evaluations=evaluations, repair_plans=repairs,
            final_report=final_attempt.report if final_attempt else None,
            goal=goal.model_dump(mode="json") if goal else {},
            roadmap=roadmap.model_dump(mode="json") if roadmap else {},
            clarifications=[item.model_dump(mode="json") for item in clarifications],
            tasks=[task.model_dump(mode="json") for task in tasks],
            workers=[worker.model_dump(mode="json") for worker in workers],
            supervision_runs=[item.model_dump(mode="json") for item in supervision],
            route_decision=route.model_dump(mode="json") if route else {},
            adapter_requests=[item.model_dump(mode="json") for item in requests if item],
            workspace=workspace.model_dump(mode="json") if workspace else {},
            approval_items=approvals, blocked_items=blocked,
            quality_score=score,
            risk_level=("high" if run.status is EmployeeRunStatus.escalated
                        else "medium" if any(not e.passed for e in evaluations) else "low"),
            declared_cost_estimate=round(sum(a.declared_cost_estimate or 0 for a in attempts), 6),
            declared_latency_ms=sum(a.declared_latency_ms for a in attempts),
            estimated_minutes_saved=run.roi_minutes_saved,
            roi_method=run.roi_method,
            evidence_refs=evidence, receipt_refs=receipts,
        )

    def list_runs(self) -> list[EmployeeRun]:
        return self._store.list_runs()

    def _ensure_routing_registry(self) -> None:
        if not self._routing.list_providers():
            self._routing.register_default_providers(actor=self._actor)

    def _ensure_internal_adapter(self) -> str:
        existing = self._adapters.get_adapter_definition("rta-internal-mock")
        if existing is None:
            self._adapters.register_adapter(
                name="Internal Mock Runtime", adapter_type=AdapterType.internal_mock,
                adapter_id="rta-internal-mock", supported_task_types=["analysis", "summarization"],
                actor=self._actor,
            )
        return "rta-internal-mock"


def default_business_fixture() -> BusinessPerformanceDataset:
    return BusinessPerformanceDataset(
        dataset_id="fixture-business-performance-v1", metric_name="notification_ctr",
        previous=BusinessMetricPeriod(label="previous_week", impressions=100_000, clicks=4_200),
        current=BusinessMetricPeriod(label="current_week", impressions=105_000, clicks=3_780),
        source_refs=["fixture://business-performance/notification-ctr-v1"],
    )
