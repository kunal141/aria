"""
LLM-as-Judge Evaluator — Week 14

Scores a skill output against a rubric using an LLM as the judge.

Why LLM-as-judge (not hand-written checks):
  - Hand-written checks verify structure, not quality.
    "Has 2 root causes" != "root causes are good".
  - LLM judge scores what humans care about: specificity, domain relevance,
    actionability — things that are hard to express as assert statements.
  - The judge runs on get_fast_llm() (cheap) — not get_smart_llm().
    Rubric scoring is a simpler task than the skill itself.

Two evaluation layers in the runner (see runner.py):
  Layer 1 — Structural checks (no LLM, instant):
    schema validity, golden example constraint matching
  Layer 2 — Quality scoring (LLM judge, ~$0.001/eval):
    per-dimension 1–5 scores with justifications
"""
import json
import os
from typing import Literal, Optional
from pydantic import BaseModel

from aria.evaluation.rubrics import Rubric


# ── Result models ─────────────────────────────────────────────────────────────

class DimensionScore(BaseModel):
    dimension: str
    score: int       # 1–5
    justification: str


class EvalResult(BaseModel):
    skill_name: str
    input_summary: str          # first 80 chars of input
    overall_score: float        # weighted average of dimension scores
    dimension_scores: list[DimensionScore]
    pass_fail: Literal["pass", "warn", "fail"]
    structural_issues: list[str]   # schema/constraint failures (no LLM needed)
    judge_available: bool          # False if LLM not configured → structural only


# ── LLM judge ─────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """You are an evaluation judge for ARIA, an AI assistant for Amar Ujala's engineering team.

You will receive:
1. A skill name and what it is supposed to do
2. The input the user gave
3. The output ARIA produced
4. A rubric with dimensions to score

For each rubric dimension, output a score from 1–5 and a short justification (one sentence).

Score meaning:
5 = Excellent — specific, actionable, grounded in media-tech domain
4 = Good — minor gap in one area
3 = Acceptable — correct but vague or generic
2 = Weak — key element missing or incorrect
1 = Failing — wrong, empty, or hallucinated

Respond with ONLY valid JSON, no markdown:
{{
  "scores": [
    {{"dimension": "<name>", "score": <1-5>, "justification": "<one sentence>"}},
    ...
  ]
}}"""

_JUDGE_HUMAN = """Skill: {skill_name}
Input: {input}
Output: {output}
Rubric dimensions to score:
{dimensions}"""


def score(
    skill_name: str,
    input_text: str,
    skill_output: str,
    rubric: Rubric,
) -> EvalResult:
    """
    Score a skill output against its rubric using LLM-as-judge.
    Falls back to structural-only evaluation if no LLM is configured.
    """
    from aria.config import has_llm, get_fast_llm
    from aria.evaluation.rubrics import get_rubric

    structural_issues = _structural_check(skill_name, skill_output)
    judge_available   = has_llm()

    if not judge_available:
        # Structural-only path — no LLM judge
        default_score = 3.0 if not structural_issues else 1.0
        dim_scores    = [
            DimensionScore(dimension=d.name, score=3, justification="[No LLM judge — structural check only]")
            for d in rubric.dimensions
        ]
        return _build_result(
            skill_name, input_text, rubric, dim_scores,
            structural_issues, judge_available=False,
        )

    # Build dimension list for the prompt
    dim_lines = "\n".join(
        f"- {d.name}: {d.description}" for d in rubric.dimensions
    )

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    chain = (
        ChatPromptTemplate.from_messages([
            ("system", _JUDGE_SYSTEM),
            ("human",  _JUDGE_HUMAN),
        ])
        | get_fast_llm(temperature=0)
        | StrOutputParser()
    )

    try:
        raw = chain.invoke({
            "skill_name": skill_name,
            "input":      input_text[:500],
            "output":     skill_output[:1500],
            "dimensions": dim_lines,
        })
        parsed      = json.loads(raw)
        raw_scores  = {s["dimension"]: s for s in parsed.get("scores", [])}
        dim_scores  = [
            DimensionScore(
                dimension=d.name,
                score=raw_scores.get(d.name, {}).get("score", 1),
                justification=raw_scores.get(d.name, {}).get("justification", "Not scored"),
            )
            for d in rubric.dimensions
        ]
    except Exception as e:
        dim_scores = [
            DimensionScore(dimension=d.name, score=1, justification=f"Judge error: {e}")
            for d in rubric.dimensions
        ]

    return _build_result(skill_name, input_text, rubric, dim_scores, structural_issues, judge_available=True)


def _structural_check(skill_name: str, skill_output: str) -> list[str]:
    """
    Fast structural validation — no LLM.
    Returns list of issues found (empty = clean).
    """
    issues = []

    if not skill_output or skill_output.startswith("["):
        issues.append("Output is a mock/placeholder — no real skill output")
        return issues

    try:
        data = json.loads(skill_output)
    except json.JSONDecodeError:
        issues.append("Output is not valid JSON")
        return issues

    if skill_name == "pr_review":
        from aria.skills.pr_review_skill import PRReviewOutput
        try:
            PRReviewOutput(**data)
        except Exception as e:
            issues.append(f"Schema validation failed: {e}")
        if not data.get("code_issues"):
            issues.append("No code issues returned — likely under-reviewing")
        if not data.get("verdict"):
            issues.append("Missing verdict field")
        if not data.get("business_impact"):
            issues.append("Missing business_impact field")

    elif skill_name == "kpi":
        from aria.skills.kpi_skill import KPIOutput
        try:
            KPIOutput(**data)
        except Exception as e:
            issues.append(f"Schema validation failed: {e}")
        if not data.get("root_causes"):
            issues.append("No root causes returned")
        conf = data.get("confidence_score", 0.0)
        if conf > 0.95:
            issues.append(f"Confidence suspiciously high ({conf}) without data — possible hallucination")

    return issues


def _build_result(
    skill_name: str,
    input_text: str,
    rubric: Rubric,
    dim_scores: list[DimensionScore],
    structural_issues: list[str],
    judge_available: bool,
) -> EvalResult:
    scores_dict   = {d.dimension: d.score for d in dim_scores}
    overall       = rubric.weighted_average(scores_dict)
    has_structural = bool(structural_issues)

    if has_structural or overall < rubric.pass_threshold:
        pass_fail = "fail"
    elif overall < rubric.warn_threshold:
        pass_fail = "warn"
    else:
        pass_fail = "pass"

    return EvalResult(
        skill_name=skill_name,
        input_summary=input_text[:80],
        overall_score=overall,
        dimension_scores=dim_scores,
        pass_fail=pass_fail,
        structural_issues=structural_issues,
        judge_available=judge_available,
    )
