"""
Week 29 Priority 5 — Fine-Tuning Prototype tests.

Deterministic, offline. No network, no LLM, no GPU, no model download, no
paid API. Covers the full required matrix:

  1.  accepted dataset produces a plan
  2.  tampered dataset rejected
  3.  insufficient dataset rejected
  4.  privacy rejection (defence-in-depth over exported content)
  5.  provenance rejection
  6.  deterministic plan generation
  7.  stable configuration hash
  8.  dry-run performs no external (socket) call
  9.  mock runner produces a deterministic result
  10. baseline comparison
  11. failed evaluation prevents approval readiness
  12. successful evaluation registers a candidate
  13. registry retains dataset provenance
  14. candidate is not activated
  15. no production router change (no active model ever)
  16. Work Ledger lifecycle events emitted
  17. artifact paths confined
  18. persistence failure fails closed
"""
from __future__ import annotations

import hashlib
import json
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aria.ledger.events import (
    ActorType,
    CorrectionRecorded,
    ModelLifecycleEvent,
    OutcomeRecorded,
    SkillInvoked,
    make_envelope,
)
from aria.ledger.reader import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.model_registry import (
    InMemoryModelStore,
    ModelProvider,
    ModelRecord,
    ModelRegistry,
    ModelStatus,
    ModelType,
    OfflineEvaluator,
    RegistryPersistenceError,
    default_pr_review_holdout,
)
from aria.training_data import (
    AcceptAllVerifier,
    DatasetExporter,
    Sensitivity,
    TrainingCandidate,
    canonical_content_hash,
)
from aria.training_data.exporter import ExportConfig
from aria.fine_tuning import (
    AcceptAllPlanProvenance,
    CandidateEvaluation,
    DatasetInsufficientError,
    DatasetIntegrityError,
    DatasetPrivacyError,
    DatasetProvenanceError,
    ArtifactPathError,
    FineTuningPipeline,
    FineTuningPlanner,
    HyperparameterProposal,
    LedgerEventProvenanceVerifier,
    OfflineCandidateEvaluator,
    OfflineMockRunner,
    TrainingMethod,
    TrainingStatus,
    compute_config_hash,
    default_baseline_record,
)


CONSUMER = "pr_review_skill"
FIXED_TS = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return FIXED_TS


# ── Fixtures: privacy-safe candidates + a real Priority-3 export ────────────────


def _sft_candidate(i: int) -> TrainingCandidate:
    task_id = f"sft-{i:02d}"
    skill = "pr_review_skill" if i % 2 == 0 else "qa_skill"
    input_text = f"Review PR #{100 + i}: adds a null check to the ranker path {i}."
    output_text = f"Risk LOW. Branch {i} is guarded; add one regression test before merge."
    return TrainingCandidate(
        task_id=task_id,
        skill_name=skill,
        input_text=input_text,
        output_text=output_text,
        sensitivity=Sensitivity.internal,
        allowed_for_training=True,
        provenance=[f"evt-{task_id}-outcome"],
        content_hash=canonical_content_hash(
            task_id=task_id, skill_name=skill,
            input_text=input_text, output_text=output_text,
            rejected_output=None, corrected_output=None,
        ),
        outcome_label="approved",
        created_at=FIXED_TS,
    )


def _dpo_candidate(i: int) -> TrainingCandidate:
    task_id = f"dpo-{i:02d}"
    skill = "pr_review_skill"
    input_text = f"Review PR #{200 + i}: refactors the notification batching loop {i}."
    rejected = f"Looks fine, ship it (variant {i})."
    corrected = f"Risk MEDIUM (variant {i}). Verify ordering and add a coverage test."
    return TrainingCandidate(
        task_id=task_id,
        skill_name=skill,
        input_text=input_text,
        output_text=None,
        rejected_output=rejected,
        corrected_output=corrected,
        sensitivity=Sensitivity.internal,
        allowed_for_training=True,
        provenance=[f"evt-{task_id}-correction"],
        content_hash=canonical_content_hash(
            task_id=task_id, skill_name=skill,
            input_text=input_text, output_text=None,
            rejected_output=rejected, corrected_output=corrected,
        ),
        outcome_label=None,
        created_at=FIXED_TS,
    )


def _build_export(export_dir: Path, n_sft: int = 8, n_dpo: int = 2):
    """Run the REAL Priority-3 exporter over privacy-safe fixtures."""
    export_dir.mkdir(parents=True, exist_ok=True)
    candidates = [_sft_candidate(i) for i in range(n_sft)] + [_dpo_candidate(i) for i in range(n_dpo)]
    exporter = DatasetExporter(ExportConfig(export_root=export_dir, verifier=AcceptAllVerifier()))
    return exporter.export(candidates)


