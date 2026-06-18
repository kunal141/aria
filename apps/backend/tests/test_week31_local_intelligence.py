"""
Week 31 — Local-Intelligence Foundation tests (V2 plan §6, branch
``v2-complete-internal-ai-employee-pilot``).

Covers the seven Week 31 items:
  1. Execution Mode Contract — validation, no implicit fallback, safe default
  2. Ollama readiness boundary — probes only when explicitly requested
  3. gemma4:e4b availability — controlled failure, `ollama pull <model>`
  4. Model-fitness gate — pass / fail / graceful-failure / latency
  5. Structural no-cloud-fallback — local_ollama never builds a cloud client
  6. Model telemetry — ModelUsed event with provider + execution_mode metadata
  7. Import-time makes no network calls

All Ollama/cloud contact is injected (fake prober / monkeypatched ``get_llm``),
so the suite needs no live daemon and makes no network/paid calls.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from aria.llm import (
    DEFAULT_MODE,
    ExecutionMode,
    InvalidExecutionModeError,
    LocalModelUnavailableError,
    MinimalMemoryExtraction,
    MinimalRoutingDecision,
    OllamaUnavailableError,
    build_active_llm,
    build_model_telemetry_event,
    coerce_execution_mode,
    configured_local_model,
    ensure_local_model_available,
    mode_allows_cloud,
    mode_requires_ollama,
    mode_uses_mock,
    record_model_telemetry,
    resolve_execution_mode,
    resolve_provider_for_mode,
    run_fitness_gate,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


# ── Item 1: Execution Mode Contract ───────────────────────────────────────────


def test_default_mode_is_offline_mock(monkeypatch):
    monkeypatch.delenv("ARIA_EXECUTION_MODE", raising=False)
    assert resolve_execution_mode() is ExecutionMode.offline_mock
    assert DEFAULT_MODE is ExecutionMode.offline_mock


def test_env_selects_mode(monkeypatch):
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "local_ollama")
    assert resolve_execution_mode() is ExecutionMode.local_ollama


def test_explicit_argument_wins_over_env(monkeypatch):
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "local_ollama")
    assert resolve_execution_mode("offline_mock") is ExecutionMode.offline_mock


def test_invalid_mode_raises_loudly_no_fallback(monkeypatch):
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "bogus")
    with pytest.raises(InvalidExecutionModeError):
        resolve_execution_mode()
    with pytest.raises(InvalidExecutionModeError):
        coerce_execution_mode("not-a-mode")


def test_mode_predicates_are_exclusive():
    assert mode_uses_mock(ExecutionMode.offline_mock)
    assert not mode_uses_mock(ExecutionMode.local_ollama)
    assert mode_requires_ollama(ExecutionMode.local_ollama)
    assert not mode_requires_ollama(ExecutionMode.cloud_opt_in)
    assert mode_allows_cloud(ExecutionMode.cloud_opt_in)
    assert not mode_allows_cloud(ExecutionMode.local_ollama)
    assert not mode_allows_cloud(ExecutionMode.offline_mock)


# ── Item 2: Readiness boundary — probe only when requested ────────────────────


def test_readiness_probe_runs_only_when_called():
    calls: list = []

    def recording_prober(host, timeout):
        calls.append((host, timeout))
        return ["gemma4:e4b"]

    # Resolving modes / predicates must not probe anything.
    resolve_execution_mode("local_ollama")
    mode_requires_ollama(ExecutionMode.local_ollama)
    assert calls == []

    # The probe runs only when ensure_local_model_available is explicitly called.
    ensure_local_model_available("gemma4:e4b", prober=recording_prober)
    assert len(calls) == 1


def test_offline_mock_needs_no_ollama():
    """build_active_llm(offline_mock) returns None and never probes/builds."""
    probed: list = []

    def prober(host, timeout):
        probed.append(host)
        return []

    assert build_active_llm(ExecutionMode.offline_mock, prober=prober) is None
    assert probed == []  # offline_mock never touches the daemon


# ── Item 3: gemma4:e4b availability — controlled failure ──────────────────────


def test_daemon_unreachable_fails_loudly(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)

    def down_prober(host, timeout):
        raise OSError("connection refused")

    with pytest.raises(OllamaUnavailableError) as exc:
        ensure_local_model_available(prober=down_prober)
    msg = str(exc.value)
    assert "not reachable" in msg
    assert "will not fall back to a cloud provider" in msg


def test_model_absent_gives_ollama_pull_guidance(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)

    def prober(host, timeout):
        return ["llama3.2", "qwen2.5-coder:7b"]  # gemma4:e4b not installed

    with pytest.raises(LocalModelUnavailableError) as exc:
        ensure_local_model_available("gemma4:e4b", prober=prober)
    msg = str(exc.value)
    assert "ollama pull gemma4:e4b" in msg
    assert "will not auto-download" in msg


def test_substitute_model_guidance_interpolates(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-coder:7b")
    assert configured_local_model() == "qwen2.5-coder:7b"

    def prober(host, timeout):
        return ["gemma4:e4b"]  # configured substitute is absent

    with pytest.raises(LocalModelUnavailableError) as exc:
        ensure_local_model_available(prober=prober)
    assert "ollama pull qwen2.5-coder:7b" in str(exc.value)


def test_model_present_returns_report():
    report = ensure_local_model_available(
        "gemma4:e4b", prober=lambda host, timeout: ["gemma4:e4b", "llama3.2"]
    )
    assert report.ok is True
    assert report.model == "gemma4:e4b"


# ── Items 5 + "no-cloud-fallback" / "cloud creds present zero cloud calls" ─────


@pytest.fixture
def cloud_creds_present(monkeypatch):
    """Simulate a machine that HAS cloud credentials configured."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-not-used")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-fake-not-used")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")


