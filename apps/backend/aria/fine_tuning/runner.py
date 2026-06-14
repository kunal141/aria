"""
Fine-Tuning Prototype — offline mock runner + pipeline orchestrator.

PROTOTYPE ONLY. The default runner performs NO real training: no GPU, no
model download, no paid API, no network socket. ``dry_run=True`` (the
default) validates the plan and produces a deterministic ``dry_run``
result that writes nothing. ``dry_run=False`` still runs fully offline —
it writes a tiny, clearly-labelled MOCK adapter placeholder (NOT real
weights) inside the confined artifact root so the registry's
artifact-hash path can be exercised.

A real trainer plugs in by dependency injection: anything satisfying the
``TrainingRunner`` protocol can replace ``OfflineMockRunner`` without
touching the pipeline. The default is, and stays, the offline mock.

``FineTuningPipeline`` ties it together:

    build manifest -> plan -> (mock) run -> build candidate ModelRecord
    -> register -> record evaluation -> if candidate wins, request approval

The pipeline NEVER approves, activates, deploys, or routes traffic. It
asserts the consumer still has no active model on the way out — the
candidate is left in ``evaluated`` or ``awaiting_approval`` only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable

from aria.model_registry import (
    ModelProvider,
    ModelRecord,
    ModelRegistry,
    ModelStatus,
    ModelType,
)
from aria.model_registry.evaluator import HoldoutExample
from aria.fine_tuning.evaluator import (
    CandidateEvaluation,
    CandidateEvaluatorProtocol,
    OfflineCandidateEvaluator,
    default_baseline_record,
    default_holdout,
)
from aria.fine_tuning.models import (
    ArtifactPathError,
    FineTuningPlan,
    MockTrainingResult,
    TrainingRunError,
    TrainingStatus,
    utc_now,
)
from aria.fine_tuning.planner import FineTuningPlanner, PlanProvenanceVerifier


# ── Runner protocol + offline mock ────────────────────────────────────────────


@runtime_checkable
class TrainingRunner(Protocol):
    """A trainer. The future real trainer is a drop-in replacement."""
    def run(self, plan: FineTuningPlan, *, dry_run: bool = True) -> MockTrainingResult: ...


class OfflineMockRunner:
    """
    Deterministic, fully-offline runner. Default mode (``dry_run=True``)
    trains nothing and writes nothing. ``dry_run=False`` writes a labelled
    mock placeholder under the confined artifact root.
    """

    def __init__(
        self,
        artifact_root: Path,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._artifact_root = Path(artifact_root)
        self._clock = clock

    def run(self, plan: FineTuningPlan, *, dry_run: bool = True) -> MockTrainingResult:
        # Always confine the plan's output location — even in dry-run, an
        # out-of-root location is a hard error (fail closed).
        out_dir = self._confine(plan.output_artifact_location)

        if dry_run:
            return MockTrainingResult(
                training_run_id=plan.training_run_id,
                status=TrainingStatus.dry_run,
                base_model=plan.base_model,
                dataset_hash=plan.dataset_hash,
                adapter_path=None,
                adapter_hash=None,
                trained_examples=0,
                config_hash=plan.config_hash,
                created_at=self._clock(),
                notes="Dry-run: plan validated, no training performed, no artifact written.",
            )

        # Offline mock materialisation — a deterministic placeholder, never weights.
        out_dir.mkdir(parents=True, exist_ok=True)
        adapter_path = out_dir / "adapter.mock.json"
        payload = json.dumps(
            {
                "prototype": True,
                "training_run_id": plan.training_run_id,
                "config_hash": plan.config_hash,
                "base_model": plan.base_model,
                "dataset_hash": plan.dataset_hash,
                "note": "MOCK ADAPTER PLACEHOLDER — NOT REAL MODEL WEIGHTS.",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        adapter_path.write_text(payload, encoding="utf-8")
        adapter_hash = hashlib.sha256(adapter_path.read_bytes()).hexdigest()

        return MockTrainingResult(
            training_run_id=plan.training_run_id,
            status=TrainingStatus.mock_done,
            base_model=plan.base_model,
            dataset_hash=plan.dataset_hash,
            adapter_path=str(adapter_path),
            adapter_hash=adapter_hash,
            trained_examples=plan.sft_example_count + plan.dpo_pair_count,
            config_hash=plan.config_hash,
            created_at=self._clock(),
        )

    def _confine(self, location: str) -> Path:
        """Resolve ``location`` and fail closed if it escapes the artifact root."""
        resolved = Path(location).resolve()
        root = self._artifact_root.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ArtifactPathError(
                f"Plan output location {location!r} resolves outside artifact "
                f"root {root}."
            )
        return resolved


# ── Pipeline result ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineResult:
    """Everything the prototype produced, for the demo/tests to inspect."""
    plan:                FineTuningPlan
    training_result:     MockTrainingResult
    evaluation:          CandidateEvaluation
    candidate:           ModelRecord
    production_consumer: str
    registered:          bool
    approval_requested:  bool
    activated:           bool = False   # invariant: ALWAYS False


# ── Pipeline ──────────────────────────────────────────────────────────────────


class FineTuningPipeline:
    """
    Orchestrates plan -> mock-train -> register -> evaluate -> (request approval).

    Dependency-injected components default to the offline implementations.
    The ``registry`` is required — it must be constructed by the caller with
    the consumer in ``known_consumers`` and (for ledger evidence) a Work
    Ledger writer.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        artifact_root: Path,
        planner: Optional[FineTuningPlanner] = None,
        runner: Optional[TrainingRunner] = None,
        candidate_evaluator: Optional[CandidateEvaluatorProtocol] = None,
        holdout: Optional[list[HoldoutExample]] = None,
        production_consumer: str = "pr_review_skill",
        model_name: str = "pr_review_specialist",
        semantic_version: str = "0.1.0",
        base_model: Optional[str] = None,
        provenance_verifier: Optional[PlanProvenanceVerifier] = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._registry = registry
        self._artifact_root = Path(artifact_root)
        # When the pipeline builds its own planner, it must forward the
        # provenance verifier — otherwise the auto-built planner would fail
        # closed on the ledger-backed provenance gate. A caller-supplied
        # ``planner`` is used as-is (its own verifier is the caller's choice).
        self._planner = (
            planner if planner is not None
            else FineTuningPlanner(clock=clock, provenance_verifier=provenance_verifier)
        )
        self._runner = runner if runner is not None else OfflineMockRunner(artifact_root, clock=clock)
        self._candidate_evaluator = (
            candidate_evaluator if candidate_evaluator is not None
            else OfflineCandidateEvaluator(clock=clock)
        )
        self._holdout = holdout if holdout is not None else default_holdout()
        self._consumer = production_consumer
        self._model_name = model_name
        self._semantic_version = semantic_version
        self._base_model = base_model
        self._clock = clock

    def run(
        self,
        export_dir: Path,
        *,
        dry_run: bool = True,
    ) -> PipelineResult:
        # Capture the consumer's active model BEFORE doing anything. The
        # prototype's safety invariant is that it leaves the active model
        # exactly as it found it — NOT merely that "no model is active". A
        # consumer may legitimately already have an active production model;
        # the prototype must neither replace it nor activate its candidate.
        active_before = self._registry.get_active_model(self._consumer)
        before_id = active_before.model_id if active_before is not None else None

        manifest = self._planner.build_manifest(export_dir)
        plan = self._planner.plan(
            manifest,
            artifact_root=self._artifact_root,
            base_model=self._base_model,
        )
        result = self._runner.run(plan, dry_run=dry_run)
        if result.status is TrainingStatus.failed:
            raise TrainingRunError(f"Mock training run {result.training_run_id} failed.")

        candidate = self._build_candidate(plan, result)
        self._registry.register_model(candidate)

        baseline = default_baseline_record(self._consumer, clock=self._clock)
        evaluation = self._candidate_evaluator.evaluate_candidate(
            candidate, baseline, self._holdout
        )
        self._registry.record_evaluation(candidate.model_id, evaluation.candidate_report)

        approval_requested = False
        if evaluation.candidate_wins:
            self._registry.request_approval(candidate.model_id)
            approval_requested = True

        # Invariant: the prototype NEVER changes the consumer's active model —
        # it neither activates its candidate nor disturbs a pre-existing active
        # model. Compare against the snapshot taken on entry, not against "no
        # active model", so a consumer that already had one is handled correctly.
        active_after = self._registry.get_active_model(self._consumer)
        after_id = active_after.model_id if active_after is not None else None
        if after_id != before_id:
            raise TrainingRunError(
                "Invariant violated: the prototype changed the active model for "
                f"consumer {self._consumer!r} (was {before_id!r}, now {after_id!r})."
            )

        final = self._registry.list_versions(self._consumer)
        candidate_final = next(r for r in final if r.model_id == candidate.model_id)

        return PipelineResult(
            plan=plan,
            training_result=result,
            evaluation=evaluation,
            candidate=candidate_final,
            production_consumer=self._consumer,
            registered=True,
            approval_requested=approval_requested,
        )

    def _build_candidate(
        self, plan: FineTuningPlan, result: MockTrainingResult
    ) -> ModelRecord:
        # ``ftrun-<16hex>`` -> ``ftmodel-<16hex>`` (filename-safe).
        suffix = plan.training_run_id.split("-", 1)[1]
        return ModelRecord(
            model_id=f"ftmodel-{suffix}",
            model_name=self._model_name,
            semantic_version=self._semantic_version,
            provider=ModelProvider.prototype,   # NEVER served to prod traffic
            model_type=ModelType.fine_tuned,
            base_model=plan.base_model,
            artifact_path=result.adapter_path,   # None for dry-run
            artifact_hash=result.adapter_hash,    # None for dry-run
            dataset_id=plan.dataset_id,
            dataset_hash=plan.dataset_hash,
            training_run_id=plan.training_run_id,
            training_config_hash=plan.config_hash,
            production_consumer=self._consumer,
            status=ModelStatus.registered,
            created_by="aria",
            created_at=self._clock(),
            metadata={
                "prototype": True,
                "training_method": plan.training_method.value,
                "run_status": result.status.value,
            },
        )