def _write_raw_export(export_dir: Path, sft_rows: list[dict], dpo_rows: list[dict]) -> None:
    """Write export files directly (bypasses the exporter's own privacy gate)."""
    export_dir.mkdir(parents=True, exist_ok=True)
    sft_text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in sft_rows)
    dpo_text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in dpo_rows)
    (export_dir / "sft_examples.jsonl").write_text(sft_text, encoding="utf-8")
    (export_dir / "dpo_pairs.jsonl").write_text(dpo_text, encoding="utf-8")
    examples_by_skill: dict[str, int] = {}
    for r in sft_rows:
        examples_by_skill[r["skill_name"]] = examples_by_skill.get(r["skill_name"], 0) + 1
    pairs_by_skill: dict[str, int] = {}
    for r in dpo_rows:
        pairs_by_skill[r["skill_name"]] = pairs_by_skill.get(r["skill_name"], 0) + 1
    report = {
        "total_sft_examples": len(sft_rows),
        "total_dpo_pairs": len(dpo_rows),
        "examples_by_skill": examples_by_skill,
        "pairs_by_skill": pairs_by_skill,
        "ready_for_finetuning": False,
        "minimum_examples_per_skill": 50,
    }
    (export_dir / "dataset_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )


def _registry(tmp_path: Path, artifact_root: Path | None = None, **kwargs):
    ledger = tmp_path / "ledger_v2.jsonl"
    store = InMemoryModelStore(persist_path=tmp_path / "registry.jsonl")
    kwargs.setdefault("known_consumers", {CONSUMER})
    kwargs.setdefault("authorized_approvers", {"human:kunal"})
    reg = ModelRegistry(
        store=store,
        writer=LedgerWriter(ledger),
        clock=_fixed_clock,
        artifact_root=artifact_root,
        **kwargs,
    )
    return reg, ledger, store


class _StubCandidateEvaluator:
    """Forces a deterministic win/lose outcome (DI to control approval readiness)."""

    def __init__(self, *, wins: bool) -> None:
        self._wins = wins

    def evaluate_candidate(self, candidate, baseline, holdout) -> CandidateEvaluation:
        # Real reports (correct model_id) so the registry accepts the evaluation.
        cand = OfflineEvaluator().evaluate(candidate, holdout)
        base = OfflineEvaluator().evaluate(baseline, holdout)
        sign = 1.0 if self._wins else -1.0
        dims = ("accuracy", "pass_rate", "rubric_score")
        return CandidateEvaluation(
            candidate_report=cand,
            baseline_report=base,
            metric_deltas={d: round(sign * 0.1, 6) for d in dims},
            dimensions=dims,
            dimensions_total=len(dims),
            dimensions_won=len(dims) if self._wins else 0,
            candidate_wins=self._wins,
            holdout_id=cand.holdout_id,
            created_at=FIXED_TS,
        )


# ── 1. Accepted dataset produces a plan ────────────────────────────────────────


def test_accepted_dataset_produces_plan(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    manifest = planner.build_manifest(export_dir)
    plan = planner.plan(manifest, artifact_root=artifact_root)

    assert plan.prototype is True
    assert plan.training_run_id.startswith("ftrun-")
    assert plan.base_model == "Qwen2.5-Coder-7B-Instruct"
    assert plan.training_method is TrainingMethod.sft_then_dpo  # dpo present
    assert plan.sft_example_count == 8
    assert plan.dpo_pair_count == 2
    assert set(plan.skills) == {"pr_review_skill", "qa_skill"}
    assert plan.estimated_tokens > 0
    assert plan.estimated_cost_usd > 0.0
    assert plan.approval_required is True
    assert plan.risk_tier.value == "T3"
    # Output location is confined beneath the artifact root.
    assert Path(plan.output_artifact_location).resolve().is_relative_to(artifact_root.resolve())


# ── 2. Tampered dataset rejected ───────────────────────────────────────────────


def test_tampered_dataset_rejected(tmp_path):
    export_dir = tmp_path / "dataset"
    _build_export(export_dir, n_sft=8, n_dpo=2)

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    manifest = planner.build_manifest(export_dir)

    # Modify a file AFTER the manifest snapshot.
    sft_path = export_dir / "sft_examples.jsonl"
    sft_path.write_text(sft_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(DatasetIntegrityError):
        planner.verify_manifest(manifest)
    with pytest.raises(DatasetIntegrityError):
        planner.plan(manifest, artifact_root=tmp_path / "artifacts")


# ── 3. Insufficient dataset rejected ───────────────────────────────────────────


def test_insufficient_dataset_rejected(tmp_path):
    export_dir = tmp_path / "dataset"
    _build_export(export_dir, n_sft=2, n_dpo=0)  # below the prototype min of 6

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    manifest = planner.build_manifest(export_dir)
    assert manifest.total_examples == 2
    with pytest.raises(DatasetInsufficientError):
        planner.plan(manifest, artifact_root=tmp_path / "artifacts")


# ── 4. Privacy rejection (defence-in-depth over exported content) ───────────────


def test_privacy_rejection(tmp_path):
    export_dir = tmp_path / "dataset"
    leaked = "Approve. key sk-ant-api03-ABCDEFGHIJKLMNOP1234 was committed."
    sft_rows = [
        {
            "input": "Review the auth PR.",
            "output": leaked,
            "skill_name": "pr_review_skill",
            "source_events": ["evt-1"],
        }
    ]
    _write_raw_export(export_dir, sft_rows, dpo_rows=[])

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetPrivacyError):
        planner.plan(manifest, artifact_root=tmp_path / "artifacts")


# ── 5. Provenance rejection ────────────────────────────────────────────────────


def test_provenance_rejection(tmp_path):
    export_dir = tmp_path / "dataset"
    sft_rows = [
        {
            "input": "Review the cache PR.",
            "output": "Risk LOW. Looks correct; add a regression test.",
            "skill_name": "pr_review_skill",
            # NOTE: no source_events → provenance gate must fire.
        }
    ]
    _write_raw_export(export_dir, sft_rows, dpo_rows=[])

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError):
        planner.plan(manifest, artifact_root=tmp_path / "artifacts")


# ── 6. Deterministic plan generation ───────────────────────────────────────────


def test_deterministic_plan_generation(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)

    p1 = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    p2 = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    plan_a = p1.plan(p1.build_manifest(export_dir), artifact_root=artifact_root)
    plan_b = p2.plan(p2.build_manifest(export_dir), artifact_root=artifact_root)
    assert plan_a == plan_b
    assert plan_a.model_dump() == plan_b.model_dump()


# ── 7. Stable configuration hash ───────────────────────────────────────────────


def test_stable_configuration_hash(tmp_path):
    export_dir = tmp_path / "dataset"
    _build_export(export_dir, n_sft=8, n_dpo=2)

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    manifest = planner.build_manifest(export_dir)
    plan = planner.plan(manifest, artifact_root=tmp_path / "artifacts")

    recomputed = compute_config_hash(
        base_model=plan.base_model,
        dataset_hash=manifest.dataset_hash,
        training_method=plan.training_method,
        hyperparameters=HyperparameterProposal(method=plan.training_method),
        sft_count=manifest.sft_count,
        dpo_count=manifest.dpo_count,
        skills=manifest.skills,
    )
    assert plan.config_hash == recomputed
    assert len(plan.config_hash) == 64


# ── 8. Dry-run performs no external (socket) call ──────────────────────────────


def test_dry_run_no_external_call(tmp_path, monkeypatch):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, _, _ = _registry(tmp_path, artifact_root=artifact_root)

    def _no_sockets(*a, **k):
        raise AssertionError("network socket opened during a dry-run prototype")

    monkeypatch.setattr(socket, "socket", _no_sockets)

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    result = pipeline.run(export_dir, dry_run=True)
    assert result.training_result.status is TrainingStatus.dry_run
    # Dry-run writes no artifact.
    assert not any(artifact_root.rglob("adapter.mock.json"))


# ── 9. Mock runner produces a deterministic result ─────────────────────────────


def test_mock_runner_deterministic(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    _build_export(export_dir, n_sft=8, n_dpo=2)

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    plan = planner.plan(planner.build_manifest(export_dir), artifact_root=artifact_root)

    runner = OfflineMockRunner(artifact_root, clock=_fixed_clock)

    # Dry-run: nothing written, deterministic empty result.
    dry = runner.run(plan, dry_run=True)
    assert dry.status is TrainingStatus.dry_run
    assert dry.adapter_path is None and dry.adapter_hash is None
    assert dry.trained_examples == 0
    assert not any(artifact_root.rglob("adapter.mock.json"))

    # Mock materialisation: deterministic adapter hash across runs.
    r1 = runner.run(plan, dry_run=False)
    r2 = runner.run(plan, dry_run=False)
    assert r1.status is TrainingStatus.mock_done
    assert r1.adapter_hash == r2.adapter_hash
    assert r1.trained_examples == plan.sft_example_count + plan.dpo_pair_count
    assert Path(r1.adapter_path).exists()


# ── 10. Baseline comparison ────────────────────────────────────────────────────


def test_baseline_comparison(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    plan = planner.plan(planner.build_manifest(export_dir), artifact_root=artifact_root)

    # A registered candidate record to score (built the way the pipeline does).
    runner = OfflineMockRunner(artifact_root, clock=_fixed_clock)
    mock = runner.run(plan, dry_run=True)
    reg, _, _ = _registry(tmp_path, artifact_root=artifact_root)
    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    candidate = pipeline._build_candidate(plan, mock)

    baseline = default_baseline_record(CONSUMER, clock=_fixed_clock)
    evaluation = OfflineCandidateEvaluator(clock=_fixed_clock).evaluate_candidate(
        candidate, baseline, default_pr_review_holdout()
    )
    assert evaluation.dimensions_total == 3
    assert set(evaluation.metric_deltas) == {"accuracy", "pass_rate", "rubric_score"}
    assert 0 <= evaluation.dimensions_won <= 3
    assert evaluation.candidate_wins == (evaluation.dimensions_won >= 2)
    # Deterministic: same inputs → same verdict.
    again = OfflineCandidateEvaluator(clock=_fixed_clock).evaluate_candidate(
        candidate, baseline, default_pr_review_holdout()
    )
    assert again.metric_deltas == evaluation.metric_deltas


# ── 11. Failed evaluation prevents approval readiness ──────────────────────────


def test_failed_evaluation_prevents_approval(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, _, _ = _registry(tmp_path, artifact_root=artifact_root)

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        candidate_evaluator=_StubCandidateEvaluator(wins=False),
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    result = pipeline.run(export_dir, dry_run=True)
    assert result.evaluation.candidate_wins is False
    assert result.approval_requested is False
    assert result.candidate.status is ModelStatus.evaluated   # never advanced
    assert reg.get_active_model(CONSUMER) is None


# ── 12. Successful evaluation registers a candidate (awaiting approval) ─────────


def test_successful_evaluation_registers_candidate(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, _, _ = _registry(tmp_path, artifact_root=artifact_root)

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        candidate_evaluator=_StubCandidateEvaluator(wins=True),
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    result = pipeline.run(export_dir, dry_run=True)
    assert result.registered is True
    assert result.approval_requested is True
    assert result.candidate.status is ModelStatus.awaiting_approval
    # Present in the registry under the consumer.
    ids = {r.model_id for r in reg.list_versions(CONSUMER)}
    assert result.candidate.model_id in ids


# ── 13. Registry retains dataset provenance ────────────────────────────────────


def test_registry_retains_dataset_provenance(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, _, _ = _registry(tmp_path, artifact_root=artifact_root)

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        candidate_evaluator=_StubCandidateEvaluator(wins=True),
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    result = pipeline.run(export_dir, dry_run=True)
    cand = result.candidate
    plan = result.plan
    assert cand.dataset_id == plan.dataset_id
    assert cand.dataset_hash == plan.dataset_hash
    assert cand.training_run_id == plan.training_run_id
    assert cand.training_config_hash == plan.config_hash
    assert cand.metadata.get("prototype") is True


# ── 14. Candidate is not activated ─────────────────────────────────────────────


@pytest.mark.parametrize("wins", [True, False])
def test_candidate_never_activated(tmp_path, wins):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, _, _ = _registry(tmp_path, artifact_root=artifact_root)

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        candidate_evaluator=_StubCandidateEvaluator(wins=wins),
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    result = pipeline.run(export_dir, dry_run=True)
    assert result.activated is False
    assert result.candidate.status is not ModelStatus.active
    assert reg.get_active_model(CONSUMER) is None


# ── 15. No production router change (no active model ever) ─────────────────────


def test_no_production_router_change(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, _, _ = _registry(tmp_path, artifact_root=artifact_root)

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        candidate_evaluator=_StubCandidateEvaluator(wins=True),
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    pipeline.run(export_dir, dry_run=True)
    # The only states reachable by the prototype are pre-activation states.
    allowed = {ModelStatus.registered, ModelStatus.evaluated, ModelStatus.awaiting_approval}
    statuses = {r.status for r in reg.list_versions(CONSUMER)}
    assert statuses <= allowed
    assert reg.get_active_model(CONSUMER) is None


# ── 16. Work Ledger lifecycle events emitted ───────────────────────────────────


def test_work_ledger_events_emitted(tmp_path):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, ledger, _ = _registry(tmp_path, artifact_root=artifact_root)

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        candidate_evaluator=_StubCandidateEvaluator(wins=True),
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    pipeline.run(export_dir, dry_run=True)

    events = [e for e in LedgerReader(v2_path=ledger).v2_events()
              if isinstance(e, ModelLifecycleEvent)]
    transitions = {(e.from_status, e.to_status) for e in events}
    assert (None, "registered") in transitions
    assert ("registered", "evaluated") in transitions
    assert ("evaluated", "awaiting_approval") in transitions
    # The prototype NEVER approves or activates.
    assert not any(e.to_status in {"approved", "active"} for e in events)
    assert all(e.production_consumer == CONSUMER for e in events)


# ── 17. Artifact paths confined ────────────────────────────────────────────────


@pytest.mark.parametrize("dry_run", [True, False])
def test_artifact_paths_confined(tmp_path, dry_run):
    export_dir = tmp_path / "dataset"
    plan_root = tmp_path / "elsewhere"     # the plan points HERE
    runner_root = tmp_path / "artifacts"   # the runner is confined HERE
    runner_root.mkdir(parents=True, exist_ok=True)
    _build_export(export_dir, n_sft=8, n_dpo=2)

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    plan = planner.plan(planner.build_manifest(export_dir), artifact_root=plan_root)

    runner = OfflineMockRunner(runner_root, clock=_fixed_clock)
    with pytest.raises(ArtifactPathError):
        runner.run(plan, dry_run=dry_run)


# ── 18. Persistence failure fails closed ───────────────────────────────────────


def test_persistence_failure_fails_closed(tmp_path, monkeypatch):
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, _, store = _registry(tmp_path, artifact_root=artifact_root)

    def _boom() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_flush", _boom)

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    with pytest.raises(RegistryPersistenceError):
        pipeline.run(export_dir, dry_run=True)
    # Fail-closed: nothing committed to the store.
    assert len(store) == 0
    assert reg.get_active_model(CONSUMER) is None


# ── Codex re-audit regressions ─────────────────────────────────────────────────
#
# These lock in the behaviours that green tests previously missed. They are
# written to FAIL against the pre-fix code and PASS only with the fixes in place.


def _write_matching_ledger(ledger_path: Path, *, n_sft: int = 8, n_dpo: int = 2) -> LedgerWriter:
    """
    Write REAL Work Ledger v2 events whose ``event_id``s are exactly the ones
    the Priority-3 export cites for each task: an ``OutcomeRecorded`` per SFT
    task (``evt-sft-NN-outcome``) and a ``CorrectionRecorded`` per DPO task
    (``evt-dpo-NN-correction``). Going through a real ``LedgerWriter`` means
    the verifier is later built from genuinely recorded events, not a fixture
    handed to it directly.
    """
    writer = LedgerWriter(ledger_path)
    for i in range(n_sft):
        task_id = f"sft-{i:02d}"
        # The authorising event records the SAME content_hash the SFT candidate
        # carries, so the planner's row-reconstructed canonical hash binds to it.
        writer.append(
            OutcomeRecorded(
                **make_envelope(
                    task_id=task_id, actor="aria", actor_type=ActorType.aria,
                    event_id=f"evt-{task_id}-outcome", timestamp=FIXED_TS,
                ),
                outcome="approved",
                content_hash=_sft_candidate(i).content_hash,
            )
        )
    for i in range(n_dpo):
        task_id = f"dpo-{i:02d}"
        writer.append(
            CorrectionRecorded(
                **make_envelope(
                    task_id=task_id, actor="human:kunal", actor_type=ActorType.human,
                    event_id=f"evt-{task_id}-correction", timestamp=FIXED_TS,
                ),
                content_hash=_dpo_candidate(i).content_hash,
            )
        )
    return writer


def _ledger_verifier(ledger_path: Path) -> LedgerEventProvenanceVerifier:
    """Build the task-bound verifier by READING the ledger back (not the export)."""
    return LedgerEventProvenanceVerifier.from_ledger_events(
        LedgerReader(v2_path=ledger_path).v2_events()
    )


# F5 — the manifest is derived from PHYSICAL rows; the report must AGREE exactly,
# and provenance must be corroborated against the ledger, TASK-BOUND (fail closed).


def test_f5_report_total_count_mismatch_rejected(tmp_path):
    """A report that overstates the SFT count vs the physical rows is rejected."""
    export_dir = tmp_path / "dataset"
    _build_export(export_dir, n_sft=8, n_dpo=2)

    report_path = export_dir / "dataset_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["total_sft_examples"] = report["total_sft_examples"] + 5  # physically false
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    with pytest.raises(DatasetIntegrityError):
        planner.build_manifest(export_dir)


def test_f5_report_per_skill_mismatch_rejected(tmp_path):
    """A report whose examples_by_skill disagrees with the rows is rejected."""
    export_dir = tmp_path / "dataset"
    _build_export(export_dir, n_sft=8, n_dpo=2)

    report_path = export_dir / "dataset_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["examples_by_skill"] = {"totally_made_up_skill": report["total_sft_examples"]}
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    with pytest.raises(DatasetIntegrityError):
        planner.build_manifest(export_dir)


def test_f5_missing_skill_name_rejected(tmp_path):
    """An SFT row with no skill_name cannot be attributed → fail closed."""
    export_dir = tmp_path / "dataset"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "sft_examples.jsonl").write_text(
        json.dumps({"input": "Review.", "output": "LOW.", "source_events": ["evt-1"]}) + "\n",
        encoding="utf-8",
    )
    (export_dir / "dpo_pairs.jsonl").write_text("", encoding="utf-8")
    (export_dir / "dataset_report.json").write_text(
        json.dumps(
            {
                "total_sft_examples": 1,
                "total_dpo_pairs": 0,
                "examples_by_skill": {},
                "pairs_by_skill": {},
                "ready_for_finetuning": False,
                "minimum_examples_per_skill": 50,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=AcceptAllPlanProvenance())
    with pytest.raises(DatasetIntegrityError):
        planner.build_manifest(export_dir)


def test_f5_missing_provenance_verifier_fails_closed(tmp_path):
    """A planner with NO provenance verifier refuses to plan (ledger gate 3b)."""
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)

    planner = FineTuningPlanner(clock=_fixed_clock)  # deliberately no verifier
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError):
        planner.plan(manifest, artifact_root=artifact_root)


def test_f5_real_ledger_provenance_accepted(tmp_path):
    """
    The full real path: write events with a real LedgerWriter, read them back
    with LedgerReader, build the task-bound verifier from those events, and the
    planner accepts an export whose every citation is task-local + authorising.
    """
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    _write_matching_ledger(ledger_path, n_sft=8, n_dpo=2)

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)
    plan = planner.plan(manifest, artifact_root=artifact_root)
    assert plan.sft_example_count == 8
    assert plan.dpo_pair_count == 2


def test_f5_cross_task_provenance_rejected(tmp_path):
    """
    Codex's exact exploit: an example for task A citing a REAL event that
    belongs to task B. The event exists globally, but a task-bound verifier
    rejects the borrowed citation.
    """
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"

    # Two real tasks, each with its own real outcome event.
    writer = LedgerWriter(ledger_path)
    for task_id in ("sft-00", "sft-01"):
        writer.append(
            OutcomeRecorded(
                **make_envelope(
                    task_id=task_id, actor="aria", actor_type=ActorType.aria,
                    event_id=f"evt-{task_id}-outcome", timestamp=FIXED_TS,
                ),
                outcome="approved",
            )
        )
    # Export row for sft-00 borrows sft-01's real event.
    _write_raw_export(
        export_dir,
        sft_rows=[{
            "task_id": "sft-00",
            "skill_name": "pr_review_skill",
            "input": "Review PR #100.",
            "output": "Risk LOW.",
            "source_events": ["evt-sft-01-outcome"],
        }],
        dpo_rows=[],
    )

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError, match="cross-task"):
        planner.plan(manifest, artifact_root=artifact_root)


def test_f5_fabricated_provenance_rejected(tmp_path):
    """A citation to an event that exists in NO task is rejected as fabricated."""
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"

    writer = LedgerWriter(ledger_path)
    writer.append(
        OutcomeRecorded(
            **make_envelope(
                task_id="sft-00", actor="aria", actor_type=ActorType.aria,
                event_id="evt-sft-00-outcome", timestamp=FIXED_TS,
            ),
            outcome="approved",
        )
    )
    _write_raw_export(
        export_dir,
        sft_rows=[{
            "task_id": "sft-00",
            "skill_name": "pr_review_skill",
            "input": "Review PR #100.",
            "output": "Risk LOW.",
            "source_events": ["evt-totally-fabricated"],
        }],
        dpo_rows=[],
    )

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError, match="fabricated"):
        planner.plan(manifest, artifact_root=artifact_root)


def test_f5_inappropriate_event_type_rejected(tmp_path):
    """
    A citation to a real, task-local event of a NON-authorising type
    (skill_invoked) is rejected — only learning-outcome events may authorise
    training provenance.
    """
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"

    writer = LedgerWriter(ledger_path)
    writer.append(
        SkillInvoked(
            **make_envelope(
                task_id="sft-00", actor="aria", actor_type=ActorType.aria,
                event_id="evt-sft-00-skill", timestamp=FIXED_TS,
            ),
            skill_name="pr_review_skill",
        )
    )
    _write_raw_export(
        export_dir,
        sft_rows=[{
            "task_id": "sft-00",
            "skill_name": "pr_review_skill",
            "input": "Review PR #100.",
            "output": "Risk LOW.",
            "source_events": ["evt-sft-00-skill"],
        }],
        dpo_rows=[],
    )

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError, match="authorise training provenance"):
        planner.plan(manifest, artifact_root=artifact_root)


def test_f5_unknown_task_provenance_rejected(tmp_path):
    """An example whose task_id has NO events in the ledger fails closed."""
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"

    # Ledger knows only sft-00; the export row belongs to an unknown task.
    writer = LedgerWriter(ledger_path)
    writer.append(
        OutcomeRecorded(
            **make_envelope(
                task_id="sft-00", actor="aria", actor_type=ActorType.aria,
                event_id="evt-sft-00-outcome", timestamp=FIXED_TS,
            ),
            outcome="approved",
        )
    )
    _write_raw_export(
        export_dir,
        sft_rows=[{
            "task_id": "ghost-99",
            "skill_name": "pr_review_skill",
            "input": "Review PR #100.",
            "output": "Risk LOW.",
            "source_events": ["evt-sft-00-outcome"],
        }],
        dpo_rows=[],
    )

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError, match="no events recorded"):
        planner.plan(manifest, artifact_root=artifact_root)


# F1 — CONTENT BINDING. A cited OutcomeRecorded / CorrectionRecorded event only
# authorises the EXACT content it judged. Re-using a real, same-task approval
# marker for DIFFERENT (poisoned) content — or citing a hashless legacy event —
# must fail closed. These reproduce Codex's "TAMPERED_CONTENT_ACCEPTED" exploit
# end-to-end through real LedgerWriter → LedgerReader events.


def test_f1_tampered_content_rejected(tmp_path):
    """
    Poison one exported row's output AFTER export but BEFORE the manifest
    snapshot (so the integrity gate passes over the tampered files), while the
    cited OutcomeRecorded event still records the ORIGINAL content's hash. The
    row-reconstructed canonical hash no longer equals the event's recorded
    hash, so the citation no longer authorises this content.
    """
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    _write_matching_ledger(ledger_path, n_sft=8, n_dpo=2)

    sft_path = export_dir / "sft_examples.jsonl"
    lines = sft_path.read_text(encoding="utf-8").splitlines()
    poisoned = json.loads(lines[0])
    poisoned["output"] = poisoned["output"] + " (silently altered to poison training)"
    lines[0] = json.dumps(poisoned, sort_keys=True)
    sft_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)  # snapshots tampered files → integrity OK
    with pytest.raises(DatasetProvenanceError, match="bound to this example"):
        planner.plan(manifest, artifact_root=artifact_root)


