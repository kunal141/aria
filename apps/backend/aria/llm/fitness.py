"""
Model-fitness gate — Week 31 item 4 (V2 plan §6.3).

A small, local, testable readiness check that a configured model is *fit* for the
behaviours V2 depends on — without implementing the real conversation or memory
layers. It validates the model against the **frozen, minimal eval-only schemas**
(``aria.llm.eval_schemas``), not Week 32's full contracts.

Checks performed:
  - structured routing decision  → parses ``MinimalRoutingDecision``
  - memory-extraction sample     → parses ``MinimalMemoryExtraction``
  - conversation-quality sample  → coherent, non-empty reply
  - output-schema validity       → the two parses above
  - latency threshold            → each call within ``latency_threshold_ms``
  - failure handling             → a raising model call fails the check
                                   gracefully, the gate does not crash

The model is reached through an injectable ``runner`` (``Callable[[str], str]``)
so the gate is fully testable without a live Ollama. The default runner uses the
local Ollama model only (never cloud), after verifying readiness.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from aria.llm.eval_schemas import MinimalMemoryExtraction, MinimalRoutingDecision

# A runner takes a prompt and returns the model's raw text output.
Runner = Callable[[str], str]

DEFAULT_LATENCY_THRESHOLD_MS = 20_000


@dataclass(frozen=True)
class FitnessCheck:
    name: str
    passed: bool
    latency_ms: int
    detail: str = ""


@dataclass(frozen=True)
class FitnessReport:
    model: str
    passed: bool
    checks: list[FitnessCheck] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Model-fitness gate for {self.model!r}: "
                 f"{'PASS' if self.passed else 'FAIL'}"]
        for c in self.checks:
            mark = "ok " if c.passed else "FAIL"
            extra = f" — {c.detail}" if c.detail else ""
            lines.append(f"  [{mark}] {c.name} ({c.latency_ms} ms){extra}")
        return "\n".join(lines)


def _extract_json(text: str) -> dict:
    """Best-effort parse of a JSON object from model text (tolerates ```json
    fences and surrounding prose). Raises ``ValueError`` if no object found."""
    if text is None:
        raise ValueError("empty model output")
    s = text.strip()
    if s.startswith("```"):
        # strip a ```json ... ``` fence
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
        s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in model output")
    return json.loads(s[start : end + 1])


def _timed_check(
    name: str,
    prompt: str,
    runner: Runner,
    validate: Callable[[str], str],
    latency_threshold_ms: int,
) -> FitnessCheck:
    """Run one check: time the model call, validate, enforce latency.

    ``validate`` returns a short detail string on success and raises on failure.
    Any exception (model error OR validation failure) yields a failed check —
    the gate never propagates it (graceful failure handling).
    """
    started = time.perf_counter()
    try:
        output = runner(prompt)
        detail = validate(output)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        # Record only the exception class — never raw text (may carry secrets).
        return FitnessCheck(name=name, passed=False, latency_ms=latency_ms,
                            detail=f"error: {type(exc).__name__}")
    latency_ms = int((time.perf_counter() - started) * 1000)
    if latency_ms > latency_threshold_ms:
        return FitnessCheck(name=name, passed=False, latency_ms=latency_ms,
                            detail=f"latency {latency_ms}ms > {latency_threshold_ms}ms")
    return FitnessCheck(name=name, passed=True, latency_ms=latency_ms, detail=detail)


def _validate_schema(model_cls: type[BaseModel]) -> Callable[[str], str]:
    def _v(output: str) -> str:
        obj = _extract_json(output)
        try:
            model_cls.model_validate(obj)
        except ValidationError as exc:
            raise ValueError(f"schema mismatch: {exc.error_count()} error(s)") from exc
        return "schema ok"
    return _v


def _validate_conversation(output: str) -> str:
    if output is None or not output.strip():
        raise ValueError("empty conversational reply")
    return "non-empty reply"


def run_fitness_gate(
    runner: Runner | None = None,
    *,
    model: str | None = None,
    host: str | None = None,
    latency_threshold_ms: int = DEFAULT_LATENCY_THRESHOLD_MS,
) -> FitnessReport:
    """Run the fitness gate against ``runner`` (default: local Ollama).

    Returns a :class:`FitnessReport`; ``report.passed`` is True only if every
    check passed within the latency threshold. Never raises for model/validation
    failures — those are recorded as failed checks.
    """
    from aria.llm.readiness import configured_local_model

    target_model = model or configured_local_model()
    if runner is None:
        runner = _default_runner(target_model, host)

    checks = [
        _timed_check(
            "routing_decision",
            'Reply with ONLY JSON: {"action": "converse", "rationale": "<why>"}. '
            "Pick action from converse|run_workflow|propose_memory|clarify for: "
            '"summarise the last deploy".',
            runner,
            _validate_schema(MinimalRoutingDecision),
            latency_threshold_ms,
        ),
        _timed_check(
            "memory_extraction",
            'Reply with ONLY JSON: {"operation": "create", "structured_value": "<fact>"}. '
            "Extract the reusable fact from: "
            '"in story_events, event_type=2 means story_click".',
            runner,
            _validate_schema(MinimalMemoryExtraction),
            latency_threshold_ms,
        ),
        _timed_check(
            "conversation_quality",
            "Reply with one short sentence acknowledging that the CI build passed.",
            runner,
            _validate_conversation,
            latency_threshold_ms,
        ),
    ]
    passed = all(c.passed for c in checks)
    return FitnessReport(model=target_model, passed=passed, checks=checks)


def _default_runner(model: str, host: str | None) -> Runner:
    """Build a local-Ollama-only runner (never cloud), after a readiness check."""
    from aria.llm.active_llm import build_active_llm
    from aria.llm.execution_mode import ExecutionMode

    llm = build_active_llm(ExecutionMode.local_ollama, model=model, host=host)

    def _run(prompt: str) -> str:
        response = llm.invoke(prompt)
        return getattr(response, "content", str(response))

    return _run
