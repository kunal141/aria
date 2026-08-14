"""Authenticated, physically tenant-isolated employee workflow API."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from aria.api.platform import AuthenticatedRequest, authenticated_request
from aria.api.v4_employee import BusinessAnalysisBody, CompletionApprovalBody
from aria.employee import BusinessMetricPeriod, BusinessPerformanceDataset, EmployeeRunNotFound
from aria.identity import AuthorizationDenied, Permission
from aria.ledger import LedgerReader
from aria.llm import resolve_execution_mode
from aria.tenancy import TenantRuntime

_log = logging.getLogger("aria.api.platform_employee")


def _dump(model: Any) -> dict[str, Any]:
    return json.loads(model.model_dump_json())


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error_code": code, "detail": detail})


def _authorize(auth: AuthenticatedRequest, tenant_id: str, permission: Permission) -> bool:
    try:
        auth.service.require(auth.context, permission, tenant_id=tenant_id)
        return True
    except AuthorizationDenied:
        return False


def _mode() -> str | None:
    mode = resolve_execution_mode().value
    return mode if mode == "offline_mock" else None


router = APIRouter(
    prefix="/api/platform/tenants/{tenant_id}/employee-runs",
    tags=["platform-employee-runs"],
)


@router.post("/business-analysis")
def run_business_analysis(
    tenant_id: str,
    body: BusinessAnalysisBody,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.work_create):
        return _error(403, "authorization_denied", "Work creation is not allowed.")
    mode = _mode()
    if mode is None:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        dataset = BusinessPerformanceDataset(
            dataset_id=body.dataset_id,
            metric_name=body.metric_name,
            previous=BusinessMetricPeriod(**body.previous.model_dump()),
            current=BusinessMetricPeriod(**body.current.model_dump()),
            source_refs=body.source_refs,
        )
        with TenantRuntime(tenant_id, execution_mode=mode) as runtime:
            result = runtime.employee_service(actor=auth.context.actor).run_business_analysis(
                goal_text=body.goal_text,
                dataset=dataset,
                max_attempts=body.max_attempts,
                intentional_quality_failures=1 if body.exercise_repair_loop else 0,
            )
        return JSONResponse(status_code=201, content=_dump(result))
    except ValueError:
        return _error(400, "invalid_employee_request", "The request violates workflow policy.")
    except Exception as exc:
        _log.error("tenant employee run failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "The employee run failed safely.")


@router.get("")
def list_employee_runs(
    tenant_id: str,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.work_read):
        return _error(403, "authorization_denied", "Work inspection is not allowed.")
    mode = _mode()
    if mode is None:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        with TenantRuntime(tenant_id, execution_mode=mode) as runtime:
            runs = runtime.employee_service(actor=auth.context.actor).list_runs()
        return {"runs": [_dump(run) for run in runs], "count": len(runs)}
    except Exception as exc:
        _log.error("tenant employee listing failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Employee runs could not be listed.")


@router.post("/{run_id}/approve-completion")
def approve_employee_completion(
    tenant_id: str,
    run_id: str,
    _body: CompletionApprovalBody,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.work_approve):
        return _error(403, "authorization_denied", "Completion approval is not allowed.")
    mode = _mode()
    if mode is None:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        with TenantRuntime(tenant_id, execution_mode=mode) as runtime:
            result = runtime.employee_service(actor=auth.context.actor).approve_completion(
                run_id, actor=auth.context.actor
            )
        return _dump(result)
    except EmployeeRunNotFound:
        return _error(404, "employee_run_not_found", "Unknown employee run.")
    except ValueError:
        return _error(
            409,
            "completion_not_approvable",
            "The employee run is not eligible for completion approval.",
        )
    except Exception as exc:
        _log.error("tenant employee approval failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Completion approval failed safely.")


@router.get("/{run_id}")
def inspect_employee_run(
    tenant_id: str,
    run_id: str,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.work_read):
        return _error(403, "authorization_denied", "Work inspection is not allowed.")
    mode = _mode()
    if mode is None:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        with TenantRuntime(tenant_id, execution_mode=mode) as runtime:
            result = runtime.employee_service(actor=auth.context.actor).inspect_run(run_id)
        return _dump(result)
    except EmployeeRunNotFound:
        return _error(404, "employee_run_not_found", "Unknown employee run.")
    except Exception as exc:
        _log.error("tenant employee inspection failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "The employee run could not be inspected.")


@router.get("/{run_id}/ledger")
def inspect_employee_run_ledger(
    tenant_id: str,
    run_id: str,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.audit_read):
        return _error(403, "authorization_denied", "Audit inspection is not allowed.")
    mode = _mode()
    if mode is None:
        return _error(409, "offline_mode_required", "This workflow requires offline_mock mode.")
    try:
        with TenantRuntime(tenant_id, execution_mode=mode) as runtime:
            view = runtime.employee_service(actor=auth.context.actor).inspect_run(run_id)
            correlations = {view.run.run_id, view.run.goal_id}
            events = LedgerReader(v2_path=runtime.ledger_path).v2_events()
            timeline = []
            for event in events:
                if getattr(event, "correlation_id", None) not in correlations:
                    continue
                payload = event.model_dump(mode="json")
                timeline.append(
                    {
                        key: payload.get(key)
                        for key in (
                            "event_id",
                            "event_type",
                            "task_id",
                            "correlation_id",
                            "actor_type",
                            "outcome",
                            "timestamp",
                        )
                        if payload.get(key) is not None
                    }
                )
        return {
            "run_id": run_id,
            "goal_id": view.run.goal_id,
            "events": timeline,
            "count": len(timeline),
        }
    except EmployeeRunNotFound:
        return _error(404, "employee_run_not_found", "Unknown employee run.")
    except Exception as exc:
        _log.error("tenant employee ledger failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "The employee ledger could not be inspected.")


__all__ = ["router"]
