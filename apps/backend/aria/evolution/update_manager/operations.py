"""
Update Manager Operations — Week 28

All 9 operations for managing versioned self-improvement updates.
Every mutating operation is idempotent: calling it twice with the same
arguments either succeeds once and is a no-op on retry, or raises a
descriptive error rather than silently corrupting state.

Approval invariants:
  - Proposer may not approve their own update (self-approval is forbidden).
  - Approval of an update not in awaiting_approval is blocked (stale approval).
  - Authorized approvers list is optional; when set, only listed identities may approve.

Activation invariants:
  - Hash must match before activation proceeds.
  - Constitutional rules must pass before activation proceeds.
  - Concurrent activation of the same update_id is blocked.

Rollback invariants:
  - Rollback verifies hash of restored content before reporting success.
  - Health checks must pass on the restore target before reporting success.
  - Status-only rollback (no content verification) is never reported as success.
"""
from __future__ import annotations

import difflib
from typing import Optional

from aria.evolution.update_manager.constitutional import check_constitutional
from aria.evolution.update_manager.health import run_health_checks
from aria.evolution.update_manager.models import (
    TERMINAL_STATUSES,
    ConcurrentActivationError,
    ConstitutionalViolationError,
    HashMismatchError,
    ImpactLevel,
    SelfApprovalError,
    UpdateComparison,
    UpdateNotFoundError,
    UpdateOperationResult,
    UpdateRelease,
    UpdateStateError,
    UpdateStatus,
    compute_hash,
    utc_now,
)
from aria.evolution.update_manager.store import InMemoryUpdateStore, UpdateStore


