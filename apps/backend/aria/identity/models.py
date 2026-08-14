"""Typed identity, tenancy, and authorization contracts.

This package is the first authenticated ARIA boundary. Tokens identify a
principal and tenant, but roles and permissions are always resolved from the
authoritative store so membership changes take effect immediately.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


def utc_now() -> datetime:
    return datetime.now(UTC)


def validate_structural_id(value: str, *, field_name: str = "identifier") -> str:
    normalized = str(value).strip().lower()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must be 3-64 lowercase letters, numbers, underscores, or hyphens"
        )
    return normalized


class TenantStatus(StrEnum):
    active = "active"
    suspended = "suspended"


class PrincipalType(StrEnum):
    human = "human"
    service = "service"


class PrincipalStatus(StrEnum):
    active = "active"
    disabled = "disabled"


class MembershipStatus(StrEnum):
    active = "active"
    revoked = "revoked"


class TenantRole(StrEnum):
    owner = "owner"
    admin = "admin"
    manager = "manager"
    member = "member"
    auditor = "auditor"
    service = "service"


class Permission(StrEnum):
    tenant_read = "tenant.read"
    tenant_manage = "tenant.manage"
    member_read = "member.read"
    member_manage = "member.manage"
    work_read = "work.read"
    work_create = "work.create"
    work_approve = "work.approve"
    action_preview = "action.preview"
    action_execute = "action.execute"
    audit_read = "audit.read"


ROLE_PERMISSIONS: dict[TenantRole, frozenset[Permission]] = {
    TenantRole.owner: frozenset(Permission),
    TenantRole.admin: frozenset(Permission),
    TenantRole.manager: frozenset(
        {
            Permission.tenant_read,
            Permission.member_read,
            Permission.work_read,
            Permission.work_create,
            Permission.work_approve,
            Permission.action_preview,
            Permission.audit_read,
        }
    ),
    TenantRole.member: frozenset(
        {
            Permission.tenant_read,
            Permission.work_read,
            Permission.work_create,
            Permission.action_preview,
        }
    ),
    TenantRole.auditor: frozenset(
        {
            Permission.tenant_read,
            Permission.member_read,
            Permission.work_read,
            Permission.audit_read,
        }
    ),
    TenantRole.service: frozenset(
        {
            Permission.tenant_read,
            Permission.work_read,
            Permission.work_create,
            Permission.action_preview,
        }
    ),
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Tenant(_FrozenModel):
    tenant_id: str
    display_name: str = Field(min_length=1, max_length=160)
    status: TenantStatus = TenantStatus.active
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="tenant_id")


class Principal(_FrozenModel):
    principal_id: str
    subject: str = Field(min_length=3, max_length=255)
    principal_type: PrincipalType
    display_name: str = Field(min_length=1, max_length=160)
    status: PrincipalStatus = PrincipalStatus.active
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("principal_id")
    @classmethod
    def _principal_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="principal_id")


class Membership(_FrozenModel):
    tenant_id: str
    principal_id: str
    role: TenantRole
    status: MembershipStatus = MembershipStatus.active
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="tenant_id")

    @field_validator("principal_id")
    @classmethod
    def _principal_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="principal_id")


class TokenClaims(_FrozenModel):
    issuer: str
    audience: str
    subject: str
    principal_id: str
    tenant_id: str
    issued_at: datetime
    expires_at: datetime
    token_id: str

    @field_validator("principal_id")
    @classmethod
    def _principal_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="principal_id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="tenant_id")

    @field_validator("token_id")
    @classmethod
    def _token_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="token_id")


class IdentityContext(_FrozenModel):
    tenant: Tenant
    principal: Principal
    membership: Membership
    permissions: frozenset[Permission]
    token_id: str

    @property
    def actor(self) -> str:
        return f"{self.principal.principal_type.value}:{self.principal.principal_id}"


__all__ = [
    "IdentityContext",
    "Membership",
    "MembershipStatus",
    "Permission",
    "Principal",
    "PrincipalStatus",
    "PrincipalType",
    "ROLE_PERMISSIONS",
    "Tenant",
    "TenantRole",
    "TenantStatus",
    "TokenClaims",
    "utc_now",
    "validate_structural_id",
]
