"""
Typed models for the Dataset Export Prototype.

All schemas use ``model_config = ConfigDict(frozen=True, extra="forbid")``
so the export pipeline cannot accidentally accept untyped fields and so
serialised records are immutable. Decimal / dict / list field types are
intentionally constrained — the prototype's safety guarantees rest on
the contract.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── Enums ─────────────────────────────────────────────────────────────────────


class Sensitivity(str, Enum):
    """
    Coarse-grained sensitivity classification on every candidate.

    Confidential and restricted candidates are ALWAYS rejected, even when
    the privacy scanner would have been able to redact credential
    patterns out of the content. The classification reflects the source
    domain's training policy, not just the present surface text.

    Unknown sensitivity fails closed in strict mode (the caller must
    classify before the export pipeline can use the candidate).
    """
    public       = "public"
    internal     = "internal"
    confidential = "confidential"
    restricted   = "restricted"
    unknown      = "unknown"


# Sensitivity classes that are ELIGIBLE for SFT/DPO export.
_TRAINING_ELIGIBLE_SENSITIVITIES: frozenset[Sensitivity] = frozenset({
    Sensitivity.public, Sensitivity.internal,
})


class RejectionReason(str, Enum):
    """
    Primary rejection reason emitted per candidate. A candidate gets
    exactly ONE primary reason (highest priority match wins) and may
    accumulate auxiliary diagnostic reasons in
    ``RejectionRecord.diagnostics``.
    """
    missing_provenance     = "rejected_missing_provenance"
    missing_label          = "rejected_missing_label"
    missing_content        = "rejected_missing_content"
    for_sensitivity        = "rejected_for_sensitivity"
    for_privacy            = "rejected_for_privacy"
    for_quality            = "rejected_for_quality"
    duplicate              = "rejected_duplicate"
    unverified_provenance  = "rejected_unverified_provenance"


# Outcome labels that count as a positive quality signal. Drives SFT
# eligibility. Governance approvals are NOT in this set — they are
# action decisions, not output-quality labels.
POSITIVE_OUTCOME_LABELS: frozenset[str] = frozenset({
    "approved", "accepted", "useful", "merged", "shipped",
})


def canonical_content_hash(
    *,
    task_id: str,
    skill_name: str,
    input_text: Optional[str],
    output_text: Optional[str],
    rejected_output: Optional[str],
    corrected_output: Optional[str],
) -> str:
    """
    Deterministic SHA-256 over a candidate's content-bearing fields.

    This is the SINGLE definition of what ``content_hash`` must equal. A
    candidate whose ``content_hash`` does not match this digest is
    rejected at construction time — a fabricated or mismatched hash can
    never enter the pipeline. Provenance, sensitivity, and outcome label
    are deliberately EXCLUDED so the hash identifies the training content
    itself (input/output/correction), independent of audit metadata.
    """
    payload = json.dumps(
        {
            "task_id": task_id,
            "skill_name": skill_name,
            "input_text": input_text,
            "output_text": output_text,
            "rejected_output": rejected_output,
            "corrected_output": corrected_output,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Typed training-source contract ────────────────────────────────────────────


class TrainingCandidate(BaseModel):
    """
    Explicit typed contract for training-source content.

    Callers MUST construct this object — the exporter never reads
    arbitrary event metadata. ``input_text`` and either ``output_text``
    OR (``rejected_output`` AND ``corrected_output``) are required for
    eligibility. The pipeline still enforces every rule independently,
    so a partial candidate is rejected with a documented reason.

    Sensitivity is the caller's classification, not derived from the
    text. Confidential / restricted classifications are honoured even
    when the surface text contains no obvious secrets.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id:          str           = Field(min_length=1)
    skill_name:       str           = Field(min_length=1)
    input_text:       Optional[str] = None
    output_text:      Optional[str] = None
    rejected_output:  Optional[str] = None
    corrected_output: Optional[str] = None
    artifact_id:      Optional[str] = None

    sensitivity:          Sensitivity
    allowed_for_training: bool
    # Source-event IDs that this candidate was assembled from.  Used
    # for provenance auditing on every exported example.
    provenance:        list[str] = Field(default_factory=list)
    content_hash:      str       = Field(min_length=64)

    # Optional outcome label set by ``OutcomeRecorded`` upstream.
    outcome_label: Optional[str] = None
    created_at:    datetime

    @field_validator("content_hash")
    @classmethod
    def _valid_sha256_hex(cls, v: str) -> str:
        normalised = v.lower()
        if len(normalised) != 64 or not all(
            c in "0123456789abcdef" for c in normalised
        ):
            raise ValueError(
                "content_hash must be a 64-character lowercase hex string "
                "(SHA-256 digest)."
            )
        return normalised

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("created_at must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)

    @field_validator("provenance")
    @classmethod
    def _nonempty_strs(cls, v: list[str]) -> list[str]:
        for s in v:
            if not isinstance(s, str) or not s.strip():
                raise ValueError(
                    "provenance entries must be non-empty strings."
                )
        return v

    @model_validator(mode="after")
    def _content_hash_matches_content(self) -> "TrainingCandidate":
        """
        Reject any candidate whose ``content_hash`` does not match the
        canonical digest of its own content. This makes the hash
        tamper-evident: a caller cannot supply a fabricated hash to
        impersonate other content or evade integrity checks.
        """
        expected = canonical_content_hash(
            task_id=self.task_id,
            skill_name=self.skill_name,
            input_text=self.input_text,
            output_text=self.output_text,
            rejected_output=self.rejected_output,
            corrected_output=self.corrected_output,
        )
        if self.content_hash != expected:
            raise ValueError(
                "content_hash does not match candidate content "
                "(possible tampering or stale hash)."
            )
        return self

    # ── Helpers consumed by the eligibility checker ─────────────────────────

    @property
    def is_eligible_sensitivity(self) -> bool:
        return self.sensitivity in _TRAINING_ELIGIBLE_SENSITIVITIES

    @property
    def has_sft_content(self) -> bool:
        return bool(self.input_text) and bool(self.output_text)

    @property
    def has_dpo_content(self) -> bool:
        return bool(self.input_text) and bool(self.rejected_output) and bool(self.corrected_output)

    @property
    def has_positive_outcome(self) -> bool:
        return (
            self.outcome_label is not None
            and self.outcome_label.lower() in POSITIVE_OUTCOME_LABELS
        )


# ── Resolver protocol (for future production wiring) ──────────────────────────


@runtime_checkable
class CandidateResolver(Protocol):
    """
    Future production wire-up: given a ledger task_id, return the typed
    candidate or ``None``. Keeps the exporter from EVER reading
    arbitrary event metadata — the resolver implementation is the safe
    boundary where ledger references get turned into training-source
    content.
    """
    def resolve(self, task_id: str) -> Optional[TrainingCandidate]: ...


# ── Output schemas ───────────────────────────────────────────────────────────


class SFTExample(BaseModel):
    """One supervised fine-tuning example."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    example_id:    str = Field(min_length=8)
    task_id:       str = Field(min_length=1)
    skill_name:    str = Field(min_length=1)
    input:         str
    output:        str
    source_events: list[str]
    artifact_id:   Optional[str] = None
    outcome_label: str
    approved:      bool
    quality_score: Optional[float] = None
    created_at:    datetime

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("created_at must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)


class DPOPair(BaseModel):
    """One direct-preference-optimization pair."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    pair_id:       str = Field(min_length=8)
    task_id:       str = Field(min_length=1)
    skill_name:    str = Field(min_length=1)
    prompt:        str
    chosen:        str
    rejected:      str
    correction:    str
    source_events: list[str]
    artifact_id:   Optional[str] = None
    created_at:    datetime

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("created_at must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)


class RejectionRecord(BaseModel):
    """One rejection — exactly one primary reason + diagnostic codes."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id:     str
    skill_name:  Optional[str] = None
    primary:     RejectionReason
    diagnostics: list[RejectionReason] = Field(default_factory=list)
    # Sanitised — caller-facing summary only. NEVER the raw content.
    summary:     str


class DatasetReport(BaseModel):
    """Typed dataset report — the stable output contract for callers."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_candidates:            int
    total_sft_examples:          int
    total_dpo_pairs:             int
    examples_by_skill:           dict[str, int]
    pairs_by_skill:              dict[str, int]
    rejected_missing_provenance: int
    rejected_missing_label:      int
    rejected_missing_content:    int
    rejected_for_sensitivity:    int
    rejected_for_privacy:        int
    rejected_for_quality:        int
    rejected_duplicate:             int
    rejected_unverified_provenance: int = 0
    skills_below_50_examples:       list[str]
    minimum_examples_per_skill:     int
    ready_for_finetuning:           bool
    recommended_next_action:        str
