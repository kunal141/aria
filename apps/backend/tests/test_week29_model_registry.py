"""
Week 29 Priority 4 — Model Lifecycle Registry v1 tests.

Deterministic, offline. No network, no LLM, no GPU. Covers the full required
matrix: record validation; allowed + forbidden transitions; duplicate
idempotency vs conflict; self-approval; activation gates (evaluation, approval);
one-active-per-consumer; atomic persistence failure; restart survival; path
traversal; artifact-hash mismatch; rollback; concurrent activation; unknown
consumer; typed ledger lifecycle events; dataset provenance; version comparison.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from aria.ledger.events import ActorType, ModelLifecycleEvent
from aria.ledger.reader import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.model_registry import (
    ApprovalRequiredError,
    ArtifactHashMismatchError,
    ArtifactIntegrityError,
    ArtifactMissingError,
    ArtifactPathError,
    ConcurrentActivationError,
    DuplicateModelConflict,
    DuplicateVersionConflict,
    EvaluationReport,
    EvaluationRequiredError,
    InMemoryModelStore,
    ModelProvider,
    ModelRecord,
    ModelRegistry,
    ModelStateError,
    ModelStatus,
    ModelType,
    MultipleActiveModelsError,
    OfflineEvaluator,
    RegistryCorruptionError,
    RegistryPersistenceError,
    SelfApprovalError,
    UnknownConsumerError,
    can_transition,
    default_pr_review_holdout,
    is_terminal,
)

CONSUMER = "pr_review_skill"
FIXED_TS = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return FIXED_TS


def _record(model_id: str, version: str = "1.0.0", **overrides) -> ModelRecord:
    base = dict(
        model_id=model_id,
        model_name="pr_review_specialist",
        semantic_version=version,
        provider=ModelProvider.prototype,
        model_type=ModelType.fine_tuned,
        base_model="Qwen2.5-Coder-7B-Instruct",
        dataset_id="ds-pr-2026w24",
        dataset_hash="a" * 64,
        created_by="aria",
        created_at=FIXED_TS,
        production_consumer=CONSUMER,
        status=ModelStatus.registered,
    )
    base.update(overrides)
    return ModelRecord(**base)


def _registry(tmp_path: Path, **kwargs) -> tuple[ModelRegistry, Path]:
    ledger = tmp_path / "ledger_v2.jsonl"
    store = InMemoryModelStore(persist_path=tmp_path / "registry.jsonl")
    kwargs.setdefault("known_consumers", {CONSUMER})
    kwargs.setdefault("authorized_approvers", {"human:kunal"})
    reg = ModelRegistry(
        store=store,
        writer=LedgerWriter(ledger),
        clock=_fixed_clock,
        **kwargs,
    )
    return reg, ledger


def _to_approved(reg: ModelRegistry, rec: ModelRecord, approver: str = "human:kunal") -> ModelRecord:
    reg.register_model(rec)
    report = OfflineEvaluator().evaluate(rec, default_pr_review_holdout())
    reg.record_evaluation(rec.model_id, report)
    reg.request_approval(rec.model_id)
    return reg.approve_model(rec.model_id, approver=approver)


# ── 1. Record validation ──────────────────────────────────────────────────────


def test_valid_record_builds_and_roundtrips():
    rec = _record("m1")
    again = ModelRecord.model_validate_json(rec.model_dump_json())
    assert again == rec
    assert again.dataset_hash == "a" * 64


@pytest.mark.parametrize("bad", [
    {"semantic_version": "1.0"},                 # not x.y.z
    {"dataset_hash": "xyz"},                      # not 64-hex
    {"created_at": datetime(2026, 6, 13)},        # naive datetime
    {"model_id": "../evil"},                      # path traversal in id
    {"model_id": "a/b"},                          # separator in id
    {"artifact_hash": "nothex"},                  # bad optional hash
    {"evaluation_metrics": {"acc": float("inf")}},  # non-finite metric
    {"evaluation_metrics": {"acc": True}},        # bool is not a number
])
def test_invalid_record_rejected(bad):
    overrides = dict(bad)
    model_id = overrides.pop("model_id", "m1")
    with pytest.raises(ValidationError):
        _record(model_id, **overrides)


# ── 2. Allowed and forbidden transitions ──────────────────────────────────────


def test_allowed_and_forbidden_transitions():
    assert can_transition(ModelStatus.registered, ModelStatus.evaluated)
    assert can_transition(ModelStatus.evaluated, ModelStatus.awaiting_approval)
    assert can_transition(ModelStatus.awaiting_approval, ModelStatus.approved)
    assert can_transition(ModelStatus.approved, ModelStatus.active)
    assert can_transition(ModelStatus.canary, ModelStatus.active)
    assert can_transition(ModelStatus.active, ModelStatus.deprecated)
    # Forbidden
    assert not can_transition(ModelStatus.registered, ModelStatus.active)
    assert not can_transition(ModelStatus.registered, ModelStatus.approved)
    assert not can_transition(ModelStatus.evaluated, ModelStatus.active)
    assert not can_transition(ModelStatus.deprecated, ModelStatus.active)
    # Terminal states allow nothing
    for terminal in (ModelStatus.rejected, ModelStatus.deprecated, ModelStatus.rolled_back, ModelStatus.failed):
        assert is_terminal(terminal)
        for to in ModelStatus:
            assert not can_transition(terminal, to)


# ── 3. Duplicate registration idempotency ─────────────────────────────────────


def test_duplicate_registration_idempotent(tmp_path):
    reg, _ = _registry(tmp_path)
    rec = _record("m1")
    first = reg.register_model(rec)
    second = reg.register_model(_record("m1"))   # identical content
    assert first.model_id == second.model_id
    assert len(reg.list_versions(CONSUMER)) == 1


# ── 4. Conflicting duplicate rejection ────────────────────────────────────────


def test_conflicting_same_id_rejected(tmp_path):
    reg, _ = _registry(tmp_path)
    reg.register_model(_record("m1", dataset_hash="a" * 64))
    with pytest.raises(DuplicateModelConflict):
        reg.register_model(_record("m1", dataset_hash="b" * 64))  # different content


def test_conflicting_version_owned_by_other_id_rejected(tmp_path):
    reg, _ = _registry(tmp_path)
    reg.register_model(_record("m1", version="1.0.0"))
    with pytest.raises(DuplicateVersionConflict):
        reg.register_model(_record("m2", version="1.0.0"))  # same (consumer, version)


# ── 5. Self-approval rejection ────────────────────────────────────────────────


def test_self_approval_rejected(tmp_path):
    reg, _ = _registry(tmp_path, authorized_approvers=None)
    rec = _record("m1", created_by="human:kunal")
    reg.register_model(rec)
    reg.record_evaluation("m1", OfflineEvaluator().evaluate(rec, default_pr_review_holdout()))
    reg.request_approval("m1")
    with pytest.raises(SelfApprovalError):
        reg.approve_model("m1", approver="human:kunal")  # creator == approver


# ── 6. Activation without evaluation rejected ─────────────────────────────────


def test_activation_without_evaluation_rejected(tmp_path):
    reg, _ = _registry(tmp_path)
    reg.register_model(_record("m1"))  # registered, never evaluated
    with pytest.raises(EvaluationRequiredError):
        reg.activate_model("m1")


# ── 7. Activation without approval rejected ───────────────────────────────────


def test_activation_without_approval_rejected(tmp_path):
    reg, _ = _registry(tmp_path)
    rec = _record("m1")
    reg.register_model(rec)
    reg.record_evaluation("m1", OfflineEvaluator().evaluate(rec, default_pr_review_holdout()))
    # evaluated but never approved
    with pytest.raises(ApprovalRequiredError):
        reg.activate_model("m1")


# ── 8. One active model per consumer ──────────────────────────────────────────


def test_activation_supersedes_prior_active(tmp_path):
    reg, _ = _registry(tmp_path)
    v1 = _record("m1", version="1.0.0")
    _to_approved(reg, v1)
    reg.activate_model("m1")

    v2 = _record("m2", version="2.0.0", dataset_hash="b" * 64)
    _to_approved(reg, v2)
    reg.activate_model("m2")

    active = reg.get_active_model(CONSUMER)
    assert active.model_id == "m2"
    assert active.supersedes == "m1"
    assert reg._store.get("m1").status == ModelStatus.deprecated
    assert len(reg._store.list_by_status(ModelStatus.active)) == 1


def test_store_rejects_two_active_for_one_consumer(tmp_path):
    store = InMemoryModelStore(persist_path=tmp_path / "r.jsonl")
    a = _record("m1", version="1.0.0", status=ModelStatus.active)
    b = _record("m2", version="2.0.0", status=ModelStatus.active, dataset_hash="b" * 64)
    with pytest.raises(MultipleActiveModelsError):
        store.save_batch([a, b])
    # Nothing committed.
    assert store.get("m1") is None and store.get("m2") is None


# ── 9. Atomic persistence failure ─────────────────────────────────────────────


def test_persistence_failure_rolls_back(tmp_path, monkeypatch):
    store = InMemoryModelStore(persist_path=tmp_path / "r.jsonl")

    def _boom() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_flush", _boom)
    with pytest.raises(RegistryPersistenceError):
        store.save(_record("m1"))
    # Fail-closed: the record is NOT visible after a failed flush.
    assert store.get("m1") is None
    assert len(store) == 0


# ── 10. Restart survival ──────────────────────────────────────────────────────


def test_restart_survival(tmp_path):
    reg, ledger = _registry(tmp_path)
    rec = _record("m1")
    _to_approved(reg, rec)
    reg.activate_model("m1")

    # New store + registry over the SAME persist file = a process restart.
    reg2 = ModelRegistry(
        store=InMemoryModelStore(persist_path=tmp_path / "registry.jsonl"),
        known_consumers={CONSUMER},
        writer=LedgerWriter(ledger),
        clock=_fixed_clock,
    )
    active = reg2.get_active_model(CONSUMER)
    assert active is not None and active.model_id == "m1"
    assert active.status == ModelStatus.active


# ── 11. Path traversal rejection ──────────────────────────────────────────────


def test_artifact_path_traversal_rejected(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    reg, _ = _registry(tmp_path, artifact_root=artifact_root)
    escape = str(tmp_path / "outside.bin")  # resolves outside artifact_root
    with pytest.raises(ArtifactPathError):
        reg.register_model(_record("m1", artifact_path=escape))


# ── 12. Artifact hash mismatch ────────────────────────────────────────────────


def test_artifact_hash_mismatch_rejected(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    art = artifact_root / "adapter.bin"
    art.write_text("REAL-BYTES", encoding="utf-8")
    wrong_hash = hashlib.sha256(b"DIFFERENT").hexdigest()
    reg, _ = _registry(tmp_path, artifact_root=artifact_root)
    with pytest.raises(ArtifactHashMismatchError):
        reg.register_model(_record("m1", artifact_path=str(art), artifact_hash=wrong_hash))


def test_artifact_hash_match_accepted(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    art = artifact_root / "adapter.bin"
    art.write_text("REAL-BYTES", encoding="utf-8")
    good_hash = hashlib.sha256(art.read_bytes()).hexdigest()
    reg, _ = _registry(tmp_path, artifact_root=artifact_root)
    rec = reg.register_model(_record("m1", artifact_path=str(art), artifact_hash=good_hash))
    assert rec.artifact_hash == good_hash


# ── 13. Rollback restores prior active version ────────────────────────────────


def test_rollback_restores_prior_active(tmp_path):
    reg, _ = _registry(tmp_path)
    v1 = _record("m1", version="1.0.0")
    _to_approved(reg, v1)
    reg.activate_model("m1")

    v2 = _record("m2", version="2.0.0", dataset_hash="b" * 64)
    _to_approved(reg, v2)
    reg.activate_model("m2")
    assert reg.get_active_model(CONSUMER).model_id == "m2"

    restored = reg.rollback_model(CONSUMER, "m1")
    assert restored.model_id == "m1"
    assert reg.get_active_model(CONSUMER).model_id == "m1"
    assert reg._store.get("m2").status == ModelStatus.rolled_back
    assert len(reg._store.list_by_status(ModelStatus.active)) == 1


# ── 14. Concurrent activation safety ──────────────────────────────────────────


def test_concurrent_activation_blocked(tmp_path):
    reg, _ = _registry(tmp_path)
    rec = _record("m1")
    _to_approved(reg, rec)
    # Simulate an in-flight activation by another worker holding the lock.
    assert reg._store.acquire_consumer(CONSUMER) is True
    try:
        with pytest.raises(ConcurrentActivationError):
            reg.activate_model("m1")
    finally:
        reg._store.release_consumer(CONSUMER)
    # Once released, activation proceeds.
    assert reg.activate_model("m1").status == ModelStatus.active


# ── 15. Unknown consumer rejection ────────────────────────────────────────────


def test_unknown_consumer_rejected(tmp_path):
    reg, _ = _registry(tmp_path, known_consumers={"only_this"})
    with pytest.raises(UnknownConsumerError):
        reg.register_model(_record("m1", production_consumer="pr_review_skill"))


# ── 16. Typed Work Ledger lifecycle events ────────────────────────────────────


def test_typed_lifecycle_events_emitted(tmp_path):
    reg, ledger = _registry(tmp_path)
    rec = _record("m1")
    _to_approved(reg, rec)
    reg.activate_model("m1")

    events = [e for e in LedgerReader(v2_path=ledger).v2_events()
              if isinstance(e, ModelLifecycleEvent)]
    transitions = [(e.from_status, e.to_status) for e in events]
    assert (None, "registered") in transitions
    assert ("registered", "evaluated") in transitions
    assert ("evaluated", "awaiting_approval") in transitions
    assert ("awaiting_approval", "approved") in transitions
    assert ("approved", "active") in transitions

    for e in events:
        assert e.production_consumer == CONSUMER
        assert e.correlation_id == "m1"
        assert e.model_name == "pr_review_specialist"
        assert e.model_version == "1.0.0"

    approve_event = next(e for e in events if e.to_status == "approved")
    assert approve_event.approval_id is not None
    assert approve_event.actor_type == ActorType.human
    assert approve_event.actor == "human:kunal"


# ── 17. Dataset provenance retained ───────────────────────────────────────────


def test_dataset_provenance_retained(tmp_path):
    reg, ledger = _registry(tmp_path)
    rec = _record("m1", dataset_id="ds-special", dataset_hash="c" * 64)
    _to_approved(reg, rec)
    activated = reg.activate_model("m1")
    # On the record across lifecycle.
    assert activated.dataset_id == "ds-special"
    assert activated.dataset_hash == "c" * 64
    # On the emitted events.
    events = [e for e in LedgerReader(v2_path=ledger).v2_events()
              if isinstance(e, ModelLifecycleEvent)]
    assert all(e.dataset_id == "ds-special" for e in events)
    assert all(e.dataset_hash == "c" * 64 for e in events)


# ── 18. Comparison of model versions ──────────────────────────────────────────


def test_compare_versions(tmp_path):
    reg, _ = _registry(tmp_path)
    a = _record("m1", version="1.0.0")
    b = _record("m2", version="2.0.0", dataset_hash="b" * 64)
    reg.register_model(a)
    reg.register_model(b)
    reg.record_evaluation("m1", _report("m1", {"accuracy": 0.70, "rubric_score": 4.0}))
    reg.record_evaluation("m2", _report("m2", {"accuracy": 0.90, "rubric_score": 4.5}))

    cmp = reg.compare_versions("m1", "m2")
    assert cmp.metric_deltas["accuracy"] == pytest.approx(0.20)
    assert cmp.metric_deltas["rubric_score"] == pytest.approx(0.5)
    assert cmp.dataset_changed is True
    assert cmp.base_model_changed is False
    assert cmp.provider_changed is False


def _report(model_id: str, metrics: dict) -> EvaluationReport:
    return EvaluationReport(
        report_id=f"eval-{model_id}",
        model_id=model_id,
        holdout_id="hold-1",
        holdout_hash="d" * 64,
        num_examples=3,
        metrics=metrics,
        created_at=FIXED_TS,
    )


# ── Codex re-audit regressions ─────────────────────────────────────────────────
#
# Each test locks in one finding the prior green suite missed. They are written
# to FAIL against the pre-fix code and PASS only with the fix in place.


# F1 — rollback eligibility: a record that never passed the activation gate must
# NOT be back-doored to ACTIVE via rollback.


def test_f1_rollback_to_approved_but_never_activated_rejected(tmp_path):
    """A target that was approved but never activated is not a rollback target."""
    reg, _ = _registry(tmp_path)
    rec = _record("m1", version="1.0.0")
    _to_approved(reg, rec)            # approved, status=approved, activated_at=None
    assert reg._store.get("m1").status == ModelStatus.approved
    with pytest.raises(ModelStateError):
        reg.rollback_model(CONSUMER, "m1")
    # The target was NOT silently promoted to active.
    assert reg._store.get("m1").status == ModelStatus.approved
    assert reg.get_active_model(CONSUMER) is None


def test_f1_rollback_to_registered_target_rejected(tmp_path):
    """A merely-registered target (never vetted) is not a rollback target."""
    reg, _ = _registry(tmp_path)
    reg.register_model(_record("m1"))
    with pytest.raises(ModelStateError):
        reg.rollback_model(CONSUMER, "m1")
    assert reg._store.get("m1").status == ModelStatus.registered


# F2 — a corrupt persisted registry refuses to start (fail closed), rather than
# booting on partial/ambiguous governance state.


def test_f2_corrupt_registry_file_refuses_to_start(tmp_path):
    persist = tmp_path / "registry.jsonl"
    persist.write_text("this is not valid json\n", encoding="utf-8")
    with pytest.raises(RegistryCorruptionError):
        InMemoryModelStore(persist_path=persist)


def test_f2_duplicate_model_id_in_file_refuses_to_start(tmp_path):
    persist = tmp_path / "registry.jsonl"
    line = _record("m1").model_dump_json()
    persist.write_text(line + "\n" + line + "\n", encoding="utf-8")  # same id twice
    with pytest.raises(RegistryCorruptionError):
        InMemoryModelStore(persist_path=persist)


# F3 — artifact verification fails closed: a declared-but-missing artifact, a
# path with no hash, a hash with no path, or a path with no configured root are
# all rejected (the prior version returned early on a missing file).


def test_f3_declared_artifact_missing_rejected(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    ghost = artifact_root / "never_written.bin"   # confined but absent
    reg, _ = _registry(tmp_path, artifact_root=artifact_root)
    with pytest.raises(ArtifactMissingError):
        reg.register_model(
            _record("m1", artifact_path=str(ghost), artifact_hash="e" * 64)
        )


def test_f3_artifact_path_without_hash_rejected(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    art = artifact_root / "adapter.bin"
    art.write_text("REAL-BYTES", encoding="utf-8")
    reg, _ = _registry(tmp_path, artifact_root=artifact_root)
    with pytest.raises(ArtifactIntegrityError):
        reg.register_model(_record("m1", artifact_path=str(art)))  # no hash


def test_f3_artifact_hash_without_path_rejected(tmp_path):
    reg, _ = _registry(tmp_path, artifact_root=tmp_path / "artifacts")
    with pytest.raises(ArtifactIntegrityError):
        reg.register_model(_record("m1", artifact_hash="e" * 64))  # no path


def test_f3_artifact_path_without_root_rejected(tmp_path):
    art = tmp_path / "adapter.bin"
    art.write_text("REAL-BYTES", encoding="utf-8")
    digest = hashlib.sha256(art.read_bytes()).hexdigest()
    reg, _ = _registry(tmp_path)  # no artifact_root configured
    with pytest.raises(ArtifactPathError):
        reg.register_model(_record("m1", artifact_path=str(art), artifact_hash=digest))


# F4 — evaluation evidence is strict: EvaluationReport rejects non-finite/bool
# metrics, and lifecycle advancement re-validates (no model_copy bypass).


@pytest.mark.parametrize("bad_metrics", [
    {"accuracy": float("nan")},
    {"accuracy": float("inf")},
    {"accuracy": float("-inf")},
    {"accuracy": True},     # bool is not a number
])
def test_f4a_evaluation_report_rejects_non_finite_metrics(bad_metrics):
    with pytest.raises(ValidationError):
        _report("m1", bad_metrics)


def test_f4b_apply_revalidates_and_rejects_non_finite(tmp_path):
    """
    Lifecycle advancement reconstructs via model_validate, so a non-finite
    metric cannot be smuggled in (Pydantic's model_copy(update=) would bypass
    field validators — that path is closed).
    """
    rec = _record("m1")
    with pytest.raises(ValidationError):
        ModelRegistry._apply(rec, evaluation_metrics={"accuracy": float("inf")})


# F7 — a Work-Ledger emission failure never silently disappears: the committed
# transition stands, and the failure is durably appended to the audit outbox
# (carrying only non-confidential lifecycle fields).


def test_f7_ledger_emission_failure_recorded_in_outbox(tmp_path):
    outbox = tmp_path / "audit_outbox.jsonl"
    store = InMemoryModelStore(persist_path=tmp_path / "registry.jsonl")

    class _BoomWriter:
        def append(self, event) -> None:
            raise OSError("ledger unavailable")

    reg = ModelRegistry(
        store=store,
        known_consumers={CONSUMER},
        authorized_approvers={"human:kunal"},
        writer=_BoomWriter(),
        audit_outbox_path=outbox,
        clock=_fixed_clock,
    )

    # The committed transition succeeds even though the ledger write fails.
    reg.register_model(_record("m1"))
    assert store.get("m1") is not None

    # The failure is recorded in memory AND durably on disk — never dropped.
    assert len(reg.audit_failures) == 1
    assert outbox.exists()
    lines = [l for l in outbox.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    failure = json.loads(lines[0])
    assert failure["model_id"] == "m1"
    assert failure["to_status"] == "registered"
    assert "OSError" in failure["error"]
    # The audit line carries lifecycle fields only — no artifact/secret payload.
    assert {"model_id", "to_status", "from_status", "production_consumer"} <= set(failure)
    assert "artifact_path" not in failure
    assert "artifact_hash" not in failure


@pytest.mark.parametrize(
    "secret",
    [
        "Bearer sk-abc123SECRETtoken4567890",                       # bearer token
        "sk-ant-api03-DEADBEEFdeadbeefSECRETkey00",                 # API key
        "password=SuperSecretP@ssw0rd",                             # plain password
        "postgres://admin:S3cretDbPass@db.internal:5432/prod",      # connection string
    ],
)
def test_f7_audit_failure_never_leaks_exception_secret(tmp_path, caplog, secret):
    """
    A writer that fails on a credential-bearing value must NOT echo that secret
    into any of the three audit sinks: the in-memory ``audit_failures`` record,
    the durable JSONL outbox, or the logs. Only the exception CLASS NAME is
    retained. Covers token / API-key shapes (which ``redact_freetext`` knows)
    AND password / connection-string shapes (which it does NOT) — proving the
    fix drops the message entirely rather than relying on partial redaction.
    """
    outbox = tmp_path / "audit_outbox.jsonl"
    store = InMemoryModelStore(persist_path=tmp_path / "registry.jsonl")

    class _SecretLeakingWriter:
        def append(self, event) -> None:
            raise RuntimeError(f"ledger connect failed: {secret}")

    reg = ModelRegistry(
        store=store,
        known_consumers={CONSUMER},
        authorized_approvers={"human:kunal"},
        writer=_SecretLeakingWriter(),
        audit_outbox_path=outbox,
        clock=_fixed_clock,
    )

    with caplog.at_level(logging.DEBUG):
        reg.register_model(_record("m1"))

    # The committed transition stands regardless of the emission failure.
    assert store.get("m1") is not None

    # Sink 1 — in-memory record: class name retained, secret absent everywhere.
    failures = reg.audit_failures
    assert len(failures) == 1
    assert failures[0]["error"] == "RuntimeError"
    assert secret not in json.dumps(failures, ensure_ascii=False)

    # Sink 2 — durable JSONL outbox.
    assert secret not in outbox.read_text(encoding="utf-8")

    # Sink 3 — logs.
    assert secret not in caplog.text
