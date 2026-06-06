"""
Week 10 — Code Intelligence Test (standalone, not part of main graph)

ARIA reads her own codebase. This is the start of self-dogfooding.

Demonstrates:
  1. AST parsing — extract functions, classes, imports from a Python file
  2. Dependency graph — which aria modules depend on which
  3. Code ingestion — index ARIA's own source into Chroma
  4. Code Q&A — answer questions about the codebase using retrieval

Run: uv run python week10_code_intel_test.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path

from aria.knowledge.code_intel import (
    parse_file, build_dep_graph, ingest_repo, print_dep_graph
)
from aria.knowledge.ingestion import collection_size
from aria.knowledge.retriever import adaptive_rag, format_context


ARIA_SRC = Path(__file__).parent / "aria"


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Parse a single file (AST demo)
# ─────────────────────────────────────────────────────────────────────────────

print("=" * 60)
print("ARIA — Week 10: Code Intelligence Layer")
print("=" * 60)

print("\n📄 Parsing aria/skills/kpi_skill.py...")
info = parse_file(str(ARIA_SRC / "skills" / "kpi_skill.py"))

print(f"   Module   : {info.module_name.split(chr(92))[-1]}")
print(f"   Imports  : {', '.join(sorted(info.imports)[:5])}{'...' if len(info.imports) > 5 else ''}")
print(f"   Functions: {', '.join(f.name for f in info.functions)}")
print(f"   Classes  : {', '.join(c.name for c in info.classes)}")

print("\n   Function details:")
for fn in info.functions:
    print(f"   • {fn.name}({', '.join(fn.args)})  line {fn.line_start}–{fn.line_end}")
    if fn.docstring:
        print(f"     doc: {fn.docstring[:80]}")

print("\n   Class details:")
for cls in info.classes:
    print(f"   • {cls.name}  methods: {cls.methods}  line {cls.line_start}–{cls.line_end}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Dependency graph
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("🗺  Building dependency graph for aria/ ...")
graph = build_dep_graph(str(ARIA_SRC))
print_dep_graph(graph)


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Ingest ARIA's own source into Chroma
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'─' * 60}")
print("📥 Ingesting ARIA source code into Chroma...")
counts = ingest_repo(str(ARIA_SRC))
print(f"   Files parsed   : {counts['files']}")
print(f"   Functions added: {counts['functions']}")
print(f"   Classes added  : {counts['classes']}")
print(f"   Total in Chroma: {collection_size()} chunks (docs + code)")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Code Q&A (ARIA answers questions about her own codebase)
# ─────────────────────────────────────────────────────────────────────────────

CODE_QUERIES = [
    "where is the kpi skill run function defined?",
    "what does the respond node do?",
    "how does the skill registry register a skill?",
    "where is ARIAState defined and what fields does it have?",
]

print(f"\n{'─' * 60}")
print("🤖 Code Q&A — ARIA reads her own codebase")
print("─" * 60)

for query in CODE_QUERIES:
    chunks, strategy = adaptive_rag(query, k=2)

    # Filter to code chunks only
    code_chunks = [c for c in chunks if c.doc_type == "code"]
    if not code_chunks:
        code_chunks = chunks  # fall back if no code chunks matched

    print(f"\n❓ {query}")
    print(f"   Strategy: {strategy}  |  Hits: {len(code_chunks)}")
    for i, chunk in enumerate(code_chunks[:2]):
        source = chunk.source
        dist   = chunk.distance
        # Show first 3 lines of the chunk text
        preview = "\n      ".join(chunk.text.split("\n")[:3])
        print(f"   [{i+1}] {source}  dist={dist:.3f}")
        print(f"      {preview}")

print("\n✅ Week 10 Code Intelligence test complete.")
print("   ARIA has now read her own codebase. Self-dogfooding begins.")
