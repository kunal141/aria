"""
Week 29 Priority 5 — Fine-Tuning Prototype.

PROTOTYPE ONLY. This package proves the Shadow-Learning -> fine-tune pipeline
(CLAUDE.md § 26.6) end-to-end WITHOUT any real training: no paid API call, no
network socket, no model download, no GPU, no production model switch. It reads
an accepted-output dataset produced by the Priority-3 exporter, verifies its
integrity / privacy / provenance, builds a deterministic ``FineTuningPlan``,
runs an offline deterministic mock trainer, evaluates the candidate against a
synthetic baseline on a fixed holdout, and registers the candidate in the
Model-Lifecycle Registry v1 — leaving it in ``evaluated`` or ``awaiting_approval``
and NEVER activating or serving it.

Public surface
--------------
- Models: ``DatasetManifest``, ``FineTuningPlan``, ``HyperparameterProposal``,
  ``EvaluationPlan``, ``MockTrainingResult``, ``TrainingMethod``,
  ``TrainingStatus``, ``compute_dataset_hash``, ``compute_config_hash``
- Planner: ``FineTuningPlanner``, ``FineTuningPolicy``
- Evaluation: ``CandidateEvaluation``, ``CandidateEvaluatorProtocol``,
  ``OfflineCandidateEvaluator``, ``default_baseline_record``, ``default_holdout``
- Runner / pipeline: ``TrainingRunner``, ``OfflineMockRunner``,
  ``FineTuningPipeline``, ``PipelineResult``
- Exceptions: ``FineTuningError`` and its subclasses
"""
from aria.fine_tuning.models import (
    ArtifactPathError,
    DatasetInsufficientError,
    DatasetIntegrityError,
    DatasetManifest,
    DatasetPrivacyError,
    DatasetProvenanceError,
    EvaluationPlan,
    FineTuningError,
    FineTuningPlan,
    HyperparameterProposal,
    MockTrainingResult,
    TrainingMethod,
    TrainingRunError,
    TrainingStatus,
    compute_config_hash,
    compute_dataset_hash,
    utc_now,
)
from aria.fine_tuning.planner import (
    FineTuningPlanner,
    FineTuningPolicy,
    confined_dir,
)
from aria.fine_tuning.evaluator import (
    CandidateEvaluation,
    CandidateEvaluatorProtocol,
    OfflineCandidateEvaluator,
    default_baseline_record,
    default_holdout,
)
from aria.fine_tuning.runner import (
    FineTuningPipeline,
    OfflineMockRunner,
    PipelineResult,
    TrainingRunner,
)

__all__ = [
    # Models
    "DatasetManifest",
    "FineTuningPlan",
    "HyperparameterProposal",
    "EvaluationPlan",
    "MockTrainingResult",
    "TrainingMethod",
    "TrainingStatus",
    "compute_dataset_hash",
    "compute_config_hash",
    "utc_now",
    # Planner
    "FineTuningPlanner",
    "FineTuningPolicy",
    "confined_dir",
    # Evaluation
    "CandidateEvaluation",
    "CandidateEvaluatorProtocol",
    "OfflineCandidateEvaluator",
    "default_baseline_record",
    "default_holdout",
    # Runner / pipeline
    "TrainingRunner",
    "OfflineMockRunner",
    "FineTuningPipeline",
    "PipelineResult",
    # Exceptions
    "FineTuningError",
    "DatasetIntegrityError",
    "DatasetInsufficientError",
    "DatasetPrivacyError",
    "DatasetProvenanceError",
    "ArtifactPathError",
    "TrainingRunError",
]
