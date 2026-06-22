"""
aria.awareness — V3.6 Work Memory Graph + World Awareness Engine.

A GOVERNED, fixture-first, advisory layer that lets ARIA remember its own WORK
(goals, decisions, failures, corrections, evidence, approvals, outcomes), distil
reusable LESSONS that always cite their source records, watch a small registry of
APPROVED external sources via deterministic FIXTURES (no live browsing/network), and
route high-signal improvements to the V3.5 skill-evolution path as PROPOSALS only.

Boundaries (V2/V3 preserved): the memory graph cannot approve actions, activate
skills, or prove current facts without evidence; world knowledge is advisory and NOT
company truth; improvement proposals stay unapproved (V3.5 owns approval/activation).

A SEPARATE package — importing it never drags in V1 LLM skills, and importing a V1
skill never loads this engine.
"""
from aria.awareness.consolidation import MIN_REPEAT, WorkHistoryConsolidator
from aria.awareness.models import (
    ConsolidationResult,
    ImprovementOrigin,
    ImprovementProposal,
    LessonApprovalStatus,
    NodeStatus,
    NodeType,
    RelationType,
    TrustLevel,
    UpdateStatus,
    WorkLesson,
    WorkMemoryEdge,
    WorkMemoryNode,
    WorldSource,
    WorldSourceType,
    WorldUpdate,
    default_trust_for,
)
from aria.awareness.service import AwarenessService, ImprovementBlocked
from aria.awareness.store import (
    AwarenessIntegrityError,
    AwarenessNotFound,
    AwarenessSecurityError,
    AwarenessStore,
)
from aria.awareness.world import (
    ARIA_TOPICS,
    assess,
    ingest_fixtures,
    register_default_sources,
    score_relevance,
)

__all__ = [
    "WorkHistoryConsolidator",
    "MIN_REPEAT",
    "AwarenessService",
    "ImprovementBlocked",
    "AwarenessStore",
    "AwarenessNotFound",
    "AwarenessSecurityError",
    "AwarenessIntegrityError",
    "register_default_sources",
    "ingest_fixtures",
    "score_relevance",
    "assess",
    "ARIA_TOPICS",
    "WorkMemoryNode",
    "WorkMemoryEdge",
    "WorkLesson",
    "NodeType",
    "RelationType",
    "NodeStatus",
    "LessonApprovalStatus",
    "WorldSource",
    "WorldSourceType",
    "WorldUpdate",
    "TrustLevel",
    "UpdateStatus",
    "default_trust_for",
    "ImprovementOrigin",
    "ImprovementProposal",
    "ConsolidationResult",
]
