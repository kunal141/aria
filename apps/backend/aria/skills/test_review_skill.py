"""
Test Review & Regression Intelligence Skill — Week 18

Reviews an existing test suite for:
  - Test quality issues (flaky patterns, weak assertions, poor isolation)
  - Regression risks — what production code paths are unguarded
  - Coverage gaps relative to the feature being tested
  - Actionable fixes for each issue

Distinct from qa_skill (Week 17):
  qa_skill        → "what tests should I write?" → generates new tests
  test_review     → "are these tests good?"      → reviews existing test quality

Domain: Amar Ujala engineering systems
  - Recommendation engine tests (ranking, diversity, A/B assignment)
  - Notification service tests (rate limiting, delivery, opt-out)
  - CMS ingestion tests (parsing, enrichment, deduplication)
  - Analytics tests (CTR computation, event deduplication)
"""
import json
from typing import Literal

from pydantic import BaseModel, Field

import aria.config
from aria.config import get_routed_llm, has_llm
from aria.tracing import traceable


# ── Input Schema ──────────────────────────────────────────────────────────────

class TestReviewInput(BaseModel):
    raw_input:        str = Field(..., description="Description of the test suite or paste of test code")
    task_id:          str = Field(..., description="Unique task identifier from ARIAState")
    test_content:     str = Field(default="", description="Optional: actual test file content")
    framework:        str = Field(default="pytest", description="Test framework: pytest, jest, unittest")
    service_name:     str = Field(default="", description="Optional: service being tested (e.g. notification, recommendation)")
    data_sensitivity: str = Field(default="internal", description="Routing signal: public/internal/confidential/restricted")
    audience:         str = Field(default="developer", description="Routing signal: developer/manager/leadership")


# ── Output Schema ─────────────────────────────────────────────────────────────

class TestQualityIssue(BaseModel):
    issue_type:  Literal["flaky", "incomplete_assertion", "missing_edge_case",
                          "poor_isolation", "no_cleanup", "hardcoded_data", "missing_mock"]
    description: str    # what specifically is wrong
    severity:    Literal["critical", "high", "medium", "low"]
    location:    str    # which test or section this applies to
    fix:         str    # concrete remediation step


class RegressionRisk(BaseModel):
    code_path:   str                              # which production path has no test guard
    risk_level:  Literal["high", "medium", "low"]
    scenario:    str                              # what could break silently
    guard_test:  str                              # test that would catch this regression


class TestReviewOutput(BaseModel):
    summary:          str                         # one-sentence quality verdict
    quality_score:    float                       # 0.0–1.0 (1.0 = excellent test suite)
    issues:           list[TestQualityIssue]
    regression_risks: list[RegressionRisk]
    coverage_verdict: Literal["good", "partial", "poor"]
    recommendations:  list[str]                   # ordered by priority
    version:          str = "v1"


# ── Skill Prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """You are ARIA, a QA specialist reviewing test suites for Amar Ujala's engineering platform.

You review tests for:
- Recommendation engine: ranking, diversity scoring, freshness weighting, A/B test assignment
- Notification service: push delivery, rate limiting, opt-out handling, retry logic
- Article ingestion: parsing, enrichment, deduplication, indexing lag
- Analytics pipeline: CTR events, deduplication, user engagement tracking

Analyse the test suite and identify:
1. Quality issues: flaky patterns (time.sleep, network calls in unit tests, hardcoded IDs),
   weak assertions (assertTrue(result) not assertEqual(result, expected)), poor isolation
   (shared state between tests), missing cleanup, missing mocks for external services
2. Regression risks: production code paths with no test guard — what could break silently
3. Coverage gaps: scenarios the tests don't cover that a real user or system would trigger

Quality score: 0.0 = no useful tests, 0.5 = basic coverage, 1.0 = comprehensive + robust

Respond with ONLY valid JSON:
{
  "summary": "one sentence quality verdict",
  "quality_score": 0.0,
  "issues": [
    {
      "issue_type": "flaky|incomplete_assertion|missing_edge_case|poor_isolation|no_cleanup|hardcoded_data|missing_mock",
      "description": "what is wrong specifically",
      "severity": "critical|high|medium|low",
      "location": "which test or line this applies to",
      "fix": "concrete fix step"
    }
  ],
  "regression_risks": [
    {
      "code_path": "which production path",
      "risk_level": "high|medium|low",
      "scenario": "what could break silently",
      "guard_test": "test that would catch this regression"
    }
  ],
  "coverage_verdict": "good|partial|poor",
  "recommendations": ["priority 1 fix", "priority 2 fix"]
}

