"""
Decision Intelligence engine — Week 24 (Pillar 20).

next_best_action() is ARIA's top-level decision API:
  given a task + a list of candidate options → returns the best option
  with full traceability (DecisionResult with matrix + LATS telemetry).
"""
from typing import List, Optional

from aria.decision.models import DecisionOption, DecisionMatrix, DecisionResult
from aria.decision.scorer import score_option, rank_options, predict_approval
from aria.decision.lats import run_lats


def next_best_action(
    task_id: str,
    task_description: str,
    options: List[DecisionOption],
    *,
    method: str = "lats",
    max_iterations: int = 10,
) -> DecisionResult:
    """
    Core Decision Intelligence entry point.

    Selects the best DecisionOption for a given task using the specified method:
      "lats"   — Language Agent Tree Search (principled, UCT-guided ranking)
      "greedy" — simple rank_options() by composite score, pick first
      "mock"   — returns first option unchanged (deterministic test path)

    Returns a DecisionResult with full decision matrix and telemetry.
    Falls back to "greedy" on empty options list edge-case.
    """
    if not options:
        placeholder = DecisionOption(
            option_id="none",
            action="No options provided — request more information",
            rationale="Empty option set received",
            risk_score=1.0,
            confidence=0.0,
            cost_estimate="low",
            approval_likelihood=0.0,
        )
        matrix = DecisionMatrix(
            task_id=task_id,
            task_description=task_description,
            options=[placeholder],
            recommended_option_id="none",
            reasoning="No options provided.",
        )
        return DecisionResult(
            task_id=task_id,
            selected_option=placeholder,
            matrix=matrix,
            lats_iterations=0,
            method="greedy",
        )

    iterations = 0

    if method == "mock":
        selected = options[0]
        ranked   = options

    elif method == "lats":
        selected, iterations = run_lats(options, max_iterations=max_iterations)
        ranked = rank_options(options)

    else:  # greedy
        ranked   = rank_options(options)
        selected = ranked[0]

    # Enrich options with predicted approval likelihoods
    enriched = []
    for opt in options:
        approval = predict_approval(opt)
        enriched.append(opt.model_copy(update={"approval_likelihood": approval}))

    # Find the enriched version of selected
    enriched_selected = next(
        (e for e in enriched if e.option_id == selected.option_id),
        selected,
    )

    matrix = DecisionMatrix(
        task_id=task_id,
        task_description=task_description,
        options=enriched,
        recommended_option_id=enriched_selected.option_id,
        reasoning=(
            f"Selected via {method} "
            f"(score={score_option(enriched_selected):.3f}, "
            f"risk={enriched_selected.risk_score:.2f}, "
            f"approval={enriched_selected.approval_likelihood:.2f})"
        ),
    )

    return DecisionResult(
        task_id=task_id,
        selected_option=enriched_selected,
        matrix=matrix,
        lats_iterations=iterations,
        method=method,
    )
