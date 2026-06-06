"""
Week 11 — Memory Fabric Test (standalone)

Demonstrates the three-tier MemGPT/Letta pattern:
  Hot  → ARIAState (current run — not shown here)
  Warm → MemoryManager.remember/recall (JSON-backed, shown here)
  Cold → Chroma ingestion at session end (shown at end)

Run: uv run python week11_memory_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import os
from pathlib import Path

# Use a test-specific store so the demo never corrupts real memory_store.json.
# ARIA_MEMORY_STORE_PATH is read by aria.memory.store before the module loads.
_test_store = Path(__file__).parent / "_week11_test_memory_store.json"
os.environ["ARIA_MEMORY_STORE_PATH"] = str(_test_store)
if _test_store.exists():
    _test_store.unlink()

from aria.memory.manager import memory


print("=" * 60)
print("ARIA — Week 11: Memory Fabric v1")
print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Session memory (what happened this conversation)
# ─────────────────────────────────────────────────────────────────────────────

print("\n📝 Writing session events...")

s1 = memory.remember_session_event(
    "User asked ARIA to review the recommendation engine PR",
    importance="medium",
)
s2 = memory.remember_session_event(
    "ARIA ran pr_review:v1 — verdict: needs_discussion, risk: medium",
    task_id="task-abc-123",
    importance="high",
)
s3 = memory.remember_session_event(
    "User approved the PR review report and forwarded it to the team",
    task_id="task-abc-123",
    importance="high",
)

print(f"   Written {3} session events")
print(f"   IDs: {s1.memory_id[:8]}... {s2.memory_id[:8]}... {s3.memory_id[:8]}...")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Task memory (what the task produced)
# ─────────────────────────────────────────────────────────────────────────────

print("\n📋 Writing task memory...")

t1 = memory.remember_task(
    task_id="task-abc-123",
    skill_name="pr_review",
    summary="PR review for recommendation engine — ranking weight change, 2 code issues, no feature flag",
    verdict="needs_discussion",
    tags=["recommendation", "pr_review", "ranking"],
)

t2 = memory.remember_task(
    task_id="task-kpi-456",
    skill_name="kpi",
    summary="CTR drop 18% week-on-week — top hypothesis: content diversity reduced by model weight change",
    tags=["ctr", "kpi", "recommendation"],
)

print(f"   Task memory: {t1.memory_id[:8]}... (pr_review)")
print(f"   Task memory: {t2.memory_id[:8]}... (kpi)")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — User preference memory (Human Teaching Layer seed)
# ─────────────────────────────────────────────────────────────────────────────

print("\n👤 Learning user preferences...")

p1 = memory.learn_user_preference(
    "Kunal always wants a rollback plan mentioned in PR reviews for Tier 3+ changes",
    category="pattern",
    confidence=0.9,
    tags=["pr_review"],
)
p2 = memory.learn_user_preference(
    "Kunal's team uses feature flags for all recommendation engine changes — flag absence is always a risk",
    category="context",
    confidence=0.95,
    tags=["pr_review", "recommendation"],
)
p3 = memory.learn_user_preference(
    "Kunal prefers root causes ranked by likelihood (high → low), not alphabetically",
    category="preference",
    confidence=0.8,
    tags=["kpi"],
)

print(f"   Learned {3} user preferences")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Outcome memory (approve/reject = DPO training seed)
# ─────────────────────────────────────────────────────────────────────────────

print("\n✅ Recording outcomes...")

o1 = memory.record_outcome(
    task_id="task-abc-123",
    skill_name="pr_review",
    approved=True,
)
o2 = memory.record_outcome(
    task_id="task-kpi-456",
    skill_name="kpi",
    approved=False,
    correction="Root causes should mention A/B test holdout group drift — this was the actual cause",
)

print(f"   pr_review → APPROVED")
print(f"   kpi       → REJECTED (with correction)")


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — Recall operations
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("RECALL OPERATIONS")
print("─" * 60)

# Recent session events
print("\n🕐 Recent session events:")
for m in memory.recall_session(limit=3):
    print(f"   [{m['importance']}] {m['content'][:70]}")

# Task recall by task_id
print("\n🎯 Everything ARIA remembers about task-abc-123:")
for m in memory.recall_task("task-abc-123"):
    print(f"   [{m['memory_type']}] {m['content'][:70]}")

# User preferences
print("\n👤 User preferences ARIA has learned:")
for m in memory.recall_user_preferences():
    print(f"   [{m['category']}] (conf={m['confidence']}) {m['content'][:70]}")

# Context for pr_review skill
print("\n💉 Context to inject before next pr_review call:")
relevant = memory.recall_for_skill("pr_review", limit=3)
print(memory.format_for_prompt(relevant))

# Stats
print(f"\n📊 Memory stats: {memory.stats()}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 6 — Inspect the JSON store on disk
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("📁 _week11_test_memory_store.json (first record):")
raw = json.loads(_test_store.read_text(encoding="utf-8"))
print(json.dumps(raw[0], indent=2))
print(f"   ... ({len(raw)} total records)")


# ─────────────────────────────────────────────────────────────────────────────
# Step 7 — Session end: promote session memories to cold, then clear warm
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("🔚 Ending session — promoting session memories to Chroma cold store...")
cleared = memory.end_session(promote_to_cold=True)
print(f"   Cleared {cleared} session memories from warm store")
print(f"   Memory stats after session end: {memory.stats()}")
print("\n✅ Week 11 Memory Fabric test complete.")
