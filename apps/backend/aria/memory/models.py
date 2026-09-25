"""
Memory Models — Week 11 + 12

Typed Pydantic schemas for every memory type ARIA holds.

The three memory tiers (MemGPT/Letta pattern):
  Hot  (Tier 1) — ARIAState in the context window right now
  Warm (Tier 2) — memory_store.json, fast JSON lookup, loaded at startup
  Cold (Tier 3) — Chroma vector store, semantic search needed

This file defines the Warm tier schemas.
Each memory record is persisted to memory_store.json by MemoryManager.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


MemoryType = Literal[
    "session",      # what happened in this conversation window
    "task",         # what a specific task produced (linked to task_id)
    "user",         # Kunal's preferences, patterns, corrections
    "outcome",      # was a skill output approved/rejected (feeds fine-tuning)
    "decision",     # Week 12: architectural/technical decision + rationale
    "artifact",     # Week 12: skill output artifact linked to task_id
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# Base record — every memory type shares these fields
# ─────────────────────────────────────────────────────────────────────────────

class MemoryRecord(BaseModel):
    memory_id: str          = Field(default_factory=_new_id)
    memory_type: MemoryType
    content: str            # the actual memory — plain text summary
    created_at: str         = Field(default_factory=_now)
    updated_at: str         = Field(default_factory=_now)
    task_id: Optional[str]  = None   # links memory to a specific task
    tags: list[str]         = Field(default_factory=list)
    importance: Literal["high", "medium", "low"] = "medium"


# ─────────────────────────────────────────────────────────────────────────────
# Specialised memory types
# ─────────────────────────────────────────────────────────────────────────────

class SessionMemory(MemoryRecord):
    """
    What happened in this conversation session.
    Written during a session, cleared (or summarised → cold) at session end.
    """
    memory_type: MemoryType = "session"
    session_id: str = Field(default_factory=_new_id)
    event: str = ""          # e.g. "user asked about CTR drop", "ARIA ran kpi_skill"


class TaskMemory(MemoryRecord):
    """
    What a specific task produced — linked permanently to its task_id.
    Examples: "PR review for recommendation engine — verdict: needs_discussion"
    """
    memory_type: MemoryType = "task"
    skill_name: Optional[str] = None
    verdict: Optional[str]    = None   # for PR review: approve/request_changes/needs_discussion
    outcome: Optional[str]    = None   # approved / rejected / pending (from user feedback)


class UserMemory(MemoryRecord):
    """
    What ARIA has learned about the user's preferences, patterns, corrections.
    This is the Human Teaching Layer (Pillar 17) seed.
    Persists indefinitely — never cleared, only updated.

    Examples:
    - "Kunal prefers root causes ranked by likelihood, not alphabetically"
    - "Kunal always asks for a rollback plan in PR reviews"
    - "The platform team uses feature flags for all ranking changes"
    """
    memory_type: MemoryType = "user"
    category: Literal["preference", "correction", "context", "pattern"] = "preference"
    confidence: float = 0.5   # 0.0–1.0 — increases as pattern repeats


class OutcomeMemory(MemoryRecord):
    """
    Was ARIA's output approved or rejected?
    This is the training signal for Week 29 fine-tuning.
    Every approve/reject pair = a DPO training example.
    """
    memory_type: MemoryType = "outcome"
    skill_name: str = ""
    approved: Optional[bool] = None    # True=approved, False=rejected, None=pending
    correction: Optional[str] = None   # what the user said when rejecting


# ─────────────────────────────────────────────────────────────────────────────
# Week 12 — Institutional memory types
# ─────────────────────────────────────────────────────────────────────────────

class DecisionMemory(MemoryRecord):
    """
    An architectural or technical decision made during the project.
    Never cleared. Builds the institutional knowledge base ARIA draws on
    when making future decisions.

    Examples:
    - "Chose Chroma over FAISS for Week 9 RAG: zero config, LangChain-native"
    - "Chose file-backed JSON over SQLite for Week 11 memory: zero deps"
    - "Deferred pgvector to Week 12: need ACID + SQL filters for outcome queries"
    """
    memory_type: MemoryType = "decision"
    decision: str = ""           # what was decided (one sentence)
    alternatives: list[str] = Field(default_factory=list)   # what was considered
    rationale: str = ""          # why this choice
    outcome: Optional[str] = None  # result after implementation (filled in retrospect)
    week: Optional[int] = None


class ArtifactMemory(MemoryRecord):
    """
    A skill output artifact stored permanently and linked to its task_id.
    Makes every ARIA output retrievable: "show me the PR review for task-abc".

    Also the foundation for the Work Ledger ROI dashboard (Week 29):
    count artifacts by type, by week, by approval status.
    """
    memory_type: MemoryType = "artifact"
    skill_name: str = ""
    artifact_type: Literal["pr_review", "kpi_brief", "test_cases", "ci_cd_summary", "jira_ticket", "general"] = "general"
    artifact_content: str = ""   # the full formatted artifact text
    approved: Optional[bool] = None
