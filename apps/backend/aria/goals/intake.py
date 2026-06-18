"""
Goal Intake Engine (V3.1) — deterministic, offline, evidence-disciplined.

Turns a vague request into a structured goal brief (problem statement, goal,
success criteria, known/missing context, clarifying questions, constraints) and a
phased roadmap. Like the V2 ``extraction`` module, this is **rule-based and
deterministic** — no LLM — so the lifecycle is testable offline and never
hallucinates a metric.

Discipline (matches V2 boundaries):
  - It NEVER asserts a metric value, baseline, or count. Anything numeric is asked
    for as *missing context* / *evidence needed*, never fabricated.
  - Memory may later supply *definitions* (what a field means); definitions never
    become factual evidence here — the intake only plans what evidence to gather.
  - Every plan ends with a governance success criterion: "no production writes".

The engine recognises a few domains heuristically (metric-drop investigation,
quality-improvement, generic) and emits a tailored-but-conservative brief. Unknown
requests fall back to a safe generic structure rather than guessing specifics.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aria.goals.models import (
    GoalIntake,
    GoalStatus,
    Roadmap,
    RoadmapPhase,
)
from aria.goals.sanitize import sanitize_goal_intake

# Conservative, deterministic keyword signals.
_METRIC_WORDS = (
    "ctr", "click-through", "click through", "conversion", "open rate", "bounce",
    "engagement", "retention", "traffic", "impressions", "rate", "metric", "kpi",
    "dau", "mau", "revenue", "sessions",
)
_DROP_WORDS = ("drop", "dropping", "declin", "falling", "fell", "down", "decreas",
               "regress", "worse", "low", "lower", "anomaly", "spike")
_QUALITY_WORDS = ("quality", "inconsistent", "inconsistency", "consistency", "accuracy",
                  "readability", "tone", "grammar", "language quality", "improve",
                  "improvement", "standard")
_GOVERNANCE_CRITERION = "no production writes performed"

# A trailing imperative like "Own this." / "own it" / "please own this" is the
# ownership signal, not part of the subject — strip it for the subject phrase.
_OWNERSHIP_RE = re.compile(r"\b(own (this|it)|take (this )?over|please own.*)\b\.?\s*$", re.IGNORECASE)


@dataclass
class _Brief:
    domain: str
    title: str
    problem_statement: str
    goal: str
    success_criteria: list[str]
    known_context: list[str]
    missing_context: list[str]
    clarifying_questions: list[str]
    constraints: list[str] = field(default_factory=list)
    phases: list[tuple[str, str, list[str]]] = field(default_factory=list)  # (name, objective, evidence)
    milestones: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


def _subject(raw: str) -> str:
    """Best-effort subject phrase: drop a trailing ownership imperative and a
    leading 'our/the/we should' so the brief reads naturally. Deterministic."""
    text = raw.strip()
    text = _OWNERSHIP_RE.sub("", text).strip().rstrip(".").strip()
    text = re.sub(r"^(our|the|we should|we need to|can you|please)\s+", "", text, flags=re.IGNORECASE)
    return text or raw.strip().rstrip(".")


def _has(text: str, words) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def _detect_domain(text: str) -> str:
    if _has(text, _METRIC_WORDS) and _has(text, _DROP_WORDS):
        return "metric_investigation"
    if _has(text, _QUALITY_WORDS):
        return "quality_improvement"
    return "generic"


def _metric_brief(raw: str, subject: str) -> _Brief:
    return _Brief(
        domain="metric_investigation",
        title=subject[:80] or "Metric investigation",
        problem_statement=(
            f"{subject} — a metric appears to be moving unfavourably and needs a "
            "structured, evidence-based investigation before any action is taken."
        ),
        goal="Identify the likely causes of the metric change and propose a governed improvement plan.",
        success_criteria=[
            "metric trend verified with evidence (not assumed)",
            "affected platforms/segments identified",
            "event/data freshness checked",
            "campaign/content/release factors reviewed",
            "likely root causes listed with supporting evidence",
            "draft action items created (draft-only)",
            _GOVERNANCE_CRITERION,
        ],
        known_context=[
            f"User reports: {raw.strip()}",
            "Relevant analytics/event data may exist for this metric",
        ],
        missing_context=[
            "time range / comparison window",
            "platform (web, app, or both)",
            "campaign / segment IDs",
            "baseline value to compare against",
            "authoritative data source",
        ],
        clarifying_questions=[
            "What date range should be checked?",
            "Which platform: web, app, or both?",
            "Should this focus on all traffic or a specific campaign/segment?",
            "What is the trusted data source for this metric?",
        ],
        constraints=[
            "read-only by default; no production writes without approval",
            "fixtures-first; no live connectors by default",
            "metrics must be evidenced, never assumed",
        ],
        phases=[
            ("Validate metric trend", "Confirm the change is real using evidence, not assumption.",
             ["metric time series for the window", "baseline comparison"]),
            ("Check data freshness", "Rule out a data/pipeline freshness problem.",
             ["ingestion timestamps", "row recency"]),
            ("Check event taxonomy", "Confirm event definitions/mappings are correct.",
             ["event schema", "approved field definitions"]),
            ("Compare segments", "Compare platform / category / campaign segments.",
             ["per-segment metric breakdown"]),
            ("Identify possible root causes", "List candidate causes with supporting evidence.",
             ["correlated changes (releases, content, delivery)"]),
            ("Draft action plan", "Prepare draft-only action items for review.", []),
            ("Prepare manager summary", "Produce an audience-aware summary for approval.", []),
        ],
        milestones=["trend validated", "root causes identified", "action plan drafted"],
        risks=[
            "data freshness or taxonomy issues could mimic a real metric drop",
            "segment mix shifts can confound the top-line metric",
        ],
        deliverables=[
            "evidence-backed root-cause summary",
            "draft action items (draft-only)",
            "manager-ready summary",
        ],
    )


def _quality_brief(raw: str, subject: str) -> _Brief:
    return _Brief(
        domain="quality_improvement",
        title=subject[:80] or "Quality improvement",
        problem_statement=(
            f"{subject} — output quality is reported as inconsistent and needs a "
            "structured definition of 'good' and an evidence-based improvement plan."
        ),
        goal="Define quality criteria, find inconsistency patterns from evidence, and propose a governed improvement plan.",
        success_criteria=[
            "quality dimensions explicitly defined",
            "a representative sample reviewed against the definition",
            "inconsistency patterns identified with examples",
            "improvement guidelines drafted (draft-only)",
            "measurable quality check proposed",
            _GOVERNANCE_CRITERION,
        ],
        known_context=[
            f"User reports: {raw.strip()}",
            "There is an existing body of content/output to sample",
        ],
        missing_context=[
            "which content type / surface / segment",
            "what 'good quality' means here (the rubric)",
            "time range / sample size to review",
            "who owns the quality standard",
        ],
        clarifying_questions=[
            "Which content type or surface should this focus on?",
            "What defines acceptable quality (a rubric or examples)?",
            "What time range or sample size should be reviewed?",
        ],
        constraints=[
            "read-only by default; no production writes without approval",
            "quality judgments must cite sampled evidence, not assumptions",
        ],
        phases=[
            ("Define quality criteria", "Agree the rubric/dimensions for 'good'.",
             ["existing style/quality guidelines, if any"]),
            ("Sample review", "Review a representative sample against the rubric.",
             ["sampled content set"]),
            ("Identify gaps", "Identify recurring inconsistency patterns with examples.",
             ["annotated examples"]),
            ("Propose guidelines", "Draft improvement guidelines (draft-only).", []),
            ("Draft action plan", "Prepare draft-only action items for review.", []),
            ("Prepare manager summary", "Produce an audience-aware summary for approval.", []),
        ],
        milestones=["rubric agreed", "patterns identified", "guidelines drafted"],
        risks=["a subjective rubric can make findings hard to act on"],
        deliverables=["quality rubric", "pattern findings with examples", "draft guidelines", "manager-ready summary"],
    )


def _generic_brief(raw: str, subject: str) -> _Brief:
    return _Brief(
        domain="generic",
        title=subject[:80] or "Goal",
        problem_statement=(
            f"{subject} — this needs to be turned into a clear problem and worked "
            "through a structured, evidence-based plan before any action is taken."
        ),
        goal=f"Understand and address: {subject}.",
        success_criteria=[
            "scope and success measure clarified with the stakeholder",
            "relevant evidence gathered",
            "options identified with trade-offs",
            "draft action plan created (draft-only)",
            _GOVERNANCE_CRITERION,
        ],
        known_context=[f"User reports: {raw.strip()}"],
        missing_context=[
            "precise scope / boundaries",
            "definition of success",
            "timeline / priority",
            "stakeholders and data sources",
        ],
        clarifying_questions=[
            "What exactly is in and out of scope?",
            "What does success look like (a measurable outcome)?",
            "What is the timeline or priority?",
        ],
        constraints=[
            "read-only by default; no production writes without approval",
            "claims must be evidenced, never assumed",
        ],
        phases=[
            ("Clarify scope", "Pin down scope, success measure, and constraints.", []),
            ("Gather evidence", "Collect the evidence needed to reason about the goal.",
             ["relevant data/docs"]),
            ("Analyse", "Analyse the evidence and identify options.", []),
            ("Propose plan", "Propose a governed plan with trade-offs.", []),
            ("Draft action plan", "Prepare draft-only action items for review.", []),
            ("Prepare manager summary", "Produce an audience-aware summary for approval.", []),
        ],
        milestones=["scope agreed", "evidence gathered", "plan drafted"],
        risks=["unclear scope can lead to wasted effort"],
        deliverables=["evidence summary", "options with trade-offs", "draft action plan"],
    )


_BUILDERS = {
    "metric_investigation": _metric_brief,
    "quality_improvement": _quality_brief,
    "generic": _generic_brief,
}


def run_intake(
    raw_request: str, *, scope: str = "general", stakeholders: list[str] | None = None,
) -> GoalIntake:
    """Convert a vague request into a structured GoalIntake (deterministic)."""
    raw = (raw_request or "").strip()
    if not raw:
        raise ValueError("raw_request must be non-empty")
    subject = _subject(raw)
    domain = _detect_domain(raw)
    brief = _BUILDERS[domain](raw, subject)
    now = _now()
    intake = GoalIntake(
        goal_id=f"goal-{uuid.uuid4().hex}",
        title=brief.title,
        raw_request=raw,
        problem_statement=brief.problem_statement,
        goal=brief.goal,
        success_criteria=brief.success_criteria,
        known_context=brief.known_context,
        missing_context=brief.missing_context,
        clarifying_questions=brief.clarifying_questions,
        constraints=brief.constraints,
        stakeholders=stakeholders or [],
        scope=scope,
        risk_level="low",
        status=GoalStatus.intake,
        created_at=now,
        updated_at=now,
    )
    # Mask any secret carried in the request BEFORE it leaves the engine. The
    # authoritative boundary is GoalStore.create_goal(); this is defence in depth so
    # the in-memory goal (and any artifact rendered from it) is already clean.
    return sanitize_goal_intake(intake)


def build_roadmap(intake: GoalIntake) -> Roadmap:
    """Build a phased roadmap for a goal (deterministic, from the same domain brief)."""
    domain = _detect_domain(intake.raw_request)
    brief = _BUILDERS[domain](intake.raw_request, _subject(intake.raw_request))
    now = _now()
    phases = [
        RoadmapPhase(order=i + 1, name=name, objective=obj, evidence_needed=list(ev))
        for i, (name, obj, ev) in enumerate(brief.phases)
    ]
    # Evidence needed across the whole roadmap (deduped, order-preserving).
    seen: set[str] = set()
    evidence_needed: list[str] = []
    for p in phases:
        for e in p.evidence_needed:
            if e not in seen:
                seen.add(e)
                evidence_needed.append(e)
    return Roadmap(
        roadmap_id=f"rm-{uuid.uuid4().hex}",
        goal_id=intake.goal_id,
        phases=phases,
        milestones=list(brief.milestones),
        dependencies=[],
        risks=list(brief.risks),
        evidence_needed=evidence_needed,
        deliverables=list(brief.deliverables),
        created_at=now,
        updated_at=now,
    )
