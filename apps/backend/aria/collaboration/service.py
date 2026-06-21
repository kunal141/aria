"""
Collaboration Service (V3.7) — governed, DRAFT-ONLY team communication.

ARIA communicates work like a reliable team member: it assembles a read-only
collaboration context from persisted goal/task/agent/memory state, then renders
manager/team updates, stakeholder questions, handoff notes, blocker notes,
summaries, decision memos, risk escalations, and approval requests — as **draft
artifacts only**.

Hard boundaries (V2/V3 preserved):
  - ARIA can draft, summarize, ask, escalate, and hand off; it CANNOT send, post,
    comment, email, or mutate any external system.
  - "approved" marks a draft approved *as an artifact* — it triggers no send.
  - every draft cites its sources (no orphan/invented communication); missing
    evidence is surfaced as explicit uncertainty, never filled with a guess.
  - secrets are masked / structural-secret refs rejected at the store boundary;
    ``ARIA_USER_ID`` is attribution only, never authorization.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.collaboration import templates
from aria.collaboration.models import (
    DRAFT_ONLY_BOUNDARY,
    ApprovalRequestDraft,
    ApprovalRequestStatus,
    Channel,
    CollaborationContext,
    CollaborationDraft,
    DraftStatus,
    DraftType,
)
from aria.collaboration.store import (
    CollaborationIntegrityError,
    CollaborationNotFound,
    CollaborationStore,
)

_MAX_REFS = 20
_MAX_ITEMS = 8


def _now() -> datetime:
    return datetime.now(UTC)


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


class CollaborationService:
    def __init__(
        self, store: CollaborationStore, *, goal_store: Any = None, awareness_store: Any = None,
        workspace_store: Any = None, execution_mode: str | None = None, actor: str = "aria",
    ) -> None:
        self._store = store
        self._goals = goal_store
        self._awareness = awareness_store
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor

    # ── Context assembly (read-only) ──────────────────────────────────────────

    def build_context(self, goal_id: str, *, task_id: str | None = None,
                      actor: str | None = None) -> CollaborationContext:
        actor = actor or self._actor
        goal = self._goals.get_goal(goal_id) if self._goals else None
        if goal is None:
            raise CollaborationNotFound(f"goal {goal_id!r} not found")
        tasks = self._goals.get_tasks(goal_id)
        assignments = self._goals.get_agent_assignments(goal_id)
        steps = self._goals.get_execution_steps(goal_id)
        escalations = self._goals.list_escalations(goal_id)
        roadmap = self._goals.get_roadmap(goal_id)

        blockers, progress, decisions, agent_outputs, evidence = [], [], [], [], []
        for t in tasks:
            if t.status.value in ("blocked", "needs_clarification", "needs_evidence"):
                blockers.append(f"Task '{t.title}' is {t.status.value}")
                evidence.append(t.task_id)
            elif t.status.value == "completed":
                progress.append(f"Completed task: {t.title}")
                evidence.append(t.task_id)
            elif t.status.value == "awaiting_approval":
                decisions.append(f"Approval needed for task: {t.title}")
                evidence.append(t.task_id)
        for a in assignments:
            if a.failure_reason:
                blockers.append(f"Agent {a.agent_id} blocked: {a.failure_reason}")
                evidence.append(a.assignment_id)
            elif a.status.value == "completed":
                if a.output_summary:
                    agent_outputs.append(a.output_summary)
                progress.append(f"Agent {a.agent_id} completed its brief")
                evidence.append(a.assignment_id)
        for s in steps:
            if s.outcome.value.startswith("blocked"):
                blockers.append(f"Step blocked: {s.selected_action}")
                evidence.append(s.step_id)
        for e in escalations:
            decisions.append(e.suggested_action)
            evidence.append(e.escalation_id)

        open_questions = _dedupe(list(goal.clarifying_questions) + list(goal.missing_context))
        risks = _dedupe(
            (list(roadmap.risks) if roadmap else [])
            + ([f"Escalation: {e.reason}" for e in escalations])
            + ([f"Goal risk level: {goal.risk_level}"] if goal.risk_level != "low" else [])
        )

        lessons, memory_refs = [], []
        if self._awareness is not None:
            try:
                usable = self._awareness.list_lessons(usable_only=True)
            except Exception:  # pragma: no cover - defensive
                usable = []
            for l in usable[:5]:
                lessons.append(l.title)
                memory_refs.append(l.lesson_id)

        ctx = CollaborationContext(
            context_id=f"cctx-{uuid.uuid4().hex}", goal_id=goal_id, task_id=task_id,
            workspace_id=goal.workspace_id, active_blockers=_dedupe(blockers)[:_MAX_ITEMS],
            recent_progress=_dedupe(progress)[:_MAX_ITEMS], open_questions=open_questions[:_MAX_ITEMS],
            risks=risks[:_MAX_ITEMS], decisions_needed=_dedupe(decisions)[:_MAX_ITEMS],
            relevant_lessons=lessons[:5], agent_outputs=_dedupe(agent_outputs)[:5],
            evidence_refs=_dedupe(evidence)[:_MAX_REFS], memory_refs=_dedupe(memory_refs)[:5],
            created_at=_now(),
        )
        created = self._store.create_context(ctx, actor=actor)
        self._attach_ws(goal.workspace_id, [f"collaboration_context:{created.context_id}"],
                        "collaboration_context_created", actor=actor)
        return created

    # ── Draft generation (draft-only, source-cited) ───────────────────────────

    def generate_draft(self, goal_id: str, draft_type: DraftType, *, task_id: str | None = None,
                       audience: str = "manager", channel: Channel = Channel.internal_note,
                       context_id: str | None = None, actor: str | None = None) -> CollaborationDraft:
        actor = actor or self._actor
        goal = self._goals.get_goal(goal_id) if self._goals else None
        if goal is None:
            raise CollaborationNotFound(f"goal {goal_id!r} not found")
        ctx = self._store.get_context(context_id) if context_id else None
        if ctx is None:
            ctx = self.build_context(goal_id, task_id=task_id, actor=actor)

        body = templates.render_body(draft_type, ctx, goal_title=goal.title)
        title = templates.default_title(draft_type, goal.title)
        # Source-cited: at minimum the goal, plus the task and the context's evidence.
        source_refs = _dedupe([goal_id] + ([task_id] if task_id else []) + list(ctx.evidence_refs))
        now = _now()
        draft = CollaborationDraft(
            draft_id=f"draft-{uuid.uuid4().hex}", draft_type=draft_type, title=title, body=body,
            audience=audience, channel=channel, goal_id=goal_id, task_id=task_id,
            workspace_id=goal.workspace_id, source_refs=source_refs[:_MAX_REFS],
            evidence_refs=list(ctx.evidence_refs), memory_refs=list(ctx.memory_refs),
            approval_required=True, status=DraftStatus.draft, created_by=actor,
            created_at=now, updated_at=now,
        )
        created = self._store.create_draft(draft, actor=actor)
        self._attach_ws(goal.workspace_id, [f"collaboration_draft:{created.draft_id}"],
                        "collaboration_drafted", actor=actor)
        return created

    def mark_ready(self, draft_id: str, *, actor: str | None = None) -> CollaborationDraft:
        actor = actor or self._actor
        return self._set_status(draft_id, DraftStatus.ready_for_review, actor=actor)

    def approve_draft(self, draft_id: str, *, actor: str | None = None) -> CollaborationDraft:
        """Mark a draft approved AS AN ARTIFACT. This NEVER sends/posts/emails it —
        V3.7 has no external send path."""
        actor = actor or self._actor
        return self._set_status(draft_id, DraftStatus.approved, actor=actor)

    def reject_draft(self, draft_id: str, *, actor: str | None = None) -> CollaborationDraft:
        actor = actor or self._actor
        return self._set_status(draft_id, DraftStatus.rejected, actor=actor)

    def archive_draft(self, draft_id: str, *, actor: str | None = None) -> CollaborationDraft:
        actor = actor or self._actor
        return self._set_status(draft_id, DraftStatus.archived, actor=actor)

    def _set_status(self, draft_id: str, status: DraftStatus, *, actor: str) -> CollaborationDraft:
        d = self._store.update_draft_status(draft_id, status=status, actor=actor)
        self._attach_ws(d.workspace_id, [f"collaboration_draft:{d.draft_id}:{status.value}"],
                        f"collaboration_{status.value}", actor=actor)
        return d

    # ── Approval-request drafts (record a request — execute nothing) ──────────

    def draft_approval_request(self, goal_id: str, *, title: str | None = None,
                              reason: str | None = None, requested_decision: str | None = None,
                              options: list[str] | None = None, recommended_option: str | None = None,
                              risk_level: str | None = None, draft_id: str | None = None,
                              actor: str | None = None) -> ApprovalRequestDraft:
        actor = actor or self._actor
        goal = self._goals.get_goal(goal_id) if self._goals else None
        if goal is None:
            raise CollaborationNotFound(f"goal {goal_id!r} not found")
        ctx = self.build_context(goal_id, actor=actor)
        # Governance: never recommend approval without an evidence basis. If there is
        # no evidence yet, refuse (a stakeholder question should gather it first).
        if not ctx.evidence_refs:
            raise CollaborationIntegrityError(
                "cannot draft an approval request without an evidence basis; gather "
                "evidence or raise a stakeholder question first")
        derived_reason = reason or (ctx.decisions_needed[:1] or ctx.active_blockers[:1]
                                    or ["proceed with the recommended next step"])[0]
        req = ApprovalRequestDraft(
            approval_request_id=f"areq-{uuid.uuid4().hex}",
            title=title or f"Approval request: {goal.title}",
            reason=derived_reason,
            requested_decision=requested_decision or "Approve the recommended next step",
            options=options or ["approve", "reject", "request changes"],
            recommended_option=recommended_option or "approve",
            risk_level=risk_level or goal.risk_level,
            evidence_refs=list(ctx.evidence_refs),
            source_refs=_dedupe([goal_id] + list(ctx.evidence_refs))[:_MAX_REFS],
            draft_id=draft_id, status=ApprovalRequestStatus.draft, created_at=_now(),
        )
        created = self._store.create_approval_request(
            req, actor=actor, goal_id=goal_id, workspace_id=goal.workspace_id)
        self._attach_ws(goal.workspace_id, [f"approval_request:{created.approval_request_id}"],
                        "approval_request_drafted", actor=actor)
        return created

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_context(self, context_id: str) -> CollaborationContext | None:
        return self._store.get_context(context_id)

    def get_draft(self, draft_id: str) -> CollaborationDraft | None:
        return self._store.get_draft(draft_id)

    def list_drafts(self, *, goal_id: str | None = None, status: str | None = None,
                    draft_type: str | None = None) -> list[CollaborationDraft]:
        return self._store.list_drafts(goal_id=goal_id, status=status, draft_type=draft_type)

    def get_approval_request(self, approval_request_id: str) -> ApprovalRequestDraft | None:
        return self._store.get_approval_request(approval_request_id)

    def list_approval_requests(self) -> list[ApprovalRequestDraft]:
        return self._store.list_approval_requests()

    @staticmethod
    def boundary_note() -> str:
        return DRAFT_ONLY_BOUNDARY

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _attach_ws(self, ws_id: str | None, refs: list[str], status: str, *, actor: str) -> None:
        if self._workspace_store is None or not ws_id or not refs:
            return
        try:
            self._workspace_store.update_workspace(
                ws_id, status=status, add_ledger_refs=list(refs), actor=actor)
        except Exception:  # pragma: no cover - workspace bookkeeping is best-effort
            pass
