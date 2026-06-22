"""
V3.10 — Manager Dashboard + ROI + Final V3 Proof tests.

Covers the read-only aggregation of every V3 system into a manager snapshot, the
transparent estimated ROI, the read-only approval queue and risk/blocker views, the
deterministic offline end-to-end V3 proof, store persistence/confinement/secrets, Work
Ledger events, the V3 API, and the read-only / no-live-write safety boundary.

V3.10 is visibility, control, proof, ROI, and acceptance — not more autonomy. Nothing
here executes work, approves anything, activates a skill, or performs an external write.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aria.actions import ActionService, ActionStore, ActionType, TargetSystem
from aria.awareness import AwarenessService, AwarenessStore
from aria.collaboration import CollaborationService, CollaborationStore, DraftType
from aria.dashboard import (
    DashboardIntegrityError,
    DashboardSecurityError,
    DashboardService,
    DashboardStore,
    estimate_roi,
)
from aria.dashboard.models import ActionSummary, ManagerDashboardSnapshot, ROISummary
from aria.goals import (
    AgentSupervisorService,
    AgentWorkforceService,
    GoalService,
    GoalStore,
)
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir
from aria.memory_v2.workspace import WorkspaceStore
from aria.routines import Cadence, RoutineService, RoutineStore, RoutineType
from aria.skill_evolution import SkillEvolutionService, SkillStore

_CTR = "Our notification CTR is dropping. Own this."


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v310_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    mode = "offline_mock"
    g = GoalStore(writer=writer, execution_mode=mode)
    sk = SkillStore(writer=writer, execution_mode=mode)
    aws = AwarenessStore(writer=writer, execution_mode=mode)
    cs = CollaborationStore(writer=writer, execution_mode=mode)
    rs = RoutineStore(writer=writer, execution_mode=mode)
    act = ActionStore(writer=writer, execution_mode=mode)
    ds = DashboardStore(writer=writer, execution_mode=mode)
    ws = WorkspaceStore(writer=writer, execution_mode=mode)
    gsvc = GoalService(g, workspace_store=ws, execution_mode=mode, actor="human:test")
    aw = AgentWorkforceService(g, workspace_store=ws, execution_mode=mode, actor="human:test")
    sup = AgentSupervisorService(g, workspace_store=ws, execution_mode=mode, actor="human:test")
    skills = SkillEvolutionService(sk, goal_store=g, workspace_store=ws, execution_mode=mode,
                                   actor="human:test")
    awareness = AwarenessService(aws, goal_store=g, skill_store=sk, skill_service=skills,
                                 workspace_store=ws, execution_mode=mode, actor="human:test")
    collab = CollaborationService(cs, goal_store=g, awareness_store=aws, workspace_store=ws,
                                  execution_mode=mode, actor="human:test")
    routines = RoutineService(rs, goal_store=g, awareness_service=awareness, collaboration_service=collab,
                              workspace_store=ws, execution_mode=mode, actor="human:test")
    actions = ActionService(act, collaboration_service=collab, workspace_store=ws, execution_mode=mode,
                            actor="human:test")
    dashboard = DashboardService(ds, goal_store=g, skill_store=sk, awareness_store=aws, collab_store=cs,
                                 routine_store=rs, action_store=act, workspace_store=ws,
                                 execution_mode=mode, actor="human:test")
    return {"g": g, "sk": sk, "aws": aws, "cs": cs, "rs": rs, "act": act, "ds": ds, "ws": ws,
            "gsvc": gsvc, "aw": aw, "sup": sup, "skills": skills, "awareness": awareness,
            "collab": collab, "routines": routines, "actions": actions, "dashboard": dashboard}


def _seed(env) -> dict:
    """Seed a representative slice of real V3 state and return key ids."""
    plan = env["gsvc"].own_goal(_CTR, scope="analytics.notifications")
    gid = plan.goal.goal_id
    env["aw"].plan(gid)
    env["sup"].run(gid)
    gaps = env["skills"].detect_gaps(gid)
    if gaps:
        env["skills"].propose_skill(gaps[0].gap_id)
    env["awareness"].consolidate_goal(gid)
    env["awareness"].ingest_world()
    draft = env["collab"].generate_draft(gid, DraftType.manager_update)
    rtn = env["routines"].create_routine(name="Daily", routine_type=RoutineType.daily_goal_review,
                                        cadence=Cadence.daily, goal_ids=[gid])
    run = env["routines"].run_routine(rtn.routine_id)
    intent = env["actions"].create_intent(action_type=ActionType.send_message, title="Notify",
                                          source_refs=[gid], evidence_refs=[draft.draft_id],
                                          payload_preview={"text": "x"})
    env["actions"].execute_dry_run(intent.action_id)
    ext = env["actions"].create_intent(action_type=ActionType.send_message, title="Teams",
                                       target_system=TargetSystem.teams, source_refs=[gid],
                                       evidence_refs=[draft.draft_id], payload_preview={"text": "y"})
    env["actions"].execute_mock(ext.action_id)             # blocked by deny-by-default
    return {"goal_id": gid, "workspace_id": plan.goal.workspace_id, "draft_id": draft.draft_id,
            "run_id": run.run_id, "intent_id": intent.action_id, "ext_id": ext.action_id}


def _event_types(writer: LedgerWriter) -> set[str]:
    if not writer.path.exists():
        return set()
    return {json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()}


def _blob(writer: LedgerWriter) -> str:
    blob = writer.path.read_text(encoding="utf-8") if writer.path.exists() else ""
    for dbf in (aria_data_dir() / "dashboard").glob("store.sqlite*"):
        blob += dbf.read_bytes().decode("utf-8", "ignore")
    return blob


# ── 1. Dashboard snapshot ─────────────────────────────────────────────────────


class TestSnapshot:
    def test_snapshot_aggregates_all_systems(self, env):
        ids = _seed(env)
        snap = env["dashboard"].create_snapshot(workspace_id=ids["workspace_id"])
        assert snap.goal_summary.total_tasks > 0
        assert snap.agent_summary.assignments_created > 0
        assert snap.memory_summary.memory_nodes > 0 and snap.memory_summary.lessons_created >= 1
        assert snap.collaboration_summary.manager_updates >= 1
        assert snap.routine_summary.runs_completed >= 1
        assert snap.action_summary.action_intents >= 2 and snap.action_summary.dry_run_receipts >= 1
        assert snap.action_summary.blocked_actions >= 1
        assert snap.roi_summary is not None
        assert ids["goal_id"] in snap.source_refs               # source-cited

    def test_live_receipts_are_zero(self, env):
        _seed(env)
        snap = env["dashboard"].create_snapshot()
        assert snap.action_summary.live_receipts == 0          # no real live execution in V3.10

    def test_get_and_list_snapshots(self, env):
        _seed(env)
        snap = env["dashboard"].create_snapshot()
        assert env["dashboard"].get_snapshot(snap.snapshot_id) is not None
        assert any(s["snapshot_id"] == snap.snapshot_id for s in env["dashboard"].list_snapshots())

    def test_empty_system_snapshot_invents_nothing(self, env):
        snap = env["dashboard"].create_snapshot()              # no seeded state
        assert snap.goal_summary.total_tasks == 0
        assert snap.action_summary.action_intents == 0
        assert snap.source_refs                                  # still cites the snapshot itself


# ── 2. ROI ────────────────────────────────────────────────────────────────────


class TestROI:
    def test_minutes_saved_and_method_exposed(self, env):
        _seed(env)
        roi = env["dashboard"].roi()
        assert roi.estimated is True
        assert roi.estimated_minutes_saved > 0
        assert roi.calculation_method and "minutes" in roi.calculation_method.lower()
        assert roi.evidence_refs

    def test_no_cost_without_config(self, env):
        _seed(env)
        roi = env["dashboard"].roi()
        assert roi.estimated_cost_saved is None                # never invents salary/cost

    def test_cost_only_when_hourly_configured(self, env):
        _seed(env)
        roi = env["dashboard"].roi(hourly_cost=60.0)
        assert roi.estimated_cost_saved is not None and roi.estimated_cost_saved >= 0

    def test_conservative_defaults_are_deterministic(self):
        roi = estimate_roi({"manager_update": 2, "handoff_note": 1}, evidence_refs=["e"])
        assert roi.estimated_minutes_saved == 2 * 10 + 1 * 12  # conservative + deterministic
        assert roi.estimated_cost_saved is None


# ── 3. Approval queue (read-only) ─────────────────────────────────────────────


class TestApprovalQueue:
    def test_summarizes_pending_items_read_only(self, env):
        ids = _seed(env)
        # Drive a skill proposal to awaiting_approval + an action to awaiting_approval.
        gaps = env["skills"].detect_gaps(ids["goal_id"])
        p = env["skills"].propose_skill(gaps[0].gap_id)
        env["skills"].generate_spec(p.proposal_id)
        env["skills"].generate_test_plan(p.proposal_id)
        env["skills"].evaluate(p.proposal_id)                  # -> awaiting_approval
        act = env["actions"].create_intent(action_type=ActionType.send_message, title="Need approval",
                                          source_refs=[ids["goal_id"]], evidence_refs=["ev-1"],
                                          payload_preview={"text": "z"})
        env["actions"].request_approval(act.action_id)         # -> awaiting_approval
        q = env["dashboard"].approval_queue()
        types = {i.item_type for i in q.items}
        assert "skill_proposal" in types and "action_intent" in types
        assert all(i.source_refs for i in q.items)             # source-cited
        # read-only: the queue did not change any underlying state
        assert env["actions"].get_intent(act.action_id).status.value == "awaiting_approval"

    def test_queue_has_no_decision_methods(self, env):
        q = env["dashboard"].approval_queue()
        assert not any(hasattr(q, m) for m in ("approve", "execute", "decide"))


# ── 4. Risk / blocker view ────────────────────────────────────────────────────


class TestRisks:
    def test_source_linked_risks_no_invention(self, env):
        _seed(env)
        r = env["dashboard"].risks()
        assert r.count > 0
        assert all(item.source_refs for item in r.items)       # source-linked, never invented
        kinds = {item.risk_type for item in r.items}
        assert "blocked_action" in kinds                       # the external action was blocked
        assert any(item.risk_type == "missing_evidence" for item in r.items)

    def test_missing_evidence_is_marked(self, env):
        _seed(env)
        r = env["dashboard"].risks()
        me = [x for x in r.items if x.risk_type == "missing_evidence"]
        assert me and "evidence missing" in me[0].title.lower()


# ── 5. Final V3 proof demo ────────────────────────────────────────────────────


class TestProof:
    def test_proof_is_deterministic_offline_and_isolated(self, env):
        env_before = os.environ.get("ARIA_DATA_DIR")
        proof = env["dashboard"].generate_proof()
        # ARIA_DATA_DIR is restored after the isolated run.
        assert os.environ.get("ARIA_DATA_DIR") == env_before
        milestones = [s["milestone"] for s in proof["proof"]["steps"]]
        assert any("V3.1" in m for m in milestones) and any("V3.10" in m for m in milestones)
        assert proof["source_refs"]
        assert "offline" in proof["proof"]["boundary"].lower()

    def test_proof_module_direct_no_pollution(self):
        from aria.demo.v3_proof import run_v3_proof

        before = os.environ.get("ARIA_DATA_DIR")
        proof = run_v3_proof()
        assert os.environ.get("ARIA_DATA_DIR") == before       # env restored
        assert proof["snapshot"]["action_summary"]["live_receipts"] == 0
        # the demo writes nothing into the aria source package
        pkg = Path(__file__).resolve().parents[1] / "aria" / "demo"
        assert not list(pkg.glob("*.sqlite"))


# ── 6. Workspace + store ──────────────────────────────────────────────────────


class TestWorkspaceAndStore:
    def test_snapshot_attaches_to_workspace(self, env):
        ids = _seed(env)
        snap = env["dashboard"].create_snapshot(workspace_id=ids["workspace_id"])
        refs = env["ws"].get_workspace(ids["workspace_id"]).ledger_refs
        assert any(r.startswith("dashboard_snapshot:") for r in refs)
        assert any(r.startswith("roi_summary:") for r in refs)
        assert snap.snapshot_id in " ".join(refs)

    def test_path_confined_restart_safe(self, env, writer):
        _seed(env)
        snap = env["dashboard"].create_snapshot()
        assert str(env["ds"].db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "dashboard"
        assert not list(source_pkg.glob("*.sqlite"))
        env["ds"].close()
        ds2 = DashboardStore(writer=writer, execution_mode="offline_mock")
        assert ds2.get_snapshot(snap.snapshot_id) is not None

    def test_orphan_snapshot_rejected(self, env):
        now = datetime.now(UTC)
        bad = ManagerDashboardSnapshot(snapshot_id=f"dash-{uuid.uuid4().hex}", generated_at=now,
                                      source_refs=[])
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_snapshot(bad)

    def test_secret_in_source_refs_rejected(self, env, writer):
        now = datetime.now(UTC)
        bad = ManagerDashboardSnapshot(snapshot_id=f"dash-{uuid.uuid4().hex}", generated_at=now,
                                      source_refs=["token=DASHSECRET777"])
        with pytest.raises(DashboardSecurityError):
            env["ds"].create_snapshot(bad)
        env["ds"].close()
        assert "DASHSECRET777" not in _blob(writer)


class TestProofClaimAuthority:
    """P1 regression — the store is the FINAL proof authority. It refuses to persist a
    snapshot/ROI that contradicts a V3 boundary or fabricates a value claim, even on a
    direct store call that bypassed the read-only aggregation service."""

    def _snap(self, **action_kw) -> ManagerDashboardSnapshot:
        return ManagerDashboardSnapshot(
            snapshot_id=f"dash-{uuid.uuid4().hex}", generated_at=datetime.now(UTC),
            action_summary=ActionSummary(**action_kw), source_refs=["src-1"])

    def _roi(self, **kw) -> ROISummary:
        base = dict(roi_summary_id=f"roi-{uuid.uuid4().hex}", estimated=True,
                    estimated_minutes_saved=0, evidence_refs=[],
                    calculation_method="Estimated, conservative minutes-saved per artifact: none.")
        base.update(kw)
        return ROISummary(**base)

    def test_fabricated_live_receipt_snapshot_rejected(self, env, writer):
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_snapshot(self._snap(live_receipts=9))
        env["ds"].close()
        assert "dash-fake" not in _blob(writer)              # nothing persisted

    def test_snapshot_with_contradicting_boundary_rejected(self, env):
        bad = ManagerDashboardSnapshot(
            snapshot_id=f"dash-{uuid.uuid4().hex}", generated_at=datetime.now(UTC),
            source_refs=["src-1"], boundary_note="anything goes")
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_snapshot(bad)

    def test_non_estimated_roi_rejected(self, env):
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_roi(self._roi(estimated=False, estimated_minutes_saved=999999,
                                          estimated_cost_saved=123456.78, evidence_refs=["e"]))

    def test_positive_roi_without_evidence_rejected(self, env):
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_roi(self._roi(estimated_minutes_saved=100, evidence_refs=[]))

    def test_arbitrary_method_roi_rejected(self, env):
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_roi(self._roi(estimated_minutes_saved=100, evidence_refs=["e"],
                                          calculation_method="trust me"))

    def test_cost_without_calculator_marker_rejected(self, env):
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_roi(self._roi(estimated_minutes_saved=10, estimated_cost_saved=5.0,
                                          evidence_refs=["e"]))   # cost but no cost marker

    def test_negative_roi_rejected(self, env):
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_roi(self._roi(estimated_minutes_saved=-1, evidence_refs=["e"]))

    def test_legitimate_service_roi_and_snapshot_still_work(self, env):
        _seed(env)
        roi = env["dashboard"].roi()                          # approved calculator path
        assert env["ds"].get_roi(roi.roi_summary_id) is not None
        snap = env["dashboard"].create_snapshot()
        assert env["ds"].get_snapshot(snap.snapshot_id) is not None
        assert snap.action_summary.live_receipts == 0

    # ── proof artifact authority ──────────────────────────────────────────────

    _GOOD_BOUNDARY = ("Offline, deterministic. No network, no external write, no live "
                      "execution, no deployment.")

    def test_fake_proof_live_receipts_rejected(self, env, writer):
        bad = json.dumps({"snapshot": {"action_summary": {"live_receipts": 9}},
                          "boundary": self._GOOD_BOUNDARY, "source_refs": ["src-1"]})
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_proof(proof_id="proof-fake1", summary="x", proof_json=bad,
                                  source_refs=["src-1"])
        env["ds"].close()
        assert "proof-fake1" not in _blob(writer)

    def test_fake_proof_boundary_rejected(self, env):
        bad = json.dumps({"snapshot": {"action_summary": {"live_receipts": 0}},
                          "boundary": "external writes happened", "source_refs": ["src-1"]})
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_proof(proof_id="proof-fake2", summary="x", proof_json=bad,
                                  source_refs=["src-1"])

    def test_malformed_proof_json_rejected(self, env):
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_proof(proof_id="proof-fake3", summary="x", proof_json="not json",
                                  source_refs=["src-1"])
        with pytest.raises(DashboardIntegrityError):
            env["ds"].create_proof(proof_id="proof-fake4", summary="x", proof_json="[1,2,3]",
                                  source_refs=["src-1"])

    def test_legitimate_proof_paths_still_work(self, env):
        from aria.demo.v3_proof import run_v3_proof

        _seed(env)
        rec = env["dashboard"].generate_proof()               # service path persists a proof
        assert env["ds"].get_proof(rec["proof_id"]) is not None
        proof = run_v3_proof()                                # direct demo path
        assert proof["snapshot"]["action_summary"]["live_receipts"] == 0
        assert all(m in proof["boundary"].lower()
                   for m in ("no external write", "no network", "no live execution"))


# ── 7. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_all_v310_events_emitted(self, env, writer):
        _seed(env)
        env["dashboard"].create_snapshot()                     # snapshot + roi + queue + risk
        env["dashboard"].generate_proof()                      # proof + acceptance
        types = _event_types(writer)
        for expected in ("dashboard_snapshot_created", "roi_summary_created",
                         "approval_queue_summarized", "risk_summary_created",
                         "v3_proof_demo_generated", "v3_acceptance_package_created"):
            assert expected in types, f"missing event {expected}"

    def test_legacy_ledger_compatibility(self, env, writer):
        _seed(env)
        env["dashboard"].create_snapshot()
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "dashboard_snapshot_created" for e in v2)


# ── 8. Safety ─────────────────────────────────────────────────────────────────


class TestSafety:
    def test_dashboard_is_read_only_no_action_methods(self, env):
        d = env["dashboard"]
        for forbidden in ("execute", "approve", "activate", "send", "post", "deploy",
                          "write_external", "connect_live"):
            assert not hasattr(d, forbidden), f"dashboard must not expose {forbidden!r}"

    def test_aria_user_id_is_attribution_not_authorization(self, env, monkeypatch):
        monkeypatch.setenv("ARIA_USER_ID", "human:admin")
        ids = _seed(env)
        # The dashboard only READS; an admin-looking actor changes no underlying state.
        before = env["actions"].get_intent(ids["ext_id"]).status.value
        env["dashboard"].create_snapshot()
        assert env["actions"].get_intent(ids["ext_id"]).status.value == before

    def test_v1_skill_import_does_not_load_dashboard(self):
        code = (
            "import sys; import aria.skills.pr_review_skill; "
            "bad=[m for m in ('aria.dashboard.service','aria.dashboard.store',"
            "'aria.dashboard.summary') if m in sys.modules]; "
            "print('LOADED', bad); assert not bad, bad"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "LOADED []" in r.stdout


# ── 9. API ────────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


class TestApi:
    def _seed_via_api(self, client) -> str:
        gid = client.post("/api/v3/goals", json={"raw_request": _CTR}).json()["goal"]["goal_id"]
        client.post(f"/api/v3/goals/{gid}/agents/plan")
        client.post(f"/api/v3/goals/{gid}/agents/supervise-run")
        return gid

    def test_snapshot_and_views(self, client):
        self._seed_via_api(client)
        snap = client.post("/api/v3/dashboard/snapshot", json={})
        assert snap.status_code == 201
        sid = snap.json()["snapshot_id"]
        assert client.get("/api/v3/dashboard/snapshots").json()["count"] >= 1
        assert client.get(f"/api/v3/dashboard/snapshots/{sid}").status_code == 200
        assert client.get("/api/v3/dashboard/approval-queue").status_code == 200
        assert client.get("/api/v3/dashboard/risks").status_code == 200
        roi = client.post("/api/v3/dashboard/roi", json={})
        assert roi.status_code == 200 and roi.json()["estimated"] is True

    def test_proof_endpoint(self, client):
        self._seed_via_api(client)
        proof = client.post("/api/v3/demo/v3-proof", json={})
        assert proof.status_code == 201
        assert proof.json()["proof"]["snapshot"]["action_summary"]["live_receipts"] == 0

    def test_safe_errors(self, client):
        assert client.get("/api/v3/dashboard/snapshots/dash-x").status_code == 404
