"""Private-staging FastAPI composition over the accepted ARIA API surfaces."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aria.api.platform import install_identity_error_handlers, platform_router
from aria.api.platform_employee import router as platform_employee_router
from aria.api.platform_integrations import router as platform_integrations_router
from aria.api.skills import skills_router
from aria.api.staging_health import staging_health_router
from aria.api.v2 import v2_router
from aria.api.v3 import v3_router
from aria.api.v4 import v4_router
from aria.api.v4_employee import v4_employee_router
from aria.api.v4_routing import v4_routing_router
from aria.ledger.api import router as ledger_router
from aria.voice.router import router as voice_router


def build_staging_app() -> FastAPI:
    """Compose existing governed APIs for localhost-only private staging."""
    app = FastAPI(
        title="ARIA Private Staging API",
        version="private-staging-1",
        description=(
            "Deterministic offline private staging: fixture connectors, mock execution, "
            "and live execution disabled."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8080", "http://localhost:8080"],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(staging_health_router)
    app.include_router(skills_router)
    install_identity_error_handlers(app)
    app.include_router(platform_router)
    app.include_router(platform_employee_router)
    app.include_router(platform_integrations_router)
    app.include_router(ledger_router)
    app.include_router(v2_router)
    app.include_router(v3_router)
    app.include_router(v4_router)
    app.include_router(v4_routing_router)
    app.include_router(v4_employee_router)
    app.include_router(voice_router)
    return app


__all__ = ["build_staging_app"]
