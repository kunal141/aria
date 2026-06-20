"""
Typed models for V3.6 — Work Memory Graph + World Awareness.

A GOVERNED, fixture-first, advisory memory/awareness layer. The memory graph
remembers WORK (goals, decisions, failures, corrections, evidence, approvals,
outcomes) and distils reusable LESSONS — but it is advisory/contextual only:
it cannot approve actions, activate skills, or prove current facts without
evidence. World awareness is fixture-only (no live browsing/network).

All models are frozen Pydantic (immutable records).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Work memory graph ────────────────────────────────────────────────────────


class NodeType(str, Enum):
    goal_pattern = "goal_pattern"
    task_pattern = "task_pattern"
    failure_pattern = "failure_pattern"
    quality_pattern = "quality_pattern"
    evidence_pattern = "evidence_pattern"
    correction_pattern = "correction_pattern"
    skill_pattern = "skill_pattern"
    decision_pattern = "decision_pattern"
    roi_pattern = "roi_pattern"
    lesson = "lesson"


class RelationType(str, Enum):
    caused_by = "caused_by"
    improved_by = "improved_by"
    blocked_by = "blocked_by"
    requires_evidence = "requires_evidence"
    uses_memory = "uses_memory"
    produced_skill_gap = "produced_skill_gap"
    resolved_by_skill = "resolved_by_skill"
    repeated_in = "repeated_in"
    approved_by = "approved_by"
    superseded_by = "superseded_by"


class NodeStatus(str, Enum):
    active = "active"
    disabled = "disabled"
    redacted = "redacted"
    superseded = "superseded"


class LessonApprovalStatus(str, Enum):
    pending = "pending"          # generated, not yet human-reviewed
    approved = "approved"
    disabled = "disabled"
    superseded = "superseded"


class WorkMemoryNode(BaseModel):
    """A source-linked node in the work-memory graph. Must link back to records."""
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_type: NodeType
    title: str
    summary: str
    source_refs: list[str] = Field(default_factory=list)
    goal_ids: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    agent_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    workspace_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    status: NodeStatus = NodeStatus.active
    created_at: datetime
    updated_at: datetime


class WorkMemoryEdge(BaseModel):
    """A typed dependency between two nodes (organises history, not flat text)."""
    model_config = ConfigDict(frozen=True)

    edge_id: str
    from_node_id: str
    to_node_id: str
    relation_type: RelationType
    source_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    created_at: datetime


class WorkLesson(BaseModel):
    """A reusable lesson distilled from repeated patterns. NEVER orphan (must cite
    source nodes), advisory only, and cannot prove current facts."""
    model_config = ConfigDict(frozen=True)

    lesson_id: str
    title: str
    lesson: str
    applies_to: list[str] = Field(default_factory=list)
    source_node_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    recommended_use: str = ""
    approval_status: LessonApprovalStatus = LessonApprovalStatus.pending
    status: NodeStatus = NodeStatus.active
    created_at: datetime
    updated_at: datetime

    @property
    def is_usable(self) -> bool:
        """A lesson informs future recommendations only while active + not disabled."""
        return self.status is NodeStatus.active and \
            self.approval_status not in (LessonApprovalStatus.disabled, LessonApprovalStatus.superseded)


# ── World awareness ──────────────────────────────────────────────────────────


class WorldSourceType(str, Enum):
    official_doc = "official_doc"
    blog = "blog"
    research_paper = "research_paper"
    security_advisory = "security_advisory"
    release_note = "release_note"
    industry_news = "industry_news"


class TrustLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class UpdateStatus(str, Enum):
    ingested = "ingested"
    scored = "scored"
    escalated = "escalated"          # high-risk → human review
    dismissed = "dismissed"


# Official/first-party sources are trusted more than blogs / industry news.
_SOURCE_TRUST: dict[WorldSourceType, TrustLevel] = {
    WorldSourceType.official_doc: TrustLevel.high,
    WorldSourceType.release_note: TrustLevel.high,
    WorldSourceType.security_advisory: TrustLevel.high,
    WorldSourceType.research_paper: TrustLevel.medium,
    WorldSourceType.blog: TrustLevel.low,
    WorldSourceType.industry_news: TrustLevel.low,
}


def default_trust_for(source_type: WorldSourceType) -> TrustLevel:
    return _SOURCE_TRUST.get(source_type, TrustLevel.low)


class WorldSource(BaseModel):
    """A registered external awareness source. FIXTURE-ONLY — never fetched live."""
    model_config = ConfigDict(frozen=True)

    source_id: str
    name: str
    source_type: WorldSourceType
    url: str = ""
    allowed: bool = True
    trust_level: TrustLevel = TrustLevel.low
    topic_tags: list[str] = Field(default_factory=list)
    last_checked_at: datetime | None = None
    policy_notes: str = ""
    created_at: datetime


class WorldUpdate(BaseModel):
    """A fixture world update. Must carry a source citation. World knowledge is NOT
    company truth — it can only inform advisory recommendations."""
    model_config = ConfigDict(frozen=True)

    update_id: str
    source_id: str
    title: str
    summary: str
    published_at: datetime | None = None
    captured_at: datetime
    source_url: str = ""
    citations: list[str] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    trust_level: TrustLevel = TrustLevel.low
    relevance_score: float = 0.0
    risk_level: str = "low"
    status: UpdateStatus = UpdateStatus.ingested
    recommendation: str = ""

    @property
    def can_change_roadmap(self) -> bool:
        """Low-trust updates may NOT directly change roadmap/skills — advisory only."""
        return self.trust_level is TrustLevel.high


# ── Improvement routing (to V3.5) ────────────────────────────────────────────


class ImprovementOrigin(str, Enum):
    work_memory = "work_memory"
    world_update = "world_update"


class ImprovementProposal(BaseModel):
    """An improvement opportunity routed to the V3.5 skill-evolution path. It always
    links back to its source and stays UNAPPROVED (V3.5 owns approval/activation)."""
    model_config = ConfigDict(frozen=True)

    proposal_id: str
    origin_type: ImprovementOrigin
    origin_ref: str                  # node_id or update_id
    title: str
    description: str
    source_refs: list[str] = Field(default_factory=list)
    skill_gap_id: str | None = None
    skill_proposal_id: str | None = None
    relevance_score: float = 0.0
    risk_level: str = "low"
    status: str = "pending"          # pending — never auto-approved here
    created_at: datetime


class ConsolidationResult(BaseModel):
    """Summary of one consolidation pass."""
    model_config = ConfigDict(frozen=True)

    goal_id: str
    nodes: list[WorkMemoryNode] = Field(default_factory=list)
    edges: list[WorkMemoryEdge] = Field(default_factory=list)
    lessons: list[WorkLesson] = Field(default_factory=list)
    boundary_note: str = (
        "Advisory work-memory only. It cannot approve actions, activate skills, or "
        "prove current facts without evidence."
    )

    def as_summary(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "node_ids": [n.node_id for n in self.nodes],
            "edge_ids": [e.edge_id for e in self.edges],
            "lesson_ids": [l.lesson_id for l in self.lessons],
        }
