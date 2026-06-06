"""
Deterministic scoring functions for Decision Intelligence — Week 24.

All functions are pure (no LLM, no I/O) so they can be used as
LATS evaluation functions and as DSPy metrics.
"""
from typing import List

from aria.decision.models import DecisionOption

_COST_RISK = {"low": 0.0, "medium": 0.1, "high": 0.25}


def score_option(option: DecisionOption) -> float:
    """
    Composite score for a single DecisionOption in [0.0, 1.0].

    Weights:
      40%  confidence          — how sure ARIA is this option works
      40%  approval_likelihood — how likely a human approves it
      20%  safety              — inverse of risk_score
    """
    return round(
        option.confidence          * 0.40
        + option.approval_likelihood * 0.40
        + (1.0 - option.risk_score)  * 0.20,
        4,
    )


def rank_options(options: List[DecisionOption]) -> List[DecisionOption]:
    """Return options sorted by composite score, highest first."""
    return sorted(options, key=score_option, reverse=True)


def predict_approval(option: DecisionOption) -> float:
    """
    Heuristic approval likelihood:
      base = confidence
      deduct risk_score × 0.5
      deduct cost penalty (low=0, medium=0.1, high=0.25)
    Result is clamped to [0.0, 1.0].
    """
    cost_penalty = _COST_RISK.get(option.cost_estimate, 0.1)
    raw = option.confidence - (option.risk_score * 0.5) - cost_penalty
    return round(max(0.0, min(1.0, raw)), 4)


def release_risk_score(options: List[DecisionOption]) -> float:
    """
    Aggregate release risk across all options — useful for release-readiness checks.
    Returns the mean risk of all options, or 0.0 for an empty list.
    """
    if not options:
        return 0.0
    return round(sum(o.risk_score for o in options) / len(options), 4)
