"""
aria.proof — Work Proof Packet v0.

The artifact a manager accepts or rejects, and the unit the benchmark measures.

Its integrity rules are **structural**, not conventional, because the failure mode
that matters most is silent: a system that quietly drops the one check that would
have blocked a release looks identical to one that never had a problem. Therefore:

- a producer can never emit ``omitted`` — only :func:`reconcile` assigns it, so a
  dangerous claim cannot be dropped out of the denominator;
- omission of a **critical** item is reported as a safety failure, not a gap;
- ``supported`` requires evidence, and evidence requires a content hash plus an
  observation timestamp, so a claim is always traceable to a specific byte state;
- a Tier-B verdict must cite the exact policy rule it applied;
- abstention requires a machine-readable reason, so "I don't know" is auditable.

Nothing here calls a model, a network, or a credential. It records and checks.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aria.goals.sanitize import sanitize_text

_SHA256_HEX_LENGTH = 64
_MAX_FLAGS = 20
_MAX_TEXT = 2_000


class Tier(str, Enum):
    """Claim tiers. Tier C (judgment) is never a manifest item — advisory only."""
    A = "A"   # verifiable fact
    B = "B"   # deterministic policy conclusion


class Materiality(str, Enum):
    critical = "critical"
    major = "major"
    minor = "minor"


class Verdict(str, Enum):
    supported = "supported"
    unsatisfied = "unsatisfied"
    abstained = "abstained"
    omitted = "omitted"      # assigned by reconciliation ONLY


class EvidenceState(str, Enum):
    present = "present"
    absent = "absent"
    stale = "stale"
    conflicting = "conflicting"
    unauthorized = "unauthorized"


VerdictOrigin = Literal["producer", "reconciliation"]


class PacketIntegrityError(ValueError):
    """A packet violated a structural integrity rule."""


def _now() -> datetime:
    return datetime.now(UTC)


def content_hash(payload: bytes) -> str:
    """Canonical evidence digest."""
    return hashlib.sha256(payload).hexdigest()


class EvidenceRef(BaseModel):
    """A pointer to the exact byte state a claim was decided from."""
    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    content_hash: str
    observed_at: datetime
    locator: str | None = None

    @field_validator("content_hash")
    @classmethod
    def _sha256_shaped(cls, value: str) -> str:
        candidate = (value or "").strip().lower()
        if len(candidate) != _SHA256_HEX_LENGTH or any(
            character not in "0123456789abcdef" for character in candidate
        ):
            raise ValueError("evidence must carry a SHA-256 content hash")
        return candidate

    @field_validator("observed_at")
    @classmethod
    def _tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evidence observation time must be timezone-aware")
        return value.astimezone(UTC)


def verify_evidence(ref: EvidenceRef, payload: bytes) -> bool:
    """True iff ``payload`` still hashes to the value recorded on ``ref``."""
    return content_hash(payload) == ref.content_hash


def evidence_state(
    refs: list[EvidenceRef],
    *,
    freshness_window_hours: float | None,
    now: datetime | None = None,
) -> EvidenceState:
    """Classify the evidence backing one claim. Absent and stale are distinct."""
    if not refs:
        return EvidenceState.absent
    if freshness_window_hours is None:
        return EvidenceState.present
    moment = now or _now()
    horizon = freshness_window_hours * 3_600
    if any((moment - ref.observed_at).total_seconds() > horizon for ref in refs):
        return EvidenceState.stale
    return EvidenceState.present


class ManifestItem(BaseModel):
    """One mandatory check. Frozen before either arm runs."""
    model_config = ConfigDict(frozen=True)

    manifest_item_id: str = Field(min_length=1)
    tier: Tier
    claim_text: str = Field(min_length=1, max_length=_MAX_TEXT)
    policy_rule_id: str | None = None
    materiality: Materiality
    authoritative_source: str = Field(min_length=1)
    freshness_window_hours: float | None = None
    stratum: str = "natural"

    @model_validator(mode="after")
    def _tier_b_declares_a_rule(self) -> ManifestItem:
        if self.tier is Tier.B and not self.policy_rule_id:
            raise ValueError("a Tier-B manifest item must declare its policy rule")
        return self


class ClaimVerdict(BaseModel):
    """A producer's answer to exactly one manifest item."""
    model_config = ConfigDict(frozen=True)

    manifest_item_id: str = Field(min_length=1)
    verdict: Verdict
    cited_policy_rule_id: str | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    abstention_reason: EvidenceState | None = None
    flags: list[str] = Field(default_factory=list, max_length=_MAX_FLAGS)
    # Provenance of this verdict. Producers always emit "producer"; only
    # :func:`reconcile` may mint "reconciliation", and only to record an omission.
    # Keeping this explicit means the omission count has exactly one author.
    origin: VerdictOrigin = "producer"

    @field_validator("flags")
    @classmethod
    def _mask_flags(cls, values: list[str]) -> list[str]:
        return [sanitize_text(value) or "" for value in values]

    @model_validator(mode="after")
    def _verdict_discipline(self) -> ClaimVerdict:
        if self.verdict is Verdict.omitted and self.origin != "reconciliation":
            raise ValueError(
                "'omitted' is assigned by reconciliation and can never be self-reported"
            )
        if self.verdict is not Verdict.omitted and self.origin == "reconciliation":
            raise ValueError("reconciliation may only record omissions")
        if self.verdict is Verdict.supported and not self.evidence_refs:
            raise ValueError("a 'supported' verdict requires at least one evidence reference")
        if self.verdict is Verdict.abstained and self.abstention_reason is None:
            raise ValueError("an abstention must record a machine-readable reason")
        return self


