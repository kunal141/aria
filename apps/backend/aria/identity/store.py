"""Authoritative SQLite identity and tenant-membership store."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aria.goals.sanitize import sanitize_text
from aria.identity.models import (
    Membership,
    MembershipStatus,
    Principal,
    PrincipalStatus,
    PrincipalType,
    Tenant,
    TenantRole,
    TenantStatus,
)
from aria.ledger import ActionTaken, ActorType
from aria.ledger.events import ActionTier, make_envelope
from aria.memory_v2.paths import ensure_confined, identity_db_path

_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS tenant (
    tenant_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS principal (
    principal_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL UNIQUE,
    principal_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS membership (
    tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),
    principal_id TEXT NOT NULL REFERENCES principal(principal_id),
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, principal_id)
);
CREATE TABLE IF NOT EXISTS audit_outbox (
    outbox_id TEXT PRIMARY KEY,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    flushed_at TEXT
);
"""


class IdentityStoreError(RuntimeError):
    pass


class TenantNotFound(IdentityStoreError):
    pass


class PrincipalNotFound(IdentityStoreError):
    pass


class MembershipNotFound(IdentityStoreError):
    pass


class IdentityConflict(IdentityStoreError):
    pass


class IdentitySecurityError(IdentityStoreError):
    pass


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _safe_structural(value: str, *, field_name: str) -> str:
    if sanitize_text(value) != value:
        raise IdentitySecurityError(f"{field_name} cannot contain credential-shaped content")
    return value


class IdentityStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None) -> None:
        resolved = Path(db_path) if db_path is not None else identity_db_path()
        self._db_path = ensure_confined(resolved)
        self._writer = writer
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _enqueue(
        self,
        conn: sqlite3.Connection,
        *,
        operation: str,
        tenant_id: str,
        actor: str,
        principal_id: str | None = None,
        role: TenantRole | None = None,
    ) -> None:
        task_id = f"identity-{uuid.uuid4().hex}"
        metadata = {
            "operation": operation,
            "tenant_id": tenant_id,
        }
        if principal_id is not None:
            metadata["principal_id"] = principal_id
        if role is not None:
            metadata["role"] = role.value
        event = ActionTaken(
            **make_envelope(
                task_id=task_id,
                correlation_id=tenant_id,
                actor=sanitize_text(actor) or "system:identity",
                actor_type=ActorType.system if actor.startswith("system:") else ActorType.human,
                action_tier=ActionTier.T4,
                risk_level="medium",
                status="recorded",
                outcome=operation,
                metadata=metadata,
            )
        )
        conn.execute(
            "INSERT INTO audit_outbox (outbox_id,event_json,created_at,flushed_at) "
            "VALUES (?,?,?,NULL)",
            (f"obx-{uuid.uuid4().hex}", event.model_dump_json(), _iso(datetime.now(UTC))),
        )

    def _resolve_writer(self, writer: Any = None):
        if writer is not None:
            return writer
        if self._writer is not None:
            return self._writer
        from aria.ledger.writer import get_default_writer

        return get_default_writer()

    def flush_outbox(self, writer: Any = None) -> int:
        conn = self._connect()
        target = self._resolve_writer(writer)
        rows = conn.execute(
            "SELECT outbox_id,event_json FROM audit_outbox "
            "WHERE flushed_at IS NULL ORDER BY rowid"
        ).fetchall()
        flushed = 0
        for row in rows:
            try:
                target.append(json.loads(row["event_json"]))
            except Exception:
                break
            with conn:
                conn.execute(
                    "UPDATE audit_outbox SET flushed_at=? WHERE outbox_id=?",
                    (_iso(datetime.now(UTC)), row["outbox_id"]),
                )
            flushed += 1
        return flushed

    def pending_audit_count(self) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS count FROM audit_outbox WHERE flushed_at IS NULL"
        ).fetchone()
        return int(row["count"])

    def bootstrap_tenant(
        self,
        tenant: Tenant,
        owner: Principal,
        *,
        actor: str = "system:bootstrap",
    ) -> Membership:
        _safe_structural(tenant.tenant_id, field_name="tenant_id")
        _safe_structural(owner.principal_id, field_name="principal_id")
        _safe_structural(owner.subject, field_name="subject")
        safe_tenant_name = sanitize_text(tenant.display_name) or "Tenant"
        safe_owner_name = sanitize_text(owner.display_name) or "Owner"
        if safe_tenant_name != tenant.display_name or safe_owner_name != owner.display_name:
            raise IdentitySecurityError("identity display names cannot contain secrets")
        membership = Membership(
            tenant_id=tenant.tenant_id,
            principal_id=owner.principal_id,
            role=TenantRole.owner,
        )
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO tenant (tenant_id,display_name,status,created_at) VALUES (?,?,?,?)",
                    (
                        tenant.tenant_id,
                        safe_tenant_name,
                        tenant.status.value,
                        _iso(tenant.created_at),
                    ),
                )
                conn.execute(
                    "INSERT INTO principal "
                    "(principal_id,subject,principal_type,display_name,status,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        owner.principal_id,
                        owner.subject,
                        owner.principal_type.value,
                        safe_owner_name,
                        owner.status.value,
                        _iso(owner.created_at),
                    ),
                )
                conn.execute(
                    "INSERT INTO membership "
                    "(tenant_id,principal_id,role,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        membership.tenant_id,
                        membership.principal_id,
                        membership.role.value,
                        membership.status.value,
                        _iso(membership.created_at),
                        _iso(membership.updated_at),
                    ),
                )
                self._enqueue(
                    conn,
                    operation="tenant_bootstrapped",
                    tenant_id=tenant.tenant_id,
                    actor=actor,
                    principal_id=owner.principal_id,
                    role=TenantRole.owner,
                )
        except sqlite3.IntegrityError as exc:
            raise IdentityConflict("tenant, subject, or principal already exists") from exc
        self.flush_outbox()
        return membership

    def register_principal(
        self,
        principal: Principal,
        *,
        actor: str,
        tenant_id: str,
    ) -> Principal:
        _safe_structural(principal.principal_id, field_name="principal_id")
        _safe_structural(principal.subject, field_name="subject")
        safe_name = sanitize_text(principal.display_name) or "Principal"
        if safe_name != principal.display_name:
            raise IdentitySecurityError("principal display name cannot contain secrets")
        if self.get_tenant(tenant_id) is None:
            raise TenantNotFound(tenant_id)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO principal "
                    "(principal_id,subject,principal_type,display_name,status,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        principal.principal_id,
                        principal.subject,
                        principal.principal_type.value,
                        safe_name,
                        principal.status.value,
                        _iso(principal.created_at),
                    ),
                )
                self._enqueue(
                    conn,
                    operation="principal_registered",
                    tenant_id=tenant_id,
                    actor=actor,
                    principal_id=principal.principal_id,
                )
        except sqlite3.IntegrityError as exc:
            raise IdentityConflict("subject or principal already exists") from exc
        self.flush_outbox()
        return principal

    def grant_membership(
        self,
        membership: Membership,
        *,
        actor: str,
    ) -> Membership:
        if self.get_tenant(membership.tenant_id) is None:
            raise TenantNotFound(membership.tenant_id)
        if self.get_principal(membership.principal_id) is None:
            raise PrincipalNotFound(membership.principal_id)
        conn = self._connect()
        now = datetime.now(UTC)
        result = membership.model_copy(
            update={"status": MembershipStatus.active, "updated_at": now}
        )
        with conn:
            conn.execute(
                "INSERT INTO membership "
                "(tenant_id,principal_id,role,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(tenant_id,principal_id) DO UPDATE SET "
                "role=excluded.role,status=excluded.status,updated_at=excluded.updated_at",
                (
                    result.tenant_id,
                    result.principal_id,
                    result.role.value,
                    result.status.value,
                    _iso(result.created_at),
                    _iso(result.updated_at),
                ),
            )
            self._enqueue(
                conn,
                operation="membership_granted",
                tenant_id=result.tenant_id,
                actor=actor,
                principal_id=result.principal_id,
                role=result.role,
            )
        self.flush_outbox()
        return result

    def revoke_membership(self, tenant_id: str, principal_id: str, *, actor: str) -> Membership:
        current = self.get_membership(tenant_id, principal_id)
        if current is None:
            raise MembershipNotFound(f"{tenant_id}:{principal_id}")
        if current.role is TenantRole.owner and current.status is MembershipStatus.active:
            owners = [
                item
                for item in self.list_memberships(tenant_id)
                if item.role is TenantRole.owner and item.status is MembershipStatus.active
            ]
            if len(owners) <= 1:
                raise IdentityConflict("the final active tenant owner cannot be revoked")
        now = datetime.now(UTC)
        revoked = current.model_copy(
            update={"status": MembershipStatus.revoked, "updated_at": now}
        )
        conn = self._connect()
        with conn:
            conn.execute(
                "UPDATE membership SET status=?,updated_at=? "
                "WHERE tenant_id=? AND principal_id=?",
                (revoked.status.value, _iso(now), tenant_id, principal_id),
            )
            self._enqueue(
                conn,
                operation="membership_revoked",
                tenant_id=tenant_id,
                actor=actor,
                principal_id=principal_id,
                role=current.role,
            )
        self.flush_outbox()
        return revoked

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        row = self._connect().execute(
            "SELECT * FROM tenant WHERE tenant_id=?", (tenant_id,)
        ).fetchone()
        if row is None:
            return None
        return Tenant(
            tenant_id=row["tenant_id"],
            display_name=row["display_name"],
            status=TenantStatus(row["status"]),
            created_at=_dt(row["created_at"]),
        )

    def get_principal(self, principal_id: str) -> Principal | None:
        row = self._connect().execute(
            "SELECT * FROM principal WHERE principal_id=?", (principal_id,)
        ).fetchone()
        if row is None:
            return None
        return Principal(
            principal_id=row["principal_id"],
            subject=row["subject"],
            principal_type=PrincipalType(row["principal_type"]),
            display_name=row["display_name"],
            status=PrincipalStatus(row["status"]),
            created_at=_dt(row["created_at"]),
        )

    def get_principal_by_subject(self, subject: str) -> Principal | None:
        row = self._connect().execute(
            "SELECT principal_id FROM principal WHERE subject=?", (subject,)
        ).fetchone()
        return self.get_principal(row["principal_id"]) if row else None

    def get_membership(self, tenant_id: str, principal_id: str) -> Membership | None:
        row = self._connect().execute(
            "SELECT * FROM membership WHERE tenant_id=? AND principal_id=?",
            (tenant_id, principal_id),
        ).fetchone()
        if row is None:
            return None
        return Membership(
            tenant_id=row["tenant_id"],
            principal_id=row["principal_id"],
            role=TenantRole(row["role"]),
            status=MembershipStatus(row["status"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def list_memberships(self, tenant_id: str) -> list[Membership]:
        rows = self._connect().execute(
            "SELECT principal_id FROM membership WHERE tenant_id=? ORDER BY principal_id",
            (tenant_id,),
        ).fetchall()
        return [
            item
            for row in rows
            if (item := self.get_membership(tenant_id, row["principal_id"])) is not None
        ]


__all__ = [
    "IdentityConflict",
    "IdentitySecurityError",
    "IdentityStore",
    "IdentityStoreError",
    "MembershipNotFound",
    "PrincipalNotFound",
    "TenantNotFound",
]
