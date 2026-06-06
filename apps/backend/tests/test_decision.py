"""
Deterministic tests for Decision Intelligence — Week 24 (Pillar 20).
No LLM, no network. All tests are pure-Python.
"""
import math
import pytest

from aria.decision.models import DecisionOption, DecisionMatrix, DecisionResult
from aria.decision.scorer import score_option, rank_options, predict_approval, release_risk_score
from aria.decision.lats import LATSNode, LATSTree, run_lats
from aria.decision.engine import next_best_action


# ── helpers ───────────────────────────────────────────────────────────────────

def _opt(
    option_id="opt-1",
    action="Do something",
    rationale="because",
    risk_score=0.2,
    confidence=0.8,
    cost_estimate="low",
    approval_likelihood=0.7,
) -> DecisionOption:
    return DecisionOption(
        option_id=option_id,
        action=action,
        rationale=rationale,
        risk_score=risk_score,
        confidence=confidence,
        cost_estimate=cost_estimate,
        approval_likelihood=approval_likelihood,
    )


def _two_options():
    """opt-A is clearly better (low risk, high confidence)."""
    a = _opt(option_id="opt-A", risk_score=0.1, confidence=0.9, approval_likelihood=0.85)
    b = _opt(option_id="opt-B", risk_score=0.6, confidence=0.4, approval_likelihood=0.3)
    return a, b


# ── DecisionOption ─────────────────────────────────────────────────────────────

def test_decision_option_fields():
    o = _opt()
    assert o.option_id == "opt-1"
    assert o.action == "Do something"
    assert o.risk_score == pytest.approx(0.2)
    assert o.confidence == pytest.approx(0.8)
    assert o.cost_estimate == "low"
    assert o.approval_likelihood == pytest.approx(0.7)


def test_decision_option_clamps_risk_above_1():
    o = _opt(risk_score=1.5)
    assert o.risk_score == pytest.approx(1.0)


def test_decision_option_clamps_confidence_below_0():
    o = _opt(confidence=-0.5)
    assert o.confidence == pytest.approx(0.0)


def test_decision_option_clamps_approval_likelihood():
    o = _opt(approval_likelihood=2.0)
    assert o.approval_likelihood == pytest.approx(1.0)


def test_decision_option_cost_estimate_default():
    o = DecisionOption(
        option_id="x", action="y", rationale="z",
        risk_score=0.0, confidence=1.0, approval_likelihood=1.0,
    )
    assert o.cost_estimate == "medium"


def test_decision_option_serialises():
    o = _opt()
    d = o.model_dump()
    assert "option_id" in d
    assert "risk_score" in d
    assert "approval_likelihood" in d


# ── DecisionMatrix ─────────────────────────────────────────────────────────────

def test_decision_matrix_fields():
    a, b = _two_options()
    m = DecisionMatrix(
        task_id="t-1",
        task_description="Which approach?",
        options=[a, b],
        recommended_option_id="opt-A",
        reasoning="Lower risk",
    )
    assert m.task_id == "t-1"
    assert len(m.options) == 2
    assert m.recommended_option_id == "opt-A"


def test_decision_matrix_serialises():
    a, _ = _two_options()
    m = DecisionMatrix(
        task_id="t-2",
        task_description="desc",
        options=[a],
        recommended_option_id="opt-A",
        reasoning="ok",
    )
    d = m.model_dump()
    assert "options" in d
    assert d["task_id"] == "t-2"


# ── DecisionResult ─────────────────────────────────────────────────────────────

def test_decision_result_defaults():
    a, _ = _two_options()
    m = DecisionMatrix(
        task_id="t-3", task_description="d", options=[a],
        recommended_option_id="opt-A", reasoning="r",
    )
    r = DecisionResult(task_id="t-3", selected_option=a, matrix=m)
    assert r.version == "v1"
    assert r.lats_iterations == 0
    assert r.method == "greedy"


def test_decision_result_serialises():
    a, _ = _two_options()
    m = DecisionMatrix(
        task_id="t-4", task_description="d", options=[a],
        recommended_option_id="opt-A", reasoning="r",
    )
    r = DecisionResult(task_id="t-4", selected_option=a, matrix=m, lats_iterations=5, method="lats")
    d = r.model_dump()
    assert d["lats_iterations"] == 5
    assert d["method"] == "lats"


# ── score_option ──────────────────────────────────────────────────────────────

def test_score_option_perfect():
    o = _opt(confidence=1.0, approval_likelihood=1.0, risk_score=0.0)
    assert score_option(o) == pytest.approx(1.0)


def test_score_option_zero():
    o = _opt(confidence=0.0, approval_likelihood=0.0, risk_score=1.0)
    assert score_option(o) == pytest.approx(0.0)


