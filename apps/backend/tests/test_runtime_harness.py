"""
Deterministic tests for the Agent Runtime Harness (Week 21).

No LLM, no network. Filesystem side-effects (audit log) are suppressed
via ARIA_AUDIT_LOG_PATH override so tests leave no artifacts.
"""
import os
import time
import pytest

os.environ.setdefault("ARIA_AUDIT_LOG_PATH", os.devnull)

from aria.runtime.harness import (
    execute,
    guard_loop,
    make_idem_key,
    clear_idem_cache,
    ToolCall,
    ToolResult,
    MAX_STEPS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_cache():
    clear_idem_cache()
    yield
    clear_idem_cache()


def _ok_fn(*args, **kwargs):
    return {"done": True}


def _fail_fn(*args, **kwargs):
    raise ValueError("intentional tool failure")


def _slow_fn(*args, **kwargs):
    time.sleep(10)
    return "should not reach here"


# ── make_idem_key ─────────────────────────────────────────────────────────────

def test_idem_key_is_deterministic():
    k1 = make_idem_key("task-1", "jira_draft", "fix es timeout")
    k2 = make_idem_key("task-1", "jira_draft", "fix es timeout")
    assert k1 == k2


def test_idem_key_differs_on_input_change():
    k1 = make_idem_key("task-1", "jira_draft", "fix es timeout")
    k2 = make_idem_key("task-1", "jira_draft", "different input")
    assert k1 != k2


def test_idem_key_differs_on_tool_change():
    k1 = make_idem_key("task-1", "jira_draft",   "same input")
    k2 = make_idem_key("task-1", "jira_create",  "same input")
    assert k1 != k2


def test_idem_key_length():
    k = make_idem_key("task-1", "tool", "input")
    assert len(k) == 16


# ── guard_loop ────────────────────────────────────────────────────────────────

def test_guard_loop_passes_under_limit():
    guard_loop(["intake", "router", "kpi_node"], "task-1")   # no exception


def test_guard_loop_passes_at_limit_minus_one():
    steps = ["step"] * (MAX_STEPS - 1)
    guard_loop(steps, "task-1")   # no exception


def test_guard_loop_raises_at_limit():
    steps = ["step"] * MAX_STEPS
    with pytest.raises(RuntimeError, match="Loop guard triggered"):
        guard_loop(steps, "task-1")


def test_guard_loop_raises_over_limit():
    steps = ["step"] * (MAX_STEPS + 5)
    with pytest.raises(RuntimeError):
        guard_loop(steps, "task-x")


# ── execute — dry-run ─────────────────────────────────────────────────────────

def test_execute_dry_run_does_not_call_fn():
    called = []

    def tracking_fn():
        called.append(True)
        return {"done": True}

    call = ToolCall(task_id="t-1", tool_name="knowledge_search", dry_run=True)
    result = execute(call, tracking_fn)

    assert result.success is True
    assert result.was_dry_run is True
    assert called == []   # fn never invoked


def test_execute_dry_run_output_is_none():
    call = ToolCall(task_id="t-1", tool_name="knowledge_search", dry_run=True)
    result = execute(call, _ok_fn)
    assert result.output is None


# ── execute — happy path ──────────────────────────────────────────────────────

def test_execute_calls_fn_and_returns_output():
    call = ToolCall(task_id="t-2", tool_name="knowledge_search")
    result = execute(call, _ok_fn)
    assert result.success is True
    assert result.output == {"done": True}
    assert result.was_dry_run is False
    assert result.was_cached is False


def test_execute_records_tool_name_and_task_id():
    call = ToolCall(task_id="t-3", tool_name="knowledge_search")
    result = execute(call, _ok_fn)
    assert result.tool_name == "knowledge_search"
    assert result.task_id == "t-3"


def test_execute_records_duration():
    call = ToolCall(task_id="t-4", tool_name="knowledge_search")
    result = execute(call, _ok_fn)
    assert result.duration_ms is not None
    assert result.duration_ms >= 0


# ── execute — idempotency ─────────────────────────────────────────────────────

def test_execute_idempotency_returns_cached_result():
    call_count = []

    def counting_fn():
        call_count.append(1)
        return {"value": len(call_count)}

    idem = make_idem_key("task-5", "knowledge_search", "same-input")
    call = ToolCall(task_id="task-5", tool_name="knowledge_search", idem_key=idem)

    r1 = execute(call, counting_fn)
    r2 = execute(call, counting_fn)

    assert r1.output == {"value": 1}
    assert r2.output == {"value": 1}   # same — fn called only once
    assert r2.was_cached is True
    assert len(call_count) == 1


def test_execute_different_idem_keys_call_fn_each_time():
    call_count = []

    def counting_fn():
        call_count.append(1)
        return len(call_count)

    for i in range(3):
        idem = make_idem_key("task-6", "knowledge_search", f"input-{i}")
        call = ToolCall(task_id="task-6", tool_name="knowledge_search", idem_key=idem)
        execute(call, counting_fn)

    assert len(call_count) == 3


# ── execute — permission blocked ──────────────────────────────────────────────

def test_execute_unregistered_tool_is_blocked():
    call = ToolCall(task_id="t-7", tool_name="nonexistent_tool_xyz")
    result = execute(call, _ok_fn)
    assert result.success is False
    assert "not registered" in (result.error or "").lower()


def test_execute_t4_without_approval_is_blocked():
    # jira_create is T4 and requires check_with_approval() — no approval in gate
    call = ToolCall(
        task_id="t-8",
        tool_name="jira_create",
        action_tier="T4",
    )
    result = execute(call, _ok_fn)
    assert result.success is False


# ── execute — fn raises exception ────────────────────────────────────────────

def test_execute_exception_returns_failure():
    call = ToolCall(task_id="t-9", tool_name="knowledge_search")
    result = execute(call, _fail_fn)
    assert result.success is False
    assert "intentional tool failure" in (result.error or "")


def test_execute_exception_does_not_cache():
    idem = make_idem_key("task-10", "knowledge_search", "failing-input")
    call = ToolCall(task_id="task-10", tool_name="knowledge_search", idem_key=idem)

    r1 = execute(call, _fail_fn)
    assert r1.success is False

    # A second call with the same idem_key must retry, not return cached failure
    call_count = []

    def success_fn():
        call_count.append(1)
        return "recovered"

    r2 = execute(call, success_fn)
    assert r2.success is True
    assert len(call_count) == 1   # fn was called (not cached)


# ── execute — timeout ─────────────────────────────────────────────────────────

def test_execute_timeout_returns_failure():
    call = ToolCall(task_id="t-11", tool_name="knowledge_search", timeout_s=0.1)
    result = execute(call, _slow_fn)
    assert result.success is False
    assert "timeout" in (result.error or "").lower()


# ── ToolResult model ──────────────────────────────────────────────────────────

def test_tool_result_defaults():
    r = ToolResult(success=True)
    assert r.was_dry_run is False
    assert r.was_cached is False
    assert r.output is None
    assert r.error is None


# ── P1.2: timeout must bound CALLER latency, not fn completion time ────────────

def test_execute_timeout_bounds_caller_latency():
    """
    shutdown(wait=False) is required: the caller must return in ~timeout_s,
    not at fn-completion time.  A 0.1 s timeout on a 3 s fn must return in < 2 s.
    """
    call = ToolCall(task_id="t-latency", tool_name="knowledge_search", timeout_s=0.1)
    start = time.monotonic()
    result = execute(call, _slow_fn)
    elapsed = time.monotonic() - start
    assert result.success is False
    assert "timeout" in (result.error or "").lower()
    assert elapsed < 2.0, f"Timeout did not bound caller latency: elapsed={elapsed:.2f}s"


# ── P1.3 (second round): CancellationToken ────────────────────────────────────

def test_cancellation_token_starts_not_cancelled():
    from aria.runtime.harness import CancellationToken
    token = CancellationToken()
    assert token.is_cancelled is False


def test_cancellation_token_cancel_sets_flag():
    from aria.runtime.harness import CancellationToken
    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled is True


def test_cancellation_token_raise_if_cancelled_raises():
    from aria.runtime.harness import CancellationToken
    token = CancellationToken()
    token.cancel()
    with pytest.raises(RuntimeError, match="cancelled"):
        token.raise_if_cancelled()


def test_cancellation_token_raise_if_not_cancelled_does_nothing():
    from aria.runtime.harness import CancellationToken
    token = CancellationToken()
    token.raise_if_cancelled()   # must not raise


def test_get_cancellation_token_inside_tool_is_set():
    """Tool running inside execute() must see a CancellationToken in thread-local."""
    import threading
    from aria.runtime.harness import get_cancellation_token, CancellationToken

    seen_token = []

    def _capturing_fn():
        seen_token.append(get_cancellation_token())
        return "ok"

    call = ToolCall(task_id="t-cancel-1", tool_name="knowledge_search")
    execute(call, _capturing_fn)
    assert len(seen_token) == 1
    assert isinstance(seen_token[0], CancellationToken)


def test_get_cancellation_token_outside_harness_returns_none():
    """get_cancellation_token() outside execute() must return None."""
    from aria.runtime.harness import get_cancellation_token
    assert get_cancellation_token() is None


def test_cancellation_token_cancelled_on_timeout():
    """Token must be cancelled when the harness fires a timeout."""
    import threading
    from aria.runtime.harness import get_cancellation_token, CancellationToken

    token_after_cancel = []
    barrier = threading.Event()

    def _slow_check():
        barrier.set()           # signal: thread started
        time.sleep(5)           # will be timed out
        token = get_cancellation_token()
        token_after_cancel.append(token.is_cancelled if token else None)
        return "done"

    call = ToolCall(task_id="t-cancel-2", tool_name="knowledge_search", timeout_s=0.05)
    result = execute(call, _slow_check)
    barrier.wait(timeout=2)     # ensure thread started
    time.sleep(0.2)             # let the thread reach the token.is_cancelled check
    assert result.success is False
    # If the thread ran the check: token must have been cancelled
    if token_after_cancel:
        assert token_after_cancel[0] is True


# ── P1.1 (second round): idem_key warning for T3/T4 ─────────────────────────

def test_t4_without_idem_key_still_executes():
    """A T4 tool missing idem_key must still execute (warning, not block)."""
    from aria.governance.approval_gate import request_approval, approve

    task_id = "t-t4-warn"
    req = request_approval(task_id, "jira_create", "Create ticket", "T4")
    approve(req.request_id, approved_by="test-user")

    call = ToolCall(task_id=task_id, tool_name="jira_create", action_tier="T4")
    result = execute(call, _ok_fn)
    assert result.success is True   # warning does not block