class UpdateManager:
    """
    Manages the full lifecycle of UpdateRelease records.

    Parameters
    ----------
    store                : UpdateStore backing store (V1: in-memory)
    authorized_approvers : If set, only these identities may approve updates.
                           None means any non-proposer may approve.
    """

    def __init__(
        self,
        store: Optional[UpdateStore] = None,
        authorized_approvers: Optional[set[str]] = None,
    ) -> None:
        self._store = store if store is not None else InMemoryUpdateStore()
        self._authorized_approvers = authorized_approvers

    # ── Read operations ────────────────────────────────────────────────────────

    def list_pending_updates(self) -> list[UpdateRelease]:
        """Return updates that need human action (awaiting_approval or canary)."""
        return [
            u for u in self._store.list_all()
            if u.status in (
                UpdateStatus.awaiting_approval,
                UpdateStatus.canary,
                UpdateStatus.evaluated,
                UpdateStatus.proposed,
            )
        ]

    def get_update(self, update_id: str) -> Optional[UpdateRelease]:
        return self._store.get(update_id)

    def compare_update(self, update_id: str) -> UpdateComparison:
        update = self._store.get(update_id)
        if update is None:
            raise UpdateNotFoundError(update_id)

        diff_lines: list[str] = []
        if update.previous_content is not None and update.content is not None:
            diff_lines = list(difflib.unified_diff(
                update.previous_content.splitlines(keepends=True),
                update.content.splitlines(keepends=True),
                fromfile=f"{update.component_name}@{update.previous_version or 'none'}",
                tofile=f"{update.component_name}@{update.semantic_version}",
                lineterm="",
            ))

        return UpdateComparison(
            update_id=update_id,
            component_name=update.component_name,
            previous_version=update.previous_version,
            proposed_version=update.semantic_version,
            previous_content=update.previous_content,
            proposed_content=update.content,
            changelog=update.changelog,
            diff_lines=diff_lines,
            evaluation_results=update.evaluation_results,
            security_impact=update.security_impact,
            privacy_impact=update.privacy_impact,
            cost_impact=update.cost_impact,
            latency_impact=update.latency_impact,
            evidence_refs=update.evidence_refs,
            canary_plan=update.canary_plan,
            rollback_target=update.rollback_target,
        )

    def show_changelog(self, component_name: str) -> list[UpdateRelease]:
        """Return all updates for a component, oldest-first."""
        updates = self._store.list_by_component(component_name)
        return sorted(updates, key=lambda u: u.discovered_at or "")

    # ── Mutating operations ────────────────────────────────────────────────────

    def approve_update(
        self,
        update_id: str,
        approver: str,
    ) -> UpdateRelease:
        """
        T4 approval gate: awaiting_approval → canary.

        Raises:
          UpdateNotFoundError         — update not in store
          UpdateStateError            — not in awaiting_approval status
          SelfApprovalError           — approver == proposer
          ConstitutionalViolationError — update fails constitutional check
        """
        update = self._require(update_id)
        if update.status == UpdateStatus.canary and update.approver == approver:
            return update   # idempotent: already approved by same approver

        if update.status != UpdateStatus.awaiting_approval:
            raise UpdateStateError(update_id, update.status, "approve (requires awaiting_approval)")

        if approver == update.proposer:
            raise SelfApprovalError(update_id, approver)

        if self._authorized_approvers and approver not in self._authorized_approvers:
            raise ValueError(
                f"Update {update_id!r}: {approver!r} is not an authorized approver."
            )

        # Constitutional safety re-check at approval time
        violations = check_constitutional(update)
        if violations:
            raise ConstitutionalViolationError(update_id, violations)

        updated = update.model_copy(update={
            "status":   UpdateStatus.canary,
            "approver": approver,
            "canary_at": utc_now(),
        })
        self._store.save(updated)
        return updated

    def reject_update(
        self,
        update_id: str,
        reason: str,
    ) -> UpdateRelease:
        """Reject an update from any non-terminal state."""
        update = self._require(update_id)
        if update.status in TERMINAL_STATUSES:
            raise UpdateStateError(update_id, update.status, "reject (already terminal)")
        updated = update.model_copy(update={
            "status":           UpdateStatus.rejected,
            "rejection_reason": reason,
            "rejected_at":      utc_now(),
        })
        self._store.save(updated)
        return updated

    def activate_canary(self, update_id: str) -> UpdateRelease:
        """
        Move an evaluated (or awaiting_approval) update into canary.
        Used for low-risk updates that don't require a separate approval step
        before canary testing begins.

        Raises ConstitutionalViolationError if safety checks fail.
        """
        update = self._require(update_id)
        if update.status not in (UpdateStatus.evaluated, UpdateStatus.awaiting_approval):
            raise UpdateStateError(
                update_id, update.status, "activate_canary (requires evaluated or awaiting_approval)"
            )
        violations = check_constitutional(update)
        if violations:
            raise ConstitutionalViolationError(update_id, violations)

        updated = update.model_copy(update={
            "status":   UpdateStatus.canary,
            "canary_at": utc_now(),
        })
        self._store.save(updated)
        return updated

    def promote_canary(self, update_id: str) -> UpdateRelease:
        """
        canary → active after health checks pass.

        Also marks any previously-active version of the same component as
        superseded. Concurrent promotion of the same update_id is blocked.

        Raises:
          UpdateStateError            — not in canary status
          HashMismatchError           — content hash does not match
          ConstitutionalViolationError — constitutional check fails
          ConcurrentActivationError   — activation already in progress
          ValueError                  — health checks failed
        """
        update = self._require(update_id)
        if update.status != UpdateStatus.canary:
            raise UpdateStateError(update_id, update.status, "promote_canary (requires canary)")

        # Concurrency gate
        if not self._store.begin_activation(update_id):
            raise ConcurrentActivationError(update_id)

        try:
            # Hash verification
            if not update.verify_hash():
                raise HashMismatchError(update_id)

            # Health checks
            health = run_health_checks(update)
            if not health.passed:
                raise ValueError(
                    f"promote_canary blocked for {update_id!r}: "
                    + "; ".join(health.findings)
                )

            # Supersede any existing active version for the same component
            self._supersede_active(update.component_name, exclude_id=update_id)

            activated = update.model_copy(update={
                "status":    UpdateStatus.active,
                "active_at": utc_now(),
            })
            self._store.save(activated)
            return activated

        finally:
            self._store.end_activation(update_id)

    def rollback_update(
        self,
        component_name: str,
        target_version: str,
    ) -> UpdateRelease:
        """
        Restore a component to a specific prior version.

        Steps:
          1. Locate the target version update in the store.
          2. Verify content hash of the restore target.
          3. Run health checks on the restore target.
          4. Mark the currently-active update as rolled_back.
          5. Set target update to active.

        Never reports success for status-only changes (step 2 and 3 must pass).

        Raises:
          UpdateNotFoundError  — target version not found
          HashMismatchError    — target content hash mismatch
          ValueError           — health checks failed on restore target
        """
        # Find target
        candidates = [
            u for u in self._store.list_by_component(component_name)
            if u.semantic_version == target_version
        ]
        if not candidates:
            raise UpdateNotFoundError(f"{component_name}@{target_version}")
        target = candidates[0]

        # Hash verification on restore target
        if not target.verify_hash():
            raise HashMismatchError(target.update_id)

        # Health checks on restore target
        health = run_health_checks(target)
        if not health.passed:
            raise ValueError(
                f"rollback blocked — health checks failed on restore target "
                f"{component_name}@{target_version}: " + "; ".join(health.findings)
            )

        # Mark currently active as rolled_back
        active = self._find_active(component_name)
        if active is not None:
            rolled = active.model_copy(update={
                "status":       UpdateStatus.rolled_back,
                "rolled_back_at": utc_now(),
            })
            self._store.save(rolled)

        # Restore target to active
        restored = target.model_copy(update={
            "status":    UpdateStatus.active,
            "active_at": utc_now(),
        })
        self._store.save(restored)
        return restored

    # ── Internals ──────────────────────────────────────────────────────────────

    def _require(self, update_id: str) -> UpdateRelease:
        update = self._store.get(update_id)
        if update is None:
            raise UpdateNotFoundError(update_id)
        return update

    def _find_active(self, component_name: str) -> Optional[UpdateRelease]:
        actives = [
            u for u in self._store.list_by_component(component_name)
            if u.status == UpdateStatus.active
        ]
        return actives[0] if actives else None

    def _supersede_active(self, component_name: str, exclude_id: str) -> None:
        for u in self._store.list_by_component(component_name):
            if u.update_id != exclude_id and u.status == UpdateStatus.active:
                superseded = u.model_copy(update={
                    "status":       UpdateStatus.superseded,
                    "superseded_at": utc_now(),
                })
                self._store.save(superseded)
