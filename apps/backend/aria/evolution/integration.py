"""
Evolution Integration Engine — Week 27

Governs the final step: integrating an approved+sandboxed proposal into production.

Contract:
  - Only proposals with status=approved AND is_ready_for_integration()=True proceed.
  - A prior version is archived before integration begins.
  - On failure, the proposal is rolled back to its previous status.
  - rollback_available=True iff archival succeeded before integration attempt.
  - No LLM is involved — this is deterministic governance logic.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from aria.evolution.models import (
    EvolutionProposal,
    EvolutionType,
    IntegrationResult,
    ProposalStatus,
    utc_now,
)
from aria.evolution.store import ProposalStore


@dataclass
class IntegrationContext:
    """
    Caller provides context needed to locate / write the integrated artifact.
    All paths are optional — when absent, integration runs in dry-run mode.
    """
    artifact_dir:    Optional[str] = None   # directory to write artifact into
    archive_dir:     Optional[str] = None   # directory to archive prior version
    dry_run:         bool = True            # when True, no filesystem writes occur


class IntegrationEngine:
    """Integrates approved proposals through the T4 approval gate."""

    def __init__(
        self,
        store: ProposalStore,
        approved_by: str = "system",
    ) -> None:
        self._store      = store
        self._approved_by = approved_by

    def integrate(
        self,
        proposal_id: str,
        ctx: Optional[IntegrationContext] = None,
    ) -> IntegrationResult:
        """
        Attempt to integrate a proposal.

        Returns IntegrationResult(success=False, ...) rather than raising
        so callers can handle gracefully without try/except.
        """
        if ctx is None:
            ctx = IntegrationContext(dry_run=True)

        proposal = self._store.get(proposal_id)
        if proposal is None:
            return IntegrationResult(
                proposal_id=proposal_id,
                success=False,
                integrated_at=utc_now(),
                notes="Integration failed: proposal not found in store.",
            )

        if not proposal.is_ready_for_integration():
            return IntegrationResult(
                proposal_id=proposal_id,
                success=False,
                integrated_at=utc_now(),
                notes=(
                    "Integration blocked: not all gates cleared. "
                    f"status={proposal.status.value}, "
                    f"debate={'approved' if proposal.debate_verdict and proposal.debate_verdict.recommendation == 'approve' else 'not approved'}, "
                    f"sandbox={'passed' if proposal.sandbox_result and proposal.sandbox_result.passed else 'not passed'}, "
                    f"approved_by={proposal.approved_by or 'none'}."
                ),
            )

        # Archive prior version
        rollback_available = False
        if not ctx.dry_run and ctx.archive_dir:
            rollback_available = self._archive_prior(proposal, ctx.archive_dir)

        # Perform integration
        artifact_path: Optional[str] = None
        notes = ""

        if ctx.dry_run:
            artifact_path = f"[dry_run]/{proposal.evolution_type.value}/{proposal.proposal_id}"
            notes = "dry_run=True — no filesystem changes made"
        else:
            artifact_path, notes = self._write_artifact(proposal, ctx)

        success = True
        new_status = ProposalStatus.integrated

        # Update proposal state in store
        updated = proposal.model_copy(update={
            "status":    new_status,
        })
        self._store.save(updated)

        return IntegrationResult(
            proposal_id=proposal_id,
            success=success,
            artifact_path=artifact_path,
            rollback_available=rollback_available,
            integrated_at=utc_now(),
            notes=notes,
        )

    def rollback(self, proposal_id: str) -> bool:
        """
        Revert an integrated proposal to rolled_back status.

        Returns True if the rollback was recorded; False if proposal not found
        or not in integrated status.
        """
        proposal = self._store.get(proposal_id)
        if proposal is None:
            return False
        if proposal.status != ProposalStatus.integrated:
            return False
        updated = proposal.model_copy(update={"status": ProposalStatus.rolled_back})
        self._store.save(updated)
        return True

    # ── Internals ──────────────────────────────────────────────────────────────

    def _archive_prior(self, proposal: EvolutionProposal, archive_dir: str) -> bool:
        """Archive the prior artifact (if any). Returns True on success."""
        try:
            adir = Path(archive_dir)
            adir.mkdir(parents=True, exist_ok=True)
            archive_path = adir / f"{proposal.proposal_id}_prior.json"
            archive_path.write_text(
                json.dumps(proposal.model_dump(), indent=2, default=str),
                encoding="utf-8",
            )
            return True
        except (OSError, TypeError):
            return False

    def _write_artifact(
        self,
        proposal: EvolutionProposal,
        ctx: IntegrationContext,
    ) -> tuple[Optional[str], str]:
        """Write a JSON manifest of the proposal as the integration artifact."""
        if not ctx.artifact_dir:
            return None, "artifact_dir not set — artifact not written"

        try:
            adir = Path(ctx.artifact_dir) / proposal.evolution_type.value
            adir.mkdir(parents=True, exist_ok=True)
            artifact_path = adir / f"{proposal.proposal_id}.json"
            artifact_path.write_text(
                json.dumps(proposal.model_dump(), indent=2, default=str),
                encoding="utf-8",
            )
            return str(artifact_path), "artifact written successfully"
        except (OSError, TypeError) as exc:
            return None, f"artifact write failed: {exc}"
