"""
aria.skill_evolution — V3.5 Skill Evolution Engine.

A SEPARATE package from the V1 ``aria.skills`` LLM-skill implementations (so importing
a V1 skill never drags in this engine). Governed, approval-gated, documentation/
config-only skill lifecycle: detect repeated capability gaps → propose skill → spec →
test plan → evaluate → request approval → approve/reject → activate/deprecate/rollback.
NO live production code is created or modified; activation is a registry STATUS and is
reversible.
"""
from aria.skill_evolution.detector import MIN_REPEAT, SkillGapDetector
from aria.skill_evolution.generators import (
    READY_THRESHOLD,
    SAFE_THRESHOLD,
    evaluate_proposal,
    generate_spec,
    generate_test_plan,
)
from aria.skill_evolution.models import (
    FORBIDDEN_SKILL_TOOLS,
    GapSourceType,
    RecommendedDecision,
    SkillDecisionRecord,
    SkillEvaluation,
    SkillGap,
    SkillProposal,
    SkillProposalStatus,
    SkillSpec,
    SkillTestPlan,
)
from aria.skill_evolution.service import SkillEvolutionService
from aria.skill_evolution.store import (
    InvalidSkillTransition,
    SkillActivationDenied,
    SkillNotFound,
    SkillStore,
)

__all__ = [
    "SkillGapDetector",
    "MIN_REPEAT",
    "generate_spec",
    "generate_test_plan",
    "evaluate_proposal",
    "SAFE_THRESHOLD",
    "READY_THRESHOLD",
    "GapSourceType",
    "RecommendedDecision",
    "SkillGap",
    "SkillProposal",
    "SkillProposalStatus",
    "SkillSpec",
    "SkillTestPlan",
    "SkillEvaluation",
    "SkillDecisionRecord",
    "FORBIDDEN_SKILL_TOOLS",
    "SkillEvolutionService",
    "SkillStore",
    "SkillNotFound",
    "InvalidSkillTransition",
    "SkillActivationDenied",
]
