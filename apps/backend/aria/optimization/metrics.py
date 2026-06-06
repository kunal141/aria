"""
Deterministic eval metrics for DSPy optimisation — Week 23.

Metric functions follow the DSPy convention:
    metric(example, prediction, trace=None) -> bool | float

All metrics are deterministic — no LLM required.
"""
from typing import Any

_VALID_TASK_TYPES = frozenset({
    "pr_review", "kpi", "ci_cd", "jira", "qa", "test_review", "general",
})
_VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
_VALID_VERDICTS    = frozenset({"APPROVE", "REQUEST_CHANGES", "NEEDS_DISCUSSION"})
_VALID_SEVERITIES  = frozenset({"low", "medium", "high", "critical"})
_VALID_CONFIDENCES = frozenset({"low", "medium", "high"})


def routing_accuracy(example: Any, prediction: Any, trace: Any = None) -> bool:
    """
    Binary metric: True iff predicted task_type matches expected_task_type.
    Used by BootstrapFewShot to select good demonstrations.
    """
    expected  = str(getattr(example,    "expected_task_type", "") or "").strip().lower()
    predicted = str(getattr(prediction, "task_type",          "") or "").strip().lower()
    return bool(expected and predicted and expected == predicted)


def pr_review_quality(example: Any, prediction: Any, trace: Any = None) -> float:
    """
    Float metric 0.0–1.0 scoring PR review output quality:
      - 0.4 points for a valid verdict
      - 0.4 points for a valid risk_level
      - 0.2 points for a non-empty summary
    """
    verdict  = str(getattr(prediction, "verdict",    "") or "").strip().upper()
    risk     = str(getattr(prediction, "risk_level", "") or "").strip().lower()
    summary  = str(getattr(prediction, "summary",    "") or "").strip()

    score = 0.0
    if verdict in _VALID_VERDICTS:
        score += 0.4
    if risk in _VALID_RISK_LEVELS:
        score += 0.4
    if summary:
        score += 0.2
    return score


def kpi_quality(example: Any, prediction: Any, trace: Any = None) -> float:
    """
    Float metric 0.0–1.0 scoring KPI investigation output quality:
      - 0.4 points for a non-empty root_cause
      - 0.3 points for a valid severity
      - 0.3 points for a non-empty recommended_action
    """
    root_cause = str(getattr(prediction, "root_cause",          "") or "").strip()
    severity   = str(getattr(prediction, "severity",            "") or "").strip().lower()
    action     = str(getattr(prediction, "recommended_action",  "") or "").strip()

    score = 0.0
    if root_cause:
        score += 0.4
    if severity in _VALID_SEVERITIES:
        score += 0.3
    if action:
        score += 0.3
    return round(score, 4)
