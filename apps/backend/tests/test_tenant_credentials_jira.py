"""Security and behavior tests for tenant credential custody and Jira reads."""
from __future__ import annotations

import base64
import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aria.api.staging import build_staging_app
from aria.connectors import (
    FixtureJiraConnector,
    JiraConfigurationError,
    LiveReadOnlyJiraConnector,
    TenantJiraReadService,
    build_jira_connector,
)
from aria.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    CredentialInactive,
    CredentialProvider,
    CredentialSecurityError,
    CredentialVaultStore,
)
from aria.identity import (
    HmacTokenCodec,
    IdentityService,
    IdentityStore,
    Principal,
    PrincipalType,
    Tenant,
    TenantRole,
)
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.tenancy import TenantRuntime

_AUTH_KEY = "jira-platform-test-auth-key-000000000000000000000000"
_SECRET = "jira-token-TOP_SECRET_123456789"


class _FailingWriter:
    def append(self, _event):
        raise RuntimeError("password=WRITER_SECRET_MUST_NOT_PERSIST")


def _master_key(byte: int = 7) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii")


def _cipher(byte: int = 7) -> CredentialCipher:
    return CredentialCipher(bytes([byte]) * 32)


def _principal(principal_id: str) -> Principal:
    return Principal(
        principal_id=principal_id,
        subject=f"subject-{principal_id}",
        principal_type=PrincipalType.human,
        display_name=principal_id.replace("-", " ").title(),
    )


def _token(codec: HmacTokenCodec, principal: Principal, tenant: Tenant) -> str:
    return codec.issue(
        subject=principal.subject,
        principal_id=principal.principal_id,
        tenant_id=tenant.tenant_id,
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(monkeypatch, tmp_path: Path):
    root = tmp_path / "aria-data"
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "offline_mock")
    monkeypatch.setenv("ARIA_PRIVATE_AUTH_SECRET", _AUTH_KEY)
    monkeypatch.setenv("ARIA_CREDENTIAL_MASTER_KEY", _master_key())
    monkeypatch.setenv("CONNECTOR_MODE", "fixtures")
    store = IdentityStore(writer=LedgerWriter(root / "identity-ledger.jsonl"))
    tenant = Tenant(tenant_id="tenant-alpha", display_name="Tenant Alpha")
    owner = _principal("owner-alpha")
    store.bootstrap_tenant(tenant, owner)
    codec = HmacTokenCodec(_AUTH_KEY)
    return root, store, tenant, owner, codec, _token(codec, owner, tenant)


def _put_jira(runtime: TenantRuntime, *, secret: str = _SECRET, cipher=None):
    vault = runtime.credential_vault(cipher or _cipher())
    metadata = vault.put_secret(
        credential_id="jira-main",
        provider=CredentialProvider.jira,
        label="Primary Jira",
        username="employee@example.com",
        endpoint_url="https://example.atlassian.net",
        secret=secret,
        actor="human:owner-alpha",
    )
    return vault, metadata


