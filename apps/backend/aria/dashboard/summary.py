"""
Read-only aggregation of every V3 system (V3.10).

Pure functions that read the existing V3 stores and build deterministic, source-cited
summaries. They never write, execute, approve, or invent facts — an empty/absent store
yields an empty summary. Counts are derived from current persisted state; the
calculation is visible and testable.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.dashboard.models import (
    ActionSummary,
    AgentWorkforceSummary,
    ApprovalQueueItem,
    ApprovalQueueSummary,
    CollaborationSummary,
    GoalProgressSummary,
    LearningSummary,
    RiskItem,
    RiskSummary,
    RoutineSummary,
)

_BLOCKED_TASK = {"blocked", "needs_clarification", "needs_evidence"}
_ACTIVE_GOAL = {"intake", "planned", "in_progress", "awaiting_approval"}
_MAX_ITEMS = 50


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # pragma: no cover - a missing/closed store yields empty summary
        return default


# ── Goals / tasks ─────────────────────────────────────────────────────────────


def goal_progress(goal_store) -> tuple[GoalProgressSummary, list[str]]:
    if goal_store is None:
        return GoalProgressSummary(), []
    goals = _safe(lambda: goal_store.list_goals(), [])
    active = completed = blocked_goals = total_tasks = completed_tasks = blocked_tasks = 0
    steps, refs = [], []
    for g in goals:
        refs.append(g.goal_id)
        sval = g.status.value
        if sval == "completed":
            completed += 1
        elif sval in _ACTIVE_GOAL:
            active += 1
        tasks = _safe(lambda gid=g.goal_id: goal_store.get_tasks(gid), [])
        has_blocked = False
        for t in tasks:
            total_tasks += 1
            tv = t.status.value
            if tv == "completed":
                completed_tasks += 1
            elif tv in _BLOCKED_TASK:
                blocked_tasks += 1
                has_blocked = True
        if has_blocked:
            blocked_goals += 1
        for e in _safe(lambda gid=g.goal_id: goal_store.list_escalations(gid), []):
            if e.suggested_action:
                steps.append(e.suggested_action)
    return GoalProgressSummary(
        active_goals=active, completed_goals=completed, blocked_goals=blocked_goals,
        total_tasks=total_tasks, completed_tasks=completed_tasks, blocked_tasks=blocked_tasks,
        next_recommended_steps=steps[:8],
    ), refs


# ── Agents / supervision ──────────────────────────────────────────────────────


def agent_workforce(goal_store) -> AgentWorkforceSummary:
    if goal_store is None:
        return AgentWorkforceSummary()
    goals = _safe(lambda: goal_store.list_goals(), [])
    planned = created = completed = blocked = quality = esc = 0
    sup_status = "none"
    for g in goals:
        planned += len(_safe(lambda gid=g.goal_id: goal_store.get_agent_briefs(gid), []))
        for a in _safe(lambda gid=g.goal_id: goal_store.get_agent_assignments(gid), []):
            created += 1
            if a.status.value == "completed":
                completed += 1
            if a.status.value == "blocked" or a.failure_reason:
                blocked += 1
            if a.failure_reason == "blocked_for_quality_review":
                quality += 1
        esc += len(_safe(lambda gid=g.goal_id: goal_store.list_escalations(gid), []))
        for run in _safe(lambda gid=g.goal_id: goal_store.list_supervision_runs(gid), []):
            sup_status = run.status.value
    return AgentWorkforceSummary(
        agents_planned=planned, assignments_created=created, assignments_completed=completed,
        assignments_blocked=blocked, quality_failures=quality, escalations=esc,
        supervision_status=sup_status,
    )


# ── Learning (memory + skill) ─────────────────────────────────────────────────


def learning(awareness_store, skill_store) -> LearningSummary:
    nodes = _safe(lambda: awareness_store.list_nodes(), []) if awareness_store else []
    lessons = _safe(lambda: awareness_store.list_lessons(), []) if awareness_store else []
    updates = _safe(lambda: awareness_store.list_updates(), []) if awareness_store else []
    improvements = _safe(lambda: awareness_store.list_improvements(), []) if awareness_store else []
    gaps = _safe(lambda: skill_store.list_gaps(), []) if skill_store else []
    proposals = _safe(lambda: skill_store.list_proposals(), []) if skill_store else []
    disabled = sum(1 for l in lessons
                   if l.status.value in ("disabled", "superseded")
                   or l.approval_status.value in ("disabled", "superseded"))
    return LearningSummary(
        memory_nodes=len(nodes), lessons_created=len(lessons), lessons_disabled=disabled,
        world_updates=len(updates), improvement_proposals=len(improvements), skill_gaps=len(gaps),
        skill_proposals=len(proposals),
        activated_skills=sum(1 for p in proposals if p.status.value == "activated"),
        rejected_skills=sum(1 for p in proposals if p.status.value == "rejected"),
    )


# ── Collaboration ─────────────────────────────────────────────────────────────


def collaboration(collab_store) -> CollaborationSummary:
    drafts = _safe(lambda: collab_store.list_drafts(), []) if collab_store else []
    approvals = _safe(lambda: collab_store.list_approval_requests(), []) if collab_store else []

    def _n(dt: str) -> int:
        return sum(1 for d in drafts if d.draft_type.value == dt)

    return CollaborationSummary(
        manager_updates=_n("manager_update"), stakeholder_questions=_n("stakeholder_question"),
        handoff_notes=_n("handoff_note"), risk_escalation_drafts=_n("risk_escalation"),
        approval_request_drafts=len(approvals),
        drafts_ready_for_review=sum(1 for d in drafts if d.status.value == "ready_for_review"),
    )


# ── Routines ──────────────────────────────────────────────────────────────────


def routines(routine_store) -> RoutineSummary:
    defs = _safe(lambda: routine_store.list_definitions(), []) if routine_store else []
    runs = _safe(lambda: routine_store.list_runs(), []) if routine_store else []
    outputs = _safe(lambda: routine_store.list_outputs(), []) if routine_store else []
    return RoutineSummary(
        routines_defined=len(defs), routines_enabled=sum(1 for d in defs if d.enabled),
        runs_completed=sum(1 for r in runs if r.status.value == "completed"),
        runs_failed=sum(1 for r in runs if r.status.value == "failed"),
        runs_missed=sum(1 for r in runs if r.status.value == "missed"),
        outputs_created=len(outputs),
        followups_drafted=sum(len(o.draft_refs) for o in outputs),
    )


# ── Actions ───────────────────────────────────────────────────────────────────


def actions(action_store) -> ActionSummary:
    intents = _safe(lambda: action_store.list_intents(), []) if action_store else []
    receipts = _safe(lambda: action_store.list_receipts(), []) if action_store else []
    approvals = _safe(lambda: action_store.list_approvals(), []) if action_store else []

    def _rmode(m: str) -> int:
        return sum(1 for r in receipts if r.execution_mode.value == m)

    return ActionSummary(
        action_intents=len(intents),
        previews=sum(1 for i in intents if i.status.value != "draft"),
        approvals_requested=sum(1 for i in intents
                                if i.status.value in ("awaiting_approval", "approved", "rejected")),
        approved_actions=sum(1 for a in approvals if a.decision.value == "approved"),
        rejected_actions=sum(1 for a in approvals if a.decision.value == "rejected"),
        blocked_actions=sum(1 for i in intents if i.status.value == "blocked"),
        dry_run_receipts=_rmode("dry_run"), mock_live_receipts=_rmode("mock_live"),
        live_receipts=_rmode("live"),
    )


# ── Approval queue (read-only) ────────────────────────────────────────────────


def approval_queue(*, skill_store=None, collab_store=None, action_store=None,
                   awareness_store=None) -> ApprovalQueueSummary:
    items: list[ApprovalQueueItem] = []
    for p in (_safe(lambda: skill_store.list_proposals(status="awaiting_approval"), [])
              if skill_store else []):
        items.append(ApprovalQueueItem(
            item_id=p.proposal_id, item_type="skill_proposal", title=p.name, risk_level=p.risk_level,
            source_refs=[p.proposal_id, p.gap_id], created_at=p.created_at, status=p.status.value,
            recommended_decision="review"))
    for a in (_safe(lambda: collab_store.list_approval_requests(), []) if collab_store else []):
        if a.status.value in ("draft", "ready_for_review"):
            items.append(ApprovalQueueItem(
                item_id=a.approval_request_id, item_type="collaboration_approval", title=a.title,
                risk_level=a.risk_level, source_refs=list(a.source_refs),
                evidence_refs=list(a.evidence_refs), created_at=a.created_at, status=a.status.value,
                recommended_decision=a.recommended_option or "review"))
    for i in (_safe(lambda: action_store.list_intents(status="awaiting_approval"), [])
              if action_store else []):
        items.append(ApprovalQueueItem(
            item_id=i.action_id, item_type="action_intent", title=i.title,
            risk_level=i.risk_level.value, source_refs=list(i.source_refs),
            evidence_refs=list(i.evidence_refs), created_at=i.created_at, status=i.status.value,
            recommended_decision="review"))
    for imp in (_safe(lambda: awareness_store.list_improvements(), []) if awareness_store else []):
        if imp.status == "pending":
            items.append(ApprovalQueueItem(
                item_id=imp.proposal_id, item_type="improvement", title=imp.title,
                risk_level=imp.risk_level, source_refs=list(imp.source_refs),
                created_at=imp.created_at, status=imp.status, recommended_decision="review"))
    items = items[:_MAX_ITEMS]
    return ApprovalQueueSummary(items=items, count=len(items))


# ── Risk / blocker view (source-linked, never invented) ───────────────────────


def risks(*, goal_store=None, routine_store=None, action_store=None,
          awareness_store=None, skill_store=None) -> RiskSummary:
    items: list[RiskItem] = []

    def _add(risk_type, title, *, severity, source_refs, evidence_refs=None, action="", owner="aria"):
        items.append(RiskItem(
            risk_id=f"risk-{uuid.uuid4().hex}", risk_type=risk_type, title=title, severity=severity,
            source_refs=[r for r in source_refs if r], evidence_refs=list(evidence_refs or []),
            owner=owner, recommended_action=action, status="open"))

    for g in (_safe(lambda: goal_store.list_goals(), []) if goal_store else []):
        for t in _safe(lambda gid=g.goal_id: goal_store.get_tasks(gid), []):
            if t.status.value in _BLOCKED_TASK:
                _add("blocked_task", f"Task '{t.title}' is {t.status.value}", severity="medium",
                     source_refs=[t.task_id, g.goal_id],
                     action="Provide the missing context/evidence to unblock.")
        for a in _safe(lambda gid=g.goal_id: goal_store.get_agent_assignments(gid), []):
            if a.failure_reason:
                _add("failed_agent", f"Agent {a.agent_id}: {a.failure_reason}", severity="medium",
                     source_refs=[a.assignment_id, g.goal_id], action="Review agent brief / evidence.")
        for e in _safe(lambda gid=g.goal_id: goal_store.list_escalations(gid), []):
            _add("escalation", f"Escalation: {e.reason}", severity=(e.risk_level or "low"),
                 source_refs=[e.escalation_id, g.goal_id], action=e.suggested_action)
        if g.missing_context:
            _add("missing_evidence", f"Goal '{g.title}' has missing context (evidence missing)",
                 severity="low", source_refs=[g.goal_id], action="Gather the listed missing context.")
    for r in (_safe(lambda: routine_store.list_runs(status="failed"), []) if routine_store else []):
        _add("failed_run", f"Routine run failed safely ({r.safe_error or 'class-only error'})",
             severity="medium", source_refs=[r.run_id, r.routine_id], action="Inspect routine inputs.")
    for i in (_safe(lambda: action_store.list_intents(status="blocked"), []) if action_store else []):
        _add("blocked_action", f"Action '{i.title}' blocked by the governed gate",
             severity=i.risk_level.value, source_refs=[i.action_id], evidence_refs=list(i.evidence_refs),
             action="High-risk/unapproved action remains blocked by policy.")
    for u in (_safe(lambda: awareness_store.list_updates(), []) if awareness_store else []):
        if u.risk_level == "high" or u.status.value == "escalated":
            _add("high_risk_world", f"High-risk world update: {u.title}", severity="high",
                 source_refs=[u.update_id], evidence_refs=list(u.citations),
                 action="Escalated for human review (advisory only).")
    for p in (_safe(lambda: skill_store.list_proposals(status="rejected"), []) if skill_store else []):
        _add("unsafe_skill", f"Skill proposal rejected: {p.name}", severity="medium",
             source_refs=[p.proposal_id], action="Rejected proposal cannot activate.")

    items = items[:_MAX_ITEMS]
    high = sum(1 for x in items if x.severity == "high")
    return RiskSummary(items=items, count=len(items), high_severity=high)


# ── ROI input counts ──────────────────────────────────────────────────────────


def roi_counts(*, collab_store=None, routine_store=None, action_store=None,
               awareness_store=None, goal_store=None) -> dict[str, Any]:
    """Gather the deterministic counts + evidence refs the ROI estimator needs."""
    drafts = _safe(lambda: collab_store.list_drafts(), []) if collab_store else []
    runs = _safe(lambda: routine_store.list_runs(status="completed"), []) if routine_store else []
    defs = {d.routine_id: d for d in (_safe(lambda: routine_store.list_definitions(), [])
                                      if routine_store else [])}
    intents = _safe(lambda: action_store.list_intents(), []) if action_store else []
    lessons = _safe(lambda: awareness_store.list_lessons(usable_only=True), []) if awareness_store else []

    def _dn(dt: str) -> int:
        return sum(1 for d in drafts if d.draft_type.value == dt)

    # Routine review minutes are credited by the run's routine_type.
    daily = blocker = world = 0
    for r in runs:
        rtype = getattr(defs.get(r.routine_id), "routine_type", None)
        rv = rtype.value if rtype else ""
        if rv in ("daily_goal_review", "weekly_goal_review"):
            daily += 1
        elif rv in ("blocker_review", "risk_review"):
            blocker += 1
        elif rv == "world_fixture_check":
            world += 1
    previews = sum(1 for i in intents if i.status.value != "draft")
    completed_tasks = 0
    if goal_store is not None:
        for g in _safe(lambda: goal_store.list_goals(), []):
            completed_tasks += sum(1 for t in _safe(lambda gid=g.goal_id: goal_store.get_tasks(gid), [])
                                   if t.status.value == "completed")
    counts = {
        "manager_update": _dn("manager_update"), "stakeholder_question": _dn("stakeholder_question"),
        "handoff_note": _dn("handoff_note"), "daily_goal_review": daily, "blocker_review": blocker,
        "world_fixture_check": world, "action_preview": previews, "reusable_lesson": len(lessons),
    }
    evidence = ([d.draft_id for d in drafts[:5]] + [r.run_id for r in runs[:5]]
                + [i.action_id for i in intents[:5]] + [l.lesson_id for l in lessons[:5]])
    blocked_unsafe = sum(1 for i in intents if i.status.value == "blocked")
    return {
        "counts": counts, "evidence_refs": evidence, "blocked_unsafe_actions": blocked_unsafe,
        "drafts_created": len(drafts), "routines_completed": len(runs),
        "action_previews_created": previews, "tasks_completed": completed_tasks,
    }
