"""
Deterministic domain-knowledge extraction (Week 32 §4).

Turns a casual statement into a structured memory-proposal payload — without an
LLM, so the lifecycle is deterministic and testable offline. The canonical
``story_events.event_type`` mapping is the worked example the spec requires.

This is intentionally conservative: it extracts only when it confidently
recognises a reusable mapping/definition. Anything else returns ``None`` (the
orchestrator then treats the turn as converse/clarify, never auto-persisting).
"""
from __future__ import annotations

import re
from typing import Any

# "event_type = 1 means page_view" / "event_type=2 means story_click"
_MAPPING_RE = re.compile(
    r"([a-zA-Z_]\w*)\s*=\s*(\d+)\s+means\s+([a-zA-Z_]\w*)", re.IGNORECASE
)
# "In story_events table, ..." / "in the story_events table" / "in story_events,"
_TABLE_RE = re.compile(
    r"\bin\s+(?:the\s+)?([a-zA-Z_]\w*)\s+table\b|\bin\s+([a-zA-Z_]\w*)\s*,", re.IGNORECASE
)


def derive_scope(table: str | None, field: str | None) -> str:
    """Derive a memory scope from the table/field. Analytics-event tables map to
    ``analytics.events`` (matches the canonical example)."""
    t = (table or "").lower()
    f = (field or "").lower()
    if t.endswith("_events") or f == "event_type" or "event" in f:
        return "analytics.events"
    if t:
        return f"analytics.{t}"
    return "analytics.general"


def extract_memory(text: str, *, default_scope: str | None = None) -> dict[str, Any] | None:
    """Extract a ``create`` memory-proposal payload from ``text``, or ``None``.

    Returns a dict: ``{operation, scope, structured_value, confidence}`` where
    ``structured_value`` is ``{table, field, mapping}`` for a recognised mapping.
    """
    mappings = _MAPPING_RE.findall(text)
    if not mappings:
        return None

    # The field is the left-hand identifier (consistent across the mapping list).
    field = mappings[0][0]
    mapping: dict[str, str] = {}
    for fld, num, label in mappings:
        if fld.lower() == field.lower():
            mapping[num] = label

    if not mapping:
        return None

    table_match = _TABLE_RE.search(text)
    table = None
    if table_match:
        table = table_match.group(1) or table_match.group(2)

    scope = default_scope or derive_scope(table, field)
    structured_value: dict[str, Any] = {"field": field, "mapping": mapping}
    if table:
        structured_value["table"] = table

    return {
        "operation": "create",
        "scope": scope,
        "structured_value": structured_value,
        "confidence": 0.9 if table else 0.7,
    }


# ── Recall-question parsing ───────────────────────────────────────────────────

_RECALL_RE = re.compile(
    r"\bwhat\s+(?:does|is)\b.*\bmean(?:ing)?\b|\bmeaning\s+of\b|\bwhat\s+are\s+the\s+.*values\b",
    re.IGNORECASE,
)
_RECALL_FIELD_RE = re.compile(
    r"\b(?:does|is)\s+(?:the\s+)?([a-zA-Z_]\w*)\s+mean\b|\bmeaning\s+of\s+([a-zA-Z_]\w*)",
    re.IGNORECASE,
)
_RECALL_TABLE_RE = re.compile(r"\bin\s+(?:the\s+)?([a-zA-Z_]\w*)\b", re.IGNORECASE)


def is_recall_question(text: str) -> bool:
    return bool(_RECALL_RE.search(text))


def parse_recall_target(text: str) -> tuple[str | None, str | None]:
    """Return ``(table, field)`` parsed from a recall question, either may be None."""
    field = None
    fm = _RECALL_FIELD_RE.search(text)
    if fm:
        field = fm.group(1) or fm.group(2)
    table = None
    tm = _RECALL_TABLE_RE.search(text)
    if tm:
        table = tm.group(1)
    return table, field
