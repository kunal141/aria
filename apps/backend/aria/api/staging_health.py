"""Safe health/readiness endpoints for the private offline staging package."""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aria.connectors.mode import resolve_connector_mode
from aria.employee import EmployeeRunStore
from aria.goals import GoalStore
from aria.llm.execution_mode import resolve_execution_mode
from aria.memory_v2.paths import aria_data_dir, ensure_confined
from aria.memory_v2.workspace import WorkspaceStore
from aria.model_routing import ModelRoutingStore
from aria.runtime_adapters import RuntimeAdapterStore

staging_health_router = APIRouter(tags=["private-staging-health"])


def _status(*, persistence_writable: bool | None = None,
            stores_ready: bool | None = None) -> dict[str, object]:
    try:
        mode = resolve_execution_mode().value
    except Exception:
        mode = "invalid"
    try:
        connector_mode = resolve_connector_mode().value
    except Exception:
        connector_mode = "invalid"
    live_disabled = (os.getenv("ARIA_LIVE_EXECUTION", "false").strip().lower()
                     in {"", "0", "false", "no", "off"})
    mode_allowed = mode in {"offline_mock", "local_ollama"}
    ready = mode_allowed and connector_mode == "fixtures" and live_disabled
    if persistence_writable is not None:
        ready = ready and persistence_writable
    if stores_ready is not None:
        ready = ready and stores_ready
    result: dict[str, object] = {
        "status": "ready" if ready else "not_ready",
        "execution_mode": mode if mode_allowed else "blocked",
        "live_execution": False,
        "connector_mode": "fixtures" if connector_mode == "fixtures" else "blocked",
    }
    if persistence_writable is not None:
        result["persistence_writable"] = persistence_writable
    if stores_ready is not None:
        result["stores_ready"] = stores_ready
    return result


@staging_health_router.get("/health")
def health():
    """Liveness only; never exposes environment values or filesystem paths."""
    payload = _status()
    return JSONResponse(status_code=200 if payload["status"] == "ready" else 503,
                        content=payload)


@staging_health_router.get("/ready")
def ready():
    """Verify the confined data root and all staging authority schemas on demand."""
    writable = stores_ok = False
    stores = []
    try:
        mode = resolve_execution_mode().value
        if mode == "local_ollama":
            from aria.llm.readiness import ensure_local_model_available

            ensure_local_model_available()
        root = ensure_confined(aria_data_dir())
        root.mkdir(parents=True, exist_ok=True)
        probe = ensure_confined(root / f".readiness-{uuid.uuid4().hex}")
        probe.write_text("ready", encoding="ascii")
        probe.unlink()
        writable = True

        goals = GoalStore(execution_mode=mode)
        workspaces = WorkspaceStore(execution_mode=mode)
        routing = ModelRoutingStore(execution_mode=mode)
        adapters = RuntimeAdapterStore(execution_mode=mode)
        employee = EmployeeRunStore(
            execution_mode=mode, routing_store=routing, adapter_store=adapters,
            goal_store=goals, workspace_store=workspaces,
        )
        stores = [employee, adapters, routing, workspaces, goals]
        goals.list_goals()
        workspaces.get_workspace("readiness-probe")
        routing.list_providers()
        adapters.list_definitions()
        employee.list_runs()
        stores_ok = True
    except Exception:
        stores_ok = False
    finally:
        for store in stores:
            try:
                store.close()
            except Exception:
                pass
    payload = _status(persistence_writable=writable, stores_ready=stores_ok)
    return JSONResponse(status_code=200 if payload["status"] == "ready" else 503,
                        content=payload)
