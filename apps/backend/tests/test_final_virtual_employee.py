"""Integrated virtual-employee proof and authority-boundary tests."""
from __future__ import annotations

import ast
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from aria.employee import (
    AttemptStatus,
    BusinessMetricPeriod,
    EmployeeAttempt,
    EmployeeEvaluation,
    EmployeeOrchestratorService,
    EmployeeRun,
    EmployeeRunIntegrityError,
    EmployeeRunStatus,
    EmployeeRunStore,
    build_business_report,
    default_business_fixture,
    evaluate_business_report,
    render_report,
)
from aria.goals import AgentSupervisorService, AgentWorkforceService, GoalService, GoalStore
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import PathConfinementError, aria_data_dir
from aria.memory_v2.workspace import WorkspaceStore
from aria.model_routing import ModelRoutingService, ModelRoutingStore
from aria.runtime_adapters import RuntimeAdapterService, RuntimeAdapterStore


def _now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def env(tmp_path: Path):
    mode = "offline_mock"
    writer = LedgerWriter(tmp_path / "employee-ledger.jsonl")
    goal_store = GoalStore(writer=writer, execution_mode=mode)
    workspace_store = WorkspaceStore(writer=writer, execution_mode=mode)
    routing_store = ModelRoutingStore(writer=writer, execution_mode=mode)
    adapter_store = RuntimeAdapterStore(writer=writer, execution_mode=mode)
    employee_store = EmployeeRunStore(
        writer=writer, execution_mode=mode, routing_store=routing_store,
        adapter_store=adapter_store, goal_store=goal_store, workspace_store=workspace_store)
    goal_service = GoalService(
        goal_store, workspace_store=workspace_store, execution_mode=mode, actor="human:test")
    workforce = AgentWorkforceService(
        goal_store, workspace_store=workspace_store, execution_mode=mode, actor="human:test")
    supervisor = AgentSupervisorService(
        goal_store, workspace_store=workspace_store, execution_mode=mode, actor="human:test")
    routing = ModelRoutingService(routing_store, execution_mode=mode, actor="human:test")
    adapters = RuntimeAdapterService(
        adapter_store, workspace_store=workspace_store, execution_mode=mode, actor="human:test")
    service = EmployeeOrchestratorService(
        employee_store, goal_service=goal_service, goal_store=goal_store,
        workforce_service=workforce, supervisor_service=supervisor,
        routing_service=routing, routing_store=routing_store,
        adapter_service=adapters, adapter_store=adapter_store, workspace_store=workspace_store,
        actor="human:test", execution_mode=mode,
    )
    yield {
        "service": service, "employee": employee_store, "goals": goal_store,
        "workspace": workspace_store, "routing": routing_store,
        "adapters": adapter_store, "writer": writer, "goal_service": goal_service,
        "routing_service": routing, "adapter_service": adapters,
        "workforce": workforce, "supervisor": supervisor,
    }
    for store in (employee_store, adapter_store, routing_store, workspace_store, goal_store):
        store.close()


def _run(env, **kwargs):
    view = env["service"].run_business_analysis(
        goal_text="Investigate the notification CTR decline and produce a manager report.",
        dataset=default_business_fixture(), **kwargs)
    if view.run.status is EmployeeRunStatus.awaiting_approval:
        return env["service"].approve_completion(
            view.run.run_id, actor="human:test-manager")
    return view