def test_f1_hashless_event_fails_closed(tmp_path):
    """
    A ledger whose authorising events recorded NO content_hash (legacy /
    pre-binding). They are real, task-local, and of an authorising type — but a
    hashless event cannot bind to any exported content, so it must fail closed
    rather than authorise by type alone.
    """
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"
    _build_export(export_dir, n_sft=8, n_dpo=2)

    writer = LedgerWriter(ledger_path)
    for i in range(8):
        task_id = f"sft-{i:02d}"
        writer.append(
            OutcomeRecorded(
                **make_envelope(
                    task_id=task_id, actor="aria", actor_type=ActorType.aria,
                    event_id=f"evt-{task_id}-outcome", timestamp=FIXED_TS,
                ),
                outcome="approved",  # NOTE: no content_hash → hashless legacy event
            )
        )
    for i in range(2):
        task_id = f"dpo-{i:02d}"
        writer.append(
            CorrectionRecorded(
                **make_envelope(
                    task_id=task_id, actor="human:kunal", actor_type=ActorType.human,
                    event_id=f"evt-{task_id}-correction", timestamp=FIXED_TS,
                )
            )
        )

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError, match="bound to this example"):
        planner.plan(manifest, artifact_root=artifact_root)


# F3 — DPO CHOSEN BINDING. The reconstructed canonical hash binds the DPO
# `correction` (the ledger-authorised corrected output), but the preferred
# response DPO actually trains toward is `chosen`. A row that keeps a valid,
# ledger-bound `correction` while swapping ONLY `chosen` poisons what training
# optimises for and must be rejected. Reproduces Codex's
# "TAMPERED_DPO_CHOSEN_ACCEPTED" exploit end-to-end through real
# LedgerWriter → LedgerReader events.


