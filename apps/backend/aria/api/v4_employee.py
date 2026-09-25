"""Manager-facing API for the integrated, offline virtual-employee workflow.

This surface composes existing V3/V4 authorities. It adds no live execution,
provider invocation, connector, credential, approval, or deployment endpoint.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aria.employee import (
    BusinessMetricPeriod,
    BusinessPerformanceDataset,
    EmployeeOrchestratorService,
    EmployeeRegistry,
    EmployeeRunNotFound,
    EmployeeRunStore,
)
from aria.goals import AgentSupervisorService, AgentWorkforceService, GoalService, GoalStore
from aria.llm import resolve_execution_mode
from aria.memory_v2.workspace import WorkspaceStore
from aria.model_routing import ModelRoutingService, ModelRoutingStore
from aria.runtime_adapters import RuntimeAdapterService, RuntimeAdapterStore

_log = logging.getLogger("aria.api.v4_employee")


class EmployeeModeBlocked(RuntimeError):
    """The integrated proof was requested outside its offline-only boundary."""


def actor() -> str:
    """Attribution label only; this is not authentication or authorization."""
    value = os.getenv("ARIA_USER_ID")
    return value if value and value.strip() else "human:local"


def _build_employee():
    mode = resolve_execution_mode().value
    if mode != "offline_mock":
        raise EmployeeModeBlocked("the integrated employee workflow is offline_mock only")
    who = actor()
    goals = GoalStore(execution_mode=mode)
    workspaces = WorkspaceStore(execution_mode=mode)
    routing_store = ModelRoutingStore(execution_mode=mode)
    adapter_store = RuntimeAdapterStore(execution_mode=mode)
    employee_registry = EmployeeRegistry()
    employee_store = EmployeeRunStore(
        execution_mode=mode, routing_store=routing_store, adapter_store=adapter_store,
        goal_store=goals, workspace_store=workspaces, employee_registry=employee_registry)
    service = EmployeeOrchestratorService(
        employee_store,
        goal_service=GoalService(
            goals, workspace_store=workspaces, execution_mode=mode, actor=who),
        goal_store=goals,
        workforce_service=AgentWorkforceService(
            goals, workspace_store=workspaces, execution_mode=mode, actor=who),
        supervisor_service=AgentSupervisorService(
            goals, workspace_store=workspaces, execution_mode=mode, actor=who),
        routing_service=ModelRoutingService(routing_store, execution_mode=mode, actor=who),
        routing_store=routing_store,
        adapter_service=RuntimeAdapterService(
            adapter_store, workspace_store=workspaces, execution_mode=mode, actor=who),
        adapter_store=adapter_store,
        workspace_store=workspaces, actor=who, execution_mode=mode,
        employee_registry=employee_registry,
    )
    return service, (
        employee_store, employee_registry, adapter_store, routing_store, workspaces, goals)


def _close(*stores) -> None:
    for store in stores:
        try:
            store.close()
        except Exception:  # pragma: no cover - defensive close only
            pass


def _dump(model: Any) -> dict[str, Any]:
    return json.loads(model.model_dump_json())


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error_code": code, "detail": detail})


class MetricPeriodBody(BaseModel):
    label: str = Field(min_length=1)
    impressions: int = Field(gt=0)
    clicks: int = Field(ge=0)


class BusinessAnalysisBody(BaseModel):
    goal_text: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    metric_name: str = "notification_ctr"
    previous: MetricPeriodBody
    current: MetricPeriodBody
    source_refs: list[str] = Field(min_length=1)
    max_attempts: int = Field(default=2, ge=1, le=5)
    exercise_repair_loop: bool = False


class CompletionApprovalBody(BaseModel):
    decision: Literal["approve"]


v4_employee_router = APIRouter(prefix="/api/v4/employee-runs", tags=["v4-employee-runs"])


@v4_employee_router.post("/business-analysis")
def run_business_analysis(body: BusinessAnalysisBody):
    """Run one bounded local analysis. ``exercise_repair_loop`` is proof-only."""
    try:
        service, stores = _build_employee()
    except EmployeeModeBlocked:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        dataset = BusinessPerformanceDataset(
            dataset_id=body.dataset_id, metric_name=body.metric_name,
            previous=BusinessMetricPeriod(**body.previous.model_dump()),
            current=BusinessMetricPeriod(**body.current.model_dump()),
            source_refs=body.source_refs,
        )
        result = service.run_business_analysis(
            goal_text=body.goal_text, dataset=dataset, max_attempts=body.max_attempts,
            intentional_quality_failures=1 if body.exercise_repair_loop else 0,
        )
        return JSONResponse(status_code=201, content=_dump(result))
    except ValueError:
        return _error(400, "invalid_employee_request", "The request violates workflow policy.")
    except Exception as exc:
        _log.error("v4 employee run failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "The employee run failed safely.")
    finally:
        _close(*stores)


@v4_employee_router.get("")
def list_employee_runs():
    try:
        service, stores = _build_employee()
    except EmployeeModeBlocked:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        runs = service.list_runs()
        return {"runs": [_dump(run) for run in runs], "count": len(runs)}
    except Exception as exc:
        _log.error("v4 employee listing failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Employee runs could not be listed.")
    finally:
        _close(*stores)


@v4_employee_router.get("/employees")
def list_employees():
    try:
        _service, stores = _build_employee()
    except EmployeeModeBlocked:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    employee_store = stores[1]
    try:
        employees = employee_store.list_employees()
        return {
            "employees": [
                {
                    "employee": _dump(employee),
                    "employment_record": _dump(
                        employee_store.employment_record(employee.employee_id)
                    ),
                }
                for employee in employees
            ],
            "count": len(employees),
        }
    except Exception as exc:
        _log.error("v4 employee registry listing failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Employees could not be listed.")
    finally:
        _close(*stores)


@v4_employee_router.get("/employees/{employee_id}")
def inspect_employee(employee_id: str):
    try:
        _service, stores = _build_employee()
    except EmployeeModeBlocked:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    employee_store = stores[1]
    try:
        employee = employee_store.get(employee_id)
        return {
            "employee": _dump(employee),
            "employment_record": _dump(employee_store.employment_record(employee_id)),
            "status_history": [
                _dump(event) for event in employee_store.status_history(employee_id)
            ],
        }
    except Exception as exc:
        if type(exc).__name__ == "EmployeeNotFound":
            return _error(404, "employee_not_found", "Unknown employee.")
        _log.error("v4 employee registry inspection failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Employee could not be inspected.")
    finally:
        _close(*stores)


@v4_employee_router.post("/{run_id}/approve-completion")
def approve_employee_completion(run_id: str, body: CompletionApprovalBody):
    """Record a local manager decision only; never execute or write externally."""
    try:
        service, stores = _build_employee()
    except EmployeeModeBlocked:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        return _dump(service.approve_completion(run_id, actor=actor()))
    except EmployeeRunNotFound:
        return _error(404, "employee_run_not_found", "Unknown employee run.")
    except ValueError:
        return _error(409, "completion_not_approvable",
                      "The employee run is not eligible for completion approval.")
    except Exception as exc:
        _log.error("v4 employee approval failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Completion approval failed safely.")
    finally:
        _close(*stores)


@v4_employee_router.get("/{run_id}/proof-packet")
def inspect_employee_run_proof_packet(run_id: str):
    try:
        service, stores = _build_employee()
    except EmployeeModeBlocked:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        view = service.inspect_run(run_id)
        if not view.work_proof_packet:
            return _error(404, "proof_packet_not_found", "The run has no proof packet yet.")
        return {
            "run_id": run_id,
            "proof_packet_ref": view.run.proof_packet_ref,
            "proof_packet": view.work_proof_packet,
        }
    except EmployeeRunNotFound:
        return _error(404, "employee_run_not_found", "Unknown employee run.")
    except Exception as exc:
        _log.error("v4 employee proof inspection failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "The proof packet could not be inspected.")
    finally:
        _close(*stores)


@v4_employee_router.get("/{run_id}")
def inspect_employee_run(run_id: str):
    try:
        service, stores = _build_employee()
    except EmployeeModeBlocked:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        return _dump(service.inspect_run(run_id))
    except EmployeeRunNotFound:
        return _error(404, "employee_run_not_found", "Unknown employee run.")
    except Exception as exc:
        _log.error("v4 employee inspection failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "The employee run could not be inspected.")
    finally:
        _close(*stores)


@v4_employee_router.get("/{run_id}/ledger")
def inspect_employee_run_ledger(run_id: str):
    """Return a sanitized audit timeline for one run and its owning goal."""
    try:
        service, stores = _build_employee()
    except EmployeeModeBlocked:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        view = service.inspect_run(run_id)
        from aria.ledger import LedgerReader
        from aria.ledger.writer import get_default_writer

        events = LedgerReader(v2_path=get_default_writer().path).v2_events()
        correlations = {view.run.run_id, view.run.goal_id}
        timeline = []
        for event in events:
            if event.correlation_id not in correlations:
                continue
            payload = event.model_dump(mode="json")
            timeline.append({
                key: payload.get(key)
                for key in (
                    "event_id", "event_type", "task_id", "correlation_id",
                    "actor_type", "outcome", "timestamp",
                )
                if payload.get(key) is not None
            })
        return {"run_id": run_id, "goal_id": view.run.goal_id,
                "events": timeline, "count": len(timeline)}
    except EmployeeRunNotFound:
        return _error(404, "employee_run_not_found", "Unknown employee run.")
    except Exception as exc:
        _log.error("v4 employee ledger inspection failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "The employee ledger could not be inspected.")
    finally:
        _close(*stores)
