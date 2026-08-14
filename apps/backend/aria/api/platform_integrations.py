"""Authenticated tenant credential administration and read-only Jira API."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

from aria.api.platform import AuthenticatedRequest, authenticated_request
from aria.connectors import (
    JiraConfigurationError,
    JiraConnectorError,
    TenantJiraReadService,
    build_jira_connector,
)
from aria.connectors.mode import ConnectorMode, resolve_connector_mode
from aria.credentials import (
    CredentialCipher,
    CredentialConfigurationError,
    CredentialInactive,
    CredentialNotFound,
    CredentialProvider,
    CredentialSecurityError,
    CredentialVaultStore,
)
from aria.identity import AuthorizationDenied, Permission
from aria.tenancy import TenantRuntime

_log = logging.getLogger("aria.api.platform_integrations")


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error_code": code, "detail": detail})


def _authorize(auth: AuthenticatedRequest, tenant_id: str, permission: Permission) -> bool:
    try:
        auth.service.require(auth.context, permission, tenant_id=tenant_id)
        return True
    except AuthorizationDenied:
        return False


def _dump(model) -> dict:
    return json.loads(model.model_dump_json())


class JiraCredentialBody(BaseModel):
    credential_id: str = Field(min_length=3, max_length=64)
    label: str = Field(min_length=1, max_length=160)
    username: str = Field(min_length=1, max_length=320)
    endpoint_url: str = Field(min_length=1, max_length=2048)
    secret: SecretStr


class RotateCredentialBody(BaseModel):
    secret: SecretStr


router = APIRouter(prefix="/api/platform/tenants/{tenant_id}", tags=["platform-integrations"])


@router.post("/credentials/jira")
def create_jira_credential(
    tenant_id: str,
    body: JiraCredentialBody,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.tenant_manage):
        return _error(403, "authorization_denied", "Credential management is not allowed.")
    try:
        cipher = CredentialCipher.from_environment()
        with TenantRuntime(tenant_id) as runtime:
            vault = runtime.credential_vault(cipher)
            try:
                metadata = vault.put_secret(
                    credential_id=body.credential_id,
                    provider=CredentialProvider.jira,
                    label=body.label,
                    username=body.username,
                    endpoint_url=body.endpoint_url,
                    secret=body.secret.get_secret_value(),
                    actor=auth.context.actor,
                )
            finally:
                vault.close()
        return JSONResponse(status_code=201, content=_dump(metadata))
    except CredentialConfigurationError:
        return _error(503, "credential_vault_unavailable", "Credential encryption is not configured.")
    except CredentialInactive:
        return _error(409, "credential_revoked", "A revoked credential cannot be rotated.")
    except (CredentialSecurityError, ValueError):
        return _error(400, "invalid_credential", "Credential metadata violates security policy.")
    except Exception as exc:
        _log.error("credential creation failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Credential storage failed safely.")


@router.get("/credentials")
def list_credentials(
    tenant_id: str,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.tenant_manage):
        return _error(403, "authorization_denied", "Credential management is not allowed.")
    try:
        cipher = CredentialCipher.from_environment()
        with TenantRuntime(tenant_id) as runtime:
            vault = runtime.credential_vault(cipher)
            try:
                records = vault.list_metadata()
            finally:
                vault.close()
        return {"credentials": [_dump(item) for item in records], "count": len(records)}
    except CredentialConfigurationError:
        return _error(503, "credential_vault_unavailable", "Credential encryption is not configured.")
    except Exception as exc:
        _log.error("credential listing failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Credentials could not be listed.")


@router.post("/credentials/{credential_id}/rotate")
def rotate_credential(
    tenant_id: str,
    credential_id: str,
    body: RotateCredentialBody,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.tenant_manage):
        return _error(403, "authorization_denied", "Credential management is not allowed.")
    try:
        cipher = CredentialCipher.from_environment()
        with TenantRuntime(tenant_id) as runtime:
            vault = runtime.credential_vault(cipher)
            try:
                current = vault.get_metadata(credential_id)
                if current is None:
                    raise CredentialNotFound(credential_id)
                metadata = vault.put_secret(
                    credential_id=credential_id,
                    provider=current.provider,
                    label=current.label,
                    username=current.username,
                    endpoint_url=current.endpoint_url,
                    secret=body.secret.get_secret_value(),
                    actor=auth.context.actor,
                )
            finally:
                vault.close()
        return _dump(metadata)
    except CredentialConfigurationError:
        return _error(503, "credential_vault_unavailable", "Credential encryption is not configured.")
    except CredentialNotFound:
        return _error(404, "credential_not_found", "Credential metadata was not found.")
    except CredentialInactive:
        return _error(409, "credential_revoked", "A revoked credential cannot be rotated.")
    except (CredentialSecurityError, ValueError):
        return _error(400, "invalid_credential", "Credential material violates security policy.")
    except Exception as exc:
        _log.error("credential rotation failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Credential rotation failed safely.")


@router.delete("/credentials/{credential_id}")
def revoke_credential(
    tenant_id: str,
    credential_id: str,
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.tenant_manage):
        return _error(403, "authorization_denied", "Credential management is not allowed.")
    try:
        cipher = CredentialCipher.from_environment()
        with TenantRuntime(tenant_id) as runtime:
            vault = runtime.credential_vault(cipher)
            try:
                metadata = vault.revoke(credential_id, actor=auth.context.actor)
            finally:
                vault.close()
        return _dump(metadata)
    except CredentialConfigurationError:
        return _error(503, "credential_vault_unavailable", "Credential encryption is not configured.")
    except CredentialNotFound:
        return _error(404, "credential_not_found", "Credential metadata was not found.")
    except ValueError:
        return _error(400, "invalid_credential", "Credential identifier is invalid.")
    except Exception as exc:
        _log.error("credential revocation failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Credential revocation failed safely.")


def _jira_service(
    runtime: TenantRuntime,
    *,
    credential_id: str | None,
    actor: str,
) -> tuple[TenantJiraReadService, CredentialVaultStore | None]:
    if resolve_connector_mode() is ConnectorMode.fixtures:
        return TenantJiraReadService(runtime, build_jira_connector(actor=actor), actor=actor), None
    cipher = CredentialCipher.from_environment()
    vault = runtime.credential_vault(cipher)
    try:
        connector = build_jira_connector(
            vault=vault, credential_id=credential_id, actor=actor
        )
    except Exception:
        vault.close()
        raise
    return TenantJiraReadService(runtime, connector, actor=actor), vault


@router.get("/connectors/jira/issues")
def list_assigned_jira_issues(
    tenant_id: str,
    credential_id: str | None = Query(default=None),
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.work_read):
        return _error(403, "authorization_denied", "Jira reading is not allowed.")
    vault = None
    try:
        with TenantRuntime(tenant_id) as runtime:
            service, vault = _jira_service(
                runtime, credential_id=credential_id, actor=auth.context.actor
            )
            issues = service.list_assigned()
        return {
            "issues": [_dump(item) for item in issues],
            "count": len(issues),
            "connector_mode": resolve_connector_mode().value,
        }
    except CredentialConfigurationError:
        return _error(503, "credential_vault_unavailable", "Credential encryption is not configured.")
    except CredentialNotFound:
        return _error(404, "credential_not_found", "Credential metadata was not found.")
    except CredentialInactive:
        return _error(409, "credential_inactive", "The selected credential is not active.")
    except (JiraConfigurationError, ValueError):
        return _error(409, "jira_not_configured", "Jira read-only access is not configured.")
    except JiraConnectorError:
        return _error(502, "jira_read_failed", "Jira returned an unusable response.")
    except Exception as exc:
        _log.error("Jira listing failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Jira reading failed safely.")
    finally:
        if vault is not None:
            vault.close()


@router.get("/connectors/jira/issues/{issue_key}")
def read_jira_issue(
    tenant_id: str,
    issue_key: str,
    credential_id: str | None = Query(default=None),
    auth: AuthenticatedRequest = Depends(authenticated_request),
):
    if not _authorize(auth, tenant_id, Permission.work_read):
        return _error(403, "authorization_denied", "Jira reading is not allowed.")
    vault = None
    try:
        with TenantRuntime(tenant_id) as runtime:
            service, vault = _jira_service(
                runtime, credential_id=credential_id, actor=auth.context.actor
            )
            issue = service.read_issue(issue_key)
        return {"issue": _dump(issue), "connector_mode": resolve_connector_mode().value}
    except CredentialConfigurationError:
        return _error(503, "credential_vault_unavailable", "Credential encryption is not configured.")
    except CredentialNotFound:
        return _error(404, "credential_not_found", "Credential metadata was not found.")
    except CredentialInactive:
        return _error(409, "credential_inactive", "The selected credential is not active.")
    except ValueError:
        return _error(400, "invalid_issue_key", "The Jira issue key is invalid.")
    except JiraConfigurationError:
        return _error(409, "jira_not_configured", "Jira read-only access is not configured.")
    except JiraConnectorError:
        return _error(404, "jira_issue_unavailable", "The Jira issue is unavailable.")
    except Exception as exc:
        _log.error("Jira issue read failed (class only): %s", type(exc).__name__)
        return _error(500, "internal_error", "Jira reading failed safely.")
    finally:
        if vault is not None:
            vault.close()


__all__ = ["router"]
