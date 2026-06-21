"""
V3.7 — Team Collaboration Layer tests.

Covers draft generation (manager update, stakeholder question, handoff note, blocker
note, summaries, decision memo, risk escalation), approval-request drafts, the
read-only collaboration context, store persistence/confinement/secret-rejection,
workspace integration, Work Ledger events, the V3 API, and the DRAFT-ONLY safety
boundary. ARIA can draft/summarize/ask/escalate/hand off — it CANNOT send, post,
comment, email, or mutate any external system, even after approval.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aria.collaboration import (
    ApprovalRequestDraft,
    Channel,
    CollaborationContext,
    CollaborationDraft,
    CollaborationIntegrityError,
    CollaborationSecurityError,
    CollaborationService,
    CollaborationStore,
    DraftStatus,
    DraftType,
)
from aria.collaboration.store import CollaborationNotFound
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

_CTR = "Our notification CTR is dropping. Own this."


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v37_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    mode = "offline_mock"
    gstore = GoalStore(writer=writer, execution_mode=mode)
    cstore = CollaborationStore(writer=writer, execution_mode=mode)
    ws = WorkspaceStore(writer=writer, execution_mode=mode)
    gsvc = GoalService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    aw = AgentWorkforceService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    sup = AgentSupervisorService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    collab = CollaborationService(cstore, goal_store=gstore, workspace_store=ws,
                                  execution_mode=mode, actor="human:test")
    return gstore, cstore, ws, gsvc, aw, sup, collab


def _blocked_goal(gsvc, aw, sup):
    """A goal whose supervised run blocks several agents on missing evidence."""
    plan = gsvc.own_goal(_CTR, scope="analytics.notifications")
    aw.plan(plan.goal.goal_id)
    sup.run(plan.goal.goal_id)
    return plan


def _event_types(writer: LedgerWriter) -> list[str]:
    if not writer.path.exists():
        return []
    return [json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()]


def _now() -> datetime:
    return datetime.now(UTC)


def _draft(*, source_refs=None, draft_type=DraftType.team_update) -> CollaborationDraft:
    now = _now()
    return CollaborationDraft(
        draft_id=f"draft-{uuid.uuid4().hex}", draft_type=draft_type, title="t", body="b",
        source_refs=(["goal-1"] if source_refs is None else source_refs), created_at=now, updated_at=now,
    )


def _approval(*, source_refs=None, evidence_refs=None) -> ApprovalRequestDraft:
    return ApprovalRequestDraft(
        approval_request_id=f"areq-{uuid.uuid4().hex}", title="t", reason="r",
        requested_decision="approve", options=["approve", "reject"], recommended_option="approve",
        source_refs=(["goal-1"] if source_refs is None else source_refs),
        evidence_refs=(["ev-1"] if evidence_refs is None else evidence_refs),
        created_at=_now(),
    )


def _blob(writer: LedgerWriter) -> str:
    blob = writer.path.read_text(encoding="utf-8") if writer.path.exists() else ""
    for dbf in (aria_data_dir() / "collaboration").glob("store.sqlite*"):
        blob += dbf.read_bytes().decode("utf-8", "ignore")
    return blob


# ── 1. Draft generation ───────────────────────────────────────────────────────


class TestDraftGeneration:
    def test_manager_update_from_goal_state(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        d = collab.generate_draft(gid, DraftType.manager_update)
        assert d.draft_type is DraftType.manager_update
        assert "Status:" in d.body
        assert d.source_refs and gid in d.source_refs
        assert d.status is DraftStatus.draft
        assert d.approval_required is True

    def test_stakeholder_question_from_blocker(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        d = collab.generate_draft(gid, DraftType.stakeholder_question)
        assert "clarification" in d.body.lower()
        assert d.source_refs

    def test_handoff_note_from_workspace_state(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        d = collab.generate_draft(gid, DraftType.handoff_note)
        assert "Recommended next step" in d.body
        assert "Source references" in d.body
        assert d.source_refs

    def test_every_draft_has_source_refs(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        for dt in (DraftType.manager_update, DraftType.team_update, DraftType.blocker_note,
                   DraftType.risk_escalation, DraftType.daily_summary, DraftType.weekly_summary,
                   DraftType.decision_memo):
            d = collab.generate_draft(gid, dt)
            assert d.source_refs, f"{dt.value} draft missing source refs"

    def test_missing_evidence_shows_as_uncertainty_no_invented_facts(self, env):
        *_, gsvc, aw, sup, collab = env
        # Fresh goal, no supervised run → no progress/evidence. Draft must SAY so,
        # not invent results.
        plan = gsvc.own_goal("Investigate homepage bounce rate.", scope="analytics")
        d = collab.generate_draft(plan.goal.goal_id, DraftType.manager_update)
        low = d.body.lower()
        assert "(none recorded)" in low or "no evidence" in low

    def test_draft_is_not_sendable_even_when_approved(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        d = collab.generate_draft(gid, DraftType.manager_update)
        collab.mark_ready(d.draft_id)
        approved = collab.approve_draft(d.draft_id)
        assert approved.status is DraftStatus.approved
        assert approved.is_sendable is False           # approval is artifact-only

    def test_mark_ready_transitions_status(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        d = collab.generate_draft(gid, DraftType.team_update)
        ready = collab.mark_ready(d.draft_id)
        assert ready.status is DraftStatus.ready_for_review


# ── 2. Collaboration context ──────────────────────────────────────────────────


class TestContext:
    def test_context_reflects_blockers_and_questions(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        ctx = collab.build_context(gid)
        assert ctx.goal_id == gid
        assert ctx.active_blockers           # blocked agents surface as blockers
        assert ctx.open_questions            # clarifying questions / missing context
        assert ctx.evidence_refs             # provenance ids, not invented facts

    def test_unknown_goal_raises(self, env):
        *_, gsvc, aw, sup, collab = env
        with pytest.raises(CollaborationNotFound):
            collab.build_context("goal-x")


# ── 3. Approval-request drafts ────────────────────────────────────────────────


class TestApprovalRequests:
    def test_approval_request_is_draft_only(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        req = collab.draft_approval_request(gid)
        assert req.status.value == "draft"
        assert req.options and req.recommended_option
        assert req.source_refs and gid in req.source_refs

    def test_approval_request_listed(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        collab.draft_approval_request(gid)
        assert len(collab.list_approval_requests()) >= 1


class TestApprovalRequestIntegrity:
    """An approval request is a governance artifact — it must cite a source AND an
    evidence basis, enforced at the store authority boundary (no orphan approval)."""

    def test_orphan_approval_request_rejected_no_residue(self, env, writer):
        _, cstore, *_rest = env
        bad = _approval(source_refs=[], evidence_refs=[])
        with pytest.raises(CollaborationIntegrityError):
            cstore.create_approval_request(bad)
        # The guard runs before any DB work: no row, no enqueued/flushed event.
        assert cstore.get_approval_request(bad.approval_request_id) is None
        cstore.close()
        assert bad.approval_request_id not in _blob(writer)

    def test_source_only_without_evidence_rejected(self, env):
        _, cstore, *_rest = env
        with pytest.raises(CollaborationIntegrityError):
            cstore.create_approval_request(_approval(source_refs=["goal-1"], evidence_refs=[]))

    def test_secret_in_approval_ref_rejected(self, env, writer):
        _, cstore, *_rest = env
        with pytest.raises(CollaborationSecurityError):
            cstore.create_approval_request(_approval(source_refs=["token=APRSECRET444"]))
        cstore.close()
        assert "APRSECRET444" not in _blob(writer)

    def test_approval_request_persists_when_evidence_exists(self, env):
        _, cstore, *_rest = env
        a = cstore.create_approval_request(_approval(source_refs=["goal-1"], evidence_refs=["ev-1"]))
        assert cstore.get_approval_request(a.approval_request_id) is not None

    def test_service_refuses_approval_without_evidence(self, env):
        *_, gsvc, aw, sup, collab = env
        # Fresh goal, no supervised run → no evidence basis → service refuses.
        plan = gsvc.own_goal("Investigate homepage bounce rate.", scope="analytics")
        with pytest.raises(CollaborationIntegrityError):
            collab.draft_approval_request(plan.goal.goal_id)

    def test_api_missing_evidence_returns_safe_error(self, env):
        # Exercised via the service here; the API maps this to a 409 (see TestApi).
        *_, gsvc, aw, sup, collab = env
        plan = gsvc.own_goal("Investigate signups.", scope="analytics")
        with pytest.raises(CollaborationIntegrityError):
            collab.draft_approval_request(plan.goal.goal_id)


# ── 4. Store: persistence / confinement / secrets ─────────────────────────────


class TestStore:
    def test_path_confined_and_restart_safe(self, env, writer):
        _, cstore, *_rest = env
        d = cstore.create_draft(_draft(source_refs=["goal-1"]))
        assert str(cstore.db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "collaboration"
        assert not list(source_pkg.glob("*.sqlite"))
        cstore.close()
        cstore2 = CollaborationStore(writer=writer, execution_mode="offline_mock")
        assert cstore2.get_draft(d.draft_id) is not None

    def test_free_text_secret_masked(self, env, writer):
        _, cstore, *_rest = env
        now = _now()
        cstore.create_draft(CollaborationDraft(
            draft_id=f"draft-{uuid.uuid4().hex}", draft_type=DraftType.manager_update,
            title="leak password=DRAFTSECRET111", body="api_key=BODYSECRET222 inside",
            source_refs=["goal-1"], created_at=now, updated_at=now))
        cstore.close()
        blob = _blob(writer)
        for secret in ("DRAFTSECRET111", "BODYSECRET222"):
            assert secret not in blob, f"secret {secret!r} leaked into SQLite/WAL/ledger"

    def test_structural_secret_ref_rejected(self, env, writer):
        _, cstore, *_rest = env
        with pytest.raises(CollaborationSecurityError):
            cstore.create_draft(_draft(source_refs=["token=REFSECRET333"]))
        cstore.close()
        assert "REFSECRET333" not in _blob(writer)

    def test_orphan_draft_rejected(self, env):
        _, cstore, *_rest = env
        with pytest.raises(CollaborationIntegrityError):
            cstore.create_draft(_draft(source_refs=[]))

    def test_no_raw_exception_text_persisted(self, env, writer):
        # Draft bodies never carry raw tracebacks — assert no stack markers persist.
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        collab.generate_draft(gid, DraftType.manager_update)
        blob = _blob(writer)
        assert "Traceback (most recent call last)" not in blob


# ── 5. Workspace integration ──────────────────────────────────────────────────


class TestWorkspaceIntegration:
    def test_draft_and_approval_attach_to_workspace(self, env):
        gstore, cstore, ws, gsvc, aw, sup, collab = env
        plan = _blocked_goal(gsvc, aw, sup)
        wsid = plan.goal.workspace_id
        d = collab.generate_draft(plan.goal.goal_id, DraftType.manager_update)
        collab.draft_approval_request(plan.goal.goal_id)
        refs = ws.get_workspace(wsid).ledger_refs
        assert any(r.startswith("collaboration_draft:") for r in refs)
        assert any(r.startswith("approval_request:") for r in refs)
        assert d.draft_id in " ".join(refs)


# ── 6. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_all_v37_events_emitted(self, env, writer):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        collab.build_context(gid)
        d = collab.generate_draft(gid, DraftType.manager_update)
        collab.mark_ready(d.draft_id)
        collab.generate_draft(gid, DraftType.handoff_note)
        collab.generate_draft(gid, DraftType.stakeholder_question)
        collab.generate_draft(gid, DraftType.risk_escalation)
        collab.draft_approval_request(gid)
        types = set(_event_types(writer))
        for expected in ("collaboration_context_created", "collaboration_draft_created",
                         "collaboration_draft_updated", "approval_request_drafted",
                         "handoff_note_created", "stakeholder_question_created",
                         "risk_escalation_drafted"):
            assert expected in types, f"missing event {expected}"

    def test_legacy_ledger_compatibility(self, env, writer):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        collab.generate_draft(gid, DraftType.manager_update)
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "collaboration_draft_created" for e in v2)
        legacy = writer.path.parent / "legacy37.jsonl"
        legacy.write_text(json.dumps({"task_id": "legacy-37", "task_type": "pr_review",
                                      "timestamp": "2026-01-01T00:00:00+00:00"}) + "\n", encoding="utf-8")
        recs = LedgerReader(v2_path=writer.path, legacy_task_path=legacy).read_all()
        assert any(getattr(r, "task_id", None) == "legacy-37" for r in recs)


# ── 7. Safety ─────────────────────────────────────────────────────────────────


class TestSafety:
    def test_service_has_no_send_path(self, env):
        *_, collab = env
        for forbidden in ("send", "post", "comment", "email", "publish", "deliver", "dispatch"):
            assert not hasattr(collab, forbidden), f"collaboration service must not expose {forbidden!r}"

    def test_draft_is_sendable_is_always_false(self, env):
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        d = collab.generate_draft(gid, DraftType.manager_update)
        assert d.is_sendable is False

    def test_aria_user_id_is_attribution_not_authorization(self, env, monkeypatch):
        # The actor label never grants authority — V3.7 sends nothing regardless.
        monkeypatch.setenv("ARIA_USER_ID", "human:admin")
        *_, gsvc, aw, sup, collab = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        d = collab.generate_draft(gid, DraftType.manager_update)
        collab.mark_ready(d.draft_id)
        approved = collab.approve_draft(d.draft_id)
        assert approved.is_sendable is False           # admin-looking actor sends nothing

    def test_v1_skill_import_does_not_load_collaboration(self):
        code = (
            "import sys; import aria.skills.pr_review_skill; "
            "bad=[m for m in ('aria.collaboration.service','aria.collaboration.store',"
            "'aria.collaboration.templates') if m in sys.modules]; "
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


def _blocked_goal_via_api(client) -> str:
    gid = client.post("/api/v3/goals", json={"raw_request": _CTR}).json()["goal"]["goal_id"]
    client.post(f"/api/v3/goals/{gid}/agents/plan")
    client.post(f"/api/v3/goals/{gid}/agents/supervise-run")
    return gid


class TestApi:
    def test_context_and_draft_flow(self, client):
        gid = _blocked_goal_via_api(client)
        ctx = client.post("/api/v3/collaboration/context", json={"goal_id": gid})
        assert ctx.status_code == 201
        draft = client.post("/api/v3/collaboration/drafts",
                            json={"goal_id": gid, "draft_type": "manager_update"})
        assert draft.status_code == 201
        did = draft.json()["draft_id"]
        assert draft.json()["source_refs"]
        assert client.get(f"/api/v3/collaboration/drafts/{did}").status_code == 200
        assert client.get("/api/v3/collaboration/drafts").json()["count"] >= 1
        ready = client.post(f"/api/v3/collaboration/drafts/{did}/mark-ready")
        assert ready.status_code == 200 and ready.json()["status"] == "ready_for_review"

    def test_approval_request_flow(self, client):
        gid = _blocked_goal_via_api(client)
        req = client.post("/api/v3/collaboration/approval-requests", json={"goal_id": gid})
        assert req.status_code == 201 and req.json()["status"] == "draft"
        assert client.get("/api/v3/collaboration/approval-requests").json()["count"] >= 1

    def test_approval_request_without_evidence_returns_409(self, client):
        # A fresh goal (no run → no evidence basis) cannot yield an approval request.
        gid = client.post("/api/v3/goals", json={"raw_request": "Investigate signups."}
                          ).json()["goal"]["goal_id"]
        resp = client.post("/api/v3/collaboration/approval-requests", json={"goal_id": gid})
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "missing_evidence_basis"

    def test_no_send_endpoint_exists(self, client):
        gid = _blocked_goal_via_api(client)
        did = client.post("/api/v3/collaboration/drafts",
                         json={"goal_id": gid, "draft_type": "manager_update"}).json()["draft_id"]
        # No send/post/email route exists — these must 404/405, never 200.
        for path in (f"/api/v3/collaboration/drafts/{did}/send",
                     f"/api/v3/collaboration/drafts/{did}/post",
                     f"/api/v3/collaboration/drafts/{did}/email"):
            assert client.post(path).status_code in (404, 405)

    def test_safe_errors(self, client):
        assert client.post("/api/v3/collaboration/context",
                          json={"goal_id": "goal-x"}).status_code == 404
        assert client.post("/api/v3/collaboration/drafts",
                          json={"goal_id": "goal-x", "draft_type": "manager_update"}).status_code == 404
        assert client.get("/api/v3/collaboration/drafts/draft-x").status_code == 404
        assert client.post("/api/v3/collaboration/drafts/draft-x/mark-ready").status_code == 404
        gid = _blocked_goal_via_api(client)
        assert client.post("/api/v3/collaboration/drafts",
                          json={"goal_id": gid, "draft_type": "bogus"}).status_code == 400
