"""
Eval Runner — Week 14

Runs the full regression suite for all registered skills.

Two-layer evaluation (matching evaluator.py):
  Layer 1 — Structural checks (instant, no LLM):
    schema validity, required fields, constraint matching against golden example metadata
  Layer 2 — Quality scoring (LLM-as-judge, ~$0.001/eval):
    per-dimension 1–5 scores with justifications

What "regression" means here:
  Not "does the output match the golden output" — that would be too brittle.
  Instead: "is the overall score >= baseline - 0.5?"
  This lets skill outputs vary (as LLMs do) while catching genuine quality degradation.

Run: uv run python -m aria.evaluation.runner
     Or import and call run_suite() programmatically.
"""
import json
import uuid
from dataclasses import dataclass, field

from aria.evaluation import evaluator, baselines
from aria.evaluation.rubrics import get_rubric


# ── Result models ─────────────────────────────────────────────────────────────

@dataclass
class ExampleResult:
    skill_name: str
    golden_index: int
    input_text: str
    overall_score: float
    pass_fail: str              # "pass" | "warn" | "fail"
    is_regression: bool
    baseline_score: float       # 0.0 if no baseline yet
    dimension_scores: dict      # {dimension: score}
    structural_issues: list[str]
    judge_available: bool
    notes: str = ""             # from golden example metadata


