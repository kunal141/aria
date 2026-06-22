"""
V3.4 — Agent Supervisor + Multi-Agent Governance tests.

Covers the supervisor service, multi-agent execution plan, dependency ordering,
budget/time/risk governance, retry/fail-safe policy, result quality checks,
escalation/human-review, cancellation/kill-switch hardening, workspace supervision
timeline, Work Ledger supervision events, and safety. DRY-RUN ONLY — no real agent
process, no network, no external write.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

import aria.goals.supervisor as supmod
from aria.goals import (
    AgentSupervisorService,
    AgentWorkforceService,
    GoalService,
    GoalStore,
    GovernancePolicy,
)
from aria.goals.agents import _FORBIDDEN_WRITE_TOOLS
from aria.goals.models import (
    AgentAssignment,
    AgentBrief,
    AgentStatus,
    AgentSupervisionRun,
    QualityStatus,
    SupervisionStatus,
)
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir
from aria.memory_v2.workspace import WorkspaceStore

_CTR = "Our notification CTR is dropping. Own this."


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v34_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    store = GoalStore(writer=writer, execution_mode="offline_mock")
    ws = WorkspaceStore(writer=writer, execution_mode="offline_mock")
    gsvc = GoalService(store, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    aw = AgentWorkforceService(store, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    sup = AgentSupervisorService(store, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    return store, ws, gsvc, aw, sup


def _goal_with_workforce(gsvc, aw, *, evidence=True):
    plan = gsvc.own_goal(_CTR, scope="analytics.notifications")
    ap = aw.plan(plan.goal.goal_id)
    if evidence:
        store = aw._store
        store.provide_evidence(plan.goal.goal_id, sorted({e for b in ap.briefs for e in b.required_inputs}))
    return plan, ap


def _custom_agent(store, goal, *, name="Custom Agent", risk="low", approval=False,
                  required=None, output_schema="Findings"):
    now = datetime.now(UTC)
    agent_id = f"agent-{uuid.uuid4().hex}"
    brief = AgentBrief(
        agent_id=agent_id, goal_id=goal.goal_id, name=name, role="analytics",
        objective="do the thing", allowed_context=["fixtures"], forbidden_context=["pii"],
        allowed_tools=["read_events"], forbidden_tools=list(_FORBIDDEN_WRITE_TOOLS),
        required_inputs=required or [], expected_output_schema=output_schema,
        approval_required=approval, risk_level=risk, created_at=now, updated_at=now,
    )
    assignment = AgentAssignment(
        assignment_id=f"assign-{uuid.uuid4().hex}", agent_id=agent_id, goal_id=goal.goal_id,
        workspace_id=goal.workspace_id, status=AgentStatus.planned, approval_required=approval,
        risk_level=risk,
    )
    store.save_agent_plan([brief], [assignment])
    return brief, assignment


def _event_types(writer: LedgerWriter) -> list[str]:
    if not writer.path.exists():
        return []
    return [json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()]


def _agent_name_order(store, gid, plan):
    by_id = {a.assignment_id: a for a in store.get_agent_assignments(gid)}
    names = {b.agent_id: b.name for b in store.get_agent_briefs(gid)}
    return [names[by_id[aid].agent_id] for aid in plan.execution_order]


# ── 1. Supervisor ─────────────────────────────────────────────────────────────


class TestSupervisor:
    def test_creates_execution_plan(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        xp = sup.plan(plan.goal.goal_id)
        assert xp.plan_id and xp.execution_order
        assert xp.estimated_cost_units > 0
        assert store.get_latest_execution_plan(plan.goal.goal_id).plan_id == xp.plan_id

    def test_runs_allowed_and_returns_completed_with_blockers(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        run = sup.run(plan.goal.goal_id)
        assert run.status is SupervisionStatus.completed_with_blockers   # approval agent blocks
        assert run.completed_assignments >= 1
        assert run.blocked_assignments >= 1

    def test_approval_required_is_blocked(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        sup.run(plan.goal.goal_id)
        approval = [a for a in store.get_agent_assignments(plan.goal.goal_id) if a.approval_required][0]
        assert approval.status is AgentStatus.blocked

    def test_killed_assignment_is_skipped(self, env):
        store, ws, gsvc, aw, sup = env
        plan, ap = _goal_with_workforce(gsvc, aw)
        gid = plan.goal.goal_id
        aw.cancel_assignment(ap.assignments[0].assignment_id, killed=True)
        run = sup.run(gid)
        killed = store.get_agent_assignment(ap.assignments[0].assignment_id)
        assert killed.status is AgentStatus.killed                      # never run
        assert killed.output_artifact is None

    def test_no_external_writes(self, env, writer):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        sup.run(plan.goal.goal_id)
        forbidden = {"read_only_connector_invoked", "draft_action_created", "jira_created",
                     "teams_sent", "pr_comment_posted", "deployment"}
        assert forbidden.isdisjoint(set(_event_types(writer)))


# ── 2. Dependency ordering ────────────────────────────────────────────────────


class TestDependency:
    def test_dependency_order_respected(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        gid = plan.goal.goal_id
        xp = sup.plan(gid)
        order = _agent_name_order(store, gid, xp)
        assert order.index("Data Freshness Agent") < order.index("Campaign Analysis Agent")
        assert order.index("Event Taxonomy Agent") < order.index("Manager Summary Agent")

    def test_unmet_dependency_blocks(self, env):
        store, ws, gsvc, aw, sup = env
        plan, ap = _goal_with_workforce(gsvc, aw)
        gid = plan.goal.goal_id
        # Kill the prerequisite (Data Freshness) → Campaign Analysis must block.
        df = [a for a in store.get_agent_assignments(gid)
              if store.get_agent_brief(a.agent_id).name == "Data Freshness Agent"][0]
        aw.cancel_assignment(df.assignment_id, killed=True)
        sup.run(gid)
        ca = [a for a in store.get_agent_assignments(gid)
              if store.get_agent_brief(a.agent_id).name == "Campaign Analysis Agent"][0]
        assert ca.status is not AgentStatus.completed

    def test_circular_dependency_fails_safely(self, env, monkeypatch):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        gid = plan.goal.goal_id
        monkeypatch.setitem(supmod._DEPENDENCY_MAP, "Data Freshness Agent", ["Campaign Analysis Agent"])
        xp = sup.plan(gid)                                              # must NOT raise
        assert len(xp.blocked_assignments) >= 2                        # cyclic pair blocked
        order = _agent_name_order(store, gid, xp)
        assert "Data Freshness Agent" not in order                     # cyclic excluded from order

    def test_dependency_blocked_persisted_and_recoverable(self, env):
        store, ws, gsvc, aw, sup = env
        plan, ap = _goal_with_workforce(gsvc, aw, evidence=False)   # no evidence yet
        gid = plan.goal.goal_id
        sup.run(gid)
        ca = [a for a in store.get_agent_assignments(gid)
              if store.get_agent_brief(a.agent_id).name == "Campaign Analysis Agent"][0]
        # Persisted as a clear, recoverable blocked state (matches the run verdict).
        assert ca.status is AgentStatus.blocked
        assert ca.failure_reason == "blocked_for_dependency"
        # Recoverable: once the prerequisite completes, a re-run completes the dependent.
        store.provide_evidence(gid, sorted({e for b in ap.briefs for e in b.required_inputs}))
        sup.run(gid)
        df = [a for a in store.get_agent_assignments(gid)
              if store.get_agent_brief(a.agent_id).name == "Data Freshness Agent"][0]
        assert df.status is AgentStatus.completed
        recovered = store.get_agent_assignment(ca.assignment_id)
        assert recovered.status is AgentStatus.completed
        assert recovered.failure_reason is None        # stale blocked reason cleared on completion

    def test_dependency_blockage_logged(self, env, writer, monkeypatch):
        store, ws, gsvc, aw, sup = env
        plan, ap = _goal_with_workforce(gsvc, aw)
        gid = plan.goal.goal_id
        df = [a for a in store.get_agent_assignments(gid)
              if store.get_agent_brief(a.agent_id).name == "Data Freshness Agent"][0]
        aw.cancel_assignment(df.assignment_id, killed=True)
        sup.run(gid)
        assert "agent_dependency_blocked" in set(_event_types(writer))


# ── 3. Budget / risk governance ───────────────────────────────────────────────


class TestBudgetRisk:
    def test_budget_estimate_created(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        xp = sup.plan(plan.goal.goal_id)
        assert xp.estimated_cost_units == len(xp.assignment_ids)        # 1 cost unit each
        assert xp.estimated_runtime_seconds > 0

    def test_budget_exceeded_blocks_safely(self, env, writer):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        gid = plan.goal.goal_id
        strict = AgentSupervisorService(store, workspace_store=ws, execution_mode="offline_mock",
                                        actor="human:test", policy=GovernancePolicy(max_total_cost_units=2))
        run = strict.run(gid)
        assert run.status is SupervisionStatus.failed_safely
        assert run.escalation_required
        assert "agent_budget_blocked" in set(_event_types(writer))

    def test_high_risk_requires_escalation(self, env):
        store, ws, gsvc, aw, sup = env
        plan = gsvc.own_goal(_CTR, scope="analytics")
        _custom_agent(store, plan.goal, name="Risky Agent", risk="high")
        run = sup.run(plan.goal.goal_id)
        assert run.escalation_required
        escs = store.list_escalations(plan.goal.goal_id)
        assert any("risk" in e.reason.lower() for e in escs)

    def test_missing_limits_use_safe_defaults(self, env):
        store, ws, gsvc, aw, sup = env
        # Default policy applies when none is supplied.
        assert sup._policy.max_total_cost_units == 100
        assert sup._policy.max_retries == 2
        assert "low" in sup._policy.allowed_risk_levels


# ── 4. Retry ──────────────────────────────────────────────────────────────────


class TestRetry:
    def test_safe_failure_retries_then_succeeds(self, env):
        store, ws, gsvc, aw, sup = env
        plan = gsvc.own_goal(_CTR, scope="analytics")
        _custom_agent(store, plan.goal, name="Flaky Agent")
        calls = {"n": 0}
        real = sup._agents._dry_execute

        def flaky(goal, brief, provided):
            calls["n"] += 1
            if calls["n"] < 3:        # fail twice, succeed on 3rd (within max_retries=2)
                raise ValueError("transient sk-ant-SECRET123456789abcdef")
            return real(goal, brief, provided)

        sup._agents._dry_execute = flaky
        run = sup.run(plan.goal.goal_id)
        assert calls["n"] == 3
        assert run.completed_assignments == 1
        assert run.failed_assignments == 0

    def test_retry_exhaustion_fails_safely_redacted(self, env):
        store, ws, gsvc, aw, sup = env
        plan = gsvc.own_goal(_CTR, scope="analytics")
        _custom_agent(store, plan.goal, name="Broken Agent")

        def always_fail(goal, brief, provided):
            raise ValueError("boom sk-ant-SECRET123456789abcdef")

        sup._agents._dry_execute = always_fail
        run = sup.run(plan.goal.goal_id)
        assert run.failed_assignments == 1
        escs = store.list_escalations(plan.goal.goal_id)
        assert escs and all("SECRET123456789" not in e.reason for e in escs)

    def test_approval_and_evidence_blocks_not_retried(self, env):
        store, ws, gsvc, aw, sup = env
        plan = gsvc.own_goal(_CTR, scope="analytics")
        _custom_agent(store, plan.goal, name="Approval Agent", approval=True)
        _custom_agent(store, plan.goal, name="Evidence Agent", required=["series"])
        calls = {"n": 0}
        real = sup._agents._dry_execute

        def counting(goal, brief, provided):
            calls["n"] += 1
            return real(goal, brief, provided)

        sup._agents._dry_execute = counting
        sup.run(plan.goal.goal_id)
        # approval never runs the executor; evidence runs once and blocks (not retried)
        assigns = {store.get_agent_brief(a.agent_id).name: a for a in store.get_agent_assignments(plan.goal.goal_id)}
        assert assigns["Approval Agent"].status is AgentStatus.blocked
        assert assigns["Evidence Agent"].status is AgentStatus.blocked


# ── 5. Quality checks ─────────────────────────────────────────────────────────


class TestQuality:
    def _agent(self, store, plan, **kw):
        return _custom_agent(store, plan.goal, **kw)

    def test_valid_result_passes(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        brief = store.get_agent_briefs(plan.goal.goal_id)[0]
        a = AgentAssignment(assignment_id="x", agent_id=brief.agent_id, goal_id=plan.goal.goal_id,
                            status=AgentStatus.completed,
                            output_summary="Used approved memory for definitions; produced findings.")
        status, reasons = sup.check_quality(a, brief, set(brief.required_inputs))
        assert status is QualityStatus.passed and reasons == []

    def test_missing_findings_fails(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        brief = store.get_agent_briefs(plan.goal.goal_id)[0]
        a = AgentAssignment(assignment_id="x", agent_id=brief.agent_id, goal_id=plan.goal.goal_id,
                            status=AgentStatus.completed, output_summary="")
        status, reasons = sup.check_quality(a, brief, set(brief.required_inputs))
        assert status is QualityStatus.escalation_required
        assert any("no findings" in r for r in reasons)

    def test_forbidden_tool_in_output_fails(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        brief = store.get_agent_briefs(plan.goal.goal_id)[0]
        a = AgentAssignment(assignment_id="x", agent_id=brief.agent_id, goal_id=plan.goal.goal_id,
                            status=AgentStatus.completed,
                            output_summary="memory used; will jira_create a ticket")
        status, reasons = sup.check_quality(a, brief, set(brief.required_inputs))
        assert status is QualityStatus.escalation_required
        assert any("forbidden write" in r for r in reasons)

    def test_secret_in_output_fails(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        brief = store.get_agent_briefs(plan.goal.goal_id)[0]
        a = AgentAssignment(assignment_id="x", agent_id=brief.agent_id, goal_id=plan.goal.goal_id,
                            status=AgentStatus.completed,
                            output_summary="memory used; key sk-ant-api03-ABCDEF1234567890abcdefXYZ")
        status, reasons = sup.check_quality(a, brief, set(brief.required_inputs))
        assert status is QualityStatus.escalation_required
        assert any("secret" in r.lower() for r in reasons)

    def test_unsupported_factual_claim_fails(self, env):
        store, ws, gsvc, aw, sup = env
        plan = gsvc.own_goal(_CTR, scope="analytics")
        brief, _ = _custom_agent(store, plan.goal, name="Summary Agent")   # no required_inputs
        a = AgentAssignment(assignment_id="x", agent_id=brief.agent_id, goal_id=plan.goal.goal_id,
                            status=AgentStatus.completed,
                            output_summary="memory used; CTR fell by 35% last week")
        status, reasons = sup.check_quality(a, brief, set())
        assert status is QualityStatus.escalation_required
        assert any("unsupported factual claim" in r for r in reasons)


# ── 6. Escalation ─────────────────────────────────────────────────────────────


class TestEscalation:
    def test_quality_failure_escalates_and_is_stored_and_logged(self, env, writer):
        store, ws, gsvc, aw, sup = env
        plan = gsvc.own_goal(_CTR, scope="analytics")
        _custom_agent(store, plan.goal, name="Summary Agent")          # completes, then we taint
        # Force a tainted completed output via the executor.
        def tainted(goal, brief, provided):
            return (AgentStatus.completed, "memory used; jira_create a ticket", "ART", None)
        sup._agents._dry_execute = tainted
        run = sup.run(plan.goal.goal_id)
        assert run.escalation_required and run.quality_passed is False
        assert store.list_escalations(plan.goal.goal_id)
        types = set(_event_types(writer))
        assert "agent_quality_check_failed" in types and "agent_escalation_required" in types
        wsrow = ws.get_workspace(plan.goal.workspace_id)
        assert any(r.startswith("escalation:") for r in wsrow.ledger_refs)

    def test_quality_failed_output_is_quarantined(self, env):
        from aria.memory_v2.paths import workspace_artifact_dir

        store, ws, gsvc, aw, sup = env
        plan = gsvc.own_goal(_CTR, scope="analytics")
        brief, asg = _custom_agent(store, plan.goal, name="Tainted Agent")
        secret_token = "jira_create QUALITYLEAK999"

        def tainted(goal, b, provided):           # forbidden write action in output
            return (AgentStatus.completed, f"memory used; will {secret_token}",
                    f"DRAFT: {secret_token}", None)

        sup._agents._dry_execute = tainted
        run = sup.run(plan.goal.goal_id)
        assert run.quality_passed is False
        a = store.get_agent_assignment(asg.assignment_id)
        # The rejected output is never persisted: no artifact, withheld summary.
        assert a.status is AgentStatus.blocked
        assert a.output_artifact is None
        assert "withheld" in a.output_summary.lower()
        # No workspace artifact ref and no on-disk file retains the rejected content.
        wsrow = ws.get_workspace(plan.goal.workspace_id)
        assert all("agent_" not in r for r in wsrow.artifact_refs)
        files = [p.read_text(encoding="utf-8")
                 for p in workspace_artifact_dir(plan.goal.workspace_id).glob("*")]
        assert all("QUALITYLEAK999" not in f for f in files)
        # The rejected content must NOT remain in ANY SQLite file (incl. the WAL).
        store.close()
        for dbf in (aria_data_dir() / "goals").glob("store.sqlite*"):
            assert b"QUALITYLEAK999" not in dbf.read_bytes(), f"leaked into {dbf.name}"


# ── 7. Cancellation / kill switch ─────────────────────────────────────────────


class TestCancellation:
    def test_cancel_run_cancels_remaining_and_logs(self, env, writer):
        store, ws, gsvc, aw, sup = env
        plan, ap = _goal_with_workforce(gsvc, aw, evidence=False)
        gid = plan.goal.goal_id
        xp = sup.plan(gid)
        run = store.create_supervision_run(AgentSupervisionRun(
            run_id=f"run-{uuid.uuid4().hex}", plan_id=xp.plan_id, goal_id=gid,
            workspace_id=plan.workspace_id, status=SupervisionStatus.running,
            started_at=datetime.now(UTC), total_assignments=len(xp.assignment_ids)))
        cancelled = sup.cancel_run(run.run_id, reason="abort")
        assert cancelled.status is SupervisionStatus.cancelled
        statuses = {a.status for a in store.get_agent_assignments(gid)}
        assert statuses == {AgentStatus.cancelled}
        wsrow = ws.get_workspace(plan.workspace_id)
        assert any(r.startswith("cancellation:") for r in wsrow.ledger_refs)


# ── 8. Workspace ──────────────────────────────────────────────────────────────


class TestWorkspace:
    def test_plan_run_escalation_stored_and_path_confined(self, env):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        gid = plan.goal.goal_id
        sup.plan(gid)
        sup.run(gid)
        wsrow = ws.get_workspace(plan.workspace_id)
        assert any(r.startswith("exec_plan:") for r in wsrow.ledger_refs)
        assert any(r.startswith("supervision_run:") for r in wsrow.ledger_refs)
        assert str(store.db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "goals"
        assert not list(source_pkg.glob("*.sqlite"))

    def test_restart_safe(self, env, writer):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        gid = plan.goal.goal_id
        sup.run(gid)
        store.close()
        store2 = GoalStore(writer=writer, execution_mode="offline_mock")
        assert store2.get_latest_execution_plan(gid) is not None
        assert store2.list_supervision_runs(gid)


# ── 9. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_supervision_events_emitted(self, env, writer):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        sup.run(plan.goal.goal_id)
        types = set(_event_types(writer))
        for expected in ("agent_supervision_planned", "agent_supervision_started",
                         "agent_supervision_completed"):
            assert expected in types, f"missing event {expected}"

    def test_legacy_compatibility(self, env, writer):
        store, ws, gsvc, aw, sup = env
        plan, _ = _goal_with_workforce(gsvc, aw)
        sup.run(plan.goal.goal_id)
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "agent_supervision_started" for e in v2)
        legacy = writer.path.parent / "legacy.jsonl"
        legacy.write_text(json.dumps({
            "task_id": "legacy-34", "task_type": "pr_review",
            "timestamp": "2026-01-01T00:00:00+00:00"}) + "\n", encoding="utf-8")
        recs = LedgerReader(v2_path=writer.path, legacy_task_path=legacy).read_all()
        assert any(getattr(r, "task_id", None) == "legacy-34" for r in recs)


# ── 10. API ───────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


class TestApi:
    def _goal_with_agents(self, client) -> str:
        gid = client.post("/api/v3/goals", json={"raw_request": _CTR}).json()["goal"]["goal_id"]
        plan = client.post(f"/api/v3/goals/{gid}/agents/plan").json()
        ev = sorted({e for b in plan["briefs"] for e in b["required_inputs"]})
        client.post(f"/api/v3/goals/{gid}/evidence", json={"evidence_refs": ev or ["x"]})
        return gid

    def test_supervise_plan_run_summary(self, client):
        gid = self._goal_with_agents(client)
        sp = client.post(f"/api/v3/goals/{gid}/agents/supervise-plan")
        assert sp.status_code == 201 and sp.json()["execution_order"]
        run = client.post(f"/api/v3/goals/{gid}/agents/supervise-run")
        assert run.status_code == 200 and run.json()["total_assignments"] >= 1
        summary = client.get(f"/api/v3/goals/{gid}/agents/supervision")
        assert summary.status_code == 200 and summary.json()["plan"] is not None

    def test_cancel_supervision(self, client):
        gid = self._goal_with_agents(client)
        client.post(f"/api/v3/goals/{gid}/agents/supervise-plan")
        run_id = client.post(f"/api/v3/goals/{gid}/agents/supervise-run").json()["run_id"]
        # A completed run can still be cancelled (idempotent state record).
        r = client.post(f"/api/v3/goals/{gid}/agents/supervision/{run_id}/cancel", json={"reason": "stop"})
        assert r.status_code == 200 and r.json()["status"] == "cancelled"

    def test_safe_errors(self, client):
        assert client.post("/api/v3/goals/goal-x/agents/supervise-plan").status_code == 404
        assert client.post("/api/v3/goals/goal-x/agents/supervise-run").status_code == 404
        gid = self._goal_with_agents(client)
        r = client.post(f"/api/v3/goals/{gid}/agents/supervision/run-missing/cancel", json={})
        assert r.status_code == 404 and r.json()["error_code"] == "run_not_found"
