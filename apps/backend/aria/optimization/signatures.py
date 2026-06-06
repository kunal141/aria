"""
DSPy Signatures for ARIA skills — Week 23.

Each Signature declares the input/output contract for a skill,
enabling systematic prompt optimisation via DSPy compilers.
"""
import dspy
from pydantic import BaseModel


# ── Instructor-validated output model ─────────────────────────────────────────

class TaskTypeOutput(BaseModel):
    """Structured output for task-type classification (Instructor-enforced)."""
    task_type: str
    confidence: float = 0.0
    reason: str = ""


# ── DSPy Signatures ───────────────────────────────────────────────────────────

class RouterSignature(dspy.Signature):
    """Classify a user request into the correct ARIA task type."""

    raw_input: str = dspy.InputField(
        desc="Natural language task description from the user"
    )
    task_type: str = dspy.OutputField(
        desc="One of: pr_review, kpi, ci_cd, jira, qa, test_review, general"
    )
    confidence: str = dspy.OutputField(
        desc="Confidence score 0.0–1.0 as a decimal string"
    )
    reason: str = dspy.OutputField(
        desc="One sentence explaining the classification decision"
    )


class PRReviewSignature(dspy.Signature):
    """Review a pull request for code quality, risk, and business impact."""

    raw_input: str = dspy.InputField(
        desc="PR title, description, and diff summary for the pull request"
    )
    risk_level: str = dspy.OutputField(
        desc="Risk level of the PR: low / medium / high / critical"
    )
    verdict: str = dspy.OutputField(
        desc="Review verdict: APPROVE / REQUEST_CHANGES / NEEDS_DISCUSSION"
    )
    summary: str = dspy.OutputField(
        desc="One-line executive summary of the review findings"
    )
    issues: str = dspy.OutputField(
        desc="Comma-separated list of key issues or concerns found"
    )


class KPISignature(dspy.Signature):
    """Investigate a KPI anomaly and identify root causes."""

    raw_input: str = dspy.InputField(
        desc="KPI anomaly description including metric names and observed deltas"
    )
    root_cause: str = dspy.OutputField(
        desc="Primary root cause of the anomaly in one concise sentence"
    )
    confidence: str = dspy.OutputField(
        desc="Confidence in the root cause assessment: low / medium / high"
    )
    recommended_action: str = dspy.OutputField(
        desc="Top recommended action to address or investigate the anomaly"
    )
    severity: str = dspy.OutputField(
        desc="Anomaly severity: low / medium / high / critical"
    )
