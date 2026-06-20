"""
World Awareness logic (V3.6) — fixture-first, deterministic.

Registers allowed sources, ingests FIXTURE updates (no live browsing/network), and
scores each update's relevance to ARIA's roadmap/goals/skills. World knowledge is
NOT company truth: it produces advisory recommendations only, never a self-change.
Low-trust updates cannot change the roadmap; high-risk advisories escalate to human
review.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from aria.awareness.fixtures import FIXTURE_SOURCES, FIXTURE_UPDATES
from aria.awareness.models import (
    TrustLevel,
    UpdateStatus,
    WorldSource,
    WorldUpdate,
    default_trust_for,
)

# Topics ARIA cares about (its roadmap / capabilities). Relevance = overlap with these.
ARIA_TOPICS: frozenset[str] = frozenset({
    "agent_harness", "external_agent", "governance", "policy_gateway", "session_sharing",
    "memory", "skill_evolution", "analytics", "evidence", "approval", "tooling",
    "model", "security",
})

# Trust weighting applied to the raw relevance overlap.
_TRUST_WEIGHT = {TrustLevel.high: 1.0, TrustLevel.medium: 0.7, TrustLevel.low: 0.4}

# Maps a fixture source's stable ``url`` back to its fixture ``key`` — deterministic
# and restart-safe (no reliance on process-local registration order).
_URL_TO_KEY: dict[str, str] = {spec["url"]: spec["key"] for spec in FIXTURE_SOURCES}


def _now() -> datetime:
    return datetime.now(UTC)


def register_default_sources(store, *, actor: str = "aria") -> list[WorldSource]:
    """Register the fixture sources that are not already present (idempotent by the
    source's stable fixture ``url``). Returns ALL fixture sources now in the store."""
    existing = {s.url: s for s in store.list_sources()}
    out: list[WorldSource] = []
    for spec in FIXTURE_SOURCES:
        if spec["url"] in existing:
            out.append(existing[spec["url"]])
            continue
        s = WorldSource(
            source_id=f"src-{uuid.uuid4().hex}", name=spec["name"], source_type=spec["source_type"],
            url=spec["url"], allowed=True, trust_level=default_trust_for(spec["source_type"]),
            topic_tags=list(spec["topic_tags"]), policy_notes=spec["policy_notes"], created_at=_now(),
        )
        out.append(store.register_source(s, actor=actor))
    return out


def ingest_fixtures(store, *, actor: str = "aria") -> list[WorldUpdate]:
    """Ingest fixture updates for every registered, ALLOWED source. Fixture-only —
    no network. Each update gets its source's trust level and a citation. The
    source↔update mapping is keyed by the source's stable URL, so it is correct
    across process restarts."""
    key_to_source = {}
    for src in store.list_sources():
        if not src.allowed:
            continue
        key = _URL_TO_KEY.get(src.url)
        if key:
            key_to_source[key] = src
    already = {u.source_url for u in store.list_updates()}
    out: list[WorldUpdate] = []
    for spec in FIXTURE_UPDATES:
        src = key_to_source.get(spec["source_key"])
        if src is None or spec["source_url"] in already:
            continue
        u = WorldUpdate(
            update_id=f"upd-{uuid.uuid4().hex}", source_id=src.source_id, title=spec["title"],
            summary=spec["summary"], captured_at=_now(), source_url=spec["source_url"],
            citations=list(spec["citations"]), topic_tags=list(spec["topic_tags"]),
            trust_level=src.trust_level, risk_level=spec.get("risk_level", "low"),
            status=UpdateStatus.ingested,
        )
        out.append(store.ingest_update(u, actor=actor))
    return out


def score_relevance(update: WorldUpdate) -> float:
    """Deterministic relevance: topic overlap with ARIA topics, weighted by trust."""
    tags = set(update.topic_tags)
    if not tags:
        return 0.0
    overlap = len(tags & ARIA_TOPICS) / len(tags)
    return round(overlap * _TRUST_WEIGHT.get(update.trust_level, 0.4), 2)


def assess(update: WorldUpdate) -> tuple[float, str, UpdateStatus, str]:
    """Return (relevance_score, risk_level, status, recommendation) for an update.

    - security advisories (or risk=high) ESCALATE for human review.
    - low-trust updates are advisory-only and cannot change the roadmap.
    """
    relevance = score_relevance(update)
    risk = update.risk_level
    src_is_security = update.risk_level == "high"
    if src_is_security:
        return (relevance, "high", UpdateStatus.escalated,
                "High-risk advisory — escalate to human review before any action.")
    if update.trust_level is TrustLevel.low:
        return (relevance, risk, UpdateStatus.scored,
                "Low-trust source — advisory only; cannot change roadmap/skills without "
                "corroboration.")
    if relevance >= 0.5:
        return (relevance, risk, UpdateStatus.scored,
                "Relevant to ARIA's roadmap — consider a roadmap note or skill proposal "
                "(proposal only, not implementation).")
    return (relevance, risk, UpdateStatus.scored, "Low relevance — no action recommended.")
