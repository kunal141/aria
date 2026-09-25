"""
Tenant organization profile — the seam that makes ARIA employer-neutral.

ARIA's engine was always generic; only the *persona* was hardcoded to one employer.
This module turns that persona into tenant configuration, so a skill prompt says
"Northwind Logistics, supply chain" for one tenant and something else for another,
with a neutral default when no profile exists.

Two safety properties matter here, because these values are interpolated into system
prompts:

1. **Values are sanitized.** A credential pasted into an org name never reaches a
   prompt, a log, or a model.
2. **Values are single-line and bounded.** A tenant must not be able to steer a system
   prompt by embedding instructions in its own organization name — newlines are
   collapsed and lengths capped, so profile text cannot open a new prompt section.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from aria.goals.sanitize import sanitize_text

_PROFILE_FILENAME = "org_profile.json"

_MAX_NAME = 120
_MAX_ITEM = 80
_MAX_ITEMS = 12

_NEUTRAL_ORG = "the organization"
_NEUTRAL_INDUSTRY = "technology"


def _single_line(value: str, limit: int) -> str:
    """Sanitize, collapse to one line, and bound — prompt-injection hygiene."""
    cleaned = sanitize_text(value) or ""
    return " ".join(cleaned.split())[:limit].strip()


def _items(values: list[str]) -> list[str]:
    cleaned = [_single_line(value, _MAX_ITEM) for value in values[:_MAX_ITEMS]]
    return [value for value in cleaned if value]


class TenantOrgProfile(BaseModel):
    """What a tenant's employees should know about the organization they work for."""
    model_config = ConfigDict(frozen=True)

    org_name: str = _NEUTRAL_ORG
    industry: str = _NEUTRAL_INDUSTRY
    services: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    project_keys: list[str] = Field(default_factory=list)

    def context_block(self) -> str:
        """A neutral, bounded preamble prepended to skill system prompts."""
        org = _single_line(self.org_name, _MAX_NAME) or _NEUTRAL_ORG
        industry = _single_line(self.industry, _MAX_NAME) or _NEUTRAL_INDUSTRY
        lines = [
            "## Operating context",
            f"Organization: {org}",
            f"Industry: {industry}",
        ]
        services = _items(self.services)
        metrics = _items(self.metrics)
        keys = _items(self.project_keys)
        if services:
            lines.append(f"Systems in scope: {', '.join(services)}")
        if metrics:
            lines.append(f"Business metrics in scope: {', '.join(metrics)}")
        if keys:
            lines.append(f"Delivery project keys: {', '.join(keys)}")
        lines.append(
            "Ground every claim in supplied evidence. If the evidence does not support "
            "a claim, say so rather than asserting it."
        )
        return "\n".join(lines)


def profile_path(tenant_root: Path) -> Path:
    return Path(tenant_root) / _PROFILE_FILENAME


def load_org_profile(tenant_root: Path) -> TenantOrgProfile:
    """Load a tenant's profile, falling back to a neutral default.

    Absent, unreadable, or malformed profiles yield the neutral default rather than
    raising: a missing profile must degrade to "generic employer", never to a
    previous tenant's identity and never to a hard failure mid-run.
    """
    path = profile_path(tenant_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return TenantOrgProfile()
        return TenantOrgProfile.model_validate(payload)
    except (OSError, ValueError):
        return TenantOrgProfile()


def save_org_profile(tenant_root: Path, profile: TenantOrgProfile) -> TenantOrgProfile:
    path = profile_path(tenant_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return profile


__all__ = [
    "TenantOrgProfile",
    "load_org_profile",
    "profile_path",
    "save_org_profile",
]
