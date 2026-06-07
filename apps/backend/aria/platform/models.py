"""
Platform Intelligence Models — Week 26

All domain contracts for the Platform Intelligence layer.
No business logic here — only typed data structures.

Key invariants (enforced by this module and callers):
  - SensitivityLevel is ordered: public < internal < restricted
  - Timestamps are UTC ISO strings; missing timestamp → fail closed (stale)
  - ClaimEvidence maps exactly one claim_id to its evidence list (never whole-answer)
  - EvidencedAnswer.answer is empty string when is_safe_to_surface=False
  - AuthorizationDecision.reason contains NO source content when allowed=False
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


# ── Sensitivity levels ────────────────────────────────────────────────────────
# Ordered: public(1) < internal(2) < restricted(3)
# A caller with level X can access sources where level <= X.

SensitivityLevel = Literal["public", "internal", "restricted"]

_SENS_RANK: dict[str, int] = {"public": 1, "internal": 2, "restricted": 3}


def sensitivity_rank(level: SensitivityLevel) -> int:
    return _SENS_RANK[level]


def caller_can_access(caller: SensitivityLevel, source: SensitivityLevel) -> bool:
    """True only if caller's clearance level >= source's sensitivity level."""
    return _SENS_RANK[caller] >= _SENS_RANK[source]


# ── Source types and default authority/staleness constants ────────────────────

SourceTypeName = Literal["repository", "jira", "documentation", "ci", "telemetry"]

# Authority score 1–10 per source type. Higher = more authoritative for current state.
# Live telemetry always beats stored documentation for "what is happening now."
SOURCE_AUTHORITY: dict[str, int] = {
    "telemetry":    10,   # live metrics — most authoritative for current-state claims
    "ci":            8,   # build/test results — near-real-time ground truth
    "repository":    7,   # code state — authoritative for implementation facts
    "jira":          5,   # human-reported, may lag behind reality
    "documentation": 3,   # often lags; lower trust for operational claims
}

# Staleness threshold in hours per source type.
# A source whose content_updated_at is older than this is flagged as stale.
STALENESS_HOURS: dict[str, int] = {
    "telemetry":      1,
    "ci":             4,
    "jira":          24,
    "repository":    48,
    "documentation": 168,  # 1 week
}


# ── Service catalog ───────────────────────────────────────────────────────────

ServiceStatus = Literal["healthy", "degraded", "down", "unknown"]


class ServiceEntry(BaseModel):
    """
    Authoritative record of a platform service.
    Immutable after creation — mutations produce new ServiceEntry objects.
    """
    service_id: str           # stable slug: "recommendation-service"
    name: str
    version: str              # semver or tag: "v3.2.1"
    owner_team: str
    oncall_contact: str
    tech_stack: list[str]
    dependencies: list[str]   # service_ids this service directly depends on
    sensitivity: SensitivityLevel
    status: ServiceStatus = "unknown"
    registered_at: str        # UTC ISO timestamp
    updated_at: str           # UTC ISO timestamp
    repository_url: Optional[str] = None
    jira_project: Optional[str] = None

    @field_validator("registered_at", "updated_at")
    @classmethod
    def must_be_parseable_utc(cls, v: str) -> str:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


# ── Knowledge sources ─────────────────────────────────────────────────────────

class KnowledgeSource(BaseModel):
    """
    A single unit of ingested platform knowledge.

    source_id must be stable across re-ingestions for deduplication.
    Convention: "{service_id}:{source_type}:{slug}"

    content_updated_at: when the original data source last changed (determines staleness).
    ingested_at:        when ARIA stored this (used for cache-age tracking only).

    Live telemetry (source_type="telemetry") has a 1-hour staleness window.
    Durable knowledge (documentation, repository) has multi-day windows.
    """
    source_id: str                # stable: "recommendation-service:ci:build-abc1234"
    source_type: SourceTypeName
    service_id: str               # must reference a registered service
    version_ref: str              # git SHA, sprint ID, doc version, build number
    title: str
    content: str
    sensitivity: SensitivityLevel
    authority: int                # 1–10; use SOURCE_AUTHORITY[source_type] as default
    ingested_at: str              # UTC ISO
    content_updated_at: str       # UTC ISO — when the source data last changed
    url: Optional[str] = None

    @field_validator("ingested_at", "content_updated_at")
    @classmethod
    def must_be_parseable_utc(cls, v: str) -> str:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


# ── Evidence (per-claim, never per-answer) ────────────────────────────────────

class Evidence(BaseModel):
    """
    A single piece of evidence supporting one specific claim.

    excerpt is the relevant fragment of the source content (not full content).
    is_stale signals that this evidence may be outdated but was the best available.
    """
    source_id: str
    source_type: SourceTypeName
    service_id: str
    excerpt: str              # specific fragment supporting the claim (max 500 chars)
    relevance_score: float    # 0.0–1.0 (keyword overlap in V1)
    authority: int
    ingested_at: str
    content_updated_at: str
    sensitivity: SensitivityLevel
    is_stale: bool
    staleness_hours: Optional[float] = None


# ── Conflict records ──────────────────────────────────────────────────────────

class ConflictRecord(BaseModel):
    """
    Records a detected conflict between two sources for the same claim.

    resolved_by: "authority" | "recency" | "unresolved"
    selected_source_id: None when conflict is unresolved (both sources excluded).
    """
    claim_id: str
    source_a_id: str
    source_b_id: str
    description: str
    resolved_by: str
    selected_source_id: Optional[str] = None


# ── Authorization decisions ───────────────────────────────────────────────────

class AuthorizationDecision(BaseModel):
    """
    Records whether a source was authorized for a given caller.

    INVARIANT: when allowed=False, `reason` contains ONLY source_id and
    sensitivity level strings — never source.title, source.content, or
    any text derived from the source's actual data.
    """
    source_id: str
    caller_level: SensitivityLevel
    source_level: SensitivityLevel
    allowed: bool
    reason: str   # safe: no source content when allowed=False


# ── Per-claim evidence specification ─────────────────────────────────────────

class ClaimSpec(BaseModel):
    """
    A claim the skill is making, declared by deterministic code (not the LLM).

    The assembler uses this to retrieve and verify evidence.
    If evidence is found → claim is supported.
    If not → answer is gated.
    """
    claim_id: str
    claim_text: str
    service_ids: list[str]               # which services this claim is about
    source_types: list[SourceTypeName]   # relevant source types for retrieval
    keywords: list[str]                  # for keyword-based retrieval in V1


# ── Per-claim evidence mapping ────────────────────────────────────────────────

class ClaimEvidence(BaseModel):
    """
    Machine-readable mapping of one claim to its supporting evidence.

    is_supported=False means the answer containing this claim must be gated.
    conflicts are always surfaced — never silently resolved.
    """
    claim_id: str
    claim_text: str
    evidence: list[Evidence]             # authorized, verified evidence only
    is_supported: bool                   # True only if evidence is non-empty
    conflicts: list[ConflictRecord]
    selected_evidence: Optional[Evidence] = None
    selection_reason: Optional[str] = None


# ── Evidenced answer ──────────────────────────────────────────────────────────

class EvidencedAnswer(BaseModel):
    """
    A skill answer with full provenance.

    answer is empty string when is_safe_to_surface=False.
    claim_evidence_map is the machine-readable per-claim breakdown.
    authorization_decisions records every source evaluated (allowed or denied).
    """
    answer_id: str
    query: str
    answer: str                          # "" when is_safe_to_surface=False
    claim_evidence_map: list[ClaimEvidence]
    authorization_decisions: list[AuthorizationDecision]
    freshness_warnings: list[str]
    is_safe_to_surface: bool
    blocked_reason: Optional[str] = None
    assembled_at: str                    # UTC ISO

    @property
    def has_unsupported_claims(self) -> bool:
        return any(not ce.is_supported for ce in self.claim_evidence_map)

    @property
    def supported_source_ids(self) -> list[str]:
        """Source IDs from authorized, supporting evidence only."""
        seen: dict[str, None] = {}
        for ce in self.claim_evidence_map:
            for ev in ce.evidence:
                seen[ev.source_id] = None
        return list(seen)
