"""Production-foundation tests for authenticated tenant identity."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aria.api.staging import build_staging_app
from aria.identity import (
    AuthenticationConfigurationError,
    AuthenticationError,
    HmacTokenCodec,
    IdentityConflict,
    IdentitySecurityError,
    IdentityService,
    IdentityStore,
    MembershipStatus,
    Permission,
    Principal,
    PrincipalType,
    Tenant,
    TenantRole,
)
from aria.identity.cli import main as identity_cli
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter, reset_default_writer
from aria.memory_v2.paths import PathConfinementError, tenant_data_dir

_KEY = "private-staging-test-key-material-000000000000000000"


def _principal(principal_id: str, *, principal_type=PrincipalType.human) -> Principal:
    return Principal(
        principal_id=principal_id,
        subject=f"subject-{principal_id}",
        principal_type=principal_type,
        display_name=principal_id.replace("-", " ").title(),
    )


def _bootstrap(
    tmp_path: Path,
    *,
    tenant_id: str = "tenant-alpha",
    owner_id: str = "owner-alpha",
    writer=None,
):
    store = IdentityStore(writer=writer or LedgerWriter(tmp_path / "identity-ledger.jsonl"))
    tenant = Tenant(tenant_id=tenant_id, display_name=f"{tenant_id} organization")
    owner = _principal(owner_id)
    store.bootstrap_tenant(tenant, owner)
    codec = HmacTokenCodec(_KEY)
    token = codec.issue(
        subject=owner.subject,
        principal_id=owner.principal_id,
        tenant_id=tenant.tenant_id,
    )
    return store, tenant, owner, codec, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _configure_api(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "aria-data"
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    monkeypatch.setenv("ARIA_LEDGER_V2_PATH", str(root / "work_ledger_v2.jsonl"))
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "offline_mock")
    monkeypatch.setenv("ARIA_CONNECTOR_MODE", "fixtures")
    monkeypatch.setenv("CONNECTOR_MODE", "fixtures")
    monkeypatch.setenv("ARIA_LIVE_EXECUTION", "false")
    monkeypatch.setenv("ARIA_PRIVATE_AUTH_SECRET", _KEY)
    reset_default_writer()


def test_token_is_signed_bounded_and_rejects_tampering():
    codec = HmacTokenCodec(_KEY)
    now = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    token = codec.issue(
        subject="subject-owner",
        principal_id="owner-alpha",
        tenant_id="tenant-alpha",
        ttl=timedelta(minutes=10),
        now=now,
    )
    claims = codec.verify(token, now=now + timedelta(minutes=1))
    assert claims.principal_id == "owner-alpha"
    assert claims.tenant_id == "tenant-alpha"
    assert "owner" not in token

    prefix, payload, signature = token.split(".")
    replacement = "A" if payload[-1] != "A" else "B"
    with pytest.raises(AuthenticationError):
        codec.verify(f"{prefix}.{payload[:-1]}{replacement}.{signature}", now=now)
    with pytest.raises(AuthenticationError, match="expired"):
        codec.verify(token, now=now + timedelta(minutes=11))
    with pytest.raises(ValueError, match="lifetime"):
        codec.issue(
            subject="subject-owner",
            principal_id="owner-alpha",
            tenant_id="tenant-alpha",
            ttl=timedelta(hours=2),
            now=now,
        )


def test_token_configuration_requires_strong_key():
    with pytest.raises(AuthenticationConfigurationError):
        HmacTokenCodec("too-short")


def test_store_is_restart_safe_and_membership_is_authoritative(tmp_path):
    store, tenant, owner, codec, token = _bootstrap(tmp_path)
    path = store.db_path
    store.close()

    reopened = IdentityStore(path, writer=LedgerWriter(tmp_path / "restart-ledger.jsonl"))
    context = IdentityService(reopened, codec).authenticate(token)
    assert context.tenant == tenant
    assert context.principal == owner
    assert context.membership.role is TenantRole.owner
    assert Permission.member_manage in context.permissions
    reopened.close()


def test_cross_tenant_access_is_denied_even_with_valid_token(tmp_path):
    store, _tenant, _owner, codec, token = _bootstrap(tmp_path)
    second = Tenant(tenant_id="tenant-beta", display_name="Tenant Beta")
    beta_owner = _principal("owner-beta")
    store.bootstrap_tenant(second, beta_owner)
    service = IdentityService(store, codec)
    context = service.authenticate(token)
    with pytest.raises(PermissionError, match="cross-tenant"):
        service.list_members(context, "tenant-beta")
    store.close()


def test_member_cannot_manage_members_and_service_cannot_approve(tmp_path):
    store, tenant, _owner, codec, token = _bootstrap(tmp_path)
    owner_context = IdentityService(store, codec).authenticate(token)
    member = _principal("member-alpha")
    IdentityService(store, codec).register_principal(
        owner_context, tenant.tenant_id, member, TenantRole.member
    )
    member_token = codec.issue(
        subject=member.subject,
        principal_id=member.principal_id,
        tenant_id=tenant.tenant_id,
    )
    member_context = IdentityService(store, codec).authenticate(member_token)
    assert Permission.member_manage not in member_context.permissions
    with pytest.raises(PermissionError, match="permission"):
        IdentityService(store, codec).register_principal(
            member_context,
            tenant.tenant_id,
            _principal("other-member"),
            TenantRole.member,
        )

    service_principal = _principal("service-alpha", principal_type=PrincipalType.service)
    IdentityService(store, codec).register_principal(
        owner_context, tenant.tenant_id, service_principal, TenantRole.service
    )
    service_token = codec.issue(
        subject=service_principal.subject,
        principal_id=service_principal.principal_id,
        tenant_id=tenant.tenant_id,
    )
    service_context = IdentityService(store, codec).authenticate(service_token)
    assert Permission.work_approve not in service_context.permissions
    assert Permission.action_execute not in service_context.permissions
    store.close()


def test_membership_revocation_invalidates_existing_token_immediately(tmp_path):
    store, tenant, _owner, codec, owner_token = _bootstrap(tmp_path)
    service = IdentityService(store, codec)
    owner_context = service.authenticate(owner_token)
    member = _principal("member-alpha")
    service.register_principal(owner_context, tenant.tenant_id, member, TenantRole.member)
    member_token = codec.issue(
        subject=member.subject,
        principal_id=member.principal_id,
        tenant_id=tenant.tenant_id,
    )
    assert service.authenticate(member_token).membership.status is MembershipStatus.active
    service.revoke_member(owner_context, tenant.tenant_id, member.principal_id)
    with pytest.raises(AuthenticationError, match="membership"):
        service.authenticate(member_token)
    store.close()


def test_final_owner_cannot_be_revoked(tmp_path):
    store, tenant, owner, codec, token = _bootstrap(tmp_path)
    context = IdentityService(store, codec).authenticate(token)
    with pytest.raises(IdentityConflict, match="final active"):
        IdentityService(store, codec).revoke_member(
            context, tenant.tenant_id, owner.principal_id
        )
    assert store.get_membership(tenant.tenant_id, owner.principal_id).status is (
        MembershipStatus.active
    )
    store.close()


def test_store_rejects_outside_path_and_secret_structural_identity(tmp_path):
    with pytest.raises(PathConfinementError):
        IdentityStore(tmp_path.parent / "outside" / "identity.sqlite")
    store = IdentityStore(writer=LedgerWriter(tmp_path / "secrets-ledger.jsonl"))
    with pytest.raises((IdentitySecurityError, ValueError)):
        store.bootstrap_tenant(
            Tenant(tenant_id="tenant-safe", display_name="Tenant Safe"),
            Principal(
                principal_id="owner-safe",
                subject="password=TOP_SECRET_VALUE",
                principal_type=PrincipalType.human,
                display_name="Owner Safe",
            ),
        )
    store.close()


def test_tenant_roots_are_confined_and_separate():
    alpha = tenant_data_dir("tenant-alpha")
    beta = tenant_data_dir("tenant-beta")
    assert alpha != beta
    assert alpha.name == "tenant-alpha"
    assert beta.name == "tenant-beta"
    with pytest.raises(ValueError):
        tenant_data_dir("../escape")


class _FailingWriter:
    def append(self, _event):
        raise RuntimeError("password=AUDIT_WRITER_SECRET")


def test_identity_audit_is_durable_recoverable_and_secret_free(tmp_path):
    store, tenant, owner, _codec, _token = _bootstrap(tmp_path, writer=_FailingWriter())
    assert store.get_tenant(tenant.tenant_id) == tenant
    assert store.get_principal(owner.principal_id) == owner
    assert store.pending_audit_count() == 1
    raw = b"".join(
        path.read_bytes()
        for path in store.db_path.parent.glob("store.sqlite*")
        if path.is_file()
    )
    assert b"AUDIT_WRITER_SECRET" not in raw

    ledger_path = tmp_path / "recovered-ledger.jsonl"
    assert store.flush_outbox(LedgerWriter(ledger_path)) == 1
    assert store.pending_audit_count() == 0
    events = LedgerReader(v2_path=ledger_path).read_all()
    assert len(events) == 1
    assert events[0].outcome == "tenant_bootstrapped"
    assert events[0].metadata["tenant_id"] == tenant.tenant_id
    store.close()


def test_api_requires_authentication_and_fails_closed_without_key(monkeypatch, tmp_path):
    _configure_api(monkeypatch, tmp_path)
    client = TestClient(build_staging_app())
    response = client.get("/api/platform/me")
    assert response.status_code == 401
    assert response.json()["error_code"] == "authentication_required"

    monkeypatch.delenv("ARIA_PRIVATE_AUTH_SECRET")
    response = client.get("/api/platform/me", headers=_auth("not-a-token"))
    assert response.status_code == 503
    assert response.json()["error_code"] == "authentication_unavailable"


def test_api_me_member_management_and_immediate_revocation(monkeypatch, tmp_path):
    _configure_api(monkeypatch, tmp_path)
    store, tenant, owner, codec, owner_token = _bootstrap(tmp_path)
    store.close()
    client = TestClient(build_staging_app())

    me = client.get("/api/platform/me", headers=_auth(owner_token))
    assert me.status_code == 200
    assert me.json()["tenant"]["tenant_id"] == tenant.tenant_id
    assert me.json()["principal"]["principal_id"] == owner.principal_id
    assert "member.manage" in me.json()["permissions"]
    assert "token_id" not in me.text

    body = {
        "principal_id": "member-alpha",
        "subject": "subject-member-alpha",
        "display_name": "Member Alpha",
        "principal_type": "human",
        "role": "member",
    }
    added = client.post(
        f"/api/platform/tenants/{tenant.tenant_id}/members",
        json=body,
        headers=_auth(owner_token),
    )
    assert added.status_code == 201
    member_token = codec.issue(
        subject=body["subject"],
        principal_id=body["principal_id"],
        tenant_id=tenant.tenant_id,
    )
    assert client.get("/api/platform/me", headers=_auth(member_token)).status_code == 200

    revoked = client.delete(
        f"/api/platform/tenants/{tenant.tenant_id}/members/{body['principal_id']}",
        headers=_auth(owner_token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert client.get("/api/platform/me", headers=_auth(member_token)).status_code == 401


def test_api_blocks_cross_tenant_and_member_administration(monkeypatch, tmp_path):
    _configure_api(monkeypatch, tmp_path)
    store, alpha, _owner, codec, owner_token = _bootstrap(tmp_path)
    beta = Tenant(tenant_id="tenant-beta", display_name="Tenant Beta")
    beta_owner = _principal("owner-beta")
    store.bootstrap_tenant(beta, beta_owner)
    owner_context = IdentityService(store, codec).authenticate(owner_token)
    member = _principal("member-alpha")
    IdentityService(store, codec).register_principal(
        owner_context, alpha.tenant_id, member, TenantRole.member
    )
    member_token = codec.issue(
        subject=member.subject,
        principal_id=member.principal_id,
        tenant_id=alpha.tenant_id,
    )
    store.close()
    client = TestClient(build_staging_app())

    cross = client.get(
        f"/api/platform/tenants/{beta.tenant_id}/members",
        headers=_auth(owner_token),
    )
    assert cross.status_code == 403
    denied = client.post(
        f"/api/platform/tenants/{alpha.tenant_id}/members",
        json={
            "principal_id": "other-member",
            "subject": "subject-other-member",
            "display_name": "Other Member",
            "role": "member",
        },
        headers=_auth(member_token),
    )
    assert denied.status_code == 403


def test_platform_surface_has_no_bootstrap_token_or_live_execution_endpoint():
    paths = {route.path for route in build_staging_app().routes}
    platform_paths = {path for path in paths if path.startswith("/api/platform")}
    assert "/api/platform/me" in platform_paths
    assert "/api/platform/tenants/{tenant_id}/credentials/jira" in platform_paths
    assert "/api/platform/tenants/{tenant_id}/connectors/jira/issues" in platform_paths
    assert not any(
        forbidden in path
        for path in platform_paths
        for forbidden in ("bootstrap", "token", "login", "execute-live", "secret")
    )
    assert not any(
        forbidden in path
        for path in platform_paths
        if "/connectors/jira" in path
        for forbidden in ("comment", "transition", "send", "write")
    )


def test_identity_runtime_bytes_do_not_contain_token_or_secret(monkeypatch, tmp_path):
    _configure_api(monkeypatch, tmp_path)
    store, _tenant, _owner, _codec, token = _bootstrap(tmp_path)
    db_dir = store.db_path.parent
    store.close()
    client = TestClient(build_staging_app())
    assert client.get("/api/platform/me", headers=_auth(token)).status_code == 200
    raw = b"".join(path.read_bytes() for path in db_dir.glob("*") if path.is_file())
    assert token.encode() not in raw
    assert _KEY.encode() not in raw
    assert b"password=" not in raw.lower()


def test_operator_cli_bootstraps_without_persisting_token_or_key(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    monkeypatch.setenv("ARIA_PRIVATE_AUTH_SECRET", _KEY)
    assert (
        identity_cli(
            [
                "bootstrap",
                "--tenant-id",
                "tenant-cli",
                "--tenant-name",
                "CLI Tenant",
                "--principal-id",
                "owner-cli",
                "--subject",
                "subject-owner-cli",
                "--principal-name",
                "CLI Owner",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["token"].startswith("aria1.")
    store = IdentityStore()
    raw = b"".join(
        path.read_bytes()
        for path in store.db_path.parent.glob("store.sqlite*")
        if path.is_file()
    )
    assert output["token"].encode() not in raw
    assert _KEY.encode() not in raw
    store.close()


def test_operator_cli_redacts_failures(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    monkeypatch.setenv("ARIA_PRIVATE_AUTH_SECRET", "password=CLI_SECRET")
    assert (
        identity_cli(
            [
                "bootstrap",
                "--tenant-id",
                "tenant-cli",
                "--tenant-name",
                "CLI Tenant",
                "--principal-id",
                "owner-cli",
                "--subject",
                "subject-owner-cli",
                "--principal-name",
                "CLI Owner",
            ]
        )
        == 2
    )
    error = capsys.readouterr().err
    assert "CLI_SECRET" not in error
    assert "details redacted" in error
