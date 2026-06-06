"""
Week 13 — LangSmith Deep Tracing + Audience-Aware Rendering (standalone)

Demonstrates:
  1. @traceable on skills — runs appear in LangSmith with ARIA metadata
  2. log_feedback() — approval/rejection paired with trace
  3. Audience-aware rendering — same task, three different outputs
  4. LangSmith project URL printed for easy navigation

Run: uv run python week13_langsmith_test.py
     Then open smith.langchain.com → project ARIA to see the traces.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import os
from pathlib import Path

_test_store = Path(__file__).parent / "_week13_test_memory_store.json"
os.environ["ARIA_MEMORY_STORE_PATH"] = str(_test_store)
if _test_store.exists():
    _test_store.unlink()

from aria.graph import aria_graph as graph
from aria.tracing import log_feedback, get_project_url, get_run_url
from aria.memory.manager import memory

print("=" * 60)
print("ARIA — Week 13: LangSmith Tracing + Audience-Aware Rendering")
print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# 1 — LangSmith status
# ─────────────────────────────────────────────────────────────────────────────

tracing_on = os.getenv("LANGCHAIN_TRACING_V2") == "true"
project_url = get_project_url()

print(f"\n📡 LangSmith tracing : {'ON' if tracing_on else 'OFF (set LANGCHAIN_API_KEY to enable)'}")
if project_url:
    print(f"   Dashboard         : {project_url}")
print()


# ─────────────────────────────────────────────────────────────────────────────
# 2 — Run a PR review task — developer audience (full card)
# ─────────────────────────────────────────────────────────────────────────────

print("─" * 60)
print("1/3  PR Review — audience: developer  (full technical card)")
print("─" * 60)

result_dev = graph.invoke({
    "raw_input":       "Review my PR for the recommendation engine ranking changes",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
    "audience":        "developer",
})

print(result_dev["response"])
print(f"\n   task_id  : {result_dev['task_id']}")
print(f"   trail    : {result_dev['steps_completed']}")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Same task — manager audience (compact summary)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("2/3  PR Review — audience: manager  (compact summary)")
print("─" * 60)

result_mgr = graph.invoke({
    "raw_input":       "Review my PR for the recommendation engine ranking changes",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
    "audience":        "manager",
})

print(result_mgr["response"])


# ─────────────────────────────────────────────────────────────────────────────
# 4 — Same task — leadership audience (executive brief)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("3/3  PR Review — audience: leadership  (executive brief)")
print("─" * 60)

result_lead = graph.invoke({
    "raw_input":       "Review my PR for the recommendation engine ranking changes",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
    "audience":        "leadership",
})

print(result_lead["response"])


# ─────────────────────────────────────────────────────────────────────────────
# 5 — Log feedback (approve dev result, reject leadership)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("📝 Logging feedback to Work Ledger + LangSmith...")

task_id_dev  = result_dev["task_id"]
task_id_lead = result_lead["task_id"]

# Approved — positive SFT example
memory.record_outcome(task_id_dev, "pr_review", approved=True)
print(f"   ✓ Approved  : {task_id_dev[:12]}... (positive training example)")

# Rejected with correction — DPO negative example
memory.record_outcome(
    task_id_lead, "pr_review", approved=False,
    correction="Leadership brief missed the deployment risk entirely — "
               "always include a one-line deployment risk statement",
)
print(f"   ✗ Rejected  : {task_id_lead[:12]}... (DPO negative example with correction)")

# If LangSmith is enabled, these approvals are also logged to the traces
if tracing_on:
    print("   → Feedback also logged to LangSmith traces (check dashboard)")


# ─────────────────────────────────────────────────────────────────────────────
# 6 — KPI task with tracing
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("📊 KPI Investigation — traced run")
print("─" * 60)

result_kpi = graph.invoke({
    "raw_input":       "CTR dropped 18% this week on the homepage feed, investigate",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
    "audience":        "manager",
})

print(result_kpi["response"])
memory.record_outcome(result_kpi["task_id"], "kpi", approved=True)
print(f"\n   ✓ KPI result approved — logged to Work Ledger")


# ─────────────────────────────────────────────────────────────────────────────
# 7 — ROI snapshot
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
roi = memory.roi_snapshot()
print("📊 Work Ledger snapshot after this session:")
print(f"   Outcomes  : {roi['total_outcomes']}")
print(f"   Approved  : {roi['approved']}")
print(f"   Rejected  : {roi['rejected']}")
print(f"   Approval  : {roi['approval_rate']:.0%}")

print("\n" + "─" * 60)
print("Audience rendering summary:")
print("  developer  → full technical card (all issues, all risks, code detail)")
print("  manager    → 5-line summary (verdict + risk + top issue + business impact)")
print("  leadership → 2-line executive brief (verdict + impact + action required)")

if project_url:
    print(f"\n   LangSmith → {project_url}")

print("\n✅ Week 13 complete.")
