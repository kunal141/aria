"""Fixture-first Jira reader with an explicit, allowlisted live GET boundary."""
from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import urllib.parse
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from aria.connectors.fixtures.data import JIRA_ISSUES
from aria.connectors.mode import ConnectorMode, ensure_live_allowed, resolve_connector_mode
from aria.credentials import CredentialProvider, CredentialVaultStore, ResolvedCredential
from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType, LedgerEventType

_ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,31}-[1-9][0-9]{0,11}$")
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_log = logging.getLogger("aria.connectors.jira")


class JiraConnectorError(RuntimeError):
    pass


class JiraConfigurationError(JiraConnectorError):
    pass


class JiraResponseError(JiraConnectorError):
    pass


class JiraIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    summary: str
    status: str
    assignee: str | None = None
    project: str
    issue_type: str
    priority: str | None = None
    updated: str | None = None
    source_refs: list[str]


class JiraReader(Protocol):
    mode: ConnectorMode

    def list_assigned(self) -> list[JiraIssue]: ...

    def read_issue(self, issue_key: str) -> JiraIssue: ...


def _safe(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    return value


def _issue(data: dict[str, Any], *, host: str) -> JiraIssue:
    fields = data.get("fields", data)
    key = str(data.get("key") or fields.get("key") or "")
    if not _ISSUE_KEY.fullmatch(key):
        raise JiraResponseError("Jira returned an invalid issue key")

    def nested(name: str, child: str = "name") -> str | None:
        value = fields.get(name)
        if isinstance(value, dict):
            raw = value.get(child)
        else:
            raw = value
        return sanitize_text(str(raw)) if raw is not None else None

    summary = sanitize_text(str(fields.get("summary") or "")) or ""
    status = nested("status") or "Unknown"
    project = nested("project", "key") or key.split("-", 1)[0]
    issue_type = nested("issuetype") or str(fields.get("issue_type") or "Unknown")
    assignee = nested("assignee", "displayName") or fields.get("assignee")
    priority = nested("priority") or fields.get("priority")
    updated = fields.get("updated")
    return JiraIssue(
        key=key,
        summary=summary,
        status=status,
        assignee=sanitize_text(str(assignee)) if assignee else None,
        project=sanitize_text(str(project)) or key.split("-", 1)[0],
        issue_type=sanitize_text(str(issue_type)) or "Unknown",
        priority=sanitize_text(str(priority)) if priority else None,
        updated=sanitize_text(str(updated)) if updated else None,
        source_refs=[f"connector:jira:{host}:issue:{key}"],
    )


class FixtureJiraConnector:
    mode = ConnectorMode.fixtures
    provider = "jira"

    def list_assigned(self) -> list[JiraIssue]:
        return [_issue(item, host="fixtures") for item in JIRA_ISSUES.values()]

    def read_issue(self, issue_key: str) -> JiraIssue:
        key = issue_key.strip().upper()
        if not _ISSUE_KEY.fullmatch(key):
            raise ValueError("invalid Jira issue key")
        data = JIRA_ISSUES.get(key)
        if data is None:
            raise JiraResponseError("Jira issue was not found")
        return _issue(data, host="fixtures")


def _decode_response(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JiraResponseError("Jira returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise JiraResponseError("Jira returned a non-object response")
    return _safe(payload)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS-validating connection whose TCP target is the policy-checked IP."""

    def __init__(self, host: str, ip: str) -> None:
        self._aria_context = ssl.create_default_context()
        super().__init__(host, port=443, timeout=15, context=self._aria_context)
        self._pinned_ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, 443), self.timeout)
        try:
            self.sock = self._aria_context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def _pinned_get_json(url: str, headers: dict[str, str], *, host: str, ip: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != host:
        raise JiraConfigurationError("Jira request escaped its configured HTTPS host")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    connection = _PinnedHTTPSConnection(host, ip)
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            raise JiraResponseError(f"Jira returned HTTP {response.status}")
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise JiraResponseError("Jira response exceeds the allowed size")
        return _decode_response(raw)
    except JiraResponseError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise JiraResponseError(f"Jira read failed ({type(exc).__name__})") from exc
    finally:
        connection.close()


class LiveReadOnlyJiraConnector:
    mode = ConnectorMode.read_only_live
    provider = "jira"

    def __init__(
        self,
        credential: ResolvedCredential,
        *,
        transport: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
        resolver: Callable[..., list] | None = None,
        host_allowlist: frozenset[str] | None = None,
    ) -> None:
        if credential.metadata.provider is not CredentialProvider.jira:
            raise JiraConfigurationError("credential is not a Jira credential")
        ensure_live_allowed("jira")
        parsed = urllib.parse.urlsplit(credential.metadata.endpoint_url)
        self._host = (parsed.hostname or "").lower()
        configured = host_allowlist if host_allowlist is not None else _jira_host_allowlist()
        if self._host not in configured:
            raise JiraConfigurationError("Jira host is not explicitly allowlisted")
        self._endpoint = credential.metadata.endpoint_url.rstrip("/")
        self._credential = credential
        self._transport = transport
        self._resolver = resolver or socket.getaddrinfo

    def _validate_network_target(self) -> list[str]:
        try:
            addresses = self._resolver(self._host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise JiraConfigurationError("Jira host could not be resolved") from exc
        if not addresses:
            raise JiraConfigurationError("Jira host resolved to no addresses")
        validated = []
        for entry in addresses:
            address = str(entry[4][0]).split("%", 1)[0]
            try:
                if not ipaddress.ip_address(address).is_global:
                    raise JiraConfigurationError("Jira host resolves to a non-public address")
                validated.append(address)
            except ValueError as exc:
                raise JiraConfigurationError("Jira host resolved to an invalid address") from exc
        return validated

    def _headers(self) -> dict[str, str]:
        raw = f"{self._credential.metadata.username}:{self._credential.secret}".encode()
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}",
            "User-Agent": "ARIA-ReadOnly-Jira/1.0",
        }

    def _get(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        addresses = self._validate_network_target()
        url = f"{self._endpoint}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        if self._transport is not None:
            return self._transport(url, self._headers())
        return _pinned_get_json(url, self._headers(), host=self._host, ip=addresses[0])

    def list_assigned(self) -> list[JiraIssue]:
        payload = self._get(
            "/rest/api/3/search/jql",
            {
                "jql": "assignee = currentUser() ORDER BY updated DESC",
                "maxResults": "50",
                "fields": "summary,status,assignee,project,issuetype,priority,updated",
            },
        )
        issues = payload.get("issues")
        if not isinstance(issues, list):
            raise JiraResponseError("Jira search response has no issue list")
        return [_issue(item, host=self._host) for item in issues if isinstance(item, dict)]

    def read_issue(self, issue_key: str) -> JiraIssue:
        key = issue_key.strip().upper()
        if not _ISSUE_KEY.fullmatch(key):
            raise ValueError("invalid Jira issue key")
        payload = self._get(
            f"/rest/api/3/issue/{urllib.parse.quote(key)}",
            {"fields": "summary,status,assignee,project,issuetype,priority,updated"},
        )
        return _issue(payload, host=self._host)


def _jira_host_allowlist() -> frozenset[str]:
    raw = os.getenv("JIRA_HOST_ALLOWLIST", "")
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def build_jira_connector(
    *,
    vault: CredentialVaultStore | None = None,
    credential_id: str | None = None,
    actor: str = "aria",
    transport: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
    resolver: Callable[..., list] | None = None,
    host_allowlist: frozenset[str] | None = None,
) -> JiraReader:
    if resolve_connector_mode() is ConnectorMode.fixtures:
        return FixtureJiraConnector()
    ensure_live_allowed("jira")
    if vault is None or not credential_id:
        raise JiraConfigurationError("live Jira requires a tenant credential")
    credential = vault.resolve_secret(credential_id, actor=actor)
    return LiveReadOnlyJiraConnector(
        credential,
        transport=transport,
        resolver=resolver,
        host_allowlist=host_allowlist,
    )


class TenantJiraReadService:
    def __init__(self, runtime, connector: JiraReader, *, actor: str) -> None:
        self._runtime = runtime
        self._connector = connector
        self._actor = actor

    def _audit(self, task_id: str, operation: str, outcome: str) -> None:
        self._runtime.workspaces.emit_event(
            LedgerEventType.read_only_connector_invoked,
            task_id=task_id,
            actor=self._actor,
            actor_type=ActorType.human,
            scope="tenant.jira.read",
            connector=f"jira:{self._connector.mode.value}",
            pilot=operation,
            execution_mode=self._runtime.execution_mode,
            outcome=outcome,
        )

    def list_assigned(self) -> list[JiraIssue]:
        task_id = f"jira-read-{uuid.uuid4().hex}"
        self._audit(task_id, "list_assigned", "requested")
        try:
            issues = self._connector.list_assigned()
        except Exception:
            try:
                self._audit(task_id, "list_assigned", "failed")
            except Exception as audit_exc:
                _log.error(
                    "Jira failure audit could not be queued (class only): %s",
                    type(audit_exc).__name__,
                )
            raise
        self._audit(task_id, "list_assigned", "completed")
        return issues

    def read_issue(self, issue_key: str) -> JiraIssue:
        task_id = f"jira-read-{uuid.uuid4().hex}"
        self._audit(task_id, "read_issue", "requested")
        try:
            issue = self._connector.read_issue(issue_key)
        except Exception:
            try:
                self._audit(task_id, "read_issue", "failed")
            except Exception as audit_exc:
                _log.error(
                    "Jira failure audit could not be queued (class only): %s",
                    type(audit_exc).__name__,
                )
            raise
        self._audit(task_id, "read_issue", "completed")
        return issue


__all__ = [
    "FixtureJiraConnector",
    "JiraConfigurationError",
    "JiraConnectorError",
    "JiraIssue",
    "JiraReader",
    "JiraResponseError",
    "LiveReadOnlyJiraConnector",
    "TenantJiraReadService",
    "build_jira_connector",
]
