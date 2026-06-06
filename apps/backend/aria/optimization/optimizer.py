"""
DSPy skill optimizer — Week 23.

optimize_skill() wraps DSPy's BootstrapFewShot compiler, falls back
gracefully when no LM is configured (deterministic test path).
"""
from typing import Any, Callable, List, Optional, Type

from pydantic import BaseModel


class SkillOptimizationResult(BaseModel):
    """Result of one optimize_skill() run."""
    skill_name:       str
    version:          str   = "v1"
    optimized:        bool  = False
    baseline_score:   float = 0.0
    optimized_score:  float = 0.0
    num_examples:     int   = 0
    compiled_program: Any   = None   # DSPy compiled predictor — arbitrary type
    error:            Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}


def optimize_skill(
    signature:                Type,
    trainset:                 List[Any],
    metric:                   Callable,
    lm:                       Optional[Any] = None,
    *,
    skill_name:               str = "unknown",
    max_bootstrapped_demos:   int = 3,
) -> SkillOptimizationResult:
    """
    Optimise a DSPy Signature using BootstrapFewShot.

    Args:
        signature:              DSPy Signature subclass to optimise.
        trainset:               List of dspy.Example instances.
        metric:                 Callable(example, prediction) → bool | float.
        lm:                     Configured DSPy LM.  Pass None to skip optimisation.
        skill_name:             Human-readable skill identifier for the result.
        max_bootstrapped_demos: Number of few-shot demonstrations to bootstrap.

    Returns:
        SkillOptimizationResult — always returns (never raises).
    """
    num_examples = len(trainset)

    if lm is None:
        return SkillOptimizationResult(
            skill_name=skill_name,
            optimized=False,
            num_examples=num_examples,
            error=(
                "No language model configured. "
                "Pass lm=dspy.LM(...) to enable optimisation."
            ),
        )

    if num_examples == 0:
        return SkillOptimizationResult(
            skill_name=skill_name,
            optimized=False,
            num_examples=0,
            error="Empty trainset — provide at least 1 example to optimise.",
        )

    try:
        import dspy
        from dspy.teleprompt import BootstrapFewShot

        predictor = dspy.Predict(signature)

        # ── Baseline score ────────────────────────────────────────────────────
        baseline_scores: List[float] = []
        with dspy.context(lm=lm):
            for ex in trainset:
                try:
                    inputs = {k: getattr(ex, k) for k in ex.inputs()}
                    pred = predictor(**inputs)
                    raw = metric(ex, pred)
                    baseline_scores.append(float(raw))
                except Exception:
                    baseline_scores.append(0.0)

        baseline = (
            sum(baseline_scores) / len(baseline_scores)
            if baseline_scores else 0.0
        )

        # ── Compile ───────────────────────────────────────────────────────────
        compiler = BootstrapFewShot(
            metric=metric,
            max_bootstrapped_demos=max_bootstrapped_demos,
        )
        with dspy.context(lm=lm):
            compiled = compiler.compile(predictor, trainset=trainset)

        # ── Optimised score ───────────────────────────────────────────────────
        optimised_scores: List[float] = []
        with dspy.context(lm=lm):
            for ex in trainset:
                try:
                    inputs = {k: getattr(ex, k) for k in ex.inputs()}
                    pred = compiled(**inputs)
                    raw = metric(ex, pred)
                    optimised_scores.append(float(raw))
                except Exception:
                    optimised_scores.append(0.0)

        optimised = (
            sum(optimised_scores) / len(optimised_scores)
            if optimised_scores else 0.0
        )

        return SkillOptimizationResult(
            skill_name=skill_name,
            optimized=True,
            baseline_score=round(baseline, 4),
            optimized_score=round(optimised, 4),
            num_examples=num_examples,
            compiled_program=compiled,
        )

    except Exception as exc:
        return SkillOptimizationResult(
            skill_name=skill_name,
            optimized=False,
            num_examples=num_examples,
            error=str(exc),
        )
