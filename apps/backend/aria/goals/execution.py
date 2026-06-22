"""
Work Execution Loop (V3.2) — governed, one step at a time.

Takes an existing V3.1 goal/roadmap/task board and moves it forward ONE governed
step per call:

    load goal -> inspect tasks/progress -> choose next actionable task
    -> check clarification -> check evidence -> check approval
    -> produce a PLANNING step result -> update task status -> update workspace
    -> emit Work Ledger events -> (progress summary on demand)

Hard boundaries (V2/V3.1 preserved):
  - PLANNING/CONTROL ONLY — a "completed step" produces a *planning artifact*; it
    runs no tool and writes nothing externally.
  - approval-required tasks NEVER auto-execute (they become ``awaiting_approval``).
  - blocked tasks are never skipped silently; missing context -> a clarification
    request; missing evidence -> a ``needs_evidence`` result.
  - ARIA never fabricates evidence; memory may explain definitions but cannot prove
    a factual claim, so the evidence gate is independent of memory.
  - failures fail SAFELY: the task goes ``failed`` and the user message carries the
    exception CLASS only — never raw exception text or chain-of-thought.
  - secrets are sanitised out of every persisted/returned string.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.goals.models import (
    ExecutionOutcome,
    ExecutionProgress,
    ExecutionStep,
    GoalIntake,
    Priority,
    TaskItem,
    TaskStatus,
)
from aria.goals.sanitize import sanitize_text
from aria.goals.store import GoalNotFound, GoalStore

_PRIORITY_RANK = {Priority.high: 3, Priority.medium: 2, Priority.low: 1}
# Not advanceable in normal selection: failed needs human review (no retry in V3.2),
# so it is excluded from selection — but it is NOT "successful work".
_NOT_ADVANCEABLE = (TaskStatus.completed, TaskStatus.cancelled, TaskStatus.failed)
# Successfully closed work. The approval gate / goal-complete require these — a
# ``failed`` task must NOT make the gate actionable or the goal look finishable.
_SUCCESSFUL = (TaskStatus.completed, TaskStatus.cancelled)


def _now() -> datetime:
    return datetime.now(UTC)


def _deliverable_kind(task: TaskItem) -> str:
    low = task.title.lower()
    if "summary" in low:
        return "manager_summary"
    if "action plan" in low or "draft" in low:
        return "action_plan"
    if "review" in low:
        return "review_findings"
    if any(w in low for w in ("validate", "trend", "segment", "taxonomy", "root cause", "analyse", "analyze")):
        return "investigation_findings"
    return "investigation_report"


class ExecutionService:
    def __init__(
        self, store: GoalStore, *, workspace_store: Any = None,
        execution_mode: str | None = None, actor: str = "aria",
    ) -> None:
        self._store = store
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor

    # ── Public API ────────────────────────────────────────────────────────────

    def execute_next(self, goal_id: str, *, actor: str | None = None) -> ExecutionStep:
        actor = actor or self._actor
        goal = self._store.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        tasks = self._store.get_tasks(goal_id)
        selected, no_action_reason = self._select_next(tasks)

        if selected is None:
            return self._record(
                goal, task=None, outcome=ExecutionOutcome.no_actionable_task,
                selected_action="none", reason=no_action_reason,
                status_after=None, safe_message=self._no_action_message(goal_id, no_action_reason),
                actor=actor,
            )
        return self._work_task(goal, selected, actor=actor)

    def submit_clarification(
        self, goal_id: str, answers: dict[str, str], *, clarification_id: str | None = None,
        actor: str | None = None,
    ):
        actor = actor or self._actor
        if self._store.get_goal(goal_id) is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        open_clars = self._store.list_clarifications(goal_id, status="open")
        target = clarification_id or (open_clars[0].clarification_id if open_clars else None)
        if target is None:
            raise GoalNotFound(f"no open clarification for goal {goal_id!r}")
        return self._store.answer_clarification(target, answers, actor=actor)

    def provide_evidence(self, goal_id: str, evidence_refs: list[str], *, provided_by: str | None = None):
        if self._store.get_goal(goal_id) is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        return self._store.provide_evidence(goal_id, evidence_refs, provided_by=provided_by or self._actor)

    def progress_report(self, goal_id: str, *, actor: str | None = None) -> ExecutionProgress:
        actor = actor or self._actor
        goal = self._store.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(f"goal {goal_id!r} not found")
        tasks = self._store.get_tasks(goal_id)
        deliverables = self._store.list_deliverables(goal_id)
        open_clars = self._store.list_clarifications(goal_id, status="open")
        provided = set(self._store.list_evidence(goal_id))

        completed = sum(1 for t in tasks if t.status is TaskStatus.completed)
        in_progress = sum(1 for t in tasks if t.status is TaskStatus.in_progress)
        blocked = sum(1 for t in tasks if t.status in (
            TaskStatus.blocked, TaskStatus.needs_clarification, TaskStatus.needs_evidence,
            TaskStatus.failed,
        ))
        pending_approvals = sum(1 for t in tasks if t.status is TaskStatus.awaiting_approval) or \
            sum(1 for t in tasks if t.approval_required and t.status not in _NOT_ADVANCEABLE
                and self._all_work_done(tasks))
        failed = sum(1 for t in tasks if t.status is TaskStatus.failed)
        evidence_needed = []
        for t in tasks:
            if t.status not in _NOT_ADVANCEABLE:
                evidence_needed.extend(e for e in t.required_evidence if e not in provided)
        evidence_needed = list(dict.fromkeys(evidence_needed))           # dedupe, ordered
        open_questions = [q for c in open_clars for q in c.questions]
        artifacts = [d.artifact_ref or d.title for d in deliverables]

        selected, _ = self._select_next(tasks)
        current_phase = selected.title if selected else "all tasks closed"
        next_action = self._next_recommended(goal_id, tasks, open_questions, evidence_needed, selected)
        risk = "blocked" if blocked else goal.risk_level

        self._store.emit_progress_report(
            goal_id, outcome=f"completed={completed}/{len(tasks)}", actor=actor,
        )
        return ExecutionProgress(
            goal_id=goal_id, goal_title=goal.title, current_phase=current_phase,
            total_tasks=len(tasks),
            completed_tasks=completed, in_progress_tasks=in_progress, blocked_tasks=blocked,
            pending_approvals=pending_approvals, evidence_needed=evidence_needed,
            artifacts_created=artifacts, open_clarifications=open_questions,
            next_recommended_action=next_action, risk_summary=risk,
        )

    # ── Next-action selector ──────────────────────────────────────────────────

    def _select_next(self, tasks: list[TaskItem]) -> tuple[TaskItem | None, str]:
        """Pick the next actionable task, or (None, reason). Work tasks first
        (highest priority, then board order); the approval gate is only selectable
        once all work tasks are done."""
        by_id = {t.task_id: t for t in tasks}
        work = [t for t in tasks if not t.approval_required]
        gates = [t for t in tasks if t.approval_required]

        advanceable = [t for t in work if t.status not in _NOT_ADVANCEABLE]
        actionable = [t for t in advanceable if self._deps_met(t, by_id)]
        if actionable:
            actionable.sort(key=lambda t: -_PRIORITY_RANK.get(t.priority, 0))
            return actionable[0], ""
        if advanceable:
            return None, "tasks_waiting_on_dependencies"

        # No advanceable work left. A FAILED work task blocks the goal — it needs
        # human review (no auto-retry in V3.2). It must NOT let the gate proceed.
        if any(t.status is TaskStatus.failed for t in work):
            return None, "failed_tasks_need_review"

        # All work SUCCESSFULLY closed (completed/cancelled) → the approval gate is
        # selectable. ``failed`` is deliberately excluded above.
        if all(t.status in _SUCCESSFUL for t in work):
            pending_gates = [
                t for t in gates
                if t.status not in (*_NOT_ADVANCEABLE, TaskStatus.awaiting_approval)
            ]
            if pending_gates and self._deps_met(pending_gates[0], by_id):
                return pending_gates[0], ""
            if any(t.status is TaskStatus.awaiting_approval for t in gates):
                return None, "awaiting_human_approval"
        return None, "goal_complete"

    @staticmethod
    def _deps_met(task: TaskItem, by_id: dict[str, TaskItem]) -> bool:
        for dep in task.blocked_by:
            dep_task = by_id.get(dep)
            if dep_task is None or dep_task.status is not TaskStatus.completed:
                return False
        return True

    @staticmethod
    def _all_work_done(tasks: list[TaskItem]) -> bool:
        """All non-approval work SUCCESSFULLY closed (failed does not count)."""
        return all(t.status in _SUCCESSFUL for t in tasks if not t.approval_required)

    # ── Per-task governed state machine ───────────────────────────────────────

    def _work_task(self, goal: GoalIntake, task: TaskItem, *, actor: str) -> ExecutionStep:
        status_before = task.status.value

        # 1) Approval gate — never auto-executes.
        if task.approval_required:
            return self._record(
                goal, task=task, outcome=ExecutionOutcome.blocked_for_approval,
                selected_action="await_approval",
                reason="task requires explicit human approval before any action",
                status_before=status_before, status_after=TaskStatus.awaiting_approval,
                safe_message="Awaiting approval: a human must approve the plan/outcome before it proceeds.",
                approval_required=True, evidence_status="n/a", actor=actor,
            )

        # 2) Clarification gate (goal-level): missing context blocks work.
        if self._needs_clarification(goal):
            clar = self._ensure_clarification(goal, task, actor=actor)
            return self._record(
                goal, task=task, outcome=ExecutionOutcome.blocked_for_clarification,
                selected_action="await_clarification",
                reason="required context is missing",
                status_before=status_before, status_after=TaskStatus.needs_clarification,
                safe_message=self._clarification_message(clar.questions),
                clarification_id=clar.clarification_id, evidence_status="missing_context", actor=actor,
            )

        # 3) Evidence gate: required evidence not provided (memory cannot satisfy it).
        provided = set(self._store.list_evidence(goal.goal_id))
        missing = [e for e in task.required_evidence if e not in provided]
        if missing:
            return self._record(
                goal, task=task, outcome=ExecutionOutcome.blocked_for_evidence,
                selected_action="await_evidence",
                reason="required evidence has not been provided (ARIA does not fabricate evidence)",
                status_before=status_before, status_after=TaskStatus.needs_evidence,
                safe_message="Blocked: evidence needed before this step.\n- " + "\n- ".join(missing),
                evidence_status="missing", actor=actor,
            )

        # 4) Execute the planning step (produce a planning artifact). Fails SAFELY.
        try:
            kind, title, artifact_ref = self._produce_deliverable(goal, task)
        except Exception as exc:  # never leak raw text — class only
            return self._record(
                goal, task=task, outcome=ExecutionOutcome.failed_safely,
                selected_action="produce_deliverable",
                reason=f"step halted by an internal error ({type(exc).__name__})",
                status_before=status_before, status_after=TaskStatus.failed,
                safe_message=(
                    f"Execution halted safely due to an internal error ({type(exc).__name__}). "
                    "No changes were made."
                ),
                evidence_status="satisfied", actor=actor,
            )

        self._store.track_deliverable(
            goal.goal_id, kind, title, task_id=task.task_id, artifact_ref=artifact_ref, actor=actor,
        )
        return self._record(
            goal, task=task, outcome=ExecutionOutcome.completed_step,
            selected_action="produce_deliverable", reason=f"produced planning {kind}",
            status_before=status_before, status_after=TaskStatus.completed,
            produced_artifact=artifact_ref, safe_message=f"Completed: {title} (planning artifact only).",
            evidence_status="satisfied", actor=actor, deliverable_kind=kind,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _needs_clarification(self, goal: GoalIntake) -> bool:
        if not goal.clarifying_questions:
            return False
        answered = self._store.list_clarifications(goal.goal_id, status="answered")
        return len(answered) == 0

    def _ensure_clarification(self, goal: GoalIntake, task: TaskItem, *, actor: str):
        open_clars = self._store.list_clarifications(goal.goal_id, status="open")
        if open_clars:
            return open_clars[0]
        return self._store.create_clarification(
            goal.goal_id, goal.clarifying_questions, task_id=task.task_id, actor=actor,
        )

    @staticmethod
    def _clarification_message(questions: list[str]) -> str:
        lines = ["Blocked: need clarification.", "Questions:"]
        lines += [f"{i + 1}. {q}" for i, q in enumerate(questions)]
        return "\n".join(lines)

    def _produce_deliverable(self, goal: GoalIntake, task: TaskItem) -> tuple[str, str, str | None]:
        """Render a PLANNING artifact for the step and store it in the workspace.
        Returns (kind, title, artifact_ref). No external write — a workspace file
        under ARIA_DATA_DIR only."""
        kind = _deliverable_kind(task)
        title = f"{task.title} ({kind})"
        # Sanitise the artifact body too — a task title/description must never leak a
        # secret into a workspace file (defence in depth on top of intake sanitising).
        content = sanitize_text(self._render_step_artifact(goal, task, kind)) or ""
        artifact_ref = None
        if self._workspace_store is not None and goal.workspace_id:
            name = f"{kind}_{uuid.uuid4().hex[:8]}.md"
            artifact_ref = self._workspace_store.write_artifact(goal.workspace_id, name, content)
        return kind, title, artifact_ref

    @staticmethod
    def _render_step_artifact(goal: GoalIntake, task: TaskItem, kind: str) -> str:
        return "\n".join([
            f"# {task.title}",
            "",
            f"**Goal:** {goal.title}  ·  **Kind:** {kind}",
            "",
            "## Objective", task.description or "(planning step)", "",
            "## Required evidence",
            *([f"- {e}" for e in task.required_evidence] or ["- (none)"]),
            "",
            "_Planning artifact only. No tool was run, no external system was written,",
            "and no evidence was fabricated. Findings require provided evidence._",
        ])

    def _next_recommended(self, goal_id, tasks, open_questions, evidence_needed, selected) -> str | None:
        # A failed task needs human review before the goal can be called finishable.
        if selected is None and any(t.status is TaskStatus.failed for t in tasks):
            return "Review the failed task(s) before continuing"
        if open_questions:
            return "Answer the open clarification questions"
        if selected is not None and selected.required_evidence and \
                any(e in evidence_needed for e in selected.required_evidence):
            return f"Provide evidence for: {selected.title}"
        if selected is not None and selected.approval_required:
            return f"Approve: {selected.title}"
        if selected is not None:
            return f"Execute next step: {selected.title}"
        if any(t.status is TaskStatus.awaiting_approval for t in tasks):
            return "Approve the pending task to finish the goal"
        return "Goal complete — no further actionable steps"

    def _no_action_message(self, goal_id: str, reason: str) -> str:
        return {
            "goal_complete": "No actionable task: the goal's work is complete.",
            "awaiting_human_approval": "No actionable task: awaiting human approval on the final gate.",
            "tasks_waiting_on_dependencies": "No actionable task: remaining tasks are waiting on dependencies.",
            "failed_tasks_need_review": (
                "No actionable task: one or more tasks failed and need human review before "
                "the goal can proceed."
            ),
        }.get(reason, "No actionable task at this time.")

    def _record(
        self, goal: GoalIntake, *, task: TaskItem | None, outcome: ExecutionOutcome,
        selected_action: str, reason: str, status_after, safe_message: str,
        status_before: str | None = None, produced_artifact: str | None = None,
        approval_required: bool = False, evidence_status: str | None = None,
        clarification_id: str | None = None, deliverable_kind: str | None = None,
        actor: str = "aria",
    ) -> ExecutionStep:
        """Persist task-status change + execution step + workspace update, then emit
        the ledger events. ``safe_message``/``reason`` are sanitised at the store."""
        status_after_value = status_after.value if isinstance(status_after, TaskStatus) else status_after
        # Update the task's planning status (skip for no_actionable_task / no task).
        if task is not None and status_after is not None and status_after.value != task.status.value:
            self._store.update_task_status(task.task_id, status_after, actor=actor)

        step = ExecutionStep(
            step_id=f"step-{uuid.uuid4().hex}", goal_id=goal.goal_id,
            task_id=task.task_id if task else None, workspace_id=goal.workspace_id,
            selected_action=selected_action, reason=sanitize_text(reason) or "",
            required_evidence=list(task.required_evidence) if task else [],
            approval_required=approval_required or (task.approval_required if task else False),
            produced_artifact=produced_artifact, status_before=status_before,
            status_after=status_after_value, outcome=outcome,
            safe_user_message=sanitize_text(safe_message) or "", created_at=_now(),
        )
        self._store.record_execution_step(step, actor=actor, evidence_status=evidence_status)
        self._update_workspace(goal, step, clarification_id=clarification_id,
                              deliverable_kind=deliverable_kind, actor=actor)
        return step

    def _update_workspace(self, goal, step, *, clarification_id, deliverable_kind, actor):
        ws = self._workspace_store
        if ws is None or not goal.workspace_id:
            return
        ledger_refs = [f"step:{step.step_id}"]
        if clarification_id:
            ledger_refs.append(f"clarification:{clarification_id}")
        if deliverable_kind:
            ledger_refs.append(f"deliverable:{deliverable_kind}")
        artifact_refs = [step.produced_artifact] if step.produced_artifact else None
        ws.update_workspace(
            goal.workspace_id, status=f"exec:{step.outcome.value}",
            add_artifact_refs=artifact_refs, add_ledger_refs=ledger_refs,
            final_outcome=step.safe_user_message, actor=actor,
        )
