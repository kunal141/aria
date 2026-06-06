"""
Week 15 — Security & Secrets Layer (standalone learning artifact)

Demonstrates:
  1. PII redaction — emails, phones, Aadhaar, API keys, PAN, cards
  2. Tool permission system — tier enforcement, sensitivity ceiling, V1 blocking
  3. Audit logging — append-only JSONL, hash-not-store, query by task_id
  4. data_sensitivity in ARIAState — inferred by intake, overrideable by caller
  5. Full graph run — security layer wired into the intake node

Run: uv run python week15_security_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import os
import uuid
from pathlib import Path

_test_audit = Path(__file__).parent / "_week15_test_tool_audit.jsonl"
os.environ["ARIA_AUDIT_LOG_PATH"] = str(_test_audit)
if _test_audit.exists():
    _test_audit.unlink()

from aria.security import pii_redactor, tool_permissions, audit_log

print("=" * 60)
print("ARIA — Week 15: Security & Secrets Layer")
print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# 1 — PII Redaction
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("1/5  PII Redaction")
print("─" * 60)

samples = [
    ("Email in PR description",
     "Please review — send feedback to kunal@amarujala.com or dev@newsroom.in"),
    ("API key accidentally pasted",
     "My API key is sk-abc123XYZ789secret456longenoughtodetect and I need help"),
    ("Indian phone number",
     "Contact the on-call engineer at +91 9876543210 for production issues"),
    ("Aadhaar in Jira ticket",
     "Employee ID verification: Aadhaar 1234 5678 9012 required for onboarding"),
    ("PAN card in expense report",
     "Tax deduction for ABCDE1234F — please process the reimbursement"),
    ("Mixed PII in a support ticket",
     "User rajesh.sharma@company.com called from 9876543210 about their Aadhaar 1234 5678 9012"),
]

for label, text in samples:
    redacted = pii_redactor.redact(text)
    changed  = text != redacted
    print(f"\n  [{label}]")
    print(f"  In : {text}")
    print(f"  Out: {redacted}")
    print(f"  PII detected: {changed}")

# Sensitivity-aware redaction
print("\n  Sensitivity-aware (public = light redaction):")
api_key_text = "Check the token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.secret123456789012"
print(f"  public    : {pii_redactor.redact(api_key_text, 'public')}")
print(f"  internal  : {pii_redactor.redact(api_key_text, 'internal')}")

# Dict redaction
print("\n  Dict redaction (LangSmith metadata):")
metadata = {
    "task_id": "abc123",
    "user":    "kunal@amarujala.com",
    "context": "Reviewing diff sent by 9876543210",
    "week":    15,
}
clean = pii_redactor.redact_dict(metadata)
print(f"  In : {metadata}")
print(f"  Out: {clean}")


# ─────────────────────────────────────────────────────────────────────────────
# 2 — Tool Permission System
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("2/5  Tool Permission System")
print("─" * 60)

print(f"\n  Registered tools: {tool_permissions.list_tools()}")
print(f"  V1-blocked tools (T4/T5): {tool_permissions.list_blocked_in_v1()}")

checks = [
    # (tool_name, sensitivity, label)
    ("kpi_skill",         "internal",     "KPI on internal data"),
    ("pr_review_skill",   "confidential", "PR review on confidential diff"),
    ("knowledge_search",  "restricted",   "Search on restricted data — should fail"),
    ("jira_draft",        "internal",     "Draft Jira ticket — T3 allowed"),
    ("jira_create",       "internal",     "Create Jira for real — T4, blocked in V1"),
    ("github_pr_comment", "internal",     "Post real PR comment — T4, blocked in V1"),
    ("unknown_tool",      "public",       "Unregistered tool — fail-closed"),
]

print()
for tool, sensitivity, label in checks:
    result = tool_permissions.check(tool, sensitivity)
    icon   = "✓" if result.allowed else "✗"
    print(f"  {icon} [{label}]")
    if not result.allowed:
        print(f"      {result.reason}")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Audit Logging
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("3/5  Audit Log — append-only JSONL")
print("─" * 60)

task_id = f"demo-{uuid.uuid4().hex[:8]}"

# Simulate a sequence of events for one task
audit_log.log_sensitivity_assignment(task_id, "internal", "inferred", "pr_review")

result = tool_permissions.check("pr_review_skill", "internal")
audit_log.log_tool_call(
    task_id=task_id,
    tool_name="pr_review_skill",
    allowed=result.allowed,
    reason=result.reason,
    action_tier="T1",
    data_sensitivity="internal",
    input_preview="Review my PR for the recommendation engine",
    outcome="success" if result.allowed else "blocked",
)

result_blocked = tool_permissions.check("jira_create", "internal")
audit_log.log_tool_call(
    task_id=task_id,
    tool_name="jira_create",
    allowed=result_blocked.allowed,
    reason=result_blocked.reason,
    action_tier="T4",
    data_sensitivity="internal",
    outcome="blocked",
)

# Simulate PII redaction event
pii_text = "Email kunal@test.com and call 9876543210 about this issue"
redacted  = pii_redactor.redact(pii_text)
redaction_count = pii_text.count("@") + (1 if "9876543210" in pii_text else 0)
audit_log.log_pii_redaction(task_id, "langsmith_trace", redaction_count, "internal")

# Query the audit log for this task
print(f"\n  Audit entries for task {task_id[:12]}...:")
entries = audit_log.query(task_id)
for entry in entries:
    detail = entry.get("tool_name") or entry.get("sensitivity") or str(entry.get("redaction_count", "?")) + " redactions"
    print(f"    [{entry['ts'][11:19]}] {entry['event']:25} | {detail}")

print(f"\n  Total entries in log: {len(audit_log.tail(100))}")
print(f"  Log file: {audit_file}")


# ─────────────────────────────────────────────────────────────────────────────
# 4 — data_sensitivity in ARIAState (inferred by intake)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("4/5  data_sensitivity inferred by intake node")
print("─" * 60)

from aria.nodes.intake import _infer_sensitivity

inference_cases = [
    ("CTR dropped 22% this week on the homepage feed",   "internal"),
    ("Review my PR for recommendation engine changes",   "internal"),
    ("Employee salary data needs updating in the system","confidential"),
    ("Need access to production database root",          "restricted"),
    ("My Aadhaar number is 1234 5678 9012",              "confidential"),
]

print()
for raw_input, expected in inference_cases:
    inferred = _infer_sensitivity(raw_input)
    match = "✓" if inferred == expected else "✗"
    print(f"  {match} '{raw_input[:55]}'")
    print(f"      inferred={inferred}  expected={expected}")


# ─────────────────────────────────────────────────────────────────────────────
# 5 — Full graph run — sensitivity flows through state
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("5/5  Full graph run — security wired into intake node")
print("─" * 60)

from aria.graph import aria_graph as graph

result_state = graph.invoke({
    "raw_input":       "CTR dropped 18% this week on the homepage feed, investigate",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
})

print(f"\n  task_id          : {result_state['task_id'][:12]}...")
print(f"  data_sensitivity : {result_state.get('data_sensitivity')}")
print(f"  task_type        : {result_state.get('task_type')}")
print(f"  steps_completed  : {result_state['steps_completed']}")

# Verify audit log captured the sensitivity assignment
entries = audit_log.query(result_state["task_id"])
sens_entries = [e for e in entries if e["event"] == "sensitivity_assigned"]
print(f"  Audit (sensitivity assigned): {bool(sens_entries)}")


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("Week 15 Security Layer — What Was Built:")
print("  pii_redactor.py    → regex-based redaction: email, phone, Aadhaar, PAN, API keys")
print("  tool_permissions.py→ per-tool tier + sensitivity ceiling; T4/T5 blocked in V1")
print("  audit_log.py       → append-only JSONL; input_hash not raw; query by task_id")
print("  state.py           → data_sensitivity field added to ARIAState")
print("  intake.py          → infers sensitivity from raw input; logs to audit trail")
print("\n✅ Week 15 complete.")
