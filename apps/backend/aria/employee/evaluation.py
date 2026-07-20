"""Deterministic business-output evaluation and bounded repair planning."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from aria.employee.models import (
    BusinessAnalysisReport,
    BusinessPerformanceDataset,
    EmployeeEvaluation,
    QualityIssue,
    RepairPlan,
)


def _now() -> datetime:
    return datetime.now(UTC)


def render_report(report: BusinessAnalysisReport, *, run_id: str, attempt_number: int) -> str:
    """Canonical manager-report bytes used by both the service and store authority."""
    def section(title: str, values: list[str]) -> list[str]:
        return [f"## {title}", *[f"- {value}" for value in values], ""]

    lines = [f"# {report.title}", "", f"Run: {run_id}", f"Attempt: {attempt_number}", "",
             "## Executive Summary", report.executive_summary, ""]
    lines += section("Findings", report.findings)
    lines += section("Risks", report.risks)
    lines += section("Recommendations", report.recommendations)
    lines += section("Evidence", report.evidence_refs)
    return "\n".join(lines)


def evaluate_business_report(
    *, run_id: str, attempt_id: str, report: BusinessAnalysisReport,
    dataset: BusinessPerformanceDataset,
) -> EmployeeEvaluation:
    """Evaluate concrete, source-checkable report requirements without an LLM judge."""
    expected_delta = round(dataset.current.ctr_percent - dataset.previous.ctr_percent, 2)
    delta_token = f"{expected_delta:+.2f} percentage points"
    criteria = {
        "findings_present": bool(report.findings),
        "risks_present": bool(report.risks),
        "recommendations_present": bool(report.recommendations),
        "evidence_cited": all(ref in report.evidence_refs for ref in dataset.source_refs),
        "metric_delta_correct": any(delta_token in finding for finding in report.findings),
        "manager_summary_present": bool(report.executive_summary.strip()),
    }
    issue_specs = {
        "findings_present": ("missing_findings", "The report has no findings.",
                             "Add evidence-backed findings."),
        "risks_present": ("missing_risks", "The report has no risk section.",
                          "Add concrete risks and limitations."),
        "recommendations_present": ("missing_recommendations",
                                    "The report has no recommendations.",
                                    "Add bounded manager recommendations."),
        "evidence_cited": ("missing_evidence", "Dataset evidence is not cited.",
                           "Cite every dataset source reference."),
        "metric_delta_correct": ("incorrect_metric_delta", "The CTR delta is not verified.",
                                 "Recalculate the percentage-point change from source data."),
        "manager_summary_present": ("missing_manager_summary", "Manager summary is missing.",
                                    "Add a concise executive summary."),
    }
    issues = [QualityIssue(code=issue_specs[name][0], message=issue_specs[name][1],
                           repair_instruction=issue_specs[name][2])
              for name, passed in criteria.items() if not passed]
    score = round(sum(criteria.values()) / len(criteria), 4)
    return EmployeeEvaluation(
        evaluation_id=f"eeval-{uuid.uuid4().hex}", run_id=run_id, attempt_id=attempt_id,
        score=score, passed=not issues, issues=issues, criteria=criteria,
        evidence_refs=list(dataset.source_refs), created_at=_now(),
    )


def build_repair_plan(evaluation: EmployeeEvaluation, *, next_attempt_number: int) -> RepairPlan:
    if evaluation.passed or not evaluation.issues:
        raise ValueError("a repair plan requires a failed evaluation with concrete issues")
    return RepairPlan(
        repair_plan_id=f"repair-{uuid.uuid4().hex}", run_id=evaluation.run_id,
        failed_attempt_id=evaluation.attempt_id, next_attempt_number=next_attempt_number,
        failure_codes=[issue.code for issue in evaluation.issues],
        instructions=[issue.repair_instruction for issue in evaluation.issues],
        created_at=_now(),
    )
