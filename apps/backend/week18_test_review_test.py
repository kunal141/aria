"""
Week 18 — Test Review & Regression Intelligence + AutoGen 2-Agent Demo

Demonstrates:
  1. Test Review skill — quality issues, flaky patterns, regression risks
  2. Full graph routing — test_review task type end-to-end
  3. AutoGen 2-agent demo — CodeReviewerAgent ↔ TestGeneratorAgent
     (runs if pyautogen installed + LLM configured; shows annotated code otherwise)
  4. Architectural comparison: AutoGen conversation vs ARIA skill isolation

Run: uv run python week18_test_review_test.py
     To run AutoGen demo: uv run pip install pyautogen && uv run python week18_test_review_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from aria.skills.test_review_skill import TestReviewInput, TestReviewOutput
import aria.skills.test_review_skill as test_review_skill
from aria.config import has_llm

print("=" * 60)
print("ARIA — Week 18: Test Review + AutoGen 2-Agent Demo")
print("=" * 60)
print(f"\n  LLM configured: {has_llm()}")


# ─────────────────────────────────────────────────────────────────────────────
# 1 — Test Review: CI flakiness investigation
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("1/4  Test Review — notification service CI flakiness")
print("─" * 60)

result: TestReviewOutput = test_review_skill.run(TestReviewInput(
    raw_input="Our notification service tests pass locally but fail randomly in CI — investigate",
    task_id="tr-demo-001",
    service_name="notification_service",
    framework="pytest",
))

print(f"\n  Summary      : {result.summary}")
print(f"  Quality score: {result.quality_score:.0%}")
print(f"  Coverage     : {result.coverage_verdict}")
print(f"  Issues found : {len(result.issues)}")

severity_counts = {}
for issue in result.issues:
    severity_counts[issue.severity] = severity_counts.get(issue.severity, 0) + 1
print(f"  By severity  : {severity_counts}")

print(f"\n  Issues:")
for issue in result.issues:
    icon = {"critical": "!!!", "high": " !!", "medium": "  !", "low": "   "}[issue.severity]
    print(f"\n  [{icon}] [{issue.issue_type:22}] {issue.description[:70]}")
    print(f"        Location: {issue.location}")
    print(f"        Fix     : {issue.fix}")

print(f"\n  Regression risks:")
for risk in result.regression_risks:
    print(f"  [{risk.risk_level:6}] {risk.scenario[:70]}")
    print(f"           Guard: {risk.guard_test[:70]}")

print(f"\n  Recommendations (priority order):")
for i, rec in enumerate(result.recommendations, 1):
    print(f"  {i}. {rec}")


# ─────────────────────────────────────────────────────────────────────────────
# 2 — Test Review: incident-driven (opted-out user got notification)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("2/4  Test Review — incident-driven (post-mortem)")
print("─" * 60)

result2: TestReviewOutput = test_review_skill.run(TestReviewInput(
    raw_input=(
        "We had a prod incident — an opted-out user received push notifications. "
        "Review our notification tests to find what guard test was missing"
    ),
    task_id="tr-demo-002",
    service_name="notification_service",
))

print(f"\n  Quality score: {result2.quality_score:.0%}  |  Coverage: {result2.coverage_verdict}")
critical = [i for i in result2.issues if i.severity == "critical"]
print(f"  Critical issues: {len(critical)}")
for i in critical:
    print(f"    - {i.description[:80]}")
print(f"\n  Regression risks: {len(result2.regression_risks)}")
for r in result2.regression_risks:
    print(f"    [{r.risk_level}] {r.scenario[:70]}")
    print(f"          {r.guard_test[:70]}")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Full graph run — test_review routing
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("3/4  Full graph run — test_review task type")
print("─" * 60)

from aria.graph import aria_graph as graph

state = graph.invoke({
    "raw_input":       "Review our flaky tests in the recommendation engine — they fail in CI every other run",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
    "audience":        "developer",
})

print(f"\n  task_id         : {state['task_id'][:12]}...")
print(f"  task_type       : {state.get('task_type')}")
print(f"  routing_tier    : {state.get('routing_tier')}")
print(f"  steps_completed : {state['steps_completed']}")


# ─────────────────────────────────────────────────────────────────────────────
# 4 — AutoGen 2-Agent Demo
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("4/4  AutoGen 2-Agent Demo — CodeReviewer ↔ TestGenerator")
print("─" * 60)

_AUTOGEN_DEMO_CODE = '''
# ── AutoGen 2-Agent Demo — Week 18 ───────────────────────────────────────────
# Install: uv add pyautogen
# Two agents converse to collaboratively generate tests:
#   CodeReviewerAgent  → analyses code snippet, finds issues
#   TestGeneratorAgent → generates tests targeted at those issues

import autogen

# ── Agent 1: Code Reviewer ────────────────────────────────────────────────────
code_reviewer = autogen.ConversableAgent(
    name="CodeReviewerAgent",
    system_message="""You are an expert code reviewer for a media-tech platform.

    Given a code snippet, identify:
    1. The top 2-3 bugs or edge cases that could cause production issues
    2. Which error paths are NOT currently tested

    Be specific to: notification services, recommendation engines, CMS pipelines.
    After your analysis, end with "ANALYSIS_DONE" so the TestGenerator knows to proceed.""",
    llm_config={"model": "claude-haiku-4-5-20251001", "api_type": "anthropic"},
    human_input_mode="NEVER",
)

# ── Agent 2: Test Generator ────────────────────────────────────────────────────
test_generator = autogen.ConversableAgent(
    name="TestGeneratorAgent",
    system_message="""You are a QA engineer for a media-tech platform.

    When CodeReviewerAgent provides analysis:
    1. Write pytest test cases targeting EXACTLY the issues they identified
    2. Use Given-When-Then format for each test
    3. Mock external services (Firebase, Elasticsearch, Redis)

    After writing the tests, reply with "TERMINATE" to end the conversation.""",
    llm_config={"model": "claude-haiku-4-5-20251001", "api_type": "anthropic"},
    human_input_mode="NEVER",
    is_termination_msg=lambda msg: "TERMINATE" in msg.get("content", ""),
)

# ── Code snippet to review ────────────────────────────────────────────────────
CODE_TO_REVIEW = """
def send_notification(user_id: str, message: str) -> bool:
    user = db.get_user(user_id)
    if user.notifications_enabled:
        count = redis.get(f"notif_count:{user_id}") or 0
        redis.set(f"notif_count:{user_id}", int(count) + 1)
        firebase.send(user.device_token, message)
        return True
    return False
