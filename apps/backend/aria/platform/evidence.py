"""
Platform Intelligence — Evidence Assembler

The single entry point for producing EvidencedAnswer objects.

Contract:
  - The LLM NEVER decides whether a claim is supported. Only deterministic
    code in this module makes that determination.
  - Two-phase authorization is enforced:
      Phase 1 — at SourceRepository.query() (sources.py)
      Phase 2 — check_authorization() re-verified here for every candidate
  - Fail closed on missing evidence, missing timestamps, or auth failures.
  - answer="" and is_safe_to_surface=False whenever any claim is unsupported.
  - restricted content NEVER appears in answer, citations, logs, or reason fields.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .catalog import ServiceCatalog
from .evaluator import build_evidence, check_authorization, detect_conflicts
from .models import (
    ClaimEvidence,
    ClaimSpec,
    EvidencedAnswer,
    KnowledgeSource,
    SensitivityLevel,
)
from .sources import SourceRepository


class EvidenceAssembler:
    """
    Assembles a fully-evidenced answer for a set of claims.

    Usage:
        assembler = EvidenceAssembler(catalog, source_repo)
        answer = assembler.assemble(
            query="...",
            claims=[ClaimSpec(...)],
            caller_level="internal",
            candidate_sources=sources,   # already Phase-1 filtered
        )
    """

    def __init__(
        self,
        catalog: ServiceCatalog,
        source_repo: SourceRepository,
    ) -> None:
        self._catalog = catalog
        self._source_repo = source_repo

    def assemble(
        self,
        query: str,
        claims: list[ClaimSpec],
        caller_level: SensitivityLevel,
        candidate_sources: list[KnowledgeSource] | None = None,
        now: datetime | None = None,
    ) -> EvidencedAnswer:
        """
        For each claim, retrieve evidence and produce a machine-readable mapping.

        candidate_sources: if provided, use these instead of querying the repo.
            Must be Phase-1 authorized already (repo.query() result).
            If None, the assembler queries the repo for each claim.

        Fail-closed invariants:
          - Claim with no authorized evidence → is_supported=False
          - Any unsupported claim → is_safe_to_surface=False, answer=""
          - Unresolved conflict → both sources excluded from selected_evidence
        """
        if now is None:
            now = datetime.now(timezone.utc)

        claim_evidence_map: list[ClaimEvidence] = []
        authorization_decisions = []
        freshness_warnings: list[str] = []

        for claim in claims:
            # Retrieve candidate sources for this claim
            if candidate_sources is not None:
                raw_sources = [
                    s for s in candidate_sources
                    if s.service_id in claim.service_ids
                    and s.source_type in claim.source_types
                ]
            else:
                raw_sources = self._source_repo.query(
                    caller_level=caller_level,
                    service_ids=claim.service_ids,
                    source_types=claim.source_types,
                    keywords=claim.keywords,
                )

            # Phase-2 authorization — re-verify each source
            authorized_sources: list[KnowledgeSource] = []
            for src in raw_sources:
                decision = check_authorization(caller_level, src)
                authorization_decisions.append(decision)
                if decision.allowed:
                    authorized_sources.append(src)

            # Detect and resolve conflicts among authorized sources
            conflicts = detect_conflicts(claim.claim_id, authorized_sources)
            excluded_ids: set[str] = set()
            for conflict in conflicts:
                if conflict.resolved_by == "unresolved":
                    excluded_ids.add(conflict.source_a_id)
                    excluded_ids.add(conflict.source_b_id)

            # Build evidence objects for non-excluded sources
            evidence_list = []
            for src in authorized_sources:
                if src.source_id in excluded_ids:
                    continue
                ev = build_evidence(src, claim.keywords, now)
                evidence_list.append(ev)
                if ev.is_stale:
                    freshness_warnings.append(
                        f"Claim '{claim.claim_id}': source '{src.source_id}' "
                        f"is {ev.staleness_hours}h old (threshold: "
                        f"{src.source_type} limit)"
                    )

            # Select best evidence (highest authority, then most recent)
            selected: ClaimEvidence = _select_best(claim, evidence_list, conflicts, now)
            claim_evidence_map.append(selected)

        # Gate the answer if any claim is unsupported
        all_supported = all(ce.is_supported for ce in claim_evidence_map)
        if all_supported:
            is_safe = True
            answer = _synthesize_answer(query, claim_evidence_map)
            blocked_reason: str | None = None
        else:
            is_safe = False
            answer = ""
            unsupported = [ce.claim_id for ce in claim_evidence_map if not ce.is_supported]
            blocked_reason = (
                f"Unsupported claims (no authorized evidence found): "
                f"{', '.join(unsupported)}"
            )

        return EvidencedAnswer(
            answer_id=str(uuid.uuid4()),
            query=query,
            answer=answer,
            claim_evidence_map=claim_evidence_map,
            authorization_decisions=authorization_decisions,
            freshness_warnings=freshness_warnings,
            is_safe_to_surface=is_safe,
            blocked_reason=blocked_reason,
            assembled_at=now.isoformat(),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _select_best(
    claim: ClaimSpec,
    evidence_list: list,
    conflicts: list,
    now: datetime,
) -> ClaimEvidence:
    """Pick the single best evidence item; record selection reason."""
    if not evidence_list:
        return ClaimEvidence(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            evidence=[],
            is_supported=False,
            conflicts=conflicts,
            selected_evidence=None,
            selection_reason=None,
        )

    # Sort by authority desc, then by content_updated_at desc
    def _sort_key(ev):
        try:
            ts = datetime.fromisoformat(ev.content_updated_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.min.replace(tzinfo=timezone.utc)
        return (ev.authority, ts)

    sorted_ev = sorted(evidence_list, key=_sort_key, reverse=True)
    best = sorted_ev[0]

    if len(evidence_list) == 1:
        reason = f"only available evidence (authority={best.authority})"
    else:
        reason = f"highest authority={best.authority} among {len(evidence_list)} sources"
    if best.is_stale:
        reason += " [stale — best available]"

    return ClaimEvidence(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        evidence=evidence_list,
        is_supported=True,
        conflicts=conflicts,
        selected_evidence=best,
        selection_reason=reason,
    )


def _synthesize_answer(query: str, claim_evidence_map: list[ClaimEvidence]) -> str:
    """
    V1 deterministic answer synthesis — no LLM involvement.
    Concatenates claim text + selected evidence excerpt per claim.
    A real V2 implementation could pass this structure to an LLM for fluency,
    but the LLM would NOT be allowed to add unsupported claims.
    """
    parts: list[str] = [f"Query: {query}", ""]
    for ce in claim_evidence_map:
        ev = ce.selected_evidence
        if ev:
            stale_flag = " [stale]" if ev.is_stale else ""
            parts.append(
                f"[{ce.claim_id}] {ce.claim_text}\n"
                f"  Source: {ev.source_id} (authority={ev.authority}{stale_flag})\n"
                f"  Evidence: {ev.excerpt[:200]}"
            )
    return "\n".join(parts)
