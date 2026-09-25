"""
Compose a skill's generic system prompt with its tenant's operating context.

Deliberately **concatenation, not string formatting**. Skill prompts contain literal
JSON braces (``Return {"verdict": ...}``), and running ``str.format`` over them raises
or silently mangles the schema the model is meant to emit — a failure mode this
codebase has already been bitten by once.
"""
from __future__ import annotations

from typing import Any


def build_system_prompt(skill_prompt: str, profile: Any | None) -> str:
    """Prepend the tenant's operating context to a generic skill prompt.

    A missing profile yields the skill prompt unchanged, so an unconfigured tenant
    still gets a working, employer-neutral employee.
    """
    if profile is None:
        return skill_prompt
    block = profile.context_block() if hasattr(profile, "context_block") else str(profile)
    if not block.strip():
        return skill_prompt
    return f"{block}\n\n{skill_prompt}"


__all__ = ["build_system_prompt"]
