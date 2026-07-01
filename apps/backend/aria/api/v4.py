"""
FastAPI V4.1 external-runtime-adapter API.

Localhost pilot only. **Additive** — it does NOT modify the V1/V2/V3 APIs. It exposes
the governed runtime-adapter foundation: register/enable/disable adapter definitions,
create bounded requests, and run them through the deny-by-default gate in
preview / dry-run / mock. ONLY the internal_mock adapter executes; every other adapter
type hard-blocks. There is NO live-execution endpoint, NO external-runtime endpoint, NO
credential endpoint, NO connector call, and NO network.

    POST  /api/v4/runtime-adapters
    GET   /api/v4/runtime-adapters[/{adapter_id}]
    POST  /api/v4/runtime-adapters/{adapter_id}/enable|disable
    POST  /api/v4/runtime-adapter-requests
    POST  /api/v4/runtime-adapter-requests/{request_id}/preview|execute-dry-run|execute-mock
    GET   /api/v4/runtime-adapter-receipts

``ARIA_USER_ID`` sets the actor label — ATTRIBUTION ONLY, never authentication. Errors
are typed code + sanitised detail — never raw exception text.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aria.llm import resolve_execution_mode
from aria.memory_v2.workspace import WorkspaceStore
from aria.runtime_adapters import (
    AdapterAlreadyExists,
    AdapterNotFound,
    AdapterType,
    RuntimeAdapterService,
    RuntimeAdapterStore,
)

_log = logging.getLogger("aria.api.v4")


def actor() -> str:
    """Configurable actor label (ATTRIBUTION ONLY — not authentication)."""
    value = os.getenv("ARIA_USER_ID")
    return value if value and value.strip() else "human:local"


def _build_adapters():
    mode = resolve_execution_mode().value
    store = RuntimeAdapterStore(execution_mode=mode)
    workspace_store = WorkspaceStore(execution_mode=mode)
    service = RuntimeAdapterService(store, workspace_store=workspace_store, execution_mode=mode,
                                    actor=actor())
    return service, (store, workspace_store)


def _close(*stores) -> None:
    for s in stores:
        try:
            if s is not None:
                s.close()
        except Exception:  # pragma: no cover - defensive
            pass


def _safe_error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_code": code, "detail": detail})


def _dump(model: Any) -> dict[str, Any]:
    return json.loads(model.model_dump_json())


# ── Request models ────────────────────────────────────────────────────────────


class RegisterAdapterRequest(BaseModel):
    name: str = Field(min_length=1)
    adapter_type: str = Field(min_length=1)
    adapter_id: str | None = None
    vendor: str = "internal"
    description: str = ""
    supported_task_types: list[str] = Field(default_factory=lambda: ["analysis"])
    risk_level: str = "low"
    enabled: bool = True


class CreateAdapterRequestBody(BaseModel):
    adapter_id: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    goal_id: str | None = None
    task_id: str | None = None
    workspace_id: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


# ── Router ─────────────────────────────────────────────────────────────────────

v4_router = APIRouter(prefix="/api/v4", tags=["v4"])


@v4_router.post("/runtime-adapters")
def register_adapter(body: RegisterAdapterRequest):
    """Register a runtime adapter DEFINITION (a governed description — no live connection)."""
    service, stores = _build_adapters()
    try:
        try:
            AdapterType(body.adapter_type)
        except ValueError:
            return _safe_error(400, "invalid_adapter_type",
                               f"Unknown adapter_type. Valid: {[a.value for a in AdapterType]}.")
        d = service.register_adapter(
            name=body.name, adapter_type=body.adapter_type, adapter_id=body.adapter_id,
            vendor=body.vendor, description=body.description,
            supported_task_types=body.supported_task_types, risk_level=body.risk_level,
            enabled=body.enabled)
        return JSONResponse(status_code=201, content=_dump(d))
    except AdapterAlreadyExists:
        return _safe_error(409, "adapter_exists", "An adapter with this id already exists.")
    except ValueError:
        return _safe_error(400, "invalid_request", "Could not register the adapter.")
    finally:
        _close(*stores)


@v4_router.get("/runtime-adapters")
def list_adapters(enabled: bool | None = None, adapter_type: str | None = None):
    service, stores = _build_adapters()
    try:
        defs = service.list_adapters(enabled=enabled, adapter_type=adapter_type)
        return {"adapters": [_dump(d) for d in defs], "count": len(defs)}
    finally:
        _close(*stores)


@v4_router.get("/runtime-adapter-receipts")
def list_receipts(request_id: str | None = None, adapter_id: str | None = None):
    service, stores = _build_adapters()
    try:
        recs = service.list_receipts(request_id=request_id, adapter_id=adapter_id)
        return {"receipts": [_dump(r) for r in recs], "count": len(recs)}
    finally:
        _close(*stores)


@v4_router.get("/runtime-adapters/{adapter_id}")
def get_adapter(adapter_id: str):
    service, stores = _build_adapters()
    try:
        d = service.get_adapter_definition(adapter_id)
        if d is None:
            return _safe_error(404, "adapter_not_found", "Unknown runtime adapter.")
        caps = service.list_capabilities(adapter_id)
        return {"adapter": _dump(d), "capabilities": [_dump(c) for c in caps]}
    finally:
        _close(*stores)


@v4_router.post("/runtime-adapters/{adapter_id}/enable")
def enable_adapter(adapter_id: str):
    service, stores = _build_adapters()
    try:
        return _dump(service.enable(adapter_id))
    except AdapterNotFound:
        return _safe_error(404, "adapter_not_found", "Unknown runtime adapter.")
    finally:
        _close(*stores)


@v4_router.post("/runtime-adapters/{adapter_id}/disable")
def disable_adapter(adapter_id: str):
    service, stores = _build_adapters()
    try:
        return _dump(service.disable(adapter_id))
    except AdapterNotFound:
        return _safe_error(404, "adapter_not_found", "Unknown runtime adapter.")
    finally:
        _close(*stores)


@v4_router.post("/runtime-adapter-requests")
def create_request(body: CreateAdapterRequestBody):
    """Create a bounded runtime-adapter request (a proposal to run a worker — not a run)."""
    service, stores = _build_adapters()
    try:
        if service.get_adapter_definition(body.adapter_id) is None:
            return _safe_error(404, "adapter_not_found", "Unknown runtime adapter.")
        req = service.create_request(
            adapter_id=body.adapter_id, task_type=body.task_type, goal_id=body.goal_id,
            task_id=body.task_id, workspace_id=body.workspace_id, input_payload=body.input_payload,
            source_refs=body.source_refs, evidence_refs=body.evidence_refs)
        return JSONResponse(status_code=201, content=_dump(req))
    except Exception as exc:  # class only, never raw text
        _log.error("v4 create_request error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not create the request.")
    finally:
        _close(*stores)


def _request_step(request_id: str, fn_name: str):
    service, stores = _build_adapters()
    try:
        if service.get_request(request_id) is None:
            return _safe_error(404, "request_not_found", "Unknown runtime-adapter request.")
        return _dump(getattr(service, fn_name)(request_id))
    except Exception as exc:  # class only, never raw text
        _log.error("v4 %s error (class only): %s", fn_name, type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not run the request step.")
    finally:
        _close(*stores)


@v4_router.post("/runtime-adapter-requests/{request_id}/preview")
def preview_request(request_id: str):
    """Preview what would happen (no execution, no network, no SDK call)."""
    return _request_step(request_id, "preview")


@v4_router.post("/runtime-adapter-requests/{request_id}/execute-dry-run")
def execute_dry_run(request_id: str):
    """Dry-run (internal_mock only; writes nothing). Future adapters hard-block."""
    return _request_step(request_id, "execute_dry_run")


@v4_router.post("/runtime-adapter-requests/{request_id}/execute-mock")
def execute_mock(request_id: str):
    """Mock run (internal_mock only; local receipt only). Future adapters hard-block."""
    return _request_step(request_id, "execute_mock")


def build_v4_app():
    """Standalone FastAPI app exposing only the V4 router (used by tests/uvicorn)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="ARIA V4 API", version="4.1.0",
                  description=("V4.1 external runtime adapter foundation — governed adapter "
                               "definitions + deny-by-default gate + internal_mock execution "
                               "(preview/dry-run/mock) + future stubs (hard-blocked) + model "
                               "router/sovereignty contracts + evaluation hooks. Localhost pilot, "
                               "MOCK/LOCAL only: no real external runtime, model API, network, SDK, "
                               "subprocess, credential, live execution, or deployment."))
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_methods=["POST", "GET"], allow_headers=["*"],
    )
    app.include_router(v4_router)
    return app
