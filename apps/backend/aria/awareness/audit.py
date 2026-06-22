"""
Work Ledger event construction for the V3.6 work-memory + world-awareness store.

Mirrors the other audit modules: every event is built here, then enqueued into the
awareness store's transactional **audit outbox** in the same SQLite transaction as
the state change and flushed to the Work Ledger — so state and audit can never
diverge. Identifiers (node/lesson/source/update/goal/skill/workspace ids,
trust_level, relevance_score) ride in the sanitised ``metadata`` dict.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    ImprovementProposalCreated,
    LedgerEventType,
    WorkLessonCreated,
    WorkLessonDisabled,
    WorkMemoryConsolidated,
    WorkMemoryEdgeCreated,
    WorkMemoryNodeCreated,
    WorkMemoryNodeRedacted,
    WorldSourceRegistered,
    WorldUpdateIngested,
    WorldUpdateScored,
)
from aria.ledger.events import RiskLevel, make_envelope

_EVENT_CLASSES = {
    LedgerEventType.work_memory_node_created:     WorkMemoryNodeCreated,
    LedgerEventType.work_memory_node_redacted:    WorkMemoryNodeRedacted,
    LedgerEventType.work_memory_edge_created:     WorkMemoryEdgeCreated,
    LedgerEventType.work_lesson_created:          WorkLessonCreated,
    LedgerEventType.work_lesson_disabled:         WorkLessonDisabled,
    LedgerEventType.work_memory_consolidated:     WorkMemoryConsolidated,
    LedgerEventType.world_source_registered:      WorldSourceRegistered,
    LedgerEventType.world_update_ingested:        WorldUpdateIngested,
    LedgerEventType.world_update_scored:          WorldUpdateScored,
    LedgerEventType.improvement_proposal_created: ImprovementProposalCreated,
}

_RISK_LEVELS = {r.value: r for r in RiskLevel}


def _coerce_risk(value: str | RiskLevel | None) -> RiskLevel | None:
    if value is None or isinstance(value, RiskLevel):
        return value
    return _RISK_LEVELS.get(str(value).strip().lower(), RiskLevel.low)


def build_awareness_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    node_id: str | None = None,
    edge_id: str | None = None,
    lesson_id: str | None = None,
    source_id: str | None = None,
    update_id: str | None = None,
    goal_id: str | None = None,
    skill_gap_id: str | None = None,
    skill_proposal_id: str | None = None,
    workspace_id: str | None = None,
    scope: str | None = None,
    execution_mode: str | None = None,
    outcome: str | None = None,
    risk_level: str | RiskLevel | None = "low",
    trust_level: str | None = None,
    relevance_score: float | None = None,
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("node_id", node_id),
        ("edge_id", edge_id),
        ("lesson_id", lesson_id),
        ("source_id", source_id),
        ("update_id", update_id),
        ("goal_id", goal_id),
        ("skill_gap_id", skill_gap_id),
        ("skill_proposal_id", skill_proposal_id),
        ("workspace_id", workspace_id),
        ("scope", scope),
        ("execution_mode", execution_mode),
        ("trust_level", trust_level),
        ("relevance_score", relevance_score),
    ):
        if value is not None:
            meta[key] = value
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or goal_id or node_id or task_id,
        outcome=outcome,
        risk_level=_coerce_risk(risk_level),
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