def test_f3_tampered_dpo_chosen_rejected(tmp_path):
    """
    Poison ONLY the `chosen` field of one DPO pair AFTER export but BEFORE the
    manifest snapshot (so the integrity gate passes over the tampered file),
    leaving the ledger-authorised `correction` untouched. Pre-fix the canonical
    hash ignored `chosen`, so the citation still bound and the poisoned preferred
    response was accepted. Now `chosen != correction` fails closed.
    """
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    _write_matching_ledger(ledger_path, n_sft=8, n_dpo=2)

    dpo_path = export_dir / "dpo_pairs.jsonl"
    lines = dpo_path.read_text(encoding="utf-8").splitlines()
    poisoned = json.loads(lines[0])
    # Keep `correction` (ledger-bound) intact; swap ONLY the preferred response.
    poisoned["chosen"] = poisoned["chosen"] + " (silently altered preferred response)"
    lines[0] = json.dumps(poisoned, sort_keys=True)
    dpo_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)  # snapshots tampered file → integrity OK
    with pytest.raises(DatasetProvenanceError, match="chosen != correction"):
        planner.plan(manifest, artifact_root=artifact_root)


# F2 — IDENTIFIER NON-COERCION. Structural identifiers (task_id, each cited
# source event) must be validated as non-empty strings BEFORE the verifier is
# consulted. Pre-fix the planner str()-coerced them, letting an integer 123
# masquerade as the ledger's string event id "123".


