"""
Week 17 — QA / Test Intelligence + AutoGen Study (standalone learning artifact)

Demonstrates:
  1. QA skill — test case generation with Given-When-Then
  2. routing_tier now wired into ARIAState (fixed from Week 16)
  3. qa task type flows end-to-end through the graph
  4. AutoGen architecture study — key concepts vs LangGraph

Run: uv run python week17_qa_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from aria.skills.qa_skill import QAInput, QAOutput
import aria.skills.qa_skill as qa_skill
from aria.config import has_llm

print("=" * 60)
print("ARIA — Week 17: QA / Test Intelligence + AutoGen Study")
print("=" * 60)
print(f"\n  LLM configured: {has_llm()}")


# ─────────────────────────────────────────────────────────────────────────────
# 1 — QA skill: notification rate limiting
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("1/4  QA skill — notification rate limiting feature")
print("─" * 60)

qa_input = QAInput(
    raw_input="Add rate limiting to the push notification service — max 5 notifications per user per hour",
    task_id="qa-demo-001",
    feature_name="NotificationRateLimiter",
)

result: QAOutput = qa_skill.run(qa_input)

print(f"\n  Feature summary: {result.feature_summary}")
print(f"  Test cases generated: {len(result.test_cases)}")
print(f"  Coverage gaps: {len(result.coverage_gaps)}")
print(f"  Test count by type: {result.test_count}")

print(f"\n  Test cases:")
for tc in result.test_cases:
    priority_icon = {"critical": "!!!", "high": " !! ", "medium": "  ! ", "low": "    "}[tc.priority]
    print(f"\n  [{priority_icon}] [{tc.test_type:11}] {tc.name}")
    print(f"    Given: {tc.given}")
    print(f"    When : {tc.when}")
    print(f"    Then : {tc.then}")

if result.coverage_gaps:
    print(f"\n  Coverage gaps:")
    for gap in result.coverage_gaps:
        print(f"    [{gap.risk:6}] {gap.gap}")


# ─────────────────────────────────────────────────────────────────────────────
# 2 — QA skill: recommendation engine freshness
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("2/4  QA skill — recommendation freshness weighting")
print("─" * 60)

qa_input2 = QAInput(
    raw_input="Implement freshness weighting in the feed ranking algorithm — articles < 2h old get 1.5× boost",
    task_id="qa-demo-002",
    feature_name="FeedFreshnessWeight",
)

result2: QAOutput = qa_skill.run(qa_input2)

print(f"\n  Feature summary: {result2.feature_summary}")
print(f"  Tests: {len(result2.test_cases)} | Gaps: {len(result2.coverage_gaps)}")
types_found = {tc.test_type for tc in result2.test_cases}
print(f"  Test types present: {sorted(types_found)}")

critical_tests = [tc for tc in result2.test_cases if tc.priority == "critical"]
print(f"  Critical tests: {len(critical_tests)}")
for tc in critical_tests:
    print(f"    - {tc.name}: {tc.description}")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Full graph run — QA task type routed end-to-end
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("3/4  Full graph run — QA routing + routing_tier wired")
print("─" * 60)

from aria.graph import aria_graph as graph

state = graph.invoke({
    "raw_input":       "Generate test cases for the A/B test framework integration in feed ranking",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
    "audience":        "developer",
})

print(f"\n  task_id          : {state['task_id'][:12]}...")
print(f"  task_type        : {state.get('task_type')}")
print(f"  routing_tier     : {state.get('routing_tier')}  ← wired in Week 17")
print(f"  data_sensitivity : {state.get('data_sensitivity')}")
print(f"  steps_completed  : {state['steps_completed']}")
print(f"\n  Response preview:")
print(f"  {state.get('response', '')[:300]}")


# ─────────────────────────────────────────────────────────────────────────────
# 4 — AutoGen architecture study
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("4/4  AutoGen Architecture Study — Week 17 learning artifact")
print("─" * 60)

AUTOGEN_STUDY = """
AutoGen (Microsoft) — Core Concepts
════════════════════════════════════

WHY AUTOGEN EXISTS
  LangGraph excels at stateful, graph-driven orchestration with human-in-the-loop.
  AutoGen excels at CONVERSATIONAL multi-agent patterns where agents debate, critique,
  and refine output through natural language back-and-forth.
  They solve different problems. ARIA uses both — LangGraph for orchestration, AutoGen
  for debate/critique workflows (Evolution proposal review at Week 27, ML Research
  peer review at Week 29).