@pytest.fixture
def get_llm_spy(monkeypatch):
    """Record every get_llm call's provider; never build a real client."""
    calls: list = []

    def fake_get_llm(provider=None, model=None, **kwargs):
        import os

        resolved = (provider or os.getenv("LLM_PROVIDER", "anthropic")).lower()
        calls.append({"provider": resolved, "model": model})
        return object()  # a stand-in "llm"

    import aria.config

    monkeypatch.setattr(aria.config, "get_llm", fake_get_llm)
    return calls


def test_local_ollama_provider_is_always_ollama(cloud_creds_present):
    assert resolve_provider_for_mode(ExecutionMode.local_ollama) == "ollama"


def test_local_ollama_never_builds_cloud_even_with_creds(cloud_creds_present, get_llm_spy):
    build_active_llm(
        ExecutionMode.local_ollama,
        model="gemma4:e4b",
        prober=lambda host, timeout: ["gemma4:e4b"],
    )
    # The ONLY provider ever constructed is ollama — never anthropic/openai.
    assert get_llm_spy == [{"provider": "ollama", "model": "gemma4:e4b"}]


def test_local_ollama_unavailable_does_not_call_cloud_or_mock(cloud_creds_present, get_llm_spy):
    with pytest.raises(OllamaUnavailableError):
        build_active_llm(
            ExecutionMode.local_ollama,
            model="gemma4:e4b",
            prober=lambda host, timeout: (_ for _ in ()).throw(OSError("down")),
        )
    # Failure means NO LLM was built at all — not a cloud client, not a downgrade.
    assert get_llm_spy == []


def test_cloud_used_only_with_explicit_cloud_opt_in(cloud_creds_present, get_llm_spy):
    build_active_llm(ExecutionMode.cloud_opt_in)
    assert len(get_llm_spy) == 1
    assert get_llm_spy[0]["provider"] == "anthropic"  # the configured cloud provider


# ── Item 4: Model-fitness gate ────────────────────────────────────────────────

_GOOD_JSON = (
    '{"action": "converse", "rationale": "ok", '
    '"operation": "create", "structured_value": "event_type=2 => story_click"}'
)