def _prepare_direct_run(env, run_id: str):
    dataset = default_business_fixture()
    plan = env["goal_service"].own_goal(
        "Investigate notification CTR and produce a cited report.",
        scope="analytics.business_performance")
    routing = env["routing_service"]
    if not routing.list_providers():
        routing.register_default_providers()
    route = routing.route(
        intent="summarization", task_type="business_analysis", adapter_request_id=run_id,
        source_refs=[plan.goal.goal_id, *dataset.source_refs],
        evidence_refs=dataset.source_refs)
    adapters = env["adapter_service"]
    if adapters.get_adapter_definition("rta-internal-mock") is None:
        adapters.register_adapter(
            name="Internal Mock Runtime", adapter_type="internal_mock",
            adapter_id="rta-internal-mock", supported_task_types=["analysis"])
    run = EmployeeRun(
        run_id=run_id, correlation_id=run_id, goal_id=plan.goal.goal_id,
        workspace_id=plan.goal.workspace_id, goal_text=plan.goal.raw_request,
        dataset=dataset, success_criteria=plan.goal.success_criteria,
        max_attempts=2, started_at=_now())
    env["employee"].create_run(run)
    env["employee"].set_route(
        run_id, decision_id=route.decision_id, provider_id=route.chosen_provider_id,
        model_id=route.chosen_model_id, adapter_id="rta-internal-mock")
    env["goals"].provide_evidence(run.goal_id, dataset.source_refs, provided_by="human:test")
    env["workforce"].plan_evidence_backed_analysis(
        run.goal_id, evidence_refs=dataset.source_refs)
    supervision = env["supervisor"].run(run.goal_id)
    assert supervision.completed_assignments == 1
    worker = next(
        item for item in env["goals"].get_agent_assignments(run.goal_id)
        if item.status.value == "completed")
    request = adapters.create_request(
        adapter_id="rta-internal-mock", task_type="analysis", goal_id=run.goal_id,
        task_id=run_id, workspace_id=run.workspace_id,
        source_refs=[run_id, route.decision_id, worker.assignment_id, *dataset.source_refs],
        evidence_refs=dataset.source_refs)
    preview = adapters.preview(request.request_id)
    receipt = adapters.execute_mock(request.request_id)
    report = build_business_report(dataset, attempt_number=1)
    artifact = env["workspace"].write_artifact(
        run.workspace_id, "direct-attempt.md",
        render_report(report, run_id=run_id, attempt_number=1))
    return run, route, request, preview, receipt, artifact, report


def _worker_id(env, goal_id: str) -> str:
    return next(
        item.assignment_id for item in env["goals"].get_agent_assignments(goal_id)
        if item.status.value == "completed")


def test_metric_period_rejects_impossible_counts():
    with pytest.raises(ValidationError):
        BusinessMetricPeriod(label="bad", impressions=10, clicks=11)


def test_evaluator_reports_concrete_missing_risk_issue():
    dataset = default_business_fixture()
    report = build_business_report(dataset, attempt_number=1, omit_risks=True)
    result = evaluate_business_report(
        run_id="run-1", attempt_id="attempt-1", report=report, dataset=dataset)
    assert result.passed is False
    assert [issue.code for issue in result.issues] == ["missing_risks"]
    assert result.issues[0].repair_instruction == "Add concrete risks and limitations."


def test_complete_flow_preserves_failed_attempt_and_repair(env):
    view = _run(env, max_attempts=2, intentional_quality_failures=1)
    assert view.run.status is EmployeeRunStatus.completed
    assert [a.status for a in view.attempts] == [
        AttemptStatus.quality_failed, AttemptStatus.passed]
    assert len(view.evaluations) == 2
    assert [evaluation.passed for evaluation in view.evaluations] == [False, True]
    assert len(view.repair_plans) == 1
    assert view.repair_plans[0].failure_codes == ["missing_risks"]
    assert view.final_report is not None
    assert view.final_report.risks
    assert view.quality_score == 1.0
    assert view.goal["goal_id"] == view.run.goal_id
    assert view.roadmap["goal_id"] == view.run.goal_id
    assert view.clarifications
    assert all(item["status"] == "answered" for item in view.clarifications)
    assert view.tasks
    assert view.workers
    assert view.supervision_runs
    assert view.route_decision["decision_id"] == view.run.route_decision_id
    assert len(view.adapter_requests) == 2
    assert view.workspace["workspace_id"] == view.run.workspace_id
    assert view.approval_items
    assert view.blocked_items == []
    assert len(view.workers) == 1
    assert view.workers[0]["status"] == "completed"
    assert {attempt.worker_assignment_id for attempt in view.attempts} == {
        view.workers[0]["assignment_id"]}


def test_complete_flow_uses_policy_route_and_internal_mock_receipts(env):
    view = _run(env)
    run = view.run
    assert run.route_decision_id
    assert run.selected_provider_id
    assert run.selected_model_id
    assert run.selected_adapter_id == "rta-internal-mock"
    route = env["routing"].get_route_decision(run.route_decision_id)
    assert route is not None and route.allowed and route.executed is False
    assert len(view.receipt_refs) == 4
    receipts = [env["adapters"].get_receipt(ref) for ref in view.receipt_refs]
    assert all(receipt is not None for receipt in receipts)
    assert {receipt.status.value for receipt in receipts if receipt} == {
        "previewed", "mock_completed"}