def test_f2_non_string_source_event_not_coerced(tmp_path):
    """An integer source-event id is rejected, NOT coerced into the string id."""
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"

    cand = _sft_candidate(0)  # task sft-00, pr_review_skill, privacy-safe content
    writer = LedgerWriter(ledger_path)
    writer.append(
        OutcomeRecorded(
            **make_envelope(
                task_id=cand.task_id, actor="aria", actor_type=ActorType.aria,
                event_id="123", timestamp=FIXED_TS,
            ),
            outcome="approved",
            content_hash=cand.content_hash,
        )
    )
    # The row cites its real authorising event by INTEGER 123 (not "123").
    _write_raw_export(
        export_dir,
        sft_rows=[{
            "task_id": cand.task_id,
            "skill_name": cand.skill_name,
            "input": cand.input_text,
            "output": cand.output_text,
            "source_events": [123],
        }],
        dpo_rows=[],
    )

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError, match="non-string or empty source event id"):
        planner.plan(manifest, artifact_root=artifact_root)


def test_f2_non_string_task_id_not_coerced(tmp_path):
    """An integer task_id is rejected, NOT coerced into the string task id."""
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    ledger_path = tmp_path / "ledger_v2.jsonl"

    input_text = "Review PR #100: adds a guard to the ranker path."
    output_text = "Risk LOW. Branch is guarded; add one regression test before merge."
    chash = canonical_content_hash(
        task_id="5", skill_name="pr_review_skill",
        input_text=input_text, output_text=output_text,
        rejected_output=None, corrected_output=None,
    )
    writer = LedgerWriter(ledger_path)
    writer.append(
        OutcomeRecorded(
            **make_envelope(
                task_id="5", actor="aria", actor_type=ActorType.aria,
                event_id="evt-5-outcome", timestamp=FIXED_TS,
            ),
            outcome="approved",
            content_hash=chash,
        )
    )
    # The row's task_id is the INTEGER 5; the ledger task is the STRING "5".
    _write_raw_export(
        export_dir,
        sft_rows=[{
            "task_id": 5,
            "skill_name": "pr_review_skill",
            "input": input_text,
            "output": output_text,
            "source_events": ["evt-5-outcome"],
        }],
        dpo_rows=[],
    )

    verifier = _ledger_verifier(ledger_path)
    planner = FineTuningPlanner(clock=_fixed_clock, provenance_verifier=verifier)
    manifest = planner.build_manifest(export_dir)
    with pytest.raises(DatasetProvenanceError, match="non-string or empty task_id"):
        planner.plan(manifest, artifact_root=artifact_root)