def _public_resolver(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def test_vault_encrypts_secret_and_returns_metadata_only(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    with TenantRuntime("tenant-alpha") as runtime:
        vault, metadata = _put_jira(runtime)
        assert metadata.credential_id == "jira-main"
        assert metadata.version == 1
        assert _SECRET not in metadata.model_dump_json()
        resolved = vault.resolve_secret("jira-main", actor="human:owner-alpha")
        assert resolved.secret == _SECRET
        assert _SECRET not in repr(resolved)
        db_path = vault.db_path
        vault.close()
    for path in db_path.parent.glob("store.sqlite*"):
        assert _SECRET.encode() not in path.read_bytes()
    assert _SECRET.encode() not in runtime.ledger_path.read_bytes()


def test_wrong_master_key_cannot_decrypt(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    with TenantRuntime("tenant-alpha") as runtime:
        vault, _metadata = _put_jira(runtime)
        vault.close()
        wrong = runtime.credential_vault(_cipher(8))
        with pytest.raises(CredentialDecryptionError):
            wrong.resolve_secret("jira-main", actor="human:owner-alpha")
        wrong.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.atlassian.net",
        "https://user:password@example.atlassian.net",
        "https://example.atlassian.net/jira",
        "https://example.atlassian.net:8443",
    ],
)
def test_store_rejects_non_origin_or_credential_bearing_endpoint(
    monkeypatch, tmp_path, endpoint
):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    with TenantRuntime("tenant-alpha") as runtime:
        vault = runtime.credential_vault(_cipher())
        with pytest.raises(CredentialSecurityError):
            vault.put_secret(
                credential_id="jira-main",
                provider=CredentialProvider.jira,
                label="Primary Jira",
                username="employee@example.com",
                endpoint_url=endpoint,
                secret=_SECRET,
                actor="human:owner-alpha",
            )
        assert vault.list_metadata() == []
        vault.close()


def test_credential_audit_outbox_survives_writer_failure_without_error_text(
    monkeypatch, tmp_path
):
    root = tmp_path / "aria-data"
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    db_path = root / "tenants" / "tenant-alpha" / "credentials" / "store.sqlite"
    vault = CredentialVaultStore(
        db_path,
        tenant_id="tenant-alpha",
        cipher=_cipher(),
        writer=_FailingWriter(),
    )
    metadata = vault.put_secret(
        credential_id="jira-main",
        provider=CredentialProvider.jira,
        label="Primary Jira",
        username="employee@example.com",
        endpoint_url="https://example.atlassian.net",
        secret=_SECRET,
        actor="human:owner-alpha",
    )
    assert metadata.status.value == "active"
    assert vault.pending_audit_count() == 1
    recovery = LedgerWriter(root / "recovery-ledger.jsonl")
    assert vault.flush_outbox(recovery) == 1
    assert vault.pending_audit_count() == 0
    vault.close()
    combined = db_path.read_bytes() + recovery.path.read_bytes()
    assert _SECRET.encode() not in combined
    assert b"WRITER_SECRET_MUST_NOT_PERSIST" not in combined


def test_rotation_replaces_secret_and_revocation_destroys_access(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    with TenantRuntime("tenant-alpha") as runtime:
        vault, first = _put_jira(runtime)
        second = vault.put_secret(
            credential_id="jira-main",
            provider=CredentialProvider.jira,
            label=first.label,
            username=first.username,
            endpoint_url=first.endpoint_url,
            secret="jira-token-ROTATED_987654321",
            actor="human:owner-alpha",
        )
        assert second.version == 2
        assert vault.resolve_secret("jira-main", actor="human:owner-alpha").secret.endswith(
            "987654321"
        )
        revoked = vault.revoke("jira-main", actor="human:owner-alpha")
        assert revoked.status.value == "revoked"
        with pytest.raises(CredentialInactive):
            vault.resolve_secret("jira-main", actor="human:owner-alpha")
        with pytest.raises(CredentialInactive):
            vault.put_secret(
                credential_id="jira-main",
                provider=CredentialProvider.jira,
                label=first.label,
                username=first.username,
                endpoint_url=first.endpoint_url,
                secret="cannot-reactivate",
                actor="human:owner-alpha",
            )
        vault.close()


def test_identical_credential_ids_are_isolated_by_tenant(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    with TenantRuntime("tenant-alpha") as alpha, TenantRuntime("tenant-beta") as beta:
        alpha_vault, _ = _put_jira(alpha, secret="alpha-only")
        beta_vault, _ = _put_jira(beta, secret="beta-only")
        assert alpha_vault.resolve_secret("jira-main", actor="human:a").secret == "alpha-only"
        assert beta_vault.resolve_secret("jira-main", actor="human:b").secret == "beta-only"
        assert alpha_vault.db_path != beta_vault.db_path
        alpha_vault.close()
        beta_vault.close()


def test_fixture_jira_requires_no_key_credentials_or_network(monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "fixtures")
    monkeypatch.delenv("ARIA_CREDENTIAL_MASTER_KEY", raising=False)
    monkeypatch.setenv("JIRA_API_TOKEN", "ambient-secret-must-not-activate")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("network used"))
    connector = build_jira_connector()
    assert isinstance(connector, FixtureJiraConnector)
    assert len(connector.list_assigned()) == 2
    assert connector.read_issue("ARIA-101").status == "In Progress"


def test_live_jira_is_explicit_allowlisted_get_only(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    monkeypatch.setenv("CONNECTOR_MODE", "read_only_live")
    monkeypatch.setenv("CONNECTOR_PROVIDER_ALLOWLIST", "jira")
    calls = []

    def transport(url, headers):
        calls.append((url, headers))
        return {
            "issues": [
                {
                    "key": "ARIA-201",
                    "fields": {
                        "summary": "Investigate password=SHOULD_BE_REDACTED",
                        "status": {"name": "Open"},
                        "assignee": {"displayName": "Kunal"},
                        "project": {"key": "ARIA"},
                        "issuetype": {"name": "Task"},
                        "priority": {"name": "High"},
                        "updated": "2026-08-04T07:00:00Z",
                    },
                }
            ]
        }

    with TenantRuntime("tenant-alpha") as runtime:
        vault, _ = _put_jira(runtime)
        connector = build_jira_connector(
            vault=vault,
            credential_id="jira-main",
            actor="human:owner-alpha",
            transport=transport,
            resolver=_public_resolver,
            host_allowlist=frozenset({"example.atlassian.net"}),
        )
        issues = connector.list_assigned()
        vault.close()
    assert len(calls) == 1
    assert calls[0][0].startswith(
        "https://example.atlassian.net/rest/api/3/search/jql?"
    )
    assert "currentUser" in calls[0][0]
    assert calls[0][1]["Authorization"].startswith("Basic ")
    assert _SECRET not in json.dumps(calls)
    assert "SHOULD_BE_REDACTED" not in issues[0].model_dump_json()


def test_live_jira_rejects_unallowlisted_and_private_targets(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    monkeypatch.setenv("CONNECTOR_MODE", "read_only_live")
    monkeypatch.setenv("CONNECTOR_PROVIDER_ALLOWLIST", "jira")
    with TenantRuntime("tenant-alpha") as runtime:
        vault, _ = _put_jira(runtime)
        resolved = vault.resolve_secret("jira-main", actor="human:owner-alpha")
        with pytest.raises(JiraConfigurationError, match="allowlisted"):
            LiveReadOnlyJiraConnector(resolved, host_allowlist=frozenset())
        connector = LiveReadOnlyJiraConnector(
            resolved,
            host_allowlist=frozenset({"example.atlassian.net"}),
            resolver=lambda *_a, **_k: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
            ],
            transport=lambda *_a: pytest.fail("transport should not run"),
        )
        with pytest.raises(JiraConfigurationError, match="non-public"):
            connector.list_assigned()
        vault.close()


def test_tenant_jira_service_records_durable_tenant_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    monkeypatch.setenv("CONNECTOR_MODE", "fixtures")
    with TenantRuntime("tenant-alpha") as runtime:
        service = TenantJiraReadService(
            runtime, FixtureJiraConnector(), actor="human:owner-alpha"
        )
        assert service.list_assigned()
        events = LedgerReader(v2_path=runtime.ledger_path).v2_events()
    matching = [event for event in events if event.event_type.value == "read_only_connector_invoked"]
    assert [event.outcome for event in matching] == ["requested", "completed"]
    assert all(event.metadata["connector"] == "jira:fixtures" for event in matching)


def test_tenant_jira_service_records_failed_read_without_error_text(monkeypatch, tmp_path):
    class FailingFixtureJira(FixtureJiraConnector):
        def list_assigned(self):
            raise RuntimeError("password=JIRA_READ_SECRET")

    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    monkeypatch.setenv("CONNECTOR_MODE", "fixtures")
    with TenantRuntime("tenant-alpha") as runtime:
        service = TenantJiraReadService(
            runtime, FailingFixtureJira(), actor="human:owner-alpha"
        )
        with pytest.raises(RuntimeError, match="JIRA_READ_SECRET"):
            service.list_assigned()
        events = LedgerReader(v2_path=runtime.ledger_path).v2_events()
        raw = runtime.ledger_path.read_text(encoding="utf-8")
    matching = [event for event in events if event.event_type.value == "read_only_connector_invoked"]
    assert [event.outcome for event in matching] == ["requested", "failed"]
    assert "JIRA_READ_SECRET" not in raw


def test_credential_api_never_returns_secret_and_enforces_admin(monkeypatch, tmp_path):
    root, store, tenant, owner, codec, owner_token = _bootstrap(monkeypatch, tmp_path)
    context = IdentityService(store, codec).authenticate(owner_token)
    member = _principal("member-alpha")
    IdentityService(store, codec).register_principal(
        context, tenant.tenant_id, member, TenantRole.member
    )
    member_token = _token(codec, member, tenant)
    store.close()
    client = TestClient(build_staging_app())
    path = f"/api/platform/tenants/{tenant.tenant_id}/credentials/jira"
    body = {
        "credential_id": "jira-main",
        "label": "Primary Jira",
        "username": "employee@example.com",
        "endpoint_url": "https://example.atlassian.net",
        "secret": _SECRET,
    }
    assert client.post(path, json=body, headers=_auth(member_token)).status_code == 403
    created = client.post(path, json=body, headers=_auth(owner_token))
    assert created.status_code == 201
    assert _SECRET not in created.text
    listed = client.get(
        f"/api/platform/tenants/{tenant.tenant_id}/credentials", headers=_auth(owner_token)
    )
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert _SECRET not in listed.text
    rotated_secret = "jira-token-ROTATED_API_123456"
    rotated = client.post(
        f"/api/platform/tenants/{tenant.tenant_id}/credentials/jira-main/rotate",
        json={"secret": rotated_secret},
        headers=_auth(owner_token),
    )
    assert rotated.status_code == 200
    assert rotated.json()["version"] == 2
    assert rotated_secret not in rotated.text
    revoked = client.delete(
        f"/api/platform/tenants/{tenant.tenant_id}/credentials/jira-main",
        headers=_auth(owner_token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    for db_file in (root / "tenants" / tenant.tenant_id / "credentials").glob("store.sqlite*"):
        raw = db_file.read_bytes()
        assert _SECRET.encode() not in raw
        assert rotated_secret.encode() not in raw


def test_fixture_jira_api_is_authenticated_tenant_scoped_and_has_no_write_route(
    monkeypatch, tmp_path
):
    _root, store, tenant, owner, _codec, token = _bootstrap(monkeypatch, tmp_path)
    store.close()
    client = TestClient(build_staging_app())
    base = f"/api/platform/tenants/{tenant.tenant_id}/connectors/jira/issues"
    assert client.get(base).status_code == 401
    listed = client.get(base, headers=_auth(token))
    assert listed.status_code == 200
    assert listed.json()["connector_mode"] == "fixtures"
    issue = client.get(f"{base}/ARIA-101", headers=_auth(token))
    assert issue.status_code == 200
    assert issue.json()["issue"]["key"] == "ARIA-101"
    assert client.post(base, json={}, headers=_auth(token)).status_code == 405
    paths = {getattr(route, "path", "") for route in build_staging_app().routes}
    assert not any(
        any(word in path.lower() for word in ("comment", "transition", "send", "write"))
        for path in paths
        if "/connectors/jira" in path
    )


def test_live_api_fails_closed_without_key_before_network(monkeypatch, tmp_path):
    _root, store, tenant, _owner, _codec, token = _bootstrap(monkeypatch, tmp_path)
    store.close()
    monkeypatch.setenv("CONNECTOR_MODE", "read_only_live")
    monkeypatch.setenv("CONNECTOR_PROVIDER_ALLOWLIST", "jira")
    monkeypatch.delenv("ARIA_CREDENTIAL_MASTER_KEY")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("network used"))
    response = TestClient(build_staging_app()).get(
        f"/api/platform/tenants/{tenant.tenant_id}/connectors/jira/issues"
        "?credential_id=jira-main",
        headers=_auth(token),
    )
    assert response.status_code == 503
    assert response.json()["error_code"] == "credential_vault_unavailable"