def test_score_option_weights():
    o = _opt(confidence=0.8, approval_likelihood=0.6, risk_score=0.2)
    expected = 0.8 * 0.4 + 0.6 * 0.4 + (1.0 - 0.2) * 0.2
    assert score_option(o) == pytest.approx(expected, abs=0.001)


def test_score_option_returns_float():
    assert isinstance(score_option(_opt()), float)


# ── rank_options ──────────────────────────────────────────────────────────────

def test_rank_options_best_first():
    a, b = _two_options()
    ranked = rank_options([b, a])  # pass in reverse order
    assert ranked[0].option_id == "opt-A"
    assert ranked[1].option_id == "opt-B"


def test_rank_options_single_element():
    a = _opt()
    ranked = rank_options([a])
    assert ranked[0].option_id == "opt-1"


def test_rank_options_equal_score_both_returned():
    a = _opt(option_id="a", confidence=0.5, approval_likelihood=0.5, risk_score=0.5)
    b = _opt(option_id="b", confidence=0.5, approval_likelihood=0.5, risk_score=0.5)
    ranked = rank_options([a, b])
    assert len(ranked) == 2


def test_rank_options_preserves_all_options():
    opts = [_opt(option_id=f"opt-{i}", confidence=i / 10) for i in range(5)]
    ranked = rank_options(opts)
    assert len(ranked) == 5


# ── predict_approval ──────────────────────────────────────────────────────────

def test_predict_approval_high_confidence_low_risk():
    o = _opt(confidence=0.9, risk_score=0.1, cost_estimate="low")
    p = predict_approval(o)
    assert 0.0 <= p <= 1.0
    assert p > 0.5


def test_predict_approval_low_confidence_high_risk():
    o = _opt(confidence=0.3, risk_score=0.9, cost_estimate="high")
    p = predict_approval(o)
    assert p == pytest.approx(0.0)   # clamped at 0


def test_predict_approval_clamped_max():
    o = _opt(confidence=1.0, risk_score=0.0, cost_estimate="low")
    assert predict_approval(o) <= 1.0


def test_predict_approval_clamped_min():
    o = _opt(confidence=0.0, risk_score=1.0, cost_estimate="high")
    assert predict_approval(o) >= 0.0


def test_predict_approval_cost_penalty_ordering():
    base = dict(confidence=0.8, risk_score=0.2, approval_likelihood=0.7)
    p_low  = predict_approval(_opt(**base, cost_estimate="low"))
    p_med  = predict_approval(_opt(**base, cost_estimate="medium"))
    p_high = predict_approval(_opt(**base, cost_estimate="high"))
    assert p_low >= p_med >= p_high


# ── release_risk_score ────────────────────────────────────────────────────────

def test_release_risk_score_empty():
    assert release_risk_score([]) == 0.0


def test_release_risk_score_single():
    o = _opt(risk_score=0.6)
    assert release_risk_score([o]) == pytest.approx(0.6)


def test_release_risk_score_mean():
    a = _opt(option_id="a", risk_score=0.2)
    b = _opt(option_id="b", risk_score=0.8)
    assert release_risk_score([a, b]) == pytest.approx(0.5)


# ── LATSNode ──────────────────────────────────────────────────────────────────

def test_lats_node_unvisited_uct_is_inf():
    node = LATSNode(option=_opt())
    assert node.uct_score() == float("inf")


def test_lats_node_update_increments_visits():
    node = LATSNode(option=_opt())
    node.update(0.8)
    assert node.visits == 1
    assert node.value == pytest.approx(0.8)


def test_lats_node_mean_value_unvisited():
    node = LATSNode(option=_opt())
    assert node.mean_value == 0.0


def test_lats_node_mean_value_after_update():
    node = LATSNode(option=_opt())
    node.update(0.6)
    node.update(0.8)
    assert node.mean_value == pytest.approx(0.7)


def test_lats_node_backpropagation_to_parent():
    parent = LATSNode(option=_opt(option_id="parent"))
    child  = LATSNode(option=_opt(option_id="child"), parent=parent)
    child.update(1.0)
    assert parent.visits == 1
    assert parent.value  == pytest.approx(1.0)


def test_lats_node_uct_finite_after_visit():
    node = LATSNode(option=_opt())
    node.update(0.5)
    assert math.isfinite(node.uct_score())


# ── LATSTree ──────────────────────────────────────────────────────────────────

def test_lats_tree_empty_options_raises():
    with pytest.raises(ValueError):
        LATSTree(options=[])


def test_lats_tree_single_option_returns_it():
    a = _opt(option_id="only")
    tree = LATSTree(options=[a])
    best = tree.run(max_iterations=5)
    assert best.option_id == "only"


def test_lats_tree_selects_best_option():
    a, b = _two_options()
    tree = LATSTree(options=[a, b])
    best = tree.run(max_iterations=20)
    assert best.option_id == "opt-A"