# F6 — the prototype leaves the consumer's active model EXACTLY as it found it,
# including the legitimate case where the consumer already has an active model.


def _activate_incumbent(reg, artifact_root: Path, *, model_id="incumbent-1_0_0") -> str:
    """Drive a real model to ACTIVE for CONSUMER (a pre-existing production model)."""
    artifact_root.mkdir(parents=True, exist_ok=True)
    art = artifact_root / f"{model_id}.bin"
    art.write_text("INCUMBENT-MOCK-WEIGHTS", encoding="utf-8")
    digest = hashlib.sha256(art.read_bytes()).hexdigest()
    record = ModelRecord(
        model_id=model_id,
        model_name="pr_review_specialist",
        semantic_version="1.0.0",
        provider=ModelProvider.prototype,
        model_type=ModelType.fine_tuned,
        base_model="Qwen2.5-Coder-7B-Instruct",
        artifact_path=str(art),
        artifact_hash=digest,
        dataset_id="ds-incumbent",
        dataset_hash="c" * 64,
        created_by="aria",
        created_at=FIXED_TS,
        production_consumer=CONSUMER,
    )
    reg.register_model(record)
    reg.record_evaluation(
        record.model_id, OfflineEvaluator().evaluate(record, default_pr_review_holdout())
    )
    reg.request_approval(record.model_id)
    reg.approve_model(record.model_id, approver="human:kunal")
    reg.activate_model(record.model_id)
    return record.model_id


