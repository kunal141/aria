"""
RAPTOR — Recursive Abstractive Processing for Tree-Organised Retrieval
Week 27

Hierarchical document chunking and summarisation:
  Level 0  — raw leaf chunks (≤ chunk_size tokens by word estimate)
  Level 1  — group summaries (one summary per group of ≤ group_size leaves)
  Level 2  — root summary (one summary over all Level-1 summaries)

V1 uses extractive summarisation (no LLM required) so all tests are deterministic.
LLM-backed abstractive summarisation is a V2 path, hooked via the `summarizer`
callable parameter.

Primary integration: Evolution Intelligence — long ML papers and work-ledger
export documents are indexed via RAPTOR so cross-document queries can operate
at multiple granularity levels simultaneously.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class RaptorChunk:
    chunk_id: str
    level:    int         # 0 = leaf, 1 = group summary, 2 = root summary
    text:     str
    parent:   Optional[str] = None   # chunk_id of the parent summary
    children: list[str] = field(default_factory=list)  # chunk_ids of children


@dataclass
class RaptorTree:
    doc_id:    str
    chunks:    dict[str, RaptorChunk] = field(default_factory=dict)
    root_id:   Optional[str] = None

    def leaves(self) -> list[RaptorChunk]:
        return [c for c in self.chunks.values() if c.level == 0]

    def level(self, lvl: int) -> list[RaptorChunk]:
        return [c for c in self.chunks.values() if c.level == lvl]

    def get_path_to_root(self, chunk_id: str) -> list[RaptorChunk]:
        """Return the chunk and all its ancestors up to root."""
        path: list[RaptorChunk] = []
        cid: Optional[str] = chunk_id
        while cid and cid in self.chunks:
            chunk = self.chunks[cid]
            path.append(chunk)
            cid = chunk.parent
        return path


# ── Builder ────────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _extractive_summary(texts: list[str], max_sentences: int = 3) -> str:
    """
    Simple extractive summarisation: pick the first sentence of each input text,
    up to max_sentences total. Deterministic — no LLM needed.
    """
    import re
    sentences: list[str] = []
    for text in texts:
        # Split on period/exclamation/question mark followed by whitespace or end
        parts = re.split(r'(?<=[.!?])\s+', text.strip())
        if parts:
            sentences.append(parts[0].strip())
        if len(sentences) >= max_sentences:
            break
    return " ".join(sentences) if sentences else " ".join(t[:120] for t in texts[:2])


class RaptorBuilder:
    """
    Builds a RAPTOR tree from a single document string.

    Parameters
    ----------
    chunk_size  : target word count per leaf chunk
    group_size  : number of leaves per Level-1 group
    summarizer  : callable(list[str]) → str.  Defaults to extractive.
    """

    def __init__(
        self,
        chunk_size:  int = 150,
        group_size:  int = 5,
        summarizer:  Optional[Callable[[list[str]], str]] = None,
    ) -> None:
        self._chunk_size = max(50, chunk_size)
        self._group_size = max(2, group_size)
        self._summarize  = summarizer or (lambda texts: _extractive_summary(texts))

    def build(self, doc_id: str, document: str) -> RaptorTree:
        tree = RaptorTree(doc_id=doc_id)

        # Level 0 — leaf chunks
        leaf_chunks = self._split_leaves(document)
        for idx, text in enumerate(leaf_chunks):
            cid = f"{doc_id}:L0:{idx}"
            tree.chunks[cid] = RaptorChunk(chunk_id=cid, level=0, text=text)

        leaf_ids = [f"{doc_id}:L0:{i}" for i in range(len(leaf_chunks))]

        # Level 1 — group summaries
        groups = _group(leaf_ids, self._group_size)
        l1_ids: list[str] = []
        for g_idx, group in enumerate(groups):
            texts = [tree.chunks[cid].text for cid in group]
            summary = self._summarize(texts)
            cid = f"{doc_id}:L1:{g_idx}"
            chunk = RaptorChunk(chunk_id=cid, level=1, text=summary, children=list(group))
            tree.chunks[cid] = chunk
            l1_ids.append(cid)
            for child_cid in group:
                tree.chunks[child_cid].parent = cid

        # Level 2 — root summary (only when more than one L1 chunk)
        if len(l1_ids) > 1:
            texts = [tree.chunks[cid].text for cid in l1_ids]
            root_summary = self._summarize(texts)
            root_cid = f"{doc_id}:L2:root"
            tree.chunks[root_cid] = RaptorChunk(
                chunk_id=root_cid,
                level=2,
                text=root_summary,
                children=list(l1_ids),
            )
            for l1_cid in l1_ids:
                tree.chunks[l1_cid].parent = root_cid
            tree.root_id = root_cid
        elif l1_ids:
            tree.root_id = l1_ids[0]

        return tree

    def _split_leaves(self, document: str) -> list[str]:
        """Split document into word-count-bounded chunks at paragraph boundaries.

        Paragraphs that individually exceed chunk_size are further split at word
        boundaries so no leaf chunk exceeds the configured limit.
        """
        paragraphs = [p.strip() for p in document.split("\n\n") if p.strip()]
        # Sub-split any paragraph that exceeds chunk_size
        sub_paras: list[str] = []
        for para in paragraphs:
            sub_paras.extend(self._split_words(para))

        chunks: list[str] = []
        current: list[str] = []
        current_wc = 0

        for para in sub_paras:
            para_wc = _word_count(para)
            if current and current_wc + para_wc > self._chunk_size:
                chunks.append("\n\n".join(current))
                current = [para]
                current_wc = para_wc
            else:
                current.append(para)
                current_wc += para_wc

        if current:
            chunks.append("\n\n".join(current))

        return chunks or [document]

    def _split_words(self, text: str) -> list[str]:
        """Split a single text into word-count-bounded segments."""
        words = text.split()
        if len(words) <= self._chunk_size:
            return [text]
        segments: list[str] = []
        for i in range(0, len(words), self._chunk_size):
            segments.append(" ".join(words[i : i + self._chunk_size]))
        return segments


# ── Retrieval helper ───────────────────────────────────────────────────────────

def query_tree(tree: RaptorTree, query: str, top_k: int = 5) -> list[RaptorChunk]:
    """
    Simple keyword overlap retrieval across all levels.
    Returns top_k chunks ranked by keyword overlap with query.
    """
    query_words = set(query.lower().split())
    scored: list[tuple[float, RaptorChunk]] = []
    for chunk in tree.chunks.values():
        chunk_words = set(chunk.text.lower().split())
        overlap = len(query_words & chunk_words)
        if overlap > 0:
            # Prefer higher-level summaries (they aggregate more information)
            score = overlap + chunk.level * 0.5
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


# ── Utilities ──────────────────────────────────────────────────────────────────

def _group(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