def test_lats_tree_iterations_count():
    a, b = _two_options()
    tree = LATSTree(options=[a, b])
    tree.run(max_iterations=7)
    assert tree.iterations == 7


def test_lats_tree_step_increments_iteration():
    tree = LATSTree(options=[_opt()])
    tree.step()
    assert tree.iterations == 1


# ── run_lats ──────────────────────────────────────────────────────────────────

def test_run_lats_returns_tuple():
    a, b = _two_options()
    result = run_lats([a, b], max_iterations=10)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_run_lats_best_option_type():
    a, _ = _two_options()
    best, _ = run_lats([a], max_iterations=5)
    assert isinstance(best, DecisionOption)


def test_run_lats_iterations_match_max():
    a, b = _two_options()
    _, iters = run_lats([a, b], max_iterations=8)
    assert iters == 8


def test_run_lats_picks_better_option():
    a, b = _two_options()
    best, _ = run_lats([a, b], max_iterations=30)
    assert best.option_id == "opt-A"


def test_run_lats_custom_evaluator():
    a = _opt(option_id="a", risk_score=0.9, confidence=0.1)
    b = _opt(option_id="b", risk_score=0.1, confidence=0.9)
    # Custom: prefer lowest risk
    best, _ = run_lats([a, b], evaluator=lambda o: 1.0 - o.risk_score, max_iterations=20)
    assert best.option_id == "b"


# ── next_best_action ──────────────────────────────────────────────────────────

def test_next_best_action_returns_result():
    a, b = _two_options()
    r = next_best_action("task-1", "Which approach?", [a, b])
    assert isinstance(r, DecisionResult)


def test_next_best_action_has_correct_task_id():
    a, _ = _two_options()
    r = next_best_action("task-99", "desc", [a])
    assert r.task_id == "task-99"


def test_next_best_action_greedy_selects_best():
    a, b = _two_options()
    r = next_best_action("t", "desc", [a, b], method="greedy")
    assert r.selected_option.option_id == "opt-A"


def test_next_best_action_lats_selects_best():
    a, b = _two_options()
    r = next_best_action("t", "desc", [a, b], method="lats", max_iterations=30)
    assert r.selected_option.option_id == "opt-A"


def test_next_best_action_mock_returns_first():
    a, b = _two_options()
    r = next_best_action("t", "desc", [a, b], method="mock")
    assert r.selected_option.option_id == "opt-A"


def test_next_best_action_empty_options_returns_result():
    r = next_best_action("t", "desc", [])
    assert isinstance(r, DecisionResult)
    assert r.selected_option.option_id == "none"


def test_next_best_action_method_recorded():
    a, _ = _two_options()
    r = next_best_action("t", "desc", [a], method="lats")
    assert r.method == "lats"


def test_next_best_action_lats_records_iterations():
    a, b = _two_options()
    r = next_best_action("t", "desc", [a, b], method="lats", max_iterations=12)
    assert r.lats_iterations == 12


def test_next_best_action_matrix_contains_all_options():
    a, b = _two_options()
    r = next_best_action("t", "desc", [a, b])
    assert len(r.matrix.options) == 2


def test_next_best_action_version():
    a, _ = _two_options()
    r = next_best_action("t", "desc", [a])
    assert r.version == "v1"


def test_next_best_action_reasoning_nonempty():
    a, b = _two_options()
    r = next_best_action("t", "desc", [a, b])
    assert len(r.matrix.reasoning) > 0


# ── P1.4: selection is internally consistent after enrichment ─────────────────

def test_selection_score_matches_matrix_score():
    """
    The selected option's score must equal the score of the same option as it
    appears in the matrix (both enriched by predict_approval before selection).
    """
    a, b = _two_options()
    r = next_best_action("t", "consistency", [a, b], method="greedy")
    selected_id = r.selected_option.option_id
    matrix_opt  = next(o for o in r.matrix.options if o.option_id == selected_id)
    # Scores must be identical — same enriched object
    assert score_option(r.selected_option) == pytest.approx(score_option(matrix_opt))
    assert r.selected_option.approval_likelihood == pytest.approx(matrix_opt.approval_likelihood)


def test_enrichment_happens_before_selection():
    """
    An option with artificially high approval_likelihood that predict_approval
    would lower must still lose to a genuinely better option.
    opt-X: high supplied approval_likelihood but high risk/low confidence (predict_approval gives ~0)
    opt-Y: modest numbers but consistent (predict_approval is positive)
    """
    opt_x = _opt(option_id="opt-X", confidence=0.1, risk_score=0.9,
                 cost_estimate="high", approval_likelihood=0.99)
    opt_y = _opt(option_id="opt-Y", confidence=0.8, risk_score=0.1,
                 cost_estimate="low", approval_likelihood=0.5)
    r = next_best_action("t", "consistency", [opt_x, opt_y], method="greedy")
    assert r.selected_option.option_id == "opt-Y"
