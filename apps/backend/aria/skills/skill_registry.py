"""
Skill Registry — Week 6

Central registry for all ARIA skills. Every skill is:
  - Named (used by router to look it up)
  - Versioned (v1 → v2 → v3 as the skill improves)
  - Typed (Pydantic input + output — enforced by Instructor from Week 21)

Week 6:  manual registration, dict lookup
Week 13: registry persisted to DB, skill metadata queryable
Week 22: Agent Factory generates new skill scaffolds from registry patterns
"""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SkillMetadata:
    name: str
    version: str
    description: str
    action_tier: int        # 1=Read, 2=Recommend, 3=Draft, 4=Execute, 5=Autonomous
    fn: Callable


_registry: dict[str, SkillMetadata] = {}


def register(
    name: str,
    fn: Callable,
    version: str = "v1",
    description: str = "",
    action_tier: int = 2,
) -> None:
    _registry[name] = SkillMetadata(
        name=name,
        version=version,
        description=description,
        action_tier=action_tier,
        fn=fn,
    )


def get(name: str) -> SkillMetadata | None:
    return _registry.get(name)


def list_skills() -> list[dict]:
    return [
        {"name": m.name, "version": m.version, "description": m.description, "tier": m.action_tier}
        for m in _registry.values()
    ]
