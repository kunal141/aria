"""
Memory Manager — Week 11 + 12

The public interface for all memory operations.
Skills and nodes call this — they never touch the store directly.

MemGPT/Letta three-tier pattern:
  Hot  → ARIAState (the context window — not managed here)
  Warm → MemoryManager.remember() / recall() / update_outcome()
  Cold → Chroma semantic search (aria.knowledge.retriever)

Promotion path:
  - New memory → Warm (write to JSON store)
  - Old session memory → Cold (ingest into Chroma at session end)
  - User/outcome memory → stays Warm indefinitely (small, high-value)
"""
from datetime import datetime, timezone
from typing import Optional

from aria.memory import store
from aria.memory.models import (
    SessionMemory, TaskMemory, UserMemory, OutcomeMemory,
    DecisionMemory, ArtifactMemory, MemoryRecord
)


class MemoryManager:

    # ── Write ──────────────────────────────────────────────────────────────

    def remember_session_event(
        self,
        event: str,
        task_id: Optional[str] = None,
        importance: str = "medium",
    ) -> SessionMemory:
        """Log a session event — what just happened in this interaction."""
        mem = SessionMemory(
            content=event,
            event=event,
            task_id=task_id,
            importance=importance,
        )
        store.write(mem)
        return mem

    def remember_task(
        self,
        task_id: str,
        skill_name: str,
        summary: str,
        verdict: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> TaskMemory:
        """Record what a task produced."""
        mem = TaskMemory(
            content=summary,
            task_id=task_id,
            skill_name=skill_name,
            verdict=verdict,
            tags=tags or [],
            importance="high" if verdict in ("request_changes", "needs_discussion") else "medium",
        )
        store.write(mem)
        return mem

    def learn_user_preference(
        self,
        preference: str,
        category: str = "preference",
        confidence: float = 0.5,
        tags: Optional[list[str]] = None,
    ) -> UserMemory:
        """
        Record something ARIA learned about the user.
        Call this when the user corrects ARIA, repeats a pattern,
        or explicitly states a preference.
        """
        mem = UserMemory(
            content=preference,
            category=category,
            confidence=confidence,
            tags=tags or [],
            importance="high",
        )
        store.write(mem)
        return mem

    def record_outcome(
        self,
        task_id: str,
        skill_name: str,
        approved: bool,
        correction: Optional[str] = None,
    ) -> OutcomeMemory:
        """
        Record whether ARIA's output was approved or rejected.
        This is a DPO training pair seed for Week 29 fine-tuning.
        """
        content = (
            f"{'Approved' if approved else 'Rejected'}: {skill_name} on task {task_id}"
            + (f" — Correction: {correction}" if correction else "")
        )
        mem = OutcomeMemory(
            content=content,
            task_id=task_id,
            skill_name=skill_name,
            approved=approved,
            correction=correction,
            importance="high",
        )
        store.write(mem)
        return mem

    # ── Read ───────────────────────────────────────────────────────────────

    def recall_session(self, limit: int = 5) -> list[dict]:
        """Most recent session events."""
        return store.read_by_type("session", limit=limit)

    def recall_task(self, task_id: str) -> list[dict]:
        """Everything ARIA remembers about a specific task."""
        return store.read_by_type("task", task_id=task_id)

    def recall_user_preferences(self, limit: int = 10) -> list[dict]:
        """What ARIA knows about the user's preferences and patterns."""
        return store.read_by_type("user", limit=limit)

    def recall_recent_outcomes(self, limit: int = 10) -> list[dict]:
        """Recent approval/rejection decisions — training signal."""
        return store.read_by_type("outcome", limit=limit)

    def recall_for_skill(self, skill_name: str, limit: int = 3) -> list[dict]:
        """
        Relevant user preferences and past outcomes for a given skill.
        Inject this into the skill's context before calling the LLM.
        """
        prefs    = store.read_by_type("user", limit=20)
        outcomes = store.read_by_type("outcome", limit=20)

        skill_prefs = [p for p in prefs
                       if skill_name in p.get("tags", []) or not p.get("tags")]
        skill_outcomes = [o for o in outcomes
                          if o.get("skill_name") == skill_name]

        return (skill_prefs + skill_outcomes)[:limit]

    # ── Week 12 — Institutional memory ────────────────────────────────────

    def record_decision(
        self,
        decision: str,
        rationale: str,
        alternatives: Optional[list[str]] = None,
        outcome: Optional[str] = None,
        week: Optional[int] = None,
        tags: Optional[list[str]] = None,
    ) -> DecisionMemory:
        """
        Log an architectural or technical decision permanently.
        Never cleared. ARIA draws on these when making future decisions.
        """
        content = f"Decision: {decision} | Rationale: {rationale}"
        mem = DecisionMemory(
            content=content,
            decision=decision,
            rationale=rationale,
            alternatives=alternatives or [],
            outcome=outcome,
            week=week,
            tags=tags or [],
            importance="high",
        )
        store.write(mem)
        return mem

    def store_artifact(
        self,
        task_id: str,
        skill_name: str,
        artifact_type: str,
        artifact_content: str,
        tags: Optional[list[str]] = None,
    ) -> ArtifactMemory:
        """
        Store a skill output artifact permanently linked to task_id.
        Makes every ARIA output retrievable by task — foundation for Work Ledger.
        """
        summary = f"{skill_name} artifact for task {task_id[:8]} — type: {artifact_type}"
        mem = ArtifactMemory(
            content=summary,
            task_id=task_id,
            skill_name=skill_name,
            artifact_type=artifact_type,
            artifact_content=artifact_content,
            tags=tags or [],
            importance="medium",
        )
        store.write(mem)
        return mem

    def get_artifact(self, task_id: str) -> Optional[dict]:
        """Retrieve the artifact produced for a specific task_id."""
        results = store.query_artifacts(task_id=task_id, limit=1)
        return results[0] if results else None

    def query_outcomes(
        self,
        approved: Optional[bool] = None,
        skill_name: Optional[str] = None,
    ) -> list[dict]:
        """
        Filter outcomes by approval status and skill.
        approved=True  → positive fine-tuning examples
        approved=False → DPO negative examples with corrections
        """
        return store.query_outcomes(approved=approved, skill_name=skill_name)

    def recall_decisions(self, week: Optional[int] = None) -> list[dict]:
        """Retrieve architectural decisions, optionally filtered by week."""
        return store.query_decisions(week=week)

    def search_memory(self, query: str, k: int = 3) -> list:
        """
        Semantic search across cold Chroma store — finds relevant past memories
        that were promoted from warm to cold at session end.
        """
        from aria.knowledge.retriever import adaptive_rag
        chunks, strategy = adaptive_rag(query, k=k)
        return chunks

    def roi_snapshot(self) -> dict:
        """Work Ledger ROI snapshot — seed of the Week 29 dashboard."""
        return store.roi_summary()

    # ── Stats ──────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        counts = store.count_by_type()
        return {
            "total": sum(counts.values()),
            "by_type": counts,
        }

    # ── Session lifecycle ──────────────────────────────────────────────────

    def end_session(self, promote_to_cold: bool = False) -> int:
        """
        Clear session memories at the end of a conversation.
        If promote_to_cold=True, ingest them into Chroma first (Week 12+).
        Returns count of records cleared.
        """
        if promote_to_cold:
            sessions = store.read_by_type("session", limit=100)
            if sessions:
                from aria.knowledge.ingestion import ingest_text
                combined = "\n".join(
                    f"[{s['created_at'][:10]}] {s['content']}"
                    for s in sessions
                )
                ingest_text(combined, source="session_archive", doc_type="session")
        return store.clear_session_memories()

    # ── Context injection ──────────────────────────────────────────────────

    def format_for_prompt(self, memories: list[dict], max_chars: int = 600) -> str:
        """
        Format memories into a compact block for LLM prompt injection.
        Keeps within a character budget — no context bloat.
        """
        if not memories:
            return ""
        parts = ["--- USER CONTEXT ---"]
        budget = max_chars
        for m in memories:
            line = f"[{m.get('memory_type', '?')}] {m.get('content', '')}"
            if budget - len(line) < 0:
                break
            parts.append(line)
            budget -= len(line)
        parts.append("--- END CONTEXT ---")
        return "\n".join(parts)


# Singleton — import and use directly
memory = MemoryManager()
