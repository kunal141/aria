"""
Fine-Tuning Prototype — offline candidate-vs-baseline evaluation.

PROTOTYPE ONLY. No model is invoked. This reuses the Model-Lifecycle
Registry's ``OfflineEvaluator`` (deterministic pseudo-metrics derived from
a model's immutable identity fingerprint + a fixed holdout) to score BOTH
a fine-tune candidate and a synthetic frontier baseline against the SAME
holdout, then decides — by a fixed dimension-win rule — whether the
candidate is good enough to even *request* human approval.

The decision is evidence, never an action: a "win" only lets the pipeline
move the candidate to ``awaiting_approval``. It never activates, deploys,
or routes traffic. A real evaluator (a LangSmith rubric against a served
endpoint) plugs in behind the same ``Evaluator`` protocol with no change
here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Protocol, runtime_checkable

from aria.model_registry.evaluator import (
    EvaluationReport,
    Evaluator,
    HoldoutExample,
    OfflineEvaluator,
    default_pr_review_holdout,
)
from aria.model_registry.models import (
    ModelProvider,
    ModelRecord,
    ModelStatus,
    ModelType,
)
from aria.fine_tuning.models import utc_now


# Dimensions on which a candidate is compared to the baseline, and how many
# it must strictly win to be considered promotable (request approval).
DEFAULT_DIMENSIONS: tuple[str, ...] = ("accuracy", "pass_rate", "rubric_score")
DEFAULT_PROMOTE_THRESHOLD: int = 2


@dataclass(frozen=True)
class CandidateEvaluation:
    """The immutable result of comparing a candidate to a baseline."""
    candidate_report: EvaluationReport
    baseline_report:  EvaluationReport
    metric_deltas:    dict[str, float]   # candidate - baseline, per dimension
    dimensions:       tuple[str, ...]
    dimensions_total: int
    dimensions_won:   int
    candidate_wins:   bool
    holdout_id:       str
    created_at:       datetime


@runtime_checkable
class CandidateEvaluatorProtocol(Protocol):
    def evaluate_candidate(
        self,
        candidate: ModelRecord,
        baseline: ModelRecord,
        holdout: list[HoldoutExample],
    ) -> CandidateEvaluation: ...


def default_baseline_record(
    production_consumer: str,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> ModelRecord:
    """
    A synthetic frontier baseline used ONLY to produce comparison metrics.

    This record is never registered, approved, activated, or served — it
    exists purely so the offline evaluator has a stable identity to score
    the candidate against. ``dataset_hash`` is the all-zero sentinel.
    """
    return ModelRecord(
        model_id="baseline-frontier",
        model_name="claude_frontier_baseline",
        semantic_version="0.0.0",
        provider=ModelProvider.anthropic,
        model_type=ModelType.frontier,
        base_model="claude-haiku",
        dataset_id="baseline",
        dataset_hash="0" * 64,
        production_consumer=production_consumer,
        status=ModelStatus.registered,
        created_by="aria",
        created_at=clock(),
    )


class OfflineCandidateEvaluator:
    """
    Scores candidate and baseline with an injected per-model ``Evaluator``
    (default: the registry's deterministic ``OfflineEvaluator``) and applies
    the dimension-win rule.
    """

    def __init__(
        self,
        evaluator: Optional[Evaluator] = None,
        *,
        dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
        promote_threshold: int = DEFAULT_PROMOTE_THRESHOLD,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._evaluator = evaluator if evaluator is not None else OfflineEvaluator()
        self._dimensions = dimensions
        self._promote_threshold = promote_threshold
        self._clock = clock

    def evaluate_candidate(
        self,
        candidate: ModelRecord,
        baseline: ModelRecord,
        holdout: list[HoldoutExample],
    ) -> CandidateEvaluation:
        cand = self._evaluator.evaluate(candidate, holdout)
        base = self._evaluator.evaluate(baseline, holdout)

        deltas: dict[str, float] = {}
        won = 0
        for dim in self._dimensions:
            c = float(cand.metrics.get(dim, 0.0))
            b = float(base.metrics.get(dim, 0.0))
            deltas[dim] = round(c - b, 6)
            if c > b:
                won += 1

        return CandidateEvaluation(
            candidate_report=cand,
            baseline_report=base,
            metric_deltas=deltas,
            dimensions=tuple(self._dimensions),
            dimensions_total=len(self._dimensions),
            dimensions_won=won,
            candidate_wins=won >= self._promote_threshold,
            holdout_id=cand.holdout_id,
            created_at=self._clock(),
        )


def default_holdout() -> list[HoldoutExample]:
    """The fixed, privacy-safe holdout shared with the registry demo/tests."""
    return default_pr_review_holdout()
