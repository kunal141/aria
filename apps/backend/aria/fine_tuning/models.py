"""
Typed models for the Fine-Tuning Prototype (Week 29 Priority 5).

PROTOTYPE ONLY. Nothing in this package downloads a model, calls a paid
API, opens a network socket, or requires a GPU. These schemas describe a
*plan* to fine-tune and a *mock* training result — the offline-deterministic
machinery the test-suite and demo exercise.

Every model is a frozen Pydantic contract (``frozen=True, extra="forbid"``)
so a plan / manifest / result is immutable once built and cannot smuggle
untyped fields. The fine-tuning layer reuses the SAME credential-detection,
path-confinement, registry, and Work-Ledger mechanisms the rest of ARIA
uses — it never builds a parallel, weaker version of them.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aria.ledger.events import ActionTier


# ── Regex-free hex helper ─────────────────────────────────────────────────────


def _is_hex64(value: str) -> bool:
    v = value.lower()
    return len(v) == 64 and all(c in "0123456789abcdef" for c in v)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────


class TrainingMethod(str, Enum):
    """How the prototype would fine-tune (no training is actually run)."""
    sft          = "sft"
    dpo          = "dpo"
    sft_then_dpo = "sft_then_dpo"


class TrainingStatus(str, Enum):
    """Status of a (mock) training run."""
    dry_run   = "dry_run"     # planned/validated, nothing executed
    mock_done = "mock_done"   # deterministic offline mock produced an artifact
    failed    = "failed"


# ── Exceptions ────────────────────────────────────────────────────────────────


class FineTuningError(RuntimeError):
    """Base class for fine-tuning prototype errors."""


class DatasetIntegrityError(FineTuningError):
    """A dataset file was missing or modified after its manifest was recorded."""


class DatasetInsufficientError(FineTuningError):
    """The exported dataset is below the prototype's minimum-example threshold."""


class DatasetPrivacyError(FineTuningError):
    """An exported example contains a credential-shaped substring (defence in depth)."""


class DatasetProvenanceError(FineTuningError):
    """An exported example is missing its source-event provenance."""


class ArtifactPathError(FineTuningError):
    """A training-artifact path resolved outside the configured artifact root."""


class TrainingRunError(FineTuningError):
    """A (mock) training run failed."""


# ── Dataset manifest ──────────────────────────────────────────────────────────


class DatasetManifest(BaseModel):
    """
    A tamper-evident snapshot of a Priority-3 dataset export.

    The Priority-3 ``DatasetExporter`` writes three files (``sft_examples
    .jsonl``, ``dpo_pairs.jsonl``, ``dataset_report.json``) but does NOT
    emit a hash manifest. This object IS that manifest: it records a
    SHA-256 of each file at snapshot time plus a combined ``dataset_hash``
    that becomes the model's training-data provenance in the registry.

    Re-reading the files later and recomputing these hashes is how the
    planner detects a dataset that was modified after export.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    export_dir:                 str
    sft_filename:               str = "sft_examples.jsonl"
    dpo_filename:               str = "dpo_pairs.jsonl"
    report_filename:            str = "dataset_report.json"
    sft_sha256:                 str
    dpo_sha256:                 str
    report_sha256:              str
    dataset_hash:               str
    dataset_id:                 str = Field(min_length=1)
    sft_count:                  int = Field(ge=0)
    dpo_count:                  int = Field(ge=0)
    skills:                     list[str] = Field(default_factory=list)
    ready_for_finetuning:       bool = False
    minimum_examples_per_skill: int = Field(ge=0)
    created_at:                 datetime

    @field_validator("sft_sha256", "dpo_sha256", "report_sha256", "dataset_hash")
    @classmethod
    def _hex64(cls, v: str) -> str:
        if not _is_hex64(v):
            raise ValueError("file/dataset hashes must be 64-char lowercase SHA-256 hex.")
        return v.lower()

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("DatasetManifest.created_at must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)

    @property
    def total_examples(self) -> int:
        return self.sft_count + self.dpo_count


def compute_dataset_hash(sft_sha256: str, dpo_sha256: str, report_sha256: str) -> str:
    """
    The single definition of a dataset's combined identity hash: a SHA-256
    over the three per-file digests. Deterministic and order-stable.
    """
    payload = json.dumps(
        {"sft": sft_sha256.lower(), "dpo": dpo_sha256.lower(), "report": report_sha256.lower()},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Hyperparameters ───────────────────────────────────────────────────────────


class HyperparameterProposal(BaseModel):
    """A deterministic LoRA hyperparameter proposal (no training is run)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    method:        TrainingMethod
    learning_rate: float = 2e-4
    lora_r:        int   = 16
    lora_alpha:    int   = 32
    lora_dropout:  float = 0.05
    epochs:        int   = 3
    batch_size:    int   = 8
    max_seq_len:   int   = 2048
    seed:          int   = 42

    def canonical(self) -> dict[str, Any]:
        return {
            "method":        self.method.value,
            "learning_rate": self.learning_rate,
            "lora_r":        self.lora_r,
            "lora_alpha":    self.lora_alpha,
            "lora_dropout":  self.lora_dropout,
            "epochs":        self.epochs,
            "batch_size":    self.batch_size,
            "max_seq_len":   self.max_seq_len,
            "seed":          self.seed,
        }


