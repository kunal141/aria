"""
Routine Execution Service (V3.8) — local, deterministic, governed.

ARIA remembers to do recurring INTERNAL work at the right cadence: daily/weekly goal
reviews, blocker/risk reviews, memory and collaboration reviews, and fixture-only
world checks. Execution is manual-trigger or deterministic due-run against an injected
``now`` — no OS cron, no cloud scheduler, no background thread, no network.

Hard boundaries (V2/V3 preserved):
  - ARIA can schedule, run, summarize, review, and recommend; it CANNOT live-browse,
    monitor uncontrolled sources, send messages, mutate external systems, or run
    external agents. World checks are FIXTURE-ONLY.
  - disabled routines can NEVER run; failed routines record a class/code-only safe
    error (no raw exception text); outputs cite their sources (no orphan outputs).
  - follow-ups are V3.7 DRAFTS only; improvement suggestions route through V3.5 as
    PROPOSALS only (never activated); ``ARIA_USER_ID`` is attribution only.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.routines import scheduler, templates
from aria.routines.models import (
    ROUTINE_BOUNDARY,
    Cadence,
    OutputType,
    RoutineDefinition,
    RoutineOutput,
    RoutineRun,
    RoutineType,
    RunStatus,
)
from aria.routines.scheduler import DueState
from aria.routines.store import (
    RoutineDisabledError,
    RoutineNotFound,
    RoutineStore,
)

_MAX_REFS = 25
_MAX_ITEMS = 10


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


class RoutineService:
    def __init__(
        self, store: RoutineStore, *, goal_store: Any = None, awareness_service: Any = None,
        collaboration_service: Any = None, workspace_store: Any = None,
        execution_mode: str | None = None, actor: str = "aria",
    ) -> None:
        self._store = store
        self._goals = goal_store
        self._awareness = awareness_service
        self._collab = collaboration_service
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor

    # ── Definitions ──────────────────────────────────────────────────────────

    def create_routine(self, *, name: str, routine_type: str | RoutineType,
                       cadence: str | Cadence = Cadence.manual, interval_hours: int = 24,
                       description: str = "", goal_ids: list[str] | None = None,
                       workspace_id: str | None = None, enabled: bool = True,
                       approval_required: bool = True, actor: str | None = None) -> RoutineDefinition:
        actor = actor or self._actor
        rtype = routine_type if isinstance(routine_type, RoutineType) else RoutineType(routine_type)
        cad = cadence if isinstance(cadence, Cadence) else Cadence(cadence)
        now = _now()
        d = RoutineDefinition(
            routine_id=f"rtn-{uuid.uuid4().hex}", name=name, description=description,
            routine_type=rtype, cadence=cad, interval_hours=max(1, interval_hours),
            enabled=enabled, goal_ids=list(goal_ids or []), workspace_id=workspace_id,
            approval_required=approval_required, created_by=actor, created_at=now, updated_at=now,
        )
        created = self._store.create_definition(d, actor=actor)
        self._attach_ws(workspace_id, [f"routine:{created.routine_id}"], "routine_defined", actor=actor)
        return created

    def enable(self, routine_id: str, *, actor: str | None = None) -> RoutineDefinition:
        return self._store.set_enabled(routine_id, True, actor=actor or self._actor)

    def disable(self, routine_id: str, *, actor: str | None = None) -> RoutineDefinition:
        return self._store.set_enabled(routine_id, False, actor=actor or self._actor)

    def get_routine(self, routine_id: str) -> RoutineDefinition | None:
        return self._store.get_definition(routine_id)

    def list_routines(self, *, enabled: bool | None = None,
                     routine_type: str | None = None) -> list[RoutineDefinition]:
        return self._store.list_definitions(enabled=enabled, routine_type=routine_type)

    # ── Due evaluation + run-due ──────────────────────────────────────────────

    def compute_due(self, *, now: datetime | None = None) -> list[RoutineDefinition]:
        now = now or _now()
        return [d for d in self._store.list_definitions(enabled=True)
                if scheduler.evaluate(d, now) is DueState.due]

    def run_due(self, *, now: datetime | None = None, actor: str | None = None) -> list[RoutineRun]:
        """Run every enabled routine that is due at ``now``; overdue-beyond-grace
        routines are recorded as missed (stale work is not silently executed)."""
        now = now or _now()
        actor = actor or self._actor
        runs: list[RoutineRun] = []
        for d in self._store.list_definitions(enabled=True):
            state = scheduler.evaluate(d, now)
            if state is DueState.due:
                self._store.emit_due(d, due_at=scheduler.due_at(d), actor=actor)
                runs.append(self.run_routine(d.routine_id, now=now, triggered_by="scheduler:due",
                                             actor=actor))
            elif state is DueState.missed:
                self._store.emit_due(d, due_at=scheduler.due_at(d), actor=actor)
                runs.append(self._record_missed(d, now=now, actor=actor))
        return runs

    # ── Run one routine ───────────────────────────────────────────────────────

    def run_routine(self, routine_id: str, *, now: datetime | None = None,
                   triggered_by: str = "manual", actor: str | None = None) -> RoutineRun:
        now = now or _now()
        actor = actor or self._actor
        d = self._store.get_definition(routine_id)
        if d is None:
            raise RoutineNotFound(f"routine {routine_id!r} not found")
        if not d.enabled:
            raise RoutineDisabledError(f"routine {routine_id!r} is disabled and cannot run")

        run_id = f"run-{uuid.uuid4().hex}"
        started = RoutineRun(
            run_id=run_id, routine_id=routine_id, status=RunStatus.running, started_at=now,
            due_at=scheduler.due_at(d), triggered_by=triggered_by, workspace_id=d.workspace_id,
        )
        self._store.record_run_started(started, routine_type=d.routine_type.value, actor=actor)

        # The ENTIRE post-start path is inside the safe-failure boundary: a handler,
        # output-construction, output-validation, persistence, follow-up emission, or
        # finish-write failure can NEVER leave the run stuck `running`. Outputs are
        # staged + validated before ANY is persisted, so a malformed output produces
        # no partial rows. On any error the run is recorded `failed` with a class/
        # code-only ``safe_error`` (never raw exception text / secret).
        try:
            result = self._dispatch(d, now=now, actor=actor)
            staged = [
                RoutineOutput(
                    output_id=f"rout-{uuid.uuid4().hex}", routine_id=routine_id, run_id=run_id,
                    output_type=spec["output_type"], title=spec["title"], body=spec["body"],
                    source_refs=spec.get("source_refs") or [routine_id],
                    evidence_refs=spec.get("evidence_refs", []), memory_refs=spec.get("memory_refs", []),
                    draft_refs=spec.get("draft_refs", []),
                    recommendation_refs=spec.get("recommendation_refs", []), created_at=now,
                )
                for spec in result["outputs"]
            ]
            for out in staged:                       # validate ALL before persisting ANY
                self._store.validate_output(out)

            output_ids: list[str] = []
            for out in staged:
                created = self._store.create_output(out, actor=actor)
                output_ids.append(created.output_id)
                self._attach_ws(d.workspace_id, [f"routine_output:{created.output_id}"],
                                "routine_output_created", actor=actor)

            for fu in result.get("followups", []):
                self._store.emit_followup(routine_id=routine_id, run_id=run_id, draft_id=fu["draft_id"],
                                         goal_id=fu.get("goal_id"), workspace_id=d.workspace_id, actor=actor)
                self._attach_ws(d.workspace_id, [f"routine_followup:{fu['draft_id']}"],
                                "routine_followup_drafted", actor=actor)

            finished = started.model_copy(update={
                "status": RunStatus.completed, "completed_at": now, "output_refs": output_ids,
                "input_refs": result.get("input_refs", []), "summary": result["summary"],
                "findings": result.get("findings", []), "recommendations": result.get("recommendations", []),
            })
            self._store.record_run_finished(finished, routine_type=d.routine_type.value, actor=actor)
            self._attach_ws(d.workspace_id, [f"routine_run:{run_id}"], "routine_run_completed", actor=actor)
            return self._store.get_run(run_id)  # type: ignore[return-value]
        except Exception as exc:  # safe failure — class/code only, never raw text/secret
            failed = started.model_copy(update={
                "status": RunStatus.failed, "completed_at": now,
                "error_code": "routine_handler_error", "safe_error": type(exc).__name__,
                "summary": "Routine failed safely; see safe_error (class only).",
            })
            self._store.record_run_finished(failed, routine_type=d.routine_type.value, actor=actor)
            return self._store.get_run(run_id)  # type: ignore[return-value]

    def _record_missed(self, d: RoutineDefinition, *, now: datetime, actor: str) -> RoutineRun:
        run_id = f"run-{uuid.uuid4().hex}"
        missed = RoutineRun(
            run_id=run_id, routine_id=d.routine_id, status=RunStatus.missed, started_at=now,
            completed_at=now, due_at=scheduler.due_at(d), triggered_by="scheduler:due",
            workspace_id=d.workspace_id,
            summary="Routine overdue beyond its grace window — recorded as missed; stale work "
                    "was not executed.",
        )
        self._store.record_run_started(missed.model_copy(update={"status": RunStatus.running}),
                                      routine_type=d.routine_type.value, actor=actor)
        self._store.record_run_finished(missed, routine_type=d.routine_type.value, actor=actor)
        self._attach_ws(d.workspace_id, [f"routine_run:{run_id}:missed"], "routine_run_missed", actor=actor)
        return self._store.get_run(run_id)  # type: ignore[return-value]

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_run(self, run_id: str) -> RoutineRun | None:
        return self._store.get_run(run_id)

    def list_runs(self, *, routine_id: str | None = None, status: str | None = None) -> list[RoutineRun]:
        return self._store.list_runs(routine_id=routine_id, status=status)

    def list_outputs(self, *, run_id: str | None = None,
                    routine_id: str | None = None) -> list[RoutineOutput]:
        return self._store.list_outputs(run_id=run_id, routine_id=routine_id)

    @staticmethod
    def boundary_note() -> str:
        return ROUTINE_BOUNDARY

    # ── Handler dispatch ──────────────────────────────────────────────────────

    def _dispatch(self, d: RoutineDefinition, *, now: datetime, actor: str) -> dict[str, Any]:
        handler = {
            RoutineType.daily_goal_review: self._h_goal_review,
            RoutineType.weekly_goal_review: self._h_goal_review,
            RoutineType.manager_summary: self._h_manager_summary,
            RoutineType.blocker_review: self._h_blocker_review,
            RoutineType.risk_review: self._h_risk_review,
            RoutineType.memory_review: self._h_memory_review,
            RoutineType.skill_gap_review: self._h_memory_review,
            RoutineType.collaboration_review: self._h_collaboration_review,
            RoutineType.approval_queue_review: self._h_collaboration_review,
            RoutineType.world_fixture_check: self._h_world_fixture_check,
        }.get(d.routine_type)
        if handler is None:  # pragma: no cover - all enum types are mapped
            raise ValueError(f"unsupported routine type {d.routine_type.value!r}")
        return handler(d, now=now, actor=actor)

    # ── Gatherers ─────────────────────────────────────────────────────────────

    def _goals_for(self, d: RoutineDefinition) -> list:
        if self._goals is None:
            return []
        if d.goal_ids:
            return [g for g in (self._goals.get_goal(gid) for gid in d.goal_ids) if g is not None]
        return self._goals.list_goals()

    def _goal_state(self, d: RoutineDefinition) -> dict[str, Any]:
        goals = self._goals_for(d)
        goal_refs, blockers, progress, evidence, decisions, risks = [], [], [], [], [], []
        for g in goals:
            goal_refs.append(g.goal_id)
            if g.risk_level and g.risk_level != "low":
                risks.append(f"Goal '{g.title}' risk level: {g.risk_level}")
            for t in self._goals.get_tasks(g.goal_id):
                if t.status.value in ("blocked", "needs_clarification", "needs_evidence"):
                    blockers.append(f"'{t.title}' is {t.status.value}")
                    evidence.append(t.task_id)
                elif t.status.value == "completed":
                    progress.append(f"Completed: {t.title}")
                    evidence.append(t.task_id)
                elif t.status.value == "awaiting_approval":
                    decisions.append(f"Approval needed: {t.title}")
                    evidence.append(t.task_id)
            for a in self._goals.get_agent_assignments(g.goal_id):
                if a.failure_reason:
                    blockers.append(f"Agent {a.agent_id} blocked: {a.failure_reason}")
                    evidence.append(a.assignment_id)
            for e in self._goals.list_escalations(g.goal_id):
                risks.append(f"Escalation: {e.reason}")
                decisions.append(e.suggested_action)
                evidence.append(e.escalation_id)
        return {
            "goals": goals, "goal_refs": _dedupe(goal_refs), "blockers": _dedupe(blockers)[:_MAX_ITEMS],
            "progress": _dedupe(progress)[:_MAX_ITEMS], "evidence": _dedupe(evidence)[:_MAX_REFS],
            "decisions": _dedupe(decisions)[:_MAX_ITEMS], "risks": _dedupe(risks)[:_MAX_ITEMS],
        }

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _h_goal_review(self, d: RoutineDefinition, *, now: datetime, actor: str) -> dict[str, Any]:
        st = self._goal_state(d)
        weekly = d.routine_type is RoutineType.weekly_goal_review
        out_type = OutputType.weekly_summary if weekly else OutputType.daily_summary
        title = ("Weekly goal review" if weekly else "Daily goal review")
        body = templates.render(title, [
            ("Goals reviewed", [f"{g.title}" for g in st["goals"]]),
            ("Recent progress", st["progress"]),
            ("Open blockers", st["blockers"]),
            ("Decisions needed", st["decisions"]),
        ], empties={"Goals reviewed": "(no active goals)"})
        followups, draft_refs = self._maybe_manager_draft(st, condition=bool(st["blockers"]), actor=actor)
        findings = [f"{len(st['goals'])} goal(s) reviewed", f"{len(st['blockers'])} blocker(s)"]
        return {
            "summary": f"{title}: {len(st['goals'])} goal(s), {len(st['blockers'])} blocker(s).",
            "findings": findings, "recommendations": st["decisions"], "input_refs": st["goal_refs"],
            "outputs": [{
                "output_type": out_type, "title": title, "body": body,
                "source_refs": _dedupe(st["goal_refs"] + [d.routine_id]),
                "evidence_refs": st["evidence"], "draft_refs": draft_refs,
            }],
            "followups": followups,
        }

    def _h_manager_summary(self, d: RoutineDefinition, *, now: datetime, actor: str) -> dict[str, Any]:
        st = self._goal_state(d)
        body = templates.render("Manager summary", [
            ("Status", [f"{len(st['goals'])} goal(s), {len(st['blockers'])} blocker(s)"]),
            ("Progress", st["progress"]),
            ("Risks", st["risks"]),
            ("Decisions needed", st["decisions"]),
        ])
        followups, draft_refs = self._maybe_manager_draft(st, condition=bool(st["goals"]), actor=actor)
        return {
            "summary": "Manager summary prepared (draft-only).", "findings": [], "input_refs": st["goal_refs"],
            "recommendations": st["decisions"],
            "outputs": [{
                "output_type": OutputType.manager_update_draft, "title": "Manager summary", "body": body,
                "source_refs": _dedupe(st["goal_refs"] + [d.routine_id]), "evidence_refs": st["evidence"],
                "draft_refs": draft_refs,
            }],
            "followups": followups,
        }

    def _h_blocker_review(self, d: RoutineDefinition, *, now: datetime, actor: str) -> dict[str, Any]:
        st = self._goal_state(d)
        questions = [f"Clarify to unblock: {b}" for b in st["blockers"][:5]]
        body = templates.render("Blocker digest", [
            ("Active blockers", st["blockers"]),
            ("Suggested stakeholder questions", questions),
            ("Risks", st["risks"]),
        ], empties={"Active blockers": "(no active blockers)"})
        # Escalation draft only when there is a recorded risk/escalation.
        followups, draft_refs = self._maybe_risk_draft(st, condition=bool(st["risks"]), actor=actor)
        return {
            "summary": f"Blocker digest: {len(st['blockers'])} blocker(s).",
            "findings": [f"{len(st['blockers'])} blocker(s)"], "recommendations": questions,
            "input_refs": st["goal_refs"],
            "outputs": [{
                "output_type": OutputType.blocker_digest, "title": "Blocker digest", "body": body,
                "source_refs": _dedupe(st["goal_refs"] + [d.routine_id]), "evidence_refs": st["evidence"],
                "draft_refs": draft_refs,
            }],
            "followups": followups,
        }

    def _h_risk_review(self, d: RoutineDefinition, *, now: datetime, actor: str) -> dict[str, Any]:
        st = self._goal_state(d)
        body = templates.render("Risk digest", [
            ("Risks", st["risks"]),
            ("Open blockers", st["blockers"]),
            ("Decisions needed", st["decisions"]),
        ], empties={"Risks": "(no recorded risks)"})
        followups, draft_refs = self._maybe_risk_draft(st, condition=bool(st["risks"]), actor=actor)
        return {
            "summary": f"Risk digest: {len(st['risks'])} risk(s).",
            "findings": [f"{len(st['risks'])} risk(s)"], "recommendations": st["decisions"],
            "input_refs": st["goal_refs"],
            "outputs": [{
                "output_type": OutputType.risk_digest, "title": "Risk digest", "body": body,
                "source_refs": _dedupe(st["goal_refs"] + [d.routine_id]), "evidence_refs": st["evidence"],
                "draft_refs": draft_refs,
            }],
            "followups": followups,
        }

    def _h_memory_review(self, d: RoutineDefinition, *, now: datetime, actor: str) -> dict[str, Any]:
        lessons, nodes, improvements = [], [], []
        lesson_titles, lesson_refs = [], []
        if self._awareness is not None:
            try:
                lessons = self._awareness.list_lessons(usable_only=True)
                nodes = self._awareness.list_nodes()
                improvements = self._awareness.list_improvements()
            except Exception:  # pragma: no cover - defensive
                lessons, nodes, improvements = [], [], []
        for l in lessons[:_MAX_ITEMS]:
            lesson_titles.append(l.title)
            lesson_refs.append(l.lesson_id)
        rec_refs = self._maybe_route_improvement(actor=actor)
        body = templates.render("Memory lesson digest", [
            ("Usable lessons", lesson_titles),
            ("Memory nodes", [f"{len(nodes)} node(s) recorded"]),
            ("Existing improvement proposals", [f"{len(improvements)} proposal(s)"]),
            ("Routed this run (proposal-only)", [f"skill proposal {r}" for r in rec_refs]),
        ], empties={"Usable lessons": "(no usable lessons yet)"})
        return {
            "summary": f"Memory digest: {len(lesson_titles)} lesson(s), {len(nodes)} node(s).",
            "findings": [f"{len(lesson_titles)} usable lesson(s)"],
            "recommendations": ["Review reusable lessons before similar work."],
            "input_refs": lesson_refs,
            "outputs": [{
                "output_type": OutputType.memory_lesson_digest, "title": "Memory lesson digest",
                "body": body, "source_refs": _dedupe(lesson_refs + [d.routine_id]),
                "memory_refs": lesson_refs, "recommendation_refs": rec_refs,
            }],
            "followups": [],
        }

    def _h_collaboration_review(self, d: RoutineDefinition, *, now: datetime, actor: str) -> dict[str, Any]:
        drafts, approvals = [], []
        if self._collab is not None:
            try:
                drafts = self._collab.list_drafts()
                approvals = self._collab.list_approval_requests()
            except Exception:  # pragma: no cover - defensive
                drafts, approvals = [], []
        draft_refs = [x.draft_id for x in drafts]
        approval_refs = [a.approval_request_id for a in approvals]
        by_status: dict[str, int] = {}
        for x in drafts:
            by_status[x.status.value] = by_status.get(x.status.value, 0) + 1
        body = templates.render("Approval queue & pending drafts", [
            ("Pending drafts by status", [f"{k}: {v}" for k, v in sorted(by_status.items())]),
            ("Approval requests", [a.title for a in approvals]),
            ("Recommended follow-up", ["Review drafts marked ready_for_review for approval."]),
        ], empties={"Pending drafts by status": "(no drafts)", "Approval requests": "(no approval requests)"})
        return {
            "summary": f"Collaboration digest: {len(drafts)} draft(s), {len(approvals)} approval request(s).",
            "findings": [f"{len(drafts)} draft(s)", f"{len(approvals)} approval request(s)"],
            "recommendations": ["Action drafts pending review."],
            "input_refs": _dedupe(draft_refs + approval_refs),
            "outputs": [{
                "output_type": OutputType.approval_queue_digest, "title": "Approval queue & pending drafts",
                "body": body, "source_refs": _dedupe(draft_refs + approval_refs + [d.routine_id]),
                "draft_refs": draft_refs,
            }],
            "followups": [],
        }

    def _h_world_fixture_check(self, d: RoutineDefinition, *, now: datetime, actor: str) -> dict[str, Any]:
        updates, brief = [], {"updates": []}
        if self._awareness is not None:
            updates = self._awareness.ingest_world(actor=actor)   # FIXTURE-ONLY (no network)
            brief = self._awareness.world_brief()
        items, update_refs, citations = [], [], []
        for u in brief.get("updates", []):
            items.append(f"{u['title']} [trust={u['trust_level']}, relevance={u['relevance_score']}, "
                         f"risk={u['risk_level']}]")
            update_refs.append(u["update_id"])
            citations.extend(u.get("citations", []))
        rec_refs = self._maybe_route_world_improvement(brief.get("updates", []), actor=actor)
        body = templates.render("World awareness digest (fixture-only)", [
            ("Updates (cited)", items),
            ("Routed this run (proposal-only)", [f"skill proposal {r}" for r in rec_refs]),
        ], empties={"Updates (cited)": "(no fixture updates)"})
        return {
            "summary": f"World fixture check: {len(update_refs)} update(s) (fixture-only, no live web).",
            "findings": [f"{len(update_refs)} fixture update(s)"],
            "recommendations": ["High-risk advisories escalate to human review."],
            "input_refs": update_refs,
            "outputs": [{
                "output_type": OutputType.world_awareness_digest,
                "title": "World awareness digest (fixture-only)", "body": body,
                "source_refs": _dedupe(update_refs + citations + [d.routine_id]),
                "evidence_refs": _dedupe(citations), "recommendation_refs": rec_refs,
            }],
            "followups": [],
        }

    # ── Follow-up draft / improvement helpers (draft-only / proposal-only) ─────

    def _maybe_manager_draft(self, st: dict, *, condition: bool, actor: str
                             ) -> tuple[list[dict], list[str]]:
        if not (condition and self._collab and st["goals"]):
            return [], []
        from aria.collaboration.models import DraftType

        try:
            goal = st["goals"][0]
            draft = self._collab.generate_draft(goal.goal_id, DraftType.manager_update, actor=actor)
            return [{"draft_id": draft.draft_id, "goal_id": goal.goal_id}], [draft.draft_id]
        except Exception:  # pragma: no cover - collaboration is best-effort here
            return [], []

    def _maybe_risk_draft(self, st: dict, *, condition: bool, actor: str
                          ) -> tuple[list[dict], list[str]]:
        if not (condition and self._collab and st["goals"]):
            return [], []
        from aria.collaboration.models import DraftType

        try:
            goal = st["goals"][0]
            draft = self._collab.generate_draft(goal.goal_id, DraftType.risk_escalation, actor=actor)
            return [{"draft_id": draft.draft_id, "goal_id": goal.goal_id}], [draft.draft_id]
        except Exception:  # pragma: no cover
            return [], []

    def _maybe_route_improvement(self, *, actor: str) -> list[str]:
        """Route ONE improvement to V3.5 as a PROPOSAL only, and only when none exist
        yet (deterministic, non-spamming, never activates)."""
        if self._awareness is None:
            return []
        try:
            if self._awareness.list_improvements():
                return []
            for node in self._awareness.list_nodes(status="active"):
                if node.confidence >= 0.5:
                    imp = self._awareness.propose_improvement_from_node(node.node_id, actor=actor)
                    return [imp.skill_proposal_id] if imp.skill_proposal_id else []
        except Exception:  # pragma: no cover - improvement routing is best-effort + guarded
            return []
        return []

    def _maybe_route_world_improvement(self, updates: list[dict], *, actor: str) -> list[str]:
        if self._awareness is None:
            return []
        try:
            if self._awareness.list_improvements():
                return []
            for u in sorted(updates, key=lambda x: -x.get("relevance_score", 0)):
                if (u.get("trust_level") == "high" and u.get("risk_level") != "high"
                        and u.get("relevance_score", 0) >= 0.5):
                    imp = self._awareness.propose_improvement_from_update(u["update_id"], actor=actor)
                    return [imp.skill_proposal_id] if imp.skill_proposal_id else []
        except Exception:  # pragma: no cover - guarded (ImprovementBlocked etc.)
            return []
        return []

    # ── Workspace ─────────────────────────────────────────────────────────────

    def _attach_ws(self, ws_id: str | None, refs: list[str], status: str, *, actor: str) -> None:
        if self._workspace_store is None or not ws_id or not refs:
            return
        try:
            self._workspace_store.update_workspace(
                ws_id, status=status, add_ledger_refs=list(refs), actor=actor)
        except Exception:  # pragma: no cover - workspace bookkeeping is best-effort
            pass
