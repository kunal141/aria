"""
Deterministic tests for the DSPy + Instructor optimisation layer (Week 23).
No LLM, no network — all tests run in full isolation.
"""
import types
import pytest
from pydantic import BaseModel

from aria.optimization.signatures import (
    PRReviewSignature,
    KPISignature,
    RouterSignature,
    TaskTypeOutput,
)
from aria.optimization.metrics import (
    routing_accuracy,
    pr_review_quality,
    kpi_quality,
)
from aria.optimization.optimizer import optimize_skill, SkillOptimizationResult


# ── helpers ───────────────────────────────────────────────────────────────────

def _ns(**kwargs):
    """SimpleNamespace — cheap stand-in for dspy.Example / dspy.Prediction."""
    return types.SimpleNamespace(**kwargs)


# ── TaskTypeOutput (Instructor model) ─────────────────────────────────────────

def test_task_type_output_is_pydantic():
    assert issubclass(TaskTypeOutput, BaseModel)


def test_task_type_output_defaults():
    o = TaskTypeOutput(task_type="kpi")
    assert o.task_type == "kpi"
    assert o.confidence == 0.0
    assert o.reason == ""


def test_task_type_output_full():
    o = TaskTypeOutput(task_type="pr_review", confidence=0.9, reason="contains diff")
    assert o.task_type == "pr_review"
    assert o.confidence == 0.9
    assert o.reason == "contains diff"


def test_task_type_output_serialises():
    o = TaskTypeOutput(task_type="ci_cd", confidence=0.7)
    d = o.model_dump()
    assert d["task_type"] == "ci_cd"
    assert "confidence" in d


# ── DSPy Signature imports & field presence ───────────────────────────────────

def test_router_signature_importable():
    import dspy
    assert issubclass(RouterSignature, dspy.Signature)


def test_pr_review_signature_importable():
    import dspy
    assert issubclass(PRReviewSignature, dspy.Signature)


def test_kpi_signature_importable():
    import dspy
    assert issubclass(KPISignature, dspy.Signature)


def test_router_signature_has_raw_input_field():
    fields = RouterSignature.model_fields
    assert "raw_input" in fields


def test_router_signature_has_task_type_field():
    fields = RouterSignature.model_fields
    assert "task_type" in fields


def test_router_signature_has_reason_field():
    fields = RouterSignature.model_fields
    assert "reason" in fields


def test_pr_review_signature_has_risk_level_field():
    fields = PRReviewSignature.model_fields
    assert "risk_level" in fields


def test_pr_review_signature_has_verdict_field():
    fields = PRReviewSignature.model_fields
    assert "verdict" in fields


def test_pr_review_signature_has_summary_field():
    fields = PRReviewSignature.model_fields
    assert "summary" in fields


def test_kpi_signature_has_root_cause_field():
    fields = KPISignature.model_fields
    assert "root_cause" in fields


def test_kpi_signature_has_severity_field():
    fields = KPISignature.model_fields
    assert "severity" in fields


def test_kpi_signature_has_recommended_action_field():
    fields = KPISignature.model_fields
    assert "recommended_action" in fields


# ── routing_accuracy metric ────────────────────────────────────────────────────

def test_routing_accuracy_exact_match():
    ex   = _ns(expected_task_type="kpi")
    pred = _ns(task_type="kpi")
    assert routing_accuracy(ex, pred) is True


def test_routing_accuracy_mismatch():
    ex   = _ns(expected_task_type="kpi")
    pred = _ns(task_type="pr_review")
    assert routing_accuracy(ex, pred) is False


def test_routing_accuracy_case_insensitive():
    ex   = _ns(expected_task_type="KPI")
    pred = _ns(task_type="kpi")
    assert routing_accuracy(ex, pred) is True


def test_routing_accuracy_missing_expected():
    ex   = _ns()
    pred = _ns(task_type="kpi")
    assert routing_accuracy(ex, pred) is False


def test_routing_accuracy_missing_predicted():
    ex   = _ns(expected_task_type="kpi")
    pred = _ns()
    assert routing_accuracy(ex, pred) is False


def test_routing_accuracy_all_task_types():
    for tt in ["pr_review", "kpi", "ci_cd", "jira", "qa", "test_review", "general"]:
        ex   = _ns(expected_task_type=tt)
        pred = _ns(task_type=tt)
        assert routing_accuracy(ex, pred) is True


# ── pr_review_quality metric ──────────────────────────────────────────────────

def test_pr_review_quality_perfect_score():
    pred = _ns(verdict="APPROVE", risk_level="low", summary="Looks good")
    assert pr_review_quality(None, pred) == 1.0


def test_pr_review_quality_invalid_verdict():
    pred = _ns(verdict="INVALID", risk_level="low", summary="Looks good")
    score = pr_review_quality(None, pred)
    assert score == pytest.approx(0.6)


def test_pr_review_quality_invalid_risk():
    pred = _ns(verdict="APPROVE", risk_level="extreme", summary="Fine")
    score = pr_review_quality(None, pred)
    assert score == pytest.approx(0.6)


