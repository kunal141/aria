"""
KPI Investigation Skill — Week 6

ARIA's first real skill. Every skill has:
  - KPIInput  : typed Pydantic input schema
  - KPIOutput : typed Pydantic output schema
  - run()     : the skill function — Claude call + structured output
  - eval rubric (bottom of file)

Domain context: Amar Ujala media platform
Relevant KPIs: CTR, feed performance, notification CTR,
               story recommendation quality, content pipeline health
"""
import json
from typing import Literal

from pydantic import BaseModel, Field

import aria.config  # must be first
from aria.config import get_routed_llm, has_llm
from aria.tracing import traceable

# ─────────────────────────────────────────────────────────────────────────────
# Input Schema
# ─────────────────────────────────────────────────────────────────────────────

class KPIInput(BaseModel):
    raw_input:        str = Field(..., description="User's description of the KPI issue")
    task_id:          str = Field(..., description="Unique task identifier from ARIAState")
    data_sensitivity: str = Field(default="internal", description="Routing signal: public/internal/confidential/restricted")
    audience:         str = Field(default="developer", description="Routing signal: developer/manager/leadership")


# ─────────────────────────────────────────────────────────────────────────────
# Output Schema
# ─────────────────────────────────────────────────────────────────────────────

class RootCauseHypothesis(BaseModel):
    hypothesis: str
    likelihood: Literal["high", "medium", "low"]
    evidence: str   # what signal would confirm or deny this


class KPIOutput(BaseModel):
    summary: str                               # one-sentence executive summary
    root_causes: list[RootCauseHypothesis]     # ranked hypotheses
    recommended_actions: list[str]             # immediate next steps
    data_needed: list[str]                     # what data would sharpen the analysis
    confidence_score: float                    # 0.0–1.0 (how confident is ARIA)
    version: str = "v1"


# ─────────────────────────────────────────────────────────────────────────────
# Skill Prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM = """You are ARIA, an AI analyst for Amar Ujala — one of India's largest Hindi media platforms.

When investigating a KPI issue, you reason about:
- Content metrics: CTR, time-on-page, scroll depth, story engagement
- Feed metrics: recommendation quality, diversity, freshness, personalisation accuracy
- Notification metrics: open rate, click rate, opt-out rate
- Pipeline metrics: ingestion lag, indexing errors, cache hit rate

Respond with ONLY valid JSON matching this exact structure:
{
  "summary": "one sentence executive summary of the issue",
  "root_causes": [
    {
      "hypothesis": "what might be causing this",
      "likelihood": "high|medium|low",
      "evidence": "what data would confirm or deny this"
    }
  ],
  "recommended_actions": ["action 1", "action 2"],
  "data_needed": ["what data to pull first", "what to check next"],
  "confidence_score": 0.0
}

Root causes: provide 2–4 hypotheses, ranked by likelihood.
Confidence score: 0.0 if you have no data, 0.5 if reasoning from context, 0.8+ if pattern is clear.
Be specific to media/content platforms. Do not give generic analytics advice."""


# ─────────────────────────────────────────────────────────────────────────────
# Skill Function
# ─────────────────────────────────────────────────────────────────────────────

@traceable(
    run_type="chain",
    name="kpi_skill_v1",
    tags=["skill", "kpi", "aria"],
)
def run(input: KPIInput) -> KPIOutput:
    if not has_llm():
        # No LLM configured — return a mock output so the graph still runs
        return KPIOutput(
            summary=f"[Mock] KPI issue detected: {input.raw_input[:80]}",
            root_causes=[
                RootCauseHypothesis(
                    hypothesis="Algorithm change may have reduced content diversity",
                    likelihood="medium",
                    evidence="Compare recommendation diversity scores before/after the drop date",
                ),
                RootCauseHypothesis(
                    hypothesis="Content ingestion pipeline experiencing latency",
                    likelihood="low",
                    evidence="Check pipeline monitoring for ingestion lag spikes",
                ),
            ],
            recommended_actions=[
                "Pull CTR data segmented by content category for the past 7 days",
                "Compare recommendation model version deployed vs previous week",
            ],
            data_needed=[
                "Daily CTR by content category (last 14 days)",
                "Recommendation model deployment log",
            ],
            confidence_score=0.0,
        )

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    chain = (
        ChatPromptTemplate.from_messages([
            ("system", _SYSTEM),
            ("human", "{raw_input}"),
        ])
        | get_routed_llm(task_type="kpi", data_sensitivity=input.data_sensitivity, audience=input.audience, temperature=0)
        | StrOutputParser()
    )

    raw = chain.invoke({"raw_input": input.raw_input})

    try:
        data = json.loads(raw)
        return KPIOutput(**data)
    except Exception as e:
        return KPIOutput(
            summary=f"Parse error: {e}. Raw: {raw[:200]}",
            root_causes=[],
            recommended_actions=[],
            data_needed=[],
            confidence_score=0.0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Eval-Lite — mandatory from Week 6 (full LangSmith harness at Week 14)
# ─────────────────────────────────────────────────────────────────────────────

EVAL_RUBRIC = """
KPI Investigation Skill — Eval Rubric (1–5)

5 — Root causes are specific, ranked, evidence-backed. Actions are immediately executable.
    Data needed is precise (exact table/metric names). Confidence score is calibrated.

4 — Root causes are plausible and ranked. Actions are clear. Minor gaps in specificity.

3 — Root causes present but unranked or generic. Actions are vague ("check the data").
    Confidence score not calibrated to evidence available.

2 — Only one root cause. No ranking. Generic advice ("look at your analytics").

1 — No root causes. No actions. Output is empty or hallucinated.
"""

GOLDEN_EXAMPLES = [
    {
        "input": "Our homepage CTR dropped 22% this Monday compared to last Monday",
        "expected_task_type": "pr_review",  # wait, this is kpi
        "expected_min_root_causes": 2,
        "expected_confidence_range": (0.3, 0.7),
        "notes": "No root cause data provided — confidence should be moderate, not high",
    },
    {
        "input": "Story recommendation feed is showing articles from 3 days ago instead of fresh content",
        "expected_min_root_causes": 2,
        "expected_confidence_range": (0.5, 0.9),
        "notes": "Clear symptom — freshness issue. Should identify ingestion lag or index staleness",
    },
    {
        "input": "Notification open rate fell from 18% to 9% after Tuesday's app release",
        "expected_min_root_causes": 2,
        "expected_confidence_range": (0.6, 0.9),
        "notes": "Time-correlated with release — should mention regression introduced in release",
    },
    {
        "input": "Users in UP region are seeing lower engagement than Delhi users this week",
        "expected_min_root_causes": 2,
        "expected_confidence_range": (0.3, 0.6),
        "notes": "Regional variation — could be content, could be infra, should not over-claim",
    },
    {
        "input": "Content pipeline seems slow — articles taking 40 minutes to appear after publish",
        "expected_min_root_causes": 2,
        "expected_confidence_range": (0.5, 0.9),
        "notes": "Clear infra/pipeline symptom — should identify ingestion, indexing, or CDN cause",
    },
]

FAILURE_CASES = [
    {
        "input": "Everything is broken",
        "expected_behavior": "Returns general hypotheses with low confidence — does not hallucinate specifics",
    },
    {
        "input": "CTR",
        "expected_behavior": "Asks for more context in data_needed, low confidence, does not fabricate",
    },
    {
        "input": "Our revenue is down",
        "expected_behavior": "Routes to general or kpi depending on framing — does not confuse with finance skill",
    },
]
