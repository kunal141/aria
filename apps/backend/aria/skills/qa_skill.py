"""
QA / Test Intelligence Skill — Week 17

Generates test cases for a feature or code change. Uses Given-When-Then
format so each test case is immediately usable in a test file.

Test types produced:
  functional   — happy-path scenarios, correct behaviour
  edge         — boundary conditions, empty inputs, extreme volumes
  negative     — invalid inputs, error paths, failure recovery
  integration  — cross-service interactions (CMS ↔ recommendation ↔ notification)
  performance  — latency/throughput SLAs under load

Domain context: Amar Ujala engineering systems
  - Article ingestion pipeline (CMS → enrichment → index)
  - Recommendation engine (feed ranking, diversity, freshness)
  - Notification service (push, in-app, rate limiting, opt-out)
  - Analytics pipeline (event tracking, CTR computation, A/B test assignment)
"""
import json
from typing import Literal

from pydantic import BaseModel, Field

import aria.config
from aria.config import get_routed_llm, has_llm
from aria.tracing import traceable


# ── Input Schema ──────────────────────────────────────────────────────────────

class QAInput(BaseModel):
    raw_input:        str = Field(..., description="Feature or code description to generate tests for")
    task_id:          str = Field(..., description="Unique task identifier from ARIAState")
    code_snippet:     str = Field(default="", description="Optional: code snippet or diff to analyse")
    feature_name:     str = Field(default="", description="Optional: name of the feature being tested")
    data_sensitivity: str = Field(default="internal", description="Routing signal: public/internal/confidential/restricted")
    audience:         str = Field(default="developer", description="Routing signal: developer/manager/leadership")


# ── Output Schema ─────────────────────────────────────────────────────────────

class TestCase(BaseModel):
    name:        str
    test_type:   Literal["functional", "edge", "negative", "integration", "performance"]
    description: str    # what scenario is being tested
    given:       str    # precondition / setup
    when:        str    # action or event triggered
    then:        str    # expected outcome
    priority:    Literal["critical", "high", "medium", "low"]


class CoverageGap(BaseModel):
    gap:  str                              # what scenario is NOT tested
    risk: Literal["high", "medium", "low"] # impact if this gap causes a bug in prod


class QAOutput(BaseModel):
    feature_summary: str                   # one-sentence description of what was analysed
    test_cases:      list[TestCase]        # generated test cases
    coverage_gaps:   list[CoverageGap]     # identified gaps in coverage
    test_count:      dict                  # {"functional": 2, "edge": 3, ...}
    version:         str = "v1"


# ── Skill Prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """You are ARIA, a QA intelligence specialist for Amar Ujala — India's largest Hindi media platform.

You generate test cases for engineering features in these systems:
- Article ingestion pipeline: CMS → enrichment → Elasticsearch index
- Recommendation engine: personalised feed ranking, diversity scoring, freshness weighting
- Notification service: push notifications, in-app alerts, rate limiting, opt-out tracking
- Analytics pipeline: CTR events, user engagement, A/B test variant assignment
- Personalisation: user preference model, content affinity, reading history

For each feature or code change you:
1. Generate test cases covering: functional, edge, negative, integration, performance
2. Use Given-When-Then format — concrete and immediately implementable
3. Identify coverage gaps — scenarios not obvious to the developer
4. Flag high-risk gaps that could cause production incidents

Respond with ONLY valid JSON matching this exact structure:
{
  "feature_summary": "one sentence describing what was analysed",
  "test_cases": [
    {
      "name": "descriptive test name in snake_case",
      "test_type": "functional|edge|negative|integration|performance",
      "description": "what scenario this tests",
      "given": "precondition or setup",
      "when": "action or event triggered",
      "then": "expected outcome — specific and verifiable",
      "priority": "critical|high|medium|low"
    }
  ],
  "coverage_gaps": [
    {
      "gap": "scenario not covered by the above tests",
      "risk": "high|medium|low"
    }
  ],
  "test_count": {"functional": 0, "edge": 0, "negative": 0, "integration": 0, "performance": 0}
}

