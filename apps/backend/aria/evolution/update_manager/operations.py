"""
Update Manager Operations — Week 28

All operations for managing versioned self-improvement updates.

Concurrency model
-----------------
Every component lifecycle mutation (promote_canary, rollback_update) acquires
the store's component-level lock BEFORE reading active releases, rollback
targets, or artifact state, and releases it in a finally block. Operations on
the same component serialize; operations on different components run in
parallel.

Source of truth
---------------
The runtime authority for a component is the immutable versioned artifact file
on disk, written under ``deployments/<update_id><suffix>`` and named by the
update_id (never reused). The active store record's ``artifact_path`` and
``content_hash`` are committed AFTER the artifact has been written and hash-
verified. Consumers (see ``aria.evolution.component_loader.load``) MUST read
the artifact from disk and re-verify its hash; ``UpdateRelease.content`` is
proposal data and is never silently substituted for an invalid artifact.

Activation invariants:
  - Hash verified before activation proceeds.
  - Constitutional rules pass before activation proceeds.
  - Concurrent operations on the same component are blocked (component lock).
  - save_batch enforces at-most-one-active-release per component atomically.

Rollback invariants:
  - Same component lock as promotion.
  - Restore-target hash verified before any disk write.
  - Same versioned-artifact design; existing target artifact is reused only
    after hash verification — never silently overwritten with different bytes.
  - Status-only rollback (no content verification) is never reported as success.
"""
from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Optional


# Update IDs must be filename-safe: ASCII alphanumerics, dot, dash, underscore
# ONLY. No path separators, no parent-traversal segments, no quote/control
# characters. Validated before being concatenated into a versioned artifact
# path so a hostile or malformed update_id cannot escape the deployment root.
_VALID_UPDATE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_update_id(update_id: str) -> None:
    """Reject update IDs that are not filename-safe or contain traversal segments."""
    if not update_id or not _VALID_UPDATE_ID_RE.match(update_id):
        raise ValueError(
            f"update_id {update_id!r} is not filename-safe; only "
            "[A-Za-z0-9._-]+ is permitted."
        )
    if ".." in update_id.split("."):
        # Defense against "..", "...", "..foo" tokens slipping through.
        raise ValueError(
            f"update_id {update_id!r} contains a parent-traversal segment."
        )

# Deployment root for path confinement. Active by default: artifact writes must
# land beneath apps/backend/deployments/ relative to this package. Production
# callers may override via configure_deployment_root() or by assigning directly.
DEPLOYMENT_ROOT: Optional[Path] = Path(__file__).parent.parent.parent.parent / "deployments"


def configure_deployment_root(path: Optional[Path]) -> None:
    """Override the module-level deployment root at process startup or in tests."""
    global DEPLOYMENT_ROOT
    DEPLOYMENT_ROOT = path


def _confined_path(path_str: str, root: Optional[Path] = None) -> Path:
    """
    Resolve ``path_str`` and verify it is strictly beneath ``root``.

    Uses ``Path.resolve()`` + ``Path.relative_to()`` so ``..`` traversal,
    Windows/Unix mixed separators, and symlinks that escape the root are all
    caught before any filesystem operation.

    Raises
    ------
    ValueError
        When the resolved path is not under the effective root.
    """
    effective_root = root if root is not None else DEPLOYMENT_ROOT
    if effective_root is None:
        return Path(path_str)  # no confinement configured

    resolved = Path(path_str).resolve()
    root_resolved = effective_root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(
            f"Deployment path {path_str!r} resolves to {resolved}, "
            f"which is outside deployment root {root_resolved}."
        )
    return resolved


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


def _log(event_type_str: str, **kwargs) -> None:
    """Best-effort ledger event; never raises so it never blocks operations."""
    try:
        from aria.work_ledger import EvolutionEventType, EvolutionLedgerEvent, log_evolution_event
        log_evolution_event(EvolutionLedgerEvent(
            event_type=EvolutionEventType(event_type_str),
            **kwargs,
        ))
    except Exception:
        pass


