"""
V3.5 — Skill Evolution Engine tests.

Covers gap detection, proposal/spec/test-plan generation, the sandbox lifecycle,
evaluation, approval-gated activation, rollback/deprecation, workspace integration,
Work Ledger events, and safety. GOVERNED / approval-gated / proposal-only — no live
production code is created or modified, and nothing auto-activates.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aria.goals import (
    AgentStatus,
    AgentSupervisorService,
    AgentWorkforceService,
    GoalService,
    GoalStore,
)
from aria.ledger import LedgerEventType, LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir
from aria.memory_v2.workspace import WorkspaceStore
from aria.skill_evolution import (
    FORBIDDEN_SKILL_TOOLS,
    SAFE_THRESHOLD,
    SkillEvolutionService,
    SkillProposalStatus,
    SkillStore,
)
from aria.skill_evolution.generators import evaluate_proposal, generate_spec, generate_test_plan
from aria.skill_evolution.models import (
    GapSourceType,
    SkillGap,
    SkillProposal,
    SkillSpec,
)
from aria.skill_evolution.store import (
    InvalidSkillTransition,
    SkillActivationDenied,
    SkillNotFound,
)

_CTR = "Our notification CTR is dropping. Own this."


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v35_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    gstore = GoalStore(writer=writer, execution_mode="offline_mock")
    sstore = SkillStore(writer=writer, execution_mode="offline_mock")
    ws = WorkspaceStore(writer=writer, execution_mode="offline_mock")
    gsvc = GoalService(gstore, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    aw = AgentWorkforceService(gstore, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    sup = AgentSupervisorService(gstore, workspace_store=ws, execution_mode="offline_mock", actor="human:test")
    skills = SkillEvolutionService(sstore, goal_store=gstore, workspace_store=ws,
                                   execution_mode="offline_mock", actor="human:test")
    return gstore, sstore, ws, gsvc, aw, sup, skills


def _blocked_goal(gsvc, aw, sup):
    """A goal whose supervised run blocks several agents on missing evidence — a
    repeated gap signal."""
    plan = gsvc.own_goal(_CTR, scope="analytics.notifications")
    aw.plan(plan.goal.goal_id)
    sup.run(plan.goal.goal_id)          # no evidence → agents blocked_for_evidence
    return plan


def _event_types(writer: LedgerWriter) -> list[str]:
    if not writer.path.exists():
        return []
    return [json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()]


def _full_pipeline(skills, gap_id):
    p = skills.propose_skill(gap_id)
    skills.generate_spec(p.proposal_id)
    skills.generate_test_plan(p.proposal_id)
    skills.evaluate(p.proposal_id)
    return p.proposal_id


def _unsafe_spec(sstore, proposal_id):
    """Persist a deliberately UNSAFE spec (allows a write tool, no forbidden list)."""
    now = datetime.now(UTC)
    spec = SkillSpec(
        spec_id=f"spec-{uuid.uuid4().hex}", proposal_id=proposal_id, skill_name="Unsafe",
        problem_solved="x", input_schema={"q": "string"}, output_schema={"r": "string"},
        allowed_tools=["jira_create"], forbidden_tools=[], memory_access_policy="anything",
        evidence_requirements=["e"], acceptance_criteria=["c"], created_at=now,
    )
    sstore.save_spec(spec, SkillProposalStatus.spec_generated)
    return spec


# ── 1. Gap detection ──────────────────────────────────────────────────────────


class TestGapDetection:
    def test_repeated_blocker_creates_gap(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        plan = _blocked_goal(gsvc, aw, sup)
        gaps = skills.detect_gaps(plan.goal.goal_id)
        assert gaps
        assert any(g.source_type is GapSourceType.repeated_missing_evidence for g in gaps)
        assert all(g.confidence >= 0.7 for g in gaps)

    def test_single_weak_signal_no_high_confidence_gap(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        # A fresh goal with no repeated blockers → no gaps.
        plan = gsvc.own_goal(_CTR, scope="analytics.notifications")
        gaps = skills.detect_gaps(plan.goal.goal_id)
        assert gaps == []

    def test_gap_cites_source_refs(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        plan = _blocked_goal(gsvc, aw, sup)
        gaps = skills.detect_gaps(plan.goal.goal_id)
        assert all(g.source_refs for g in gaps)
        assert all(plan.goal.goal_id in g.affected_goals for g in gaps)


# ── 2. Proposal ───────────────────────────────────────────────────────────────


class TestProposal:
    def _gap(self, skills, gsvc, aw, sup):
        plan = _blocked_goal(gsvc, aw, sup)
        return skills.detect_gaps(plan.goal.goal_id)[0]

    def test_proposal_created_from_gap(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = self._gap(skills, gsvc, aw, sup)
        p = skills.propose_skill(gap.gap_id)
        assert p.gap_id == gap.gap_id
        assert p.status is SkillProposalStatus.proposed

    def test_write_tools_forbidden_and_approval_required(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = self._gap(skills, gsvc, aw, sup)
        p = skills.propose_skill(gap.gap_id)
        assert set(FORBIDDEN_SKILL_TOOLS).issubset(set(p.forbidden_tools))
        assert set(p.required_tools).isdisjoint(set(FORBIDDEN_SKILL_TOOLS))
        assert p.approval_required is True


# ── 3. Spec + 4. Test plan ────────────────────────────────────────────────────


class TestSpecAndTestPlan:
    def test_spec_has_schema_evidence_forbidden_rollback(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        p = skills.propose_skill(gap.gap_id)
        spec = skills.generate_spec(p.proposal_id)
        assert spec.input_schema and spec.output_schema
        assert spec.evidence_requirements
        assert set(FORBIDDEN_SKILL_TOOLS).issubset(set(spec.forbidden_tools))
        assert set(spec.allowed_tools).isdisjoint(set(FORBIDDEN_SKILL_TOOLS))
        assert spec.rollback_plan
        assert sstore.get_proposal(p.proposal_id).status is SkillProposalStatus.spec_generated

    def test_test_plan_covers_required_kinds(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        p = skills.propose_skill(gap.gap_id)
        skills.generate_spec(p.proposal_id)
        tp = skills.generate_test_plan(p.proposal_id)
        for kind in ("happy_path", "missing_evidence", "sensitive_input", "prompt_injection",
                     "forbidden_tool", "output_schema", "rollback"):
            assert kind in tp.case_kinds
        assert sstore.get_proposal(p.proposal_id).status is SkillProposalStatus.sandbox_ready


# ── 5. Evaluation ─────────────────────────────────────────────────────────────


class TestEvaluation:
    def test_safe_spec_scores_high_and_recommends_approve(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        p = skills.propose_skill(gap.gap_id)
        skills.generate_spec(p.proposal_id)
        skills.generate_test_plan(p.proposal_id)
        ev = skills.evaluate(p.proposal_id)
        assert ev.safety_score >= SAFE_THRESHOLD
        assert ev.recommended_decision.value == "approve"
        assert sstore.get_proposal(p.proposal_id).status is SkillProposalStatus.awaiting_approval

    def test_unsafe_spec_scores_low(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        p = skills.propose_skill(gap.gap_id)
        spec = _unsafe_spec(sstore, p.proposal_id)
        tp = generate_test_plan(spec)
        sstore.save_test_plan(tp, SkillProposalStatus.sandbox_ready)
        ev = evaluate_proposal(p, spec, tp)
        assert ev.safety_score < SAFE_THRESHOLD
        assert ev.recommended_decision.value == "reject"
        assert ev.missing_requirements

    def test_low_test_coverage_flagged(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        p = skills.propose_skill(gap.gap_id)
        spec = skills.generate_spec(p.proposal_id)
        from aria.skill_evolution.models import SkillTestPlan
        thin = SkillTestPlan(test_plan_id="tp-x", proposal_id=p.proposal_id, spec_id=spec.spec_id,
                            test_cases=[{"name": "h", "kind": "happy_path", "expectation": "ok"}],
                            created_at=datetime.now(UTC))
        ev = evaluate_proposal(p, spec, thin)
        assert any("test coverage" in m for m in ev.missing_requirements)


# ── 6/7. Approval-gated activation ────────────────────────────────────────────


class TestApprovalActivation:
    def test_approval_required_before_activation(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        pid = _full_pipeline(skills, gap.gap_id)
        # Before any decision, the proposal is awaiting approval — NOT activated.
        assert sstore.get_proposal(pid).status is SkillProposalStatus.awaiting_approval
        rec = skills.decide(pid, "approve", decided_by="human:lead")
        assert rec.activated is True
        assert sstore.get_proposal(pid).status is SkillProposalStatus.activated

    def test_rejected_proposal_cannot_activate(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        pid = _full_pipeline(skills, gap.gap_id)
        skills.decide(pid, "reject", decided_by="human:lead")
        assert sstore.get_proposal(pid).status is SkillProposalStatus.rejected
        rec = skills.decide(pid, "approve", decided_by="human:lead")
        assert rec.activated is False                       # terminal — cannot activate

    def test_unsafe_skill_cannot_activate_even_with_admin(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        p = skills.propose_skill(gap.gap_id)
        _unsafe_spec(sstore, p.proposal_id)
        skills.generate_test_plan(p.proposal_id)
        skills.evaluate(p.proposal_id)                      # unsafe → low safety
        # Admin-looking metadata must NOT authorize an unsafe activation.
        rec = skills.decide(p.proposal_id, "approve", decided_by="human:admin")
        assert rec.activated is False
        assert "unsafe" in rec.reason.lower()
        assert sstore.get_proposal(p.proposal_id).status is not SkillProposalStatus.activated

    def test_aria_user_id_is_not_authorization(self, env, monkeypatch):
        monkeypatch.setenv("ARIA_USER_ID", "human:admin")
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        p = skills.propose_skill(gap.gap_id)
        _unsafe_spec(sstore, p.proposal_id)
        skills.generate_test_plan(p.proposal_id)
        skills.evaluate(p.proposal_id)
        rec = skills.decide(p.proposal_id, "approve", decided_by="human:admin")
        assert rec.activated is False                       # caller identity grants nothing


# ── 8. Rollback / deprecation ─────────────────────────────────────────────────


class TestRollbackDeprecation:
    def _activate(self, skills, gsvc, aw, sup):
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        pid = _full_pipeline(skills, gap.gap_id)
        skills.decide(pid, "approve", decided_by="human:lead")
        return pid

    def test_activated_can_be_deprecated(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        pid = self._activate(skills, gsvc, aw, sup)
        dep = skills.deprecate(pid)
        assert dep.status is SkillProposalStatus.deprecated

    def test_rollback_restores_safe_state(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        pid = self._activate(skills, gsvc, aw, sup)
        rb = skills.rollback(pid)
        assert rb.status is SkillProposalStatus.rolled_back

    def test_cannot_rollback_non_activated(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        p = skills.propose_skill(gap.gap_id)
        with pytest.raises(SkillNotFound):
            skills.rollback(p.proposal_id)


# ── 9. Workspace + persistence ────────────────────────────────────────────────


class TestWorkspacePersistence:
    def test_artifacts_attached_path_confined_restart_safe(self, env, writer):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        plan = _blocked_goal(gsvc, aw, sup)
        gid = plan.goal.goal_id
        gap = skills.detect_gaps(gid)[0]
        pid = _full_pipeline(skills, gap.gap_id)
        wsrow = ws.get_workspace(plan.goal.workspace_id)
        for prefix in ("skill_gap:", "skill_proposal:", "skill_spec:", "skill_evaluation:"):
            assert any(r.startswith(prefix) for r in wsrow.ledger_refs)
        assert str(sstore.db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "skills"
        assert not list(source_pkg.glob("*.sqlite"))
        # restart-safe
        sstore.close()
        sstore2 = SkillStore(writer=writer, execution_mode="offline_mock")
        assert sstore2.get_proposal(pid) is not None
        assert sstore2.get_spec(pid) is not None

    def test_secrets_not_stored_in_sqlite_or_ledger(self, env, writer):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        # A gap whose description carries a secret must be sanitised before persist.
        now = datetime.now(UTC)
        gap = SkillGap(gap_id=f"gap-{uuid.uuid4().hex}", source_type=GapSourceType.repeated_blocker,
                      source_refs=["a"], description="leak password=SKILLSECRET123 token=AbC",
                      repeated_pattern="x", confidence=0.8, created_at=now)
        sstore.create_gap(gap)
        sstore.close()
        blob = writer.path.read_text(encoding="utf-8")
        for dbf in (aria_data_dir() / "skills").glob("store.sqlite*"):
            blob += dbf.read_bytes().decode("utf-8", "ignore")
        assert "SKILLSECRET123" not in blob


# ── 10. Work Ledger events ────────────────────────────────────────────────────


class TestLedger:
    def test_lifecycle_events_emitted(self, env, writer):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        pid = _full_pipeline(skills, gap.gap_id)
        skills.decide(pid, "approve", decided_by="human:lead")
        skills.rollback(pid)
        types = set(_event_types(writer))
        for expected in ("skill_gap_detected", "skill_proposal_created", "skill_spec_generated",
                         "skill_test_plan_generated", "skill_evaluated", "skill_approval_requested",
                         "skill_activated", "skill_rolled_back"):
            assert expected in types, f"missing event {expected}"

    def test_reject_event_and_legacy_compatibility(self, env, writer):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        pid = _full_pipeline(skills, gap.gap_id)
        skills.decide(pid, "reject", decided_by="human:lead")
        assert "skill_rejected" in set(_event_types(writer))
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "skill_gap_detected" for e in v2)
        legacy = writer.path.parent / "legacy.jsonl"
        legacy.write_text(json.dumps({"task_id": "legacy-35", "task_type": "pr_review",
                                      "timestamp": "2026-01-01T00:00:00+00:00"}) + "\n", encoding="utf-8")
        recs = LedgerReader(v2_path=writer.path, legacy_task_path=legacy).read_all()
        assert any(getattr(r, "task_id", None) == "legacy-35" for r in recs)


# ── 11. API ───────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


def _blocked_goal_via_api(client) -> str:
    gid = client.post("/api/v3/goals", json={"raw_request": _CTR}).json()["goal"]["goal_id"]
    client.post(f"/api/v3/goals/{gid}/agents/plan")
    client.post(f"/api/v3/goals/{gid}/agents/supervise-run")   # no evidence → blocked agents
    return gid


class TestApi:
    def test_full_skill_pipeline_via_api(self, client):
        gid = _blocked_goal_via_api(client)
        det = client.post("/api/v3/skills/gaps/detect", json={"goal_id": gid})
        assert det.status_code == 200 and det.json()["count"] >= 1
        gap_id = det.json()["gaps"][0]["gap_id"]
        prop = client.post("/api/v3/skills/proposals", json={"gap_id": gap_id})
        assert prop.status_code == 201
        pid = prop.json()["proposal_id"]
        assert client.post(f"/api/v3/skills/proposals/{pid}/spec").status_code == 201
        assert client.post(f"/api/v3/skills/proposals/{pid}/test-plan").status_code == 201
        assert client.post(f"/api/v3/skills/proposals/{pid}/evaluate").status_code == 200
        dec = client.post(f"/api/v3/skills/proposals/{pid}/decision", json={"decision": "approve"})
        assert dec.status_code == 200 and dec.json()["activated"] is True
        rb = client.post(f"/api/v3/skills/proposals/{pid}/rollback")
        assert rb.status_code == 200 and rb.json()["status"] == "rolled_back"
        assert client.get(f"/api/v3/skills/proposals/{pid}").json()["proposal"]["proposal_id"] == pid
        assert client.get("/api/v3/skills/proposals").json()["count"] >= 1

    def test_safe_errors(self, client):
        assert client.post("/api/v3/skills/gaps/detect", json={"goal_id": "goal-x"}).status_code == 404
        assert client.post("/api/v3/skills/proposals", json={"gap_id": "gap-x"}).status_code == 404
        assert client.get("/api/v3/skills/proposals/prop-x").status_code == 404
        assert client.post("/api/v3/skills/proposals/prop-x/rollback").status_code in (404, 409)


# ── 12. Lifecycle transition enforcement (store authority) ────────────────────


class TestLifecycleGuards:
    def _proposed(self, env):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        gap = skills.detect_gaps(_blocked_goal(gsvc, aw, sup).goal.goal_id)[0]
        return sstore, skills, skills.propose_skill(gap.gap_id)

    def test_direct_proposed_to_activated_is_rejected(self, env):
        sstore, skills, p = self._proposed(env)
        with pytest.raises(InvalidSkillTransition):
            sstore.transition(p.proposal_id, SkillProposalStatus.activated,
                              LedgerEventType.skill_activated)
        assert sstore.get_proposal(p.proposal_id).status is SkillProposalStatus.proposed

    def test_rejected_cannot_be_revived_by_generate_spec(self, env):
        sstore, skills, p = self._proposed(env)
        skills.generate_spec(p.proposal_id)
        skills.generate_test_plan(p.proposal_id)
        skills.evaluate(p.proposal_id)
        skills.decide(p.proposal_id, "reject", decided_by="human:lead")
        with pytest.raises(InvalidSkillTransition):
            skills.generate_spec(p.proposal_id)        # save_spec on a rejected proposal
        assert sstore.get_proposal(p.proposal_id).status is SkillProposalStatus.rejected

    def test_terminal_proposals_stay_terminal(self, env):
        sstore, skills, p = self._proposed(env)
        skills.generate_spec(p.proposal_id)
        skills.generate_test_plan(p.proposal_id)
        skills.evaluate(p.proposal_id)
        skills.decide(p.proposal_id, "approve", decided_by="human:lead")   # activated
        skills.rollback(p.proposal_id)                                     # rolled_back (terminal)
        rec = skills.decide(p.proposal_id, "approve", decided_by="human:lead")
        assert rec.activated is False                                      # no decision on terminal
        with pytest.raises(InvalidSkillTransition):
            skills.generate_spec(p.proposal_id)
        assert sstore.get_proposal(p.proposal_id).status is SkillProposalStatus.rolled_back

    def test_save_spec_on_activated_is_rejected(self, env):
        sstore, skills, p = self._proposed(env)
        skills.generate_spec(p.proposal_id)
        skills.generate_test_plan(p.proposal_id)
        skills.evaluate(p.proposal_id)
        skills.decide(p.proposal_id, "approve", decided_by="human:lead")   # activated
        with pytest.raises(InvalidSkillTransition):
            skills.generate_spec(p.proposal_id)        # activated → spec_generated is illegal

    def test_direct_awaiting_approval_to_activated_is_rejected(self, env):
        # A direct store caller cannot bypass decide()/safety to activate.
        sstore, skills, p = self._proposed(env)
        skills.generate_spec(p.proposal_id)
        skills.generate_test_plan(p.proposal_id)
        skills.evaluate(p.proposal_id)
        assert sstore.get_proposal(p.proposal_id).status is SkillProposalStatus.awaiting_approval
        with pytest.raises(InvalidSkillTransition):
            sstore.transition(p.proposal_id, SkillProposalStatus.activated,
                              LedgerEventType.skill_activated)
        assert sstore.get_proposal(p.proposal_id).status is SkillProposalStatus.awaiting_approval

    def test_store_activate_after_approval_enforces_safety(self, env):
        # Even the narrow activation path re-checks the safety gate at the store.
        sstore, skills, p = self._proposed(env)
        _unsafe_spec(sstore, p.proposal_id)
        skills.generate_test_plan(p.proposal_id)
        skills.evaluate(p.proposal_id)                 # unsafe → safety below threshold
        with pytest.raises(SkillActivationDenied):
            sstore.activate_after_approval(p.proposal_id)
        assert sstore.get_proposal(p.proposal_id).status is not SkillProposalStatus.activated

    def test_store_activate_after_approval_requires_approval_state(self, env):
        # Activation cannot happen from a pre-approval state (e.g. proposed).
        sstore, skills, p = self._proposed(env)
        with pytest.raises(InvalidSkillTransition):
            sstore.activate_after_approval(p.proposal_id)   # status is 'proposed'


# ── 13. Secret rejection in gap list fields ───────────────────────────────────


class TestSecretListFields:
    def test_secrets_in_list_fields_not_persisted(self, env, writer):
        gstore, sstore, ws, gsvc, aw, sup, skills = env
        now = datetime.now(UTC)
        gap = SkillGap(
            gap_id=f"gap-{uuid.uuid4().hex}", source_type=GapSourceType.repeated_blocker,
            source_refs=["password=LISTSECRET111"], affected_goals=["token=GOALSECRET222"],
            affected_tasks=["Bearer TASKSECRET333abcdef"], evidence_refs=["api_key=EVIDSECRET444"],
            description="d", repeated_pattern="p", confidence=0.8, created_at=now,
        )
        sstore.create_gap(gap)
        sstore.close()
        secrets = ["LISTSECRET111", "GOALSECRET222", "TASKSECRET333abcdef", "EVIDSECRET444"]
        blob = writer.path.read_text(encoding="utf-8")
        for dbf in (aria_data_dir() / "skills").glob("store.sqlite*"):
            blob += dbf.read_bytes().decode("utf-8", "ignore")
        for s in secrets:
            assert s not in blob, f"secret {s!r} leaked into SQLite/WAL/ledger"


# ── 14. Package isolation (V1 skills do not load the evolution engine) ────────


class TestPackageIsolation:
    def test_v1_skill_import_does_not_load_evolution_or_goals(self):
        import subprocess
        import sys

        code = (
            "import sys; import aria.skills.pr_review_skill; "
            "bad=[m for m in ('aria.skill_evolution.service','aria.skill_evolution.detector',"
            "'aria.skill_evolution.store','aria.goals.store') if m in sys.modules]; "
            "print('LOADED', bad); assert not bad, bad"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "LOADED []" in r.stdout
