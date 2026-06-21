"""
V3.8 — Scheduled Routines + Approved Monitoring tests.

Covers routine definitions, deterministic due/missed evaluation, manual and due runs,
the routine handlers (daily/weekly goal review, blocker/risk review, memory review,
collaboration review, fixture-only world check), cited outputs, V3.7 draft follow-ups,
V3.5 proposal-only improvement routing, store persistence/confinement/secrets, Work
Ledger events, the V3 API, and the LOCAL/deterministic/fixture-only safety boundary.

ARIA can schedule, run, summarize, review, and recommend — it CANNOT live-browse,
monitor uncontrolled sources, send messages, mutate external systems, run external
agents, or start a background daemon.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aria.awareness import AwarenessService, AwarenessStore
from aria.collaboration import CollaborationService, CollaborationStore
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
from aria.routines import (
    Cadence,
    DueState,
    RoutineDisabledError,
    RoutineIntegrityError,
    RoutineSecurityError,
    RoutineNotFound,
    RoutineOutput,
    RoutineService,
    RoutineStore,
    RoutineType,
    RunStatus,
    evaluate,
)
from aria.routines.models import OutputType, RoutineDefinition
from aria.skill_evolution import SkillEvolutionService, SkillStore

_CTR = "Our notification CTR is dropping. Own this."
_T0 = datetime(2026, 6, 21, 9, 0, tzinfo=UTC)


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v38_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    mode = "offline_mock"
    gstore = GoalStore(writer=writer, execution_mode=mode)
    sstore = SkillStore(writer=writer, execution_mode=mode)
    astore = AwarenessStore(writer=writer, execution_mode=mode)
    cstore = CollaborationStore(writer=writer, execution_mode=mode)
    rstore = RoutineStore(writer=writer, execution_mode=mode)
    ws = WorkspaceStore(writer=writer, execution_mode=mode)
    gsvc = GoalService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    aw = AgentWorkforceService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    sup = AgentSupervisorService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    skills = SkillEvolutionService(sstore, goal_store=gstore, workspace_store=ws,
                                   execution_mode=mode, actor="human:test")
    awareness = AwarenessService(astore, goal_store=gstore, skill_store=sstore, skill_service=skills,
                                 workspace_store=ws, execution_mode=mode, actor="human:test")
    collab = CollaborationService(cstore, goal_store=gstore, awareness_store=astore, workspace_store=ws,
                                  execution_mode=mode, actor="human:test")
    routines = RoutineService(rstore, goal_store=gstore, awareness_service=awareness,
                              collaboration_service=collab, workspace_store=ws,
                              execution_mode=mode, actor="human:test")
    return {
        "gstore": gstore, "sstore": sstore, "astore": astore, "cstore": cstore, "rstore": rstore,
        "ws": ws, "gsvc": gsvc, "aw": aw, "sup": sup, "skills": skills, "awareness": awareness,
        "collab": collab, "routines": routines,
    }


def _blocked_goal(env):
    plan = env["gsvc"].own_goal(_CTR, scope="analytics.notifications")
    env["aw"].plan(plan.goal.goal_id)
    env["sup"].run(plan.goal.goal_id)
    env["awareness"].consolidate_goal(plan.goal.goal_id)
    return plan


def _event_types(writer: LedgerWriter) -> list[str]:
    if not writer.path.exists():
        return []
    return [json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()]


def _now() -> datetime:
    return datetime.now(UTC)


def _def(**kw) -> RoutineDefinition:
    now = kw.pop("created_at", _now())
    base = dict(routine_id=f"rtn-{uuid.uuid4().hex}", name="r", routine_type=RoutineType.daily_goal_review,
                cadence=Cadence.daily, created_at=now, updated_at=now)
    base.update(kw)
    return RoutineDefinition(**base)


def _output(*, source_refs=None) -> RoutineOutput:
    return RoutineOutput(
        output_id=f"rout-{uuid.uuid4().hex}", routine_id="rtn-1", run_id="run-1",
        output_type=OutputType.daily_summary, title="t", body="b",
        source_refs=(["rtn-1"] if source_refs is None else source_refs), created_at=_now())


def _blob(writer: LedgerWriter) -> str:
    blob = writer.path.read_text(encoding="utf-8") if writer.path.exists() else ""
    for dbf in (aria_data_dir() / "routines").glob("store.sqlite*"):
        blob += dbf.read_bytes().decode("utf-8", "ignore")
    return blob


# ── 1. Definitions ────────────────────────────────────────────────────────────


class TestDefinitions:
    def test_create_enable_disable(self, env):
        r = env["routines"]
        d = r.create_routine(name="Daily", routine_type=RoutineType.daily_goal_review,
                             cadence=Cadence.daily)
        assert d.enabled is True
        assert r.disable(d.routine_id).enabled is False
        assert r.enable(d.routine_id).enabled is True

    def test_invalid_routine_type_rejected(self, env):
        with pytest.raises(ValueError):
            env["routines"].create_routine(name="x", routine_type="not_a_routine")

    def test_disabled_routine_cannot_run(self, env):
        r = env["routines"]
        d = r.create_routine(name="d", routine_type=RoutineType.daily_goal_review)
        r.disable(d.routine_id)
        with pytest.raises(RoutineDisabledError):
            r.run_routine(d.routine_id, now=_T0)

    def test_cadence_stored_safely(self, env):
        r = env["routines"]
        d = r.create_routine(name="n", routine_type=RoutineType.blocker_review,
                             cadence=Cadence.every_n_hours, interval_hours=6)
        got = r.get_routine(d.routine_id)
        assert got.cadence is Cadence.every_n_hours and got.interval_hours == 6


class TestDueCalculation:
    def test_due_is_deterministic(self):
        d = _def(cadence=Cadence.daily, created_at=_T0, last_run_at=_T0)
        assert evaluate(d, _T0 + timedelta(hours=1)) is DueState.not_due
        assert evaluate(d, _T0 + timedelta(hours=25)) is DueState.due
        assert evaluate(d, _T0 + timedelta(days=10)) is DueState.missed

    def test_manual_routine_never_auto_due(self):
        d = _def(cadence=Cadence.manual, created_at=_T0)
        assert evaluate(d, _T0 + timedelta(days=30)) is DueState.manual_only

    def test_disabled_not_due(self):
        d = _def(cadence=Cadence.daily, created_at=_T0, last_run_at=_T0, enabled=False)
        assert evaluate(d, _T0 + timedelta(hours=25)) is DueState.not_due

    def test_first_run_never_missed(self):
        # Never-run routine created long ago is due, not missed.
        d = _def(cadence=Cadence.daily, created_at=_T0, last_run_at=None)
        assert evaluate(d, _T0 + timedelta(days=30)) is DueState.due


# ── 2. Runs ───────────────────────────────────────────────────────────────────


class TestRuns:
    def test_manual_run_completes(self, env):
        _blocked_goal(env)
        d = env["routines"].create_routine(name="dgr", routine_type=RoutineType.daily_goal_review)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        assert run.status is RunStatus.completed
        assert run.output_refs

    def test_due_run_works_and_is_idempotent(self, env):
        _blocked_goal(env)
        d = env["routines"].create_routine(name="dgr", routine_type=RoutineType.daily_goal_review,
                                          cadence=Cadence.daily)
        env["routines"].run_routine(d.routine_id, now=_T0)               # last_run = _T0
        later = _T0 + timedelta(hours=25)
        first = env["routines"].run_due(now=later)
        assert any(r.routine_id == d.routine_id and r.status is RunStatus.completed for r in first)
        # A second run-due at the same instant must NOT re-run it (idempotent).
        second = env["routines"].run_due(now=later)
        assert all(r.routine_id != d.routine_id for r in second)

    def test_missed_routine_recorded(self, env):
        d = env["routines"].create_routine(name="risk", routine_type=RoutineType.risk_review,
                                          cadence=Cadence.daily)
        env["routines"].run_routine(d.routine_id, now=_T0)
        runs = env["routines"].run_due(now=_T0 + timedelta(days=10))
        assert any(r.routine_id == d.routine_id and r.status is RunStatus.missed for r in runs)

    def test_failed_routine_records_safe_error_no_raw_text(self, env, writer):
        r = env["routines"]
        d = r.create_routine(name="boom", routine_type=RoutineType.daily_goal_review)
        r._h_goal_review = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sk-leak-RAW boom"))
        run = r.run_routine(d.routine_id, now=_T0)
        assert run.status is RunStatus.failed
        assert run.safe_error == "RuntimeError" and run.error_code == "routine_handler_error"
        r.rstore = None
        # No raw exception text / secret persisted anywhere.
        blob = _blob(writer)
        assert "sk-leak-RAW" not in blob
        assert "Traceback (most recent call last)" not in blob


class TestFailureBoundary:
    """P1 regression — the ENTIRE post-start path is inside the safe-failure boundary.
    A handler / output-construction / validation / persistence / finish failure must
    leave the run ``failed`` (never stuck ``running``), with a class/code-only safe
    error, no secret leakage, and no partial output rows."""

    def _routine(self, env, rtype=RoutineType.daily_goal_review, cadence=Cadence.manual):
        return env["routines"].create_routine(name="fb", routine_type=rtype, cadence=cadence)

    def test_secret_in_output_source_refs_fails_not_running(self, env, writer):
        r = env["routines"]
        d = self._routine(env)
        r._h_goal_review = lambda *a, **k: {
            "summary": "s", "findings": [], "recommendations": [], "input_refs": [],
            "outputs": [{"output_type": OutputType.daily_summary, "title": "t", "body": "b",
                         "source_refs": ["token=OUTSECRET999"]}],
            "followups": [],
        }
        run = r.run_routine(d.routine_id, now=_T0)
        assert run.status is RunStatus.failed
        assert run.safe_error == "RoutineSecurityError"          # class/code only
        assert r.get_run(run.run_id).status is RunStatus.failed  # never left running
        env["rstore"].close()
        assert "OUTSECRET999" not in _blob(writer)

    def test_no_partial_outputs_on_failure(self, env):
        r = env["routines"]
        d = self._routine(env)
        # first output valid, second carries a secret → NOTHING should persist.
        r._h_goal_review = lambda *a, **k: {
            "summary": "s", "outputs": [
                {"output_type": OutputType.daily_summary, "title": "ok", "body": "b",
                 "source_refs": ["rtn-ok"]},
                {"output_type": OutputType.daily_summary, "title": "bad", "body": "b",
                 "source_refs": ["token=PARTIALSECRET"]},
            ], "followups": [],
        }
        run = r.run_routine(d.routine_id, now=_T0)
        assert run.status is RunStatus.failed
        assert r.list_outputs(run_id=run.run_id) == []           # no partial rows

    def test_invalid_output_spec_fails_not_running(self, env):
        r = env["routines"]
        d = self._routine(env)
        # malformed spec (missing "body") → construction error inside the boundary.
        r._h_goal_review = lambda *a, **k: {
            "summary": "s", "outputs": [{"output_type": OutputType.daily_summary, "title": "t"}],
            "followups": [],
        }
        run = r.run_routine(d.routine_id, now=_T0)
        assert run.status is RunStatus.failed
        assert r.get_run(run.run_id).status is RunStatus.failed

    def test_secret_in_persistence_exception_not_leaked(self, env, writer, monkeypatch):
        r = env["routines"]
        d = self._routine(env)

        def boom(*a, **k):
            raise RuntimeError("sk-PERSIST-SECRET-123 boom")

        monkeypatch.setattr(env["rstore"], "create_output", boom)
        r._h_goal_review = lambda *a, **k: {
            "summary": "s", "outputs": [{"output_type": OutputType.daily_summary, "title": "t",
                                         "body": "b", "source_refs": ["rtn-ok"]}],
            "followups": [],
        }
        run = r.run_routine(d.routine_id, now=_T0)
        assert run.status is RunStatus.failed and run.safe_error == "RuntimeError"
        env["rstore"].close()
        assert "sk-PERSIST-SECRET-123" not in _blob(writer)

    def test_failed_run_advances_cadence_window(self, env):
        r = env["routines"]
        d = r.create_routine(name="fb", routine_type=RoutineType.daily_goal_review,
                            cadence=Cadence.daily)
        r._h_goal_review = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        run = r.run_routine(d.routine_id, now=_T0)
        assert run.status is RunStatus.failed
        # last_run advanced → not due within the window; run-due stays idempotent.
        assert all(x.routine_id != d.routine_id for x in r.compute_due(now=_T0 + timedelta(hours=1)))
        again = r.run_due(now=_T0 + timedelta(hours=1))
        assert all(x.routine_id != d.routine_id for x in again)


# ── 3. Outputs ────────────────────────────────────────────────────────────────


class TestOutputs:
    def test_daily_goal_review_summary(self, env):
        _blocked_goal(env)
        d = env["routines"].create_routine(name="dgr", routine_type=RoutineType.daily_goal_review)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        assert out.output_type is OutputType.daily_summary
        assert out.source_refs
        assert out.draft_refs              # manager_update follow-up draft created

    def test_blocker_review_digest(self, env):
        _blocked_goal(env)
        d = env["routines"].create_routine(name="br", routine_type=RoutineType.blocker_review)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        assert out.output_type is OutputType.blocker_digest
        assert "Blocker digest" in out.body and out.source_refs

    def test_memory_review_digest(self, env):
        _blocked_goal(env)
        d = env["routines"].create_routine(name="mr", routine_type=RoutineType.memory_review)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        assert out.output_type is OutputType.memory_lesson_digest
        assert out.source_refs

    def test_collaboration_review_digest(self, env):
        _blocked_goal(env)
        d = env["routines"].create_routine(name="cr", routine_type=RoutineType.collaboration_review)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        assert out.output_type is OutputType.approval_queue_digest
        assert out.source_refs

    def test_world_fixture_check_is_cited_and_offline(self, env):
        d = env["routines"].create_routine(name="wc", routine_type=RoutineType.world_fixture_check)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        assert out.output_type is OutputType.world_awareness_digest
        assert out.evidence_refs                       # fixture citations
        assert all("fixture://" in c for c in out.evidence_refs)   # no live URLs

    def test_output_does_not_invent_facts_when_empty(self, env):
        # A world check with NO awareness service still produces a safe, non-invented digest.
        rstore = env["rstore"]
        r = RoutineService(rstore, goal_store=env["gstore"], execution_mode="offline_mock")
        d = r.create_routine(name="empty", routine_type=RoutineType.world_fixture_check)
        run = r.run_routine(d.routine_id, now=_T0)
        out = r.list_outputs(run_id=run.run_id)[0]
        assert "(no fixture updates)" in out.body
        assert out.source_refs                          # still cites the routine itself

    def test_outputs_attach_to_workspace(self, env):
        plan = _blocked_goal(env)
        wsid = plan.goal.workspace_id
        d = env["routines"].create_routine(name="dgr", routine_type=RoutineType.daily_goal_review,
                                          workspace_id=wsid, goal_ids=[plan.goal.goal_id])
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        refs = env["ws"].get_workspace(wsid).ledger_refs
        assert any(r.startswith("routine_output:") for r in refs)
        assert any(r.startswith("routine_run:") for r in refs)


# ── 4. Integration with V3.1–V3.7 ─────────────────────────────────────────────


class TestIntegration:
    def test_routine_creates_collaboration_draft_followup(self, env):
        plan = _blocked_goal(env)
        d = env["routines"].create_routine(name="dgr", routine_type=RoutineType.daily_goal_review,
                                          goal_ids=[plan.goal.goal_id])
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        assert out.draft_refs
        # the follow-up exists in the collaboration layer as a DRAFT
        draft = env["collab"].get_draft(out.draft_refs[0])
        assert draft is not None and draft.is_sendable is False

    def test_memory_review_routes_proposal_only_no_activation(self, env):
        _blocked_goal(env)
        d = env["routines"].create_routine(name="mr", routine_type=RoutineType.memory_review)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        if out.recommendation_refs:                     # one improvement routed (proposal-only)
            prop = env["sstore"].get_proposal(out.recommendation_refs[0])
            assert prop is not None and prop.status.value == "proposed"   # never activated

    def test_world_check_uses_fixture_state_only(self, env):
        d = env["routines"].create_routine(name="wc", routine_type=RoutineType.world_fixture_check)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        # fixture ingestion populated the awareness store with fixture updates
        assert env["astore"].list_updates()
        assert all(u.source_url.startswith("fixture://") for u in env["astore"].list_updates())


# ── 5. Store: persistence / confinement / secrets ─────────────────────────────


class TestStore:
    def test_path_confined_restart_safe(self, env, writer):
        rstore = env["rstore"]
        d = env["routines"].create_routine(name="n", routine_type=RoutineType.daily_goal_review)
        assert str(rstore.db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "routines"
        assert not list(source_pkg.glob("*.sqlite"))
        rstore.close()
        rstore2 = RoutineStore(writer=writer, execution_mode="offline_mock")
        assert rstore2.get_definition(d.routine_id) is not None

    def test_orphan_output_rejected(self, env):
        with pytest.raises(RoutineIntegrityError):
            env["rstore"].create_output(_output(source_refs=[]))

    def test_structural_secret_ref_rejected(self, env, writer):
        with pytest.raises(RoutineSecurityError):
            env["rstore"].create_output(_output(source_refs=["token=ROUTSECRET777"]))
        env["rstore"].close()
        assert "ROUTSECRET777" not in _blob(writer)

    def test_free_text_secret_masked(self, env, writer):
        env["routines"].create_routine(name="leak password=RNAMESECRET888",
                                       routine_type=RoutineType.daily_goal_review)
        env["rstore"].close()
        assert "RNAMESECRET888" not in _blob(writer)


# ── 6. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_all_v38_events_emitted(self, env, writer):
        _blocked_goal(env)
        r = env["routines"]
        d = r.create_routine(name="dgr", routine_type=RoutineType.daily_goal_review, cadence=Cadence.daily)
        r.disable(d.routine_id); r.enable(d.routine_id)
        r.run_routine(d.routine_id, now=_T0)                       # started + completed + output + followup
        r.run_due(now=_T0 + timedelta(hours=25))                   # due
        # a failed run
        bad = r.create_routine(name="boom", routine_type=RoutineType.daily_goal_review)
        r._h_goal_review = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        r.run_routine(bad.routine_id, now=_T0)
        # a missed run
        miss = r.create_routine(name="miss", routine_type=RoutineType.risk_review, cadence=Cadence.daily)
        # restore handler so risk_review works for first run
        from aria.routines.service import RoutineService as _RS
        r._h_goal_review = _RS._h_goal_review.__get__(r)
        r.run_routine(miss.routine_id, now=_T0)
        r.run_due(now=_T0 + timedelta(days=10))
        types = set(_event_types(writer))
        for expected in ("routine_defined", "routine_enabled", "routine_disabled", "routine_due",
                         "routine_run_started", "routine_run_completed", "routine_run_failed",
                         "routine_run_missed", "routine_output_created", "routine_followup_drafted"):
            assert expected in types, f"missing event {expected}"

    def test_legacy_ledger_compatibility(self, env, writer):
        _blocked_goal(env)
        d = env["routines"].create_routine(name="dgr", routine_type=RoutineType.daily_goal_review)
        env["routines"].run_routine(d.routine_id, now=_T0)
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "routine_run_completed" for e in v2)


# ── 7. Safety ─────────────────────────────────────────────────────────────────


class TestSafety:
    def test_service_has_no_network_or_send_methods(self, env):
        r = env["routines"]
        for forbidden in ("crawl", "browse", "fetch", "http_get", "send", "post", "email",
                          "start_daemon", "schedule_cron", "spawn"):
            assert not hasattr(r, forbidden), f"routine service must not expose {forbidden!r}"

    def test_world_check_never_uses_live_urls(self, env):
        d = env["routines"].create_routine(name="wc", routine_type=RoutineType.world_fixture_check)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        assert "http://" not in out.body and "https://" not in out.body

    def test_aria_user_id_is_attribution_not_authorization(self, env, monkeypatch):
        monkeypatch.setenv("ARIA_USER_ID", "human:admin")
        _blocked_goal(env)
        d = env["routines"].create_routine(name="mr", routine_type=RoutineType.memory_review)
        run = env["routines"].run_routine(d.routine_id, now=_T0)
        out = env["routines"].list_outputs(run_id=run.run_id)[0]
        if out.recommendation_refs:
            prop = env["sstore"].get_proposal(out.recommendation_refs[0])
            assert prop.status.value == "proposed"     # admin-looking actor activates nothing

    def test_v1_skill_import_does_not_load_routines(self):
        code = (
            "import sys; import aria.skills.pr_review_skill; "
            "bad=[m for m in ('aria.routines.service','aria.routines.store',"
            "'aria.routines.scheduler') if m in sys.modules]; "
            "print('LOADED', bad); assert not bad, bad"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "LOADED []" in r.stdout


# ── 8. API ────────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


class TestApi:
    def test_create_list_get_routine(self, client):
        resp = client.post("/api/v3/routines",
                          json={"name": "Daily", "routine_type": "daily_goal_review", "cadence": "daily"})
        assert resp.status_code == 201
        rid = resp.json()["routine_id"]
        assert client.get("/api/v3/routines").json()["count"] >= 1
        assert client.get(f"/api/v3/routines/{rid}").status_code == 200

    def test_enable_disable_and_run(self, client):
        rid = client.post("/api/v3/routines",
                         json={"name": "wc", "routine_type": "world_fixture_check"}).json()["routine_id"]
        assert client.post(f"/api/v3/routines/{rid}/disable").json()["enabled"] is False
        # disabled run → safe 409
        assert client.post(f"/api/v3/routines/{rid}/run").status_code == 409
        assert client.post(f"/api/v3/routines/{rid}/enable").json()["enabled"] is True
        run = client.post(f"/api/v3/routines/{rid}/run")
        assert run.status_code == 200 and run.json()["status"] == "completed"

    def test_run_due_and_list_runs(self, client):
        client.post("/api/v3/routines", json={"name": "wc", "routine_type": "world_fixture_check",
                                              "cadence": "daily"})
        due = client.post("/api/v3/routines/run-due")
        assert due.status_code == 200
        runs = client.get("/api/v3/routines/runs")
        assert runs.status_code == 200
        if runs.json()["count"]:
            run_id = runs.json()["runs"][0]["run_id"]
            assert client.get(f"/api/v3/routines/runs/{run_id}").status_code == 200

    def test_safe_errors_and_no_monitor_endpoint(self, client):
        assert client.post("/api/v3/routines",
                          json={"name": "x", "routine_type": "bogus"}).status_code == 400
        assert client.get("/api/v3/routines/rtn-x").status_code == 404
        assert client.get("/api/v3/routines/runs/run-x").status_code == 404
        assert client.post("/api/v3/routines/rtn-x/run").status_code == 404
        # No live-monitor / crawl endpoint exists.
        for path in ("/api/v3/routines/monitor", "/api/v3/routines/crawl", "/api/v3/routines/watch-live"):
            assert client.post(path).status_code in (404, 405)
