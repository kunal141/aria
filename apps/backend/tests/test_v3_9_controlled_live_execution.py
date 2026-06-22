"""
V3.9 — Controlled Live Execution Layer tests.

Covers the governed action gate: typed action intents, the deny-by-default policy
engine, safe preview, the payload+scope-bound approval gate, dry-run + internal-mock
executors (and the hard-blocked live executor), receipts with rollback/compensation
notes, store persistence/confinement/secrets, integration with V3.7 collaboration,
Work Ledger events, the V3 API, and the no-live-write safety boundary.

ARIA can act ONLY through this gate: live execution is disabled; only explicitly
approved, policy-allowed actions run, and only in dry-run or internal_mock mode. No
real connector write, network call, or external send happens in V3.9.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aria.actions import (
    ActionExecutionViolation,
    ActionIntegrityError,
    ActionPolicyEngine,
    ActionSecurityError,
    ActionService,
    ActionStatus,
    ActionStore,
    ActionType,
    ApprovalDecision,
    ExecutionMode,
    InvalidActionTransition,
    TargetSystem,
    get_executor,
)
from aria.actions.executors import LiveExecutionBlocked
from aria.actions.models import ActionApproval, ActionIntent, ActionReceipt, RiskLevel
from aria.actions.store import ActionNotFound
from aria.collaboration import CollaborationService, CollaborationStore, DraftType
from aria.goals import GoalService, GoalStore
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir
from aria.memory_v2.workspace import WorkspaceStore

_T0 = datetime(2026, 6, 21, 9, 0, tzinfo=UTC)


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v39_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    mode = "offline_mock"
    gstore = GoalStore(writer=writer, execution_mode=mode)
    cstore = CollaborationStore(writer=writer, execution_mode=mode)
    astore = ActionStore(writer=writer, execution_mode=mode)
    ws = WorkspaceStore(writer=writer, execution_mode=mode)
    gsvc = GoalService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    collab = CollaborationService(cstore, goal_store=gstore, workspace_store=ws,
                                  execution_mode=mode, actor="human:test")
    actions = ActionService(astore, collaboration_service=collab, workspace_store=ws,
                            execution_mode=mode, actor="human:test")
    return {"gstore": gstore, "cstore": cstore, "astore": astore, "ws": ws, "gsvc": gsvc,
            "collab": collab, "actions": actions}


def _now() -> datetime:
    return datetime.now(UTC)


def _intent(env, **kw):
    base = dict(action_type=ActionType.mock_external_action, title="t",
                target_system=TargetSystem.internal_mock, source_refs=["goal-x"],
                payload_preview={"text": "hi"})
    base.update(kw)
    return env["actions"].create_intent(**base)


def _mem_intent(*, source_refs=None, target_system=TargetSystem.internal_mock,
                action_type=ActionType.send_message) -> ActionIntent:
    now = _now()
    return ActionIntent(
        action_id=f"act-{uuid.uuid4().hex}", action_type=action_type, title="t",
        target_system=target_system,
        source_refs=(["goal-x"] if source_refs is None else source_refs),
        evidence_refs=["ev-1"], created_at=now, updated_at=now)


def _blob(writer: LedgerWriter) -> str:
    blob = writer.path.read_text(encoding="utf-8") if writer.path.exists() else ""
    for dbf in (aria_data_dir() / "actions").glob("store.sqlite*"):
        blob += dbf.read_bytes().decode("utf-8", "ignore")
    return blob


def _event_types(writer: LedgerWriter) -> set[str]:
    if not writer.path.exists():
        return set()
    return {json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()}


# ── 1. Action intents ─────────────────────────────────────────────────────────


class TestIntents:
    def test_create_intent_sets_policy_risk_and_scope(self, env):
        i = _intent(env)
        assert i.risk_level is RiskLevel.low and i.approval_required is False
        assert i.permission_scope == "internal_mock:mock_external_action"
        assert i.status is ActionStatus.draft

    def test_unsupported_action_type_rejected(self, env):
        with pytest.raises(ValueError):
            env["actions"].create_intent(action_type="not_an_action", title="t", source_refs=["g"])

    def test_missing_source_refs_rejected(self, env):
        with pytest.raises(ActionIntegrityError):
            _intent(env, source_refs=[])

    def test_external_action_missing_evidence_rejected(self, env):
        with pytest.raises(ActionIntegrityError):
            env["actions"].create_intent(action_type=ActionType.post_comment, title="t",
                                        target_system=TargetSystem.github, source_refs=["g"],
                                        evidence_refs=[])

    def test_secret_payload_masked_secret_ref_rejected(self, env, writer):
        i = _intent(env, payload_preview={"text": "password=PAYSECRET999"})
        assert "PAYSECRET999" not in json.dumps(env["actions"].get_intent(i.action_id).payload_preview)
        with pytest.raises(ActionSecurityError):
            _intent(env, source_refs=["token=REFSECRET888"])
        env["astore"].close()
        blob = _blob(writer)
        assert "PAYSECRET999" not in blob and "REFSECRET888" not in blob


# ── 2. Policy engine ──────────────────────────────────────────────────────────


class TestPolicy:
    def setup_method(self):
        self.policy = ActionPolicyEngine()

    def test_internal_low_risk_no_approval(self):
        d = self.policy.evaluate(_mem_intent(action_type=ActionType.mock_external_action))
        assert d.allowed and not d.approval_required and ExecutionMode.mock_live in d.allowed_execution_modes

    def test_live_mode_never_allowed(self):
        d = self.policy.evaluate(_mem_intent())
        assert ExecutionMode.live not in d.allowed_execution_modes

    def test_external_blocked_from_mock(self):
        d = self.policy.evaluate(_mem_intent(target_system=TargetSystem.teams))
        assert ExecutionMode.mock_live not in d.allowed_execution_modes
        assert ExecutionMode.dry_run in d.allowed_execution_modes        # preview only
        assert d.approval_required and d.evidence_required

    def test_high_risk_requires_approval(self):
        d = self.policy.evaluate(_mem_intent(action_type=ActionType.trigger_webhook))
        assert d.risk_level is RiskLevel.high and d.approval_required

    def test_deny_by_default_missing_source(self):
        d = self.policy.evaluate(_mem_intent(source_refs=[]))
        assert not d.allowed and d.blocked_reasons

    def test_mock_only_for_internal_mock(self):
        internal = self.policy.evaluate(_mem_intent(action_type=ActionType.mock_external_action))
        external = self.policy.evaluate(_mem_intent(target_system=TargetSystem.slack))
        assert ExecutionMode.mock_live in internal.allowed_execution_modes
        assert ExecutionMode.mock_live not in external.allowed_execution_modes


# ── 3. Preview ────────────────────────────────────────────────────────────────


class TestPreview:
    def test_preview_no_execution_and_persisted(self, env):
        i = _intent(env)
        prev = env["actions"].preview(i.action_id)
        assert prev["allowed"] and "payload_preview" in prev and "risk_level" in prev
        assert "rollback_note" in prev and "blocked_reasons" in prev
        assert env["actions"].get_intent(i.action_id).status is ActionStatus.previewed   # persisted
        assert env["actions"].list_receipts(action_id=i.action_id) == []                 # no execution

    def test_preview_is_safe_summary_no_secret(self, env):
        i = _intent(env, payload_preview={"text": "password=PREVSECRET"})
        prev = env["actions"].preview(i.action_id)
        assert "PREVSECRET" not in json.dumps(prev)


# ── 4. Approval gate ──────────────────────────────────────────────────────────


class TestApprovalGate:
    def _medium(self, env, **kw):
        return env["actions"].create_intent(
            action_type=ActionType.send_message, title="t", target_system=TargetSystem.internal_mock,
            source_refs=["goal-x"], evidence_refs=["ev-1"], payload_preview={"text": "v1"}, **kw)

    def test_cannot_mock_execute_without_required_approval(self, env):
        i = self._medium(env)
        r = env["actions"].execute_mock(i.action_id, now=_T0)
        assert r.result_status == "blocked"
        assert env["actions"].get_intent(i.action_id).status is ActionStatus.blocked

    def test_approved_then_mock_executes(self, env):
        i = self._medium(env)
        env["actions"].approve(i.action_id, approver="human:lead")
        r = env["actions"].execute_mock(i.action_id, now=_T0)
        assert r.result_status == "mock_executed"

    def test_rejected_action_cannot_execute(self, env):
        i = self._medium(env)
        env["actions"].reject(i.action_id, approver="human:lead", reason="no")
        r = env["actions"].execute_mock(i.action_id, now=_T0)
        assert r.result_status == "blocked"
        assert env["actions"].get_intent(i.action_id).status is ActionStatus.rejected

    def test_changed_payload_requires_reapproval(self, env):
        i = self._medium(env)
        env["actions"].approve(i.action_id, approver="human:lead")
        env["actions"].change_payload(i.action_id, {"text": "v2-CHANGED"})
        r = env["actions"].execute_mock(i.action_id, now=_T0)
        assert r.result_status == "blocked" and "re-approval" in r.receipt_summary.lower()

    def test_expired_approval_cannot_execute(self, env):
        i = self._medium(env)
        env["actions"].approve(i.action_id, approver="human:lead", expires_at=_T0 - timedelta(hours=1))
        r = env["actions"].execute_mock(i.action_id, now=_T0)
        assert r.result_status == "blocked" and "expired" in r.receipt_summary.lower()

    def test_approval_scoped_to_action_id(self, env):
        i1 = self._medium(env)
        i2 = self._medium(env)
        env["actions"].approve(i1.action_id, approver="human:lead")   # approves i1 only
        r = env["actions"].execute_mock(i2.action_id, now=_T0)         # i2 has no approval
        assert r.result_status == "blocked"


# ── 5. Executors ──────────────────────────────────────────────────────────────


class TestExecutors:
    def test_dry_run_writes_nothing(self, env):
        i = _intent(env)
        r = env["actions"].execute_dry_run(i.action_id, now=_T0)
        assert r.execution_mode is ExecutionMode.dry_run and r.result_status == "dry_run_ok"
        assert r.external_ref is None and "DRY RUN" in r.receipt_summary

    def test_mock_executor_creates_mock_receipt_only(self, env):
        i = _intent(env)                       # low-risk internal, no approval needed
        r = env["actions"].execute_mock(i.action_id, now=_T0)
        assert r.result_status == "mock_executed"
        assert r.external_ref.startswith("mock://internal_mock/")

    def test_live_executor_hard_blocks(self):
        with pytest.raises(LiveExecutionBlocked):
            get_executor(ExecutionMode.live).execute(_mem_intent(), None, executed_by="x", now=_T0)

    def test_mock_executor_blocks_external_target(self):
        from aria.actions.executors import MockLiveExecutor
        with pytest.raises(LiveExecutionBlocked):
            MockLiveExecutor().execute(_mem_intent(target_system=TargetSystem.teams), None,
                                       executed_by="x", now=_T0)

    def test_failed_execution_records_failed_receipt_class_only(self, env, monkeypatch):
        i = _intent(env)
        from aria.actions import executors as _ex

        def boom(self, intent, decision, **k):
            raise RuntimeError("sk-EXEC-SECRET boom")

        monkeypatch.setattr(_ex.MockLiveExecutor, "execute", boom)
        r = env["actions"].execute_mock(i.action_id, now=_T0)
        assert r.result_status == "failed" and "RuntimeError" in r.receipt_summary
        assert env["actions"].get_intent(i.action_id).status is ActionStatus.failed


# ── 6. Receipts ───────────────────────────────────────────────────────────────


class TestReceipts:
    def test_receipt_has_rollback_and_compensation(self, env):
        i = _intent(env)
        r = env["actions"].execute_dry_run(i.action_id, now=_T0)
        assert r.rollback_note and r.compensation_note

    def test_receipt_attaches_to_workspace(self, env):
        plan = env["gsvc"].own_goal("Investigate CTR.", scope="analytics")
        i = _intent(env, source_refs=[plan.goal.goal_id])
        # attach intent to the goal workspace by setting workspace_id
        i2 = env["actions"].create_intent(action_type=ActionType.mock_external_action, title="t",
                                         source_refs=[plan.goal.goal_id],
                                         workspace_id=plan.goal.workspace_id, payload_preview={})
        env["actions"].execute_dry_run(i2.action_id, now=_T0)
        refs = env["ws"].get_workspace(plan.goal.workspace_id).ledger_refs
        assert any(r.startswith("action_receipt:") for r in refs)

    def test_no_raw_exception_or_secret_in_receipts(self, env, writer, monkeypatch):
        i = _intent(env)
        from aria.actions import executors as _ex
        monkeypatch.setattr(_ex.MockLiveExecutor, "execute",
                           lambda self, intent, decision, **k: (_ for _ in ()).throw(
                               RuntimeError("sk-RECEIPT-SECRET-xyz boom")))
        env["actions"].execute_mock(i.action_id, now=_T0)
        env["astore"].close()
        blob = _blob(writer)
        assert "sk-RECEIPT-SECRET-xyz" not in blob
        assert "Traceback (most recent call last)" not in blob


# ── 7. Integration with V3.6 / V3.7 / V3.8 ────────────────────────────────────


class TestIntegration:
    def test_collaboration_draft_converts_to_intent(self, env):
        plan = env["gsvc"].own_goal("Our notification CTR is dropping. Own this.",
                                   scope="analytics.notifications")
        draft = env["collab"].generate_draft(plan.goal.goal_id, DraftType.manager_update)
        intent = env["actions"].intent_from_collaboration_draft(draft.draft_id)
        assert intent.action_type is ActionType.send_message
        assert draft.draft_id in intent.source_refs and draft.draft_id in intent.draft_refs

    def test_draft_to_intent_does_not_send(self, env):
        plan = env["gsvc"].own_goal("x", scope="analytics")
        draft = env["collab"].generate_draft(plan.goal.goal_id, DraftType.manager_update)
        intent = env["actions"].intent_from_collaboration_draft(draft.draft_id)
        # creating the intent performs no execution / no receipt
        assert env["actions"].list_receipts(action_id=intent.action_id) == []
        assert intent.status is ActionStatus.draft


# ── 8. Store: confinement / restart / secrets ─────────────────────────────────


class TestStore:
    def test_path_confined_restart_safe(self, env, writer):
        i = _intent(env)
        assert str(env["astore"].db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "actions"
        assert not list(source_pkg.glob("*.sqlite"))
        env["astore"].close()
        astore2 = ActionStore(writer=writer, execution_mode="offline_mock")
        assert astore2.get_intent(i.action_id) is not None


class TestStoreExecutionAuthority:
    """P1 regression — the store is the FINAL execution authority. A direct store
    caller CANNOT fabricate an executed/live receipt by bypassing the policy +
    executor + service gate."""

    def _receipt(self, action_id, *, mode=ExecutionMode.mock_live, target=TargetSystem.internal_mock,
                 result="mock_executed", external_ref=None) -> ActionReceipt:
        return ActionReceipt(
            receipt_id=f"rcpt-{uuid.uuid4().hex}", action_id=action_id, target_system=target,
            execution_mode=mode, executed_at=_now(), result_status=result, external_ref=external_ref)

    def test_generic_transition_method_removed(self, env):
        # The permissive generic transition() is gone — only narrow methods remain.
        assert not hasattr(env["astore"], "transition")

    def test_direct_jump_to_executed_rejected(self, env):
        i = _intent(env)                                    # status = draft
        # No real receipt → cannot fabricate an executed status.
        with pytest.raises(ActionExecutionViolation):
            env["astore"].mark_execution_succeeded(i.action_id, receipt_id="rcpt-x")
        assert env["astore"].get_intent(i.action_id).status is ActionStatus.draft

    def test_direct_jump_to_failed_rejected(self, env):
        i = _intent(env)
        with pytest.raises(ActionExecutionViolation):
            env["astore"].mark_execution_failed(i.action_id, receipt_id="rcpt-x", safe_error="X")

    def test_forged_two_step_live_sequence_blocked(self, env):
        # Codex probe: mark_execution_started('live') → mark_execution_succeeded(fake).
        i = _intent(env)
        with pytest.raises(ActionExecutionViolation):           # 'live' start rejected outright
            env["astore"].mark_execution_started(i.action_id, execution_mode="live")
        assert env["astore"].get_intent(i.action_id).status is ActionStatus.draft
        # Even a legitimate mock-live start cannot be 'succeeded' with a fake receipt.
        env["astore"].mark_execution_started(i.action_id, execution_mode=ExecutionMode.mock_live)
        with pytest.raises(ActionExecutionViolation):
            env["astore"].mark_execution_succeeded(i.action_id, receipt_id="rcpt-fake-live")
        assert env["astore"].get_intent(i.action_id).status is ActionStatus.executing   # never executed

    def test_succeeded_with_foreign_receipt_rejected(self, env):
        i1 = _intent(env)
        i2 = _intent(env)
        r2 = env["actions"].execute_dry_run(i2.action_id, now=_T0)    # a real receipt for i2
        env["astore"].mark_execution_started(i1.action_id, execution_mode=ExecutionMode.dry_run)
        with pytest.raises(ActionExecutionViolation):
            env["astore"].mark_execution_succeeded(i1.action_id, receipt_id=r2.receipt_id)

    def test_succeeded_requires_success_result(self, env):
        # A blocked receipt (or any non-success) cannot back a 'succeeded' transition.
        i = env["actions"].create_intent(action_type=ActionType.send_message, title="t",
                                        source_refs=["goal-x"], evidence_refs=["ev-1"], payload_preview={})
        blocked = env["actions"].execute_mock(i.action_id, now=_T0)   # no approval → blocked receipt
        assert blocked.result_status == "blocked"
        env["astore"].mark_execution_started(i.action_id, execution_mode=ExecutionMode.mock_live)
        with pytest.raises(ActionExecutionViolation):
            env["astore"].mark_execution_succeeded(i.action_id, receipt_id=blocked.receipt_id)

    def test_succeeded_from_non_executing_rejected(self, env):
        # A VALID receipt still cannot move a non-'executing' action to executed.
        i = _intent(env)
        r = env["actions"].execute_dry_run(i.action_id, now=_T0)      # i is now 'executed'
        with pytest.raises(InvalidActionTransition):
            env["astore"].mark_execution_succeeded(i.action_id, receipt_id=r.receipt_id)

    def test_direct_live_receipt_rejected(self, env):
        i = _intent(env)
        with pytest.raises(ActionExecutionViolation):
            env["astore"].create_receipt(self._receipt(
                i.action_id, mode=ExecutionMode.live, target=TargetSystem.github,
                result="live_executed", external_ref="github://real/123"))

    def test_live_result_status_rejected(self, env):
        i = _intent(env)
        with pytest.raises(ActionExecutionViolation):
            env["astore"].create_receipt(self._receipt(i.action_id, result="live_executed"))

    def test_external_mock_receipt_rejected(self, env):
        i = _intent(env)
        with pytest.raises(ActionExecutionViolation):
            env["astore"].create_receipt(self._receipt(
                i.action_id, target=TargetSystem.github, result="mock_executed",
                external_ref="github://real/123"))

    def test_mock_receipt_with_forged_external_ref_rejected(self, env):
        i = _intent(env)
        with pytest.raises(ActionExecutionViolation):
            env["astore"].create_receipt(self._receipt(
                i.action_id, external_ref="https://example.com/real"))

    def test_receipt_for_unknown_action_rejected(self, env):
        with pytest.raises(ActionNotFound):
            env["astore"].create_receipt(self._receipt(
                "act-unknown", mode=ExecutionMode.dry_run, result="dry_run_ok"))

    def test_legitimate_dry_run_and_mock_still_work(self, env):
        i = _intent(env)
        dr = env["actions"].execute_dry_run(i.action_id, now=_T0)
        mk = env["actions"].execute_mock(i.action_id, now=_T0)
        assert dr.result_status == "dry_run_ok" and mk.result_status == "mock_executed"
        assert env["astore"].get_receipt(mk.receipt_id).external_ref == f"mock://internal_mock/{i.action_id}"

    # ── approval-path execution bypass (record_decision) ──────────────────────

    def _approval(self, action_id, decision=ApprovalDecision.approved) -> ActionApproval:
        return ActionApproval(approval_id=f"appr-{uuid.uuid4().hex}", action_id=action_id,
                              approver="human:x", decision=decision, decided_at=_now())

    def test_record_decision_cannot_set_executed(self, env):
        i = _intent(env)
        with pytest.raises(InvalidActionTransition):
            env["astore"].record_decision(self._approval(i.action_id),
                                         intent_status=ActionStatus.executed)
        assert env["astore"].get_intent(i.action_id).status is ActionStatus.draft   # no execution
        assert env["actions"].list_receipts(action_id=i.action_id) == []

    def test_record_decision_cannot_set_failed(self, env):
        i = _intent(env)
        with pytest.raises(InvalidActionTransition):
            env["astore"].record_decision(self._approval(i.action_id),
                                         intent_status=ActionStatus.failed)

    def test_record_decision_status_must_match_decision(self, env):
        i = _intent(env)
        with pytest.raises(InvalidActionTransition):
            env["astore"].record_decision(self._approval(i.action_id, ApprovalDecision.approved),
                                         intent_status=ActionStatus.rejected)

    def test_normal_approve_and_reject_still_work(self, env):
        i1 = env["actions"].create_intent(action_type=ActionType.send_message, title="t",
                                         source_refs=["goal-x"], evidence_refs=["ev-1"], payload_preview={})
        env["actions"].approve(i1.action_id, approver="human:lead")
        assert env["actions"].get_intent(i1.action_id).status is ActionStatus.approved
        i2 = env["actions"].create_intent(action_type=ActionType.send_message, title="t",
                                         source_refs=["goal-x"], evidence_refs=["ev-1"], payload_preview={})
        env["actions"].reject(i2.action_id, approver="human:lead", reason="no")
        assert env["actions"].get_intent(i2.action_id).status is ActionStatus.rejected


# ── 9. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_action_lifecycle_events_emitted(self, env, writer):
        i = env["actions"].create_intent(action_type=ActionType.send_message, title="t",
                                        source_refs=["goal-x"], evidence_refs=["ev-1"],
                                        payload_preview={"text": "v"})
        env["actions"].preview(i.action_id)
        env["actions"].request_approval(i.action_id)
        env["actions"].approve(i.action_id, approver="human:lead")
        env["actions"].execute_mock(i.action_id, now=_T0)
        # a separate blocked + rejected path
        j = env["actions"].create_intent(action_type=ActionType.send_message, title="t",
                                        source_refs=["goal-x"], evidence_refs=["ev-1"], payload_preview={})
        env["actions"].execute_mock(j.action_id, now=_T0)             # blocked (no approval)
        env["actions"].reject(j.action_id, approver="human:lead")
        types = _event_types(writer)
        for expected in ("action_intent_created", "action_previewed", "action_blocked",
                         "action_approval_requested", "action_approved", "action_rejected",
                         "action_execution_started", "action_executed", "action_receipt_created"):
            assert expected in types, f"missing event {expected}"

    def test_failed_event_and_legacy_compatibility(self, env, writer, monkeypatch):
        i = _intent(env)
        from aria.actions import executors as _ex
        monkeypatch.setattr(_ex.MockLiveExecutor, "execute",
                           lambda self, intent, decision, **k: (_ for _ in ()).throw(RuntimeError("x")))
        env["actions"].execute_mock(i.action_id, now=_T0)
        assert "action_execution_failed" in _event_types(writer)
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "action_intent_created" for e in v2)


# ── 10. Safety ────────────────────────────────────────────────────────────────


class TestSafety:
    def test_service_has_no_live_send_methods(self, env):
        a = env["actions"]
        for forbidden in ("send", "post", "email", "http_post", "connect_live", "webhook",
                          "deliver", "dispatch", "crawl"):
            assert not hasattr(a, forbidden), f"action service must not expose {forbidden!r}"

    def test_aria_user_id_is_attribution_not_authorization(self, env, monkeypatch):
        monkeypatch.setenv("ARIA_USER_ID", "human:admin")
        i = env["actions"].create_intent(action_type=ActionType.send_message, title="t",
                                        source_refs=["goal-x"], evidence_refs=["ev-1"], payload_preview={})
        # admin-looking actor does NOT grant approval — mock execution still blocked.
        r = env["actions"].execute_mock(i.action_id, now=_T0)
        assert r.result_status == "blocked"

    def test_no_external_write_receipts_are_dry_or_mock(self, env):
        i = _intent(env)
        env["actions"].execute_dry_run(i.action_id, now=_T0)
        env["actions"].execute_mock(i.action_id, now=_T0)
        for r in env["actions"].list_receipts(action_id=i.action_id):
            assert r.execution_mode in (ExecutionMode.dry_run, ExecutionMode.mock_live)
            assert r.result_status in ("dry_run_ok", "mock_executed")

    def test_v1_skill_import_does_not_load_actions(self):
        code = (
            "import sys; import aria.skills.pr_review_skill; "
            "bad=[m for m in ('aria.actions.service','aria.actions.store',"
            "'aria.actions.executors','aria.actions.policy') if m in sys.modules]; "
            "print('LOADED', bad); assert not bad, bad"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "LOADED []" in r.stdout


# ── 11. API ───────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


class TestApi:
    def _create(self, client, **kw):
        body = dict(action_type="mock_external_action", title="t", target_system="internal_mock",
                    source_refs=["goal-x"], payload_preview={"text": "hi"})
        body.update(kw)
        return client.post("/api/v3/actions/intents", json=body)

    def test_full_dry_run_and_mock_flow(self, client):
        resp = self._create(client)
        assert resp.status_code == 201
        aid = resp.json()["action_id"]
        assert client.get("/api/v3/actions/intents").json()["count"] >= 1
        assert client.get(f"/api/v3/actions/intents/{aid}").status_code == 200
        assert client.post(f"/api/v3/actions/intents/{aid}/preview").status_code == 200
        dr = client.post(f"/api/v3/actions/intents/{aid}/execute-dry-run")
        assert dr.status_code == 200 and dr.json()["result_status"] == "dry_run_ok"
        mk = client.post(f"/api/v3/actions/intents/{aid}/execute-mock")
        assert mk.status_code == 200 and mk.json()["result_status"] == "mock_executed"
        rid = mk.json()["receipt_id"]
        assert client.get(f"/api/v3/actions/receipts/{rid}").status_code == 200
        assert client.get("/api/v3/actions/receipts").json()["count"] >= 1

    def test_approval_required_flow(self, client):
        aid = self._create(client, action_type="send_message", evidence_refs=["ev-1"]).json()["action_id"]
        # mock without approval → blocked receipt
        blocked = client.post(f"/api/v3/actions/intents/{aid}/execute-mock")
        assert blocked.status_code == 200 and blocked.json()["result_status"] == "blocked"
        assert client.post(f"/api/v3/actions/intents/{aid}/request-approval").status_code == 200
        assert client.post(f"/api/v3/actions/intents/{aid}/approve", json={}).status_code == 200
        ok = client.post(f"/api/v3/actions/intents/{aid}/execute-mock")
        assert ok.json()["result_status"] == "mock_executed"

    def test_safe_errors_and_no_real_send_endpoint(self, client):
        assert self._create(client, action_type="bogus").status_code == 400
        assert self._create(client, source_refs=[]).status_code == 400
        assert client.get("/api/v3/actions/intents/act-x").status_code == 404
        assert client.get("/api/v3/actions/receipts/rcpt-x").status_code == 404
        aid = self._create(client).json()["action_id"]
        # No live/real-send endpoint exists.
        for path in (f"/api/v3/actions/intents/{aid}/execute-live",
                     f"/api/v3/actions/intents/{aid}/send",
                     f"/api/v3/actions/intents/{aid}/execute-real"):
            assert client.post(path).status_code in (404, 405)
