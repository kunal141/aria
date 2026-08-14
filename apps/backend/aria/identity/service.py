"""Authentication and store-authoritative authorization service."""
from __future__ import annotations

from aria.identity.models import (
    ROLE_PERMISSIONS,
    IdentityContext,
    Membership,
    MembershipStatus,
    Permission,
    Principal,
    PrincipalStatus,
    TenantRole,
    TenantStatus,
)
from aria.identity.store import IdentityStore, PrincipalNotFound
from aria.identity.tokens import AuthenticationError, TokenVerifier


class AuthorizationDenied(PermissionError):
    """An authenticated identity lacks the requested tenant permission."""


class IdentityService:
    def __init__(self, store: IdentityStore, verifier: TokenVerifier) -> None:
        self._store = store
        self._verifier = verifier

    def authenticate(self, token: str) -> IdentityContext:
        claims = self._verifier.verify(token)
        tenant = self._store.get_tenant(claims.tenant_id)
        if tenant is None:
            raise AuthenticationError("token tenant is not registered")
        if tenant.status is not TenantStatus.active:
            raise AuthenticationError("token tenant is unavailable")
        principal = self._store.get_principal(claims.principal_id)
        if principal is None or principal.subject != claims.subject:
            raise AuthenticationError("token principal is not registered")
        if principal.status is not PrincipalStatus.active:
            raise AuthenticationError("token principal is disabled")
        membership = self._store.get_membership(claims.tenant_id, claims.principal_id)
        if membership is None or membership.status is not MembershipStatus.active:
            raise AuthenticationError("token membership is inactive")
        return IdentityContext(
            tenant=tenant,
            principal=principal,
            membership=membership,
            permissions=ROLE_PERMISSIONS[membership.role],
            token_id=claims.token_id,
        )

    @staticmethod
    def require(
        context: IdentityContext,
        permission: Permission,
        *,
        tenant_id: str | None = None,
    ) -> None:
        if tenant_id is not None and context.tenant.tenant_id != tenant_id:
            raise AuthorizationDenied("cross-tenant access is forbidden")
        if permission not in context.permissions:
            raise AuthorizationDenied("permission is not granted")

    def list_members(self, context: IdentityContext, tenant_id: str) -> list[Membership]:
        self.require(context, Permission.member_read, tenant_id=tenant_id)
        return self._store.list_memberships(tenant_id)

    def register_principal(
        self,
        context: IdentityContext,
        tenant_id: str,
        principal: Principal,
        role: TenantRole,
    ) -> Membership:
        self.require(context, Permission.member_manage, tenant_id=tenant_id)
        existing = self._store.get_principal(principal.principal_id)
        if existing is None:
            self._store.register_principal(
                principal, actor=context.actor, tenant_id=tenant_id
            )
        elif existing.subject != principal.subject:
            raise PrincipalNotFound(principal.principal_id)
        return self._store.grant_membership(
            Membership(tenant_id=tenant_id, principal_id=principal.principal_id, role=role),
            actor=context.actor,
        )

    def revoke_member(
        self, context: IdentityContext, tenant_id: str, principal_id: str
    ) -> Membership:
        self.require(context, Permission.member_manage, tenant_id=tenant_id)
        return self._store.revoke_membership(
            tenant_id, principal_id, actor=context.actor
        )


__all__ = ["AuthorizationDenied", "IdentityService"]
