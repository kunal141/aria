"""
Evaluation Harness Hook — CONTRACT + deterministic mock emit (V4.1).

Evaluation is a first-class product layer: every runtime adapter and model route should
eventually be evaluable (output quality, prompt/model regression, safety-boundary
compliance, cost/latency, human labels, pass/fail reason, version history). V4.1 adds
ONLY the interface/contract/hook — it calls NO external eval API, NO cloud service, and
emits NO hidden telemetry. Persisted eval records are path-confined (by the store) and
source-linked (``input_ref`` / ``output_ref`` are required — no orphan eval claims).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EvalOutcome(str, Enum):
    pass_ = "pass"
    fail = "fail"
    not_evaluated = "not_evaluated"


class EvaluationRecord(BaseModel):
    """A single evaluation record. Source-linked: it must reference the input and output
    it evaluated. Advisory/measurement only — it approves and executes nothing."""
    model_config = ConfigDict(frozen=True)

    eval_id: str
    goal_id: str | None = None
    task_id: str | None = None
    adapter_id: str | None = None
    model_id: str | None = None
    prompt_version: str = "v0"
    skill_version: str = "v0"
    input_ref: str
    output_ref: str
    expected_behavior: str = ""
    actual_behavior: str = ""
    score: float = 0.0
    pass_fail: EvalOutcome = EvalOutcome.not_evaluated
    failure_reason: str = ""
    human_label: str = ""
    cost_estimate: float | None = None
    latency_ms: int = 0
    created_at: datetime


class EvaluationHookError(ValueError):
    """An evaluation record violated the source-linked discipline (missing input/output
    reference)."""


def _now() -> datetime:
    return datetime.now(UTC)


class EvaluationHook:
    """The emit interface adapters / model routes call to produce evaluation records.

    V4.1 wires the contract, not a scoring engine. ``build_record`` validates the
    source-linked discipline; ``evaluate_receipt`` provides a deterministic mock
    evaluation (a completed mock/dry-run receipt passes; a blocked/failed one fails).
    No external service is contacted.
    """

    def build_record(self, *, input_ref: str, output_ref: str, adapter_id: str | None = None,
                     model_id: str | None = None, goal_id: str | None = None,
                     task_id: str | None = None, expected_behavior: str = "",
                     actual_behavior: str = "", score: float = 0.0,
                     pass_fail: EvalOutcome = EvalOutcome.not_evaluated, failure_reason: str = "",
                     human_label: str = "", cost_estimate: float | None = None,
                     latency_ms: int = 0, prompt_version: str = "v0",
                     skill_version: str = "v0") -> EvaluationRecord:
        if not input_ref or not output_ref:
            raise EvaluationHookError(
                "an evaluation record must be source-linked (input_ref and output_ref required)")
        return EvaluationRecord(
            eval_id=f"eval-{uuid.uuid4().hex}", goal_id=goal_id, task_id=task_id,
            adapter_id=adapter_id, model_id=model_id, prompt_version=prompt_version,
            skill_version=skill_version, input_ref=input_ref, output_ref=output_ref,
            expected_behavior=expected_behavior, actual_behavior=actual_behavior, score=score,
            pass_fail=pass_fail, failure_reason=failure_reason, human_label=human_label,
            cost_estimate=cost_estimate, latency_ms=latency_ms, created_at=_now(),
        )

    def evaluate_receipt(self, receipt, request, *, model_id: str | None = None) -> EvaluationRecord:
        """A deterministic mock evaluation of an adapter receipt. A completed mock/dry-run
        run passes safety-boundary compliance (no external write occurred); a blocked or
        failed run fails. No external eval API."""
        completed = receipt.status.value in ("mock_completed", "dry_run_completed")
        outcome = EvalOutcome.pass_ if completed else EvalOutcome.fail
        reason = "" if completed else f"receipt status={receipt.status.value}"
        return self.build_record(
            input_ref=f"request:{request.request_id}", output_ref=f"receipt:{receipt.receipt_id}",
            adapter_id=receipt.adapter_id, model_id=model_id, goal_id=request.goal_id,
            task_id=request.task_id,
            expected_behavior="bounded local execution, no external write",
            actual_behavior=(receipt.output_summary or receipt.status.value)[:200],
            score=1.0 if completed else 0.0, pass_fail=outcome, failure_reason=reason,
            cost_estimate=0.0, latency_ms=0,
        )
