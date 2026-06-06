"""
Memory Store — Week 11 + 12

File-backed JSON store for warm memory.
Reads on startup, writes on every update. Zero external dependencies.

Warm tier: fast, in-process, survives across task runs within a session.
Migration path: swap this file-backed store for Postgres at Week 12
when institutional + outcome memory needs SQL filters and ACID guarantees.

File: apps/backend/memory_store.json
"""
import json
from pathlib import Path
from typing import Optional

from aria.memory.models import MemoryRecord, MemoryType

import os as _os
_STORE_FILE = Path(_os.getenv("ARIA_MEMORY_STORE_PATH") or str(Path(__file__).parent.parent.parent / "memory_store.json"))


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    if not _STORE_FILE.exists():
        return []
    try:
        return json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save(records: list[dict]) -> None:
    _STORE_FILE.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def write(record: MemoryRecord) -> None:
    """Append or update a memory record."""
    records = _load()
    # Replace if same memory_id exists
    updated = False
    for i, r in enumerate(records):
        if r.get("memory_id") == record.memory_id:
            records[i] = record.model_dump()
            updated = True
            break
    if not updated:
        records.append(record.model_dump())
    _save(records)


def read_by_type(
    memory_type: MemoryType,
    limit: int = 10,
    task_id: Optional[str] = None,
) -> list[dict]:
    """Return the most recent N records of a given type."""
    records = _load()
    filtered = [
        r for r in records
        if r.get("memory_type") == memory_type
        and (task_id is None or r.get("task_id") == task_id)
    ]
    # Most recent first (created_at is ISO 8601 so lexicographic sort works)
    filtered.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return filtered[:limit]


def read_by_id(memory_id: str) -> Optional[dict]:
    for r in _load():
        if r.get("memory_id") == memory_id:
            return r
    return None


def delete(memory_id: str) -> bool:
    records = _load()
    before = len(records)
    records = [r for r in records if r.get("memory_id") != memory_id]
    _save(records)
    return len(records) < before


def count_by_type() -> dict[str, int]:
    records = _load()
    counts: dict[str, int] = {}
    for r in records:
        t = r.get("memory_type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


def clear_session_memories() -> int:
    """Remove all session-type memories (called at session end)."""
    records = _load()
    before = len(records)
    records = [r for r in records if r.get("memory_type") != "session"]
    _save(records)
    return before - len(records)


# ─────────────────────────────────────────────────────────────────────────────
# Week 12 — Institutional query methods
# ─────────────────────────────────────────────────────────────────────────────

def query_outcomes(
    approved: Optional[bool] = None,
    skill_name: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    Filter outcome memories.
    approved=True  → only approved outputs  (positive fine-tuning examples)
    approved=False → only rejected outputs  (DPO negative examples with corrections)
    approved=None  → all outcomes
    """
    records = _load()
    results = []
    for r in records:
        if r.get("memory_type") != "outcome":
            continue
        if approved is not None and r.get("approved") != approved:
            continue
        if skill_name and r.get("skill_name") != skill_name:
            continue
        results.append(r)
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results[:limit]


def query_artifacts(
    task_id: Optional[str] = None,
    artifact_type: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Retrieve stored skill artifacts, optionally filtered by task or type."""
    records = _load()
    results = [
        r for r in records
        if r.get("memory_type") == "artifact"
        and (task_id is None or r.get("task_id") == task_id)
        and (artifact_type is None or r.get("artifact_type") == artifact_type)
    ]
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results[:limit]


def query_decisions(week: Optional[int] = None, limit: int = 50) -> list[dict]:
    """Return architectural decision records, optionally filtered by week."""
    records = _load()
    results = [
        r for r in records
        if r.get("memory_type") == "decision"
        and (week is None or r.get("week") == week)
    ]
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results[:limit]


def roi_summary() -> dict:
    """
    Work Ledger ROI snapshot — counts by type and skill.
    Seed of the Week 29 ROI dashboard.
    """
    records = _load()
    artifacts = [r for r in records if r.get("memory_type") == "artifact"]
    outcomes  = [r for r in records if r.get("memory_type") == "outcome"]
    approved  = [o for o in outcomes if o.get("approved") is True]
    rejected  = [o for o in outcomes if o.get("approved") is False]

    by_skill: dict[str, int] = {}
    for a in artifacts:
        s = a.get("skill_name", "unknown")
        by_skill[s] = by_skill.get(s, 0) + 1

    return {
        "total_artifacts": len(artifacts),
        "total_outcomes": len(outcomes),
        "approved": len(approved),
        "rejected": len(rejected),
        "approval_rate": round(len(approved) / len(outcomes), 2) if outcomes else 0.0,
        "artifacts_by_skill": by_skill,
    }
