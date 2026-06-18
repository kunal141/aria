"""
Typed models for the Week 34 read-only pilots.

Reports carry evidence references; findings that lack fixture support are marked
``evidence_required`` / ``evidence_missing`` rather than inventing claims. Draft
actions are **data artifacts only** — they carry explicit boundary text and are
never posted/sent/created in any external system.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Boundary strings attached to every draft (Week 34 §5).
JIRA_BOUNDARY = "Draft only. Not posted. No external write executed."
TEAMS_BOUNDARY = "Preview only. Not sent. No external write executed."
PR_COMMENT_BOUNDARY = "Draft only. Not posted. No external write executed."

EVIDENCE_REQUIRED = "evidence_required"
EVIDENCE_MISSING = "evidence_missing"


class PilotKind(str, Enum):
    pr_review = "pr_review"
    ci_cd = "ci_cd"
    analytics = "analytics"


class DraftKind(str, Enum):
    jira = "jira"
    teams = "teams"
    pr_comment = "pr_comment"


class EvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: str                       # e.g. "fixture:analytics:story_events:events"
    detail: str = ""                  # human-readable note (no secrets)


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str                         # schema / freshness / nulls / duplicates / ...
    summary: str
    severity: str = "info"            # info / low / medium / high
    # When a claim needs data we don't have, status flags it instead of inventing.
    status: str = "supported"         # supported | evidence_required | evidence_missing
    evidence: list[str] = Field(default_factory=list)


class DraftAction(BaseModel):
    model_config = ConfigDict(frozen=True)
    draft_id: str
    kind: DraftKind
    title: str
    body: str
    boundary: str                     # the draft-only boundary text
    approved: bool = False            # an approval marks the decision only
    # The target a real action WOULD touch — recorded for traceability only.
    would_target: str = ""


class PilotReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    pilot: PilotKind
    title: str
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    memory_citations: list[dict[str, Any]] = Field(default_factory=list)
    drafts: list[DraftAction] = Field(default_factory=list)
    boundary: str = "Read-only investigation. No external write executed."
    connector_mode: str = "fixtures"

    def render(self) -> str:
        """Human-readable report (used as the workspace artifact + terminal output).
        Contains only fixture-derived, non-secret content."""
        lines = [f"# {self.title}", "", self.summary, ""]
        if self.findings:
            lines.append("## Findings")
            for f in self.findings:
                flag = "" if f.status == "supported" else f"  [{f.status}]"
                ev = f" (evidence: {', '.join(f.evidence)})" if f.evidence else ""
                lines.append(f"- [{f.severity}] {f.kind}: {f.summary}{flag}{ev}")
            lines.append("")
        if self.memory_citations:
            lines.append("## Memory citations")
            for c in self.memory_citations:
                lines.append(
                    f"- memory {c.get('memory_id')} v{c.get('version')} — {c.get('retrieval_reason')}"
                )
            lines.append("")
        if self.evidence_references:
            lines.append("## Evidence references")
            for e in self.evidence_references:
                detail = f" — {e.detail}" if e.detail else ""
                lines.append(f"- {e.source}{detail}")
            lines.append("")
        if self.drafts:
            lines.append("## Draft actions (NOT executed)")
            for d in self.drafts:
                lines.append(f"- [{d.kind.value}] {d.title} — {d.boundary}")
            lines.append("")
        lines.append(f"Boundary: {self.boundary}")
        return "\n".join(lines)
