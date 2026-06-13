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
from pathlib import Path
from typing import Optional

from aria.evolution.debate import DebateEngine
from aria.evolution.models import (
    EvolutionProposal,
    ProposalStatus,
    utc_now,
)
from aria.evolution.sandbox import run_sandbox
from aria.evolution.store import InMemoryProposalStore, ProposalStore
from aria.evolution.update_manager.models import (
    UpdateRelease,
    UpdateStatus,
    compute_hash,
)
from aria.evolution.update_manager.store import InMemoryUpdateStore, UpdateStore
from aria.work_ledger import EvolutionEventType, EvolutionLedgerEvent, log_evolution_event


# Component identity is sourced from the evolvable-component registry
# (``aria.evolution.component_registry``). The pipeline uses
# ``EvolutionProposal.target_component`` to look up the registration and
# build the release; ``evolution_type`` is retained as proposal metadata
# but no longer drives component naming.


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
        log_evolution_event(EvolutionLedgerEvent(
            event_type=EvolutionEventType.proposal,
            task_id=proposal.proposal_id,
            proposal_id=proposal.proposal_id,
            component_name=proposal.target_component,
            actor=proposal.proposed_by,
            outcome="submitted",
        ))

        # ── Step 1: Debate ─────────────────────────────────────────────────────
        debate_result = self._debate.debate(proposal)
        proposal = proposal.model_copy(update={
            "debate_verdict": debate_result.verdict,
            "status": ProposalStatus.debate_complete,
        })
        self._proposal_store.save(proposal)

        log_evolution_event(EvolutionLedgerEvent(
            event_type=EvolutionEventType.generation,
            task_id=proposal.proposal_id,
            proposal_id=proposal.proposal_id,
            component_name=proposal.target_component,
            outcome=debate_result.verdict.recommendation,
            detail="; ".join(debate_result.verdict.pro_arguments[:2]),
        ))

        if debate_result.verdict.recommendation != "approve":
            proposal = proposal.model_copy(update={"status": ProposalStatus.rejected})
            self._proposal_store.save(proposal)
            log_evolution_event(EvolutionLedgerEvent(
                event_type=EvolutionEventType.failure,
                task_id=proposal.proposal_id,
                proposal_id=proposal.proposal_id,
                component_name=proposal.target_component,
                outcome="debate_rejected",
                detail="; ".join(debate_result.verdict.con_arguments[:2]),
            ))
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

        log_evolution_event(EvolutionLedgerEvent(
            event_type=EvolutionEventType.sandbox,
            task_id=proposal.proposal_id,
            proposal_id=proposal.proposal_id,
            component_name=proposal.target_component,
            outcome="passed" if sandbox_result.passed else "failed",
            detail="; ".join(sandbox_result.findings[:2]),
        ))

        if not sandbox_result.passed:
            log_evolution_event(EvolutionLedgerEvent(
                event_type=EvolutionEventType.failure,
                task_id=proposal.proposal_id,
                proposal_id=proposal.proposal_id,
                component_name=proposal.target_component,
                outcome="sandbox_failed",
                detail="; ".join(sandbox_result.findings[:2]),
            ))
            return PipelineResult(
                proposal=proposal,
                update=None,
                blocked_reason=(
                    "Sandbox failed: " + "; ".join(sandbox_result.findings[:2])
                ),
            )

        # ── Step 3: Create UpdateRelease ───────────────────────────────────────
        # Reject unknown / non-evolvable targets BEFORE building the release —
        # defence in depth on top of the model validator. A proposal whose
        # target_component is not registered cannot produce a deployable
        # artifact; surface a clear failure rather than silently building a
        # bogus release.
        from aria.evolution import component_registry
        from aria.evolution.update_manager import operations as _ops

        try:
            registration = component_registry.get_registration(proposal.target_component)
        except component_registry.UnknownComponentError as exc:
            return PipelineResult(
                proposal=proposal,
                update=None,
                blocked_reason=(
                    f"target_component {proposal.target_component!r} is not "
                    f"in the evolvable component registry: {exc}"
                ),
            )

        content = _build_content(proposal)
        content_hash = compute_hash(content)
        component_type = registration.component_type

        # Immutable update_id: encodes both proposal identity and version so
        # rescanning the same proposal at the same version is always idempotent.
        update_id = f"upd-{proposal.proposal_id[:16]}-v{current_version}"

        # ── Idempotency: never overwrite an existing release ───────────────────
        existing = self._update_store.get(update_id)
        if existing is not None:
            if existing.content_hash != content_hash:
                # Same ID but different content means the caller reused the
                # version string with changed content — require a version bump.
                raise ValueError(
                    f"Update {update_id!r} already exists with a different "
                    "content hash. Bump the semantic version to create a new "
                    "release rather than silently discarding the changed content."
                )
            # Same content hash → true duplicate scan; return existing unchanged.
            return PipelineResult(proposal=proposal, update=existing)

        component_name = proposal.target_component
        # Every production release gets a confined deployment artifact_path
        # so the runtime authority contract (component_loader reads from disk)
        # is never bypassed. The actual artifact write happens in
        # promote_canary at a versioned path keyed by update_id.
        deployment_root = (
            _ops.DEPLOYMENT_ROOT if _ops.DEPLOYMENT_ROOT is not None
            else Path("deployments")
        )
        artifact_path = component_registry.artifact_path_for(
            component_name, deployment_root
        )

        update = UpdateRelease(
            update_id=update_id,
            component_name=component_name,
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
            artifact_path=artifact_path,
            awaiting_approval_at=utc_now(),
            evaluated_at=utc_now(),
            canary_plan=(
                f"Deploy to 5% of traffic for 24h. "
                f"Monitor {proposal.evolution_type.value} quality metrics. "
                f"Promote if no regressions detected."
            ),
        )
        self._update_store.save(update)
        log_evolution_event(EvolutionLedgerEvent(
            event_type=EvolutionEventType.approval_request,
            task_id=proposal.proposal_id,
            proposal_id=proposal.proposal_id,
            update_id=update.update_id,
            component_name=update.component_name,
            version=update.semantic_version,
            actor=proposal.proposed_by,
            outcome="awaiting_approval",
        ))

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
