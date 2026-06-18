"""
Goal / Task Board Service (V3.1 — Goal Ownership Foundation).

A thin planning/control facade over the deterministic intake engine and the SQLite
goal store, with optional V2-workspace integration. It is the single entry point
the API/terminal use to "own" a goal.

PLANNING ONLY. ``own_goal`` turns a vague request into a goal + roadmap + task
board and links a workspace. Moving a task changes a *planning status* — it runs
no tool, no workflow, and writes nothing externally. Approval-required tasks are
flagged for a human decision; flagging is not execution.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.goals.intake import build_roadmap, run_intake
from aria.goals.models import (
    GoalIntake,
    GoalPlan,
    GoalProgress,
    GoalStatus,
    OwnerType,
    Priority,
    Roadmap,
    TaskItem,
    TaskStatus,
)
from aria.goals.store import GoalStore


def _now() -> datetime:
    return datetime.now(UTC)


def _skill_hint(phase_name: str) -> str | None:
    low = phase_name.lower()
    if any(w in low for w in ("trend", "metric", "segment", "taxonomy", "freshness", "data")):
        return "analytics"
    if "summary" in low:
        return "reporting"
    if "review" in low or "code" in low:
        return "pr_review"
    return None


class GoalService:
    def __init__(
        self, store: GoalStore, *, workspace_store: Any = None,
        execution_mode: str | None = None, actor: str = "aria",
    ) -> None:
        self._store = store
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor

    # ── Own a goal end-to-end (intake → roadmap → task board → workspace) ────

    def own_goal(
        self, raw_request: str, *, scope: str = "general", owner: str | None = None,
        stakeholders: list[str] | None = None,
    ) -> GoalPlan:
        actor = owner or self._actor
        intake = run_intake(raw_request, scope=scope, stakeholders=stakeholders)
        goal = self._store.create_goal(intake, actor=actor)

        roadmap = build_roadmap(goal)
        self._store.create_roadmap(roadmap, actor=actor)

        tasks = self._build_tasks(goal, roadmap)
        self._store.create_tasks(tasks, actor=actor)

        workspace_id = self._integrate_workspace(goal, roadmap, tasks, actor=actor)
        if workspace_id is not None:
            goal = self._store.set_goal_workspace(goal.goal_id, workspace_id)
        goal = self._store.update_goal_status(goal.goal_id, GoalStatus.planned)

        return GoalPlan(
            goal=goal, roadmap=self._store.get_roadmap(goal.goal_id),  # type: ignore[arg-type]
            tasks=self._store.get_tasks(goal.goal_id), workspace_id=workspace_id,
        )

    # ── Task board operations (planning only) ────────────────────────────────

    def update_task_status(
        self, task_id: str, status: TaskStatus | str, *,
        blocked_by: list[str] | None = None, output_artifact: str | None = None,
        actor: str | None = None,
    ) -> TaskItem:
        return self._store.update_task_status(
            task_id, status, blocked_by=blocked_by, output_artifact=output_artifact,
            actor=actor or self._actor,
        )

    def get_progress(self, goal_id: str, *, report: bool = True) -> GoalProgress:
        if report:
            return self._store.report_progress(goal_id, actor=self._actor)
        return self._store.compute_progress(goal_id)

    # ── Pass-through reads ───────────────────────────────────────────────────

    def get_goal(self, goal_id: str) -> GoalIntake | None:
        return self._store.get_goal(goal_id)

    def get_roadmap(self, goal_id: str) -> Roadmap | None:
        return self._store.get_roadmap(goal_id)

    def get_tasks(self, goal_id: str) -> list[TaskItem]:
        return self._store.get_tasks(goal_id)

    def list_goals(self, *, status: str | None = None, scope: str | None = None) -> list[GoalIntake]:
        return self._store.list_goals(status=status, scope=scope)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _build_tasks(self, goal: GoalIntake, roadmap: Roadmap) -> list[TaskItem]:
        """One planning task per roadmap phase + a final human approval gate. All
        start ``planned``; none execute anything."""
        now = _now()
        tasks: list[TaskItem] = []
        for phase in roadmap.phases:
            tasks.append(TaskItem(
                task_id=f"taskitem-{uuid.uuid4().hex}", goal_id=goal.goal_id,
                roadmap_id=roadmap.roadmap_id, title=phase.name, description=phase.objective,
                status=TaskStatus.planned, priority=Priority.medium, owner_type=OwnerType.aria,
                required_skill=_skill_hint(phase.name),
                required_evidence=list(phase.evidence_needed),
                approval_required=False, created_at=now, updated_at=now,
            ))
        # Final governance gate: a human must approve the plan/outcome. Flag only —
        # no external action is taken when this is created or moved.
        tasks.append(TaskItem(
            task_id=f"taskitem-{uuid.uuid4().hex}", goal_id=goal.goal_id,
            roadmap_id=roadmap.roadmap_id, title="Approve plan and outcome",
            description="Human approval gate before any action item leaves draft state.",
            status=TaskStatus.planned, priority=Priority.high, owner_type=OwnerType.human,
            required_skill=None, required_evidence=[], approval_required=True,
            created_at=now, updated_at=now,
        ))
        return tasks

    def _integrate_workspace(
        self, goal: GoalIntake, roadmap: Roadmap, tasks: list[TaskItem], *, actor: str,
    ) -> str | None:
        ws_store = self._workspace_store
        if ws_store is None:
            return None
        ws = ws_store.create_workspace(
            owner=actor, scope=goal.scope, correlation_id=goal.goal_id, task_id=goal.goal_id,
        )
        brief_ref = ws_store.write_artifact(ws.workspace_id, "goal_brief.md", render_goal_brief(goal))
        roadmap_ref = ws_store.write_artifact(ws.workspace_id, "roadmap.md", render_roadmap(roadmap))
        ledger_refs = (
            [f"goal:{goal.goal_id}", f"roadmap:{roadmap.roadmap_id}"]
            + [f"task:{t.task_id}" for t in tasks]
        )
        approval_refs = [f"task:{t.task_id}" for t in tasks if t.approval_required]
        ws_store.update_workspace(
            ws.workspace_id, status="goal_planned",
            add_artifact_refs=[brief_ref, roadmap_ref],
            add_ledger_refs=ledger_refs, add_approval_refs=approval_refs,
            final_outcome=f"goal planned: {goal.title}", actor=actor,
        )
        return ws.workspace_id


# ── Deterministic artifact renderers (no secrets, no raw paths) ──────────────


def render_goal_brief(goal: GoalIntake) -> str:
    lines = [
        f"# Goal Brief — {goal.title}",
        "",
        f"**Status:** {goal.status.value}  ·  **Scope:** {goal.scope}  ·  **Risk:** {goal.risk_level}",
        "",
        "## Problem Statement", goal.problem_statement, "",
        "## Goal", goal.goal, "",
        "## Success Criteria",
        *[f"- {c}" for c in goal.success_criteria], "",
        "## Known Context",
        *[f"- {c}" for c in goal.known_context], "",
        "## Missing Context",
        *[f"- {c}" for c in goal.missing_context], "",
        "## Clarifying Questions",
        *[f"- {q}" for q in goal.clarifying_questions], "",
        "## Constraints",
        *[f"- {c}" for c in goal.constraints], "",
        "_Planning artifact only. No production writes. No external actions taken._",
    ]
    return "\n".join(lines)


def render_roadmap(roadmap: Roadmap) -> str:
    lines = [f"# Roadmap ({roadmap.roadmap_id})", ""]
    for p in roadmap.phases:
        lines.append(f"{p.order}. **{p.name}** — {p.objective}")
        for e in p.evidence_needed:
            lines.append(f"   - evidence: {e}")
    lines += ["", "## Deliverables", *[f"- {d}" for d in roadmap.deliverables]]
    lines += ["", "## Risks", *[f"- {r}" for r in roadmap.risks]]
    lines += ["", "_Planning artifact only. Evidence is gathered, never assumed._"]
    return "\n".join(lines)