KEY ABSTRACTIONS
  ┌─────────────────────────────────────────────────────────┐
  │  ConversableAgent                                        │
  │  Base class for all AutoGen agents.                      │
  │  Can: send messages, receive messages, call tools,       │
  │       generate replies using an LLM.                     │
  │                                                          │
  │  Key args:                                               │
  │    name          = "SkepticAgent"                        │
  │    system_message = "Challenge every assumption..."      │
  │    llm_config    = {"model": "gpt-4o", ...}              │
  │    human_input_mode = "NEVER" | "ALWAYS" | "TERMINATE"  │
  └─────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────┐
  │  UserProxyAgent                                          │
  │  Special ConversableAgent that can:                      │
  │  - Execute code returned by another agent                │
  │  - Represent a human in the conversation                 │
  │  - Terminate the conversation based on a condition       │
  └─────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────┐
  │  GroupChat + GroupChatManager                            │
  │  Orchestrates N agents talking to each other.            │
  │  GroupChatManager uses an LLM to decide "who speaks      │
  │  next" based on conversation history.                    │
  └─────────────────────────────────────────────────────────┘

ACTOR MODEL
  Each agent is an independent actor with its own:
  - System prompt (role identity)
  - LLM config (different agents can use different models)
  - Tool set (optional)
  Agents communicate by passing messages. No shared state dict.
  This is fundamentally different from LangGraph's state machine.

TERMINATION CONDITIONS
  A conversation ends when:
  - An agent replies with a termination keyword ("TERMINATE")
  - Max rounds is reached
  - A custom is_termination_msg() function returns True

HOW IT DIFFERS FROM LANGGRAPH
  ┌────────────────┬────────────────────┬──────────────────────────┐
  │                │ LangGraph          │ AutoGen                  │
  ├────────────────┼────────────────────┼──────────────────────────┤
  │ Model          │ Graph/state machine│ Conversational actors    │
  │ State          │ Shared TypedDict   │ Message history per agent│
  │ Flow control   │ Explicit edges     │ LLM decides who speaks   │
  │ Determinism    │ Predictable graph  │ Emergent conversation    │
  │ Best for       │ Stateful enterprise│ Debate, critique, review │
  │                │ orchestration      │ patterns                 │
  │ Human-in-loop  │ interrupt_before/  │ human_input_mode=ALWAYS  │
  │                │ after              │                          │
  └────────────────┴────────────────────┴──────────────────────────┘

WHEN AUTOGEN BEATS LANGGRAPH
  - Output quality improves through critique and iteration
  - Multiple perspectives genuinely needed (proposer vs skeptic)
  - The number of rounds is unknown in advance
  - Conversation history is the primary state (not structured data)

WHEN LANGGRAPH BEATS AUTOGEN
  - Stateful enterprise flows with typed contracts
  - Deterministic routing required
  - Human approval gates at specific nodes
  - Memory and tool calls need to be governed and auditable

ARIA's AutoGen usage (from CLAUDE.md):
  - Week 17-18: STUDY + 2-agent demo (not production code)
  - Week 22: Side-by-side comparison with CrewAI
  - Week 27: Production — Evolution proposal review (Proposer vs Skeptic vs Implementer)
  - Week 29: Production — ML Research peer review (Paper Reader vs Experiment Designer vs Risk Reviewer)
  LangGraph remains the production backbone for all stateful orchestration.

WEEK 18 BUILD PREVIEW
  Small 2-agent AutoGen demo:
    CodeReviewerAgent: Reviews a code snippet
    TestGeneratorAgent: Generates tests based on the review
  Both converse until TestGeneratorAgent says "DONE"
  Compare output quality vs ARIA's qa_skill running in isolation
"""

print(AUTOGEN_STUDY)


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

print("─" * 60)
print("Week 17 — What Was Built:")
print("  skills/qa_skill.py      → QA/Test Intelligence: TestCase + CoverageGap + Given-When-Then")
print("  nodes/skill_nodes.py    → qa_node registered and wired")
print("  graph.py                → qa task type routes to qa_node")
print("  state.py                → 'qa' added to task_type Literal")
print("  nodes/router.py         → 'qa' keyword rules + routing_tier NOW WIRED")
print("  [study] AutoGen         → ConversableAgent, GroupChat, actor-model vs LangGraph")
print("\n✅ Week 17 complete.")
