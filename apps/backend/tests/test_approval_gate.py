"""
Unit tests for the approval gate.

These are deterministic and in-memory — no network, no LLM, no filesystem.
The audit log side-effect is suppressed by the gate's own except-pass guard,
so no ARIA_AUDIT_LOG_PATH override is needed here.
"""
import pytest
from aria.governance import approval_gate


@pytest.fixture(autouse=True)
def clear_gate():
    """Isolate each test — start with an empty in-memory store."""
    approval_gate.clear()
    yield
    approval_gate.clear()


# ── request_approval ──────────────────────────────────────────────────────────

def test_request_creates_pending_entry():
    req = approval_gate.request_approval("task-1", "pr_review", "Review PR #42", "T2")
    assert req.task_id == "task-1"
    assert req.tool_name == "pr_review"
    assert req.status == "pending"
    assert req.request_id  # non-empty UUID string


def test_request_is_idempotent():
    req1 = approval_gate.request_approval("task-2", "kpi", "Investigate CTR drop", "T2")
    req2 = approval_gate.request_approval("task-2", "kpi", "Investigate CTR drop", "T2")
    assert req1.request_id == req2.request_id


def test_get_for_task_returns_all_requests():
    approval_gate.request_approval("task-3", "pr_review", "action A", "T2")
    approval_gate.request_approval("task-3", "ci_cd",    "action B", "T2")
    results = approval_gate.get_for_task("task-3")
    assert len(results) == 2
    tool_names = {r.tool_name for r in results}
    assert tool_names == {"pr_review", "ci_cd"}


def test_get_for_task_returns_empty_for_unknown():
    assert approval_gate.get_for_task("nonexistent-task") == []


# ── approve ───────────────────────────────────────────────────────────────────

def test_approve_changes_status():
    req = approval_gate.request_approval("task-4", "pr_review", "action", "T2")
    updated = approval_gate.approve(req.request_id, approved_by="kunal")
    assert updated.status == "approved"
    assert updated.approved_by == "kunal"
    assert updated.resolved_at is not None


def test_is_approved_true_after_approve():
    req = approval_gate.request_approval("task-5", "pr_review", "action", "T2")
    assert not approval_gate.is_approved("task-5", "pr_review")
    approval_gate.approve(req.request_id)
    assert approval_gate.is_approved("task-5", "pr_review")


def test_approve_nonexistent_returns_none():
    result = approval_gate.approve("does-not-exist")
    assert result is None


# ── reject ────────────────────────────────────────────────────────────────────

def test_reject_changes_status():
    req = approval_gate.request_approval("task-6", "kpi", "action", "T2")
    updated = approval_gate.reject(req.request_id, reason="Wrong metric")
    assert updated.status == "rejected"
    assert updated.rejection_reason == "Wrong metric"
    assert updated.resolved_at is not None


def test_reject_nonexistent_returns_none():
    result = approval_gate.reject("does-not-exist")
    assert result is None


# ── get_pending ───────────────────────────────────────────────────────────────

def test_get_pending_excludes_resolved():
    req_a = approval_gate.request_approval("task-7", "pr_review", "a", "T2")
    req_b = approval_gate.request_approval("task-8", "kpi",       "b", "T2")
    approval_gate.approve(req_a.request_id)
    pending = approval_gate.get_pending()
    ids = [r.request_id for r in pending]
    assert req_b.request_id in ids
    assert req_a.request_id not in ids
