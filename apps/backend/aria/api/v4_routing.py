"""
FastAPI V4.2 model-routing API.

Localhost pilot only. **Additive** — it does NOT modify the V1/V2/V3/V4.1 APIs. It exposes
the governed model-routing layer: register/list mock providers, change provider status,
create bounded route requests, and DECIDE a route by policy (deterministic, decision-only).

    POST  /api/v4/model-routing/providers
    GET   /api/v4/model-routing/providers
    POST  /api/v4/model-routing/providers/{provider_id}/status
    POST  /api/v4/model-routing/route-requests
    POST  /api/v4/model-routing/route-requests/{request_id}/decide
    GET   /api/v4/model-routing/route-decisions

There is NO execute endpoint, NO live endpoint, NO model-invocation endpoint, NO credential
endpoint, and NO network. Every route is a DECISION (``executed=False``). ``ARIA_USER_ID``
sets the actor label — ATTRIBUTION ONLY, never authentication. Errors are typed code +
sanitised detail — never raw exception text.
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
from aria.model_routing import (
    ModelCategory,
    ModelProvider,
    ModelRoutingService,
    ModelRoutingStore,
    ProviderAlreadyExists,
    ProviderNotFound,
    ProviderStatus,
    RoutingIntegrityError,
    RoutingSecurityError,
)

_log = logging.getLogger("aria.api.v4_routing")


def actor() -> str:
    """Configurable actor label (ATTRIBUTION ONLY — not authentication)."""
    value = os.getenv("ARIA_USER_ID")
    return value if value and value.strip() else "human:local"


def _build_service():
    mode = resolve_execution_mode().value
    store = ModelRoutingStore(execution_mode=mode)
    service = ModelRoutingService(store, execution_mode=mode, actor=actor())
    return service, store


def _close(store) -> None:
    try:
        if store is not None:
            store.close()
    except Exception:  # pragma: no cover - defensive
        pass


def _safe_error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_code": code, "detail": detail})


def _dump(model: Any) -> dict[str, Any]:
    return json.loads(model.model_dump_json())


# ── Request models ────────────────────────────────────────────────────────────


class RegisterProviderBody(BaseModel):
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    vendor: str = "mock"
    status: str = "declared"


class SetStatusBody(BaseModel):
    status: str = Field(min_length=1)


class CreateRouteRequestBody(BaseModel):
    intent: str = Field(min_length=1)
    task_type: str | None = None
    sovereignty_name: str = "default"
    adapter_request_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


# ── Router ─────────────────────────────────────────────────────────────────────

v4_routing_router = APIRouter(prefix="/api/v4/model-routing", tags=["v4-model-routing"])


@v4_routing_router.post("/providers")
def register_provider(body: RegisterProviderBody):
    """Register a mock model provider (declared registry metadata — never a live client)."""
    service, store = _build_service()
    try:
        try:
            category = ModelCategory(body.category)
        except ValueError:
            return _safe_error(400, "invalid_category",
                               f"Unknown category. Valid: {[c.value for c in ModelCategory]}.")
        try:
            status = ProviderStatus(body.status)
        except ValueError:
            return _safe_error(400, "invalid_status",
                               f"Unknown status. Valid: {[s.value for s in ProviderStatus]}.")
        provider = ModelProvider(provider_id=body.provider_id, vendor=body.vendor,
                                 model_id=body.model_id, category=category, status=body.status)
        created = service.register_provider(provider, status=status)
        return JSONResponse(status_code=201, content=_dump(created))
    except ProviderAlreadyExists:
        return _safe_error(409, "provider_exists", "A provider with this id already exists.")
    except ValueError:
        return _safe_error(400, "invalid_request", "Could not register the provider.")
    finally:
        _close(store)


@v4_routing_router.get("/providers")
def list_providers(category: str | None = None, status: str | None = None):
    service, store = _build_service()
    try:
        providers = service.list_providers(category=category, status=status)
        return {"providers": [_dump(p) for p in providers], "count": len(providers)}
    finally:
        _close(store)


@v4_routing_router.post("/providers/{provider_id}/status")
def set_provider_status(provider_id: str, body: SetStatusBody):
    service, store = _build_service()
    try:
        try:
            status = ProviderStatus(body.status)
        except ValueError:
            return _safe_error(400, "invalid_status",
                               f"Unknown status. Valid: {[s.value for s in ProviderStatus]}.")
        return _dump(service.set_provider_status(provider_id, status))
    except ProviderNotFound:
        return _safe_error(404, "provider_not_found", "Unknown model provider.")
    finally:
        _close(store)


@v4_routing_router.post("/route-requests")
def create_route_request(body: CreateRouteRequestBody):
    """Create a bounded route request (a proposal to choose a model by policy — not a call)."""
    service, store = _build_service()
    try:
        req = service.create_route_request(
            intent=body.intent, task_type=body.task_type, sovereignty_name=body.sovereignty_name,
            adapter_request_id=body.adapter_request_id, source_refs=body.source_refs,
            evidence_refs=body.evidence_refs)
        return JSONResponse(status_code=201, content=_dump(req))
    except (RoutingIntegrityError, RoutingSecurityError):
        return _safe_error(400, "invalid_route_request",
                           "The route request violates routing governance policy.")
    except Exception as exc:  # class only, never raw text
        _log.error("v4 routing create_route_request error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not create the route request.")
    finally:
        _close(store)


@v4_routing_router.post("/route-requests/{request_id}/decide")
def decide_route(request_id: str):
    """Decide a route by policy (deterministic; no model call, no network, no SDK)."""
    service, store = _build_service()
    try:
        if service.get_route_request(request_id) is None:
            return _safe_error(404, "request_not_found", "Unknown route request.")
        return _dump(service.decide(request_id))
    except RoutingIntegrityError:
        return _safe_error(409, "route_not_decidable",
                           "The route request is no longer eligible for a decision.")
    except Exception as exc:  # class only, never raw text
        _log.error("v4 routing decide error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not decide the route.")
    finally:
        _close(store)


@v4_routing_router.get("/route-decisions")
def list_route_decisions(route_request_id: str | None = None, adapter_request_id: str | None = None):
    service, store = _build_service()
    try:
        decisions = service.list_route_decisions(route_request_id=route_request_id,
                                                adapter_request_id=adapter_request_id)
        return {"decisions": [_dump(d) for d in decisions], "count": len(decisions)}
    finally:
        _close(store)


def build_v4_routing_app():
    """Standalone FastAPI app exposing only the V4.2 model-routing router (tests/uvicorn)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="ARIA V4 Model Routing API", version="4.2.0",
                  description=("V4.2 model router + sovereignty mock layer — governed provider "
                               "registry + deny-by-default route gate + profile-aware, "
                               "deterministic route decisions (cheapest eligible provider; risk / "
                               "sovereignty / outage / export as hard exclusions). Localhost pilot, "
                               "MOCK/LOCAL only: no real model, provider, network, SDK, credential, "
                               "or execution. Every route is a decision (executed=False)."))
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_methods=["POST", "GET"], allow_headers=["*"],
    )
    app.include_router(v4_routing_router)
    return app
