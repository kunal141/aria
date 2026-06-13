"""
Model Lifecycle Registry v1 — Week 29 Priority 4.

A minimal, governed MLOps registry that tracks each candidate model through an
explicit lifecycle (register → evaluate → approve → activate → deprecate /
rollback) with immutable versioned records, at-most-one-active-per-consumer
enforcement, path confinement, hash verification, and typed Work Ledger v2
lifecycle events.

This is the concrete artifact that anchors the governed self-improvement loop
(CLAUDE.md § 28.2 behaviour #10) and the home into which the Week 29 Priority 5
fine-tuning prototype registers its candidate. It runs fully offline and holds
no secrets.

Public surface
--------------
- ``ModelRecord``         — immutable, frozen typed model-version contract
- ``ModelStatus`` / ``ModelProvider`` / ``ModelType`` — lifecycle + taxonomy enums
- ``ModelComparison`` / ``compare_records`` — version diff view
- ``can_transition`` / ``is_terminal`` — lifecycle state-machine helpers
- ``InMemoryModelStore`` / ``ModelStore`` — atomic, fail-closed backing store
- ``EvaluationReport`` / ``OfflineEvaluator`` / ``HoldoutExample`` — offline eval
- ``ModelRegistry``       — the 12 governed lifecycle operations
- typed registry exceptions
"""
from aria.model_registry.evaluator import (
    EVALUATOR_VERSION,
    EvaluationReport,
    Evaluator,
    HoldoutExample,
    OfflineEvaluator,
    default_pr_review_holdout,
    holdout_fingerprint,
)
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
    ModelProvider,
    ModelRecord,
    ModelRegistryError,
    ModelStateError,
    ModelStatus,
    ModelType,
    MultipleActiveModelsError,
    RegistryCorruptionError,
    RegistryPersistenceError,
    SelfApprovalError,
    TERMINAL_STATUSES,
    UnauthorizedApproverError,
    UnknownConsumerError,
    can_transition,
    compare_records,
    is_terminal,
    utc_now,
)
from aria.model_registry.registry import ModelRegistry
from aria.model_registry.store import InMemoryModelStore, ModelStore

__all__ = [
    # Records + enums
    "ModelRecord",
    "ModelStatus",
    "ModelProvider",
    "ModelType",
    "ModelComparison",
    "compare_records",
    "can_transition",
    "is_terminal",
    "utc_now",
    "TERMINAL_STATUSES",
    # Store
    "InMemoryModelStore",
    "ModelStore",
    # Evaluation
    "EvaluationReport",
    "Evaluator",
    "OfflineEvaluator",
    "HoldoutExample",
    "holdout_fingerprint",
    "default_pr_review_holdout",
    "EVALUATOR_VERSION",
    # Registry
    "ModelRegistry",
    # Exceptions
    "ModelRegistryError",
    "ModelNotFoundError",
    "ModelStateError",
    "DuplicateModelConflict",
    "DuplicateVersionConflict",
    "SelfApprovalError",
    "UnauthorizedApproverError",
    "EvaluationRequiredError",
    "ApprovalRequiredError",
    "UnknownConsumerError",
    "ArtifactHashMismatchError",
    "ArtifactMissingError",
    "ArtifactIntegrityError",
    "ArtifactPathError",
    "MultipleActiveModelsError",
    "ConcurrentActivationError",
    "RegistryPersistenceError",
    "RegistryCorruptionError",
]