def test_pr_review_quality_empty_summary():
    pred = _ns(verdict="REQUEST_CHANGES", risk_level="high", summary="")
    score = pr_review_quality(None, pred)
    assert score == pytest.approx(0.8)


def test_pr_review_quality_zero_score():
    pred = _ns(verdict="", risk_level="", summary="")
    assert pr_review_quality(None, pred) == 0.0


def test_pr_review_quality_all_valid_verdicts():
    for v in ["APPROVE", "REQUEST_CHANGES", "NEEDS_DISCUSSION"]:
        pred = _ns(verdict=v, risk_level="medium", summary="ok")
        assert pr_review_quality(None, pred) == pytest.approx(1.0)


def test_pr_review_quality_all_valid_risk_levels():
    for r in ["low", "medium", "high", "critical"]:
        pred = _ns(verdict="APPROVE", risk_level=r, summary="ok")
        assert pr_review_quality(None, pred) == pytest.approx(1.0)


# ── kpi_quality metric ────────────────────────────────────────────────────────

def test_kpi_quality_perfect_score():
    pred = _ns(root_cause="Cache eviction spike", severity="high", recommended_action="Increase TTL")
    assert kpi_quality(None, pred) == pytest.approx(1.0)


def test_kpi_quality_empty_root_cause():
    pred = _ns(root_cause="", severity="high", recommended_action="Increase TTL")
    score = kpi_quality(None, pred)
    assert score == pytest.approx(0.6)


def test_kpi_quality_invalid_severity():
    pred = _ns(root_cause="Cache eviction", severity="catastrophic", recommended_action="Rollback")
    score = kpi_quality(None, pred)
    assert score == pytest.approx(0.7)


def test_kpi_quality_empty_action():
    pred = _ns(root_cause="Algo change", severity="critical", recommended_action="")
    score = kpi_quality(None, pred)
    assert score == pytest.approx(0.7)


def test_kpi_quality_zero_score():
    pred = _ns(root_cause="", severity="", recommended_action="")
    assert kpi_quality(None, pred) == 0.0


def test_kpi_quality_all_valid_severities():
    for s in ["low", "medium", "high", "critical"]:
        pred = _ns(root_cause="cause", severity=s, recommended_action="act")
        assert kpi_quality(None, pred) == pytest.approx(1.0)


# ── SkillOptimizationResult ───────────────────────────────────────────────────

def test_skill_optimization_result_defaults():
    r = SkillOptimizationResult(skill_name="pr_review")
    assert r.skill_name == "pr_review"
    assert r.version == "v1"
    assert r.optimized is False
    assert r.baseline_score == 0.0
    assert r.optimized_score == 0.0
    assert r.num_examples == 0
    assert r.compiled_program is None
    assert r.error is None


def test_skill_optimization_result_with_error():
    r = SkillOptimizationResult(skill_name="kpi", error="No LM", num_examples=5)
    assert r.error == "No LM"
    assert r.optimized is False
    assert r.num_examples == 5


def test_skill_optimization_result_serialises():
    r = SkillOptimizationResult(skill_name="router", optimized=True, baseline_score=0.6, optimized_score=0.85)
    d = r.model_dump()
    assert d["skill_name"] == "router"
    assert d["optimized"] is True
    assert d["baseline_score"] == pytest.approx(0.6)
    assert d["optimized_score"] == pytest.approx(0.85)


def test_skill_optimization_result_accepts_arbitrary_compiled_program():
    fake_program = object()
    r = SkillOptimizationResult(skill_name="pr_review", compiled_program=fake_program)
    assert r.compiled_program is fake_program


# ── optimize_skill — no LM path (fully deterministic) ─────────────────────────

def test_optimize_skill_no_lm_returns_result():
    result = optimize_skill(PRReviewSignature, [], routing_accuracy, lm=None, skill_name="pr_review")
    assert isinstance(result, SkillOptimizationResult)


def test_optimize_skill_no_lm_not_optimized():
    result = optimize_skill(KPISignature, [], kpi_quality, lm=None, skill_name="kpi")
    assert result.optimized is False


def test_optimize_skill_no_lm_has_error():
    result = optimize_skill(RouterSignature, [], routing_accuracy, lm=None)
    assert result.error is not None
    assert len(result.error) > 0


def test_optimize_skill_no_lm_skill_name_preserved():
    result = optimize_skill(PRReviewSignature, [], pr_review_quality, lm=None, skill_name="pr_review_v2")
    assert result.skill_name == "pr_review_v2"


def test_optimize_skill_empty_trainset_no_lm():
    result = optimize_skill(KPISignature, [], kpi_quality, lm=None, skill_name="kpi")
    assert result.num_examples == 0


def test_optimize_skill_no_lm_zero_scores():
    result = optimize_skill(RouterSignature, [], routing_accuracy, lm=None)
    assert result.baseline_score == 0.0
    assert result.optimized_score == 0.0


def test_optimize_skill_no_lm_no_compiled_program():
    result = optimize_skill(PRReviewSignature, [], pr_review_quality, lm=None)
    assert result.compiled_program is None