def _write_artifact_atomic(
    path_str: str,
    content: str,
    deployment_root: Optional[Path] = None,
) -> None:
    """
    Atomically write content to path via tmp + os.replace (crash-safe).

    Path confinement is enforced whenever a root is known: the explicit
    ``deployment_root`` kwarg takes precedence, then the module-level
    ``DEPLOYMENT_ROOT`` global is used as a fallback.  Raises ``ValueError``
    for out-of-root paths.
    """
    effective_root = deployment_root if deployment_root is not None else DEPLOYMENT_ROOT
    if effective_root is not None:
        path = _confined_path(path_str, root=effective_root)
    else:
        path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _verify_artifact(path_str: str, expected_hash: str) -> bool:
    """Read the file at path_str and verify its SHA-256 matches expected_hash."""
    try:
        content = Path(path_str).read_text(encoding="utf-8")
        return compute_hash(content) == expected_hash
    except Exception:
        return False


def _versioned_artifact_path(
    artifact_path_str: str,
    update_id: str,
    deployment_root: Optional[Path],
    module_root: Optional[Path],
) -> Path:
    """
    Resolve the immutable versioned path for ``update_id``: a sibling of the
    declared artifact path, named ``<update_id><suffix>``.

    Defence-in-depth against path escape:
      1. ``update_id`` is validated to be filename-safe (alphanumeric, dot,
         dash, underscore) and contain no parent-traversal segments.
      2. The declared ``artifact_path_str`` is confined against the
         deployment root.
      3. The DERIVED versioned path (with ``update_id`` appended) is
         RE-CONFINED — even if ``update_id`` somehow contained a traversal
         segment that slipped past step 1, the final path is verified to
         resolve strictly inside the deployment root before any
         ``exists()``, read, or write touches the filesystem.
    """
    _validate_update_id(update_id)
    effective_root = deployment_root if deployment_root is not None else module_root
    confined_final = (
        _confined_path(artifact_path_str, root=effective_root)
        if effective_root is not None
        else Path(artifact_path_str)
    )
    derived = confined_final.parent / (update_id + confined_final.suffix)
    # Re-confine the FINAL derived path. Without this, an update_id that
    # somehow embedded a separator could escape the root via the join.
    if effective_root is not None:
        return _confined_path(str(derived), root=effective_root)
    return derived


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
        deployment_root: Optional[Path] = None,
    ) -> None:
        self._store = store if store is not None else InMemoryUpdateStore()
        self._authorized_approvers = authorized_approvers
        # None → resolved at write time from the module-level DEPLOYMENT_ROOT global.
        # Pass an explicit path to confine writes to a different root (e.g. tmp_path in tests).
        self._deployment_root = deployment_root

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
        _log(
            "approval",
            task_id=update_id,
            update_id=update_id,
            component_name=updated.component_name,
            version=updated.semantic_version,
            actor=approver,
            outcome="approved_canary",
        )
        _log(
            "canary",
            task_id=update_id,
            update_id=update_id,
            component_name=updated.component_name,
            version=updated.semantic_version,
            actor=approver,
            outcome="canary_started",
        )
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
        _log(
            "failure",
            task_id=update_id,
            update_id=update_id,
            component_name=updated.component_name,
            version=updated.semantic_version,
            outcome="rejected",
            detail=reason,
        )
        return updated

    def activate_canary(self, update_id: str, approver: str) -> UpdateRelease:
        """
        Approve an awaiting_approval update and start canary deployment.

        Every path to canary requires human approval — there is no approval-free
        fast-track regardless of risk level. Delegates to approve_update so all
        guards (self-approval, authorized_approvers, constitutional) apply.

        Raises:
          UpdateStateError            — not in awaiting_approval status
          SelfApprovalError           — approver == proposer
          ValueError                  — approver not in authorized_approvers list
          ConstitutionalViolationError — constitutional check fails
        """
        return self.approve_update(update_id, approver=approver)

    def promote_canary(self, update_id: str) -> UpdateRelease:
        """
        canary → active after health checks pass.

        Concurrency: acquires the component lock BEFORE reading active releases
        or any artifact state. Concurrent operations on the same component —
        whether two promotions, a promotion and a rollback, or two rollbacks —
        serialize on this lock. Operations on different components run in
        parallel.

        Also marks any previously-active version of the same component as
        superseded — all transitions are committed atomically in a single
        save_batch call, which the store rejects if it would result in more
        than one active release per component.

        Raises:
          UpdateStateError              — not in canary status
          HashMismatchError             — content hash does not match
          ConstitutionalViolationError  — constitutional check fails
          ConcurrentActivationError     — component lock already held
          ValueError                    — health checks failed / path outside root
          MultipleActiveReleasesError   — store invariant violated
        """
        # Initial lookup just to identify the component_name. The lock — not
        # this read — is the correctness boundary; all governed reads happen
        # under the lock below.
        update_initial = self._require(update_id)
        component_name = update_initial.component_name

        if not self._store.acquire_component(component_name):
            raise ConcurrentActivationError(update_id)

        try:
            # ── Middle try: emit a failure ledger event for any exception in
            #    the governed block (hash, health, artifact, persistence).
            try:
                # Re-read state UNDER the lock. This is the canonical state.
                update = self._require(update_id)
                if update.status != UpdateStatus.canary:
                    raise UpdateStateError(
                        update_id, update.status, "promote_canary (requires canary)"
                    )

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

                _log(
                    "verification",
                    task_id=update_id,
                    update_id=update_id,
                    component_name=update.component_name,
                    version=update.semantic_version,
                    outcome="hash_ok_health_ok",
                )

                superseded = self._collect_superseded(component_name, exclude_id=update_id)
                activated = update.model_copy(update={
                    "status":    UpdateStatus.active,
                    "active_at": utc_now(),
                })

                # Inner: write the immutable versioned artifact, hash-verify
                # it, then commit the active store record with the versioned
                # path. save_batch is the LAST operation. If anything fails
                # before save_batch, the staged artifact is deleted; if
                # save_batch fails, the staged artifact is also deleted and
                # the in-memory store is restored.
                staged_path: Optional[Path] = None
                staged_was_pre_existing = False
                try:
                    if update.artifact_path and update.content is not None:
                        versioned = _versioned_artifact_path(
                            update.artifact_path,
                            update_id,
                            self._deployment_root,
                            DEPLOYMENT_ROOT,
                        )
                        # Immutable: if the versioned file already exists, it
                        # must already match content_hash. Never silently
                        # overwrite an existing immutable artifact.
                        if versioned.exists():
                            if not _verify_artifact(str(versioned), update.content_hash):
                                raise HashMismatchError(update_id)
                            staged_was_pre_existing = True
                            staged_path = None  # nothing to clean up; existing valid file
                        else:
                            _write_artifact_atomic(
                                str(versioned), update.content,
                                deployment_root=self._deployment_root,
                            )
                            staged_path = versioned
                            if not _verify_artifact(str(versioned), update.content_hash):
                                raise HashMismatchError(update_id)

                        activated = activated.model_copy(
                            update={"artifact_path": str(versioned)}
                        )

                    self._store.save_batch(superseded + [activated])
                    # Commit succeeded — the staged file (or pre-existing
                    # immutable file) is now the live artifact.
                    staged_path = None
                except Exception:
                    if staged_path is not None and not staged_was_pre_existing:
                        try:
                            staged_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    raise

                _log(
                    "promotion",
                    task_id=update_id,
                    update_id=update_id,
                    component_name=activated.component_name,
                    version=activated.semantic_version,
                    outcome="promoted_to_active",
                )
                _log(
                    "activation",
                    task_id=update_id,
                    update_id=update_id,
                    component_name=activated.component_name,
                    version=activated.semantic_version,
                    outcome="active",
                )
                return activated

            except Exception as exc:
                _log(
                    "failure",
                    task_id=update_id,
                    update_id=update_id,
                    component_name=component_name,
                    version=update_initial.semantic_version,
                    outcome="promotion_failed",
                    detail=str(exc),
                )
                raise

        finally:
            self._store.release_component(component_name)

    def rollback_update(
        self,
        component_name: str,
        target_version: str,
    ) -> UpdateRelease:
        """
        Restore a component to a specific prior version.

        Uses the SAME component lock as promote_canary, so promotion-vs-
        rollback and rollback-vs-rollback for one component serialize. Uses
        the SAME immutable versioned artifact design — the restore target's
        artifact is written to a path keyed by ``target.update_id`` (never
        reused across updates). If an existing artifact at that path already
        matches the target's content_hash, it is reused without rewrite; if
        it exists but mismatches, the operation fails closed.

        Never reports success for status-only changes — content presence,
        hash verification, and health checks must all pass.

        Raises:
          UpdateNotFoundError           — target version not found
          HashMismatchError             — content hash mismatch (in-memory or on-disk)
          ConcurrentActivationError     — component lock already held
          ValueError                    — content missing, health checks failed,
                                          or path outside deployment root
          MultipleActiveReleasesError   — store invariant violated
        """
        if not self._store.acquire_component(component_name):
            # No specific update_id to attribute the conflict to — surface the
            # first canary/active record for that component if any, else use
            # the requested target as the conflict identifier.
            existing = [
                u for u in self._store.list_by_component(component_name)
                if u.status in (UpdateStatus.canary, UpdateStatus.active)
            ]
            attribution = existing[0].update_id if existing else f"{component_name}@{target_version}"
            raise ConcurrentActivationError(attribution)

        try:
            # Find target UNDER the lock — canonical state.
            candidates = [
                u for u in self._store.list_by_component(component_name)
                if u.semantic_version == target_version
            ]
            if not candidates:
                raise UpdateNotFoundError(f"{component_name}@{target_version}")
            target = candidates[0]

            try:
                # Content must be present — status-only rollback is never sufficient.
                if not target.content:
                    raise ValueError(
                        f"rollback blocked — restore target {component_name}@{target_version} "
                        "has no content to restore (status-only record)"
                    )

                if not target.verify_hash():
                    raise HashMismatchError(target.update_id)

                health = run_health_checks(target)
                if not health.passed:
                    raise ValueError(
                        f"rollback blocked — health checks failed on restore target "
                        f"{component_name}@{target_version}: " + "; ".join(health.findings)
                    )

                # Build all state transitions.
                active = self._find_active(component_name)
                batch: list[UpdateRelease] = []
                if active is not None and active.update_id != target.update_id:
                    batch.append(active.model_copy(update={
                        "status":         UpdateStatus.rolled_back,
                        "rolled_back_at": utc_now(),
                    }))
                restored = target.model_copy(update={
                    "status":    UpdateStatus.active,
                    "active_at": utc_now(),
                })
                batch.append(restored)

                staged_path: Optional[Path] = None
                staged_was_pre_existing = False
                try:
                    if target.artifact_path and target.content is not None:
                        versioned = _versioned_artifact_path(
                            target.artifact_path,
                            target.update_id,
                            self._deployment_root,
                            DEPLOYMENT_ROOT,
                        )
                        if versioned.exists():
                            # Immutable: reuse only if hash matches; never overwrite
                            # an existing immutable artifact with different bytes.
                            if not _verify_artifact(str(versioned), target.content_hash):
                                raise HashMismatchError(target.update_id)
                            staged_was_pre_existing = True
                            staged_path = None
                        else:
                            _write_artifact_atomic(
                                str(versioned), target.content,
                                deployment_root=self._deployment_root,
                            )
                            staged_path = versioned
                            if not _verify_artifact(str(versioned), target.content_hash):
                                raise HashMismatchError(target.update_id)

                        restored = restored.model_copy(
                            update={"artifact_path": str(versioned)}
                        )
                        batch = [b for b in batch if b.update_id != restored.update_id]
                        batch.append(restored)

                    self._store.save_batch(batch)
                    staged_path = None
                except Exception:
                    if staged_path is not None and not staged_was_pre_existing:
                        try:
                            staged_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    raise

                _log(
                    "failure",
                    task_id=target.update_id,
                    update_id=target.update_id,
                    component_name=component_name,
                    version=target_version,
                    outcome="rollback",
                    detail=f"Restored {component_name} to v{target_version}",
                )
                return restored

            except Exception as exc:
                _log(
                    "failure",
                    task_id=target.update_id if 'target' in locals() else "",
                    update_id=target.update_id if 'target' in locals() else "",
                    component_name=component_name,
                    version=target_version,
                    outcome="rollback_failed",
                    detail=str(exc),
                )
                raise

        finally:
            self._store.release_component(component_name)

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

    def _collect_superseded(self, component_name: str, exclude_id: str) -> list[UpdateRelease]:
        """Return updated copies of any currently-active releases that should be superseded.
        Does NOT write to the store — callers include these in a save_batch call."""
        result = []
        for u in self._store.list_by_component(component_name):
            if u.update_id != exclude_id and u.status == UpdateStatus.active:
                result.append(u.model_copy(update={
                    "status":        UpdateStatus.superseded,
                    "superseded_at": utc_now(),
                }))
        return result
