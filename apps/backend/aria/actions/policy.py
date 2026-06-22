"""
Action Policy Engine (V3.9) — DENY-BY-DEFAULT.

Decides, for an :class:`ActionIntent`, whether it may proceed and under what
constraints: risk level, whether approval/evidence are required, which execution
modes are permitted, the required permission scope, and any blocked reasons.

Governing rules (all enforced here, structurally):
  - **live mode is disabled** — it is never an allowed execution mode in V3.9;
  - **external target systems are blocked from mock/live execution** — only
    ``internal_mock`` may ``mock_live``; external targets may only ``dry_run``
    (a write-nothing preview);
  - **deny by default** — missing source refs, or missing evidence on an external
    action, hard-blocks the action;
  - **high/medium risk or any external target requires explicit approval**;
  - the engine NEVER consults caller identity (``ARIA_USER_ID`` is attribution only).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aria.actions.models import (
    ActionIntent,
    ActionType,
    ExecutionMode,
    RiskLevel,
    TargetSystem,
    permission_scope_for,
)

_RISK_ORDER = {RiskLevel.low: 0, RiskLevel.medium: 1, RiskLevel.high: 2}

_ACTION_RISK = {
    ActionType.mark_done: RiskLevel.low,
    ActionType.apply_label: RiskLevel.low,
    ActionType.archive_item: RiskLevel.low,
    ActionType.update_status: RiskLevel.low,
    ActionType.mock_external_action: RiskLevel.low,
    ActionType.send_message: RiskLevel.medium,
    ActionType.post_comment: RiskLevel.medium,
    ActionType.create_ticket: RiskLevel.medium,
    ActionType.trigger_webhook: RiskLevel.high,
}

_TARGET_RISK = {
    TargetSystem.internal_mock: RiskLevel.low,
    TargetSystem.teams: RiskLevel.medium,
    TargetSystem.slack: RiskLevel.medium,
    TargetSystem.gmail: RiskLevel.medium,
    TargetSystem.jira: RiskLevel.medium,
    TargetSystem.github: RiskLevel.medium,
    TargetSystem.calendar: RiskLevel.medium,
    TargetSystem.webhook: RiskLevel.high,
}


def _max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    return a if _RISK_ORDER[a] >= _RISK_ORDER[b] else b


class PolicyDecision(BaseModel):
    """The governed verdict for an action. ``allowed`` means 'not hard-blocked'; an
    allowed action still cannot mock-execute without satisfying approval + mode."""
    model_config = ConfigDict(frozen=True)

    allowed: bool
    risk_level: RiskLevel
    approval_required: bool
    evidence_required: bool
    permission_scope: str
    allowed_execution_modes: list[ExecutionMode] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    rollback_note: str = ""
    compensation_note: str = ""

    def mode_allowed(self, mode: ExecutionMode) -> bool:
        return self.allowed and mode in self.allowed_execution_modes


class ActionPolicyEngine:
    """Stateless, deterministic policy evaluation. No I/O, no identity checks."""

    def evaluate(self, intent: ActionIntent) -> PolicyDecision:
        risk = _max_risk(_ACTION_RISK.get(intent.action_type, RiskLevel.high),
                         _TARGET_RISK.get(intent.target_system, RiskLevel.high))
        scope = permission_scope_for(intent.action_type, intent.target_system)
        external = intent.is_external
        evidence_required = external                    # external actions need evidence

        blocked: list[str] = []
        if not intent.source_refs:
            blocked.append("missing source references (deny-by-default)")
        if evidence_required and not intent.evidence_refs:
            blocked.append("external action requires evidence references")

        allowed = not blocked
        # Execution modes (deny-by-default): live is NEVER allowed; mock_live only for
        # internal_mock; dry_run is a safe, write-nothing preview for any target.
        modes: list[ExecutionMode] = []
        if allowed:
            modes.append(ExecutionMode.dry_run)
            if intent.target_system is TargetSystem.internal_mock:
                modes.append(ExecutionMode.mock_live)
            else:
                blocked.append(
                    f"external target '{intent.target_system.value}' is blocked from "
                    "live/mock execution in V3.9 (dry-run preview only)")
        # ``live`` is intentionally never added.

        # The policy is AUTHORITATIVE for approval (it does not inherit the intent's
        # pre-policy default): medium/high risk OR any external target requires it.
        approval_required = (risk is not RiskLevel.low) or external

        rollback = ("No external change was made (dry-run/mock-only); there is nothing to "
                    "roll back.")
        compensation = ("If this were ever a real action, the compensating action would be "
                        f"the inverse of '{intent.action_type.value}' on "
                        f"'{intent.target_system.value}'.")
        return PolicyDecision(
            allowed=allowed, risk_level=risk, approval_required=approval_required,
            evidence_required=evidence_required, permission_scope=scope,
            allowed_execution_modes=modes, blocked_reasons=blocked,
            rollback_note=rollback, compensation_note=compensation,
        )
