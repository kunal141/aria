"""
Platform Intelligence — Evidence Evaluator

Pure functions for:
  - Staleness detection (per STALENESS_HOURS thresholds)
  - Phase-2 authorization check (at assembly time, after Phase-1 retrieval)
  - Conflict detection between two sources for the same claim
  - Conflict resolution (authority → recency → unresolved)
  - Evidence object construction from an authorized, non-stale KnowledgeSource

All functions are deterministic and have no side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    AuthorizationDecision,
    ConflictRecord,
    Evidence,
    KnowledgeSource,
    STALENESS_HOURS,
    SensitivityLevel,
    caller_can_access,
)

_MAX_EXCERPT = 500


# ── Staleness ─────────────────────────────────────────────────────────────────

def check_staleness(
    source: KnowledgeSource,
    now: datetime | None = None,
) -> tuple[bool, float | None]:
    """
    Returns (is_stale, hours_old).

    Fails closed: if content_updated_at cannot be parsed → stale=True, hours_old=None.
    now defaults to UTC now.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        updated = datetime.fromisoformat(
            source.content_updated_at.replace("Z", "+00:00")
        )
    except (ValueError, AttributeError):
        return True, None

    threshold = STALENESS_HOURS.get(source.source_type, 24)
    delta_hours = (now - updated).total_seconds() / 3600
    return delta_hours > threshold, round(delta_hours, 2)


# ── Phase-2 authorization ─────────────────────────────────────────────────────

def check_authorization(
    caller_level: SensitivityLevel,
    source: KnowledgeSource,
) -> AuthorizationDecision:
    """
    Returns an AuthorizationDecision for this (caller, source) pair.

    INVARIANT: when allowed=False, reason contains ONLY the source_id and
    sensitivity-level strings — never source.title or source.content.
    """
    allowed = caller_can_access(caller_level, source.sensitivity)
    if allowed:
        reason = (
            f"caller level '{caller_level}' meets source sensitivity "
            f"'{source.sensitivity}' for source '{source.source_id}'"
        )
    else:
        reason = (
            f"source '{source.source_id}' requires sensitivity "
            f"'{source.sensitivity}'; caller has '{caller_level}'"
        )
    return AuthorizationDecision(
        source_id=source.source_id,
        caller_level=caller_level,
        source_level=source.sensitivity,
        allowed=allowed,
        reason=reason,
    )


# ── Conflict detection ────────────────────────────────────────────────────────

def detect_conflicts(
    claim_id: str,
    sources: list[KnowledgeSource],
) -> list[ConflictRecord]:
    """
    Detect pairwise conflicts between sources for the same claim.

    V1 heuristic: two sources conflict when they have the SAME source_type
    but DIFFERENT version_refs (e.g., two CI builds with different build numbers).
    This is conservative — some non-conflicting same-type sources will be flagged.
    Resolution is cheap, so false-positives are safe.

    Returns one ConflictRecord per conflicting pair (A, B) where A.source_id < B.source_id
    to avoid duplicate records.
    """
    conflicts: list[ConflictRecord] = []

    for i, src_a in enumerate(sources):
        for src_b in sources[i + 1:]:
            if src_a.source_type == src_b.source_type and src_a.version_ref != src_b.version_ref:
                resolved_by, selected_id = _resolve_conflict(src_a, src_b)
                conflicts.append(
                    ConflictRecord(
                        claim_id=claim_id,
                        source_a_id=src_a.source_id,
                        source_b_id=src_b.source_id,
                        description=(
                            f"Both are '{src_a.source_type}' sources with different "
                            f"version refs: '{src_a.version_ref}' vs '{src_b.version_ref}'"
                        ),
                        resolved_by=resolved_by,
                        selected_source_id=selected_id,
                    )
                )
    return conflicts


def _resolve_conflict(
    src_a: KnowledgeSource,
    src_b: KnowledgeSource,
) -> tuple[str, str | None]:
    """
    Returns (resolved_by, selected_source_id).

    Resolution order:
    1. Authority — higher authority score wins.
    2. Recency — more recent content_updated_at wins.
    3. Unresolved — both sources excluded (selected_source_id=None).
    """
    if src_a.authority != src_b.authority:
        winner = src_a if src_a.authority > src_b.authority else src_b
        return "authority", winner.source_id

    # Try recency
    try:
        ts_a = datetime.fromisoformat(src_a.content_updated_at.replace("Z", "+00:00"))
        ts_b = datetime.fromisoformat(src_b.content_updated_at.replace("Z", "+00:00"))
        if ts_a != ts_b:
            winner = src_a if ts_a > ts_b else src_b
            return "recency", winner.source_id
    except (ValueError, AttributeError):
        pass

    return "unresolved", None


# ── Evidence construction ─────────────────────────────────────────────────────

def build_evidence(
    source: KnowledgeSource,
    keywords: list[str],
    now: datetime | None = None,
) -> Evidence:
    """
    Build an Evidence object from an authorized, retrieved KnowledgeSource.

    excerpt: the first _MAX_EXCERPT chars of content (V1 simple truncation).
    relevance_score: keyword-overlap ratio in [0.0, 1.0].
    is_stale + staleness_hours: from check_staleness().
    """
    is_stale, staleness_hours = check_staleness(source, now)

    # Relevance: fraction of keywords that appear in the source text
    text_lower = (source.title + " " + source.content).lower()
    if keywords:
        matched = sum(1 for kw in keywords if kw.lower() in text_lower)
        relevance = round(matched / len(keywords), 3)
    else:
        relevance = 0.0

    excerpt = source.content[:_MAX_EXCERPT]

    return Evidence(
        source_id=source.source_id,
        source_type=source.source_type,
        service_id=source.service_id,
        excerpt=excerpt,
        relevance_score=relevance,
        authority=source.authority,
        ingested_at=source.ingested_at,
        content_updated_at=source.content_updated_at,
        sensitivity=source.sensitivity,
        is_stale=is_stale,
        staleness_hours=staleness_hours,
    )