class EvaluationPlan(BaseModel):
    """How the candidate will be evaluated against the baseline (offline)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    holdout_id:                  str
    evaluator_version:           str
    dimensions:                  list[str]
    promote_threshold_dimensions: int = Field(ge=1)
    note:                        str = "Offline deterministic evaluation — prototype evidence only."


# ── Fine-tuning plan ──────────────────────────────────────────────────────────


class FineTuningPlan(BaseModel):
    """
    The deterministic plan produced from a verified dataset manifest.

    Holds everything a (future, real) trainer would need — base model,
    dataset provenance, example counts, method, hyperparameters, token /
    cost ESTIMATES, the evaluation plan, the governance risk tier and
    approval requirement, and the confined output-artifact location.

    The plan never triggers anything: it is data. ``config_hash`` is a
    stable fingerprint of the plan's training-relevant inputs so two plans
    over the same dataset + settings are byte-identical.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    training_run_id:          str = Field(min_length=1)
    base_model:               str = Field(min_length=1)
    dataset_id:               str = Field(min_length=1)
    dataset_hash:             str
    sft_example_count:        int = Field(ge=0)
    dpo_pair_count:           int = Field(ge=0)
    skills:                   list[str]
    training_method:          TrainingMethod
    hyperparameters:          HyperparameterProposal
    estimated_tokens:         int = Field(ge=0)
    estimated_cost_usd:       float = Field(ge=0.0)
    evaluation_plan:          EvaluationPlan
    risk_tier:                ActionTier = ActionTier.T3
    approval_required:        bool = True
    output_artifact_location: str
    config_hash:              str
    created_at:               datetime
    prototype:                Literal[True] = True
    notes:                    str = "Prototype fine-tuning plan. No training executed."

    @field_validator("dataset_hash", "config_hash")
    @classmethod
    def _hex64(cls, v: str) -> str:
        if not _is_hex64(v):
            raise ValueError("dataset_hash / config_hash must be 64-char lowercase SHA-256 hex.")
        return v.lower()

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("FineTuningPlan.created_at must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)


def compute_config_hash(
    *,
    base_model: str,
    dataset_hash: str,
    training_method: TrainingMethod,
    hyperparameters: HyperparameterProposal,
    sft_count: int,
    dpo_count: int,
    skills: list[str],
) -> str:
    """Stable SHA-256 fingerprint over the plan's training-relevant inputs."""
    payload = json.dumps(
        {
            "base_model":      base_model,
            "dataset_hash":    dataset_hash.lower(),
            "training_method": training_method.value,
            "hyperparameters": hyperparameters.canonical(),
            "sft_count":       sft_count,
            "dpo_count":       dpo_count,
            "skills":          sorted(skills),
        },
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Mock training result ──────────────────────────────────────────────────────


class MockTrainingResult(BaseModel):
    """
    The deterministic output of the offline mock runner.

    No real weights exist. ``adapter_path`` points at a tiny deterministic
    placeholder file the runner writes inside the confined artifact root,
    and ``adapter_hash`` is the SHA-256 of that file's bytes — exactly the
    shape the Model Lifecycle Registry verifies, so the candidate registers
    through the same path a real artifact would.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    training_run_id: str = Field(min_length=1)
    status:          TrainingStatus
    base_model:      str = Field(min_length=1)
    dataset_hash:    str
    adapter_path:    Optional[str] = None
    adapter_hash:    Optional[str] = None
    trained_examples: int = Field(ge=0)
    config_hash:     str
    created_at:      datetime
    prototype:       Literal[True] = True
    notes:           str = "Deterministic offline mock — no real training occurred."

    @field_validator("dataset_hash", "config_hash")
    @classmethod
    def _hex64(cls, v: str) -> str:
        if not _is_hex64(v):
            raise ValueError("dataset_hash / config_hash must be 64-char lowercase SHA-256 hex.")
        return v.lower()

    @field_validator("adapter_hash")
    @classmethod
    def _optional_hex64(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _is_hex64(v):
            raise ValueError("adapter_hash must be 64-char lowercase SHA-256 hex.")
        return v.lower()

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("MockTrainingResult.created_at must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)