def test_f6_preexisting_active_model_left_unchanged(tmp_path):
    """
    With a consumer that ALREADY has an active production model, the prototype
    must still run, must NOT change the active model, and must NOT activate its
    candidate. (The pre-fix invariant asserted 'no active model' and would have
    wrongly rejected this legitimate state.)
    """
    export_dir = tmp_path / "dataset"
    artifact_root = tmp_path / "artifacts"
    _build_export(export_dir, n_sft=8, n_dpo=2)
    reg, _, _ = _registry(tmp_path, artifact_root=artifact_root)

    incumbent_id = _activate_incumbent(reg, artifact_root)
    assert reg.get_active_model(CONSUMER).model_id == incumbent_id

    pipeline = FineTuningPipeline(
        reg, artifact_root=artifact_root, production_consumer=CONSUMER,
        candidate_evaluator=_StubCandidateEvaluator(wins=True),
        provenance_verifier=AcceptAllPlanProvenance(), clock=_fixed_clock,
    )
    result = pipeline.run(export_dir, dry_run=True)

    active_after = reg.get_active_model(CONSUMER)
    assert active_after is not None
    assert active_after.model_id == incumbent_id        # untouched
    assert result.candidate.model_id != incumbent_id
    assert result.candidate.status is ModelStatus.awaiting_approval
    assert result.activated is False
