"""
AgentSpec — Week 22 (Agent Factory, Pillar 13)

Every agent spawned by ARIA is described by an AgentSpec.
The spec is the contract between the factory and the registry:
  factory.scaffold_agent(spec) → produces runnable Python module stub
  registry.register(spec)      → makes the agent discoverable
  graph._route_to_skill()      → can look up registered agents by capability

Lifecycle:
  draft      → spec created, not yet tested
  sandbox    → deployed to isolated env, approval required before promotion
  active     → running in production, governs real tasks
  deprecated → replaced by a newer version, no new tasks routed to it

Why typed specs (not a plain dict):
  The factory generates code from these fields.
  Wrong types = broken generated code at runtime.
  Pydantic catches that at spec creation time, not at deploy time.
"""
from datetime import datetime, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field


AgentStatus = Literal["draft", "sandbox", "active", "deprecated"]


class AgentCapability(BaseModel):
    skill_name:  str
    action_tier: Literal["T1", "T2", "T3", "T4"] = "T2"
    description: str = ""


class AgentSpec(BaseModel):
    name:         str  = Field(..., description="Unique kebab-case agent name, e.g. 'analytics-aria'")
    role:         str  = Field(..., description="One-line role title, e.g. 'Analytics Specialist'")
    goal:         str  = Field(..., description="One sentence: what this agent optimises for")
    backstory:    str  = Field(..., description="Context paragraph the LLM uses to stay in role")
    capabilities: list[AgentCapability] = Field(default_factory=list)
    owner:        str  = "aria-platform"
    version:      str  = "v1"
    status:       AgentStatus = "draft"
    created_at:   str  = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    parent_agent: Optional[str] = None   # name of the agent that spawned this one

    @property
    def skill_names(self) -> list[str]:
        return [c.skill_name for c in self.capabilities]

    def promote(self) -> "AgentSpec":
        """Return a copy with status advanced one step in the lifecycle."""
        _next: dict[AgentStatus, AgentStatus] = {
            "draft":      "sandbox",
            "sandbox":    "active",
            "active":     "active",
            "deprecated": "deprecated",
        }
        return self.model_copy(update={"status": _next[self.status]})

    def deprecate(self) -> "AgentSpec":
        return self.model_copy(update={"status": "deprecated"})
