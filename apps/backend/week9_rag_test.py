"""
Week 9 — RAG Test Script (standalone, not part of main graph)

Demonstrates:
  1. Document ingestion (chunk + embed + store in Chroma)
  2. Basic RAG retrieval
  3. HyDE retrieval
  4. Self-RAG retrieval
  5. Adaptive RAG (auto-selects strategy)

Run: uv run python week9_rag_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path

from aria.knowledge.ingestion import ingest_file, collection_size
from aria.knowledge.retriever import (
    basic_rag, hyde, self_rag, adaptive_rag, format_context
)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Ingest seed documents
# ─────────────────────────────────────────────────────────────────────────────

SEED_DIR = Path(__file__).parent / "aria" / "knowledge" / "seed_docs"

print("=" * 60)
print("ARIA — Week 9: Knowledge Retrieval Layer")
print("=" * 60)
print("\n📥 Ingesting seed documents...")

n1 = ingest_file(str(SEED_DIR / "kpi_runbook.md"),    doc_type="runbook")
n2 = ingest_file(str(SEED_DIR / "pr_guidelines.md"),  doc_type="guidelines")

print(f"   kpi_runbook.md    → {n1} chunks")
print(f"   pr_guidelines.md  → {n2} chunks")
print(f"   Total in Chroma   : {collection_size()} chunks")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Test queries
# ─────────────────────────────────────────────────────────────────────────────

QUERIES = [
    ("Our CTR dropped 18% this week — where do I start?",        "kpi"),
    ("What should I check when notification open rate falls?",   "kpi"),
    ("How do I review a recommendation engine PR safely?",       "pr_review"),
    ("What is the deployment risk tier for schema migrations?",  "pr_review"),
]

print("\n" + "─" * 60)
print("RETRIEVAL TESTS")
print("─" * 60)

for query, expected_type in QUERIES:
    print(f"\n🔍 Query: {query[:65]}")
    print(f"   Expected type: {expected_type}")

    # Adaptive RAG — auto-selects strategy
    chunks, strategy = adaptive_rag(query, k=2)
    print(f"   Strategy chosen : {strategy}")
    print(f"   Chunks retrieved: {len(chunks)}")

    for i, chunk in enumerate(chunks):
        print(f"\n   [{i+1}] source={chunk.source}  distance={chunk.distance:.3f}")
        print(f"        {chunk.text[:180]}...")

    # Show formatted context (what would be injected into a skill prompt)
    ctx = format_context(chunks)
    print(f"\n   Formatted context ({len(ctx)} chars):")
    print("   " + "\n   ".join(ctx.split("\n")[:4]))  # first 4 lines


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Strategy comparison on one query
# ─────────────────────────────────────────────────────────────────────────────

COMPARE_QUERY = "Why would our homepage CTR drop after a model deployment?"

print(f"\n{'─' * 60}")
print(f"STRATEGY COMPARISON on: '{COMPARE_QUERY[:55]}'")
print("─" * 60)

for label, fn in [("Basic RAG", basic_rag), ("HyDE", hyde), ("Self-RAG", self_rag)]:
    chunks = fn(COMPARE_QUERY, k=2)
    print(f"\n{label}:")
    if chunks:
        print(f"  top hit: [{chunks[0].source}] dist={chunks[0].distance:.3f}")
        print(f"  {chunks[0].text[:160]}...")
    else:
        print("  no relevant chunks found")

print("\n✅ Week 9 RAG test complete.")