Be specific to media-tech systems. Not generic test advice."""


# ── Skill Function ────────────────────────────────────────────────────────────

@traceable(
    run_type="chain",
    name="test_review_skill_v1",
    tags=["skill", "test_review", "qa", "aria"],
)
def run(input: TestReviewInput) -> TestReviewOutput:
    if not has_llm():
        return TestReviewOutput(
            summary="[Mock] Test suite reviewed — multiple quality issues detected",
            quality_score=0.45,
            issues=[
                TestQualityIssue(
                    issue_type="flaky",
                    description="Test uses time.sleep(2) to wait for async notification delivery",
                    severity="critical",
                    location="test_notification_delivery",
                    fix="Replace time.sleep with an async event or polling with timeout: wait_for_delivery(timeout=5)",
                ),
                TestQualityIssue(
                    issue_type="incomplete_assertion",
                    description="assertTrue(result) only checks truthiness, not actual notification count or recipient",
                    severity="high",
                    location="test_rate_limit_enforced",
                    fix="assertEqual(len(delivered), 5) and assert delivered[0].recipient_id == user.id",
                ),
                TestQualityIssue(
                    issue_type="missing_mock",
                    description="Test calls real push notification provider (Firebase) — will fail in CI without credentials",
                    severity="critical",
                    location="test_push_notification_sent",
                    fix="Mock the NotificationProvider with @patch('services.notifications.provider.send')",
                ),
                TestQualityIssue(
                    issue_type="hardcoded_data",
                    description="User ID '12345' hardcoded — will break if that user is deleted from test DB",
                    severity="medium",
                    location="test_user_notification_preference",
                    fix="Create a fixture user in setUp() and reference user.id throughout",
                ),
            ],
            regression_risks=[
                RegressionRisk(
                    code_path="notification_service.send() when user.opt_out=True",
                    risk_level="high",
                    scenario="Opted-out user still receives notification if opt-out flag check is removed",
                    guard_test="test_opted_out_user_receives_no_notification: verify send() is never called when user.opt_out=True",
                ),
                RegressionRisk(
                    code_path="rate_limiter.check() at exactly the limit boundary (n=5)",
                    risk_level="medium",
                    scenario="Off-by-one in rate limit allows 6 notifications instead of 5",
                    guard_test="test_rate_limit_boundary: send exactly 5 → assert 5 delivered; send 6th → assert blocked",
                ),
            ],
            coverage_verdict="partial",
            recommendations=[
                "Replace all time.sleep() with async event waiting or polling helpers",
                "Mock external services (Firebase, APNS) in all unit tests",
                "Add boundary test for rate limit at exactly n=5 and n=6",
                "Add test for opted-out user receiving no notification",
            ],
        )

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    human_msg = input.raw_input
    if input.service_name:
        human_msg = f"Service under test: {input.service_name}\n\n{human_msg}"
    if input.test_content:
        human_msg += f"\n\n--- TEST CODE ---\n{input.test_content[:3000]}"

    chain = (
        ChatPromptTemplate.from_messages([
            ("system", _SYSTEM),
            ("human", "{raw_input}"),
        ])
        | get_routed_llm(task_type="test_review", data_sensitivity=input.data_sensitivity, audience=input.audience, temperature=0)
        | StrOutputParser()
    )

    raw = chain.invoke({"raw_input": human_msg})

    try:
        data = json.loads(raw)
        return TestReviewOutput(**data)
    except Exception as e:
        return TestReviewOutput(
            summary=f"Parse error: {e}",
            quality_score=0.0,
            issues=[],
            regression_risks=[],
            coverage_verdict="poor",
            recommendations=[f"Could not parse review: {str(e)[:100]}"],
        )


# ── Eval-Lite ─────────────────────────────────────────────────────────────────

EVAL_RUBRIC = """
Test Review Skill — Eval Rubric (1–5)

5 — Issues are specific with exact locations and concrete fixes. Regression risks name
    real production code paths. Guard tests are immediately implementable.

4 — Issues are specific. Minor gap in one fix or location. Regression risks identified.

3 — Issues present but descriptions are vague ("test is flaky"). Regression risks are
    generic ("something could break"). Fixes are not actionable.

2 — Only quality score returned. Issues list very short. No regression risks.

1 — Generic test advice ("write better tests"). No specific issues. No fixes.
"""

GOLDEN_EXAMPLES = [
    {
        "input": "Review our notification service tests — they're passing in dev but failing randomly in CI",
        "service_name": "notification_service",
        "expected_issue_types": ["flaky", "missing_mock"],
        "notes": "Random CI failures → likely time.sleep, real network calls, or shared state",
    },
    {
        "input": "Our recommendation engine tests take 45 seconds to run — review them for performance",
        "service_name": "recommendation_engine",
        "expected_issue_types": ["poor_isolation", "missing_mock"],
        "notes": "Slow tests → likely real DB calls, real model loading — need mocks",
    },
    {
        "input": "We had a prod incident where an opted-out user still got notifications. Review our notification tests",
        "service_name": "notification_service",
        "expected_regression_risk_count": 2,
        "notes": "Incident-driven review — must identify the missing guard test for opt-out",
    },
    {
        "input": "Review our A/B test assignment tests for the feed ranking experiment",
        "service_name": "feed_ranking",
        "expected_issue_types": ["missing_edge_case", "hardcoded_data"],
        "notes": "A/B tests — check for consistent assignment, collision handling, holdout group",
    },
]

FAILURE_CASES = [
    {
        "input": "Review my tests",
        "expected_behavior": "Returns generic review with low quality_score; lists what information was missing",
    },
]
