"""
Week 16 — Model Router v1 + Approval Gates (standalone learning artifact)

Demonstrates:
  1. ModelRouter — routing decisions for every task type × sensitivity × audience
  2. get_routed_llm() — config.py picks the right model tier automatically
  3. Approval gate — T4 lifecycle: request → approve → check → execute
  4. T4 tools now unblocked through approval gate (T5 still blocked)
  5. Full graph run — routing_tier in ARIAState, logged to Work Ledger

Run: uv run python week16_model_router_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import uuid
from aria.routing.model_router import ModelRouter, route
from aria.governance import approval_gate
from aria.security import tool_permissions
from aria.security.audit_log import tail as audit_tail

print("=" * 60)
print("ARIA — Week 16: Model Router v1 + Approval Gates")
print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# 1 — ModelRouter routing decisions
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("1/5  ModelRouter — routing decisions")
print("─" * 60)

router = ModelRouter()

cases = [
    # (task_type, sensitivity, audience, complexity, label)
    ("general",    "internal",     None,         None,      "General query"),
    ("kpi",        "internal",     "developer",  None,      "KPI investigation — developer"),
    ("kpi",        "internal",     "leadership", None,      "KPI investigation — leadership brief"),
    ("pr_review",  "internal",     "developer",  "normal",  "PR review — normal diff"),
    ("pr_review",  "internal",     "developer",  "complex", "PR review — huge diff, complex"),
    ("pr_review",  "confidential", "developer",  None,      "PR review — confidential codebase"),
    ("pr_review",  "restricted",   "developer",  None,      "PR review — restricted data"),
    ("ci_cd",      "internal",     None,         "simple",  "CI/CD — simple failure"),
    ("jira",       "internal",     "manager",    None,      "Jira ticket creation"),
    ("unknown",    "public",       None,         None,      "Unknown task type"),
]

print()
for task_type, sensitivity, audience, complexity, label in cases:
    d = router.route(
        task_type=task_type,
        data_sensitivity=sensitivity,
        audience=audience,
        complexity=complexity,
        input_length=300,
    )
    tier_icon = {"fast": "⚡", "smart": "🔵", "frontier": "★"}[d.tier]
    print(f"  {tier_icon} [{d.tier:8}] {label}")
    print(f"           {d.reason}   cost={d.estimated_cost}")
    if d.privacy_note:
        print(f"           ⚠ {d.privacy_note}")


# ─────────────────────────────────────────────────────────────────────────────
# 2 — get_routed_llm() — config integration
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("2/5  get_routed_llm() — config.py integration")
print("─" * 60)

from aria.config import get_routed_llm, get_fast_llm, get_smart_llm, get_frontier_llm, has_llm

print(f"\n  LLM configured: {has_llm()}")
print(f"\n  Routing tier tests (returns LLM object — not invoked here):")

routing_tests = [
    dict(task_type="general",   data_sensitivity="public"),
    dict(task_type="pr_review", data_sensitivity="internal", audience="developer"),
    dict(task_type="kpi",       data_sensitivity="internal", audience="leadership"),
    dict(task_type="pr_review", data_sensitivity="confidential"),
]

for kwargs in routing_tests:
    from aria.routing.model_router import route as route_fn
    d = route_fn(**kwargs, input_length=300)
    llm = get_routed_llm(**kwargs, input_length=300)
    llm_type = type(llm).__name__
    print(f"  {kwargs.get('task_type'):10} + {kwargs.get('audience','developer'):10} → {d.tier:8} → {llm_type}")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Approval gate lifecycle
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("3/5  Approval gate — T4 request → approve → execute")
print("─" * 60)

approval_gate.clear()
task_id = f"demo-{uuid.uuid4().hex[:8]}"

# Step 1: Try T4 tool without approval — should fail
result = tool_permissions.check_with_approval("jira_create", task_id, "internal")
print(f"\n  [Before approval]")
print(f"  check_with_approval('jira_create', task_id): allowed={result.allowed}")
print(f"  reason: {result.reason}")

# Step 2: Request approval
req = approval_gate.request_approval(
    task_id=task_id,
    tool_name="jira_create",
    proposed_action="Create Jira ticket: [ARIA-42] Add rate limiting to notification service",
)
print(f"\n  [Approval requested]")
print(f"  request_id : {req.request_id[:12]}...")
print(f"  status     : {req.status}")
print(f"  action     : {req.proposed_action}")

# Step 3: Human approves (simulated)
approved = approval_gate.approve(req.request_id, approved_by="kunal.mahajan")
print(f"\n  [Human approves]")
print(f"  status     : {approved.status}")
print(f"  approved_by: {approved.approved_by}")

# Step 4: Re-check — now allowed
result2 = tool_permissions.check_with_approval("jira_create", task_id, "internal")
print(f"\n  [After approval]")
print(f"  check_with_approval('jira_create', task_id): allowed={result2.allowed}")
print(f"  reason: {result2.reason}")

# Step 5: Rejection flow
task_id2 = f"demo-{uuid.uuid4().hex[:8]}"
req2 = approval_gate.request_approval(task_id2, "github_pr_comment", "Post review comment on PR #87")
rejected = approval_gate.reject(req2.request_id, reason="Too risky — needs manual review first")
print(f"\n  [Rejection flow]")
print(f"  status          : {rejected.status}")
print(f"  rejection_reason: {rejected.rejection_reason}")

# Step 6: T5 still blocked
result_t5 = tool_permissions.check("github_pr_comment", "internal")  # check() not check_with_approval
result_t4_no_approval = tool_permissions.check_with_approval("github_pr_comment", task_id2, "internal")
print(f"\n  [T5 check] github_pr_comment via check(): allowed={result_t5.allowed}")
print(f"  [T4 rejected] github_pr_comment via check_with_approval(): allowed={result_t4_no_approval.allowed}")


# ─────────────────────────────────────────────────────────────────────────────
# 4 — Pending approval queue
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("4/5  Pending approval queue")
print("─" * 60)

# Create a few more pending requests
task_id3 = f"demo-{uuid.uuid4().hex[:8]}"
approval_gate.request_approval(task_id3, "teams_message_send", "Notify #engineering about deploy")
task_id4 = f"demo-{uuid.uuid4().hex[:8]}"
approval_gate.request_approval(task_id4, "jira_create", "Create ticket for CTR regression investigation")

pending = approval_gate.get_pending()
print(f"\n  Pending approvals in queue: {len(pending)}")
for p in pending:
    print(f"  [{p.task_id[:8]}] {p.tool_name:25} | {p.proposed_action[:50]}")

print(f"\n  (In Teams bot: each pending request generates an Adaptive Card with Approve/Reject buttons)")


# ─────────────────────────────────────────────────────────────────────────────
# 5 — Full graph run with routing_tier in state
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("5/5  Full graph run — routing_tier flows through ARIAState")
print("─" * 60)

from aria.graph import aria_graph as graph

result_state = graph.invoke({
    "raw_input":       "Review my PR for the recommendation engine — I changed the ranking weights",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
    "audience":        "developer",
})

print(f"\n  task_id          : {result_state['task_id'][:12]}...")
print(f"  task_type        : {result_state.get('task_type')}")
print(f"  data_sensitivity : {result_state.get('data_sensitivity')}")
print(f"  routing_tier     : {result_state.get('routing_tier', 'not set — wire in Week 17')}")
print(f"  steps_completed  : {result_state['steps_completed']}")


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("Week 16 — What Was Built:")
print("  routing/model_router.py   → ModelRouter: 5-rule routing table → fast/smart/frontier")
print("  governance/approval_gate.py → T4 lifecycle: request → approve/reject → check")
print("  config.py                 → get_frontier_llm(), get_routed_llm()")
print("  state.py                  → routing_tier, complexity, approval_request_id fields")
print("  tool_permissions.py       → T4 now unlocked via approval gate; T5 still blocked")
print("\n  Routing tiers:")
print("    fast      → SLM or Haiku — classification, simple tasks  (~$0)")
print("    smart     → Sonnet — PR review, KPI, normal engineering  (~$0.001)")
print("    frontier  → Opus — leadership briefs, complex, high-stakes (~$0.01+)")
print("\n✅ Week 16 complete.")
