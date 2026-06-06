"""
Week 12 — Institutional & Outcome Memory Test (standalone)

Demonstrates:
  1. Decision memory — architectural choices logged permanently
  2. Artifact memory — skill outputs stored and retrieved by task_id
  3. Outcome querying — filter by approved/rejected (fine-tuning data pipeline)
  4. Semantic memory search — find past decisions by meaning, not keyword
  5. ROI snapshot — seed of the Week 29 Work Ledger dashboard

Run: uv run python week12_institutional_memory_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import os
from pathlib import Path

_test_store = Path(__file__).parent / "_week12_test_memory_store.json"
os.environ["ARIA_MEMORY_STORE_PATH"] = str(_test_store)
if _test_store.exists():
    _test_store.unlink()

from aria.memory.manager import memory


print("=" * 60)
print("ARIA — Week 12: Institutional & Outcome Memory")
print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# 1 — Decision memory (architectural choices, permanent)
# ─────────────────────────────────────────────────────────────────────────────

print("\n🏛  Recording architectural decisions...")

memory.record_decision(
    decision="Use Chroma (in-memory) for Week 9 RAG, migrate to pgvector at Week 11",
    rationale="Chroma is zero-config and LangChain-native — right for learning phase. pgvector needed when ACID + SQL filters matter.",
    alternatives=["FAISS (faster, no metadata)", "Weaviate (managed, cost)", "pgvector directly (skips learning curve)"],
    outcome="Working — 58 chunks indexed, 4-query test all passed",
    week=9,
    tags=["rag", "vector-store", "architecture"],
)

memory.record_decision(
    decision="File-backed JSON for warm memory store (Week 11), not SQLite/Postgres",
    rationale="Zero deps during learning phase. Single-file, human-readable, trivially inspectable. Migration is one file swap.",
    alternatives=["SQLite (zero-server, but binary)", "Postgres (full ACID, but infra overhead)"],
    outcome="Working — memory_store.json readable with any text editor",
    week=11,
    tags=["memory", "architecture"],
)

memory.record_decision(
    decision="Skill registry pattern: register(name, fn, version, tier) → decouples node from skill file",
    rationale="Allows swapping kpi_skill v1 → v2 without changing kpi_node. Enables fine-tuned model routing at Week 29.",
    alternatives=["Direct import in node (simpler but tightly coupled)"],
    week=6,
    tags=["skills", "architecture"],
)

print(f"   Recorded 3 architectural decisions")


# ─────────────────────────────────────────────────────────────────────────────
# 2 — Artifact memory (skill outputs linked to tasks)
# ─────────────────────────────────────────────────────────────────────────────

print("\n📎 Storing skill output artifacts...")

TASK_PR  = "task-pr-001"
TASK_KPI = "task-kpi-002"

art1 = memory.store_artifact(
    task_id=TASK_PR,
    skill_name="pr_review",
    artifact_type="pr_review",
    artifact_content="verdict: needs_discussion | risk: medium | issues: 2 | missing_tests: 3 | deployment_risks: 2",
    tags=["recommendation", "ranking"],
)

art2 = memory.store_artifact(
    task_id=TASK_KPI,
    skill_name="kpi",
    artifact_type="kpi_brief",
    artifact_content="summary: CTR dropped 18% | root_causes: 2 | confidence: 0.0 | recommended_actions: 2",
    tags=["ctr", "feed"],
)

print(f"   pr_review artifact: {art1.memory_id[:8]}...")
print(f"   kpi_brief artifact: {art2.memory_id[:8]}...")

# Retrieve artifact by task_id
retrieved = memory.get_artifact(TASK_PR)
print(f"\n   Retrieve artifact for {TASK_PR}:")
print(f"   → skill: {retrieved['skill_name']}  type: {retrieved['artifact_type']}")
print(f"   → content: {retrieved['artifact_content'][:60]}")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Outcome records + querying
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("✅ Recording outcomes and querying...")

memory.record_outcome(TASK_PR,  "pr_review", approved=True)
memory.record_outcome(TASK_KPI, "kpi", approved=False,
    correction="Should have flagged A/B holdout group drift as a root cause — that was the actual issue")

# Also add a second approved kpi to show ratio
memory.record_outcome("task-kpi-003", "kpi", approved=True)

# Query approved outcomes → positive fine-tuning examples
approved = memory.query_outcomes(approved=True)
print(f"\n   Approved outcomes ({len(approved)}) — positive fine-tuning examples:")
for o in approved:
    print(f"   ✓ [{o['skill_name']}] {o['content'][:60]}")

# Query rejected outcomes → DPO negative examples
rejected = memory.query_outcomes(approved=False)
print(f"\n   Rejected outcomes ({len(rejected)}) — DPO negative examples:")
for o in rejected:
    print(f"   ✗ [{o['skill_name']}] correction: {o.get('correction', '')[:60]}")

# Filter by skill
kpi_outcomes = memory.query_outcomes(skill_name="kpi")
print(f"\n   All KPI outcomes: {len(kpi_outcomes)} total")
for o in kpi_outcomes:
    status = "✓" if o.get("approved") else "✗"
    print(f"   {status} {o['content'][:55]}")


# ─────────────────────────────────────────────────────────────────────────────
# 4 — Decision recall
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("🏛  Recalling architectural decisions...")

decisions = memory.recall_decisions()
print(f"   {len(decisions)} decisions on record:")
for d in decisions:
    print(f"\n   Week {d.get('week', '?')} — {d.get('decision', '')[:60]}")
    print(f"   Rationale: {d.get('rationale', '')[:60]}")
    alts = d.get("alternatives", [])
    if alts:
        print(f"   Alternatives considered: {len(alts)}")
    if d.get("outcome"):
        print(f"   Outcome: {d['outcome'][:55]}")


# ─────────────────────────────────────────────────────────────────────────────
# 5 — Semantic memory search (cold tier)
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("🔍 Semantic memory search (cold Chroma tier)...")

# First promote a session memory to cold so there's something to search
memory.remember_session_event(
    "Discussed architecture decision: chose Chroma over FAISS because LangChain-native and zero config",
    importance="high",
)
memory.end_session(promote_to_cold=True)

chunks = memory.search_memory("which vector store did we choose for RAG and why?", k=2)
print(f"   Query: 'which vector store did we choose for RAG and why?'")
print(f"   Hits : {len(chunks)}")
for c in chunks:
    print(f"   [{c.source}] dist={c.distance:.3f}: {c.text[:80]}...")


# ─────────────────────────────────────────────────────────────────────────────
# 6 — ROI snapshot (Work Ledger seed)
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("📊 ROI Snapshot (Work Ledger seed):")
roi = memory.roi_snapshot()
print(f"   Total artifacts  : {roi['total_artifacts']}")
print(f"   Total outcomes   : {roi['total_outcomes']}")
print(f"   Approved         : {roi['approved']}")
print(f"   Rejected         : {roi['rejected']}")
print(f"   Approval rate    : {roi['approval_rate']:.0%}")
print(f"   By skill         : {roi['artifacts_by_skill']}")

print(f"\n   Full memory stats: {memory.stats()}")
print("\n✅ Week 12 Institutional Memory test complete.")
