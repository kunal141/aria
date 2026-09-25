"""
PR Review Skill — Week 7

ARIA's second real skill. Reviews pull requests for:
  - Code quality issues
  - Deployment risk (what could break in prod)
  - Business impact (effect on CTR, feed, notifications)
  - Missing test coverage

Domain context: supplied per tenant via TenantOrgProfile
Relevant systems: CMS pipelines, recommendation engine,
                  notification service, personalisation, analytics
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

import aria.config  # must be first
from aria.config import get_routed_llm, has_llm
from aria.skills.json_output import parse_json_object
from aria.tracing import traceable

# ─────────────────────────────────────────────────────────────────────────────
# Input Schema
# ─────────────────────────────────────────────────────────────────────────────

class PRReviewInput(BaseModel):
    raw_input:        str = Field(..., description="User's description of the PR or diff to review")
    task_id:          str = Field(..., description="Unique task identifier from ARIAState")
    diff:             str = Field(default="", description="Optional: actual git diff or code snippet")
    pr_title:         str = Field(default="", description="Optional: PR title for context")
    data_sensitivity: str = Field(default="internal", description="Routing signal: public/internal/confidential/restricted")
    audience:         str = Field(default="developer", description="Routing signal: developer/manager/leadership")


# ─────────────────────────────────────────────────────────────────────────────
# Output Schema
# ─────────────────────────────────────────────────────────────────────────────

class CodeIssue(BaseModel):
    severity: Literal["critical", "high", "medium", "low"]
    category: Literal["correctness", "performance", "security", "maintainability", "test_coverage"]
    description: str
    suggestion: str


class PRReviewOutput(BaseModel):
    verdict: Literal["approve", "request_changes", "needs_discussion"]
    risk_level: Literal["high", "medium", "low"]
    summary: str                        # one-sentence executive summary
    code_issues: list[CodeIssue]        # specific issues found
    missing_tests: list[str]            # test cases that should exist but don't
    deployment_risks: list[str]         # what could break in production
    business_impact: str                # effect on CTR, feed, notifications, etc.
    positive_observations: list[str]    # what was done well
    version: str = "v1"
    component_version: Optional[str] = None   # semantic version of the active prompt (if promoted)
    component_hash:    Optional[str] = None   # SHA-256 of the prompt content actually used


# ─────────────────────────────────────────────────────────────────────────────
# Skill Prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM = """You are ARIA, an AI code reviewer for the organization described in the operating context.

You review pull requests for the platform's core engineering systems:
- CMS pipeline: article ingestion, enrichment, indexing
- Recommendation engine: personalised feed, trending stories, related articles
- Notification service: push notifications, email, in-app alerts
- Analytics pipeline: event tracking, CTR computation, engagement metrics
- Personalisation: user preference modelling, A/B test assignment

When reviewing a PR, you assess:
1. Code correctness and edge cases
2. Performance implications (latency, memory, query efficiency)
3. Security (injection risks, auth gaps, data exposure)
4. Test coverage gaps
5. Deployment risk (what could fail in production at scale)
6. Business impact on key metrics (CTR, open rate, feed quality)

Respond with ONLY valid JSON matching this exact structure:
{
  "verdict": "approve|request_changes|needs_discussion",
  "risk_level": "high|medium|low",
  "summary": "one sentence executive summary of the PR quality",
  "code_issues": [
    {
      "severity": "critical|high|medium|low",
      "category": "correctness|performance|security|maintainability|test_coverage",
      "description": "what the issue is",
      "suggestion": "what to do instead"
    }
  ],
  "missing_tests": ["test case that should exist", "another missing test"],
  "deployment_risks": ["risk 1 in production", "risk 2"],
  "business_impact": "how this change could affect CTR, feed, notifications, etc.",
  "positive_observations": ["what was done well", "another good pattern"]
}