def test_offline_employee_rejects_non_fixture_dataset_sources(env):
    dataset = default_business_fixture().model_copy(
        update={"source_refs": ["https://example.invalid/private-metric"]})
    with pytest.raises(ValueError, match="fixture://"):
        env["service"].run_business_analysis(
            goal_text="Analyse the metric.", dataset=dataset,
            max_attempts=1, intentional_quality_failures=0)


def test_manager_view_exposes_only_declared_estimates(env):
    view = _run(env)
    assert view.declared_cost_estimate >= 0
    assert view.declared_latency_ms >= 0
    completed_work = [task for task in view.tasks
                      if not task["approval_required"] and task["status"] == "completed"]
    assert view.estimated_minutes_saved == len(completed_work) * 5 + 5
    assert "not production ROI" in view.roi_method
    assert set(task["task_id"] for task in completed_work) <= set(view.run.roi_evidence_refs)
    assert view.run.manager_report_ref in view.run.roi_evidence_refs
    assert view.evidence_refs == ["fixture://business-performance/notification-ctr-v1"]
    assert "No network" in view.boundary_note


def test_completion_requires_explicit_manager_approval(env):
    pending = env["service"].run_business_analysis(
        goal_text="Investigate the notification CTR decline and report.",
        dataset=default_business_fixture(), max_attempts=1,
        intentional_quality_failures=0)
    assert pending.run.status is EmployeeRunStatus.awaiting_approval
    assert pending.goal["status"] == "awaiting_approval"
    assert all(task["status"] == "completed" for task in pending.tasks
               if not task["approval_required"])
    approval = next(task for task in pending.tasks if task["approval_required"])
    assert approval["status"] == "awaiting_approval"
    with pytest.raises(EmployeeRunIntegrityError, match="goal and task authorities"):
        env["employee"].complete_run(pending.run.run_id, actor="forged:caller")
    completed = env["service"].approve_completion(
        pending.run.run_id, actor="human:test-manager")
    assert completed.run.status is EmployeeRunStatus.completed
    assert completed.goal["status"] == "completed"
    assert all(task["status"] in {"completed", "cancelled"} for task in completed.tasks)


def test_structured_clarification_is_not_misattributed_to_human(env):
    view = _run(env, max_attempts=1, intentional_quality_failures=0)
    events = LedgerReader(v2_path=env["writer"].path).v2_events()
    answered = [event for event in events
                if event.event_type.value == "clarification_answered"
                and event.correlation_id == view.run.goal_id]
    assert answered
    assert all(event.actor_type.value == "aria" for event in answered)
    assert all(event.actor == "aria:structured-input" for event in answered)


def test_retry_exhaustion_escalates_without_final_report(env):
    view = _run(env, max_attempts=2, intentional_quality_failures=2)
    assert view.run.status is EmployeeRunStatus.escalated
    assert len(view.attempts) == 2
    assert all(not evaluation.passed for evaluation in view.evaluations)
    assert len(view.repair_plans) == 1
    assert view.final_report is None
    assert view.estimated_minutes_saved == 0
    assert view.risk_level == "high"


@pytest.mark.parametrize("attempts", [0, 6])
def test_attempt_budget_is_bounded(env, attempts):
    with pytest.raises(ValueError, match="between 1 and 5"):
        _run(env, max_attempts=attempts)


def test_employee_store_is_restart_safe(env):
    view = _run(env)
    path = env["employee"].db_path
    env["employee"].close()
    reopened = EmployeeRunStore(
        path, writer=env["writer"], execution_mode="offline_mock",
        routing_store=env["routing"], adapter_store=env["adapters"],
        goal_store=env["goals"], workspace_store=env["workspace"])
    try:
        assert reopened.get_run(view.run.run_id) == view.run
        assert len(reopened.list_attempts(view.run.run_id)) == 2
        assert len(reopened.list_evaluations(view.run.run_id)) == 2
    finally:
        reopened.close()


