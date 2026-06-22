"""
V3.3 — Dynamic Agent Workforce (DRY-RUN / fixture-first) tests.

Covers the workforce planner, the agent brief/assignment registry, the deterministic
dry-run executor (evidence + approval gates), the result merger, supervision /
kill-switch, workspace integration, Work Ledger agent events, and safety boundaries.
DRY-RUN ONLY — no real agent process, no network, no external write.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aria.goals import (
    AgentStatus,
    AgentWorkforceService,
    GoalService,
    GoalStore,
)
from aria.goals.agents import _FORBIDDEN_WRITE_TOOLS, _READONLY_TOOLS
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir, workspace_artifact_dir
from aria.memory_v2.workspace import WorkspaceStore

_CTR = "Our notification CTR is dropping. Own this."


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v33_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    store = GoalStore(writer=writer, execution_mode="offline_mock")
    ws = WorkspaceStore(writer=writer, execution_mode="offline_mock")
    gsvc = GoalService(store, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    aw = AgentWorkforceService(store, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    return store, ws, gsvc, aw


def _planned_goal(gsvc, aw, scope="analytics.notifications", req=_CTR):
    plan = gsvc.own_goal(req, scope=scope)
    ap = aw.plan(plan.goal.goal_id)
    return plan, ap


def _event_types(writer: LedgerWriter) -> list[str]:
    if not writer.path.exists():
        return []
    return [json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()]


def _all_evidence(briefs) -> list[str]:
    return sorted({e for b in briefs for e in b.required_inputs})


# ── 1. Planner ────────────────────────────────────────────────────────────────


class TestPlanner:
    def test_goal_creates_relevant_specialist_briefs(self, env):
        store, ws, gsvc, aw = env
        _, ap = _planned_goal(gsvc, aw)
        names = {b.name for b in ap.briefs}
        for expected in ("Data Freshness Agent", "Event Taxonomy Agent",
                         "Recommendation Analyst Agent", "Manager Summary Agent"):
            assert expected in names

    def test_vague_goal_produces_bounded_agents(self, env):
        store, ws, gsvc, aw = env
        _, ap = _planned_goal(gsvc, aw, scope="general", req="Please look into this thing. Own it.")
        assert 1 <= len(ap.briefs) <= 8           # bounded — not an unbounded swarm

    def test_each_brief_has_objective_context_tools_limits_schema(self, env):
        store, ws, gsvc, aw = env
        _, ap = _planned_goal(gsvc, aw)
        for b in ap.briefs:
            assert b.objective.strip()
            assert b.allowed_context and b.forbidden_context
            assert b.expected_output_schema
            assert b.time_limit_seconds > 0 and b.cost_limit_units > 0
            assert b.risk_level == "low"

    def test_no_forbidden_tools_and_no_write_capability(self, env):
        store, ws, gsvc, aw = env
        _, ap = _planned_goal(gsvc, aw)
        writes = set(_FORBIDDEN_WRITE_TOOLS)
        for b in ap.briefs:
            assert set(b.allowed_tools).issubset(set(_READONLY_TOOLS))
            assert set(b.allowed_tools).isdisjoint(writes)        # no live write capability
            assert writes.issubset(set(b.forbidden_tools))        # writes explicitly forbidden

    def test_plan_is_idempotent(self, env, writer):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        ap2 = aw.plan(gid)                                        # second call — no duplicates
        assert len(ap2.briefs) == len(ap.briefs)
        assert len(store.get_agent_briefs(gid)) == len(ap.briefs)
        assert len(store.get_agent_assignments(gid)) == len(ap.assignments)
        created = sum(1 for t in _event_types(writer) if t == "agent_assignment_created")
        assert created == len(ap.briefs)                         # no duplicate creation events


# ── 2. Assignment registry ────────────────────────────────────────────────────


class TestRegistry:
    def test_assignments_created(self, env):
        store, ws, gsvc, aw = env
        _, ap = _planned_goal(gsvc, aw)
        assert len(ap.assignments) == len(ap.briefs)
        assert all(a.status is AgentStatus.planned for a in ap.assignments)

    def test_status_transitions(self, env):
        store, ws, gsvc, aw = env
        _, ap = _planned_goal(gsvc, aw)
        aid = ap.assignments[0].assignment_id
        store.update_agent_assignment(aid, status=AgentStatus.running)
        assert store.get_agent_assignment(aid).status is AgentStatus.running
        store.update_agent_assignment(aid, status=AgentStatus.completed, output_summary="done")
        assert store.get_agent_assignment(aid).status is AgentStatus.completed

    def test_cancelled_does_not_appear_completed(self, env):
        store, ws, gsvc, aw = env
        _, ap = _planned_goal(gsvc, aw)
        a = aw.cancel_assignment(ap.assignments[0].assignment_id, reason="x", killed=True)
        assert a.status is AgentStatus.killed
        assert a.has_findings is False

    def test_restart_safe_retrieval(self, env, writer):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        store.close()
        store2 = GoalStore(writer=writer, execution_mode="offline_mock")
        assert len(store2.get_agent_briefs(gid)) == len(ap.briefs)
        assert len(store2.get_agent_assignments(gid)) == len(ap.assignments)


# ── 3. Dry-run executor ───────────────────────────────────────────────────────


class TestDryRun:
    def test_completes_deterministically_with_evidence(self, env):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        store.provide_evidence(gid, _all_evidence(ap.briefs))
        merged = aw.run_dry(gid)
        assert merged.completed_assignments >= 1
        assert merged.key_findings

    def test_blocked_for_evidence(self, env):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        merged = aw.run_dry(plan.goal.goal_id)            # no evidence provided
        assert merged.blocked_assignments >= 1
        assert any("blocked_for_evidence" in r or "evidence" in r.lower()
                   for r in merged.blocked_reasons)

    def test_blocked_for_approval_does_not_run(self, env):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        store.provide_evidence(gid, _all_evidence(ap.briefs))
        aw.run_dry(gid)
        approval = [a for a in store.get_agent_assignments(gid) if a.approval_required][0]
        assert approval.status is AgentStatus.blocked
        assert approval.failure_reason == "blocked_for_approval"
        assert approval.output_artifact is None           # produced NO findings

    def test_failed_dry_run_redacts_exception(self, env, monkeypatch):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        store.provide_evidence(gid, _all_evidence(ap.briefs))

        def _boom(*a, **k):
            raise ValueError("leak sk-ant-api03-ABCDEF1234567890abcdefXYZ")

        monkeypatch.setattr(aw, "_dry_execute", _boom)
        aw.run_dry(gid)
        failed = [a for a in store.get_agent_assignments(gid) if a.status is AgentStatus.failed]
        assert failed
        assert all("sk-ant" not in (a.failure_reason or "") for a in failed)
        assert all("ValueError" in (a.failure_reason or "") for a in failed)

    def test_blocked_for_evidence_recovers_after_evidence(self, env):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        m1 = aw.run_dry(gid)                                      # no evidence → blocked
        assert m1.blocked_assignments >= 1
        store.provide_evidence(gid, _all_evidence(ap.briefs))     # supply evidence
        m2 = aw.run_dry(gid)                                      # re-run
        assert m2.completed_assignments > m1.completed_assignments
        # evidence-blocked agents recovered; approval-gated stays blocked
        assigns = store.get_agent_assignments(gid)
        assert not [a for a in assigns
                    if a.status is AgentStatus.blocked and a.failure_reason == "blocked_for_evidence"]
        approval = [a for a in assigns if a.approval_required][0]
        assert approval.status is AgentStatus.blocked
        assert approval.failure_reason == "blocked_for_approval"

    def test_artifact_write_failure_is_safe(self, env, writer, monkeypatch):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        store.provide_evidence(gid, _all_evidence(ap.briefs))

        def _boom(*a, **k):
            raise RuntimeError("workspace failure with password=SECRETXYZ123")

        monkeypatch.setattr(ws, "write_artifact", _boom)
        merged = aw.run_dry(gid)                                  # must NOT raise
        assigns = store.get_agent_assignments(gid)
        assert not any(a.status is AgentStatus.running for a in assigns)   # never stuck running
        failed = [a for a in assigns if a.status is AgentStatus.failed]
        assert failed
        assert all("RuntimeError" in (a.failure_reason or "") for a in failed)
        assert all("SECRETXYZ123" not in (a.failure_reason or "") for a in failed)
        # No raw secret in SQLite / ledger / API-shaped merge result
        blob = (store.db_path.read_bytes().decode("utf-8", "ignore")
                + writer.path.read_text(encoding="utf-8") + merged.model_dump_json())
        assert "SECRETXYZ123" not in blob

    def test_only_agent_events_no_connector_or_external(self, env, writer):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        store.provide_evidence(plan.goal.goal_id, _all_evidence(ap.briefs))
        aw.run_dry(plan.goal.goal_id)
        types = set(_event_types(writer))
        forbidden = {"read_only_connector_invoked", "pilot_report_created", "draft_action_created",
                     "jira_created", "teams_sent", "pr_comment_posted", "deployment"}
        assert forbidden.isdisjoint(types)


# ── 4. Result merger ──────────────────────────────────────────────────────────


class TestMerger:
    def test_completed_outputs_merge(self, env):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        store.provide_evidence(gid, _all_evidence(ap.briefs))
        merged = aw.run_dry(gid)
        assert len(merged.key_findings) == merged.completed_assignments
        assert merged.evidence_refs
        assert merged.memory_citations
        assert merged.deliverables
        assert "no external writes" in merged.boundary_note.lower()
        assert merged.draft_actions == []                 # draft-only boundary, none auto-created

    def test_blocked_agents_appear_and_findings_not_invented(self, env):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        merged = aw.run_dry(plan.goal.goal_id)            # no evidence → mostly blocked
        assert merged.blocked_assignments >= 1
        assert merged.blocked_reasons
        # findings count never exceeds completed agents (nothing invented for blocked)
        assert len(merged.key_findings) == merged.completed_assignments


# ── 5. Workspace ──────────────────────────────────────────────────────────────


class TestWorkspace:
    def test_plan_and_merge_attached_to_workspace(self, env):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        wsrow = ws.get_workspace(plan.workspace_id)
        assert any(r.startswith("agent_brief:") for r in wsrow.ledger_refs)
        assert any(r.startswith("agent_assignment:") for r in wsrow.ledger_refs)
        store.provide_evidence(gid, _all_evidence(ap.briefs))
        aw.run_dry(gid)
        wsrow = ws.get_workspace(plan.workspace_id)
        assert any(r.startswith("agent_merge:") for r in wsrow.ledger_refs)
        assert wsrow.artifact_refs                        # agent findings artifacts

    def test_path_confined_and_no_source_writes(self, env):
        store, ws, gsvc, aw = env
        _planned_goal(gsvc, aw)
        assert str(store.db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "goals"
        assert not list(source_pkg.glob("*.sqlite"))


# ── 6. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_agent_events_emitted(self, env, writer):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        store.provide_evidence(plan.goal.goal_id, _all_evidence(ap.briefs))
        aw.run_dry(plan.goal.goal_id)
        types = set(_event_types(writer))
        for expected in (
            "agent_workforce_planned", "agent_assignment_created", "agent_assignment_started",
            "agent_assignment_completed", "agent_assignment_blocked", "agent_result_merged",
        ):
            assert expected in types, f"missing ledger event: {expected}"

    def test_cancel_emits_event_and_legacy_compatibility(self, env, writer):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        aw.cancel_assignment(ap.assignments[0].assignment_id, reason="x")
        assert "agent_assignment_cancelled" in set(_event_types(writer))
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "agent_workforce_planned" for e in v2)
        legacy = writer.path.parent / "legacy.jsonl"
        legacy.write_text(json.dumps({
            "task_id": "legacy-33", "task_type": "pr_review",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }) + "\n", encoding="utf-8")
        recs = LedgerReader(v2_path=writer.path, legacy_task_path=legacy).read_all()
        assert any(getattr(r, "task_id", None) == "legacy-33" for r in recs)


# ── 7. Safety ─────────────────────────────────────────────────────────────────


class TestSafety:
    def test_approval_required_agent_never_runs(self, env):
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        store.provide_evidence(gid, _all_evidence(ap.briefs))
        aw.run_dry(gid)
        approval = [a for a in store.get_agent_assignments(gid) if a.approval_required][0]
        assert approval.status is AgentStatus.blocked and approval.output_artifact is None

    def test_secrets_redacted_across_surfaces(self, env, writer):
        store, ws, gsvc, aw = env
        # Secret in the goal request — sanitised at intake; must not reach agents either.
        plan = gsvc.own_goal(
            "CTR dropping. password=TOPSECRET123 own this. token=LEAKED9999", scope="analytics")
        gid = plan.goal.goal_id
        ap = aw.plan(gid)
        store.provide_evidence(gid, _all_evidence(ap.briefs))
        aw.run_dry(gid)
        # Also force a secret into an assignment output directly.
        a0 = store.get_agent_assignments(gid)[0]
        store.update_agent_assignment(a0.assignment_id, status=AgentStatus.completed,
                                      output_summary="leak password=TOPSECRET123")
        secrets = ["TOPSECRET123", "LEAKED9999"]
        art = "".join(p.read_text(encoding="utf-8")
                      for p in workspace_artifact_dir(plan.workspace_id).glob("*")) \
            if plan.workspace_id else ""
        blob = (store.db_path.read_bytes().decode("utf-8", "ignore")
                + writer.path.read_text(encoding="utf-8") + art)
        assert not any(s in blob for s in secrets)

    def test_aria_user_id_is_not_authorization(self, env, monkeypatch):
        monkeypatch.setenv("ARIA_USER_ID", "human:admin")
        store, ws, gsvc, aw = env
        plan, ap = _planned_goal(gsvc, aw)
        gid = plan.goal.goal_id
        store.provide_evidence(gid, _all_evidence(ap.briefs))
        aw.run_dry(gid, actor="human:admin")
        approval = [a for a in store.get_agent_assignments(gid) if a.approval_required][0]
        assert approval.status is AgentStatus.blocked     # actor label did not authorise it


# ── 8. API ────────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


class TestApi:
    def _goal(self, client) -> str:
        return client.post("/api/v3/goals", json={"raw_request": _CTR}).json()["goal"]["goal_id"]

    def test_plan_run_list_summary(self, client):
        gid = self._goal(client)
        plan = client.post(f"/api/v3/goals/{gid}/agents/plan")
        assert plan.status_code == 201 and plan.json()["count"] >= 1
        # provide evidence so some agents complete
        briefs = plan.json()["briefs"]
        evidence = sorted({e for b in briefs for e in b["required_inputs"]})
        client.post(f"/api/v3/goals/{gid}/evidence", json={"evidence_refs": evidence or ["x"]})
        run = client.post(f"/api/v3/goals/{gid}/agents/run-dry")
        assert run.status_code == 200
        assert run.json()["agents_run"] >= 1
        assert client.get(f"/api/v3/goals/{gid}/agents").status_code == 200
        assert client.get(f"/api/v3/goals/{gid}/agents/summary").status_code == 200

    def test_cancel_endpoint(self, client):
        gid = self._goal(client)
        plan = client.post(f"/api/v3/goals/{gid}/agents/plan").json()
        aid = plan["assignments"][0]["assignment_id"]
        r = client.post(f"/api/v3/goals/{gid}/agents/{aid}/cancel",
                        json={"reason": "not needed", "killed": True})
        assert r.status_code == 200 and r.json()["status"] == "killed"

    def test_safe_errors(self, client):
        assert client.post("/api/v3/goals/goal-missing/agents/plan").status_code == 404
        assert client.post("/api/v3/goals/goal-missing/agents/run-dry").status_code == 404
        gid = self._goal(client)
        r = client.post(f"/api/v3/goals/{gid}/agents/assign-missing/cancel", json={})
        assert r.status_code == 404 and r.json()["error_code"] == "assignment_not_found"
