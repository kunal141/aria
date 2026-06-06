"""
Token Budget Tracker — Week 21

Enforces a per-task token ceiling to prevent runaway LLM costs.
Call consume() before any LLM invocation; abort if it returns False.

V1 defaults (configurable via env vars):
  ARIA_DEFAULT_TOKEN_BUDGET = 50000
  ARIA_MAX_TOKEN_BUDGET     = 200000

The tracker is a process-level singleton (budget_tracker). Skills import
it directly; ARIAState carries token_budget / token_budget_used for
observability but the tracker is the authoritative source.
"""
import os
from typing import Optional


_DEFAULT_BUDGET = int(os.getenv("ARIA_DEFAULT_TOKEN_BUDGET", "50000"))
_MAX_BUDGET     = int(os.getenv("ARIA_MAX_TOKEN_BUDGET",     "200000"))


class BudgetTracker:
    """In-memory per-task token budget store."""

    def __init__(self, default_budget: int = _DEFAULT_BUDGET):
        self._default  = default_budget
        self._budgets: dict[str, int] = {}   # task_id → tokens_remaining

    def init_task(self, task_id: str, budget: Optional[int] = None) -> int:
        """
        Initialise budget for a task. Safe to call multiple times — only
        sets the budget if the task has not been seen before.
        Returns the effective budget.
        """
        if task_id not in self._budgets:
            effective = min(budget or self._default, _MAX_BUDGET)
            self._budgets[task_id] = effective
        return self._budgets[task_id]

    def consume(self, task_id: str, tokens: int) -> bool:
        """
        Deduct tokens from the task's budget.
        Returns True if the consumption is within budget, False if exceeded.
        Does NOT deduct when returning False — the call is blocked, not penalised.
        """
        remaining = self._budgets.get(task_id, self._default)
        if tokens > remaining:
            return False
        self._budgets[task_id] = remaining - tokens
        return True

    def remaining(self, task_id: str) -> int:
        """Tokens remaining for the task."""
        return self._budgets.get(task_id, self._default)

    def used(self, task_id: str, initial_budget: Optional[int] = None) -> int:
        """Tokens consumed so far (requires knowing the initial budget)."""
        initial = initial_budget or self._default
        return initial - self._budgets.get(task_id, initial)

    def clear(self, task_id: str) -> None:
        """Remove a task's budget entry. Used after task completion or in tests."""
        self._budgets.pop(task_id, None)

    def clear_all(self) -> None:
        """Clear all budgets. Used in tests."""
        self._budgets.clear()


# ── Module-level singleton ────────────────────────────────────────────────────

budget_tracker = BudgetTracker()