def test_employee_store_path_is_confined():
    with pytest.raises(PathConfinementError):
        EmployeeRunStore(Path("C:/not-confined/employee.sqlite"))
    assert EmployeeRunStore().db_path.is_relative_to(aria_data_dir())


def test_store_rejects_nonsequential_attempt(env):
    store = env["employee"]
    run, route, request, preview, receipt, artifact, report = _prepare_direct_run(
        env, "run-direct")
    attempt = EmployeeAttempt(
        attempt_id="attempt-direct", run_id=run.run_id, attempt_number=2,
        worker_assignment_id=_worker_id(env, run.goal_id),
        route_decision_id=route.decision_id, adapter_request_id=request.request_id,
        preview_receipt_id=preview.receipt_id, execution_receipt_id=receipt.receipt_id,
        status=AttemptStatus.passed,
        report=report,
        artifact_ref=artifact, created_at=_now())
    with pytest.raises(EmployeeRunIntegrityError, match="bounded retry sequence"):
        store.record_attempt(attempt)


def test_store_rejects_attempt_without_completed_worker(env):
    store = env["employee"]
    run, route, request, preview, receipt, artifact, report = _prepare_direct_run(
        env, "run-no-worker")
    attempt = EmployeeAttempt(
        attempt_id="attempt-no-worker", run_id=run.run_id, attempt_number=1,
        worker_assignment_id="assign-invented",
        route_decision_id=route.decision_id, adapter_request_id=request.request_id,
        preview_receipt_id=preview.receipt_id, execution_receipt_id=receipt.receipt_id,
        status=AttemptStatus.passed, report=report, artifact_ref=artifact, created_at=_now())
    with pytest.raises(EmployeeRunIntegrityError, match="completed evidence-backed worker"):
        store.record_attempt(attempt)
    assert store.get_attempt(attempt.attempt_id) is None


def test_store_rejects_completion_without_passed_evaluation(env):
    store = env["employee"]
    run, route, request, preview, receipt, artifact, _ = _prepare_direct_run(env, "run-failed")
    failed_report = build_business_report(run.dataset, attempt_number=1, omit_risks=True)
    artifact = env["workspace"].write_artifact(
        run.workspace_id, Path(artifact).name,
        render_report(failed_report, run_id=run.run_id, attempt_number=1))
    attempt = EmployeeAttempt(
        attempt_id="attempt-failed", run_id=run.run_id, attempt_number=1,
        worker_assignment_id=_worker_id(env, run.goal_id),
        route_decision_id=route.decision_id, adapter_request_id=request.request_id,
        preview_receipt_id=preview.receipt_id, execution_receipt_id=receipt.receipt_id,
        status=AttemptStatus.quality_failed,
        report=failed_report,
        artifact_ref=artifact, created_at=_now())
    store.record_attempt(attempt)
    evaluation = evaluate_business_report(
        run_id=run.run_id, attempt_id=attempt.attempt_id,
        report=attempt.report, dataset=run.dataset)
    store.record_evaluation(evaluation)
    with pytest.raises(EmployeeRunIntegrityError, match="quality-passed"):
        store.request_completion_approval(
            run.run_id, final_attempt_id=attempt.attempt_id,
            manager_report_ref="workspace-failed/final.md",
            approval_task_id="approval-failed")


def test_store_rejects_forged_route_reference(env):
    plan = env["goal_service"].own_goal("Analyse the fixture and report.")
    run = EmployeeRun(
        run_id="run-forged-route", correlation_id="run-forged-route",
        goal_id=plan.goal.goal_id, workspace_id=plan.goal.workspace_id,
        goal_text=plan.goal.raw_request, dataset=default_business_fixture(),
        success_criteria=plan.goal.success_criteria, started_at=_now())
    env["employee"].create_run(run)
    with pytest.raises(EmployeeRunIntegrityError, match="persisted, allowed decision"):
        env["employee"].set_route(
            run.run_id, decision_id="route-invented", provider_id="provider-invented",
            model_id="model-invented", adapter_id="rta-internal-mock")


