"""
Explicit readiness / fitness command — Week 31 items 2, 3, 4, 6 (V2 plan §6.2).

    cd apps/backend
    uv run python -m aria.llm.check                          # readiness (resolved mode)
    uv run python -m aria.llm.check --fitness                # selects local_ollama, runs fitness
    uv run python -m aria.llm.check --fitness --mode local_ollama   # explicit
    uv run python -m aria.llm.check --fitness --mode offline_mock   # plumbing dry-run (no Ollama)

Mode selection:
  - ``--mode <m>`` is explicit and wins.
  - otherwise ``--fitness`` selects ``local_ollama`` (you don't run a fitness gate
    against the mock brain by accident).
  - otherwise the resolved mode (``ARIA_EXECUTION_MODE`` env, else ``offline_mock``).

This is the **explicit readiness command** of the readiness boundary: probing runs
here (or at V2 chat/API startup, or a future health endpoint) — never at import.
It exits non-zero on failure so it can gate a shell workflow. Daemon/model
unavailability is recorded as a failed ``model_used`` telemetry event (sanitized
failure class) before exit.

Runtime-write note: by design this command is **not** isolated from runtime ledger
state. Its telemetry (readiness failure, fitness outcome) is appended to the real
Work Ledger v2 (``apps/backend/work_ledger_v2.jsonl``) via the default writer —
these are genuine model-use / failure records, not test artifacts. Only the test
suite redirects the writer to a temp file (autouse conftest fixture). The ledger
file is gitignored, so a local readiness run never affects committed state.
"""
from __future__ import annotations

import sys

from aria.llm.execution_mode import (
    ExecutionMode,
    InvalidExecutionModeError,
    coerce_execution_mode,
    resolve_execution_mode,
)
from aria.llm.readiness import (
    OllamaUnavailableError,
    configured_local_model,
    configured_ollama_host,
    ensure_local_model_available,
)

_READINESS_TASK_ID = "week31-readiness-check"
_FITNESS_TASK_ID = "week31-fitness-gate"

# Deterministic stub used only by the offline_mock fitness dry-run, so the gate
# plumbing can be exercised without a live model. Returns one valid JSON object
# that satisfies every fitness check.
_DRY_RUN_OUTPUT = (
    '{"action": "converse", "rationale": "dry-run", '
    '"operation": "create", "structured_value": "dry-run"}'
)


def _parse_mode_arg(argv: list[str]) -> str | None:
    """Extract ``--mode <value>`` (or ``--mode=<value>``) from argv, if present."""
    for i, arg in enumerate(argv):
        if arg == "--mode" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--mode="):
            return arg.split("=", 1)[1]
    return None


def _record_telemetry_safe(**kwargs) -> None:
    """Record a model_used telemetry event; never let a ledger error crash the CLI."""
    try:
        from aria.llm.telemetry import record_model_telemetry

        record_model_telemetry(**kwargs)
    except Exception:  # pragma: no cover - telemetry must not mask the real result
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    run_fitness = "--fitness" in argv
    mode_arg = _parse_mode_arg(argv)

    # Mode resolution: explicit --mode wins; else --fitness implies local_ollama;
    # else the resolved (env/default) mode.
    try:
        if mode_arg is not None:
            mode = coerce_execution_mode(mode_arg)
        elif run_fitness:
            mode = ExecutionMode.local_ollama
        else:
            mode = resolve_execution_mode()
    except InvalidExecutionModeError as exc:
        print(f"ERROR: {exc}")
        return 2

    model = configured_local_model()
    host = configured_ollama_host()

    print(f"Execution mode: {mode.value}")
    print(f"Configured model: {model}")
    print(f"Ollama host: {host}")

    if mode is ExecutionMode.offline_mock:
        if run_fitness:
            # Explicit test/demo dry-run: exercise the gate plumbing with a
            # deterministic stub, no Ollama contacted.
            from aria.llm.fitness import run_fitness_gate

            report = run_fitness_gate(runner=lambda _prompt: _DRY_RUN_OUTPUT, model=model)
            print("\nDRY RUN (offline_mock): gate plumbing only, not a real model.")
            print(report.summary())
            return 0 if report.passed else 1
        print("offline_mock: no Ollama required; nothing to verify.")
        return 0

    if mode is ExecutionMode.cloud_opt_in:
        print("cloud_opt_in: explicit cloud mode; local readiness not applicable.")
        return 0

    # local_ollama — verify the daemon and the configured model.
    try:
        report = ensure_local_model_available(model, host)
    except OllamaUnavailableError as exc:
        # P2 (Week 31 item 6): record the failure as ledger telemetry before exit.
        _record_telemetry_safe(
            task_id=_READINESS_TASK_ID,
            model_name=model,
            provider="ollama",
            execution_mode=mode.value,
            status="failed",
            failure_reason=type(exc).__name__,
            outcome="readiness_unavailable",
        )
        print(f"\nNOT READY:\n{exc}")
        return 1

    print(f"\nREADY: model {report.model!r} is available "
          f"({len(report.available_models)} model(s) installed).")

    if run_fitness:
        from aria.llm.fitness import run_fitness_gate

        fitness = run_fitness_gate(model=model, host=host)
        print("\n" + fitness.summary())
        worst_latency = max((c.latency_ms for c in fitness.checks), default=0)
        _record_telemetry_safe(
            task_id=_FITNESS_TASK_ID,
            model_name=model,
            provider="ollama",
            execution_mode=mode.value,
            latency_ms=worst_latency,
            status="ok" if fitness.passed else "failed",
            outcome="fitness_pass" if fitness.passed else "fitness_fail",
        )
        return 0 if fitness.passed else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
