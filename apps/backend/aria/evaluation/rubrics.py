"""
Eval Rubrics — Week 14

Structured rubric definitions for every ARIA skill.
Each rubric has scored dimensions (1–5). The LLM judge scores each dimension
independently — no holistic "feel". This is the difference between a demo and
a measurable system.

Why per-dimension scoring (not a single 1–5 score):
  - A single score hides which aspect failed: was it bad root causes? wrong
    risk level? vague actions? Per-dimension scores tell you exactly where to
    improve the skill prompt.
  - Per-dimension scores enable targeted DSPy optimisation at Week 21:
    "optimise the KPI skill prompt to improve hypothesis_quality without
     regressing on action_quality"

Scoring scale (consistent across all skills):
  5 — Excellent. Specific, actionable, grounded in media-tech domain.
  4 — Good. Minor gap in one area.
  3 — Acceptable. Correct but vague or generic.
  2 — Weak. Key element missing or incorrect.
  1 — Failing. Wrong, empty, or hallucinated.
"""
from typing import Literal
from pydantic import BaseModel, Field


class RubricDimension(BaseModel):
    name: str
    description: str
    weight: float = 1.0   # relative weight for weighted average


class Rubric(BaseModel):
    skill_name: str
    version: str = "v1"
    pass_threshold: float = 3.0    # overall score below this = FAIL
    warn_threshold: float = 3.5    # below this = WARN
    dimensions: list[RubricDimension]

    def dimension_names(self) -> list[str]:
        return [d.name for d in self.dimensions]

    def weighted_average(self, scores: dict[str, int]) -> float:
        total_weight = sum(d.weight for d in self.dimensions)
        weighted_sum = sum(
            scores.get(d.name, 1) * d.weight
            for d in self.dimensions
        )
        return round(weighted_sum / total_weight, 2)


# ── PR Review Rubric ──────────────────────────────────────────────────────────

PR_REVIEW_RUBRIC = Rubric(
    skill_name="pr_review",
    dimensions=[
        RubricDimension(
            name="issue_specificity",
            description=(
                "Code issues have specific severity, category, description of what's wrong, "
                "and a concrete actionable suggestion. Not vague ('improve this')."
            ),
            weight=1.5,
        ),
        RubricDimension(
            name="risk_accuracy",
            description=(
                "Risk level (high/medium/low) matches the actual deployment risk implied "
                "by the change. A ranking weight change is not 'low'. A README typo is not 'high'."
            ),
            weight=1.5,
        ),
        RubricDimension(
            name="test_coverage_awareness",
            description=(
                "Missing tests are named specifically — not 'add more tests'. "
                "Each missing test describes exactly what scenario is uncovered."
            ),
            weight=1.0,
        ),
        RubricDimension(
            name="deployment_risk_specificity",
            description=(
                "Deployment risks are production-specific. Not generic ('could cause issues'). "
                "Should name what breaks: which service, which metric, which user flow."
            ),
            weight=1.0,
        ),
        RubricDimension(
            name="domain_awareness",
            description=(
                "Business impact connects the code change to a concrete metric declared "
                "in the tenant's operating context. Generic 'could affect users' scores 1."
            ),
            weight=1.0,
        ),
    ],
)


# ── KPI Investigation Rubric ──────────────────────────────────────────────────

KPI_RUBRIC = Rubric(
    skill_name="kpi",
    dimensions=[
        RubricDimension(
            name="hypothesis_quality",
            description=(
                "Root cause hypotheses are specific and testable. Each names a concrete "
                "system or process that could explain the metric change. "
                "Not 'something went wrong with the algorithm'."
            ),
            weight=1.5,
        ),
        RubricDimension(
            name="domain_relevance",
            description=(
                "Hypotheses are grounded in media/content platform reality: "
                "ingestion pipeline, recommendation model, notification service, "
                "A/B test assignment, CDN, content freshness. Generic analytics advice scores 1."
            ),
            weight=1.5,
        ),
        RubricDimension(
            name="evidence_specificity",
            description=(
                "Evidence signals are concrete and measurable: 'compare recommendation "
                "model version deployed' not 'check your logs'. "
                "Each evidence item should be a specific query or check."
            ),
            weight=1.0,
        ),
        RubricDimension(
            name="action_quality",
            description=(
                "Recommended actions are immediately executable by an engineer. "
                "Each action has a clear next step. Not 'investigate further'."
            ),
            weight=1.0,
        ),
        RubricDimension(
            name="confidence_calibration",
            description=(
                "Confidence score reflects actual evidence available. "
                "With no data provided: 0.0–0.4. With clear symptom + timing: 0.5–0.8. "
                "Confidence > 0.9 without data = hallucination signal."
            ),
            weight=1.0,
        ),
    ],
)


# ── Registry ──────────────────────────────────────────────────────────────────

_RUBRICS: dict[str, Rubric] = {
    "pr_review": PR_REVIEW_RUBRIC,
    "kpi":       KPI_RUBRIC,
}

def get_rubric(skill_name: str) -> Rubric:
    if skill_name not in _RUBRICS:
        raise KeyError(f"No rubric registered for skill '{skill_name}'. Known: {list(_RUBRICS)}")
    return _RUBRICS[skill_name]

def list_rubrics() -> list[str]:
    return list(_RUBRICS)
