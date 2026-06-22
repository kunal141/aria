"""
Agent Supervisor + Multi-Agent Governance — V3.4.

A governance layer over the V3.3 DRY-RUN workforce. It builds a dependency-ordered,
budget-estimated execution plan, then runs allowed assignments one at a time under
governance: dependency gating, budget/time/risk limits, a deterministic retry
policy, output quality checks, escalation/human-review flags, and run-level
cancellation. It supervises — it does NOT introduce any new execution power.

Hard boundaries (V2/V3.1/V3.2/V3.3 preserved):
  - DRY-RUN / fixture-first only — no real agent process, no network, no external
    write, no live connector, no uncontrolled tool use.
  - approval-required assignments NEVER run.
  - high-risk / budget-exceeded / quality-failed conditions ESCALATE (recorded for
    human review — no external message is sent).
  - cancelled/killed assignments are skipped and never merged as completed.
  - secrets are sanitised out of every persisted/returned string; failures and
    escalations carry class-only / safe reasons (no raw exception text).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from aria.goals.agents import AgentWorkforceService, _FORBIDDEN_WRITE_TOOLS
from aria.goals.models import (
    AgentBrief,
    AgentExecutionPlan,
    AgentStatus,
    AgentSupervisionRun,
    Escalation,
    GovernancePolicy,
    QualityStatus,
    SupervisionStatus,
)
from aria.goals.sanitize import sanitize_text
from aria.goals.store import GoalNotFound, GoalStore
from aria.ledger import LedgerEventType
from aria.ledger.privacy import contains_credential_pattern

_log = logging.getLogger("aria.goals.supervisor")

# Deterministic dependency map (by agent name). Editable by tests to inject cycles.
_DEPENDENCY_MAP: dict[str, list[str]] = {
    "Campaign Analysis Agent": ["Data Freshness Agent"],
    "Recommendation Analyst Agent": ["Event Taxonomy Agent"],
    "Manager Summary Agent": ["Event Taxonomy Agent"],
    "Style Consistency Agent": ["Content Quality Agent"],
}

_RISK_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_NUMERIC_CLAIM_RE = re.compile(r"\d+(\.\d+)?\s*%|\bby\s+\d+")


def _now() -> datetime:
    return datetime.now(UTC)


class AgentSupervisorService:
    def __init__(
        self, store: GoalStore, *, workspace_store: Any = None,
        execution_mode: str | None = None, actor: str = "aria",
        policy: GovernancePolicy | None = None,
    ) -> None:
        self._store = store
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor
        self._policy = policy or GovernancePolicy()
        self._agents = AgentWorkforceService(
            store, workspace_store=workspace_store, execution_mode=execution_mode, actor=actor,
        )

    # ── 2/3/4. Plan: dependency order + budget estimate ──────────────────────

    def plan(self, goal_id: str, *, actor: str | None = None) -> AgentExecutionPlan:
        actor = actor or self._actor
        goal = self._store.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        deps, assignments = self._dependencies(goal_id)
        active = [a for a in assignments if a.status not in (AgentStatus.cancelled, AgentStatus.killed)]
        active_ids = [a.assignment_id for a in active]
        order, cyclic = self._topo_order(active_ids, deps)
        approval_ids = [a.assignment_id for a in active if a.approval_required]
        blocked = sorted(set(cyclic) | set(approval_ids))
        est_cost = sum(max(a.max_cost_units, 1) for a in active)
        est_runtime = sum(max(a.max_runtime_seconds, 1) for a in active)
        risk_summary = self._max_risk(active)
        now = _now()
        plan = AgentExecutionPlan(
            plan_id=f"plan-{uuid.uuid4().hex}", goal_id=goal_id, workspace_id=goal.workspace_id,
            assignment_ids=active_ids, execution_order=order, blocked_assignments=blocked,
            approval_required_assignments=approval_ids, estimated_cost_units=est_cost,
            estimated_runtime_seconds=est_runtime, risk_summary=risk_summary,
            created_at=now, updated_at=now,
        )
        budget_status = "ok" if self._within_budget(plan)[0] else "exceeded"
        self._store.save_execution_plan(plan, actor=actor, budget_status=budget_status)
        if budget_status == "exceeded":
            self._store.emit_supervision_event(
                LedgerEventType.agent_budget_blocked, goal_id=goal_id, plan_id=plan.plan_id,
                workspace_id=plan.workspace_id, correlation_id=goal_id, budget_status="exceeded",
                outcome="budget_exceeded_at_plan", actor=actor,
            )
        if cyclic:
            for aid in cyclic:
                self._store.emit_supervision_event(
                    LedgerEventType.agent_dependency_blocked, goal_id=goal_id, plan_id=plan.plan_id,
                    assignment_id=aid, correlation_id=goal_id, outcome="circular_dependency",
                    actor=actor,
                )
        self._attach_plan_to_workspace(plan, actor=actor)
        return plan

    # ── 1. Supervised run ─────────────────────────────────────────────────────

    def run(self, goal_id: str, *, actor: str | None = None) -> AgentSupervisionRun:
        actor = actor or self._actor
        goal = self._store.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        plan = self._store.get_latest_execution_plan(goal_id) or self.plan(goal_id, actor=actor)
        run = AgentSupervisionRun(
            run_id=f"run-{uuid.uuid4().hex}", plan_id=plan.plan_id, goal_id=goal_id,
            workspace_id=plan.workspace_id, status=SupervisionStatus.running, started_at=_now(),
            total_assignments=len(plan.assignment_ids),
        )
        run = self._store.create_supervision_run(run, actor=actor)

        within, reason = self._within_budget(plan)
        if not within:
            return self._block_run_for_budget(goal, plan, run, reason, actor=actor)

        deps, _ = self._dependencies(goal_id)
        briefs = {b.agent_id: b for b in self._store.get_agent_briefs(goal_id)}
        provided = set(self._store.list_evidence(goal_id))
        completed = blocked = failed = cancelled = 0
        quality_ok = True
        escalated = False

        for aid in plan.execution_order:
            a = self._store.get_agent_assignment(aid)
            if a is None or a.status in (AgentStatus.cancelled, AgentStatus.killed):
                cancelled += 1
                continue
            if a.status is AgentStatus.completed:
                completed += 1
                continue
            # Dependency gate. Persist a clear, RECOVERABLE blocked state on the
            # dependent assignment (it can re-run once the prerequisite completes).
            if self._unmet_dependencies(aid, deps):
                blocked += 1
                self._store.update_agent_assignment(
                    aid, status=AgentStatus.blocked, failure_reason="blocked_for_dependency",
                    actor=actor,
                )
                self._store.emit_supervision_event(
                    LedgerEventType.agent_dependency_blocked, goal_id=goal_id, plan_id=plan.plan_id,
                    run_id=run.run_id, assignment_id=aid, correlation_id=goal_id,
                    outcome="dependency_blocked", actor=actor,
                )
                continue
            # Risk gate.
            if not self._risk_allowed(a.risk_level):
                blocked += 1
                escalated = True
                self._escalate(goal, run, aid, a.risk_level,
                               "assignment risk exceeds the allowed policy",
                               "Obtain human approval / lower the risk before running", actor=actor)
                continue
            # Approval gate — never runs; recorded as blocked_for_approval.
            if a.approval_required:
                blocked += 1
                self._store.update_agent_assignment(
                    aid, status=AgentStatus.blocked, failure_reason="blocked_for_approval", actor=actor,
                )
                continue
            # Mark running, then STAGE the dry-run IN MEMORY (no output persisted yet),
            # with retry on safe failures.
            started = _now()
            self._store.update_agent_assignment(
                aid, status=AgentStatus.running, started_at=started, actor=actor)
            st, summary, content, failure = self._stage_with_retry(goal_id, aid)

            if st is AgentStatus.completed:
                # Quality-review the STAGED (in-memory) output BEFORE persisting it, so
                # a rejected output never reaches SQLite or disk.
                transient = a.model_copy(update={"output_summary": summary,
                                                 "status": AgentStatus.completed})
                qstatus, reasons = self.check_quality(transient, briefs.get(a.agent_id), provided)
                if qstatus is QualityStatus.passed:
                    self._agents.commit_assignment(
                        goal_id, aid, AgentStatus.completed, summary, content, None,
                        started_at=started, actor=actor)
                    completed += 1
                else:
                    quality_ok = False
                    escalated = True
                    blocked += 1
                    # Rejected content is DISCARDED (never persisted). Record a blocked
                    # state with a withheld note + a workspace timeline marker.
                    self._store.update_agent_assignment(
                        aid, status=AgentStatus.blocked, failure_reason="blocked_for_quality_review",
                        clear_output=True, started_at=started, actor=actor)
                    if self._workspace_store and goal.workspace_id:
                        self._workspace_store.update_workspace(
                            goal.workspace_id, status="quality_rejected",
                            add_ledger_refs=[f"quality_rejected:{aid}"], actor=actor)
                    self._store.emit_supervision_event(
                        LedgerEventType.agent_quality_check_failed, goal_id=goal_id,
                        plan_id=plan.plan_id, run_id=run.run_id, assignment_id=aid,
                        correlation_id=goal_id, quality_status="failed",
                        outcome="; ".join(reasons)[:120], actor=actor)
                    self._escalate(goal, run, aid, a.risk_level,
                                   "agent output failed quality checks: " + "; ".join(reasons),
                                   "Review the agent output before any use", actor=actor)
            elif st is AgentStatus.failed:
                failed += 1
                escalated = True
                self._agents.commit_assignment(
                    goal_id, aid, AgentStatus.failed, "", None, failure,
                    started_at=started, actor=actor)
                self._escalate(goal, run, aid, a.risk_level,
                               "agent failed safely after retries",
                               "Review and re-run the failed agent", actor=actor)
            else:  # blocked (evidence / approval surfaced by the executor)
                blocked += 1
                self._agents.commit_assignment(
                    goal_id, aid, AgentStatus.blocked, summary, None, failure,
                    started_at=started, actor=actor)

        status = (SupervisionStatus.completed
                  if blocked == 0 and failed == 0 and cancelled == 0
                  else SupervisionStatus.completed_with_blockers)
        run = run.model_copy(update={
            "status": status, "completed_at": _now(), "completed_assignments": completed,
            "blocked_assignments": blocked, "failed_assignments": failed,
            "cancelled_assignments": cancelled, "quality_passed": quality_ok,
            "escalation_required": escalated,
            "summary": sanitize_text(
                f"{completed} completed, {blocked} blocked, {failed} failed, {cancelled} cancelled"
            ) or "",
        })
        run = self._store.complete_supervision_run(run, actor=actor)
        self._attach_run_to_workspace(run, actor=actor)
        return run

    # ── 8. Cancellation / kill switch ─────────────────────────────────────────

    def cancel_run(self, run_id: str, *, reason: str = "cancelled by supervisor",
                   actor: str | None = None) -> AgentSupervisionRun:
        actor = actor or self._actor
        run = self._store.get_supervision_run(run_id)
        if run is None:
            raise GoalNotFound(f"supervision run {run_id!r} not found")
        # Cancel remaining non-terminal assignments for the goal.
        cancelled = 0
        for a in self._store.get_agent_assignments(run.goal_id):
            if a.status in (AgentStatus.planned, AgentStatus.ready, AgentStatus.running):
                self._agents.cancel_assignment(a.assignment_id, reason=reason, actor=actor)
                cancelled += 1
        run = run.model_copy(update={
            "status": SupervisionStatus.cancelled, "completed_at": _now(),
            "cancelled_assignments": run.cancelled_assignments + cancelled,
            "summary": sanitize_text(f"run cancelled: {reason}") or "",
        })
        run = self._store.complete_supervision_run(run, actor=actor)
        self._attach_run_to_workspace(run, actor=actor, note=f"cancelled: {reason}")
        return run

    # ── 6. Quality checks ─────────────────────────────────────────────────────

    def check_quality(
        self, assignment, brief: AgentBrief | None, provided: set[str],
    ) -> tuple[QualityStatus, list[str]]:
        """Inspect a (completed) agent output. Returns (status, reasons). Never
        silently accepts a bad result."""
        reasons: list[str] = []
        out = assignment.output_summary or ""
        if assignment.status is AgentStatus.completed:
            if not out.strip():
                reasons.append("completed agent has no findings summary")
            if brief is not None:
                missing_ev = [e for e in brief.required_inputs if e not in provided]
                if missing_ev:
                    reasons.append("required evidence refs missing")
                uses_memory = any(c.startswith("memory:") for c in brief.allowed_context)
                if uses_memory and "memory" not in out.lower():
                    reasons.append("memory citation missing where memory was used")
                # An asserted numeric/metric claim with NO evidence inputs is unsupported.
                if _NUMERIC_CLAIM_RE.search(out) and not brief.required_inputs:
                    reasons.append("unsupported factual claim (numeric claim without evidence)")
            if any(tool in out.lower() for tool in _FORBIDDEN_WRITE_TOOLS):
                reasons.append("output references a forbidden write action (live write requested)")
            if contains_credential_pattern(out):
                reasons.append("sensitive data / secret detected in output")
        else:  # non-completed must carry a reason
            if not (assignment.failure_reason or "").strip():
                reasons.append("blocked agent has no blocked reason")
        if reasons:
            return QualityStatus.escalation_required, reasons
        return QualityStatus.passed, []

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_supervision(self, goal_id: str) -> dict[str, Any]:
        plan = self._store.get_latest_execution_plan(goal_id)
        runs = self._store.list_supervision_runs(goal_id)
        escalations = self._store.list_escalations(goal_id)
        return {
            "goal_id": goal_id,
            "plan": plan.model_dump(mode="json") if plan else None,
            "runs": [r.model_dump(mode="json") for r in runs],
            "escalations": [e.model_dump(mode="json") for e in escalations],
        }

    # ── 5. Retry (staged — nothing is persisted between attempts) ────────────

    def _stage_with_retry(self, goal_id: str, aid: str):
        """Stage the dry-run in memory, retrying only safe deterministic failures up
        to the policy limit. Evidence/approval blocks are NOT retried (they are not
        ``failed``). Nothing is persisted here — the caller decides + commits."""
        result = self._agents.stage_assignment(goal_id, aid)
        attempts = 1
        while result[0] is AgentStatus.failed and attempts <= self._policy.max_retries:
            result = self._agents.stage_assignment(goal_id, aid)
            attempts += 1
        return result

    # ── Governance helpers ────────────────────────────────────────────────────

    def _within_budget(self, plan: AgentExecutionPlan) -> tuple[bool, str]:
        p = self._policy
        if plan.estimated_cost_units > p.max_total_cost_units:
            return False, "estimated cost exceeds the budget policy"
        if plan.estimated_runtime_seconds > p.max_total_runtime_seconds:
            return False, "estimated runtime exceeds the time policy"
        if len(plan.assignment_ids) > p.max_assignments_per_run:
            return False, "assignment count exceeds the per-run policy"
        return True, ""

    def _risk_allowed(self, risk_level: str) -> bool:
        if risk_level not in self._policy.allowed_risk_levels:
            return False
        if self._policy.require_approval_for_high_risk and _RISK_RANK.get(risk_level, 1) >= 3:
            return False
        return True

    @staticmethod
    def _max_risk(assignments) -> str:
        best = "low"
        for a in assignments:
            if _RISK_RANK.get(a.risk_level, 1) > _RISK_RANK.get(best, 1):
                best = a.risk_level
        return best

    def _block_run_for_budget(self, goal, plan, run, reason, *, actor) -> AgentSupervisionRun:
        self._store.emit_supervision_event(
            LedgerEventType.agent_budget_blocked, goal_id=goal.goal_id, plan_id=plan.plan_id,
            run_id=run.run_id, correlation_id=goal.goal_id, budget_status="exceeded",
            outcome="budget_exceeded", actor=actor,
        )
        self._escalate(goal, run, None, plan.risk_summary,
                       f"supervision blocked: {reason}",
                       "Reduce agent scope or raise the budget/time policy", actor=actor)
        run = run.model_copy(update={
            "status": SupervisionStatus.failed_safely, "completed_at": _now(),
            "blocked_assignments": run.total_assignments, "escalation_required": True,
            "quality_passed": True,
            "summary": sanitize_text(f"blocked before run: {reason}") or "",
        })
        run = self._store.complete_supervision_run(run, actor=actor, blocked=True)
        self._attach_run_to_workspace(run, actor=actor, note=reason)
        return run

    def _escalate(self, goal, run, assignment_id, risk_level, reason, suggested, *, actor):
        esc = Escalation(
            escalation_id=f"esc-{uuid.uuid4().hex}", goal_id=goal.goal_id,
            run_id=run.run_id, assignment_id=assignment_id, reason=reason,
            suggested_action=suggested, risk_level=risk_level, workspace_id=goal.workspace_id,
            created_at=_now(),
        )
        return self._store.create_escalation(esc, actor=actor)

    # ── Dependency helpers ────────────────────────────────────────────────────

    def _dependencies(self, goal_id: str):
        briefs = self._store.get_agent_briefs(goal_id)
        assignments = self._store.get_agent_assignments(goal_id)
        brief_by_agent = {b.agent_id: b for b in briefs}
        name_to_aid: dict[str, str] = {}
        aid_to_name: dict[str, str] = {}
        for a in assignments:
            b = brief_by_agent.get(a.agent_id)
            if b:
                name_to_aid.setdefault(b.name, a.assignment_id)
                aid_to_name[a.assignment_id] = b.name
        deps: dict[str, list[str]] = {}
        for a in assignments:
            name = aid_to_name.get(a.assignment_id)
            prereqs = _DEPENDENCY_MAP.get(name or "", [])
            deps[a.assignment_id] = [name_to_aid[p] for p in prereqs if p in name_to_aid]
        return deps, assignments

    def _unmet_dependencies(self, aid: str, deps: dict[str, list[str]]) -> bool:
        for prereq in deps.get(aid, []):
            dep_a = self._store.get_agent_assignment(prereq)
            if dep_a is None or dep_a.status is not AgentStatus.completed:
                return True
        return False

    @staticmethod
    def _topo_order(active_ids: list[str], deps: dict[str, list[str]]):
        """Kahn's algorithm. Returns (order, cyclic_ids). Cyclic nodes are reported
        (fail safe) — never executed."""
        active = set(active_ids)
        indeg = {a: 0 for a in active_ids}
        adj: dict[str, list[str]] = {a: [] for a in active_ids}
        for a in active_ids:
            for p in deps.get(a, []):
                if p in active:
                    adj[p].append(a)
                    indeg[a] += 1
        ready = [a for a in active_ids if indeg[a] == 0]
        order: list[str] = []
        while ready:
            ready.sort(key=active_ids.index)
            n = ready.pop(0)
            order.append(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        cyclic = [a for a in active_ids if a not in order]
        return order, cyclic

    # ── Workspace integration ─────────────────────────────────────────────────

    def _attach_plan_to_workspace(self, plan: AgentExecutionPlan, *, actor):
        ws = self._workspace_store
        if ws is None or not plan.workspace_id:
            return
        ws.update_workspace(
            plan.workspace_id, status="supervision_planned",
            add_ledger_refs=[f"exec_plan:{plan.plan_id}",
                             f"exec_order:{len(plan.execution_order)}",
                             f"budget:{plan.estimated_cost_units}/{self._policy.max_total_cost_units}"],
            final_outcome=f"supervision plan: order={len(plan.execution_order)}, risk={plan.risk_summary}",
            actor=actor,
        )

    def _attach_run_to_workspace(self, run: AgentSupervisionRun, *, actor, note: str | None = None):
        ws = self._workspace_store
        if ws is None or not run.workspace_id:
            return
        refs = [f"supervision_run:{run.run_id}:{run.status.value}"]
        if run.escalation_required:
            refs.append(f"escalation:{run.run_id}")
        if note:
            refs.append(f"cancellation:{run.run_id}")
        ws.update_workspace(
            run.workspace_id, status=f"supervision:{run.status.value}", add_ledger_refs=refs,
            final_outcome=sanitize_text(note or run.summary) or "", actor=actor,
        )
