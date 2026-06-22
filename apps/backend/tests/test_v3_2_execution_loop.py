"""
V3.2 — Work Execution Loop + Progress Tracking tests.

Covers the governed one-step-at-a-time execution loop: next-action selection,
clarification/evidence/approval gates, completed steps producing planning
artifacts, safe failure, progress reporting, workspace integration, Work Ledger
execution events, and safety boundaries. PLANNING ONLY — nothing executes a tool
or writes externally.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aria.goals import (
    ExecutionService,
    GoalService,
    GoalStore,
)
from aria.goals.models import (
    ExecutionOutcome,
    GoalIntake,
    GoalStatus,
    OwnerType,
    Priority,
    TaskItem,
    TaskStatus,
)
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir
from aria.memory_v2.workspace import WorkspaceStore

_CTR = "Our notification CTR is dropping. Own this."


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v32_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    store = GoalStore(writer=writer, execution_mode="offline_mock")
    ws = WorkspaceStore(writer=writer, execution_mode="offline_mock")
    gsvc = GoalService(store, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    ex = ExecutionService(store, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    return store, ws, gsvc, ex


def _event_types(writer: LedgerWriter) -> list[str]:
    if not writer.path.exists():
        return []
    return [json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()]


def _bare_goal(store: GoalStore, *, clarifying=None, scope="general") -> GoalIntake:
    """A persisted goal with NO clarifying questions (so the clarification gate is
    off) — lets us exercise the selector / evidence / approval branches directly."""
    now = datetime.now(UTC)
    intake = GoalIntake(
        goal_id=f"goal-{datetime.now(UTC).timestamp()}".replace(".", ""),
        title="bare goal", raw_request="bare", problem_statement="ps", goal="g",
        clarifying_questions=clarifying or [], scope=scope, status=GoalStatus.planned,
        created_at=now, updated_at=now,
    )
    return store.create_goal(intake)


def _task(goal_id, title, *, priority=Priority.medium, evidence=None, approval=False,
          owner=OwnerType.aria, blocked_by=None) -> TaskItem:
    now = datetime.now(UTC)
    import uuid
    return TaskItem(
        task_id=f"taskitem-{uuid.uuid4().hex}", goal_id=goal_id, title=title,
        description=title, priority=priority, owner_type=owner,
        required_evidence=evidence or [], approval_required=approval,
        blocked_by=blocked_by or [], created_at=now, updated_at=now,
    )


# ── 1. Execution loop ─────────────────────────────────────────────────────────


class TestExecutionLoop:
    def test_selects_highest_priority_actionable_task(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t_low = _task(goal.goal_id, "low task", priority=Priority.low)
        t_high = _task(goal.goal_id, "high task", priority=Priority.high)
        t_med = _task(goal.goal_id, "med task", priority=Priority.medium)
        store.create_tasks([t_low, t_high, t_med])
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.completed_step
        assert step.task_id == t_high.task_id

    def test_unmet_dependency_is_not_executed(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t_low = _task(goal.goal_id, "prereq", priority=Priority.low)
        t_high = _task(goal.goal_id, "dependent", priority=Priority.high,
                       blocked_by=[t_low.task_id])
        store.create_tasks([t_low, t_high])
        step = ex.execute_next(goal.goal_id)
        # The high-priority task is blocked by an incomplete prereq → prereq runs.
        assert step.task_id == t_low.task_id

    def test_approval_required_becomes_awaiting_approval(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        gate = _task(goal.goal_id, "Approve plan", approval=True, owner=OwnerType.human,
                     priority=Priority.high)
        store.create_tasks([gate])
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.blocked_for_approval
        assert store.get_task(gate.task_id).status is TaskStatus.awaiting_approval

    def test_missing_evidence_creates_needs_evidence(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t = _task(goal.goal_id, "Validate trend", evidence=["metric time series"])
        store.create_tasks([t])
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.blocked_for_evidence
        assert store.get_task(t.task_id).status is TaskStatus.needs_evidence

    def test_missing_clarification_creates_request(self, env):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR, scope="analytics.notifications")
        step = ex.execute_next(plan.goal.goal_id)
        assert step.outcome is ExecutionOutcome.blocked_for_clarification
        assert "Questions:" in step.safe_user_message
        assert store.list_clarifications(plan.goal.goal_id, status="open")

    def test_completed_step_updates_task_status(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t = _task(goal.goal_id, "Draft action plan")   # no evidence, no clarification
        store.create_tasks([t])
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.completed_step
        assert store.get_task(t.task_id).status is TaskStatus.completed

    def test_failed_step_redacts_exception_text(self, env, monkeypatch):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t = _task(goal.goal_id, "Draft action plan")
        store.create_tasks([t])

        def _boom(*a, **k):
            raise ValueError("leak sk-ant-api03-ABCDEF1234567890abcdefXYZ")

        monkeypatch.setattr(ex, "_produce_deliverable", _boom)
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.failed_safely
        assert store.get_task(t.task_id).status is TaskStatus.failed
        assert "sk-ant" not in step.safe_user_message       # raw secret not surfaced
        assert "leak" not in step.safe_user_message          # raw message not surfaced
        assert "ValueError" in step.safe_user_message        # class only is fine

    def test_no_actionable_task_returns_safe_summary(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t = _task(goal.goal_id, "Draft action plan")
        store.create_tasks([t])
        ex.execute_next(goal.goal_id)                        # completes the only task
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.no_actionable_task
        assert step.safe_user_message
        assert step.task_id is None


# ── 2. Progress ───────────────────────────────────────────────────────────────


class TestProgress:
    def test_report_shows_task_counts(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t1 = _task(goal.goal_id, "Draft action plan")
        t2 = _task(goal.goal_id, "Prepare manager summary")
        store.create_tasks([t1, t2])
        ex.execute_next(goal.goal_id)                        # complete one
        prog = ex.progress_report(goal.goal_id)
        assert prog.completed_tasks == 1
        assert prog.completed_tasks + prog.in_progress_tasks + prog.blocked_tasks <= 2

    def test_report_does_not_invent_completion(self, env):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        prog = ex.progress_report(plan.goal.goal_id)
        assert prog.completed_tasks == 0                     # nothing executed yet

    def test_blocker_appears_in_report(self, env):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        ex.execute_next(plan.goal.goal_id)                   # blocks for clarification
        prog = ex.progress_report(plan.goal.goal_id)
        assert prog.open_clarifications or prog.blocked_tasks >= 1

    def test_pending_approval_appears_in_report(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        gate = _task(goal.goal_id, "Approve plan", approval=True, owner=OwnerType.human)
        store.create_tasks([gate])
        ex.execute_next(goal.goal_id)                        # → awaiting_approval
        prog = ex.progress_report(goal.goal_id)
        assert prog.pending_approvals >= 1

    def test_deliverable_reference_appears_in_report(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        store.create_tasks([_task(goal.goal_id, "Draft action plan")])
        ex.execute_next(goal.goal_id)
        prog = ex.progress_report(goal.goal_id)
        assert prog.artifacts_created


# ── 3. Workspace ──────────────────────────────────────────────────────────────


class TestWorkspace:
    def test_step_updates_workspace_metadata(self, env):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        step = ex.execute_next(plan.goal.goal_id)
        wsrow = ws.get_workspace(plan.workspace_id)
        assert any(r == f"step:{step.step_id}" for r in wsrow.ledger_refs)

    def test_clarification_stored_and_referenced(self, env):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        ex.execute_next(plan.goal.goal_id)
        clars = store.list_clarifications(plan.goal.goal_id)
        assert clars and clars[0].status == "open"
        wsrow = ws.get_workspace(plan.workspace_id)
        assert any(r.startswith("clarification:") for r in wsrow.ledger_refs)

    def test_deliverable_tracked(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        store.create_tasks([_task(goal.goal_id, "Draft action plan")])
        ex.execute_next(goal.goal_id)
        assert store.list_deliverables(goal.goal_id)

    def test_path_confined_and_no_source_writes(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        store.create_tasks([_task(goal.goal_id, "Draft action plan")])
        ex.execute_next(goal.goal_id)
        assert str(store.db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "goals"
        assert not list(source_pkg.glob("*.sqlite"))

    def test_restart_safe_retrieval(self, env, writer):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        ex.execute_next(plan.goal.goal_id)
        gid = plan.goal.goal_id
        store.close()
        store2 = GoalStore(writer=writer, execution_mode="offline_mock")
        assert store2.get_execution_steps(gid)
        assert store2.list_clarifications(gid)


# ── 4. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_execution_events_emitted(self, env, writer):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        gid = plan.goal.goal_id
        ex.execute_next(gid)                                 # clarification block
        ex.submit_clarification(gid, {"date_range": "7d", "platform": "app"})
        s = ex.execute_next(gid)                             # evidence block
        ex.provide_evidence(gid, s.required_evidence)
        ex.execute_next(gid)                                 # completed step
        ex.progress_report(gid)
        types = set(_event_types(writer))
        for expected in (
            "work_step_started", "work_step_completed", "work_step_blocked",
            "clarification_requested", "progress_report_created", "deliverable_tracked",
        ):
            assert expected in types, f"missing ledger event: {expected}"

    def test_legacy_ledger_compatibility_preserved(self, env, writer):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        ex.execute_next(plan.goal.goal_id)
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "work_step_blocked" for e in v2)
        legacy = writer.path.parent / "legacy.jsonl"
        legacy.write_text(json.dumps({
            "task_id": "legacy-9", "task_type": "pr_review",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }) + "\n", encoding="utf-8")
        recs = LedgerReader(v2_path=writer.path, legacy_task_path=legacy).read_all()
        assert any(getattr(r, "task_id", None) == "legacy-9" for r in recs)


# ── 5. Safety ─────────────────────────────────────────────────────────────────


class TestSafety:
    def test_no_external_or_connector_events(self, env, writer):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        gid = plan.goal.goal_id
        ex.execute_next(gid)
        ex.submit_clarification(gid, {"q": "a"})
        s = ex.execute_next(gid)
        if s.required_evidence:
            ex.provide_evidence(gid, s.required_evidence)
            ex.execute_next(gid)
        types = set(_event_types(writer))
        forbidden = {
            "read_only_connector_invoked", "pilot_report_created", "draft_action_created",
            "jira_created", "teams_sent", "pr_comment_posted", "deployment",
        }
        assert forbidden.isdisjoint(types)

    def test_memory_does_not_bypass_evidence_gate(self, env):
        # An evidence-requiring task stays blocked even though the loop never
        # consults memory — memory definitions can't satisfy the evidence gate.
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t = _task(goal.goal_id, "Validate trend", evidence=["metric series"])
        store.create_tasks([t])
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.blocked_for_evidence

    def test_secrets_redacted_in_step_and_artifact(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        # A task whose title carries a secret (defence in depth).
        store.create_tasks([_task(goal.goal_id, "Draft password=TOP_SECRET_TOKEN plan")])
        step = ex.execute_next(goal.goal_id)
        assert "TOP_SECRET_TOKEN" not in step.safe_user_message
        # artifact bytes are clean too
        from aria.memory_v2.paths import workspace_artifact_dir
        art = "".join(p.read_text(encoding="utf-8")
                      for p in workspace_artifact_dir(goal.workspace_id).glob("*")) \
            if goal.workspace_id else ""
        assert "TOP_SECRET_TOKEN" not in art
        # ledger is clean
        assert "TOP_SECRET_TOKEN" not in store.db_path.read_bytes().decode("utf-8", "ignore")

    def test_aria_user_id_is_not_authorization(self, env, monkeypatch):
        # An actor label must NOT auto-approve an approval-required task.
        monkeypatch.setenv("ARIA_USER_ID", "human:admin")
        store, ws, _, ex = env
        goal = _bare_goal(store)
        gate = _task(goal.goal_id, "Approve plan", approval=True, owner=OwnerType.human)
        store.create_tasks([gate])
        step = ex.execute_next(goal.goal_id, actor="human:admin")
        assert step.outcome is ExecutionOutcome.blocked_for_approval   # not auto-approved


# ── 5b. Failed work must not look finishable (P1) ─────────────────────────────


class TestFailedWork:
    def test_failed_work_does_not_make_gate_actionable(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        wt = _task(goal.goal_id, "work")
        gate = _task(goal.goal_id, "Approve plan", approval=True, owner=OwnerType.human,
                     priority=Priority.high)
        store.create_tasks([wt, gate])
        store.update_task_status(wt.task_id, TaskStatus.failed)
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.no_actionable_task
        assert store.get_task(gate.task_id).status is TaskStatus.planned   # NOT awaiting_approval

    def test_progress_says_failed_needs_review_not_approve(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        wt = _task(goal.goal_id, "work")
        gate = _task(goal.goal_id, "Approve plan", approval=True, owner=OwnerType.human)
        store.create_tasks([wt, gate])
        store.update_task_status(wt.task_id, TaskStatus.failed)
        prog = ex.progress_report(goal.goal_id)
        assert prog.pending_approvals == 0
        assert "review" in (prog.next_recommended_action or "").lower()
        assert "approve" not in (prog.next_recommended_action or "").lower()

    def test_all_failed_work_is_not_goal_complete(self, env):
        store, ws, _, ex = env
        goal = _bare_goal(store)
        t = _task(goal.goal_id, "only work")
        store.create_tasks([t])
        store.update_task_status(t.task_id, TaskStatus.failed)
        step = ex.execute_next(goal.goal_id)
        assert step.outcome is ExecutionOutcome.no_actionable_task
        assert "review" in step.safe_user_message.lower()
        assert "complete" not in step.safe_user_message.lower()


# ── 5c. Evidence / clarification audit (P1) ───────────────────────────────────


class _FailingWriter:
    """A writer whose append always fails — to prove the outbox retains audit."""
    def append(self, _event):  # noqa: D401
        raise OSError("ledger unavailable")

    def __len__(self):
        return 0


class TestEvidenceClarificationAudit:
    def test_evidence_provision_emits_audit_event(self, env, writer):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        store.provide_evidence(plan.goal.goal_id, ["metric-series"], provided_by="human:analyst")
        events = [json.loads(l) for l in writer.path.read_text(encoding="utf-8").splitlines()]
        ev = [e for e in events if e["event_type"] == "evidence_provided"]
        assert ev, "evidence_provided event missing"
        meta = ev[-1]["metadata"]
        assert meta["goal_id"] == plan.goal.goal_id
        assert "metric-series" in meta["evidence_refs"]
        assert ev[-1]["actor"] == "human:analyst"

    def test_clarification_answer_emits_audit_event(self, env, writer):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        ex.execute_next(plan.goal.goal_id)            # creates an open clarification
        clar = store.list_clarifications(plan.goal.goal_id, status="open")[0]
        store.answer_clarification(clar.clarification_id, {"platform": "app"}, actor="human:lead")
        events = [json.loads(l) for l in writer.path.read_text(encoding="utf-8").splitlines()]
        ans = [e for e in events if e["event_type"] == "clarification_answered"]
        assert ans, "clarification_answered event missing"
        assert ans[-1]["metadata"]["clarification_id"] == clar.clarification_id
        assert ans[-1]["actor"] == "human:lead"

    def test_writer_failure_keeps_state_and_queues_audit(self, tmp_path):
        """On ledger write failure, state commits and the audit event stays durably
        queued; a later flush drains it (no divergence)."""
        store = GoalStore(writer=_FailingWriter(), execution_mode="offline_mock")
        goal = _bare_goal(store)
        store.provide_evidence(goal.goal_id, ["series"], provided_by="human:a")
        # State committed despite the writer being down:
        assert "series" in store.list_evidence(goal.goal_id)
        # Audit event durably queued for recovery:
        assert store.pending_audit_count() >= 1
        # Recovery flush to a working writer drains the queue, in order:
        good = LedgerWriter(tmp_path / "recover.jsonl")
        store.flush_outbox(good)
        assert store.pending_audit_count() == 0
        types = [json.loads(l)["event_type"] for l in good.path.read_text(encoding="utf-8").splitlines()]
        assert "evidence_provided" in types

    def test_recovery_flush_orders_evidence_before_next_completed_step(self, tmp_path):
        store = GoalStore(writer=_FailingWriter(), execution_mode="offline_mock")
        ex = ExecutionService(store, execution_mode="offline_mock", actor="human:t")
        goal = _bare_goal(store)
        t = _task(goal.goal_id, "Validate trend", evidence=["series"])
        store.create_tasks([t])
        store.provide_evidence(goal.goal_id, ["series"], provided_by="human:a")
        ex.execute_next(goal.goal_id)                 # now completes (evidence present)
        good = LedgerWriter(tmp_path / "ordered.jsonl")
        store.flush_outbox(good)
        types = [json.loads(l)["event_type"] for l in good.path.read_text(encoding="utf-8").splitlines()]
        assert "evidence_provided" in types and "work_step_completed" in types
        assert types.index("evidence_provided") < types.index("work_step_completed")

    def test_secret_bearing_evidence_and_answers_do_not_leak(self, env, writer):
        store, ws, gsvc, ex = env
        plan = gsvc.own_goal(_CTR)
        gid = plan.goal.goal_id
        ex.execute_next(gid)
        clar = store.list_clarifications(gid, status="open")[0]
        store.answer_clarification(clar.clarification_id, {"creds": "password=TOPSECRET123"})
        store.provide_evidence(gid, ["api_key=LEAKEDKEY9999"])
        secrets = ["TOPSECRET123", "LEAKEDKEY9999"]
        blob = (
            store.db_path.read_bytes().decode("utf-8", "ignore")
            + writer.path.read_text(encoding="utf-8")
            + json.dumps([d.model_dump_json() for d in store.list_clarifications(gid)])
            + json.dumps(store.list_evidence(gid))
        )
        assert not any(s in blob for s in secrets), "secret leaked into SQLite/ledger/state"


# ── 6. API ────────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


class TestApi:
    def _create(self, client) -> str:
        return client.post("/api/v3/goals", json={"raw_request": _CTR}).json()["goal"]["goal_id"]

    def test_execute_next_endpoint(self, client):
        gid = self._create(client)
        r = client.post(f"/api/v3/goals/{gid}/execute-next")
        assert r.status_code == 200
        assert r.json()["outcome"] == "blocked_for_clarification"

    def test_clarification_then_evidence_then_progress(self, client):
        gid = self._create(client)
        client.post(f"/api/v3/goals/{gid}/execute-next")
        ans = client.post(f"/api/v3/goals/{gid}/clarifications",
                         json={"answers": {"date_range": "7d", "platform": "app"}})
        assert ans.status_code == 200 and ans.json()["status"] == "answered"
        step = client.post(f"/api/v3/goals/{gid}/execute-next").json()
        if step["required_evidence"]:
            ev = client.post(f"/api/v3/goals/{gid}/evidence",
                            json={"evidence_refs": step["required_evidence"]})
            assert ev.status_code == 200
        prog = client.get(f"/api/v3/goals/{gid}/progress")
        assert prog.status_code == 200
        assert "boundary_note" in prog.json()

    def test_invalid_goal_returns_safe_error(self, client):
        r = client.post("/api/v3/goals/goal-missing/execute-next")
        assert r.status_code == 404 and r.json()["error_code"] == "goal_not_found"
        assert client.get("/api/v3/goals/goal-missing/progress").status_code == 404
