"""
Week 14 — Agent Evaluation Harness (standalone learning artifact)

Demonstrates:
  1. Rubric definitions — per-dimension scoring with weights
  2. Structural evaluation — schema checks, constraint matching, no LLM
  3. LLM-as-judge — per-dimension 1–5 scores with justifications
  4. Baseline tracking — regression detection across runs
  5. Full regression suite — run all golden examples, compare to baselines

Run: uv run python week14_eval_harness_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import os
import uuid
from pathlib import Path

_test_baselines = Path(__file__).parent / "_week14_test_eval_baselines.json"
os.environ["ARIA_BASELINES_PATH"] = str(_test_baselines)
if _test_baselines.exists():
    _test_baselines.unlink()

from aria.evaluation.rubrics import PR_REVIEW_RUBRIC, KPI_RUBRIC, get_rubric, list_rubrics
from aria.evaluation import evaluator
from aria.evaluation import baselines
from aria.evaluation.runner import run_suite, print_summary
from aria.config import has_llm

print("=" * 60)
print("ARIA — Week 14: Agent Evaluation Harness")
print("=" * 60)

llm_status = "LLM judge ACTIVE" if has_llm() else "LLM judge OFFLINE (structural-only mode)"
print(f"\n  Judge status: {llm_status}")


# ─────────────────────────────────────────────────────────────────────────────
# 1 — Rubric inspection
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("1/5  Rubric definitions")
print("─" * 60)

for rubric in [PR_REVIEW_RUBRIC, KPI_RUBRIC]:
    print(f"\n  Skill: {rubric.skill_name}  ({rubric.version})")
    print(f"  Pass threshold: {rubric.pass_threshold}  |  Warn threshold: {rubric.warn_threshold}")
    total_weight = sum(d.weight for d in rubric.dimensions)
    print(f"  Dimensions ({len(rubric.dimensions)} total, {total_weight:.1f} weight units):")
    for d in rubric.dimensions:
        print(f"    [{d.weight:3.1f}x] {d.name}")

print(f"\n  Registered rubrics: {list_rubrics()}")


# ─────────────────────────────────────────────────────────────────────────────
# 2 — Structural evaluation (no LLM)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("2/5  Structural checks — schema + constraint validation (no LLM)")
print("─" * 60)

# Case 1: Valid PR review output
valid_pr_output = json.dumps({
    "verdict": "request_changes",
    "risk_level": "high",
    "summary": "Async refactor introduces data loss risk without error recovery.",
    "code_issues": [
        {
            "severity": "critical",
            "category": "correctness",
            "description": "No retry logic on async queue write failure — articles can be silently dropped",
            "suggestion": "Add exponential backoff retry with dead-letter queue for failed writes"
        }
    ],
    "missing_tests": [
        "Unit test: async worker handles connection timeout without data loss",
        "Integration test: pipeline resumes correctly after worker restart mid-batch"
    ],
    "deployment_risks": [
        "Async queue write failures could cause article loss during ingestion — monitor dead-letter queue post-deploy"
    ],
    "business_impact": "Silent article drop affects content freshness score — CTR on homepage feed could drop 5-8% if recent articles don't appear within SLA",
    "positive_observations": ["Clean separation of sync/async concerns"],
    "version": "v1"
})

result = evaluator.score(
    skill_name="pr_review",
    input_text="Refactoring the article ingestion pipeline to use async processing",
    skill_output=valid_pr_output,
    rubric=PR_REVIEW_RUBRIC,
)

print(f"\n  Valid PR review output:")
print(f"    Structural issues : {result.structural_issues or 'none'}")
print(f"    Overall score     : {result.overall_score}")
print(f"    Pass/fail         : {result.pass_fail}")
print(f"    Judge available   : {result.judge_available}")

if result.judge_available:
    print(f"    Dimension scores:")
    for ds in result.dimension_scores:
        print(f"      [{ds.score}/5] {ds.dimension}: {ds.justification}")


# Case 2: Structural failure — missing required field
bad_output = json.dumps({
    "verdict": "approve",
    "risk_level": "low",
    "summary": "Looks fine.",
    "code_issues": [],
    "missing_tests": [],
    "deployment_risks": [],
    "positive_observations": []
    # Missing: business_impact
})

result_bad = evaluator.score(
    skill_name="pr_review",
    input_text="Fix typo in README",
    skill_output=bad_output,
    rubric=PR_REVIEW_RUBRIC,
)

print(f"\n  Incomplete PR review output (missing business_impact):")
print(f"    Structural issues : {result_bad.structural_issues}")
print(f"    Pass/fail         : {result_bad.pass_fail}")


# Case 3: Mock/placeholder output detection
mock_output = "[Mock output — no real skill output]"
result_mock = evaluator.score(
    skill_name="pr_review",
    input_text="Review my PR",
    skill_output=mock_output,
    rubric=PR_REVIEW_RUBRIC,
)

print(f"\n  Mock/placeholder output:")
print(f"    Structural issues : {result_mock.structural_issues}")
print(f"    Pass/fail         : {result_mock.pass_fail}")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — KPI skill evaluation
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("3/5  KPI skill — live evaluation")
print("─" * 60)

from aria.skills.kpi_skill import KPIInput
import aria.skills.kpi_skill as kpi_skill

kpi_input = KPIInput(
    raw_input="CTR dropped 22% this Monday compared to last Monday on our homepage feed",
    task_id=f"eval-demo-{uuid.uuid4().hex[:8]}",
)

print(f"\n  Input: {kpi_input.raw_input}")
kpi_output = kpi_skill.run(kpi_input)
print(f"  Output summary: {kpi_output.summary}")
print(f"  Root causes: {len(kpi_output.root_causes)}")
print(f"  Confidence: {kpi_output.confidence_score}")

kpi_result = evaluator.score(
    skill_name="kpi",
    input_text=kpi_input.raw_input,
    skill_output=kpi_output.model_dump_json(),
    rubric=KPI_RUBRIC,
)

print(f"\n  Evaluation:")
print(f"    Overall score: {kpi_result.overall_score}  ({kpi_result.pass_fail})")
print(f"    Structural   : {kpi_result.structural_issues or 'clean'}")
if kpi_result.judge_available:
    for ds in kpi_result.dimension_scores:
        print(f"    [{ds.score}/5] {ds.dimension}")


# ─────────────────────────────────────────────────────────────────────────────
# 4 — Baseline tracking
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("4/5  Baseline storage and regression detection")
print("─" * 60)

# Store a baseline
dim_scores = {d.dimension: d.score for d in kpi_result.dimension_scores}
baselines.update("kpi", 0, kpi_result.overall_score, dim_scores)
stored = baselines.get("kpi", 0)
print(f"\n  Stored baseline: overall={stored['overall']}")

# Simulate a regression (score dropped > 0.5)
fake_lower = max(1.0, kpi_result.overall_score - 0.6)
is_reg = baselines.is_regression("kpi", 0, fake_lower)
print(f"  Score {fake_lower:.2f} vs baseline {stored['overall']:.2f} → regression={is_reg}")

# Simulate a non-regression (small drop within threshold)
fake_small_drop = max(1.0, kpi_result.overall_score - 0.3)
is_reg2 = baselines.is_regression("kpi", 0, fake_small_drop)
print(f"  Score {fake_small_drop:.2f} vs baseline {stored['overall']:.2f} → regression={is_reg2}")

# Baselines.update() won't lower the bar
updated = baselines.update("kpi", 0, fake_lower, dim_scores)
after   = baselines.get("kpi", 0)
print(f"  Tried to update to lower score ({fake_lower:.2f}) → accepted={updated}  stored={after['overall']:.2f}")


# ─────────────────────────────────────────────────────────────────────────────
# 5 — Full regression suite
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("5/5  Full regression suite — all golden examples")
print("─" * 60)

# Clear baselines so first run sets them (no false regressions)
if baseline_file.exists():
    baseline_file.unlink()

summary = run_suite(skills=["kpi", "pr_review"], verbose=True)
print_summary(summary)


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("Week 14 Eval Harness — What Was Built:")
print("  rubrics.py     → per-dimension scoring rubrics (PR review + KPI)")
print("  evaluator.py   → two-layer eval: structural + LLM-as-judge")
print("  baselines.py   → file-backed baseline store, regression detection")
print("  runner.py      → regression suite: all golden examples, LangSmith logging")
print(f"\n  Judge mode: {'LLM-as-judge (per-dimension quality scores)' if has_llm() else 'Structural-only (no LLM judge configured)'}")
print("\n✅ Week 14 complete.")
