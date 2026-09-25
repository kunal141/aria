"""Typed contracts for ARIA's integrated, local virtual-employee workflow."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmployeeRunStatus(str, Enum):
    running = "running"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    escalated = "escalated"
    blocked = "blocked"
    failed = "failed"


class AttemptStatus(str, Enum):
    quality_failed = "quality_failed"
    passed = "passed"


class BusinessMetricPeriod(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    impressions: int = Field(gt=0)
    clicks: int = Field(ge=0)

    @model_validator(mode="after")
    def _clicks_within_impressions(self):
        if self.clicks > self.impressions:
            raise ValueError("clicks cannot exceed impressions")
        return self

    @property
    def ctr_percent(self) -> float:
        return round((self.clicks / self.impressions) * 100, 2)


class BusinessPerformanceDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str
    metric_name: str = "notification_ctr"
    previous: BusinessMetricPeriod
    current: BusinessMetricPeriod
    source_refs: list[str] = Field(min_length=1)


class BusinessAnalysisReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    executive_summary: str
    findings: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class QualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    repair_instruction: str


class EmployeeEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluation_id: str
    run_id: str
    attempt_id: str
    score: float = Field(ge=0, le=1)
    passed: bool
    issues: list[QualityIssue] = Field(default_factory=list)
    criteria: dict[str, bool] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(min_length=1)
    created_at: datetime


class RepairPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    repair_plan_id: str
    run_id: str
    failed_attempt_id: str
    next_attempt_number: int = Field(gt=1)
    failure_codes: list[str] = Field(min_length=1)
    instructions: list[str] = Field(min_length=1)
    created_at: datetime


class EmployeeAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str
    run_id: str
    attempt_number: int = Field(gt=0)
    worker_assignment_id: str
    route_decision_id: str
    adapter_request_id: str
    preview_receipt_id: str
    execution_receipt_id: str
    status: AttemptStatus
    report: BusinessAnalysisReport
    artifact_ref: str
    declared_cost_estimate: float | None = Field(default=None, ge=0)
    declared_latency_ms: int = Field(default=0, ge=0)
    created_at: datetime


class EmployeeRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    correlation_id: str
    employee_id: str = "emp-unassigned"
    goal_id: str
    workspace_id: str
    goal_text: str
    dataset: BusinessPerformanceDataset
    status: EmployeeRunStatus = EmployeeRunStatus.running
    success_criteria: list[str] = Field(min_length=1)
    max_attempts: int = Field(default=2, ge=1, le=5)
    current_attempt: int = Field(default=0, ge=0)
    route_decision_id: str | None = None
    selected_provider_id: str | None = None
    selected_model_id: str | None = None
    selected_adapter_id: str | None = None
    final_attempt_id: str | None = None
    manager_report_ref: str | None = None
    proof_packet_ref: str | None = None
    proof_packet: dict[str, Any] | None = None
    approval_task_id: str | None = None
    roi_minutes_saved: int = Field(default=0, ge=0)
    roi_method: str = "not calculated"
    roi_evidence_refs: list[str] = Field(default_factory=list)
    escalation_reason: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class ManagerRunView(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: EmployeeRun
    attempts: list[EmployeeAttempt]
    evaluations: list[EmployeeEvaluation]
    repair_plans: list[RepairPlan]
    final_report: BusinessAnalysisReport | None = None
    goal: dict[str, Any] = Field(default_factory=dict)
    roadmap: dict[str, Any] = Field(default_factory=dict)
    clarifications: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    workers: list[dict[str, Any]] = Field(default_factory=list)
    employee: dict[str, Any] = Field(default_factory=dict)
    employment_record: dict[str, Any] = Field(default_factory=dict)
    supervision_runs: list[dict[str, Any]] = Field(default_factory=list)
    route_decision: dict[str, Any] = Field(default_factory=dict)
    adapter_requests: list[dict[str, Any]] = Field(default_factory=list)
    workspace: dict[str, Any] = Field(default_factory=dict)
    approval_items: list[dict[str, Any]] = Field(default_factory=list)
    blocked_items: list[dict[str, Any]] = Field(default_factory=list)
    quality_score: float = 0.0
    risk_level: str = "low"
    declared_cost_estimate: float = 0.0
    declared_latency_ms: int = 0
    estimated_minutes_saved: int = 0
    roi_method: str = "conservative deterministic estimate; not production ROI"
    evidence_refs: list[str] = Field(default_factory=list)
    receipt_refs: list[str] = Field(default_factory=list)
    work_proof_packet: dict[str, Any] = Field(default_factory=dict)
    boundary_note: str = (
        "Offline deterministic proof only. No network, provider call, external write, "
        "automatic approval, deployment, or uncontrolled self-modification."
    )
