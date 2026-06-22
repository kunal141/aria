"""
Action Service (V3.9) — the governed action gate.

ARIA can act, but ONLY through this gate: create an action intent → preview it →
(if policy requires) get explicit approval bound to the action's payload + scope →
execute in ``dry_run`` (writes nothing) or ``mock_live`` (internal_mock only; writes
only ARIA's local receipt). Live execution is disabled; no real connector write,
network call, or external send happens in V3.9.

Hard boundaries (V2/V3 preserved):
  - DENY-BY-DEFAULT — external targets cannot mock/live-execute; high/medium-risk or
    external actions require explicit, action-specific approval;
  - approval is bound to ``action_id`` + payload hash + scope — a changed payload or
    widened scope silently invalidates it (re-approval required); expired approval
    cannot execute;
  - a blocked action leaves no external side effect; failures record a class/code-only
    ``safe_error``; ``ARIA_USER_ID`` is attribution only, never authorization.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.actions import receipts
from aria.actions.executors import ExecutorError, get_executor
from aria.actions.models import (
    ACTION_BOUNDARY,
    ActionApproval,
    ActionIntent,
    ActionReceipt,
    ActionStatus,
    ActionType,
    ApprovalDecision,
    ExecutionMode,
    TargetSystem,
)
from aria.actions.policy import ActionPolicyEngine, PolicyDecision
from aria.actions.store import ActionNotFound, ActionStore


def _now() -> datetime:
    return datetime.now(UTC)


# Collaboration draft_type → the action intent it most naturally becomes (V3.7 → V3.9).
_DRAFT_TYPE_ACTION = {
    "manager_update": ActionType.send_message,
    "team_update": ActionType.send_message,
    "stakeholder_question": ActionType.send_message,
    "approval_request": ActionType.update_status,
    "risk_escalation": ActionType.send_message,
}


class ActionService:
    def __init__(
        self, store: ActionStore, *, collaboration_service: Any = None, workspace_store: Any = None,
        execution_mode: str | None = None, actor: str = "aria",
    ) -> None:
        self._store = store
        self._collab = collaboration_service
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor
        self._policy = ActionPolicyEngine()

    # ── Intent creation ───────────────────────────────────────────────────────

    def create_intent(self, *, action_type: str | ActionType, title: str,
                      target_system: str | TargetSystem = TargetSystem.internal_mock,
                      description: str = "", goal_id: str | None = None, task_id: str | None = None,
                      workspace_id: str | None = None, source_refs: list[str] | None = None,
                      evidence_refs: list[str] | None = None, draft_refs: list[str] | None = None,
                      payload_preview: dict[str, Any] | None = None, requested_by: str | None = None,
                      actor: str | None = None) -> ActionIntent:
        actor = actor or self._actor
        atype = action_type if isinstance(action_type, ActionType) else ActionType(action_type)
        target = target_system if isinstance(target_system, TargetSystem) else TargetSystem(target_system)
        now = _now()
        draft = ActionIntent(
            action_id=f"act-{uuid.uuid4().hex}", action_type=atype, title=title, description=description,
            requested_by=requested_by or actor, goal_id=goal_id, task_id=task_id,
            workspace_id=workspace_id, source_refs=list(source_refs or []),
            evidence_refs=list(evidence_refs or []), draft_refs=list(draft_refs or []),
            target_system=target, payload_preview=payload_preview or {}, status=ActionStatus.draft,
            created_at=now, updated_at=now,
        )
        # The POLICY is authoritative for risk / approval / scope.
        decision = self._policy.evaluate(draft)
        draft = draft.model_copy(update={
            "risk_level": decision.risk_level, "approval_required": decision.approval_required,
            "permission_scope": decision.permission_scope,
        })
        created = self._store.create_intent(draft, actor=actor)
        self._attach_ws(created.workspace_id, [f"action_intent:{created.action_id}"],
                        "action_intent_created", actor=actor)
        return created

    def intent_from_collaboration_draft(self, draft_id: str, *, target_system="internal_mock",
                                       actor: str | None = None) -> ActionIntent:
        """Convert a V3.7 collaboration DRAFT into an action intent (still draft-only —
        creating the intent sends nothing)."""
        actor = actor or self._actor
        if self._collab is None:
            raise ActionNotFound("collaboration service not available")
        draft = self._collab.get_draft(draft_id)
        if draft is None:
            raise ActionNotFound(f"collaboration draft {draft_id!r} not found")
        atype = _DRAFT_TYPE_ACTION.get(draft.draft_type.value, ActionType.send_message)
        return self.create_intent(
            action_type=atype, title=draft.title, description="From collaboration draft",
            target_system=target_system, goal_id=draft.goal_id, task_id=draft.task_id,
            workspace_id=draft.workspace_id, source_refs=[draft_id, *draft.source_refs],
            evidence_refs=list(draft.evidence_refs), draft_refs=[draft_id],
            payload_preview={"draft_id": draft_id, "title": draft.title}, actor=actor)

    # ── Preview ───────────────────────────────────────────────────────────────

    def preview(self, action_id: str, *, actor: str | None = None) -> dict[str, Any]:
        """Build a safe, persisted preview. NO execution, NO connector/network call."""
        actor = actor or self._actor
        intent = self._require(action_id)
        decision = self._policy.evaluate(intent)
        if not decision.allowed:
            self._store.mark_blocked(action_id, reason="preview:not policy-allowed", actor=actor)
        else:
            self._store.mark_previewed(action_id, actor=actor)
        intent = self._store.get_intent(action_id)
        self._attach_ws(intent.workspace_id, [f"action_preview:{action_id}"], "action_previewed",
                        actor=actor)
        return self._preview_dict(intent, decision)

    @staticmethod
    def _preview_dict(intent: ActionIntent, decision: PolicyDecision) -> dict[str, Any]:
        return {
            "action_id": intent.action_id, "action_type": intent.action_type.value,
            "target_system": intent.target_system.value, "payload_preview": intent.payload_preview,
            "risk_level": decision.risk_level.value, "approval_required": decision.approval_required,
            "evidence_required": decision.evidence_required, "permission_scope": decision.permission_scope,
            "allowed": decision.allowed,
            "allowed_execution_modes": [m.value for m in decision.allowed_execution_modes],
            "blocked_reasons": list(decision.blocked_reasons), "rollback_note": decision.rollback_note,
            "compensation_note": decision.compensation_note, "source_refs": list(intent.source_refs),
            "evidence_refs": list(intent.evidence_refs), "status": intent.status.value,
            "boundary_note": ACTION_BOUNDARY,
        }

    # ── Approval gate ─────────────────────────────────────────────────────────

    def request_approval(self, action_id: str, *, actor: str | None = None) -> ActionIntent:
        actor = actor or self._actor
        intent = self._require(action_id)
        decision = self._policy.evaluate(intent)
        if not decision.allowed:
            return self._store.mark_blocked(action_id, reason="not policy-allowed", actor=actor)
        return self._store.mark_approval_requested(action_id, actor=actor)

    def approve(self, action_id: str, *, approver: str | None = None, reason: str = "",
               expires_at: datetime | None = None, actor: str | None = None) -> ActionApproval:
        actor = actor or self._actor
        approver = approver or actor
        intent = self._require(action_id)
        decision = self._policy.evaluate(intent)
        # Approval is bound to THIS action's payload hash + required scope.
        approval = ActionApproval(
            approval_id=f"appr-{uuid.uuid4().hex}", action_id=action_id, approver=approver,
            decision=ApprovalDecision.approved, reason=reason, decided_at=_now(),
            approval_scope=decision.permission_scope, payload_hash=intent.payload_hash,
            expires_at=expires_at, source_refs=list(intent.source_refs),
            evidence_refs=list(intent.evidence_refs),
        )
        rec = self._store.record_decision(approval, intent_status=ActionStatus.approved, actor=actor)
        self._attach_ws(intent.workspace_id, [f"action_approval:{rec.approval_id}"], "action_approved",
                        actor=actor)
        return rec

    def reject(self, action_id: str, *, approver: str | None = None, reason: str = "",
              actor: str | None = None) -> ActionApproval:
        actor = actor or self._actor
        approver = approver or actor
        intent = self._require(action_id)
        approval = ActionApproval(
            approval_id=f"appr-{uuid.uuid4().hex}", action_id=action_id, approver=approver,
            decision=ApprovalDecision.rejected, reason=reason, decided_at=_now(),
            approval_scope=intent.permission_scope, payload_hash=intent.payload_hash,
        )
        rec = self._store.record_decision(approval, intent_status=ActionStatus.rejected, actor=actor)
        self._attach_ws(intent.workspace_id, [f"action_rejection:{rec.approval_id}"], "action_rejected",
                        actor=actor)
        return rec

    def change_payload(self, action_id: str, new_payload: dict[str, Any], *,
                      actor: str | None = None) -> ActionIntent:
        """Edit a pending action's payload — invalidates any prior approval."""
        return self._store.update_intent_payload(action_id, new_payload, actor=actor or self._actor)

    # ── Execution (dry-run / internal-mock ONLY) ──────────────────────────────

    def execute_dry_run(self, action_id: str, *, now: datetime | None = None,
                       actor: str | None = None) -> ActionReceipt:
        return self._execute(action_id, ExecutionMode.dry_run, now=now or _now(),
                            actor=actor or self._actor)

    def execute_mock(self, action_id: str, *, now: datetime | None = None,
                    actor: str | None = None) -> ActionReceipt:
        return self._execute(action_id, ExecutionMode.mock_live, now=now or _now(),
                            actor=actor or self._actor)

    def _execute(self, action_id: str, mode: ExecutionMode, *, now: datetime,
                actor: str) -> ActionReceipt:
        intent = self._require(action_id)
        decision = self._policy.evaluate(intent)

        # 1) Mode must be policy-allowed (live never is; mock only for internal_mock).
        if not decision.mode_allowed(mode):
            return self._blocked(intent, mode, decision.blocked_reasons or
                                 [f"{mode.value} not permitted for this action"], now=now, actor=actor)
        # 2) Terminal/rejected actions never execute.
        if intent.status in (ActionStatus.rejected, ActionStatus.cancelled, ActionStatus.rolled_back):
            return self._blocked(intent, mode, [f"action is {intent.status.value}; cannot execute"],
                                now=now, actor=actor)
        # 3) Approval gate (dry-run is a safe preview and needs none; mock needs a valid,
        #    action+payload+scope-bound, unexpired approval when policy requires it).
        if mode is ExecutionMode.mock_live and decision.approval_required:
            approval = self._store.latest_approval(action_id)
            if approval is None or not approval.is_valid_for(intent, now=now):
                reason = self._approval_block_reason(approval, intent, now=now)
                return self._blocked(intent, mode, [reason], now=now, actor=actor)

        # Execute under the safe-failure boundary. The store DERIVES the executed/failed
        # status from the real receipt — the service never asserts mode/outcome directly.
        self._store.mark_execution_started(action_id, execution_mode=mode, actor=actor)
        try:
            receipt = get_executor(mode).execute(intent, decision, executed_by=actor, now=now)
            created = self._store.create_receipt(receipt, actor=actor)
            self._store.mark_execution_succeeded(action_id, receipt_id=created.receipt_id, actor=actor)
            self._attach_ws(intent.workspace_id, [f"action_receipt:{created.receipt_id}"],
                            "action_executed", actor=actor)
            return created
        except Exception as exc:  # safe failure — class/code only, never raw text
            failed = receipts.failed_receipt(
                intent, mode=mode, safe_error=type(exc).__name__, rollback_note=decision.rollback_note,
                compensation_note=decision.compensation_note, executed_by=actor, now=now)
            created = self._store.create_receipt(failed, actor=actor)
            self._store.mark_execution_failed(action_id, receipt_id=created.receipt_id,
                                             safe_error=type(exc).__name__, actor=actor)
            self._attach_ws(intent.workspace_id, [f"action_receipt:{created.receipt_id}"],
                            "action_execution_failed", actor=actor)
            return created

    def _blocked(self, intent: ActionIntent, mode: ExecutionMode, reasons: list[str], *,
                now: datetime, actor: str) -> ActionReceipt:
        decision = self._policy.evaluate(intent)
        receipt = receipts.blocked_receipt(
            intent, mode=mode, reasons=reasons, rollback_note=decision.rollback_note,
            compensation_note=decision.compensation_note, executed_by=actor, now=now)
        created = self._store.create_receipt(receipt, actor=actor)
        self._store.mark_blocked(intent.action_id, receipt_id=created.receipt_id,
                                reason=(reasons[0] if reasons else "blocked"),
                                execution_mode=mode.value, actor=actor)
        self._attach_ws(intent.workspace_id, [f"action_blocked:{created.receipt_id}"], "action_blocked",
                        actor=actor)
        return created

    @staticmethod
    def _approval_block_reason(approval: ActionApproval | None, intent: ActionIntent, *,
                              now: datetime) -> str:
        if approval is None:
            return "required approval is missing"
        if approval.decision is not ApprovalDecision.approved:
            return f"action was {approval.decision.value}; cannot execute"
        if approval.payload_hash != intent.payload_hash:
            return "payload changed after approval — re-approval required"
        if approval.approval_scope and approval.approval_scope != intent.permission_scope:
            return "permission scope changed after approval — re-approval required"
        if approval.expires_at is not None and now > approval.expires_at:
            return "approval has expired — re-approval required"
        return "approval is not valid for this action"

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_intent(self, action_id: str) -> ActionIntent | None:
        return self._store.get_intent(action_id)

    def list_intents(self, *, status: str | None = None,
                    target_system: str | None = None) -> list[ActionIntent]:
        return self._store.list_intents(status=status, target_system=target_system)

    def get_receipt(self, receipt_id: str) -> ActionReceipt | None:
        return self._store.get_receipt(receipt_id)

    def list_receipts(self, *, action_id: str | None = None) -> list[ActionReceipt]:
        return self._store.list_receipts(action_id=action_id)

    @staticmethod
    def boundary_note() -> str:
        return ACTION_BOUNDARY

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _require(self, action_id: str) -> ActionIntent:
        i = self._store.get_intent(action_id)
        if i is None:
            raise ActionNotFound(f"action {action_id!r} not found")
        return i

    def _attach_ws(self, ws_id: str | None, refs: list[str], status: str, *, actor: str) -> None:
        if self._workspace_store is None or not ws_id or not refs:
            return
        try:
            self._workspace_store.update_workspace(
                ws_id, status=status, add_ledger_refs=list(refs), actor=actor)
        except Exception:  # pragma: no cover - workspace bookkeeping is best-effort
            pass
