"""
Evolution Integration Engine — Week 27

Governs the final step: integrating an approved+sandboxed proposal into production.

Contract:
  - Only proposals with status=approved AND is_ready_for_integration()=True proceed.
  - Non-dry-run integration requires a non-empty approval_request_id proving the
    caller obtained explicit T4 approval (not just a field set on the proposal).
  - A prior version is archived before integration begins.
  - If the artifact write fails, success=False and status is NOT updated to integrated.
  - rollback_available=True iff archival succeeded before integration attempt.
  - rollback() with a context will delete the integration artifact and restore the archive.
  - No LLM is involved — this is deterministic governance logic.

Security note:
  - proposal_id is sanitized before use in any file path (path traversal prevention).
    Sanitized form: only alphanumeric, hyphens, and underscores; max 128 chars.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from aria.evolution.models import (
    EvolutionProposal,
    IntegrationResult,
    ProposalStatus,
    utc_now,
)
from aria.evolution.store import ProposalStore


# ── Path safety ────────────────────────────────────────────────────────────────

_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9\-_]")
_MAX_ID_LEN = 128


def _safe_id(proposal_id: str) -> str:
    """
    Return a filesystem-safe version of proposal_id.
    Strips everything except alphanumerics, hyphens, underscores.
    Raises ValueError if the result would be empty.
    """
    safe = _SAFE_ID_RE.sub("_", proposal_id)[:_MAX_ID_LEN]
    if not safe.strip("_"):
        raise ValueError(f"proposal_id {proposal_id!r} produces an empty safe filename")
    return safe


# ── Context ────────────────────────────────────────────────────────────────────

@dataclass
class IntegrationContext:
    """
    Caller provides context needed to locate / write the integrated artifact.

    approval_request_id: Required for non-dry-run integration.
      Must be the request ID obtained from the T4 governance gate.
      An empty string or None blocks non-dry-run integration.

    dry_run: When True, no filesystem writes occur and approval_request_id
      is not required (safe for tests).
    """
    artifact_dir:        Optional[str] = None
    archive_dir:         Optional[str] = None
    dry_run:             bool = True
    approval_request_id: Optional[str] = None   # T4 gate token; required when dry_run=False


# ── Engine ─────────────────────────────────────────────────────────────────────

class IntegrationEngine:
    """Integrates approved proposals through the T4 approval gate."""

    def __init__(self, store: ProposalStore) -> None:
        self._store = store

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

        # T4 gate: non-dry-run requires an approval_request_id
        if not ctx.dry_run and not ctx.approval_request_id:
            return IntegrationResult(
                proposal_id=proposal_id,
                success=False,
                integrated_at=utc_now(),
                notes=(
                    "Integration blocked: approval_request_id is required for non-dry-run "
                    "integration. Obtain T4 approval via the governance gate first."
                ),
            )

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

        # Validate proposal_id is safe for use in filesystem paths
        try:
            safe_pid = _safe_id(proposal.proposal_id)
        except ValueError as exc:
            return IntegrationResult(
                proposal_id=proposal_id,
                success=False,
                integrated_at=utc_now(),
                notes=f"Integration blocked: {exc}",
            )

        # Archive prior version
        rollback_available = False
        if not ctx.dry_run and ctx.archive_dir:
            rollback_available = self._archive_prior(proposal, safe_pid, ctx.archive_dir)

        # Perform integration
        artifact_path: Optional[str] = None
        notes = ""
        success = True

        if ctx.dry_run:
            artifact_path = f"[dry_run]/{proposal.evolution_type.value}/{safe_pid}"
            notes = "dry_run=True — no filesystem changes made"
        else:
            artifact_path, notes = self._write_artifact(proposal, safe_pid, ctx)
            if artifact_path is None:
                # Write failed — do not mark as integrated
                success = False
                return IntegrationResult(
                    proposal_id=proposal_id,
                    success=False,
                    rollback_available=rollback_available,
                    integrated_at=utc_now(),
                    notes=notes,
                )

        # Only update status when integration actually succeeded
        updated = proposal.model_copy(update={"status": ProposalStatus.integrated})
        self._store.save(updated)

        return IntegrationResult(
            proposal_id=proposal_id,
            success=True,
            artifact_path=artifact_path,
            rollback_available=rollback_available,
            integrated_at=utc_now(),
            notes=notes,
        )

    def rollback(
        self,
        proposal_id: str,
        ctx: Optional[IntegrationContext] = None,
    ) -> bool:
        """
        Revert an integrated proposal to rolled_back status.

        When ctx is provided with archive_dir and artifact_dir (and dry_run=False):
          - Deletes the integration artifact from artifact_dir.
          - Restores the prior JSON from archive_dir if present.

        Returns True if the rollback was recorded; False if proposal not found
        or not in integrated status.
        """
        proposal = self._store.get(proposal_id)
        if proposal is None:
            return False
        if proposal.status != ProposalStatus.integrated:
            return False

        if ctx is not None and not ctx.dry_run:
            try:
                safe_pid = _safe_id(proposal.proposal_id)
            except ValueError:
                safe_pid = None

            if safe_pid:
                # Delete integration artifact
                if ctx.artifact_dir:
                    artifact_path = (
                        Path(ctx.artifact_dir) / proposal.evolution_type.value / f"{safe_pid}.json"
                    )
                    try:
                        artifact_path.unlink(missing_ok=True)
                    except OSError:
                        pass

                # Restore archive if present
                if ctx.archive_dir:
                    archive_path = Path(ctx.archive_dir) / f"{safe_pid}_prior.json"
                    if archive_path.exists() and ctx.artifact_dir:
                        restore_dir = Path(ctx.artifact_dir) / proposal.evolution_type.value
                        restore_dir.mkdir(parents=True, exist_ok=True)
                        try:
                            import shutil
                            shutil.copy2(archive_path, restore_dir / f"{safe_pid}.json")
                        except OSError:
                            pass

        updated = proposal.model_copy(update={"status": ProposalStatus.rolled_back})
        self._store.save(updated)
        return True

    # ── Internals ──────────────────────────────────────────────────────────────

    def _archive_prior(
        self,
        proposal: EvolutionProposal,
        safe_pid: str,
        archive_dir: str,
    ) -> bool:
        """Archive the prior artifact (if any). Returns True on success."""
        try:
            adir = Path(archive_dir)
            adir.mkdir(parents=True, exist_ok=True)
            archive_path = adir / f"{safe_pid}_prior.json"
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
        safe_pid: str,
        ctx: IntegrationContext,
    ) -> tuple[Optional[str], str]:
        """Write a JSON manifest of the proposal as the integration artifact."""
        if not ctx.artifact_dir:
            return None, "artifact_dir not set — artifact not written"

        try:
            adir = Path(ctx.artifact_dir) / proposal.evolution_type.value
            adir.mkdir(parents=True, exist_ok=True)
            artifact_path = adir / f"{safe_pid}.json"
            artifact_path.write_text(
                json.dumps(proposal.model_dump(), indent=2, default=str),
                encoding="utf-8",
            )
            return str(artifact_path), "artifact written successfully"
        except (OSError, TypeError) as exc:
            return None, f"artifact write failed: {exc}"
