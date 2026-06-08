"""
Evolution Intelligence Models — Week 27

Typed contracts for ARIA's governed self-evolution system.
No business logic — only data structures.

Lifecycle: draft → debate → sandbox → approval → integration
           (or rejection / rollback at any stage)

Key invariants:
  - ARIA never modifies production behaviour without human approval at T4
  - EvolutionType.prompt is safest (risk_score cap 0.3); EvolutionType.agent is highest risk
  - DebateVerdict.recommendation is one of: approve | reject | defer
  - SandboxResult.passed=False → integration is blocked (no bypass)
  - IntegrationResult.rollback_available=True iff a prior version was archived
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


# ── Evolution taxonomy ────────────────────────────────────────────────────────

class EvolutionType(str, Enum):
    prompt     = "prompt"      # skill system prompt improvement
    skill      = "skill"       # new or upgraded skill capability
    workflow   = "workflow"    # recurring task pattern → automation
    agent      = "agent"       # new specialist agent
    memory     = "memory"      # memory layer improvement
    tool       = "tool"        # new external tool connector
    rag        = "rag"         # retrieval improvement (RAPTOR, GraphRAG, etc.)
    routing    = "routing"     # model routing / SLM classification improvement
    evaluation = "evaluation"  # better rubric or regression benchmark


# Risk ceilings per evolution type.
# Proposals whose risk_score exceeds their type's ceiling are auto-rejected at debate.
RISK_CEILING: dict[str, float] = {
    "prompt":     0.30,   # changing prompts is low-blast-radius
    "evaluation": 0.30,
    "routing":    0.40,
    "rag":        0.45,
    "memory":     0.50,
    "skill":      0.55,
    "workflow":   0.55,
    "tool":       0.65,
    "agent":      0.75,   # new agents have broadest potential impact
}


# ── Proposal status lifecycle ─────────────────────────────────────────────────

class ProposalStatus(str, Enum):
    draft           = "draft"            # created, not yet debated
    debate_pending  = "debate_pending"   # queued for AutoGen debate
    debate_complete = "debate_complete"  # verdict issued; awaiting sandbox
    sandbox_pending = "sandbox_pending"  # sandboxed evaluation in progress
    sandbox_passed  = "sandbox_passed"   # sandbox green; awaiting human approval
    sandbox_failed  = "sandbox_failed"   # sandbox red; requires fix before retry
    approved        = "approved"         # human approved via T4 gate
    rejected        = "rejected"         # debate / human rejected
    integrated      = "integrated"       # live in production
    rolled_back     = "rolled_back"      # integration reverted


# ── Debate models ─────────────────────────────────────────────────────────────

class DebateArgument(BaseModel):
    """A single turn from one agent in the debate."""
    agent:   Literal["ResearchAgent", "ScepticAgent", "ModeratorAgent"]
    round:   int        # 1-indexed
    content: str


class DebateVerdict(BaseModel):
    """
    Structured output from the ModeratorAgent.

    recommendation: "approve" | "reject" | "defer"
    conditions: requirements that must be met before the proposal may proceed;
                empty list when recommendation != "approve"
    """
    proposal_id:    str
    recommendation: Literal["approve", "reject", "defer"]
    confidence:     float          # 0.0–1.0
    pro_arguments:  list[str]
    con_arguments:  list[str]
    conditions:     list[str]      # met before integration is attempted
    transcript:     list[DebateArgument]
    debated_at:     str            # UTC ISO
    rounds:         int

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be 0.0–1.0, got {v}")
        return round(v, 3)


# ── Sandbox models ────────────────────────────────────────────────────────────

class SandboxResult(BaseModel):
    """
    Result of running the proposal through an isolated evaluation.

    passed=False → integration is BLOCKED regardless of approval status.
    findings: human-readable list of failures or warnings.
    """
    proposal_id:  str
    passed:       bool
    checks_run:   list[str]   # e.g. ["compile_check", "import_check", "golden_test"]
    findings:     list[str]   # empty when passed=True; errors/warnings when False
    evaluated_at: str         # UTC ISO


# ── Integration models ────────────────────────────────────────────────────────

class IntegrationResult(BaseModel):
    """
    Result of integrating an approved+sandboxed proposal into production.

    rollback_available=True iff a prior version was archived before integration.
    artifact_path: where the integrated artifact lives (Python module path, etc.)
    """
    proposal_id:        str
    success:            bool
    artifact_path:      Optional[str] = None
    rollback_available: bool = False
    integrated_at:      str            # UTC ISO
    notes:              str = ""


# ── Main proposal model ───────────────────────────────────────────────────────

class EvolutionProposal(BaseModel):
    """
    A capability upgrade proposal, with full lifecycle state.

    evidence: list of human-readable reasons why this is needed
              (e.g., "kpi_node had 0 supported claims in 8 of last 10 runs")
    risk_score: 0.0–1.0; must not exceed RISK_CEILING for the evolution_type
    proposed_by: who/what generated this proposal
      "monitor:work_ledger" | "monitor:paper_scan" | "human:<name>"
    """
    proposal_id:    str
    title:          str
    description:    str
    evolution_type: EvolutionType
    status:         ProposalStatus = ProposalStatus.draft
    evidence:       list[str]
    risk_score:     float              # 0.0–1.0
    expected_gain:  str                # human-readable improvement description
    proposed_at:    str                # UTC ISO
    proposed_by:    str

    # Filled as proposal progresses through lifecycle
    debate_verdict:  Optional[DebateVerdict]  = None
    sandbox_result:  Optional[SandboxResult]  = None
    approved_by:     Optional[str]            = None
    approved_at:     Optional[str]            = None
    integration:     Optional[IntegrationResult] = None

    @field_validator("risk_score")
    @classmethod
    def _risk_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"risk_score must be 0.0–1.0, got {v}")
        return round(v, 3)

    @field_validator("proposed_at")
    @classmethod
    def _parseable_utc(cls, v: str) -> str:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    def exceeds_risk_ceiling(self) -> bool:
        ceiling = RISK_CEILING.get(self.evolution_type.value, 1.0)
        return self.risk_score > ceiling

    def is_ready_for_integration(self) -> bool:
        """
        True only when: debate approved + sandbox passed + human approval recorded.
        All three gates must be green — no shortcuts.
        """
        return (
            self.debate_verdict is not None
            and self.debate_verdict.recommendation == "approve"
            and self.sandbox_result is not None
            and self.sandbox_result.passed
            and self.approved_by is not None
            and self.status == ProposalStatus.approved
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
