"""
aria.actions — V3.9 Controlled Live Execution Layer.

A governed ACTION GATE: ARIA proposes external-action intents, previews them,
obtains payload-bound approval, and executes them — but only in ``dry_run`` (writes
nothing) or ``mock_live`` (internal_mock only; writes only ARIA's local receipt).
Live execution is DENY-BY-DEFAULT and disabled; no real connector write, network
call, or external send happens in V3.9.

Approval is bound to an action's id + payload hash + scope; a changed payload or
widened scope (or an expired approval) silently invalidates it (re-approval required).

A SEPARATE package — importing it never drags in V1 LLM skills, and importing a V1
skill never loads this layer.
"""
from aria.actions.executors import (
    BlockedLiveExecutor,
    DryRunExecutor,
    ExecutorError,
    LiveExecutionBlocked,
    MockLiveExecutor,
    get_executor,
)
from aria.actions.models import (
    ACTION_BOUNDARY,
    EXTERNAL_TARGETS,
    INTERNAL_TARGET,
    ActionApproval,
    ActionIntent,
    ActionReceipt,
    ActionStatus,
    ActionType,
    ApprovalDecision,
    ExecutionMode,
    RiskLevel,
    TargetSystem,
    payload_hash,
    permission_scope_for,
)
from aria.actions.policy import ActionPolicyEngine, PolicyDecision
from aria.actions.service import ActionService
from aria.actions.store import (
    ActionExecutionViolation,
    ActionIntegrityError,
    ActionNotFound,
    ActionSecurityError,
    ActionStore,
    InvalidActionTransition,
)

__all__ = [
    "ActionService",
    "ActionStore",
    "ActionNotFound",
    "ActionSecurityError",
    "ActionIntegrityError",
    "ActionExecutionViolation",
    "InvalidActionTransition",
    "ActionPolicyEngine",
    "PolicyDecision",
    "ActionIntent",
    "ActionApproval",
    "ActionReceipt",
    "ActionType",
    "TargetSystem",
    "ActionStatus",
    "ApprovalDecision",
    "ExecutionMode",
    "RiskLevel",
    "INTERNAL_TARGET",
    "EXTERNAL_TARGETS",
    "payload_hash",
    "permission_scope_for",
    "ACTION_BOUNDARY",
    "DryRunExecutor",
    "MockLiveExecutor",
    "BlockedLiveExecutor",
    "get_executor",
    "ExecutorError",
    "LiveExecutionBlocked",
]