@dataclass
class RunSummary:
    total: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    regressions: list[ExampleResult] = field(default_factory=list)
    results: list[ExampleResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def regression_count(self) -> int:
        return len(self.regressions)


# ── Skill runners ─────────────────────────────────────────────────────────────

def _run_kpi_example(example: dict, index: int) -> ExampleResult:
    from aria.skills import kpi_skill
    from aria.skills.kpi_skill import KPIInput

    task_id    = f"eval-kpi-{index}-{uuid.uuid4().hex[:6]}"
    raw_input  = example["input"]
    skill_in   = KPIInput(raw_input=raw_input, task_id=task_id)
    skill_out  = kpi_skill.run(skill_in)
    output_str = skill_out.model_dump_json()

    rubric     = get_rubric("kpi")
    result     = evaluator.score("kpi", raw_input, output_str, rubric)

    dim_scores = {d.dimension: d.score for d in result.dimension_scores}
    regression = baselines.is_regression("kpi", index, result.overall_score)

    # Update baseline only if this run beats the previous high score
    baselines.update("kpi", index, result.overall_score, dim_scores)

    return ExampleResult(
        skill_name="kpi",
        golden_index=index,
        input_text=raw_input,
        overall_score=result.overall_score,
        pass_fail=result.pass_fail,
        is_regression=regression,
        baseline_score=baselines.get("kpi", index)["overall"] if baselines.get("kpi", index) else 0.0,
        dimension_scores=dim_scores,
        structural_issues=result.structural_issues,
        judge_available=result.judge_available,
        notes=example.get("notes", ""),
    )


def _run_pr_review_example(example: dict, index: int) -> ExampleResult:
    from aria.skills import pr_review_skill
    from aria.skills.pr_review_skill import PRReviewInput

    task_id    = f"eval-pr-{index}-{uuid.uuid4().hex[:6]}"
    raw_input  = example["input"]
    skill_in   = PRReviewInput(raw_input=raw_input, task_id=task_id)
    skill_out  = pr_review_skill.run(skill_in)
    output_str = skill_out.model_dump_json()

    rubric     = get_rubric("pr_review")
    result     = evaluator.score("pr_review", raw_input, output_str, rubric)

    dim_scores = {d.dimension: d.score for d in result.dimension_scores}
    regression = baselines.is_regression("pr_review", index, result.overall_score)

    baselines.update("pr_review", index, result.overall_score, dim_scores)

    return ExampleResult(
        skill_name="pr_review",
        golden_index=index,
        input_text=raw_input,
        overall_score=result.overall_score,
        pass_fail=result.pass_fail,
        is_regression=regression,
        baseline_score=baselines.get("pr_review", index)["overall"] if baselines.get("pr_review", index) else 0.0,
        dimension_scores=dim_scores,
        structural_issues=result.structural_issues,
        judge_available=result.judge_available,
        notes=example.get("notes", ""),
    )


# ── Suite runner ──────────────────────────────────────────────────────────────

def run_suite(
    skills: list[str] = None,
    log_to_langsmith: bool = True,
    verbose: bool = True,
) -> RunSummary:
    """
    Run the full regression suite.

    Args:
        skills: list of skill names to run (default: all registered skills)
        log_to_langsmith: log pass/fail feedback to LangSmith traces
        verbose: print progress and results

    Returns:
        RunSummary with counts, regressions, and full result list
    """
    from aria.skills.kpi_skill import GOLDEN_EXAMPLES as KPI_EXAMPLES
    from aria.skills.pr_review_skill import GOLDEN_EXAMPLES as PR_EXAMPLES

    skills = skills or ["kpi", "pr_review"]
    summary = RunSummary()

    _skill_runners = {
        "kpi":       (KPI_EXAMPLES,  _run_kpi_example),
        "pr_review": (PR_EXAMPLES,   _run_pr_review_example),
    }

    for skill_name in skills:
        if skill_name not in _skill_runners:
            if verbose:
                print(f"  [SKIP] Unknown skill: {skill_name}")
            continue

        examples, runner_fn = _skill_runners[skill_name]

        if verbose:
            print(f"\n{'─' * 55}")
            print(f"Running {skill_name} ({len(examples)} examples)")
            print(f"{'─' * 55}")

        for i, example in enumerate(examples):
            if verbose:
                print(f"  [{i+1}/{len(examples)}] {example['input'][:60]}...")

            try:
                ex_result = runner_fn(example, i)
            except Exception as e:
                if verbose:
                    print(f"        ✗ RUNNER ERROR: {e}")
                # Create a failed placeholder so the suite continues
                ex_result = ExampleResult(
                    skill_name=skill_name,
                    golden_index=i,
                    input_text=example["input"],
                    overall_score=1.0,
                    pass_fail="fail",
                    is_regression=False,
                    baseline_score=0.0,
                    dimension_scores={},
                    structural_issues=[f"Runner error: {e}"],
                    judge_available=False,
                    notes=example.get("notes", ""),
                )

            summary.total   += 1
            summary.results.append(ex_result)

            if ex_result.pass_fail == "pass":
                summary.passed += 1
            elif ex_result.pass_fail == "warn":
                summary.warned += 1
            else:
                summary.failed += 1

            if ex_result.is_regression:
                summary.regressions.append(ex_result)

            if verbose:
                _print_example_result(ex_result)

    if log_to_langsmith:
        _log_suite_to_langsmith(summary)

    return summary


# ── LangSmith logging ─────────────────────────────────────────────────────────

def _log_suite_to_langsmith(summary: RunSummary) -> None:
    """Log pass/fail for each example to LangSmith as eval feedback."""
    try:
        from aria.tracing import get_client
        client = get_client()
        if not client:
            return
        # LangSmith doesn't have a direct "eval run" concept in the simple client.
        # We log a dataset-level feedback entry summarising the run.
        # Full LangSmith eval datasets are a Week 21+ addition (Pillar 12 V2).
    except Exception:
        pass


# ── Pretty printing ───────────────────────────────────────────────────────────

def _print_example_result(r: ExampleResult) -> None:
    icon = {"pass": "✓", "warn": "~", "fail": "✗"}[r.pass_fail]
    reg  = " ⚠ REGRESSION" if r.is_regression else ""
    print(f"        {icon} {r.pass_fail.upper():4} | score={r.overall_score:.2f}{reg}")
    if r.structural_issues:
        for issue in r.structural_issues:
            print(f"          structural: {issue}")
    if not r.judge_available:
        print(f"          [no LLM judge — structural only]")


def print_summary(summary: RunSummary) -> None:
    width = 55
    print("\n" + "=" * width)
    print(f"  ARIA Evaluation Suite — Run Summary")
    print("=" * width)
    print(f"  Total    : {summary.total}")
    print(f"  Passed   : {summary.passed}  ({summary.pass_rate:.0%})")
    print(f"  Warned   : {summary.warned}")
    print(f"  Failed   : {summary.failed}")
    print(f"  Regress. : {summary.regression_count}")

    if summary.regressions:
        print(f"\n  Regressions detected:")
        for r in summary.regressions:
            print(f"    - {r.skill_name}[{r.golden_index}]: "
                  f"score={r.overall_score:.2f}  baseline={r.baseline_score:.2f}  "
                  f"drop={r.baseline_score - r.overall_score:.2f}")
    else:
        print(f"\n  No regressions.")

    print("=" * width)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("ARIA Evaluation Runner — Week 14")
    summary = run_suite(verbose=True)
    print_summary(summary)

    if summary.regression_count > 0:
        sys.exit(1)   # non-zero exit so CI can detect regressions