def test_store_recomputes_and_rejects_forged_pass_evaluation(env):
    run, route, request, preview, receipt, artifact, _ = _prepare_direct_run(
        env, "run-forged-eval")
    report = build_business_report(run.dataset, attempt_number=1, omit_risks=True)
    artifact = env["workspace"].write_artifact(
        run.workspace_id, Path(artifact).name,
        render_report(report, run_id=run.run_id, attempt_number=1))
    attempt = EmployeeAttempt(
        attempt_id="attempt-forged-eval", run_id=run.run_id, attempt_number=1,
        worker_assignment_id=_worker_id(env, run.goal_id),
        route_decision_id=route.decision_id, adapter_request_id=request.request_id,
        preview_receipt_id=preview.receipt_id, execution_receipt_id=receipt.receipt_id,
        status=AttemptStatus.passed, report=report, artifact_ref=artifact, created_at=_now())
    env["employee"].record_attempt(attempt)
    forged = EmployeeEvaluation(
        evaluation_id="eval-forged", run_id=run.run_id, attempt_id=attempt.attempt_id,
        score=1.0, passed=True, issues=[], criteria={"all_good": True},
        evidence_refs=run.dataset.source_refs, created_at=_now())
    with pytest.raises(EmployeeRunIntegrityError, match="verdict disagrees"):
        env["employee"].record_evaluation(forged)
    assert env["employee"].get_evaluation_for_attempt(attempt.attempt_id) is None


def test_store_rejects_foreign_runtime_receipts(env):
    run, route, request, preview, receipt, artifact, report = _prepare_direct_run(
        env, "run-foreign-receipt")
    other = env["adapter_service"].create_request(
        adapter_id="rta-internal-mock", task_type="analysis", goal_id=run.goal_id,
        task_id=run.run_id, workspace_id=run.workspace_id,
        source_refs=[run.run_id, route.decision_id], evidence_refs=run.dataset.source_refs)
    other_receipt = env["adapter_service"].execute_mock(other.request_id)
    attempt = EmployeeAttempt(
        attempt_id="attempt-foreign", run_id=run.run_id, attempt_number=1,
        worker_assignment_id=_worker_id(env, run.goal_id),
        route_decision_id=route.decision_id, adapter_request_id=request.request_id,
        preview_receipt_id=preview.receipt_id, execution_receipt_id=other_receipt.receipt_id,
        status=AttemptStatus.passed,
        report=report,
        artifact_ref=artifact, created_at=_now())
    with pytest.raises(EmployeeRunIntegrityError, match="persisted mock receipt"):
        env["employee"].record_attempt(attempt)


def test_store_rejects_attempt_artifact_that_disagrees_with_report(env):
    run, route, request, preview, receipt, artifact, report = _prepare_direct_run(
        env, "run-tampered-attempt")
    env["workspace"].write_artifact(run.workspace_id, Path(artifact).name, "forged report bytes")
    attempt = EmployeeAttempt(
        attempt_id="attempt-tampered", run_id=run.run_id, attempt_number=1,
        worker_assignment_id=_worker_id(env, run.goal_id),
        route_decision_id=route.decision_id, adapter_request_id=request.request_id,
        preview_receipt_id=preview.receipt_id, execution_receipt_id=receipt.receipt_id,
        status=AttemptStatus.passed, report=report, artifact_ref=artifact, created_at=_now())
    with pytest.raises(EmployeeRunIntegrityError, match="evaluated report"):
        env["employee"].record_attempt(attempt)
    assert env["employee"].get_attempt(attempt.attempt_id) is None


def test_store_rejects_final_artifact_that_disagrees_with_passed_attempt(env):
    run, route, request, preview, receipt, artifact, report = _prepare_direct_run(
        env, "run-tampered-final")
    attempt = EmployeeAttempt(
        attempt_id="attempt-valid", run_id=run.run_id, attempt_number=1,
        worker_assignment_id=_worker_id(env, run.goal_id),
        route_decision_id=route.decision_id, adapter_request_id=request.request_id,
        preview_receipt_id=preview.receipt_id, execution_receipt_id=receipt.receipt_id,
        status=AttemptStatus.passed, report=report, artifact_ref=artifact, created_at=_now())
    env["employee"].record_attempt(attempt)
    evaluation = evaluate_business_report(
        run_id=run.run_id, attempt_id=attempt.attempt_id, report=report, dataset=run.dataset)
    env["employee"].record_evaluation(evaluation)
    final_ref = env["workspace"].write_artifact(
        run.workspace_id, "forged-final.md", "contradictory manager report")
    with pytest.raises(EmployeeRunIntegrityError, match="quality-passed report"):
        approval = next(task for task in env["goals"].get_tasks(run.goal_id)
                        if task.approval_required)
        env["employee"].request_completion_approval(
            run.run_id, final_attempt_id=attempt.attempt_id,
            manager_report_ref=final_ref, approval_task_id=approval.task_id)
    assert env["employee"].get_run(run.run_id).status is EmployeeRunStatus.running