"""

# ── Start the conversation ────────────────────────────────────────────────────
# CodeReviewer starts by analysing the code
# TestGenerator responds with targeted tests
# Conversation ends when TestGenerator says "TERMINATE"
result = code_reviewer.initiate_chat(
    recipient=test_generator,
    message=f"Review this notification service function and identify testable issues:\\n{CODE_TO_REVIEW}",
    max_turns=4,   # safety limit — prevents runaway conversation
)

# ── Extract the generated tests ───────────────────────────────────────────────
# The last message from TestGeneratorAgent contains the test code
conversation = result.chat_history
tests_message = next(
    (m["content"] for m in reversed(conversation) if m["role"] == "assistant"),
    "No tests generated"
)
print(tests_message)

# ── Key architectural insights ────────────────────────────────────────────────
#
# AutoGen advantage here:
#   The CodeReviewer's analysis INFORMS the TestGenerator's output.
#   Tests are targeted at actual issues, not generated blindly.
#   This emergent collaboration can produce higher-quality targeted tests.
#
# ARIA qa_skill advantage:
#   Single LLM call, deterministic, fast, typed Pydantic output.
#   Integrates with Work Ledger, audit log, approval gates.
#   No conversational overhead when the task is well-defined.
#
# When to use each:
#   qa_skill    → routine test generation for a known feature
#   AutoGen     → complex code review + targeted test generation (Week 27+)
'''

# Check if pyautogen is available
_autogen_available = False
_llm_ready = has_llm()

try:
    import autogen  # type: ignore
    _autogen_available = True
except ImportError:
    pass

if _autogen_available and _llm_ready:
    print("\n  pyautogen installed + LLM configured — running live demo...")
    print("  (This would run a real 2-agent conversation)")
    # NOTE: In a real run, exec the demo code above after verifying API config
    print("  [Skipped in test harness — run standalone for live conversation]")
else:
    missing = []
    if not _autogen_available:
        missing.append("pyautogen not installed (uv add pyautogen)")
    if not _llm_ready:
        missing.append("LLM not configured (set ANTHROPIC_API_KEY)")
    print(f"\n  Prerequisites missing: {', '.join(missing)}")
    print("  Showing annotated demo code instead:\n")
    print(_AUTOGEN_DEMO_CODE)

# Architecture comparison table
print("\n  AutoGen vs ARIA qa_skill — architecture comparison:")
print("""
  ┌─────────────────────┬──────────────────────────────┬───────────────────────────────┐
  │                     │ ARIA qa_skill                │ AutoGen 2-agent               │
  ├─────────────────────┼──────────────────────────────┼───────────────────────────────┤
  │ LLM calls           │ 1                            │ 2-8 (per round)               │
  │ Output format       │ Typed Pydantic               │ Raw conversation text         │
  │ Audit trail         │ Work Ledger + LangSmith      │ chat_history dict             │
  │ Governance          │ Action tiers, approval gate  │ human_input_mode              │
  │ Collaboration       │ None (single-pass)           │ Agents refine each other      │
  │ Best for            │ Well-defined, routine tasks  │ Complex analysis + generation │
  │ ARIA uses when      │ Weeks 6-20 (all skills)      │ Weeks 27-29 (debate/review)   │
  └─────────────────────┴──────────────────────────────┴───────────────────────────────┘
""")


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

print("─" * 60)
print("Week 18 — What Was Built:")
print("  skills/test_review_skill.py → quality issues, flaky detection, regression risks")
print("  nodes/skill_nodes.py        → test_review_node registered + wired")
print("  graph.py                    → test_review task type routed")
print("  state.py                    → 'test_review' added to task_type Literal")
print("  [study] AutoGen demo        → 2-agent CodeReviewer ↔ TestGenerator annotated code")
print("  [study] Architecture table  → when AutoGen > ARIA skill and vice versa")
print("\n✅ Week 18 complete.")
