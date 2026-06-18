"""
Read-only Analytics / KPI / Events Investigation Pilot (Week 34 §4).

Reads a schema fixture + sample event rows, optionally uses approved Domain
Memory to *explain* event values, runs data-quality checks (schema / freshness /
nulls / duplicates / taxonomy / funnel / anomaly), and produces a cited report +
draft Jira items. Read-only: no database mutation.

Evidence discipline (critical):
  - Memory may explain WHAT values mean (with a citation).
  - Memory must NOT prove actual counts, drops, anomalies, or KPI changes.
  - Counts / anomalies require fixture (or query) evidence; if the event data is
    missing, those findings are marked ``evidence_required`` / ``evidence_missing``
    instead of inventing claims.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from aria.pilots.drafts import jira_draft
from aria.pilots.models import (
    EVIDENCE_MISSING,
    EVIDENCE_REQUIRED,
    EvidenceReference,
    Finding,
    PilotKind,
    PilotReport,
)

# A recall callable: (table, field) -> (mapping_dict, citation_dict) | None
RecallFn = Callable[[str, str], "tuple[dict, dict] | None"]


def run_analytics(
    connector, *, table: str = "story_events", recall: RecallFn | None = None,
) -> PilotReport:
    schema, schema_ev = connector.read_schema(table)
    events, events_ev = connector.read_events(table)
    evidence = list(schema_ev) + list(events_ev)

    findings: list[Finding] = []
    memory_citations: list[dict[str, Any]] = []
    known_taxonomy: set[int] = set()

    # ── Approved memory: explains value meanings only (never proves counts) ──
    if recall is not None:
        hit = recall(table, "event_type")
        if hit is not None:
            mapping, citation = hit
            memory_citations.append(citation)
            for k in (mapping or {}):
                try:
                    known_taxonomy.add(int(k))
                except (TypeError, ValueError):
                    continue
            findings.append(Finding(
                kind="memory", severity="info",
                summary=("event_type values explained from approved memory: "
                         + ", ".join(f"{k}={v}" for k, v in mapping.items())),
                evidence=[f"memory:{citation.get('memory_id')}:v{citation.get('version')}"],
            ))

    # ── Schema + freshness (schema-evidence backed) ──
    if schema is None:
        findings.append(Finding(kind="schema", summary=f"No schema fixture for {table}.",
                                status=EVIDENCE_MISSING, severity="medium"))
    else:
        nullable = [c["name"] for c in schema.get("columns", []) if c.get("nullable")]
        if nullable:
            findings.append(Finding(kind="schema", severity="low",
                                    summary=f"Nullable columns present: {nullable}.", evidence=schema_ev))
        fh, ft = schema.get("freshness_hours"), schema.get("freshness_threshold_hours")
        if fh is not None and ft is not None:
            stale = fh > ft
            findings.append(Finding(
                kind="freshness", severity="high" if stale else "info",
                summary=f"Data is {fh}h old (threshold {ft}h){' — STALE' if stale else ' — fresh'}.",
                evidence=schema_ev,
            ))

    # ── Count/anomaly checks REQUIRE event evidence ──
    if not events:
        for kind in ("nulls", "duplicates", "taxonomy", "funnel", "anomaly", "distribution"):
            findings.append(Finding(
                kind=kind, status=EVIDENCE_REQUIRED, severity="info",
                summary=f"{kind} check needs event data, which is not available — claim withheld.",
            ))
    else:
        # nulls
        null_session = sum(1 for r in events if r.get("session_id") is None)
        if null_session:
            findings.append(Finding(kind="nulls", severity="medium",
                                    summary=f"{null_session} row(s) with null session_id.", evidence=events_ev))
        # duplicates
        seen: set = set()
        dups = 0
        for r in events:
            key = tuple(sorted((k, str(v)) for k, v in r.items()))
            if key in seen:
                dups += 1
            else:
                seen.add(key)
        if dups:
            findings.append(Finding(kind="duplicates", severity="low",
                                    summary=f"{dups} duplicate row(s).", evidence=events_ev))
        # distribution (counts are fixture-evidence backed)
        dist = Counter(r["event_type"] for r in events)
        findings.append(Finding(kind="distribution", severity="info",
                                summary=f"event_type distribution: {dict(sorted(dist.items()))}.",
                                evidence=events_ev))
        # taxonomy + anomaly — against the memory-defined taxonomy when available
        baseline = known_taxonomy or {1, 2, 3}
        unknown = sorted(et for et in dist if et not in baseline)
        if unknown:
            src = "approved memory" if known_taxonomy else "the default {1,2,3} taxonomy"
            findings.append(Finding(kind="taxonomy", severity="high",
                                    summary=f"event_type values {unknown} are outside {src}.",
                                    evidence=events_ev))
            findings.append(Finding(kind="anomaly", severity="high",
                                    summary=f"Anomalous event_type {unknown} present (unexpected value).",
                                    evidence=events_ev))
        # funnel consistency (page_view >= story_click) — needs counts (evidence)
        pv, sc = dist.get(1, 0), dist.get(2, 0)
        if sc > pv:
            findings.append(Finding(kind="funnel", severity="medium",
                                    summary=f"story_click ({sc}) exceeds page_view ({pv}) — funnel inconsistency.",
                                    evidence=events_ev))
        else:
            findings.append(Finding(kind="funnel", severity="info",
                                    summary=f"Funnel consistent: page_view ({pv}) >= story_click ({sc}).",
                                    evidence=events_ev))

    # ── Draft Jira for actionable data-quality issues ──
    drafts = []
    if any(f.kind == "nulls" and f.status == "supported" for f in findings):
        drafts.append(jira_draft(
            title=f"Investigate null session_id in {table}",
            body=f"{table} has rows with null session_id; trace the ingestion path and backfill.",
            would_target="jira",
        ))
    if any(f.kind == "taxonomy" and f.status == "supported" for f in findings):
        drafts.append(jira_draft(
            title=f"Unknown event_type values in {table}",
            body=f"{table} contains event_type values outside the approved taxonomy; confirm or map them.",
            would_target="jira",
        ))

    summary = (
        f"Events/KPI investigation for {table}: {len(findings)} finding(s), "
        f"{len(memory_citations)} memory citation(s). Read-only — no data mutated."
    )
    return PilotReport(
        pilot=PilotKind.analytics, title="Events/KPI Investigation Report", summary=summary,
        findings=findings, drafts=drafts, memory_citations=memory_citations,
        evidence_references=[EvidenceReference(source=s, detail=table) for s in evidence],
        connector_mode=connector.mode.value,
        boundary="Read-only analytics investigation. No data mutation.",
    )