If no code diff is provided, infer from the PR description what likely changed and flag uncertainty.
Be specific to media-tech systems. Do not give generic advice."""


# ─────────────────────────────────────────────────────────────────────────────
# Skill Function
# ─────────────────────────────────────────────────────────────────────────────

@traceable(
    run_type="chain",
    name="pr_review_skill_v1",
    tags=["skill", "pr_review", "aria"],
)
def run(input: PRReviewInput) -> PRReviewOutput:
    # Load active prompt from the component store. The "no active release"
    # case is handled by component_loader.load() itself, which returns
    # ``(default, None, None)`` — so a fallback to the hardcoded ``_SYSTEM``
    # only occurs when no release exists at all.
    #
    # If an active release IS present, the loader reads its on-disk artifact
    # and re-verifies the SHA-256 hash. A missing, unreadable, outside-root,
    # or hash-mismatched artifact raises ComponentArtifactError and this
    # function MUST allow it to propagate — silently falling back to
    # ``_SYSTEM`` would defeat the runtime artifact-authority contract by
    # running PR review with the wrong (and unauditable) prompt.
    import aria.evolution.component_loader as _cl

    system_prompt, comp_hash, comp_version = _cl.load(
        "pr_review_prompt", default=_SYSTEM,
    )

    if not has_llm():
        return PRReviewOutput(
            verdict="needs_discussion",
            risk_level="medium",
            summary=f"[Mock] PR review for: {input.raw_input[:80]}",
            code_issues=[
                CodeIssue(
                    severity="medium",
                    category="test_coverage",
                    description="No unit tests visible for the recommendation ranking change",
                    suggestion="Add tests for edge cases: empty candidate list, all candidates below threshold",
                ),
                CodeIssue(
                    severity="low",
                    category="maintainability",
                    description="Magic numbers in ranking weights should be named constants",
                    suggestion="Extract to a config file or named constants with descriptive names",
                ),
            ],
            missing_tests=[
                "Unit test: recommendation returns empty list when no candidates pass threshold",
                "Integration test: CTR feedback loop doesn't cause feedback explosion",
                "Load test: ranking latency under 10K concurrent requests",
            ],
            deployment_risks=[
                "Ranking weight change could cause sudden feed diversity drop — monitor CTR in first 30 min post-deploy",
                "No feature flag — rollback requires a new deployment",
            ],
            business_impact="Changes to recommendation ranking directly affect feed CTR. A 10% weight shift can move CTR by 1–3%. Monitor closely after deploy.",
            positive_observations=[
                "Clean separation of ranking logic from data fetching",
                "Good use of caching for candidate retrieval",
            ],
            component_hash=comp_hash,
            component_version=comp_version,
        )

    from langchain_core.messages import SystemMessage
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    human_msg = input.raw_input
    if input.pr_title:
        human_msg = f"PR Title: {input.pr_title}\n\n{human_msg}"
    if input.diff:
        human_msg += f"\n\n--- DIFF ---\n{input.diff}"

    chain = (
        ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            ("human", "{raw_input}"),
        ])
        | get_routed_llm(task_type="pr_review", data_sensitivity=input.data_sensitivity, audience=input.audience, temperature=0)
        | StrOutputParser()
    )

    raw = chain.invoke({"raw_input": human_msg})

    try:
        data = parse_json_object(raw)
        return PRReviewOutput(**data, component_hash=comp_hash, component_version=comp_version)
    except Exception as exc:
        error_type = type(exc).__name__
        return PRReviewOutput(
            verdict="needs_discussion",
            risk_level="medium",
            summary=f"Model output invalid ({error_type}; details redacted).",
            code_issues=[],
            missing_tests=[],
            deployment_risks=[],
            business_impact="Could not parse review output.",
            positive_observations=[],
            component_hash=comp_hash,
            component_version=comp_version,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Eval-Lite — mandatory from Week 6 (full LangSmith harness at Week 14)
# ─────────────────────────────────────────────────────────────────────────────

EVAL_RUBRIC = """
PR Review Skill — Eval Rubric (1–5)

5 — Verdict is justified by specific issues. All issues have severity + category + actionable suggestion.
    Missing tests are named precisely. Deployment risks are production-specific, not generic.
    Business impact links the code change to a metric.

4 — Verdict justified. Issues are clear. Minor gaps in test coverage specificity or deployment risk.

3 — Verdict present but weakly justified. Issues are vague ("refactor this").
    Missing tests are generic ("add more tests"). Business impact is surface-level.

2 — Only one or two issues. No missing tests. Deployment risk missing or trivial.
    Business impact absent.

1 — No structured output. Generic review advice. No connection to media-tech systems.
"""

GOLDEN_EXAMPLES = [
    {
        "input": "Review my PR for the recommendation engine — I changed the ranking weights to favour freshness over engagement",
        "expected_verdict": "needs_discussion",
        "expected_min_issues": 1,
        "expected_risk_level": "medium",
        "notes": "Ranking weight change — should flag CTR monitoring, A/B test suggestion, missing feature flag",
    },
    {
        "input": "PR adds a new push notification trigger for breaking news stories",
        "expected_verdict_options": ["approve", "needs_discussion"],
        "expected_min_issues": 1,
        "notes": "Notification frequency risk — should flag opt-out rate impact, rate limiting, A/B test",
    },
    {
        "input": "Refactoring the article ingestion pipeline to use async processing",
        "expected_risk_level": "high",
        "expected_min_issues": 2,
        "notes": "Async refactor = high risk — should flag data loss edge cases, error handling, rollback plan",
    },
    {
        "input": "PR fixes a null pointer in the CTR computation job",
        "expected_verdict": "approve",
        "expected_risk_level": "low",
        "notes": "Bug fix — should approve but verify the null case is tested",
    },
    {
        "input": "Adding A/B test framework integration to the feed ranking service",
        "expected_min_issues": 1,
        "notes": "A/B test infra — should check for experiment collision, holdout group, logging of variant assignment",
    },
]

FAILURE_CASES = [
    {
        "input": "Review this code",
        "expected_behavior": "Asks for diff or description in data_needed, returns needs_discussion with low confidence",
    },
    {
        "input": "My PR looks good, approve it",
        "expected_behavior": "Does not auto-approve — returns needs_discussion and lists what it cannot verify without a diff",
    },
    {
        "input": "Fix typo in README.md",
        "expected_behavior": "Approves with low risk, no code issues, minimal missing tests — does not over-review trivial changes",
    },
]
