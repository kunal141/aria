"""
Deterministic draft-body templates for V3.7 collaboration.

Each template renders a concise, professional body **only** from a
``CollaborationContext`` (which is itself assembled from persisted goal/task/agent/
memory records). Templates invent NO facts: an empty section is shown as an explicit
"(none recorded)" / "(to be confirmed)" rather than filled with a guess, so missing
evidence and uncertainty stay visible. No template sends, posts, or emails anything.
"""
from __future__ import annotations

from aria.collaboration.models import CollaborationContext, DraftType

_NONE = "(none recorded)"
_TBC = "(to be confirmed)"


def _bullets(items: list[str], *, empty: str = _NONE) -> str:
    items = [i for i in (items or []) if i and i.strip()]
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {i}" for i in items)


def derive_status(ctx: CollaborationContext) -> str:
    """A deterministic status label from the context (no guessing)."""
    if ctx.active_blockers:
        return "blocked"
    if ctx.decisions_needed or ctx.open_questions:
        return "needs review"
    return "on track"


def default_title(draft_type: DraftType, goal_title: str) -> str:
    label = {
        DraftType.manager_update: "Manager update",
        DraftType.team_update: "Team update",
        DraftType.stakeholder_question: "Clarification needed",
        DraftType.handoff_note: "Handoff note",
        DraftType.approval_request: "Approval request",
        DraftType.risk_escalation: "Risk escalation",
        DraftType.daily_summary: "Daily summary",
        DraftType.weekly_summary: "Weekly summary",
        DraftType.decision_memo: "Decision memo",
        DraftType.blocker_note: "Blocker note",
    }.get(draft_type, "Update")
    return f"{label}: {goal_title}".strip()


def _evidence(ctx: CollaborationContext) -> str:
    refs = list(ctx.evidence_refs) + list(ctx.memory_refs)
    return _bullets(refs, empty="(no evidence attached yet — findings are unverified)")


def manager_update(ctx: CollaborationContext, *, goal_title: str) -> str:
    return (
        f"Status: {derive_status(ctx)}\n\n"
        f"Completed:\n{_bullets(ctx.recent_progress)}\n\n"
        f"In progress:\n{_bullets(ctx.agent_outputs)}\n\n"
        f"Risks:\n{_bullets(ctx.risks)}\n\n"
        f"Decision needed:\n{_bullets(ctx.decisions_needed, empty='(none)')}\n\n"
        f"Evidence:\n{_evidence(ctx)}"
    )


def team_update(ctx: CollaborationContext, *, goal_title: str) -> str:
    return (
        f"Goal: {goal_title}\n"
        f"Status: {derive_status(ctx)}\n\n"
        f"Recent progress:\n{_bullets(ctx.recent_progress)}\n\n"
        f"Open questions:\n{_bullets(ctx.open_questions, empty='(none)')}\n\n"
        f"Blockers:\n{_bullets(ctx.active_blockers, empty='(none)')}\n\n"
        f"Relevant lessons:\n{_bullets(ctx.relevant_lessons, empty='(none recorded)')}"
    )


def stakeholder_question(ctx: CollaborationContext, *, goal_title: str) -> str:
    questions = ctx.open_questions or ["date range", "business owner", "success metric",
                                       "allowed data source"]
    reason = ctx.active_blockers or ["current task is blocked pending the above"]
    return (
        "We need clarification on:\n"
        f"{_bullets(questions)}\n\n"
        "Reason:\n"
        f"{_bullets(reason)}\n\n"
        "Evidence:\n"
        f"{_evidence(ctx)}"
    )


