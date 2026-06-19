"""
Dynamic Agent Workforce — V3.3 (DRY-RUN / fixture-first).

Lets ARIA decompose a goal into a BOUNDED set of specialist-agent briefs, simulate
their work deterministically, and merge the outputs into one goal-level summary —
all under governance. There is NO real agent process, NO network, NO live connector,
and NO external write anywhere in this module.

Hard boundaries (V2/V3.1/V3.2 preserved):
  - planning + DRY-RUN only; an "agent" is a typed brief + a simulated result.
  - every brief has a NARROW objective, explicit allowed/forbidden context, a
    read-only tool allowlist, an always-forbidden WRITE-tool list, evidence inputs,
    an output schema, risk/time/cost limits, and an approval flag.
  - approval-required assignments do NOT run (they return blocked_for_approval).
  - missing evidence returns blocked_for_evidence (agents never fabricate evidence).
  - cancelled/killed assignments never present findings as if completed.
  - findings are never invented when agents are blocked.
  - secrets are sanitised out of every persisted/returned string.
  - failures fail safely (class-only message, never raw text).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_log = logging.getLogger("aria.goals.agents")

from aria.goals.intake import _detect_domain  # deterministic domain detection
from aria.goals.models import (
    AgentAssignment,
    AgentBrief,
    AgentMergeResult,
    AgentPlan,
    AgentStatus,
    GoalIntake,
)
from aria.goals.sanitize import sanitize_text
from aria.goals.store import GoalNotFound, GoalStore

# Read-only tool catalog. Briefs may only draw ``allowed_tools`` from this set.
_READONLY_TOOLS = ("recall_memory", "read_schema", "read_events", "read_pr", "read_ci_run", "read_docs")
# WRITE tools are ALWAYS forbidden for every agent (no live writes in V3.3).
_FORBIDDEN_WRITE_TOOLS = (
    "jira_create", "teams_send", "pr_comment", "deploy", "db_write", "run_pipeline", "fs_write",
)
_FORBIDDEN_CONTEXT = ("pii", "secrets", "credentials", "other_teams_data")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _AgentTemplate:
    name: str
    role: str
    objective: str
    required_inputs: tuple[str, ...]
    tools: tuple[str, ...]
    uses_memory: bool = False
    approval_required: bool = False


# Deterministic per-domain agent templates (bounded — a small, fixed workforce).
_TEMPLATES: dict[str, tuple[_AgentTemplate, ...]] = {
    "metric_investigation": (
        _AgentTemplate("Data Freshness Agent", "data_quality",
                       "Check ingestion freshness and row recency for the metric source.",
                       ("ingestion timestamps", "row recency"), ("read_schema", "read_events")),
        _AgentTemplate("Event Taxonomy Agent", "analytics",
                       "Verify event_type mappings and taxonomy consistency.",
                       ("event schema", "sample event distribution"),
                       ("recall_memory", "read_schema", "read_events"), uses_memory=True),
        _AgentTemplate("Campaign Analysis Agent", "analytics",
                       "Compare campaign/segment performance for the metric.",
                       ("per-segment metric breakdown",), ("read_events",)),
        _AgentTemplate("Content Quality Agent", "content",
                       "Assess notification content/format quality factors.",
                       ("content sample",), ("read_docs",)),
        _AgentTemplate("Recommendation Analyst Agent", "recommendation",
                       "Analyse whether ranking/retrieval changes affect the metric and propose options.",
                       ("ranking change log",), ("recall_memory", "read_events"),
                       uses_memory=True, approval_required=True),
        _AgentTemplate("Manager Summary Agent", "reporting",
                       "Summarise findings for leadership in audience-aware language.",
                       (), ("recall_memory",), uses_memory=True),
    ),
    "quality_improvement": (
        _AgentTemplate("Content Quality Agent", "content",
                       "Define quality dimensions and review a content sample.",
                       ("content sample",), ("read_docs",)),
        _AgentTemplate("Style Consistency Agent", "content",
                       "Identify style/consistency inconsistencies against the rubric.",
                       ("style guide",), ("read_docs", "recall_memory"), uses_memory=True),
        _AgentTemplate("Manager Summary Agent", "reporting",
                       "Summarise quality findings for leadership.",
                       (), ("recall_memory",), uses_memory=True),
    ),
    "generic": (
        _AgentTemplate("Research Agent", "research",
                       "Gather and summarise the evidence relevant to the goal.",
                       ("relevant docs",), ("read_docs",)),
        _AgentTemplate("Analysis Agent", "analysis",
                       "Analyse the evidence and identify options with trade-offs.",
                       ("evidence set",), ("read_docs",)),
        _AgentTemplate("Manager Summary Agent", "reporting",
                       "Summarise the analysis for leadership.",
                       (), ("recall_memory",), uses_memory=True),
    ),
}


class AgentWorkforceService:
    def __init__(
        self, store: GoalStore, *, workspace_store: Any = None,
        execution_mode: str | None = None, actor: str = "aria",
    ) -> None:
        self._store = store
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor

    # ── 1. Planner ────────────────────────────────────────────────────────────

    def plan(self, goal_id: str, *, actor: str | None = None) -> AgentPlan:
        actor = actor or self._actor
        goal = self._store.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        # Idempotent: if a workforce already exists for this goal, return it without
        # creating duplicate briefs/assignments (repeated POST / double-click safe).
        existing = self._store.get_agent_briefs(goal_id)
        if existing:
            return AgentPlan(
                goal_id=goal_id, briefs=existing,
                assignments=self._store.get_agent_assignments(goal_id),
            )
        domain = _detect_domain(goal.raw_request)
        templates = _TEMPLATES.get(domain, _TEMPLATES["generic"])
        now = _now()
        briefs: list[AgentBrief] = []
        assignments: list[AgentAssignment] = []
        for tpl in templates:
            agent_id = f"agent-{uuid.uuid4().hex}"
            allowed_tools = [t for t in tpl.tools if t in _READONLY_TOOLS]
            allowed_context = ["goal_brief", "roadmap", "fixtures"]
            if tpl.uses_memory:
                allowed_context.append(f"memory:{goal.scope}")
            briefs.append(AgentBrief(
                agent_id=agent_id, goal_id=goal_id, task_id=None, name=tpl.name, role=tpl.role,
                objective=tpl.objective, allowed_context=allowed_context,
                forbidden_context=list(_FORBIDDEN_CONTEXT), allowed_tools=allowed_tools,
                forbidden_tools=list(_FORBIDDEN_WRITE_TOOLS), required_inputs=list(tpl.required_inputs),
                expected_output_schema=f"{tpl.role.title().replace('_', '')}Findings",
                approval_required=tpl.approval_required, risk_level="low",
                time_limit_seconds=60, cost_limit_units=1, status=AgentStatus.planned,
                created_at=now, updated_at=now,
            ))
            assignments.append(AgentAssignment(
                assignment_id=f"assign-{uuid.uuid4().hex}", agent_id=agent_id, goal_id=goal_id,
                task_id=None, workspace_id=goal.workspace_id,
                input_summary=f"inputs: {', '.join(tpl.required_inputs) or 'none'}",
                status=AgentStatus.planned, approval_required=tpl.approval_required,
                max_runtime_seconds=60, max_cost_units=1, risk_level="low", supervisor=actor,
            ))
        self._store.save_agent_plan(briefs, assignments, actor=actor)
        self._attach_plan_to_workspace(goal, briefs, assignments, actor=actor)
        return AgentPlan(goal_id=goal_id, briefs=self._store.get_agent_briefs(goal_id),
                         assignments=self._store.get_agent_assignments(goal_id))

    # ── 3. Dry-run executor + 4. merger ──────────────────────────────────────

    def run_dry(self, goal_id: str, *, actor: str | None = None) -> AgentMergeResult:
        actor = actor or self._actor
        goal = self._store.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        provided = set(self._store.list_evidence(goal_id))
        briefs = {b.agent_id: b for b in self._store.get_agent_briefs(goal_id)}
        for assignment in self._store.get_agent_assignments(goal_id):
            if not self._is_runnable(assignment):
                continue
            brief = briefs.get(assignment.agent_id)
            if brief is None:
                continue
            self._run_one(goal, brief, assignment, provided, actor=actor)
        return self.summary(goal_id, actor=actor, emit=True)

    @staticmethod
    def _is_runnable(assignment: AgentAssignment) -> bool:
        """An assignment may (re)run unless it is terminal. ``blocked_for_evidence``
        is RECOVERABLE — once evidence is supplied a re-run can complete it.
        ``blocked_for_approval`` stays blocked (no approval mechanism in V3.3).
        completed / failed / cancelled / killed are terminal."""
        if assignment.status in (
            AgentStatus.completed, AgentStatus.failed,
            AgentStatus.cancelled, AgentStatus.killed,
        ):
            return False
        if assignment.status is AgentStatus.blocked:
            return assignment.failure_reason == "blocked_for_evidence"
        return True   # planned / ready / running

    def _run_one(self, goal, brief: AgentBrief, assignment: AgentAssignment, provided, *, actor):
        aid = assignment.assignment_id
        self._store.update_agent_assignment(aid, status=AgentStatus.running, started_at=_now(), actor=actor)
        # The WHOLE body — including the workspace artifact write — runs inside the
        # safe boundary, so an artifact/write failure becomes a SAFE assignment
        # failure (class-only reason, never raw text, never left ``running``).
        try:
            status, summary, artifact_content, failure = self._dry_execute(goal, brief, provided)
            artifact_ref = None
            if status is AgentStatus.completed and artifact_content and self._workspace_store \
                    and goal.workspace_id:
                name = f"agent_{brief.role}_{uuid.uuid4().hex[:8]}.md"
                artifact_ref = self._workspace_store.write_artifact(goal.workspace_id, name, artifact_content)
            self._store.update_agent_assignment(
                aid, status=status, output_summary=summary, output_artifact=artifact_ref,
                failure_reason=failure, completed_at=_now(), actor=actor,
            )
        except Exception as exc:  # safe failure — class only, never raw text; not left running
            _log.error("agent dry-run step failed (class only): %s", type(exc).__name__)
            self._store.update_agent_assignment(
                aid, status=AgentStatus.failed,
                failure_reason=f"internal error ({type(exc).__name__})", completed_at=_now(), actor=actor,
            )
            return
        # Secondary workspace bookkeeping is best-effort — it must NOT flip a
        # completed assignment to failed or surface raw text.
        self._safe_workspace_update(goal, aid, status, artifact_ref, actor=actor)

    def _safe_workspace_update(self, goal, aid: str, status, artifact_ref, *, actor) -> None:
        if self._workspace_store is None or not goal.workspace_id:
            return
        try:
            self._workspace_store.update_workspace(
                goal.workspace_id, status=f"agent:{status.value}",
                add_artifact_refs=[artifact_ref] if artifact_ref else None,
                add_ledger_refs=[f"assignment:{aid}:{status.value}"], actor=actor,
            )
        except Exception as exc:  # pragma: no cover - defensive
            _log.error("agent workspace bookkeeping failed (class only): %s", type(exc).__name__)

    def _dry_execute(self, goal: GoalIntake, brief: AgentBrief, provided: set[str]):
        """Deterministic, offline simulation. Returns
        (status, output_summary, artifact_content, failure_reason)."""
        # Approval gate — an approval-required agent does NOT run.
        if brief.approval_required:
            return (AgentStatus.blocked,
                    f"{brief.name}: awaiting approval — not run (blocked_for_approval).",
                    None, "blocked_for_approval")
        # Evidence gate — agents never fabricate evidence.
        missing = [e for e in brief.required_inputs if e not in provided]
        if missing:
            return (AgentStatus.blocked,
                    f"{brief.name}: evidence needed before findings (blocked_for_evidence).",
                    None, "blocked_for_evidence")
        # Completed: produce deterministic findings (memory explains, evidence proves).
        summary = (
            f"{brief.name}: {brief.objective} Used approved memory for definitions; "
            f"evidence: {', '.join(brief.required_inputs) or 'none required'}; produced findings."
        )
        artifact = self._render_agent_artifact(goal, brief)
        return AgentStatus.completed, summary, artifact, None

    @staticmethod
    def _render_agent_artifact(goal: GoalIntake, brief: AgentBrief) -> str:
        mem = [c for c in brief.allowed_context if c.startswith("memory:")]
        return "\n".join([
            f"# {brief.name}",
            "",
            f"**Goal:** {goal.title}  ·  **Role:** {brief.role}  ·  **Risk:** {brief.risk_level}",
            "",
            "## Objective", brief.objective, "",
            "## Memory used (definitions only)",
            *([f"- {m}" for m in mem] or ["- (none)"]),
            "## Required evidence",
            *([f"- {e}" for e in brief.required_inputs] or ["- (none)"]),
            "",
            "## Findings",
            "- Deterministic dry-run findings based on provided evidence and approved memory.",
            "",
            "## Boundary",
            "- Read-only dry-run. No external writes. No live connectors. No real agent process.",
        ])

    def summary(self, goal_id: str, *, actor: str | None = None, emit: bool = True) -> AgentMergeResult:
        actor = actor or self._actor
        goal = self._store.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        briefs = {b.agent_id: b for b in self._store.get_agent_briefs(goal_id)}
        assignments = self._store.get_agent_assignments(goal_id)

        completed = [a for a in assignments if a.status is AgentStatus.completed]
        blocked = [a for a in assignments if a.status in (AgentStatus.blocked, AgentStatus.failed)]
        cancelled = [a for a in assignments if a.status in (AgentStatus.cancelled, AgentStatus.killed)]

        key_findings = [a.output_summary for a in completed if a.output_summary]
        blocked_reasons = [
            f"{briefs[a.agent_id].name if a.agent_id in briefs else a.agent_id}: "
            f"{a.failure_reason or 'blocked'}"
            for a in blocked
        ]
        evidence_refs, memory_citations, deliverables = [], [], []
        for a in completed:
            b = briefs.get(a.agent_id)
            if b:
                evidence_refs.extend(b.required_inputs)
                memory_citations.extend(c for c in b.allowed_context if c.startswith("memory:"))
            if a.output_artifact:
                deliverables.append(a.output_artifact)
        evidence_refs = list(dict.fromkeys(evidence_refs))
        memory_citations = list(dict.fromkeys(memory_citations))

        risks = [goal.risk_level]
        if blocked:
            risks.append(f"{len(blocked)} agent(s) blocked — findings incomplete")
        next_action = (
            "Resolve agent blockers (provide evidence / obtain approval), then re-run the workforce"
            if blocked else
            ("Review merged agent findings and approve next steps" if completed
             else "Plan and run the agent workforce")
        )
        result = AgentMergeResult(
            goal_id=goal_id, agents_run=len(assignments), completed_assignments=len(completed),
            blocked_assignments=len(blocked), cancelled_assignments=len(cancelled),
            key_findings=key_findings, blocked_reasons=blocked_reasons, evidence_refs=evidence_refs,
            memory_citations=memory_citations, deliverables=deliverables, draft_actions=[],
            risks=risks, next_recommended_action=next_action,
        )
        if emit:
            self._store.emit_agent_result_merged(
                goal_id, outcome=f"completed={len(completed)}/{len(assignments)}", actor=actor,
            )
            self._attach_merge_to_workspace(goal, result, actor=actor)
        return result

    # ── 5. Supervision / kill switch ──────────────────────────────────────────

    def cancel_assignment(
        self, assignment_id: str, *, reason: str = "cancelled by supervisor",
        killed: bool = False, supervisor: str | None = None, actor: str | None = None,
    ) -> AgentAssignment:
        actor = actor or self._actor
        a = self._store.get_agent_assignment(assignment_id)
        if a is None:
            raise GoalNotFound(f"assignment {assignment_id!r} not found")
        status = AgentStatus.killed if killed else AgentStatus.cancelled
        return self._store.update_agent_assignment(
            assignment_id, status=status, kill_reason=reason, supervisor=supervisor or actor,
            stopped_at=_now(), actor=actor,
        )

    # ── Pass-through reads ────────────────────────────────────────────────────

    def get_briefs(self, goal_id: str):
        return self._store.get_agent_briefs(goal_id)

    def get_assignments(self, goal_id: str):
        return self._store.get_agent_assignments(goal_id)

    # ── Workspace integration ─────────────────────────────────────────────────

    def _attach_plan_to_workspace(self, goal, briefs, assignments, *, actor):
        ws = self._workspace_store
        if ws is None or not goal.workspace_id:
            return
        ledger_refs = [f"agent_brief:{b.agent_id}" for b in briefs] + \
            [f"agent_assignment:{a.assignment_id}" for a in assignments]
        ws.update_workspace(
            goal.workspace_id, status="agents_planned", add_ledger_refs=ledger_refs,
            final_outcome=f"planned {len(briefs)} specialist agents", actor=actor,
        )

    def _attach_merge_to_workspace(self, goal, result: AgentMergeResult, *, actor):
        ws = self._workspace_store
        if ws is None or not goal.workspace_id:
            return
        ws.update_workspace(
            goal.workspace_id, status="agents_merged",
            add_ledger_refs=[f"agent_merge:{result.completed_assignments}/{result.agents_run}"],
            final_outcome=sanitize_text(result.next_recommended_action or "") or "", actor=actor,
        )