def test_fitness_gate_passes_with_good_model():
    report = run_fitness_gate(runner=lambda prompt: _GOOD_JSON, model="gemma4:e4b")
    assert report.passed is True
    assert {c.name for c in report.checks} == {
        "routing_decision",
        "memory_extraction",
        "conversation_quality",
    }
    assert all(c.passed for c in report.checks)


def test_fitness_gate_fails_on_bad_schema():
    report = run_fitness_gate(runner=lambda prompt: "totally not json", model="m")
    assert report.passed is False
    failed = {c.name for c in report.checks if not c.passed}
    assert "routing_decision" in failed
    assert "memory_extraction" in failed


def test_fitness_gate_handles_model_failure_gracefully():
    def boom(prompt):
        raise RuntimeError("model exploded")

    report = run_fitness_gate(runner=boom, model="m")  # must NOT raise
    assert report.passed is False
    assert all(not c.passed for c in report.checks)
    assert all("RuntimeError" in c.detail for c in report.checks)


def test_fitness_gate_enforces_latency_threshold():
    def slow(prompt):
        time.sleep(0.01)
        return _GOOD_JSON

    report = run_fitness_gate(runner=slow, model="m", latency_threshold_ms=1)
    assert report.passed is False
    assert any("latency" in c.detail for c in report.checks)


# ── Item 6: Model telemetry events ────────────────────────────────────────────


def test_build_telemetry_event_carries_provider_and_mode():
    from aria.ledger import LedgerEventType

    event = build_model_telemetry_event(
        task_id="t-1",
        model_name="gemma4:e4b",
        provider="ollama",
        execution_mode="local_ollama",
        latency_ms=1234,
        status="ok",
        outcome="fitness_pass",
    )
    assert event.event_type is LedgerEventType.model_used
    assert event.model_name == "gemma4:e4b"
    assert event.duration_ms == 1234
    assert event.metadata["provider"] == "ollama"
    assert event.metadata["execution_mode"] == "local_ollama"


def test_record_telemetry_to_isolated_writer(tmp_path):
    from aria.ledger.writer import LedgerWriter

    ledger_path = tmp_path / "telemetry.jsonl"
    writer = LedgerWriter(ledger_path)

    assert record_model_telemetry(
        writer=writer,
        task_id="t-2",
        model_name="gemma4:e4b",
        provider="ollama",
        execution_mode="local_ollama",
        latency_ms=42,
    ) is True

    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_type"] == "model_used"
    assert record["model_name"] == "gemma4:e4b"
    assert record["metadata"]["provider"] == "ollama"
    assert record["metadata"]["execution_mode"] == "local_ollama"


def test_record_telemetry_via_default_isolated_writer():
    """The autouse conftest fixture redirects the default writer to tmp; this
    proves the default path emits a model_used event without touching runtime."""
    from aria.ledger.writer import get_default_writer

    writer = get_default_writer()
    before = len(writer)
    assert record_model_telemetry(
        task_id="t-3",
        model_name="gemma4:e4b",
        provider="ollama",
        execution_mode="local_ollama",
        status="failed",
        failure_reason="OllamaUnavailableError",
    ) is True
    assert len(writer) == before + 1


# ── Item 7: import-time makes no network calls ────────────────────────────────


