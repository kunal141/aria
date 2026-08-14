"""Focused private-staging health, boundary, and ledger tests."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from aria.api.staging import build_staging_app
from aria.ledger.writer import reset_default_writer


def _configure(monkeypatch, tmp_path):
    root = tmp_path / "aria-data"
    monkeypatch.setenv("ARIA_DATA_DIR", str(root))
    monkeypatch.setenv("ARIA_LEDGER_V2_PATH", str(root / "work_ledger_v2.jsonl"))
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "offline_mock")
    monkeypatch.setenv("ARIA_CONNECTOR_MODE", "fixtures")
    monkeypatch.setenv("CONNECTOR_MODE", "fixtures")
    monkeypatch.setenv("ARIA_LIVE_EXECUTION", "false")
    reset_default_writer()
    return root


def test_health_is_import_safe_and_ready_is_schema_aware(monkeypatch, tmp_path):
    root = _configure(monkeypatch, tmp_path)
    assert not root.exists()
    client = TestClient(build_staging_app())
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ready", "execution_mode": "offline_mock",
        "live_execution": False, "connector_mode": "fixtures",
    }
    assert not root.exists()
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["persistence_writable"] is True
    assert ready.json()["stores_ready"] is True
    assert root.exists()
    assert str(tmp_path) not in ready.text


def test_readiness_fails_closed_without_leaking_environment(monkeypatch, tmp_path):
    root = _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "cloud_opt_in")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-secret-value")
    response = TestClient(build_staging_app()).get("/ready")
    assert response.status_code == 503
    assert response.json()["execution_mode"] == "blocked"
    assert response.json()["live_execution"] is False
    assert "test-only-secret-value" not in response.text
    assert str(root) not in response.text


def test_health_fails_closed_for_live_connector_mode(monkeypatch, tmp_path):
    root = _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("CONNECTOR_MODE", "read_only_live")
    response = TestClient(build_staging_app()).get("/health")
    assert response.status_code == 503
    assert response.json()["connector_mode"] == "blocked"
    assert "read_only_live" not in response.text
    assert str(root) not in response.text


def test_health_accepts_explicit_local_ollama_mode(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "local_ollama")
    response = TestClient(build_staging_app()).get("/health")
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "local_ollama"
    assert response.json()["live_execution"] is False


def test_employee_ledger_endpoint_is_sanitized_and_correlated(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(build_staging_app())
    body = {
        "goal_text": "Investigate notification CTR and report.",
        "dataset_id": "fixture-staging-test", "metric_name": "notification_ctr",
        "previous": {"label": "previous", "impressions": 1000, "clicks": 50},
        "current": {"label": "current", "impressions": 1000, "clicks": 35},
        "source_refs": ["fixture://staging/test"], "max_attempts": 2,
        "exercise_repair_loop": True,
    }
    created = client.post("/api/v4/employee-runs/business-analysis", json=body)
    assert created.status_code == 201
    run_id = created.json()["run"]["run_id"]
    approved = client.post(
        f"/api/v4/employee-runs/{run_id}/approve-completion", json={"decision": "approve"})
    assert approved.status_code == 200
    ledger = client.get(f"/api/v4/employee-runs/{run_id}/ledger")
    assert ledger.status_code == 200
    payload = ledger.json()
    assert payload["count"] > 0
    assert {event["correlation_id"] for event in payload["events"]} <= {
        run_id, payload["goal_id"]}
    assert "metadata" not in json.dumps(payload)
    assert client.get("/api/v4/employee-runs/unknown/ledger").status_code == 404


def test_compose_package_defaults_offline_and_excludes_provider_sdks():
    root = Path(__file__).parents[3]
    compose = (root / "compose.private.yml").read_text(encoding="utf-8")
    backend = (root / "Dockerfile.backend").read_text(encoding="utf-8")
    requirements = (root / "deployment/private-staging/backend-requirements.lock").read_text(
        encoding="utf-8")
    combined = compose + backend + requirements
    assert "127.0.0.1:8000:8000" in compose
    assert "127.0.0.1:8080:8080" in compose
    assert "internal: true" in compose
    assert "read_only: true" in compose
    assert "ARIA_EXECUTION_MODE: offline_mock" in compose
    assert "CONNECTOR_MODE: ${CONNECTOR_MODE:-fixtures}" in compose
    assert 'ARIA_LIVE_EXECUTION: "false"' in compose
    assert "python-dotenv==" in requirements
    assert "cryptography==" in requirements
    assert "docker.sock" not in combined
    assert "privileged:" not in combined
    for forbidden in (
        "langchain-anthropic", "anthropic", "openai", "slack", "gmail", "jira",
        "github", "mcp", "crewai", "dspy", "chromadb", "sentence-transformers",
    ):
        assert forbidden not in requirements.lower()


def test_staging_factory_exposes_frontend_api_surfaces_without_live_route(
        monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    paths = {route.path for route in build_staging_app().routes}
    assert "/api/v1/ledger/metrics" in paths
    assert "/api/v2/chat/sessions" in paths
    assert "/api/v4/employee-runs/business-analysis" in paths
    assert "/api/platform/tenants/{tenant_id}/credentials/jira" in paths
    assert "/api/platform/tenants/{tenant_id}/connectors/jira/issues" in paths
    assert "/voice/run" in paths
    assert not any("execute-live" in path or "secret" in path for path in paths)


def test_staging_cors_allows_authenticated_member_management(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    response = TestClient(build_staging_app()).options(
        "/api/platform/tenants/tenant-1/members/principal-1",
        headers={
            "Origin": "http://127.0.0.1:8080",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8080"
    assert "DELETE" in response.headers["access-control-allow-methods"]
    assert "Authorization" in response.headers["access-control-allow-headers"]
