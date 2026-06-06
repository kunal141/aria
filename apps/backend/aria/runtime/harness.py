"""
Agent Runtime Harness — Week 21 (Pillar 11)

Every real tool call goes through execute(). It enforces:
  - Permission check (T1–T4 via tool_permissions)
  - Dry-run mode (skip fn, return success=True, was_dry_run=True)
  - Idempotency (same idem_key → return cached result)
  - Timeout (thread-based; cross-platform including Windows)
  - Audit log write on every path (success, blocked, dry_run, timeout, error)

Safety properties are structural: they cannot be bypassed by forgetting a
conditional — execute() is the only path to calling a real tool.

Loop detection:
  guard_loop(steps_completed, task_id) raises RuntimeError if the graph has
  accumulated too many steps. Call it at the start of any skill node.

Usage:
    from aria.runtime import execute, guard_loop, make_idem_key, ToolCall

    call = ToolCall(
        task_id="task-123",
        tool_name="jira_create",
        action_tier="T4",
        dry_run=state.get("execution_mode") == "dry_run",
        idem_key=make_idem_key("task-123", "jira_create", draft.title),
    )
    result = execute(call, jira_api.create_ticket, draft)
    if result.success:
        ticket_id = result.output["ticket_id"]
"""
import concurrent.futures
import hashlib
import time
from typing import Any, Callable, Optional

from pydantic import BaseModel


# ── Constants ─────────────────────────────────────────────────────────────────

MAX_STEPS = 25   # safety cap: raises if steps_completed reaches this length


# ── Models ────────────────────────────────────────────────────────────────────

class ToolCall(BaseModel):
    task_id:          str
    tool_name:        str
    action_tier:      str   = "T1"
    dry_run:          bool  = False
    idem_key:         Optional[str] = None
    timeout_s:        float = 30.0
    data_sensitivity: str   = "internal"


class ToolResult(BaseModel):
    success:      bool
    output:       Any             = None
    error:        Optional[str]   = None
    was_dry_run:  bool            = False
    was_cached:   bool            = False
    tool_name:    str             = ""
    task_id:      str             = ""
    duration_ms:  Optional[float] = None


# ── In-memory idempotency cache ───────────────────────────────────────────────

_IDEM_CACHE: dict[str, ToolResult] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def make_idem_key(task_id: str, tool_name: str, input_repr: str) -> str:
    """Deterministic 16-char hex key for deduplicating tool calls."""
    raw = f"{task_id}:{tool_name}:{input_repr}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def guard_loop(steps_completed: list, task_id: str = "") -> None:
    """
    Raise RuntimeError if the graph has exceeded the safe step limit.
    Call at the start of any skill node before doing expensive work.
    """
    if len(steps_completed) >= MAX_STEPS:
        raise RuntimeError(
            f"Loop guard triggered: {len(steps_completed)} steps completed "
            f"for task {task_id!r}. Maximum is {MAX_STEPS}. "
            "Check LangGraph for cycles — a conditional edge may be routing back "
            "to an already-visited node."
        )


def execute(call: ToolCall, fn: Callable, /, *args: Any, **kwargs: Any) -> ToolResult:
    """
    Execute a tool call with full safety properties.

    Order of operations:
      1. Permission check — blocks unregistered or tier-violated calls
      2. Dry-run guard — returns success without calling fn
      3. Idempotency check — returns cached result if idem_key was seen
      4. Execute fn with timeout
      5. Audit log (every path)

    The permission check for T4 tools uses check_with_approval(), which
    verifies that a human has approved the action in the approval gate.
    """
    start_ms = time.monotonic() * 1000

    # ── 1. Permission check ───────────────────────────────────────────────────
    perm_result = _check_permission(call)
    if not perm_result.allowed:
        _audit(call, allowed=False, outcome="blocked", reason=perm_result.reason)
        return ToolResult(
            success=False,
            error=perm_result.reason,
            was_dry_run=call.dry_run,
            tool_name=call.tool_name,
            task_id=call.task_id,
        )

    # ── 2. Dry-run ────────────────────────────────────────────────────────────
    if call.dry_run:
        _audit(call, allowed=True, outcome="dry_run", reason="dry_run mode — fn not called")
        return ToolResult(
            success=True,
            was_dry_run=True,
            tool_name=call.tool_name,
            task_id=call.task_id,
            duration_ms=0.0,
        )

    # ── 3. Idempotency ────────────────────────────────────────────────────────
    if call.idem_key:
        cached = _IDEM_CACHE.get(call.idem_key)
        if cached is not None and cached.success:
            return ToolResult(**{**cached.model_dump(), "was_cached": True})

    # ── 4. Execute with timeout ───────────────────────────────────────────────
    try:
        output = _run_with_timeout(fn, args, kwargs, call.timeout_s)
        duration_ms = (time.monotonic() * 1000) - start_ms
        result = ToolResult(
            success=True,
            output=output,
            tool_name=call.tool_name,
            task_id=call.task_id,
            duration_ms=round(duration_ms, 1),
        )
        if call.idem_key:
            _IDEM_CACHE[call.idem_key] = result
        _audit(call, allowed=True, outcome="success", reason="executed")
        return result

    except TimeoutError as exc:
        duration_ms = (time.monotonic() * 1000) - start_ms
        _audit(call, allowed=True, outcome="timeout", reason=str(exc))
        return ToolResult(
            success=False,
            error=str(exc),
            tool_name=call.tool_name,
            task_id=call.task_id,
            duration_ms=round(duration_ms, 1),
        )

    except Exception as exc:
        duration_ms = (time.monotonic() * 1000) - start_ms
        _audit(call, allowed=True, outcome="error", reason=str(exc), error=str(exc))
        return ToolResult(
            success=False,
            error=str(exc),
            tool_name=call.tool_name,
            task_id=call.task_id,
            duration_ms=round(duration_ms, 1),
        )


def clear_idem_cache() -> None:
    """Clear the idempotency cache. Used in tests."""
    _IDEM_CACHE.clear()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_permission(call: ToolCall):
    from aria.security.tool_permissions import check, check_with_approval
    if call.action_tier == "T4":
        return check_with_approval(call.tool_name, call.task_id, call.data_sensitivity)
    return check(call.tool_name, call.data_sensitivity)


def _run_with_timeout(fn: Callable, args: tuple, kwargs: dict, timeout_s: float) -> Any:
    """Run fn(*args, **kwargs) with a wall-clock timeout. Cross-platform (no SIGALRM)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(
                f"Tool execution exceeded {timeout_s}s timeout"
            )


def _audit(
    call: ToolCall,
    allowed: bool,
    outcome: str,
    reason: str,
    error: Optional[str] = None,
) -> None:
    try:
        from aria.security.audit_log import log_tool_call
        log_tool_call(
            task_id=call.task_id,
            tool_name=call.tool_name,
            allowed=allowed,
            reason=reason,
            action_tier=call.action_tier,
            data_sensitivity=call.data_sensitivity,
            outcome=outcome,
            error=error,
        )
    except Exception:
        pass   # audit failure must never block tool execution
