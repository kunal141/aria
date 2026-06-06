"""
Decision Intelligence data models — Week 24 (Pillar 20).

DecisionOption  → one candidate action with risk, confidence, cost, approval estimate
DecisionMatrix  → full set of options + recommended choice
DecisionResult  → final output from next_best_action(), including LATS telemetry
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, field_validator


CostLevel = Literal["low", "medium", "high"]


class DecisionOption(BaseModel):
    """A single candidate action ARIA could take."""
    option_id:           str
    action:              str    # imperative description of what ARIA would do
    rationale:           str    # why this option fits the situation
    risk_score:          float  # 0.0 = no risk, 1.0 = maximum risk
    confidence:          float  # 0.0 = no confidence, 1.0 = certain
    cost_estimate:       CostLevel = "medium"
    approval_likelihood: float  # predicted P(human approves) in [0.0, 1.0]

    @field_validator("risk_score", "confidence", "approval_likelihood")
    @classmethod
    def _clamp_float(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class DecisionMatrix(BaseModel):
    """Full option set with recommended choice and reasoning."""
    task_id:               str
    task_description:      str
    options:               List[DecisionOption]
    recommended_option_id: str
    reasoning:             str


class DecisionResult(BaseModel):
    """
    Output of next_best_action().
    Carries the selected option, the full matrix, and LATS telemetry.
    """
    task_id:         str
    selected_option: DecisionOption
    matrix:          DecisionMatrix
    lats_iterations: int   = 0
    method:          str   = "greedy"   # "lats" | "greedy" | "mock"
    version:         str   = "v1"
