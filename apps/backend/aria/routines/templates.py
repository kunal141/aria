"""
Deterministic digest templates for V3.8 routines.

Pure rendering of already-gathered, persisted data into a concise body. Templates
invent NO facts: an empty section is shown as an explicit "(none)" rather than filled
with a guess, so missing data stays visible. No template sends anything.
"""
from __future__ import annotations


def bullets(items: list[str], *, empty: str = "(none)") -> str:
    items = [i for i in (items or []) if i and str(i).strip()]
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {i}" for i in items)


def render(title: str, sections: list[tuple[str, list[str]]], *,
           empties: dict[str, str] | None = None) -> str:
    """Render a titled digest from ``(heading, items)`` sections. ``empties`` maps a
    heading to a custom empty-label."""
    empties = empties or {}
    parts = [title.strip(), ""]
    for heading, items in sections:
        parts.append(f"{heading}:")
        parts.append(bullets(items, empty=empties.get(heading, "(none)")))
        parts.append("")
    return "\n".join(parts).rstrip()
