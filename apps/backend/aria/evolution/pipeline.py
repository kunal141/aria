"""
Proposal Pipeline — Week 28

Connects EvolutionMonitor → DebateEngine → run_sandbox → UpdateRelease.

The pipeline is the bridge between "capability gap discovered" and
"versioned update ready for T4 approval". It does not trigger approval;
it produces an UpdateRelease in awaiting_approval status and stops.

Design:
  - All steps are deterministic when llm_enabled=False (test-safe).
  - A failed debate or sandbox produces a rejected proposal — no UpdateRelease.
  - A passing pipeline produces both an updated EvolutionProposal (status=sandbox_passed)
    and a new UpdateRelease (status=awaiting_approval) ready for human review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from aria.evolution.debate import DebateEngine
from aria.evolution.models import (
    EvolutionProposal,
    EvolutionType,
    ProposalStatus,
    utc_now,
)
from aria.evolution.sandbox import run_sandbox
from aria.evolution.store import InMemoryProposalStore, ProposalStore
from aria.evolution.update_manager.models import (
    ComponentType,
    ImpactLevel,
    UpdateRelease,
    UpdateStatus,
    compute_hash,
)
from aria.evolution.update_manager.store import InMemoryUpdateStore, UpdateStore


# Map EvolutionType → ComponentType
_ETYPE_TO_COMPONENT: dict[EvolutionType, ComponentType] = {
    EvolutionType.prompt:     ComponentType.prompt,
    EvolutionType.skill:      ComponentType.skill,
    EvolutionType.workflow:   ComponentType.skill,
    EvolutionType.agent:      ComponentType.skill,
    EvolutionType.memory:     ComponentType.knowledge_ingestion,
    EvolutionType.tool:       ComponentType.skill,
    EvolutionType.rag:        ComponentType.retrieval_config,
    EvolutionType.routing:    ComponentType.routing_rule,
    EvolutionType.evaluation: ComponentType.evaluation_rubric,
}


@dataclass
class PipelineResult:
    proposal:      EvolutionProposal
    update:        Optional[UpdateRelease]    # None if pipeline was blocked
    blocked_reason: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.update is not None


class ProposalPipeline:
    """
    Runs an EvolutionProposal through debate → sandbox → UpdateRelease creation.

    Parameters
    ----------
    proposal_store : where proposals are persisted
    update_store   : where UpdateReleases are persisted
    llm_enabled    : False → use heuristic debate (test-safe)
    debate_rounds  : number of debate exchange rounds
    """

    def __init__(
        self,
        proposal_store: Optional[ProposalStore] = None,
        update_store:   Optional[UpdateStore]   = None,
        llm_enabled:    bool = False,
        debate_rounds:  int  = 2,
    ) -> None:
        self._proposal_store = proposal_store if proposal_store is not None else InMemoryProposalStore()
        self._update_store   = update_store   if update_store   is not None else InMemoryUpdateStore()
        self._debate         = DebateEngine(llm_enabled=llm_enabled, rounds=debate_rounds)

    def run(
        self,
        proposal: EvolutionProposal,
        current_version: str = "1.0.0",
        previous_content: Optional[str] = None,
    ) -> PipelineResult:
        """
        Run the full proposal → update pipeline.

        Parameters
        ----------
        proposal         : The draft EvolutionProposal to evaluate.
        current_version  : Semantic version to assign to the UpdateRelease.
        previous_content : Prior content of the component (for diff).

        Returns PipelineResult with update=None if blocked at debate or sandbox.
        """
        self._proposal_store.save(proposal)

        # ── Step 1: Debate ─────────────────────────────────────────────────────
        debate_result = self._debate.debate(proposal)
        proposal = proposal.model_copy(update={
            "debate_verdict": debate_result.verdict,
            "status": ProposalStatus.debate_complete,
        })
        self._proposal_store.save(proposal)

        if debate_result.verdict.recommendation != "approve":
            proposal = proposal.model_copy(update={"status": ProposalStatus.rejected})
            self._proposal_store.save(proposal)
            return PipelineResult(
                proposal=proposal,
                update=None,
                blocked_reason=(
                    f"Debate {debate_result.verdict.recommendation}: "
                    + "; ".join(debate_result.verdict.con_arguments[:2])
                ),
            )

        # ── Step 2: Sandbox ────────────────────────────────────────────────────
        sandbox_result = run_sandbox(proposal)
        status = (
            ProposalStatus.sandbox_passed
            if sandbox_result.passed
            else ProposalStatus.sandbox_failed
        )
        proposal = proposal.model_copy(update={
            "sandbox_result": sandbox_result,
            "status":         status,
        })
        self._proposal_store.save(proposal)

        if not sandbox_result.passed:
            return PipelineResult(
                proposal=proposal,
                update=None,
                blocked_reason=(
                    "Sandbox failed: " + "; ".join(sandbox_result.findings[:2])
                ),
            )

        # ── Step 3: Create UpdateRelease ───────────────────────────────────────
        content = _build_content(proposal)
        content_hash = compute_hash(content)
        component_type = _ETYPE_TO_COMPONENT.get(
            proposal.evolution_type, ComponentType.skill
        )

        update = UpdateRelease(
            update_id=f"upd-{proposal.proposal_id[:16]}",
            component_name=f"{proposal.evolution_type.value}_component",
            component_type=component_type,
            semantic_version=current_version,
            previous_version=None,
            rollback_target=None,
            content_hash=content_hash,
            changelog=proposal.expected_gain,
            evidence_refs=proposal.evidence,
            proposer=proposal.proposed_by,
            proposal_id=proposal.proposal_id,
            status=UpdateStatus.awaiting_approval,
            content=content,
            previous_content=previous_content,
            awaiting_approval_at=utc_now(),
            evaluated_at=utc_now(),
            canary_plan=(
                f"Deploy to 5% of traffic for 24h. "
                f"Monitor {proposal.evolution_type.value} quality metrics. "
                f"Promote if no regressions detected."
            ),
        )
        self._update_store.save(update)

        return PipelineResult(proposal=proposal, update=update)


def _build_content(proposal: EvolutionProposal) -> str:
    """Build the update content string from a proposal."""
    lines = [
        f"# {proposal.title}",
        f"",
        f"## Description",
        proposal.description,
        f"",
        f"## Evidence",
    ] + [f"- {e}" for e in proposal.evidence] + [
        f"",
        f"## Expected Gain",
        proposal.expected_gain,
        f"",
        f"## Evolution Type",
        proposal.evolution_type.value,
    ]
    return "\n".join(lines)
