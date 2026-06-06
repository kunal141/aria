"""
Approval Gate v1 — Week 16

In-memory approval queue for T4 (Execute-with-Approval) actions.

Lifecycle:
  1. Skill or node calls request_approval() → creates ApprovalRequest
  2. ARIA pauses, sends approval card to Teams/UI (Week 16+ wires Teams)
  3. Human calls approve() or reject() with the request_id
  4. ARIA resumes — reads status, proceeds or halts

V1 limitations (will improve at Week 21 with full Runtime Harness):
  - In-memory only — requests are lost on process restart
  - No async wait — callers must poll or re-enter after approval
  - No timeout/escalation — added at Week 21
  - No persistence — PostgreSQL-backed queue at Week 21

Why approval gate matters:
  T3 (Draft) = ARIA creates a draft; human edits and sends.
  T4 (Execute-with-Approval) = ARIA does the real action after explicit approval.
  Without an approval gate, T4 tools are effectively T5 (autonomous) — dangerous.
  The gate is the governance contract. No gate = no T4.

Example flow (PR comment):
  skill_node → check_permission("github_pr_comment") → check_approval_gate(task_id)
             → if no approval: request_approval() → return ApprovalRequest to caller
             → caller sends approval card to Teams
             → human clicks Approve in Teams card
             → Teams webhook calls approve(request_id)
             → skill_node retries → approval found → executes
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Literal

from pydantic import BaseModel


# ── Models ────────────────────────────────────────────────────────────────────

ApprovalStatus = Literal["pending", "approved", "rejected"]


class ApprovalRequest(BaseModel):
    request_id: str
    task_id: str
    tool_name: str
    proposed_action: str           # human-readable description of what will happen
    action_tier: str               # "T4" or "T5"
    status: ApprovalStatus = "pending"
    created_at: str
    resolved_at: Optional[str] = None
    approved_by: Optional[str] = None
    rejection_reason: Optional[str] = None


# ── In-memory store ───────────────────────────────────────────────────────────

_requests: dict[str, ApprovalRequest] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def request_approval(
    task_id: str,
    tool_name: str,
    proposed_action: str,
    action_tier: str = "T4",
) -> ApprovalRequest:
    """
    Create a pending approval request. Returns the request so the caller
    can send it to Teams / display in UI.

    If an identical pending request already exists for this task+tool,
    returns the existing one (idempotent).
    """
    # Idempotency: return existing pending request for same task+tool
    for req in _requests.values():
        if req.task_id == task_id and req.tool_name == tool_name and req.status == "pending":
            return req

    req = ApprovalRequest(
        request_id=str(uuid.uuid4()),
        task_id=task_id,
        tool_name=tool_name,
        proposed_action=proposed_action,
        action_tier=action_tier,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _requests[req.request_id] = req

    # Log to audit trail
    try:
        from aria.security.audit_log import log_tool_call
        log_tool_call(
            task_id=task_id,
            tool_name=tool_name,
            allowed=False,             # not yet approved
            reason=f"Approval requested for {action_tier} action",
            action_tier=action_tier,
            outcome="pending_approval",
        )
    except Exception:
        pass

    return req


def approve(
    request_id: str,
    approved_by: str = "human",
) -> Optional[ApprovalRequest]:
    """
    Approve a pending request. Returns updated request, or None if not found.
    """
    req = _requests.get(request_id)
    if not req or req.status != "pending":
        return req

    req.status      = "approved"
    req.approved_by = approved_by
    req.resolved_at = datetime.now(timezone.utc).isoformat()

    try:
        from aria.security.audit_log import log_tool_call
        log_tool_call(
            task_id=req.task_id,
            tool_name=req.tool_name,
            allowed=True,
            reason=f"Approved by {approved_by}",
            action_tier=req.action_tier,
            outcome="approved",
        )
    except Exception:
        pass

    return req


def reject(
    request_id: str,
    reason: str = "",
) -> Optional[ApprovalRequest]:
    """
    Reject a pending request. Returns updated request, or None if not found.
    """
    req = _requests.get(request_id)
    if not req or req.status != "pending":
        return req

    req.status           = "rejected"
    req.rejection_reason = reason
    req.resolved_at      = datetime.now(timezone.utc).isoformat()

    try:
        from aria.security.audit_log import log_security_event
        log_security_event(
            req.task_id,
            "approval_rejected",
            f"Tool '{req.tool_name}' rejected: {reason}",
            severity="info",
        )
    except Exception:
        pass

    return req


def is_approved(task_id: str, tool_name: str) -> bool:
    """Check if an approved request exists for task+tool."""
    for req in _requests.values():
        if req.task_id == task_id and req.tool_name == tool_name and req.status == "approved":
            return True
    return False


def get(request_id: str) -> Optional[ApprovalRequest]:
    return _requests.get(request_id)


def get_pending() -> list[ApprovalRequest]:
    return [r for r in _requests.values() if r.status == "pending"]


def get_for_task(task_id: str) -> list[ApprovalRequest]:
    return [r for r in _requests.values() if r.task_id == task_id]


def clear() -> None:
    """Clear all requests. Used in tests only."""
    _requests.clear()
