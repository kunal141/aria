"""
Model Lifecycle Registry v1 — operations layer (Week 29 Priority 4).

``ModelRegistry`` drives a ``ModelRecord`` through its governed lifecycle:

    register → evaluate → request_approval → approve → (canary) → activate
                                          ↘ reject                ↘ deprecate / rollback

Governance guarantees enforced here (the model layer enforces structure; this
layer enforces process):

  - **Self-approval forbidden** — the creator can never approve their own model.
  - **No activation without evaluation** — a model with no recorded evaluation
    cannot be activated (``EvaluationRequiredError``).
  - **No activation without human approval** — ``ApprovalRequiredError``.
  - **At most one ACTIVE model per consumer** — activation supersedes the prior
    active version atomically; the store rejects any batch that would leave two
    active models for one consumer.
  - **Immutable version records** — lifecycle advances by ``model_copy`` +
    store replacement; records are never mutated in place.
  - **Path confinement + hash verification** — artifact paths must resolve
    beneath the configured artifact root, and a declared ``artifact_hash`` must
    match the bytes on disk.
  - **Consumer-level serialization** — activation / rollback / promotion /
    deprecation for one consumer serialize on a consumer lock; different
    consumers proceed in parallel.

Every transition emits a typed ``ModelLifecycleEvent`` to the Work Ledger v2
AFTER the store commit (the store is the source of truth; the ledger is the
audit trail). Per the Week-29 governance rule, NO credentials, raw confidential
content, or training examples are placed on the registry record or the ledger
event.

This module holds NO secrets and runs fully offline.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from aria.ledger.events import ActorType, ModelLifecycleEvent, make_envelope
from aria.model_registry.evaluator import EvaluationReport
from aria.model_registry.models import (
    ApprovalRequiredError,
    ArtifactHashMismatchError,
    ArtifactIntegrityError,
    ArtifactMissingError,
    ArtifactPathError,
    ConcurrentActivationError,
    DuplicateModelConflict,
    DuplicateVersionConflict,
    EvaluationRequiredError,
    ModelComparison,
    ModelNotFoundError,
    ModelRecord,
    ModelStateError,
    ModelStatus,
    SelfApprovalError,
    UnauthorizedApproverError,
    UnknownConsumerError,
    can_transition,
    compare_records,
    utc_now,
)
from aria.model_registry.store import InMemoryModelStore, ModelStore

logger = logging.getLogger("aria.model_registry")


class ModelRegistry:
    """
    Operations layer over a ``ModelStore``.

    Parameters
    ----------
    store
        Backing store (V1: in-memory, optionally file-backed).
    known_consumers
        If set, only these ``production_consumer`` values may be registered;
        an unknown consumer is rejected. ``None`` means any consumer is allowed.
    authorized_approvers
        If set, only these identities may approve models. ``None`` means any
        non-creator may approve.
    artifact_root
        If set, every declared ``artifact_path`` must resolve strictly beneath
        this directory. ``None`` disables confinement (not recommended in prod).
    writer
        Work Ledger v2 writer. ``None`` → the process default writer.
    audit_outbox_path
        Durable file into which any ledger-emission failure is appended (one
        JSON object per line) so an audit line is never lost silently. ``None``
        keeps the in-memory ``audit_failures`` record but writes no file.
    clock
        Injectable UTC clock for deterministic timestamps in tests.
    """

    def __init__(
        self,
        store: Optional[ModelStore] = None,
        *,
        known_consumers: Optional[set[str]] = None,
        authorized_approvers: Optional[set[str]] = None,
        artifact_root: Optional[Path] = None,
        writer: object = None,
        audit_outbox_path: Optional[Path | str] = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store if store is not None else InMemoryModelStore()
        self._known_consumers = known_consumers
        self._authorized_approvers = authorized_approvers
        self._artifact_root = Path(artifact_root) if artifact_root is not None else None
        self._writer = writer
        self._audit_outbox_path = (
            Path(audit_outbox_path) if audit_outbox_path is not None else None
        )
        self._audit_failures: list[dict] = []
        self._clock = clock

    @property
    def audit_failures(self) -> list[dict]:
        """
        Ledger-emission failures observed this process (defensive copy).

        A non-empty list means one or more lifecycle events could not be written
        to the Work Ledger. The store state is still correct (it committed before
        emission), but the audit trail has a known, recorded gap — never a silent
        one. Each entry is also appended to ``audit_outbox_path`` when configured.
        """
        return list(self._audit_failures)

    # ── Read operations ────────────────────────────────────────────────────────

    def get_active_model(self, production_consumer: str) -> Optional[ModelRecord]:
        """Return the single ACTIVE model for a consumer, or None."""
        actives = [
            r for r in self._store.list_by_consumer(production_consumer)
            if r.status == ModelStatus.active
        ]
        return actives[0] if actives else None

    def list_versions(self, production_consumer: Optional[str] = None) -> list[ModelRecord]:
        """All versions for a consumer (or every version), oldest-first."""
        records = (
            self._store.list_by_consumer(production_consumer)
            if production_consumer is not None
            else self._store.list_all()
        )
        return sorted(records, key=lambda r: (r.created_at, r.semantic_version))

    def compare_versions(self, model_id_a: str, model_id_b: str) -> ModelComparison:
        """Diff two model versions (b relative to a)."""
        return compare_records(self._require(model_id_a), self._require(model_id_b))

    # ── Mutating operations ────────────────────────────────────────────────────

    def register_model(self, record: ModelRecord, *, actor: Optional[str] = None) -> ModelRecord:
        """
        Register a new model version in ``registered`` status.

        Raises
        ------
        ModelStateError         — record is not in ``registered`` status
        UnknownConsumerError    — production_consumer not in known_consumers
        ArtifactPathError       — artifact_path escapes the artifact root (or no
                                  artifact_root is configured for a declared path)
        ArtifactMissingError    — declared artifact_path does not exist on disk
        ArtifactIntegrityError  — artifact_path/artifact_hash pairing is inconsistent
        ArtifactHashMismatchError — on-disk artifact bytes ≠ declared hash
        DuplicateModelConflict  — same model_id, different content
        DuplicateVersionConflict — (consumer, version) owned by another model_id
        """
        if record.status != ModelStatus.registered:
            raise ModelStateError(record.model_id, record.status, "register (requires 'registered' status)")

        if self._known_consumers is not None and record.production_consumer not in self._known_consumers:
            raise UnknownConsumerError(record.production_consumer)

        # Artifact confinement + integrity (fail closed when a path is declared).
        self._verify_artifact(record, stage="register")

        # Idempotency / conflict detection.
        existing = self._store.get(record.model_id)
        if existing is not None:
            if existing.identity_fingerprint() == record.identity_fingerprint():
                return existing  # idempotent re-registration; never downgrade lifecycle
            raise DuplicateModelConflict(record.model_id)

        # A semantic version maps to exactly one model_id per consumer.
        for other in self._store.list_by_consumer(record.production_consumer):
            if other.version_key() == record.version_key() and other.model_id != record.model_id:
                raise DuplicateVersionConflict(
                    record.production_consumer, record.semantic_version, other.model_id
                )

        self._store.save(record)
        self._emit(
            record,
            from_status=None,
            to_status=ModelStatus.registered.value,
            actor=actor or record.created_by,
            actor_type=ActorType.aria,
            outcome="registered",
        )
        return record

    def record_evaluation(
        self, model_id: str, report: EvaluationReport, *, actor: str = "aria"
    ) -> ModelRecord:
        """
        Attach an evaluation report: ``registered`` → ``evaluated``.

        The report must reference this model. Metrics are re-validated by the
        ``ModelRecord`` validator (finite numbers only), so a malformed report
        cannot smuggle NaN/inf into a record.
        """
        record = self._require(model_id)
        if report.model_id != model_id:
            raise ValueError(
                f"EvaluationReport references {report.model_id!r}, not {model_id!r}."
            )
        if record.status == ModelStatus.evaluated and record.evaluation_report_id == report.report_id:
            return record  # idempotent
        if not can_transition(record.status, ModelStatus.evaluated):
            raise ModelStateError(model_id, record.status, "record_evaluation (requires 'registered')")

        updated = self._apply(
            record,
            status=ModelStatus.evaluated,
            evaluation_metrics=dict(report.metrics),
            evaluation_report_id=report.report_id,
        )
        self._store.save(updated)
        self._emit(
            updated,
            from_status=record.status.value,
            to_status=ModelStatus.evaluated.value,
            actor=actor,
            actor_type=ActorType.aria,
            outcome=f"evaluated:{report.report_id}",
        )
        return updated

    def request_approval(self, model_id: str, *, actor: str = "aria") -> ModelRecord:
        """``evaluated`` → ``awaiting_approval``."""
        record = self._require(model_id)
        if record.status == ModelStatus.awaiting_approval:
            return record  # idempotent
        if not can_transition(record.status, ModelStatus.awaiting_approval):
            raise ModelStateError(model_id, record.status, "request_approval (requires 'evaluated')")
        updated = self._apply(record, status=ModelStatus.awaiting_approval)
        self._store.save(updated)
        self._emit(
            updated,
            from_status=record.status.value,
            to_status=ModelStatus.awaiting_approval.value,
            actor=actor,
            actor_type=ActorType.aria,
            outcome="approval_requested",
        )
        return updated

    def approve_model(self, model_id: str, approver: str) -> ModelRecord:
        """
        Human approval gate: ``awaiting_approval`` → ``approved``.

        Raises
        ------
        SelfApprovalError        — approver == creator
        UnauthorizedApproverError — approver not in authorized_approvers
        ModelStateError          — not in awaiting_approval status
        """
        record = self._require(model_id)
        if record.status == ModelStatus.approved and record.approved_by == approver:
            return record  # idempotent — already approved by same human

        if record.status != ModelStatus.awaiting_approval:
            raise ModelStateError(model_id, record.status, "approve (requires 'awaiting_approval')")

        if approver == record.created_by:
            raise SelfApprovalError(model_id, approver)
        if self._authorized_approvers is not None and approver not in self._authorized_approvers:
            raise UnauthorizedApproverError(model_id, approver)

        approval_id = "appr-" + hashlib.sha256(
            f"{model_id}::{approver}".encode("utf-8")
        ).hexdigest()[:16]
        updated = self._apply(
            record,
            status=ModelStatus.approved,
            approved_by=approver,
            approved_at=self._clock(),
        )
        self._store.save(updated)
        self._emit(
            updated,
            from_status=record.status.value,
            to_status=ModelStatus.approved.value,
            actor=approver,
            actor_type=ActorType.human,
            approval_id=approval_id,
            outcome="approved",
        )
        return updated

    def reject_model(self, model_id: str, reason: str, *, actor: str = "aria") -> ModelRecord:
        """Reject a model from any non-terminal state → ``rejected``."""
        record = self._require(model_id)
        if record.is_terminal():
            raise ModelStateError(model_id, record.status, "reject (already terminal)")
        updated = self._apply(record, status=ModelStatus.rejected)
        self._store.save(updated)
        self._emit(
            updated,
            from_status=record.status.value,
            to_status=ModelStatus.rejected.value,
            actor=actor,
            actor_type=ActorType.aria,
            status="failed",
            outcome=f"rejected:{reason}",
        )
        return updated

    def promote_canary(self, model_id: str, *, actor: str = "aria") -> ModelRecord:
        """``approved`` → ``canary`` (consumer-serialized)."""
        record = self._require(model_id)
        consumer = record.production_consumer
        if not self._store.acquire_consumer(consumer):
            raise ConcurrentActivationError(consumer)
        try:
            record = self._require(model_id)  # canonical state under the lock
            if record.status == ModelStatus.canary:
                return record  # idempotent
            if not can_transition(record.status, ModelStatus.canary):
                raise ModelStateError(model_id, record.status, "promote_canary (requires 'approved')")
            self._verify_artifact(record, stage="promote_canary")
            updated = self._apply(record, status=ModelStatus.canary)
            self._store.save(updated)
            self._emit(
                updated,
                from_status=record.status.value,
                to_status=ModelStatus.canary.value,
                actor=actor,
                actor_type=ActorType.aria,
                outcome="canary",
            )
            return updated
        finally:
            self._store.release_consumer(consumer)

    def activate_model(self, model_id: str, *, actor: str = "aria") -> ModelRecord:
        """
        Activate a model: ``approved`` | ``canary`` → ``active``.

        Guard ordering (each yields a distinct, testable error):
          1. evaluation present?  else ``EvaluationRequiredError``
          2. human approval present?  else ``ApprovalRequiredError``
          3. transition allowed?  else ``ModelStateError``

        The previously-active model for the same consumer is atomically
        superseded (``active`` → ``deprecated``) in the same batch, so the store
        never holds two active models for one consumer.
        """
        record = self._require(model_id)
        consumer = record.production_consumer
        if not self._store.acquire_consumer(consumer):
            raise ConcurrentActivationError(consumer)
        try:
            record = self._require(model_id)  # canonical state under the lock

            # 1. Evaluation gate FIRST.
            if not record.evaluation_metrics and not record.evaluation_report_id:
                raise EvaluationRequiredError(model_id)
            # 2. Human-approval gate.
            if record.approved_by is None or record.approved_at is None:
                raise ApprovalRequiredError(model_id)
            # 3. State-machine gate.
            if record.status == ModelStatus.active:
                return record  # idempotent
            if not can_transition(record.status, ModelStatus.active):
                raise ModelStateError(model_id, record.status, "activate (requires 'approved'/'canary')")

            # 4. Artifact integrity gate — the bytes we are about to make live
            #    must exist and match the declared hash (fail closed).
            self._verify_artifact(record, stage="activate")

            now = self._clock()
            prior_active = self.get_active_model(consumer)
            batch: list[ModelRecord] = []
            if prior_active is not None and prior_active.model_id != model_id:
                batch.append(self._apply(prior_active, status=ModelStatus.deprecated))
            activated = self._apply(
                record,
                status=ModelStatus.active,
                activated_at=now,
                supersedes=prior_active.model_id if prior_active else None,
            )
            batch.append(activated)

            self._store.save_batch(batch)

            if prior_active is not None and prior_active.model_id != model_id:
                self._emit(
                    batch[0],
                    from_status=ModelStatus.active.value,
                    to_status=ModelStatus.deprecated.value,
                    actor=actor,
                    actor_type=ActorType.aria,
                    outcome=f"superseded_by:{model_id}",
                )
            self._emit(
                activated,
                from_status=record.status.value,
                to_status=ModelStatus.active.value,
                actor=actor,
                actor_type=ActorType.aria,
                outcome="active",
            )
            return activated
        finally:
            self._store.release_consumer(consumer)

    def deprecate_model(self, model_id: str, *, actor: str = "aria") -> ModelRecord:
        """``active`` → ``deprecated`` (consumer-serialized)."""
        record = self._require(model_id)
        consumer = record.production_consumer
        if not self._store.acquire_consumer(consumer):
            raise ConcurrentActivationError(consumer)
        try:
            record = self._require(model_id)
            if not can_transition(record.status, ModelStatus.deprecated):
                raise ModelStateError(model_id, record.status, "deprecate (requires 'active')")
            updated = self._apply(record, status=ModelStatus.deprecated)
            self._store.save(updated)
            self._emit(
                updated,
                from_status=record.status.value,
                to_status=ModelStatus.deprecated.value,
                actor=actor,
                actor_type=ActorType.aria,
                outcome="deprecated",
            )
            return updated
        finally:
            self._store.release_consumer(consumer)

    def rollback_model(
        self, production_consumer: str, target_model_id: str, *, actor: str = "aria"
    ) -> ModelRecord:
        """
        Restore a prior version as the active model for a consumer.

        The current active model (if any) is marked ``rolled_back`` and the
        target is restored to ``active`` in one atomic batch. The target must
        belong to the consumer and must itself have been evaluated and approved
        — you cannot roll back to an un-vetted version.

        Raises
        ------
        ModelNotFoundError        — target not found for this consumer
        EvaluationRequiredError   — target was never evaluated
        ApprovalRequiredError     — target was never approved
        ConcurrentActivationError — consumer lock already held
        """
        if not self._store.acquire_consumer(production_consumer):
            raise ConcurrentActivationError(production_consumer)
        try:
            target = self._store.get(target_model_id)
            if target is None or target.production_consumer != production_consumer:
                raise ModelNotFoundError(f"{production_consumer}:{target_model_id}")

            # Eligibility FIRST: a rollback target must be a version that was
            # itself once LIVE and then retired — never a draft / registered /
            # approved-but-never-activated record. Without this guard a record
            # that never passed the activation gate could be back-doored to
            # ``active`` through rollback, bypassing the activation path. A
            # valid target is ``deprecated`` or ``rolled_back`` AND carries an
            # ``activated_at`` proving it was once active.
            if target.status not in (ModelStatus.deprecated, ModelStatus.rolled_back):
                raise ModelStateError(
                    target_model_id, target.status,
                    "rollback (target must be a previously-active "
                    "'deprecated'/'rolled_back' version)",
                )
            if target.activated_at is None:
                raise ModelStateError(
                    target_model_id, target.status,
                    "rollback (target was never activated)",
                )

            # Governance: only roll back to a previously-vetted version.
            if not target.evaluation_metrics and not target.evaluation_report_id:
                raise EvaluationRequiredError(target_model_id)
            if target.approved_by is None or target.approved_at is None:
                raise ApprovalRequiredError(target_model_id)

            # Artifact integrity: the bytes we are about to make live again must
            # still exist and match the declared hash (fail closed).
            self._verify_artifact(target, stage="rollback")

            now = self._clock()
            prior_active = self.get_active_model(production_consumer)
            batch: list[ModelRecord] = []
            if prior_active is not None and prior_active.model_id != target_model_id:
                batch.append(self._apply(prior_active, status=ModelStatus.rolled_back))
            restored = self._apply(
                target,
                status=ModelStatus.active,
                activated_at=now,
                rollback_target=prior_active.model_id if prior_active else None,
            )
            batch.append(restored)

            self._store.save_batch(batch)

            if prior_active is not None and prior_active.model_id != target_model_id:
                self._emit(
                    batch[0],
                    from_status=ModelStatus.active.value,
                    to_status=ModelStatus.rolled_back.value,
                    actor=actor,
                    actor_type=ActorType.aria,
                    outcome=f"rolled_back_for:{target_model_id}",
                )
            self._emit(
                restored,
                from_status=target.status.value,
                to_status=ModelStatus.active.value,
                actor=actor,
                actor_type=ActorType.aria,
                outcome=f"restored_from:{prior_active.model_id if prior_active else 'none'}",
            )
            return restored
        finally:
            self._store.release_consumer(production_consumer)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _require(self, model_id: str) -> ModelRecord:
        record = self._store.get(model_id)
        if record is None:
            raise ModelNotFoundError(model_id)
        return record

    @staticmethod
    def _apply(record: ModelRecord, **changes: object) -> ModelRecord:
        """
        Advance a record by FULL re-validation, not ``model_copy(update=...)``.

        Pydantic v2's ``model_copy(update=...)`` bypasses field validators, so
        it would let an unvalidated value (a non-finite metric, a malformed
        hash, a tz-naive timestamp, an unsanitised metadata blob) slip into a
        stored record. Reconstructing via ``model_validate`` over the merged
        data re-runs every validator, so a record can never advance into an
        invalid state. ``model_dump()`` (python mode) preserves enum members
        and datetimes, which ``model_validate`` accepts, and re-sanitising
        already-clean metadata is idempotent.
        """
        return ModelRecord.model_validate({**record.model_dump(), **changes})

    def _confined_artifact_path(self, path_str: str, model_id: str) -> Path:
        """Resolve ``path_str`` and verify it is strictly beneath the artifact root."""
        if self._artifact_root is None:
            return Path(path_str)
        resolved = Path(path_str).resolve()
        root = self._artifact_root.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ArtifactPathError(
                f"Model {model_id!r}: artifact path {path_str!r} resolves to "
                f"{resolved}, which is outside the artifact root {root}."
            )
        return resolved

    def _verify_artifact(self, record: ModelRecord, *, stage: str) -> None:
        """
        Fail-closed artifact verification. ``stage`` names the calling operation
        for error context. A previous version returned early when the file did
        not exist — meaning a declared-but-missing or hash-less artifact passed
        verification. That hole is closed here: a declared artifact MUST be
        confined, present, and hash-matched before it can register, go canary,
        activate, or be rolled back to.

        Rules:
          - No ``artifact_path`` → nothing to verify, BUT a declared
            ``artifact_hash`` with no path is inconsistent → ``ArtifactIntegrityError``.
          - ``artifact_path`` set but no ``artifact_root`` configured → we cannot
            confine, so we will not trust it → ``ArtifactPathError``.
          - Path must resolve strictly beneath the artifact root → ``ArtifactPathError``.
          - The file MUST exist → ``ArtifactMissingError``.
          - An ``artifact_hash`` MUST be declared → ``ArtifactIntegrityError``.
          - On-disk bytes MUST hash to the declared value → ``ArtifactHashMismatchError``.
        """
        if record.artifact_path is None:
            if record.artifact_hash is not None:
                raise ArtifactIntegrityError(
                    record.model_id,
                    "artifact_hash is declared but artifact_path is None; a hash "
                    "with no artifact to bind to is rejected.",
                )
            return

        if self._artifact_root is None:
            raise ArtifactPathError(
                f"Model {record.model_id!r} ({stage}): artifact_path "
                f"{record.artifact_path!r} is declared but no artifact_root is "
                "configured; refusing to trust an unconfined artifact."
            )

        confined = self._confined_artifact_path(record.artifact_path, record.model_id)
        if not confined.exists():
            raise ArtifactMissingError(record.model_id, record.artifact_path)
        if record.artifact_hash is None:
            raise ArtifactIntegrityError(
                record.model_id,
                "artifact_path is declared but artifact_hash is None; an "
                "unverifiable artifact cannot enter a governed lifecycle.",
            )
        actual = hashlib.sha256(confined.read_bytes()).hexdigest()
        if actual != record.artifact_hash.lower():
            raise ArtifactHashMismatchError(record.model_id)

    def _emit(
        self,
        record: ModelRecord,
        *,
        from_status: Optional[str],
        to_status: str,
        actor: str,
        actor_type: ActorType,
        approval_id: Optional[str] = None,
        outcome: Optional[str] = None,
        status: str = "ok",
    ) -> None:
        """
        Emit a typed ``ModelLifecycleEvent`` to the Work Ledger v2 AFTER the
        store commit. A ledger hiccup never rolls back a committed state change
        (the store is the source of truth), but a failure is NEVER swallowed
        silently: it is logged at ERROR, recorded in ``audit_failures``, and
        appended to the durable ``audit_outbox_path`` when configured, so the
        gap in the audit trail is itself auditable.
        """
        try:
            writer = self._writer if self._writer is not None else _default_writer()
            envelope = make_envelope(
                task_id=record.model_id,
                actor=actor,
                actor_type=actor_type,
                correlation_id=record.model_id,
                model_name=record.model_name,
                model_version=record.semantic_version,
                production_consumer=record.production_consumer,
                to_status=to_status,
                from_status=from_status,
                dataset_id=record.dataset_id,
                dataset_hash=record.dataset_hash,
                approval_id=approval_id,
                outcome=outcome,
                status=status,
            )
            writer.append(ModelLifecycleEvent(**envelope))
        except Exception as exc:  # noqa: BLE001 — emission must never crash a committed transition
            self._record_audit_failure(
                record,
                from_status=from_status,
                to_status=to_status,
                actor=actor,
                actor_type=actor_type,
                approval_id=approval_id,
                outcome=outcome,
                status=status,
                error=exc,
            )

    def _record_audit_failure(
        self,
        record: ModelRecord,
        *,
        from_status: Optional[str],
        to_status: str,
        actor: str,
        actor_type: ActorType,
        approval_id: Optional[str],
        outcome: Optional[str],
        status: str,
        error: Exception,
    ) -> None:
        """
        Durably record a ledger-emission failure. Never raises and never logs
        secrets — the failure envelope carries only the same non-confidential
        lifecycle fields the ledger event itself would have.

        The exception MESSAGE is deliberately dropped: a writer that failed on a
        credential-bearing value (e.g. a connection string or ``password=...``)
        would otherwise echo that secret into the in-memory record, the JSONL
        outbox, AND the logs. The ledger redaction boundary (``redact_freetext``)
        masks API-key/token shapes but NOT passwords or connection strings, so a
        partial redaction here would still leak. We therefore record only the
        exception's CLASS NAME — a code identifier that cannot carry a secret —
        across all three sinks. If even the outbox write fails, that is escalated
        to CRITICAL (class name only) but still does not propagate (the committed
        state change must stand).
        """
        error_type = type(error).__name__
        failure = {
            "kind": "model_lifecycle_audit_failure",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "model_id": record.model_id,
            "model_name": record.model_name,
            "model_version": record.semantic_version,
            "production_consumer": record.production_consumer,
            "from_status": from_status,
            "to_status": to_status,
            "actor": actor,
            "actor_type": actor_type.value if hasattr(actor_type, "value") else str(actor_type),
            "approval_id": approval_id,
            "outcome": outcome,
            "status": status,
            "error": error_type,
        }
        self._audit_failures.append(failure)
        logger.error(
            "Work Ledger emission failed for model %s (%s -> %s): %s",
            record.model_id, from_status, to_status, error_type,
        )
        if self._audit_outbox_path is None:
            return
        try:
            self._audit_outbox_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._audit_outbox_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(failure, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception as outbox_exc:  # noqa: BLE001 — last-resort durability
            logger.critical(
                "Could not persist audit-failure for model %s to outbox %s: %s",
                record.model_id, self._audit_outbox_path, type(outbox_exc).__name__,
            )


def _default_writer() -> object:
    """Lazy import so the registry module has no hard import-time ledger dependency."""
    from aria.ledger.writer import get_default_writer
    return get_default_writer()