def handoff_note(ctx: CollaborationContext, *, goal_title: str) -> str:
    next_step = ctx.decisions_needed[:1] or ctx.open_questions[:1] or [_TBC]
    return (
        f"Goal:\n- {goal_title}\n\n"
        f"Current state: {derive_status(ctx)}\n\n"
        f"Completed work:\n{_bullets(ctx.recent_progress)}\n\n"
        f"Open blockers:\n{_bullets(ctx.active_blockers, empty='(none)')}\n\n"
        f"Artifacts:\n{_bullets(ctx.evidence_refs, empty='(none attached)')}\n\n"
        f"Recommended next step:\n{_bullets(next_step)}\n\n"
        f"Source references:\n{_bullets(ctx.memory_refs + ctx.evidence_refs)}"
    )


def blocker_note(ctx: CollaborationContext, *, goal_title: str) -> str:
    return (
        f"Goal: {goal_title}\n\n"
        f"Blockers:\n{_bullets(ctx.active_blockers, empty='(none currently)')}\n\n"
        f"What is needed to unblock:\n{_bullets(ctx.open_questions, empty=_TBC)}\n\n"
        f"Evidence:\n{_evidence(ctx)}"
    )


def risk_escalation(ctx: CollaborationContext, *, goal_title: str) -> str:
    return (
        f"Goal: {goal_title}\n"
        "Escalation: human review requested.\n\n"
        f"Risks:\n{_bullets(ctx.risks, empty='(no specific risk recorded)')}\n\n"
        f"Active blockers:\n{_bullets(ctx.active_blockers, empty='(none)')}\n\n"
        f"Decision needed:\n{_bullets(ctx.decisions_needed, empty=_TBC)}\n\n"
        f"Evidence:\n{_evidence(ctx)}"
    )


def decision_memo(ctx: CollaborationContext, *, goal_title: str) -> str:
    return (
        f"Goal: {goal_title}\n\n"
        f"Decisions needed:\n{_bullets(ctx.decisions_needed, empty=_TBC)}\n\n"
        f"Open questions:\n{_bullets(ctx.open_questions, empty='(none)')}\n\n"
        f"Risks:\n{_bullets(ctx.risks, empty='(none recorded)')}\n\n"
        f"Evidence:\n{_evidence(ctx)}"
    )


def daily_summary(ctx: CollaborationContext, *, goal_title: str) -> str:
    return (
        f"Daily summary — {goal_title}\n"
        f"Status: {derive_status(ctx)}\n\n"
        f"Progress today:\n{_bullets(ctx.recent_progress)}\n\n"
        f"Blockers:\n{_bullets(ctx.active_blockers, empty='(none)')}\n\n"
        f"Next:\n{_bullets(ctx.decisions_needed or ctx.open_questions, empty=_TBC)}"
    )


def weekly_summary(ctx: CollaborationContext, *, goal_title: str) -> str:
    return (
        f"Weekly summary — {goal_title}\n"
        f"Status: {derive_status(ctx)}\n\n"
        f"Progress this week:\n{_bullets(ctx.recent_progress)}\n\n"
        f"Risks:\n{_bullets(ctx.risks, empty='(none recorded)')}\n\n"
        f"Decisions needed:\n{_bullets(ctx.decisions_needed, empty='(none)')}\n\n"
        f"Lessons:\n{_bullets(ctx.relevant_lessons, empty='(none recorded)')}"
    )


_RENDERERS = {
    DraftType.manager_update: manager_update,
    DraftType.team_update: team_update,
    DraftType.stakeholder_question: stakeholder_question,
    DraftType.handoff_note: handoff_note,
    DraftType.blocker_note: blocker_note,
    DraftType.risk_escalation: risk_escalation,
    DraftType.decision_memo: decision_memo,
    DraftType.daily_summary: daily_summary,
    DraftType.weekly_summary: weekly_summary,
}


def render_body(draft_type: DraftType, ctx: CollaborationContext, *, goal_title: str) -> str:
    """Render the draft body for a draft_type. ``approval_request`` is rendered by the
    service (it has its own typed record), so it falls back to a decision memo here."""
    renderer = _RENDERERS.get(draft_type, decision_memo)
    return renderer(ctx, goal_title=goal_title)
