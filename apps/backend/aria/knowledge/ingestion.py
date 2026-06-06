"""
Knowledge Ingestion — Week 9

Chunks, embeds, and stores documents in Chroma.
Uses local sentence-transformers model — no API key required.

Usage:
    from aria.knowledge.ingestion import ingest_document, ingest_text

Collection layout:
    "aria_knowledge" — all ingested docs live here
    metadata keys: source, doc_type, week_added
"""
import hashlib
from typing import Optional
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions


# ─────────────────────────────────────────────────────────────────────────────
# Chroma client + collection (in-memory for Week 9; pgvector at Week 11)
# ─────────────────────────────────────────────────────────────────────────────

_client = chromadb.Client()  # in-memory, resets on process restart

_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"  # 80MB, fast, good for semantic search
)

_collection = _client.get_or_create_collection(
    name="aria_knowledge",
    embedding_function=_ef,
    metadata={"hnsw:space": "cosine"},
)


# ─────────────────────────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 80) -> list[str]:
    """Split text into overlapping chunks by word boundary."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i: i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks


def _doc_id(source: str, chunk_index: int) -> str:
    key = f"{source}::{chunk_index}"
    return hashlib.md5(key.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def ingest_text(
    text: str,
    source: str,
    doc_type: str = "general",
    week_added: int = 9,
) -> int:
    """
    Chunk, embed, and store plain text. Returns number of chunks stored.
    source: human-readable identifier (e.g. 'kpi_runbook', 'pr_guidelines')
    """
    chunks = _chunk_text(text)
    if not chunks:
        return 0

    ids        = [_doc_id(source, i) for i in range(len(chunks))]
    metadatas  = [{"source": source, "doc_type": doc_type, "week_added": week_added, "chunk_index": i}
                  for i in range(len(chunks))]

    _collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)
    return len(chunks)


def ingest_file(path: str, doc_type: str = "general", week_added: int = 9) -> int:
    """Read a .txt or .md file and ingest it."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    text = p.read_text(encoding="utf-8")
    return ingest_text(text, source=p.stem, doc_type=doc_type, week_added=week_added)


def collection_size() -> int:
    return _collection.count()


def get_collection():
    """Expose collection for retriever."""
    return _collection
