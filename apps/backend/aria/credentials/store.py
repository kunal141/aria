"""Tenant-confined encrypted credential authority with durable audit outbox."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aria.credentials.crypto import CredentialCipher, EncryptedSecret
from aria.credentials.models import (
    CredentialMetadata,
    CredentialProvider,
    CredentialStatus,
    utc_now,
)
from aria.goals.sanitize import sanitize_text
from aria.identity.models import validate_structural_id
from aria.ledger import ActionTaken, ActorType
from aria.ledger.events import ActionTier, make_envelope
from aria.memory_v2.paths import ensure_confined

_SCHEMA = """
CREATE TABLE IF NOT EXISTS credential (
    credential_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    label TEXT NOT NULL,
    username TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,
    key_id TEXT NOT NULL,
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_outbox (
    outbox_id TEXT PRIMARY KEY,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    flushed_at TEXT
);
"""


class CredentialNotFound(LookupError):
    pass


class CredentialInactive(RuntimeError):
    pass


class CredentialSecurityError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedCredential:
    metadata: CredentialMetadata
    secret: str = field(repr=False)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _safe_text(value: str, *, field_name: str) -> str:
    safe = sanitize_text(value)
    if safe != value:
        raise CredentialSecurityError(f"{field_name} cannot contain credential-shaped content")
    return value.strip()


def _safe_endpoint(value: str) -> str:
    endpoint = _safe_text(value, field_name="endpoint_url").rstrip("/")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise CredentialSecurityError("endpoint_url is malformed") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise CredentialSecurityError("endpoint_url must be a credential-free HTTPS origin")
    return endpoint


class CredentialVaultStore:
    def __init__(
        self,
        db_path: Path | str,
        *,
        tenant_id: str,
        cipher: CredentialCipher,
        writer: Any = None,
    ) -> None:
        self._db_path = ensure_confined(Path(db_path))
        self.tenant_id = validate_structural_id(tenant_id, field_name="tenant_id")
        self._cipher = cipher
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

    def _aad(self, credential_id: str, provider: CredentialProvider, version: int) -> bytes:
        return f"aria:{self.tenant_id}:{credential_id}:{provider.value}:{version}".encode()

    def _enqueue(
        self,
        conn: sqlite3.Connection,
        *,
        operation: str,
        credential_id: str,
        provider: CredentialProvider,
        version: int,
        actor: str,
    ) -> None:
        event = ActionTaken(
            **make_envelope(
                task_id=f"credential-{uuid.uuid4().hex}",
                correlation_id=self.tenant_id,
                actor=sanitize_text(actor) or "system:credentials",
                actor_type=ActorType.system if actor.startswith("system:") else ActorType.human,
                action_tier=ActionTier.T4,
                risk_level="high",
                status="recorded",
                outcome=operation,
                metadata={
                    "tenant_id": self.tenant_id,
                    "credential_id": credential_id,
                    "provider": provider.value,
                    "version": version,
                },
            )
        )
        conn.execute(
            "INSERT INTO audit_outbox (outbox_id,event_json,created_at,flushed_at) "
            "VALUES (?,?,?,NULL)",
            (f"obx-{uuid.uuid4().hex}", event.model_dump_json(), _iso(utc_now())),
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
                    (_iso(utc_now()), row["outbox_id"]),
                )
            flushed += 1
        return flushed

    def pending_audit_count(self) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS count FROM audit_outbox WHERE flushed_at IS NULL"
        ).fetchone()
        return int(row["count"])

    def put_secret(
        self,
        *,
        credential_id: str,
        provider: CredentialProvider,
        label: str,
        username: str,
        endpoint_url: str,
        secret: str,
        actor: str,
    ) -> CredentialMetadata:
        credential_id = validate_structural_id(credential_id, field_name="credential_id")
        label = _safe_text(label, field_name="label")
        username = _safe_text(username, field_name="username")
        endpoint_url = _safe_endpoint(endpoint_url)
        conn = self._connect()
        existing = conn.execute(
            "SELECT * FROM credential WHERE credential_id=?", (credential_id,)
        ).fetchone()
        if existing is not None and existing["tenant_id"] != self.tenant_id:
            raise CredentialSecurityError("credential row belongs to another tenant")
        if existing is not None and existing["status"] == CredentialStatus.revoked.value:
            raise CredentialInactive("revoked credentials cannot be rotated")
        version = int(existing["version"]) + 1 if existing else 1
        encrypted = self._cipher.encrypt(
            secret, aad=self._aad(credential_id, provider, version)
        )
        now = utc_now()
        created_at = existing["created_at"] if existing else _iso(now)
        operation = "credential_rotated" if existing else "credential_created"
        with conn:
            conn.execute(
                "INSERT INTO credential "
                "(credential_id,tenant_id,provider,label,username,endpoint_url,key_id,nonce,"
                "ciphertext,version,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(credential_id) DO UPDATE SET provider=excluded.provider,"
                "label=excluded.label,username=excluded.username,endpoint_url=excluded.endpoint_url,"
                "key_id=excluded.key_id,nonce=excluded.nonce,ciphertext=excluded.ciphertext,"
                "version=excluded.version,status=excluded.status,updated_at=excluded.updated_at",
                (
                    credential_id,
                    self.tenant_id,
                    provider.value,
                    label,
                    username,
                    endpoint_url,
                    encrypted.key_id,
                    encrypted.nonce,
                    encrypted.ciphertext,
                    version,
                    CredentialStatus.active.value,
                    created_at,
                    _iso(now),
                ),
            )
            self._enqueue(
                conn,
                operation=operation,
                credential_id=credential_id,
                provider=provider,
                version=version,
                actor=actor,
            )
        self.flush_outbox()
        return self.get_metadata(credential_id)  # type: ignore[return-value]

    def list_metadata(self, *, provider: CredentialProvider | None = None) -> list[CredentialMetadata]:
        if provider is None:
            rows = self._connect().execute(
                "SELECT * FROM credential ORDER BY created_at,credential_id"
            ).fetchall()
        else:
            rows = self._connect().execute(
                "SELECT * FROM credential WHERE provider=? ORDER BY created_at,credential_id",
                (provider.value,),
            ).fetchall()
        return [self._metadata(row) for row in rows]

    def get_metadata(self, credential_id: str) -> CredentialMetadata | None:
        credential_id = validate_structural_id(credential_id, field_name="credential_id")
        row = self._connect().execute(
            "SELECT * FROM credential WHERE credential_id=?", (credential_id,)
        ).fetchone()
        return self._metadata(row) if row else None

    def resolve_secret(self, credential_id: str, *, actor: str) -> ResolvedCredential:
        credential_id = validate_structural_id(credential_id, field_name="credential_id")
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM credential WHERE credential_id=?", (credential_id,)
        ).fetchone()
        if row is None:
            raise CredentialNotFound(credential_id)
        metadata = self._metadata(row)
        if metadata.status is not CredentialStatus.active:
            raise CredentialInactive("credential is not active")
        with conn:
            self._enqueue(
                conn,
                operation="credential_access_attempted",
                credential_id=credential_id,
                provider=metadata.provider,
                version=metadata.version,
                actor=actor,
            )
        self.flush_outbox()
        secret = self._cipher.decrypt(
            EncryptedSecret(
                key_id=row["key_id"], nonce=bytes(row["nonce"]), ciphertext=bytes(row["ciphertext"])
            ),
            aad=self._aad(credential_id, metadata.provider, metadata.version),
        )
        return ResolvedCredential(metadata=metadata, secret=secret)

    def revoke(self, credential_id: str, *, actor: str) -> CredentialMetadata:
        credential_id = validate_structural_id(credential_id, field_name="credential_id")
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM credential WHERE credential_id=?", (credential_id,)
        ).fetchone()
        if row is None:
            raise CredentialNotFound(credential_id)
        metadata = self._metadata(row)
        if metadata.status is CredentialStatus.revoked:
            return metadata
        with conn:
            conn.execute(
                "UPDATE credential SET status=?,nonce=?,ciphertext=?,updated_at=? "
                "WHERE credential_id=?",
                (CredentialStatus.revoked.value, b"", b"", _iso(utc_now()), credential_id),
            )
            self._enqueue(
                conn,
                operation="credential_revoked",
                credential_id=credential_id,
                provider=metadata.provider,
                version=metadata.version,
                actor=actor,
            )
        self.flush_outbox()
        return self.get_metadata(credential_id)  # type: ignore[return-value]

    def _metadata(self, row: sqlite3.Row) -> CredentialMetadata:
        if row["tenant_id"] != self.tenant_id:
            raise CredentialSecurityError("credential row belongs to another tenant")
        return CredentialMetadata(
            credential_id=row["credential_id"],
            tenant_id=row["tenant_id"],
            provider=CredentialProvider(row["provider"]),
            label=row["label"],
            username=row["username"],
            endpoint_url=row["endpoint_url"],
            key_id=row["key_id"],
            version=int(row["version"]),
            status=CredentialStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


__all__ = [
    "CredentialInactive",
    "CredentialNotFound",
    "CredentialSecurityError",
    "CredentialVaultStore",
    "ResolvedCredential",
]
