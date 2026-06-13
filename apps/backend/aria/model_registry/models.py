"""
Model Lifecycle Registry v1 — typed models, lifecycle states, transitions.

Week 29 Priority 4. Minimal MLOps registry that tracks each candidate model
through a governed lifecycle. Every ``ModelRecord`` is an immutable, frozen
Pydantic contract; lifecycle advances by ``model_copy(update={...})`` and a
new record replacing the old one in the store — never by mutating a record in
place (mirrors ``aria.evolution.update_manager.models.UpdateRelease``).

Governance guarantees enforced here (model layer) and in ``registry.py``
(operations layer):

  - Hashes (``dataset_hash``, ``artifact_hash``, ``training_config_hash``) must
    be 64-char lowercase SHA-256 hex when present — malformed hashes rejected.
  - ``model_id`` / ``training_run_id`` are filename-safe (no path separators,
    no parent-traversal) because they key immutable artifacts on disk.
  - ``metadata`` is sanitised through the SAME redaction boundary as the Work
    Ledger (``aria.ledger.privacy.sanitize_metadata``) so credentials / raw
    confidential content / training examples can never be stored in registry
    metadata.
  - Lifecycle transitions are validated against an explicit allowed-transition
    map; terminal states permit no further transitions.

This module holds NO secrets and runs fully offline.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aria.ledger.privacy import sanitize_metadata


_HEX64_RE = re.compile(r"^[a-f0-9]{64}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
# model_id / training_run_id are concatenated into immutable artifact paths,
# so they must be filename-safe: ASCII alphanumerics, dot, dash, underscore
# only — no path separators, no parent-traversal segments.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


# ── Enumerations ────────────────────────────────────────────────────────────────


class ModelStatus(str, Enum):
    draft             = "draft"
    registered        = "registered"
    evaluated         = "evaluated"
    awaiting_approval = "awaiting_approval"
    approved          = "approved"
    canary            = "canary"
    active            = "active"
    rejected          = "rejected"
    deprecated        = "deprecated"
    rolled_back       = "rolled_back"
    failed            = "failed"


class ModelProvider(str, Enum):
    anthropic   = "anthropic"
    openai      = "openai"
    local       = "local"        # self-hosted (e.g. vLLM) — V2+
    huggingface = "huggingface"
    prototype   = "prototype"    # offline prototype; NEVER served to prod traffic


class ModelType(str, Enum):
    frontier   = "frontier"
    slm        = "slm"
    fine_tuned = "fine_tuned"
    base       = "base"


# Terminal states — no further transitions permitted.
TERMINAL_STATUSES: frozenset[ModelStatus] = frozenset({
    ModelStatus.rejected,
    ModelStatus.deprecated,
    ModelStatus.rolled_back,
    ModelStatus.failed,
})


# Explicit allowed-transition map. A transition is permitted ONLY if the
# target appears in the source's set. This is the single source of truth for
# "allowed and forbidden transitions" — the operations layer consults it and
# the test suite asserts it directly.
_ALLOWED_TRANSITIONS: dict[ModelStatus, frozenset[ModelStatus]] = {
    ModelStatus.draft:             frozenset({ModelStatus.registered, ModelStatus.failed, ModelStatus.rejected}),
    ModelStatus.registered:        frozenset({ModelStatus.evaluated, ModelStatus.failed, ModelStatus.rejected}),
    ModelStatus.evaluated:         frozenset({ModelStatus.awaiting_approval, ModelStatus.failed, ModelStatus.rejected}),
    ModelStatus.awaiting_approval: frozenset({ModelStatus.approved, ModelStatus.rejected, ModelStatus.failed}),
    ModelStatus.approved:          frozenset({ModelStatus.canary, ModelStatus.active, ModelStatus.rejected, ModelStatus.failed}),
    ModelStatus.canary:            frozenset({ModelStatus.active, ModelStatus.rolled_back, ModelStatus.rejected, ModelStatus.failed}),
    ModelStatus.active:            frozenset({ModelStatus.deprecated, ModelStatus.rolled_back}),
    ModelStatus.rejected:          frozenset(),
    ModelStatus.deprecated:        frozenset(),
    ModelStatus.rolled_back:       frozenset(),
    ModelStatus.failed:            frozenset(),
}


def can_transition(frm: ModelStatus, to: ModelStatus) -> bool:
    """True iff ``frm → to`` is an allowed lifecycle transition."""
    return to in _ALLOWED_TRANSITIONS.get(frm, frozenset())


def is_terminal(status: ModelStatus) -> bool:
    return status in TERMINAL_STATUSES


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Core record ─────────────────────────────────────────────────────────────────


class ModelRecord(BaseModel):
    """
    An immutable versioned model record.

    ``frozen=True`` enforces immutability — the registry advances lifecycle by
    ``model_copy(update={...})`` and replacing the stored record. ``extra=
    "forbid"`` keeps the contract tight. ``protected_namespaces=()`` silences
    Pydantic's ``model_*`` field-name warning (we deliberately use
    ``model_id`` / ``model_name`` / ``model_type``).
    """
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    model_id:             str = Field(min_length=1)
    model_name:           str = Field(min_length=1)
    semantic_version:     str
    provider:             ModelProvider
    model_type:           ModelType
    base_model:           str = Field(min_length=1)
    artifact_path:        Optional[str] = None
    artifact_hash:        Optional[str] = None
    dataset_id:           str = Field(min_length=1)
    dataset_hash:         str
    training_run_id:      Optional[str] = None
    training_config_hash: Optional[str] = None
    production_consumer:  str = Field(min_length=1)
    status:               ModelStatus = ModelStatus.registered
    evaluation_metrics:   dict[str, float] = Field(default_factory=dict)
    evaluation_report_id: Optional[str] = None
    created_by:           str = Field(min_length=1)
    approved_by:          Optional[str] = None
    created_at:           datetime
    approved_at:          Optional[datetime] = None
    activated_at:         Optional[datetime] = None
    supersedes:           Optional[str] = None
    rollback_target:      Optional[str] = None
    metadata:             dict[str, Any] = Field(default_factory=dict)

    # ── Field validators ────────────────────────────────────────────────────

    @field_validator("model_id", "training_run_id")
    @classmethod
    def _filename_safe(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _SAFE_ID_RE.match(v) or ".." in v.split("."):
            raise ValueError(
                f"identifier {v!r} is not filename-safe; only [A-Za-z0-9._-]+ "
                "with no parent-traversal segments is permitted."
            )
        return v

    @field_validator("semantic_version")
    @classmethod
    def _valid_semver(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(f"semantic_version must be semver (x.y.z), got {v!r}")
        return v

    @field_validator("dataset_hash")
    @classmethod
    def _valid_dataset_hash(cls, v: str) -> str:
        normalised = v.lower()
        if not _HEX64_RE.match(normalised):
            raise ValueError("dataset_hash must be 64-char SHA-256 hex.")
        return normalised

    @field_validator("artifact_hash", "training_config_hash")
    @classmethod
    def _valid_optional_hash(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        normalised = v.lower()
        if not _HEX64_RE.match(normalised):
            raise ValueError("hash fields must be 64-char SHA-256 hex when present.")
        return normalised

    @field_validator("created_at", "approved_at", "activated_at")
    @classmethod
    def _tz_aware(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        if v.tzinfo is None:
            raise ValueError("registry timestamps must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)

    @field_validator("evaluation_metrics", mode="before")
    @classmethod
    def _finite_metrics(cls, v: dict[str, float]) -> dict[str, float]:
        # Runs BEFORE Pydantic's float coercion so a raw bool (a subclass of
        # int) is rejected rather than silently coerced to 1.0/0.0.
        import math
        if not isinstance(v, dict):
            raise ValueError("evaluation_metrics must be a mapping of name -> number.")
        for name, value in v.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"evaluation_metrics[{name!r}] must be a number.")
            if not math.isfinite(float(value)):
                raise ValueError(f"evaluation_metrics[{name!r}] must be finite.")
        return v

    @field_validator("metadata")
    @classmethod
    def _sanitize_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        # Same redaction boundary as the Work Ledger. Credentials / raw
        # confidential content embedded in metadata are masked at the type
        # boundary so the registry cannot persist secrets.
        return sanitize_metadata(v, strict=False)

    # ── Derived helpers ──────────────────────────────────────────────────────

    def identity_fingerprint(self) -> str:
        """
        Deterministic SHA-256 over the IMMUTABLE identity fields of a model
        version. Excludes mutable lifecycle fields (status, approvals,
        timestamps, evaluation_metrics, supersedes, rollback_target) so two
        registrations of the same model differ only in lifecycle are
        idempotent, while a different artifact/dataset is a real conflict.
        """
        payload = json.dumps(
            {
                "model_name": self.model_name,
                "semantic_version": self.semantic_version,
                "provider": self.provider.value,
                "model_type": self.model_type.value,
                "base_model": self.base_model,
                "artifact_path": self.artifact_path,
                "artifact_hash": self.artifact_hash,
                "dataset_id": self.dataset_id,
                "dataset_hash": self.dataset_hash,
                "training_run_id": self.training_run_id,
                "training_config_hash": self.training_config_hash,
                "production_consumer": self.production_consumer,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def version_key(self) -> tuple[str, str]:
        """Version identity = (production_consumer, semantic_version)."""
        return (self.production_consumer, self.semantic_version)

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


# ── Comparison view ─────────────────────────────────────────────────────────────


class ModelComparison(BaseModel):
    """Diff view between two model versions for one production consumer."""
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    production_consumer: str
    model_name_a:        str
    model_name_b:        str
    version_a:           str
    version_b:           str
    model_id_a:          str
    model_id_b:          str
    status_a:            ModelStatus
    status_b:            ModelStatus
    metrics_a:           dict[str, float]
    metrics_b:           dict[str, float]
    metric_deltas:       dict[str, float]   # b - a for each shared metric
    dataset_changed:     bool
    base_model_changed:  bool
    provider_changed:    bool


def compare_records(a: ModelRecord, b: ModelRecord) -> ModelComparison:
    """Build a ``ModelComparison`` between two records (b relative to a)."""
    shared = set(a.evaluation_metrics) & set(b.evaluation_metrics)
    deltas = {
        m: float(b.evaluation_metrics[m]) - float(a.evaluation_metrics[m])
        for m in sorted(shared)
    }
    return ModelComparison(
        production_consumer=a.production_consumer,
        model_name_a=a.model_name,
        model_name_b=b.model_name,
        version_a=a.semantic_version,
        version_b=b.semantic_version,
        model_id_a=a.model_id,
        model_id_b=b.model_id,
        status_a=a.status,
        status_b=b.status,
        metrics_a=dict(a.evaluation_metrics),
        metrics_b=dict(b.evaluation_metrics),
        metric_deltas=deltas,
        dataset_changed=(a.dataset_hash != b.dataset_hash),
        base_model_changed=(a.base_model != b.base_model),
        provider_changed=(a.provider != b.provider),
    )


# ── Exceptions ──────────────────────────────────────────────────────────────────


class ModelRegistryError(RuntimeError):
    """Base class for registry errors."""


class ModelNotFoundError(KeyError):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"Model not found: {model_id!r}")


class ModelStateError(ValueError):
    """An invalid lifecycle transition was attempted."""
    def __init__(self, model_id: str, current: ModelStatus, attempted: str) -> None:
        super().__init__(
            f"Model {model_id!r} is in state {current.value!r}; cannot {attempted}."
        )


class DuplicateModelConflict(ValueError):
    """Same model_id re-registered with DIFFERENT content."""
    def __init__(self, model_id: str) -> None:
        super().__init__(
            f"Model {model_id!r} already registered with different content; "
            "refusing to overwrite an immutable version record."
        )


class DuplicateVersionConflict(ValueError):
    """Same (consumer, semantic_version) owned by a different model_id."""
    def __init__(self, consumer: str, version: str, existing_id: str) -> None:
        super().__init__(
            f"Version {version!r} for consumer {consumer!r} is already owned by "
            f"model {existing_id!r}; a semantic version maps to exactly one model."
        )


class SelfApprovalError(ValueError):
    def __init__(self, model_id: str, approver: str) -> None:
        super().__init__(
            f"Model {model_id!r}: creator and approver are both {approver!r}. "
            "Self-approval is forbidden."
        )


class UnauthorizedApproverError(ValueError):
    def __init__(self, model_id: str, approver: str) -> None:
        super().__init__(
            f"Model {model_id!r}: {approver!r} is not an authorized approver."
        )


class EvaluationRequiredError(ValueError):
    """Activation attempted on a model with no recorded evaluation."""
    def __init__(self, model_id: str) -> None:
        super().__init__(
            f"Model {model_id!r}: cannot activate without a recorded evaluation "
            "(evaluation_metrics + evaluation_report_id required)."
        )


class ApprovalRequiredError(ValueError):
    """Activation attempted on a model that has no human approval."""
    def __init__(self, model_id: str) -> None:
        super().__init__(
            f"Model {model_id!r}: cannot activate without human approval."
        )


class UnknownConsumerError(ValueError):
    def __init__(self, consumer: str) -> None:
        super().__init__(
            f"Production consumer {consumer!r} is not a known consumer."
        )


class ArtifactHashMismatchError(ValueError):
    def __init__(self, model_id: str) -> None:
        super().__init__(
            f"Model {model_id!r}: SHA-256 of artifact does not match artifact_hash."
        )


class ArtifactPathError(ValueError):
    """Artifact path is not confined beneath the registry artifact root."""


class ArtifactMissingError(ValueError):
    """A declared artifact_path does not exist on disk (cannot be verified)."""
    def __init__(self, model_id: str, path: str) -> None:
        super().__init__(
            f"Model {model_id!r}: declared artifact_path {path!r} does not exist; "
            "an artifact that cannot be read cannot be trusted."
        )


class ArtifactIntegrityError(ValueError):
    """An artifact_path/artifact_hash pairing is internally inconsistent."""
    def __init__(self, model_id: str, detail: str) -> None:
        super().__init__(f"Model {model_id!r}: {detail}")


class MultipleActiveModelsError(RuntimeError):
    """A batch would leave more than one ACTIVE model for a consumer."""
    def __init__(self, violators: dict[str, list[str]]) -> None:
        self.violators = violators
        super().__init__(
            f"save_batch rejected — more than one active model per consumer: "
            f"{violators!r}"
        )


class ConcurrentActivationError(RuntimeError):
    def __init__(self, consumer: str) -> None:
        super().__init__(
            f"An activation/rollback for consumer {consumer!r} is already in "
            "progress; concurrent operation blocked."
        )


class RegistryPersistenceError(RuntimeError):
    """The registry store could not durably flush a record to disk."""


class RegistryCorruptionError(RegistryPersistenceError):
    """
    The persisted registry file is malformed, contains an invalid/duplicate
    record, or violates the at-most-one-active-per-consumer invariant. Loading
    fails closed rather than silently dropping records or surfacing a
    half-loaded store as if it were authoritative.
    """
