"""
Deterministic tests for BudgetTracker (Week 21).
No LLM, no filesystem, no network.
"""
import pytest
from aria.runtime.budget import BudgetTracker


@pytest.fixture()
def tracker():
    t = BudgetTracker(default_budget=10_000)
    yield t
    t.clear_all()


# ── init_task ─────────────────────────────────────────────────────────────────

def test_init_task_sets_budget(tracker):
    tracker.init_task("t-1", budget=5_000)
    assert tracker.remaining("t-1") == 5_000


def test_init_task_uses_default_when_budget_is_none(tracker):
    tracker.init_task("t-2")
    assert tracker.remaining("t-2") == 10_000


def test_init_task_is_idempotent(tracker):
    tracker.init_task("t-3", budget=3_000)
    tracker.init_task("t-3", budget=9_999)   # second call — must not override
    assert tracker.remaining("t-3") == 3_000


def test_init_task_clamps_to_max():
    t = BudgetTracker(default_budget=1_000)
    # _MAX_BUDGET is read from env, default 200_000 — use a huge value to hit it
    from aria.runtime import budget as _bmod
    original_max = _bmod._MAX_BUDGET
    _bmod._MAX_BUDGET = 500
    try:
        t.init_task("t-clamp", budget=999_999)
        assert t.remaining("t-clamp") <= 500
    finally:
        _bmod._MAX_BUDGET = original_max


# ── consume ───────────────────────────────────────────────────────────────────

def test_consume_within_budget_returns_true(tracker):
    tracker.init_task("t-4", budget=1_000)
    assert tracker.consume("t-4", 500) is True


def test_consume_decreases_remaining(tracker):
    tracker.init_task("t-5", budget=1_000)
    tracker.consume("t-5", 300)
    assert tracker.remaining("t-5") == 700


def test_consume_exact_budget_returns_true(tracker):
    tracker.init_task("t-6", budget=1_000)
    assert tracker.consume("t-6", 1_000) is True
    assert tracker.remaining("t-6") == 0


def test_consume_over_budget_returns_false(tracker):
    tracker.init_task("t-7", budget=100)
    assert tracker.consume("t-7", 101) is False


def test_consume_over_budget_does_not_deduct(tracker):
    tracker.init_task("t-8", budget=100)
    tracker.consume("t-8", 101)   # blocked
    assert tracker.remaining("t-8") == 100   # unchanged


def test_consume_sequential_exhausts_budget(tracker):
    tracker.init_task("t-9", budget=300)
    assert tracker.consume("t-9", 100) is True
    assert tracker.consume("t-9", 100) is True
    assert tracker.consume("t-9", 100) is True
    assert tracker.consume("t-9",   1) is False   # exhausted


# ── remaining / used ──────────────────────────────────────────────────────────

def test_remaining_returns_default_for_unknown_task(tracker):
    assert tracker.remaining("never-initialised") == 10_000


def test_used_reflects_consumption(tracker):
    tracker.init_task("t-10", budget=1_000)
    tracker.consume("t-10", 250)
    assert tracker.used("t-10", initial_budget=1_000) == 250


# ── task isolation ────────────────────────────────────────────────────────────

def test_tasks_are_independent(tracker):
    tracker.init_task("t-a", budget=500)
    tracker.init_task("t-b", budget=500)
    tracker.consume("t-a", 400)
    assert tracker.remaining("t-a") == 100
    assert tracker.remaining("t-b") == 500   # unaffected


# ── clear ─────────────────────────────────────────────────────────────────────

def test_clear_removes_task(tracker):
    tracker.init_task("t-11", budget=1_000)
    tracker.clear("t-11")
    assert tracker.remaining("t-11") == 10_000   # falls back to default


def test_clear_all_resets_everything(tracker):
    tracker.init_task("t-12", budget=1_000)
    tracker.init_task("t-13", budget=2_000)
    tracker.clear_all()
    assert tracker.remaining("t-12") == 10_000
    assert tracker.remaining("t-13") == 10_000


# ── P1.3: budget wired into intake and respond ────────────────────────────────

def test_intake_initialises_budget_tracker():
    """intake() must call budget_tracker.init_task() so budget is tracked."""
    from aria.runtime.budget import budget_tracker
    from aria.nodes.intake import intake

    budget_tracker.clear_all()
    state = {
        "raw_input":      "Review my PR",
        "task_status":    "pending",
        "steps_completed": [],
        "data_sensitivity": None,
        "token_budget":    20_000,
    }
    result = intake(state)
    task_id = result["task_id"]
    assert result["token_budget"] == 20_000
    # BudgetTracker must have been initialised for this task
    assert budget_tracker.remaining(task_id) == 20_000
    budget_tracker.clear(task_id)


def test_respond_records_token_budget_used():
    """respond() must set token_budget_used in returned state."""
    from aria.nodes.respond import respond
    from aria.runtime.budget import budget_tracker

    budget_tracker.clear_all()
    task_id = "t-respond-budget"
    budget_tracker.init_task(task_id, 50_000)
    state = {
        "task_id":         task_id,
        "task_type":       "kpi",
        "skill_output":    '{"summary": "CTR dropped"}',
        "routing_reason":  "kpi keyword",
        "audience":        "developer",
        "steps_completed": ["intake", "router", "kpi_node"],
        "token_budget_used": 0,
    }
    result = respond(state)
    assert "token_budget_used" in result
    assert result["token_budget_used"] > 0
    budget_tracker.clear(task_id)
