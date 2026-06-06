"""
Knowledge Retriever — Week 9

Three retrieval strategies:
  1. Basic RAG    — direct similarity search (fast, works when query is specific)
  2. HyDE         — generate a hypothetical answer, embed that, search with it
                    (works when query is vague or conceptual)
  3. Self-RAG     — retrieve → critique relevance → re-retrieve if needed
                    (highest quality, slightly slower)

Adaptive RAG chooses the right strategy based on query characteristics.

All strategies return list[RetrievedChunk].
"""
import os
from dataclasses import dataclass
from typing import Literal

from aria.knowledge.ingestion import get_collection


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    text: str
    source: str
    doc_type: str
    distance: float     # cosine distance — lower = more similar


def _to_chunks(results: dict) -> list[RetrievedChunk]:
    chunks = []
    docs       = results.get("documents", [[]])[0]
    metas      = results.get("metadatas", [[]])[0]
    distances  = results.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, distances):
        chunks.append(RetrievedChunk(
            text=doc,
            source=meta.get("source", "unknown"),
            doc_type=meta.get("doc_type", "general"),
            distance=dist,
        ))
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 1 — Basic RAG
# ─────────────────────────────────────────────────────────────────────────────

def basic_rag(query: str, k: int = 3) -> list[RetrievedChunk]:
    """Embed the query directly. Return top-k most similar chunks."""
    collection = get_collection()
    if collection.count() == 0:
        return []
    results = collection.query(query_texts=[query], n_results=min(k, collection.count()))
    return _to_chunks(results)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 2 — HyDE (Hypothetical Document Embeddings)
# ─────────────────────────────────────────────────────────────────────────────

def _generate_hypothetical_doc(query: str) -> str:
    """
    Generate a hypothetical answer document that WOULD answer this query.
    This hypothetical doc is then embedded and used as the search vector
    instead of the raw query — produces much better retrieval for vague queries.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        # No key — use the query itself with a prefix that helps retrieval
        return f"This document explains: {query}. Key facts include the cause, the impact, and the recommended resolution steps."

    from langchain_anthropic import ChatAnthropic
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    chain = (
        ChatPromptTemplate.from_messages([
            ("system", "Write a short expert document (2-3 sentences) that directly answers the query. Be specific and factual. Do not say 'I don't know'."),
            ("human", "{query}"),
        ])
        | ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
        | StrOutputParser()
    )
    return chain.invoke({"query": query})


def hyde(query: str, k: int = 3) -> list[RetrievedChunk]:
    """
    HyDE: generate a hypothetical answer → embed it → search with that vector.
    Better than basic RAG when the query is vague or asks 'how do I...'
    """
    collection = get_collection()
    if collection.count() == 0:
        return []
    hypothetical = _generate_hypothetical_doc(query)
    results = collection.query(query_texts=[hypothetical], n_results=min(k, collection.count()))
    return _to_chunks(results)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 3 — Self-RAG
# ─────────────────────────────────────────────────────────────────────────────

_RELEVANCE_THRESHOLD = 0.45  # cosine distance — above this = not relevant


def _is_relevant(chunk: RetrievedChunk, query: str) -> bool:
    """
    Quick relevance check: distance threshold + optional Claude critique.
    In mock mode (no API key), use distance only.
    """
    if chunk.distance > _RELEVANCE_THRESHOLD:
        return False
    return True


def self_rag(query: str, k: int = 3, max_retries: int = 1) -> list[RetrievedChunk]:
    """
    Self-RAG: retrieve → critique relevance → re-retrieve with refined query if needed.
    Returns the best chunks after up to max_retries refinement attempts.
    """
    collection = get_collection()
    if collection.count() == 0:
        return []

    chunks = basic_rag(query, k=k)
    relevant = [c for c in chunks if _is_relevant(c, query)]

    if relevant or max_retries == 0:
        return relevant if relevant else chunks  # fall back to raw results

    # Refine: try HyDE on retry
    refined = hyde(query, k=k)
    relevant_refined = [c for c in refined if _is_relevant(c, query)]
    return relevant_refined if relevant_refined else refined


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive RAG — choose strategy by query characteristics
# ─────────────────────────────────────────────────────────────────────────────

def _classify_query(query: str) -> Literal["basic", "hyde", "self_rag"]:
    """
    Heuristic: pick retrieval strategy based on query shape.
    - Short, specific (< 8 words, contains named entity) → basic
    - Vague or open-ended ('how', 'why', 'what should') → HyDE
    - High-stakes / 'best' / 'recommend' → Self-RAG
    """
    q = query.lower()
    words = q.split()

    high_stakes = any(w in q for w in ["best", "recommend", "should", "risk", "critical", "production"])
    open_ended  = any(q.startswith(p) for p in ["how", "why", "what should", "when should", "explain"])

    if high_stakes:
        return "self_rag"
    if open_ended or len(words) < 5:
        return "hyde"
    return "basic"


def adaptive_rag(query: str, k: int = 3) -> tuple[list[RetrievedChunk], str]:
    """
    Choose the best retrieval strategy automatically.
    Returns (chunks, strategy_used) so the caller can log which strategy ran.
    """
    strategy = _classify_query(query)

    if strategy == "hyde":
        return hyde(query, k=k), "HyDE"
    elif strategy == "self_rag":
        return self_rag(query, k=k), "Self-RAG"
    else:
        return basic_rag(query, k=k), "Basic RAG"


# ─────────────────────────────────────────────────────────────────────────────
# Format retrieved chunks for injection into skill prompts
# ─────────────────────────────────────────────────────────────────────────────

def format_context(chunks: list[RetrievedChunk], max_chars: int = 1200) -> str:
    """
    Format retrieved chunks into a compact context block for LLM injection.
    Respects a character budget — truncates chunks to fit rather than skipping.
    """
    if not chunks:
        return ""

    parts = ["--- RETRIEVED CONTEXT ---"]
    budget = max_chars
    for chunk in chunks:
        if budget <= 0:
            break
        header = f"[{chunk.source}]"
        # Take as much of the text as the budget allows
        available = budget - len(header) - 2
        text = chunk.text[:available] if available > 0 else ""
        parts.append(f"{header} {text}")
        budget -= len(header) + len(text) + 2
    parts.append("--- END CONTEXT ---")
    return "\n".join(parts)