class WorkProofPacket(BaseModel):
    """The manager-facing artifact for one commitment."""
    model_config = ConfigDict(frozen=True)

    packet_id: str
    commitment_ref: str
    manifest_id: str
    verdicts: list[ClaimVerdict]
    omitted_item_ids: list[str] = Field(default_factory=list)
    critical_omissions: list[str] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _packet_is_self_consistent(self) -> WorkProofPacket:
        ids = [verdict.manifest_item_id for verdict in self.verdicts]
        if len(ids) != len(set(ids)):
            raise ValueError("a packet cannot contain duplicate manifest verdicts")
        omitted = sorted(
            verdict.manifest_item_id
            for verdict in self.verdicts
            if verdict.verdict is Verdict.omitted
        )
        if sorted(self.omitted_item_ids) != omitted:
            raise ValueError("packet omitted_item_ids must match omitted verdicts")
        if not set(self.critical_omissions).issubset(set(self.omitted_item_ids)):
            raise ValueError("critical omissions must be a subset of omitted item ids")
        return self

    @property
    def manifest_completeness(self) -> float:
        """Answered ÷ required. Omitted items stay in the denominator, by design."""
        if not self.verdicts:
            return 0.0
        answered = sum(1 for v in self.verdicts if v.verdict is not Verdict.omitted)
        return round(answered / len(self.verdicts), 4)

    @property
    def has_critical_failure(self) -> bool:
        """A silently dropped critical check is a safety failure, not a gap."""
        return bool(self.critical_omissions)


def reconcile(
    manifest: list[ManifestItem], responses: list[ClaimVerdict]
) -> list[ClaimVerdict]:
    """Force every manifest item to carry a verdict, assigning ``omitted`` for gaps.

    This is the anti-gaming boundary: a producer that answers only the easy checks
    cannot thereby shrink the denominator.
    """
    known = {item.manifest_item_id for item in manifest}
    seen: set[str] = set()
    for response in responses:
        if response.origin != "producer":
            raise PacketIntegrityError(
                "responses submitted for reconciliation must originate from a producer")
        if response.manifest_item_id not in known:
            raise PacketIntegrityError(
                f"response references unknown manifest item {response.manifest_item_id!r}")
        if response.manifest_item_id in seen:
            raise PacketIntegrityError(
                f"duplicate response for manifest item {response.manifest_item_id!r}")
        seen.add(response.manifest_item_id)

    by_id = {response.manifest_item_id: response for response in responses}
    return [
        by_id.get(
            item.manifest_item_id,
            ClaimVerdict(
                manifest_item_id=item.manifest_item_id,
                verdict=Verdict.omitted,
                origin="reconciliation",
            ),
        )
        for item in manifest
    ]


def assemble_packet(
    *,
    commitment_ref: str,
    manifest_id: str,
    manifest: list[ManifestItem],
    responses: list[ClaimVerdict],
    packet_id: str | None = None,
    now: datetime | None = None,
) -> WorkProofPacket:
    """Reconcile, verify Tier-B rule citation, and record omissions."""
    import uuid

    verdicts = reconcile(manifest, responses)
    items = {item.manifest_item_id: item for item in manifest}

    for verdict in verdicts:
        item = items[verdict.manifest_item_id]
        if verdict.verdict is Verdict.omitted or item.tier is not Tier.B:
            continue
        if verdict.cited_policy_rule_id != item.policy_rule_id:
            raise PacketIntegrityError(
                f"Tier-B item {item.manifest_item_id!r} must cite "
                f"{item.policy_rule_id!r}; a missing or mismatched citation is unsupported"
            )

    omitted = [v.manifest_item_id for v in verdicts if v.verdict is Verdict.omitted]
    critical = [
        item_id for item_id in omitted
        if items[item_id].materiality is Materiality.critical
    ]
    return WorkProofPacket(
        packet_id=packet_id or f"wpp-{uuid.uuid4().hex}",
        commitment_ref=commitment_ref,
        manifest_id=manifest_id,
        verdicts=verdicts,
        omitted_item_ids=omitted,
        critical_omissions=critical,
        created_at=now or _now(),
    )


__all__ = [
    "ClaimVerdict",
    "EvidenceRef",
    "EvidenceState",
    "ManifestItem",
    "Materiality",
    "PacketIntegrityError",
    "Tier",
    "Verdict",
    "WorkProofPacket",
    "assemble_packet",
    "content_hash",
    "evidence_state",
    "reconcile",
    "verify_evidence",
]
