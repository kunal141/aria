"""Physical tenant isolation for the authenticated employee workflow."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aria.api.staging import build_staging_app
from aria.employee import EmployeeRunNotFound, default_business_fixture
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
from aria.ledger.writer import LedgerWriter, configure_default_writer, reset_default_writer
from aria.memory_v2.paths import tenant_data_dir
from aria.tenancy import TenantIsolationError, TenantRuntime

_KEY = "tenant-platform-test-key-material-000000000000000000000"


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


def _analysis_body(*, dataset_id: str = "fixture-tenant-api") -> dict:
    return {
        "goal_text": "Investigate the notification CTR decline and report.",
        "dataset_id": dataset_id,
        "metric_name": "notification_ctr",
        "previous": {"label": "previous", "impressions": 1000, "clicks": 50},
        "current": {"label": "current", "impressions": 1000, "clicks": 35},
        "source_refs": [f"fixture://tenant/{dataset_id}"],
        "max_attempts": 2,
        "exercise_repair_loop": False,
    }


def _identity_fixture(monkeypatch, tmp_path: Path):
    root = tmp_path / "aria-data"
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "offline_mock")
    monkeypatch.setenv("ARIA_PRIVATE_AUTH_SECRET", _KEY)
    store = IdentityStore(writer=LedgerWriter(root / "identity-ledger.jsonl"))
    codec = HmacTokenCodec(_KEY)
    alpha = Tenant(tenant_id="tenant-alpha", display_name="Tenant Alpha")
    beta = Tenant(tenant_id="tenant-beta", display_name="Tenant Beta")
    alpha_owner = _principal("owner-alpha")
    beta_owner = _principal("owner-beta")
    store.bootstrap_tenant(alpha, alpha_owner)
    store.bootstrap_tenant(beta, beta_owner)
    return root, store, codec, alpha, beta, alpha_owner, beta_owner


def test_runtime_confines_every_store_ledger_and_artifact(monkeypatch, tmp_path):
    root = tmp_path / "aria-data"
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    with TenantRuntime("tenant-alpha") as runtime:
        tenant_root = runtime.root.resolve()
        for path in (*runtime.store_paths, runtime.ledger_path, runtime.workspaces.artifact_root):
            path.resolve().relative_to(tenant_root)
        workspace = runtime.workspaces.create_workspace(
            session_id="session-alpha",
            task_id="task-alpha",
            owner="human:owner-alpha",
            scope="tenant-isolation-test",
        )
        ref = runtime.workspaces.write_artifact(workspace.workspace_id, "report.md", "alpha")
        artifact = runtime.workspaces.artifact_root / ref
        assert artifact.read_text(encoding="utf-8") == "alpha"
        artifact.resolve().relative_to(tenant_root)
    assert not (root / "workspaces" / workspace.workspace_id / "report.md").exists()


def test_employee_state_and_ledger_are_physically_isolated(monkeypatch, tmp_path):
    root = tmp_path / "aria-data"
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    global_ledger = root / "global-ledger.jsonl"
    configure_default_writer(LedgerWriter(global_ledger))
    try:
        with TenantRuntime("tenant-alpha") as alpha:
            result = alpha.employee_service(actor="human:owner-alpha").run_business_analysis(
                goal_text="Investigate the notification CTR decline.",
                dataset=default_business_fixture(),
                intentional_quality_failures=0,
            )
            run_id = result.run.run_id
            assert alpha.employee_service(actor="human:owner-alpha").list_runs()
            alpha_ledger = alpha.ledger_path
        with TenantRuntime("tenant-beta") as beta:
            assert beta.employee_service(actor="human:owner-beta").list_runs() == []
            with pytest.raises(EmployeeRunNotFound, match="not found"):
                beta.employee_service(actor="human:owner-beta").inspect_run(run_id)
            assert not beta.ledger_path.exists()
        with TenantRuntime("tenant-alpha") as reopened:
            assert reopened.employee_service(actor="human:owner-alpha").inspect_run(run_id).run.run_id == run_id
        assert LedgerReader(v2_path=alpha_ledger).v2_events()
        assert not global_ledger.exists()
    finally:
        reset_default_writer()


def test_invalid_tenant_identifier_creates_no_runtime_data(monkeypatch, tmp_path):
    root = tmp_path / "aria-data"
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    for tenant_id in ("../escape", "password=TOP_SECRET", "Tenant With Spaces"):
        with pytest.raises(ValueError):
            TenantRuntime(tenant_id)
    assert not (root / "tenants").exists()


def test_tenant_root_alias_is_rejected(monkeypatch, tmp_path):
    root = tmp_path / "aria-data"
    tenants = root / "tenants"
    beta = tenants / "tenant-beta"
    beta.mkdir(parents=True)
    alpha = tenants / "tenant-alpha"
    try:
        alpha.symlink_to(beta, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this Windows account")
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    with pytest.raises(TenantIsolationError, match="aliased"):
        TenantRuntime("tenant-alpha")


def test_workspace_authority_rejects_traversal_reference(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path / "aria-data"))
    with TenantRuntime("tenant-alpha") as runtime:
        workspace = runtime.workspaces.create_workspace(
            owner="human:owner-alpha", scope="tenant-isolation-test"
        )
        with pytest.raises(ValueError, match="confined filename"):
            runtime.workspaces.resolve_artifact_ref(
                workspace.workspace_id, f"{workspace.workspace_id}/../tenant-beta/report.md"
            )


def test_authenticated_employee_api_enforces_tenant_scope_and_permissions(
    monkeypatch, tmp_path
):
    root, store, codec, alpha, beta, alpha_owner, beta_owner = _identity_fixture(
        monkeypatch, tmp_path
    )
    alpha_token = _token(codec, alpha_owner, alpha)
    beta_token = _token(codec, beta_owner, beta)
    member = _principal("member-alpha")
    owner_context = IdentityService(store, codec).authenticate(alpha_token)
    IdentityService(store, codec).register_principal(
        owner_context, alpha.tenant_id, member, TenantRole.member
    )
    member_token = _token(codec, member, alpha)
    store.close()
    client = TestClient(build_staging_app())
    base = f"/api/platform/tenants/{alpha.tenant_id}/employee-runs"

    created = client.post(
        f"{base}/business-analysis", json=_analysis_body(), headers=_auth(member_token)
    )
    assert created.status_code == 201
    run_id = created.json()["run"]["run_id"]
    employee_id = created.json()["run"]["employee_id"]
    assert client.get(base, headers=_auth(member_token)).json()["count"] == 1
    assert client.get(f"{base}/{run_id}", headers=_auth(member_token)).status_code == 200
    proof = client.get(f"{base}/{run_id}/proof-packet", headers=_auth(member_token))
    assert proof.status_code == 200
    assert proof.json()["proof_packet"]["commitment_ref"] == run_id
    employees = client.get(f"{base}/employees", headers=_auth(member_token))
    assert employees.status_code == 200
    assert employees.json()["count"] == 1
    assert employees.json()["employees"][0]["employee"]["employee_id"] == employee_id
    employee = client.get(f"{base}/employees/{employee_id}", headers=_auth(member_token))
    assert employee.status_code == 200
    assert employee.json()["employee"]["employee_id"] == employee_id
    assert client.get(f"{base}/{run_id}/ledger", headers=_auth(member_token)).status_code == 403
    assert client.post(
        f"{base}/{run_id}/approve-completion",
        json={"decision": "approve"},
        headers=_auth(member_token),
    ).status_code == 403

    cross = client.get(
        f"/api/platform/tenants/{beta.tenant_id}/employee-runs",
        headers=_auth(alpha_token),
    )
    assert cross.status_code == 403
    beta_view = client.get(
        f"/api/platform/tenants/{beta.tenant_id}/employee-runs/{run_id}",
        headers=_auth(beta_token),
    )
    assert beta_view.status_code == 404
    assert client.get(f"{base}/{run_id}/ledger", headers=_auth(alpha_token)).status_code == 200

    approved = client.post(
        f"{base}/{run_id}/approve-completion",
        json={"decision": "approve"},
        headers=_auth(alpha_token),
    )
    assert approved.status_code == 200
    assert approved.json()["run"]["status"] == "completed"
    record = client.get(f"{base}/employees/{employee_id}", headers=_auth(member_token))
    assert record.json()["employment_record"]["total_runs"] == 1
    assert record.json()["employment_record"]["passed_runs"] == 1
    assert (root / "tenants" / alpha.tenant_id / "employee_runs" / "store.sqlite").exists()
    assert (root / "tenants" / alpha.tenant_id / "employee_registry" / "store.sqlite").exists()
    with TenantRuntime(beta.tenant_id) as beta_runtime:
        assert beta_runtime.employee_service(actor="human:owner-beta").list_runs() == []
        assert beta_runtime.employee_registry.list_employees() == []
        assert not beta_runtime.ledger_path.exists()


def test_revoked_membership_immediately_blocks_employee_api(monkeypatch, tmp_path):
    _root, store, codec, alpha, _beta, alpha_owner, _beta_owner = _identity_fixture(
        monkeypatch, tmp_path
    )
    owner_token = _token(codec, alpha_owner, alpha)
    owner_context = IdentityService(store, codec).authenticate(owner_token)
    member = _principal("member-revoked")
    IdentityService(store, codec).register_principal(
        owner_context, alpha.tenant_id, member, TenantRole.member
    )
    member_token = _token(codec, member, alpha)
    store.close()
    client = TestClient(build_staging_app())
    path = f"/api/platform/tenants/{alpha.tenant_id}/employee-runs"
    assert client.get(path, headers=_auth(member_token)).status_code == 200
    revoked = client.delete(
        f"/api/platform/tenants/{alpha.tenant_id}/members/{member.principal_id}",
        headers=_auth(owner_token),
    )
    assert revoked.status_code == 200
    assert client.get(path, headers=_auth(member_token)).status_code == 401


def test_platform_employee_errors_do_not_echo_secret(monkeypatch, tmp_path, caplog):
    _root, store, codec, alpha, _beta, alpha_owner, _beta_owner = _identity_fixture(
        monkeypatch, tmp_path
    )
    token = _token(codec, alpha_owner, alpha)
    store.close()
    client = TestClient(build_staging_app())
    response = client.post(
        f"/api/platform/tenants/{alpha.tenant_id}/employee-runs/business-analysis",
        json={**_analysis_body(), "source_refs": ["password=TOP_SECRET_TOKEN"]},
        headers=_auth(token),
    )
    assert response.status_code == 400
    combined = response.text + "\n" + "\n".join(record.message for record in caplog.records)
    assert "TOP_SECRET_TOKEN" not in combined
    tenant_root = tenant_data_dir(alpha.tenant_id)
    if tenant_root.exists():
        for path in tenant_root.rglob("*"):
            if path.is_file():
                assert b"TOP_SECRET_TOKEN" not in path.read_bytes()