def test_employee_audit_outbox_recovers_without_state_divergence(env, tmp_path):
    class FailingWriter:
        def append(self, _event):
            raise RuntimeError("password=OUTBOX_SECRET")

    plan = env["goal_service"].own_goal("Prepare a fixture report.")
    store = EmployeeRunStore(
        tmp_path / "aria_data" / "employee_runs" / "outbox.sqlite",
        writer=FailingWriter(), execution_mode="offline_mock",
        routing_store=env["routing"], adapter_store=env["adapters"],
        goal_store=env["goals"], workspace_store=env["workspace"])
    run = EmployeeRun(
        run_id="run-outbox", correlation_id="run-outbox", goal_id=plan.goal.goal_id,
        workspace_id=plan.goal.workspace_id, goal_text=plan.goal.raw_request,
        dataset=default_business_fixture(), success_criteria=plan.goal.success_criteria,
        started_at=_now())
    try:
        assert store.create_run(run).run_id == run.run_id
        assert store.pending_audit_count() == 1
        assert store.flush_outbox(env["writer"]) == 1
        assert store.pending_audit_count() == 0
        store.close()
        raw = (tmp_path / "aria_data" / "employee_runs" / "outbox.sqlite").read_bytes()
        assert b"OUTBOX_SECRET" not in raw
    finally:
        store.close()


def test_employee_ledger_is_correlated_and_contains_repair_trace(env):
    view = _run(env)
    records = LedgerReader(v2_path=env["writer"].path).v2_events()
    correlated = [event for event in records if event.correlation_id == view.run.run_id]
    outcomes = {event.outcome for event in correlated}
    assert {"employee_run_started", "model_route_selected", "quality_failed",
            "repair_planned", "retry_started", "quality_passed",
            "manager_report_created", "manager_approval_requested",
            "goal_completed", "roi_estimated", "employee_run_completed"} <= outcomes
    adapter_events = [event for event in correlated
                      if event.event_type.value.startswith("runtime_adapter_")]
    assert adapter_events
    assert all(event.correlation_id == view.run.run_id for event in adapter_events)
    workers = env["goals"].get_agent_assignments(view.run.goal_id)
    assert len(workers) == 1 and workers[0].status.value == "completed"
    assert all(attempt.worker_assignment_id == workers[0].assignment_id
               for attempt in view.attempts)
    ordered = [event.outcome for event in correlated]
    required_order = [
        "employee_run_started", "route_requested", "decided", "model_route_selected",
        "quality_failed", "repair_planned", "retry_started", "quality_passed",
        "manager_report_created", "manager_approval_requested", "goal_completed",
        "roi_estimated", "employee_run_completed",
    ]
    positions = [ordered.index(outcome) for outcome in required_order]
    assert positions == sorted(positions)


def test_no_secret_is_persisted_in_employee_surfaces(env):
    dataset = default_business_fixture().model_copy(update={
        "previous": BusinessMetricPeriod(
            label="password=TOP_SECRET", impressions=100, clicks=5)})
    view = env["service"].run_business_analysis(
        goal_text="Analyse password=TOP_SECRET and report safely.", dataset=dataset,
        max_attempts=1, intentional_quality_failures=0)
    assert "TOP_SECRET" not in view.model_dump_json()
    env["employee"].close()
    runtime_bytes = b"".join(
        path.read_bytes() for path in aria_data_dir().rglob("*") if path.is_file())
    assert b"TOP_SECRET" not in runtime_bytes
    if env["writer"].path.exists():
        assert "TOP_SECRET" not in env["writer"].path.read_text(encoding="utf-8")


