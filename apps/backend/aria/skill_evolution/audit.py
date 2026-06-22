"""
Work Ledger event construction for the V3.5 skill-evolution store.

Mirrors ``aria.goals.audit``: every skill-lifecycle event is built here, then
enqueued into the skill store's transactional **audit outbox** in the same SQLite
transaction as the state change and flushed to the Work Ledger — so skill state and
its audit can never diverge.

Skill identifiers (gap_id, proposal_id, spec_id, evaluation_id, workspace_id,
recommended_decision) ride in the sanitised ``metadata`` dict; ``correlation_id``
and ``actor`` are typed envelope fields. Redaction still runs at the writer boundary.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    LedgerEventType,
    SkillActivated,
    SkillApprovalRequested,
    SkillDeprecated,
    SkillEvaluated,
    SkillGapDetected,
    SkillProposalCreated,
    SkillRejected,
    SkillRolledBack,
    SkillSpecGenerated,
    SkillTestPlanGenerated,
)
from aria.ledger.events import RiskLevel, make_envelope

_EVENT_CLASSES = {
    LedgerEventType.skill_gap_detected:        SkillGapDetected,
    LedgerEventType.skill_proposal_created:    SkillProposalCreated,
    LedgerEventType.skill_spec_generated:      SkillSpecGenerated,
    LedgerEventType.skill_test_plan_generated: SkillTestPlanGenerated,
    LedgerEventType.skill_evaluated:           SkillEvaluated,
    LedgerEventType.skill_approval_requested:  SkillApprovalRequested,
    LedgerEventType.skill_activated:           SkillActivated,
    LedgerEventType.skill_rejected:            SkillRejected,
    LedgerEventType.skill_deprecated:          SkillDeprecated,
    LedgerEventType.skill_rolled_back:         SkillRolledBack,
}

_RISK_LEVELS = {r.value: r for r in RiskLevel}


def _coerce_risk(value: str | RiskLevel | None) -> RiskLevel | None:
    if value is None or isinstance(value, RiskLevel):
        return value
    return _RISK_LEVELS.get(str(value).strip().lower(), RiskLevel.low)


def build_skill_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    gap_id: str | None = None,
    proposal_id: str | None = None,
    spec_id: str | None = None,
    test_plan_id: str | None = None,
    evaluation_id: str | None = None,
    workspace_id: str | None = None,
    scope: str | None = None,
    execution_mode: str | None = None,
    outcome: str | None = None,
    risk_level: str | RiskLevel | None = "low",
    approval_required: bool | None = None,
    recommended_decision: str | None = None,
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("gap_id", gap_id),
        ("proposal_id", proposal_id),
        ("spec_id", spec_id),
        ("test_plan_id", test_plan_id),
        ("evaluation_id", evaluation_id),
        ("workspace_id", workspace_id),
        ("scope", scope),
        ("execution_mode", execution_mode),
        ("approval_required", approval_required),
        ("recommended_decision", recommended_decision),
    ):
        if value is not None:
            meta[key] = value
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or proposal_id or gap_id or task_id,
        outcome=outcome,
        risk_level=_coerce_risk(risk_level),
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