Generate 5–8 test cases. Be specific to the media-tech domain. Not generic unit test advice."""


# ── Skill Function ─────────────────────────────────────────────────────────────

@traceable(
    run_type="chain",
    name="qa_skill_v1",
    tags=["skill", "qa", "aria"],
)
def run(input: QAInput) -> QAOutput:
    if not has_llm():
        return QAOutput(
            feature_summary=f"[Mock] Test cases for: {input.raw_input[:80]}",
            test_cases=[
                TestCase(
                    name="test_notification_rate_limit_per_user",
                    test_type="negative",
                    description="User should not receive more than 5 notifications per hour",
                    given="User has opted in to notifications; notification service is running",
                    when="6 push notification events are triggered for the same user within 60 minutes",
                    then="Only 5 notifications are delivered; 6th is queued and delivered after the rate-limit window resets",
                    priority="critical",
                ),
                TestCase(
                    name="test_recommendation_freshness_weight",
                    test_type="functional",
                    description="Articles published in the last 2 hours should appear in the top 10 feed positions",
                    given="10 articles published > 24 hours ago and 2 articles published < 2 hours ago",
                    when="Feed ranking is computed for an active user",
                    then="At least 1 of the 2 fresh articles appears in positions 1–10",
                    priority="high",
                ),
                TestCase(
                    name="test_ingestion_pipeline_handles_empty_body",
                    test_type="edge",
                    description="Article with empty body should not crash the ingestion pipeline",
                    given="CMS publishes an article with title but empty body field",
                    when="Ingestion pipeline processes the article",
                    then="Article is indexed with empty body; no pipeline exception; error logged to monitoring",
                    priority="high",
                ),
            ],
            coverage_gaps=[
                CoverageGap(
                    gap="No test for notification delivery when user device is offline and comes back online",
                    risk="high",
                ),
                CoverageGap(
                    gap="No integration test for A/B test assignment collision when user is in multiple experiments",
                    risk="medium",
                ),
            ],
            test_count={"functional": 1, "edge": 1, "negative": 1, "integration": 0, "performance": 0},
        )

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    human_msg = input.raw_input
    if input.feature_name:
        human_msg = f"Feature: {input.feature_name}\n\n{human_msg}"
    if input.code_snippet:
        human_msg += f"\n\n--- CODE ---\n{input.code_snippet[:2000]}"

    chain = (
        ChatPromptTemplate.from_messages([
            ("system", _SYSTEM),
            ("human", "{raw_input}"),
        ])
        | get_routed_llm(task_type="qa", data_sensitivity=input.data_sensitivity, audience=input.audience, temperature=0)
        | StrOutputParser()
    )

    raw = chain.invoke({"raw_input": human_msg})

    try:
        data = json.loads(raw)
        # Compute test_count from actual test_cases if not provided
        if not data.get("test_count"):
            counts: dict = {}
            for tc in data.get("test_cases", []):
                t = tc.get("test_type", "functional")
                counts[t] = counts.get(t, 0) + 1
            data["test_count"] = counts
        return QAOutput(**data)
    except Exception as e:
        return QAOutput(
            feature_summary=f"Parse error: {e}. Raw: {raw[:200]}",
            test_cases=[],
            coverage_gaps=[],
            test_count={},
        )


# ── Eval-Lite ──────────────────────────────────────────────────────────────────

EVAL_RUBRIC = """
QA / Test Intelligence Skill — Eval Rubric (1–5)

5 — Tests are immediately implementable. Given-When-Then is concrete and specific.
    Coverage gaps are non-obvious and production-relevant. All 3+ test types present.

4 — Tests are specific. Minor gap in one Given-When-Then. Coverage gaps identified.

3 — Tests present but Given-When-Then is vague ("it works correctly"). Missing at least
    one test type. Coverage gaps are obvious, not insightful.

2 — Only functional tests. No edge or negative tests. Coverage gaps absent.

1 — Generic test advice ("write unit tests"). No concrete scenarios. No Given-When-Then.
"""

GOLDEN_EXAMPLES = [
    {
        "input": "Add rate limiting to the push notification service — max 5 notifications per user per hour",
        "expected_min_test_cases": 4,
        "expected_types": ["negative", "edge", "functional"],
        "notes": "Rate limiting — must test boundary (exactly 5), over-limit (6+), and window reset",
    },
    {
        "input": "Implement freshness weighting in the recommendation feed ranking algorithm",
        "expected_min_test_cases": 4,
        "expected_types": ["functional", "edge"],
        "notes": "Freshness ranking — test articles at different ages, edge: all articles are old",
    },
    {
        "input": "Refactor article ingestion pipeline to use async processing",
        "expected_min_test_cases": 5,
        "expected_types": ["functional", "negative", "integration"],
        "notes": "Async refactor — must cover failure recovery, out-of-order processing, idempotency",
    },
    {
        "input": "Add A/B test framework to feed ranking — 50% users in control, 50% in treatment",
        "expected_min_test_cases": 4,
        "expected_types": ["functional", "edge", "integration"],
        "notes": "A/B test assignment — test consistent assignment, collision with other experiments, holdout group",
    },
    {
        "input": "Implement CTR click event deduplication to prevent double-counting from mobile retry",
        "expected_min_test_cases": 4,
        "expected_types": ["negative", "edge", "functional"],
        "notes": "Deduplication — exact duplicate within window, near-duplicate (same user different article), legitimate rapid clicks",
    },
]

FAILURE_CASES = [
    {
        "input": "Test my code",
        "expected_behavior": "Asks for feature description in coverage_gaps; returns minimal but valid tests",
    },
    {
        "input": "Write tests for the recommendation engine",
        "expected_behavior": "Broad scope — should generate generic but domain-relevant tests, ask for specifics",
    },
]