def test_no_network_or_external_runtime_imports():
    root = Path(__file__).parents[1] / "aria" / "employee"
    imported: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(
        {"requests", "httpx", "aiohttp", "socket", "subprocess", "docker", "mcp"})


def test_v4_employee_api_runs_and_inspects(monkeypatch):
    from fastapi.testclient import TestClient

    from aria.api.v4 import build_v4_app

    monkeypatch.setenv("ARIA_EXECUTION_MODE", "offline_mock")
    client = TestClient(build_v4_app())
    body = {
        "goal_text": "Investigate the notification CTR decline.",
        "dataset_id": "fixture-api",
        "metric_name": "notification_ctr",
        "previous": {"label": "previous", "impressions": 1000, "clicks": 50},
        "current": {"label": "current", "impressions": 1000, "clicks": 35},
        "source_refs": ["fixture://api/ctr"],
        "max_attempts": 2,
        "exercise_repair_loop": True,
    }
    created = client.post("/api/v4/employee-runs/business-analysis", json=body)
    assert created.status_code == 201
    payload = created.json()
    assert payload["run"]["status"] == "awaiting_approval"
    assert [item["status"] for item in payload["attempts"]] == [
        "quality_failed", "passed"]
    run_id = payload["run"]["run_id"]
    approved = client.post(
        f"/api/v4/employee-runs/{run_id}/approve-completion",
        json={"decision": "approve"})
    assert approved.status_code == 200
    assert approved.json()["run"]["status"] == "completed"
    inspected = client.get(f"/api/v4/employee-runs/{run_id}")
    assert inspected.status_code == 200
    assert inspected.json()["run"]["run_id"] == run_id
    listed = client.get("/api/v4/employee-runs")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1


def test_v4_employee_api_requires_offline_mock(monkeypatch):
    from fastapi.testclient import TestClient

    from aria.api.v4 import build_v4_app

    monkeypatch.setenv("ARIA_EXECUTION_MODE", "cloud_opt_in")
    response = TestClient(build_v4_app()).get("/api/v4/employee-runs")
    assert response.status_code == 409
    assert response.json()["error_code"] == "offline_mode_required"


def test_v4_employee_api_has_no_live_or_approval_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from aria.api.v4 import build_v4_app

    monkeypatch.setenv("ARIA_EXECUTION_MODE", "offline_mock")
    client = TestClient(build_v4_app())
    assert client.post("/api/v4/employee-runs/run-1/execute-live").status_code == 404
    assert client.post("/api/v4/employee-runs/run-1/approve").status_code == 404


def test_v4_employee_api_redacts_internal_exception_text(monkeypatch, caplog):
    from fastapi.testclient import TestClient

    import aria.api.v4_employee as employee_api
    from aria.api.v4 import build_v4_app

    class BrokenService:
        def list_runs(self):
            raise RuntimeError("password=API_SECRET")

    monkeypatch.setattr(employee_api, "_build_employee", lambda: (BrokenService(), ()))
    response = TestClient(build_v4_app()).get("/api/v4/employee-runs")
    assert response.status_code == 500
    combined = response.text + caplog.text
    assert "API_SECRET" not in combined
    assert "RuntimeError" in caplog.text


def test_virtual_employee_demo_repairs_and_cleans(monkeypatch):
    from aria.demo.virtual_employee import run_demo

    monkeypatch.setenv("ARIA_EXECUTION_MODE", "cloud_opt_in")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    output: list[str] = []
    result = run_demo(write=output.append)
    assert result["ok"] is True
    assert result["execution_mode"] == "offline_mock"
    assert result["attempt_statuses"] == ["quality_failed", "passed"]
    assert result["approval_sequence"] == ["awaiting_approval", "completed"]
    assert result["repair_failure_codes"] == ["missing_risks"]
    assert result["quality_score"] == 1.0
    assert result["receipt_count"] == 4
    assert result["correlated_employee_events"] >= 6
    assert result["temp_cleaned"] is True
    assert not Path(result["data_dir"]).exists()
    assert os.environ["ARIA_EXECUTION_MODE"] == "cloud_opt_in"
    assert os.environ["OPENAI_API_KEY"] == "test-only-not-a-real-key"
    assert "test-only-not-a-real-key" not in "\n".join(output)
