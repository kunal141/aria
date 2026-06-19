"""
Work Ledger event construction for the V3.1 goal store.

Mirrors ``aria.memory_v2.audit``: every goal/roadmap/task planning event is built
here, then enqueued into the goal store's transactional **audit outbox** inside the
same SQLite transaction as the state change and flushed to the Work Ledger — so
goal state and its audit can never diverge.

Goal-specific identifiers (goal_id, roadmap_id, task_id, workspace_id, scope,
execution_mode) ride in the sanitised ``metadata`` dict; ``correlation_id`` and
``actor`` are typed envelope fields. No envelope changes are needed and redaction
still runs at the writer boundary.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    AgentAssignmentBlocked,
    AgentAssignmentCancelled,
    AgentAssignmentCompleted,
    AgentAssignmentCreated,
    AgentAssignmentStarted,
    AgentResultMerged,
    AgentWorkforcePlanned,
    ClarificationAnswered,
    ClarificationRequested,
    DeliverableTracked,
    EvidenceProvided,
    GoalCreated,
    GoalProgressReported,
    LedgerEventType,
    ProblemStatementGenerated,
    ProgressReportCreated,
    RoadmapCreated,
    TaskBoardCreated,
    TaskStatusUpdated,
    WorkStepBlocked,
    WorkStepCompleted,
    WorkStepStarted,
)
from aria.ledger.events import RiskLevel, make_envelope

_EVENT_CLASSES = {
    LedgerEventType.goal_created:                GoalCreated,
    LedgerEventType.problem_statement_generated: ProblemStatementGenerated,
    LedgerEventType.roadmap_created:             RoadmapCreated,
    LedgerEventType.task_board_created:          TaskBoardCreated,
    LedgerEventType.task_status_updated:         TaskStatusUpdated,
    LedgerEventType.goal_progress_reported:      GoalProgressReported,
    # V3.2 — work-execution loop
    LedgerEventType.work_step_started:           WorkStepStarted,
    LedgerEventType.work_step_completed:         WorkStepCompleted,
    LedgerEventType.work_step_blocked:           WorkStepBlocked,
    LedgerEventType.clarification_requested:     ClarificationRequested,
    LedgerEventType.clarification_answered:      ClarificationAnswered,
    LedgerEventType.evidence_provided:           EvidenceProvided,
    LedgerEventType.progress_report_created:     ProgressReportCreated,
    LedgerEventType.deliverable_tracked:         DeliverableTracked,
    # V3.3 — dynamic agent workforce (dry-run)
    LedgerEventType.agent_workforce_planned:     AgentWorkforcePlanned,
    LedgerEventType.agent_assignment_created:    AgentAssignmentCreated,
    LedgerEventType.agent_assignment_started:    AgentAssignmentStarted,
    LedgerEventType.agent_assignment_completed:  AgentAssignmentCompleted,
    LedgerEventType.agent_assignment_blocked:    AgentAssignmentBlocked,
    LedgerEventType.agent_assignment_cancelled:  AgentAssignmentCancelled,
    LedgerEventType.agent_result_merged:         AgentResultMerged,
}

_RISK_LEVELS = {r.value: r for r in RiskLevel}


def _coerce_risk(value: str | RiskLevel | None) -> RiskLevel | None:
    if value is None or isinstance(value, RiskLevel):
        return value
    return _RISK_LEVELS.get(str(value).strip().lower(), RiskLevel.low)


def build_goal_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    goal_id: str | None = None,
    roadmap_id: str | None = None,
    task_ref: str | None = None,
    workspace_id: str | None = None,
    scope: str | None = None,
    execution_mode: str | None = None,
    outcome: str | None = None,
    risk_level: str | RiskLevel | None = "low",
    approval_required: bool | None = None,
    evidence_status: str | None = None,
    step_id: str | None = None,
    clarification_id: str | None = None,
    evidence_refs: list[str] | None = None,
    agent_id: str | None = None,
    assignment_id: str | None = None,
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("goal_id", goal_id),
        ("roadmap_id", roadmap_id),
        ("task_id", task_ref),
        ("workspace_id", workspace_id),
        ("scope", scope),
        ("execution_mode", execution_mode),
        ("approval_required", approval_required),
        ("evidence_status", evidence_status),
        ("step_id", step_id),
        ("clarification_id", clarification_id),
        ("evidence_refs", evidence_refs),
        ("agent_id", agent_id),
        ("assignment_id", assignment_id),
    ):
        if value is not None:
            meta[key] = value
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or goal_id or task_id,
        outcome=outcome,
        risk_level=_coerce_risk(risk_level),
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
