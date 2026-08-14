"""Authenticated platform API for identity and tenant administration.

This router is intentionally separate from the legacy fixture APIs. It proves a
real authentication/authorization boundary without falsely making the existing
global stores tenant-safe. No bootstrap or token-issuance endpoint is exposed.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aria.identity import (
    AuthenticationConfigurationError,
    AuthenticationError,
    AuthorizationDenied,
    HmacTokenCodec,
    IdentityConflict,
    IdentityContext,
    IdentityService,
    IdentityStore,
    MembershipNotFound,
    Principal,
    PrincipalType,
    TenantRole,
)

_log = logging.getLogger("aria.api.platform")


@dataclass
class AuthenticatedRequest:
    context: IdentityContext
    service: IdentityService
    store: IdentityStore


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error_code": code, "detail": detail})


def _codec_from_environment() -> HmacTokenCodec:
    secret = os.getenv("ARIA_PRIVATE_AUTH_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise AuthenticationConfigurationError("private authentication is not configured")
    return HmacTokenCodec(
        secret,
        issuer=os.getenv("ARIA_AUTH_ISSUER", "aria-private-staging"),
        audience=os.getenv("ARIA_AUTH_AUDIENCE", "aria-platform"),
    )


def authenticated_request(
    authorization: str | None = Header(default=None),
) -> Iterator[AuthenticatedRequest]:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AuthenticationError("bearer credential required")
    token = authorization[7:].strip()
    if not token:
        raise AuthenticationError("bearer credential required")
    store = IdentityStore()
    try:
        service = IdentityService(store, _codec_from_environment())
        context = service.authenticate(token)
        yield AuthenticatedRequest(context=context, service=service, store=store)
    finally:
        store.close()


class AddMemberRequest(BaseModel):
    principal_id: str = Field(min_length=3, max_length=64)
    subject: str = Field(min_length=3, max_length=255)
    display_name: str = Field(min_length=1, max_length=160)
    principal_type: PrincipalType = PrincipalType.human
    role: TenantRole


platform_router = APIRouter(prefix="/api/platform", tags=["platform-identity"])


@platform_router.get("/me")
def who_am_i(auth: AuthenticatedRequest = Depends(authenticated_request)):
    context = auth.context
    return {
        "tenant": json.loads(context.tenant.model_dump_json()),
        "principal": json.loads(context.principal.model_dump_json()),
        "membership": json.loads(context.membership.model_dump_json()),
        "permissions": sorted(permission.value for permission in context.permissions),
        "data_scope": f"tenant:{context.tenant.tenant_id}",
    }


@platform_router.get("/tenants/{tenant_id}/members")
def list_members(
    tenant_id: str,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    try:
        members = auth.service.list_members(auth.context, tenant_id)
        return {
            "memberships": [json.loads(item.model_dump_json()) for item in members],
            "count": len(members),
        }
    except AuthorizationDenied:
        return _error(403, "authorization_denied", "The requested tenant scope is not allowed.")


@platform_router.post("/tenants/{tenant_id}/members")
def add_member(
    tenant_id: str,
    body: AddMemberRequest,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    try:
        principal = Principal(
            principal_id=body.principal_id,
            subject=body.subject,
            display_name=body.display_name,
            principal_type=body.principal_type,
        )
        membership = auth.service.register_principal(
            auth.context, tenant_id, principal, body.role
        )
        return JSONResponse(
            status_code=201,
            content=json.loads(membership.model_dump_json()),
        )
    except AuthorizationDenied:
        return _error(403, "authorization_denied", "Member management is not allowed.")
    except IdentityConflict:
        return _error(409, "identity_conflict", "The identity already exists.")
    except Exception as exc:
        _log.error("platform add-member failed (class only): %s", type(exc).__name__)
        return _error(400, "invalid_identity", "The identity could not be registered.")


@platform_router.delete("/tenants/{tenant_id}/members/{principal_id}")
def revoke_member(
    tenant_id: str,
    principal_id: str,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    try:
        membership = auth.service.revoke_member(
            auth.context, tenant_id, principal_id
        )
        return json.loads(membership.model_dump_json())
    except AuthorizationDenied:
        return _error(403, "authorization_denied", "Member management is not allowed.")
    except MembershipNotFound:
        return _error(404, "membership_not_found", "The membership does not exist.")
    except IdentityConflict:
        return _error(409, "owner_required", "The final tenant owner cannot be revoked.")


def install_identity_error_handlers(app) -> None:
    @app.exception_handler(AuthenticationError)
    async def _authentication_error(_request, _exc):
        return _error(401, "authentication_required", "A valid access token is required.")

    @app.exception_handler(AuthenticationConfigurationError)
    async def _configuration_error(_request, _exc):
        return _error(503, "authentication_unavailable", "Authentication is not configured.")


__all__ = [
    "authenticated_request",
    "install_identity_error_handlers",
    "platform_router",
]
