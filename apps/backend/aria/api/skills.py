"""
Read-only skills API — lists ARIA's concrete domain skills for the manager interface.

    GET /api/skills

Read-only and deterministic: it returns the typed contract + action tier of each skill from
``aria.skills.catalog``. It NEVER executes a skill, calls a model, touches a network, or reads
a credential. Errors are typed code + sanitised detail — never raw exception text.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from aria.skills.catalog import skills_catalog

_log = logging.getLogger("aria.api.skills")

skills_router = APIRouter(prefix="/api", tags=["skills"])


class SkillItem(BaseModel):
    name: str
    title: str
    category: str
    version: str
    action_tier: int
    tier_name: str
    input_schema: str
    output_schema: str
    description: str


class SkillsResponse(BaseModel):
    api_version: str = "v1"
    count: int
    skills: list[SkillItem]


@skills_router.get("/skills", response_model=SkillsResponse)
def list_skills():
    """Return the read-only catalog of ARIA's domain skills (no execution)."""
    try:
        items = [SkillItem(**s) for s in skills_catalog()]
        return SkillsResponse(count=len(items), skills=items)
    except Exception as exc:  # class only, never raw text
        _log.error("skills catalog error (class only): %s", type(exc).__name__)
        return JSONResponse(status_code=500,
                            content={"error_code": "internal_error",
                                     "detail": "Could not load the skills catalog."})


__all__ = ["skills_router"]
