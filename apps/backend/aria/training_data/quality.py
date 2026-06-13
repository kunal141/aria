"""
Deterministic quality checks for the Dataset Export Prototype.

NO LLM scoring. Every check is a pure function over the typed
``TrainingCandidate`` and a small ``QualityPolicy`` config.

Policies
--------
- ``MINIMUM_OUTPUT_LENGTH`` — smallest accepted ``output_text`` length
  (in characters). Outputs below this are rejected to keep the SFT
  dataset from degenerating into "ok"/"done"/"y" answers.
- ``DUPLICATE_CONTENT_KEY``  — what counts as a duplicate. We hash
  ``(skill_name, input_text, output_text)`` for SFT and
  ``(skill_name, input_text, rejected_output, corrected_output)`` for
  DPO. Identical content collapses to ONE record regardless of how
  many tasks produced it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from aria.training_data.models import TrainingCandidate


@dataclass(frozen=True)
class QualityPolicy:
    """All policy thresholds the eligibility checker reads."""
    minimum_output_length:    int = 5
    minimum_examples_per_skill: int = 50
    forbid_identical_chosen_rejected: bool = True


DEFAULT_QUALITY_POLICY = QualityPolicy()


# ── Per-candidate quality checks ──────────────────────────────────────────────


def fails_minimum_output_length(
    candidate: TrainingCandidate,
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> bool:
    if not candidate.output_text:
        return False  # the missing-content check is the right gate
    return len(candidate.output_text.strip()) < policy.minimum_output_length


def identical_chosen_rejected(
    candidate: TrainingCandidate,
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> bool:
    """A DPO pair where chosen == rejected is degenerate — there is no
    preference signal to learn."""
    if not policy.forbid_identical_chosen_rejected:
        return False
    if not candidate.rejected_output or not candidate.corrected_output:
        return False
    return (
        candidate.rejected_output.strip()
        == candidate.corrected_output.strip()
    )


def malformed_correction_pair(candidate: TrainingCandidate) -> bool:
    """
    Either rejected XOR corrected is set, but not both. A DPO pair
    requires BOTH sides; one without the other is not a valid pair.
    """
    has_rej = bool(candidate.rejected_output and candidate.rejected_output.strip())
    has_cor = bool(candidate.corrected_output and candidate.corrected_output.strip())
    return has_rej != has_cor   # XOR


# ── Deduplication keys (deterministic, content-based) ─────────────────────────


def sft_dedup_key(candidate: TrainingCandidate) -> str:
    """Stable dedup key for SFT examples. Identical content → identical key."""
    parts = [
        candidate.skill_name or "",
        candidate.input_text  or "",
        candidate.output_text or "",
    ]
    payload = "".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def dpo_dedup_key(candidate: TrainingCandidate) -> str:
    """Stable dedup key for DPO pairs. Identical content → identical key."""
    parts = [
        candidate.skill_name        or "",
        candidate.input_text        or "",
        candidate.rejected_output   or "",
        candidate.corrected_output  or "",
    ]
    payload = "".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── Deterministic IDs ─────────────────────────────────────────────────────────


def sft_example_id(candidate: TrainingCandidate) -> str:
    """
    Deterministic, content-hash-derived ID for an SFT example.
    Re-exporting the same content produces the same ID — supports
    byte-identical repeat runs.
    """
    return f"sft-{sft_dedup_key(candidate)[:24]}"


def dpo_pair_id(candidate: TrainingCandidate) -> str:
    return f"dpo-{dpo_dedup_key(candidate)[:24]}"


# ── Readiness policy ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReadinessAssessment:
    ready: bool
    next_action: str


def assess_readiness(
    *,
    total_sft_examples: int,
    examples_by_skill: dict[str, int],
    minimum_examples_per_skill: int,
    rejected_for_privacy: int,
    rejected_unverified_provenance: int = 0,
    skills_below_threshold: list[str],
) -> ReadinessAssessment:
    """
    Default readiness policy for the prototype.  All conditions must be
    true for ``ready_for_finetuning`` to flip to True:

    1. Zero unresolved privacy rejections.
    2. Zero unverified-provenance rejections.
    3. At least one skill present.
    4. EVERY skill at or above the minimum threshold (default 50).
       Skills that had only rejected candidates count as zero examples.
    5. Total SFT examples ≥ minimum threshold.

    Anything else → False with a precise next-action string.
    """
    if rejected_for_privacy > 0:
        return ReadinessAssessment(
            ready=False,
            next_action=(
                f"Resolve {rejected_for_privacy} privacy rejection"
                f"{'s' if rejected_for_privacy != 1 else ''} "
                "before any fine-tuning."
            ),
        )
    if rejected_unverified_provenance > 0:
        return ReadinessAssessment(
            ready=False,
            next_action=(
                f"Resolve {rejected_unverified_provenance} unverified-provenance "
                f"rejection{'s' if rejected_unverified_provenance != 1 else ''} "
                "before any fine-tuning."
            ),
        )
    if not examples_by_skill:
        return ReadinessAssessment(
            ready=False,
            next_action="No skills have SFT examples yet; collect approved task outcomes.",
        )
    if skills_below_threshold:
        return ReadinessAssessment(
            ready=False,
            next_action=(
                f"Collect more approved examples for skills below "
                f"{minimum_examples_per_skill}: {sorted(skills_below_threshold)}."
            ),
        )
    if total_sft_examples < minimum_examples_per_skill:
        return ReadinessAssessment(
            ready=False,
            next_action=(
                f"Total SFT example count {total_sft_examples} below "
                f"minimum {minimum_examples_per_skill}."
            ),
        )
    return ReadinessAssessment(
        ready=True,
        next_action="Ready to schedule a fine-tuning prototype against this dataset.",
    )
