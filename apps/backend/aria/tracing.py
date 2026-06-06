"""
LangSmith Tracing Helpers — Week 13

Thin wrapper around LangSmith client for:
  - Tagging runs with ARIA metadata (task_id, task_type, skill_name, week, provider)
  - Logging human feedback (approve/reject) for the fine-tuning pipeline
  - Capturing run URLs for the Work Ledger

Pattern:
  1. Decorate skill functions with @traceable — traces appear in LangSmith automatically
  2. Call log_feedback() from MemoryManager.record_outcome() — every approval/rejection
     shows up in LangSmith alongside the trace that produced the output
  3. Run URL is stored in Work Ledger so you can jump from a ledger entry to its trace

Why this matters: LangSmith traces are the observability layer. Without them, debugging
a wrong skill output means guessing. With them, you can replay the exact prompt, see every
token, compare runs side-by-side, and build rubric-based regression tests.
"""
import os
from typing import Optional


# ── @traceable decorator ──────────────────────────────────────────────────────
# Import from langsmith if available; fall back to no-op so skills work without
# LangSmith configured (dev mode, offline, no API key).

try:
    from langsmith import traceable  # noqa: F401  (re-exported for skill imports)
    _LANGSMITH_AVAILABLE = True
except ImportError:
    _LANGSMITH_AVAILABLE = False

    def traceable(
        run_type: str = "chain",
        name: Optional[str] = None,
        tags: Optional[list] = None,
        metadata: Optional[dict] = None,
    ):
        """No-op @traceable when langsmith not installed."""
        def decorator(fn):
            return fn
        return decorator


# ── LangSmith client ──────────────────────────────────────────────────────────

def get_client():
    """
    Return a LangSmith Client if tracing is enabled, else None.
    Always safe to call — returns None gracefully when not configured.
    """
    if not _LANGSMITH_AVAILABLE:
        return None
    if os.getenv("LANGCHAIN_TRACING_V2") != "true":
        return None
    try:
        from langsmith import Client
        return Client()
    except Exception:
        return None


# ── Feedback logging ──────────────────────────────────────────────────────────

def log_feedback(
    run_id: str,
    approved: bool,
    correction: Optional[str] = None,
    key: str = "user_approval",
) -> None:
    """
    Log human feedback to a LangSmith run.

    approved=True  → score=1.0  → positive SFT training example
    approved=False → score=0.0  → DPO negative example (correction captured in comment)

    Called automatically from MemoryManager.record_outcome() so every
    approve/reject action in the Work Ledger is paired with its trace.
    """
    client = get_client()
    if not client or not run_id:
        return
    try:
        client.create_feedback(
            run_id=run_id,
            key=key,
            score=1.0 if approved else 0.0,
            comment=correction,
        )
    except Exception:
        pass  # tracing is always non-critical — never block task execution


# ── Run URL ───────────────────────────────────────────────────────────────────

def get_project_url() -> Optional[str]:
    """Return the LangSmith project dashboard URL."""
    if not os.getenv("LANGCHAIN_API_KEY"):
        return None
    project = os.getenv("LANGCHAIN_PROJECT", "ARIA")
    return f"https://smith.langchain.com/projects/p/{project}"


def get_run_url(run_id: str) -> Optional[str]:
    """Return the LangSmith UI URL for a specific run."""
    if not run_id or not os.getenv("LANGCHAIN_API_KEY"):
        return None
    return f"https://smith.langchain.com/runs/{run_id}"


# ── Run metadata helper ───────────────────────────────────────────────────────

def aria_metadata(
    task_id: str,
    task_type: Optional[str] = None,
    skill_name: Optional[str] = None,
    week: int = 13,
) -> dict:
    """
    Build standard ARIA metadata dict for @traceable calls.
    Attach this to every traced run so LangSmith runs are filterable
    by task_id, skill, and week without digging into raw inputs.

    Usage:
      @traceable(
          run_type="chain",
          name="pr_review_v1",
          tags=["skill", "pr_review"],
          metadata=aria_metadata(task_id=input.task_id, task_type="pr_review", skill_name="pr_review", week=7),
      )
    """
    return {
        "task_id":    task_id,
        "task_type":  task_type or "unknown",
        "skill_name": skill_name or "unknown",
        "week":       week,
        "provider":   os.getenv("LLM_PROVIDER", "anthropic"),
        "model":      os.getenv("SMART_LLM_MODEL") or os.getenv("LLM_MODEL", "default"),
    }