def test_importing_aria_llm_opens_no_sockets():
    """Fresh interpreter: block all socket creation, then import every aria.llm
    submodule. If anything probed Ollama or a cloud provider at import time, a
    socket would be created and the import would fail."""
    snippet = textwrap.dedent(
        """
        import socket

        class _BlockedNetwork(Exception):
            pass

        def _guard(*args, **kwargs):
            raise _BlockedNetwork("network access at import time is forbidden")

        socket.socket = _guard
        socket.create_connection = _guard

        import aria.llm
        import aria.llm.execution_mode
        import aria.llm.readiness
        import aria.llm.active_llm
        import aria.llm.fitness
        import aria.llm.telemetry
        import aria.llm.eval_schemas
        import aria.llm.check
        print("IMPORT_OK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"import failed:\n{proc.stderr}"
    assert "IMPORT_OK" in proc.stdout


# ── Frozen eval-only schemas are minimal compatibility contracts ──────────────


def test_eval_schemas_are_minimal_and_forward_compatible():
    # Minimal required fields...
    assert set(MinimalRoutingDecision.model_fields) == {"action", "rationale"}
    assert set(MinimalMemoryExtraction.model_fields) == {"operation", "structured_value"}
    # ...and forward-compatible (Week 32 may add fields; extras are ignored).
    routing = MinimalRoutingDecision.model_validate(
        {"action": "converse", "rationale": "x", "confidence": 0.9}
    )
    assert routing.action == "converse"


def test_routing_action_must_be_one_of_four_valid_actions():
    from pydantic import ValidationError

    for action in ("converse", "run_workflow", "propose_memory", "clarify"):
        MinimalRoutingDecision(action=action, rationale="ok")  # valid
    with pytest.raises(ValidationError):
        MinimalRoutingDecision(action="delete_everything", rationale="ok")


def test_memory_operation_must_be_one_of_planned_operations():
    from pydantic import ValidationError

    for op in ("create", "update", "delete"):
        MinimalMemoryExtraction(operation=op, structured_value="x")  # valid
    with pytest.raises(ValidationError):
        MinimalMemoryExtraction(operation="exfiltrate", structured_value="x")


# ── Readiness/fitness command (check.py) — P1.1 + P2.3 ────────────────────────


def _passing_fitness(model: str):
    from aria.llm.fitness import FitnessCheck, FitnessReport

    return FitnessReport(
        model=model, passed=True,
        checks=[FitnessCheck("routing_decision", True, 5)],
    )


def test_check_fitness_selects_local_ollama_and_records_telemetry(monkeypatch):
    from aria.llm import check as check_mod
    from aria.llm.readiness import ReadinessReport

    monkeypatch.setattr(
        check_mod, "ensure_local_model_available",
        lambda model, host: ReadinessReport(ok=True, model=model, host=host,
                                            available_models=[model]),
    )
    import aria.llm.fitness as fit
    monkeypatch.setattr(fit, "run_fitness_gate", lambda **kw: _passing_fitness(kw.get("model", "m")))

    recorded: list = []
    import aria.llm.telemetry as tel
    monkeypatch.setattr(tel, "record_model_telemetry", lambda **kw: recorded.append(kw))

    rc = check_mod.main(["--fitness"])  # no --mode → must select local_ollama
    assert rc == 0
    assert recorded and recorded[-1]["execution_mode"] == "local_ollama"
    assert recorded[-1]["status"] == "ok"


def test_check_readiness_failure_records_failed_telemetry(monkeypatch):
    from aria.llm import check as check_mod

    def boom(model, host):
        raise OllamaUnavailableError("daemon down; will not fall back to a cloud provider")

    monkeypatch.setattr(check_mod, "ensure_local_model_available", boom)

    recorded: list = []
    import aria.llm.telemetry as tel
    monkeypatch.setattr(tel, "record_model_telemetry", lambda **kw: recorded.append(kw))

    rc = check_mod.main(["--mode", "local_ollama"])
    assert rc == 1
    assert len(recorded) == 1
    event = recorded[0]
    assert event["status"] == "failed"
    assert event["failure_reason"] == "OllamaUnavailableError"  # sanitized class, no raw text
    assert event["execution_mode"] == "local_ollama"
    assert event["outcome"] == "readiness_unavailable"


def test_check_offline_mock_fitness_is_dry_run_without_ollama(monkeypatch):
    from aria.llm import check as check_mod

    def fail_if_called(*args, **kwargs):
        raise AssertionError("offline_mock dry-run must not contact Ollama")

    monkeypatch.setattr(check_mod, "ensure_local_model_available", fail_if_called)
    rc = check_mod.main(["--mode", "offline_mock", "--fitness"])
    assert rc == 0  # plumbing dry-run passes, no daemon contacted


def test_check_invalid_mode_returns_controlled_error(capsys):
    from aria.llm import check as check_mod

    rc = check_mod.main(["--mode", "bogus"])
    assert rc == 2
    assert "Invalid execution mode" in capsys.readouterr().out
