"""
Agent Registry — Week 22

Tracks every agent spawned by ARIA's Agent Factory.
Process-level singleton (agent_registry). In-memory for V1;
PostgreSQL-backed in V2 (needs persistence across restarts).

The registry is the source of truth for:
  - Which agents exist and their current status
  - Which capabilities each agent has
  - Who spawned them (parent_agent chain)
  - Version history (name collision = new version, old gets deprecated)
"""
from typing import Literal, Optional
from aria.factory.agent_spec import AgentSpec, AgentStatus


class AgentRegistry:

    def __init__(self) -> None:
        self._agents: dict[str, AgentSpec] = {}

    # ── Write ──────────────────────────────────────────────────────────────────

    def register(self, spec: AgentSpec) -> AgentSpec:
        """
        Register an agent spec.
        If an agent with the same name already exists, deprecate it first
        and store the new spec — versioning via status, not name collision.
        """
        existing = self._agents.get(spec.name)
        if existing and existing.status == "active":
            self._agents[spec.name] = existing.deprecate()
            # Store the deprecated version under a versioned key
            versioned_key = f"{spec.name}@{existing.version}"
            self._agents[versioned_key] = self._agents[spec.name]
        self._agents[spec.name] = spec
        return spec

    def update_status(self, name: str, status: AgentStatus) -> Optional[AgentSpec]:
        """Update status of a registered agent. Returns updated spec or None."""
        spec = self._agents.get(name)
        if spec is None:
            return None
        updated = spec.model_copy(update={"status": status})
        self._agents[name] = updated
        return updated

    # ── Read ───────────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[AgentSpec]:
        return self._agents.get(name)

    def list_agents(
        self,
        status: Optional[AgentStatus] = None,
        capability: Optional[str] = None,
    ) -> list[AgentSpec]:
        """List agents, optionally filtered by status or capability (skill_name)."""
        agents = list(self._agents.values())
        if status:
            agents = [a for a in agents if a.status == status]
        if capability:
            agents = [a for a in agents if capability in a.skill_names]
        return agents

    def count(self, status: Optional[AgentStatus] = None) -> int:
        return len(self.list_agents(status=status))

    # ── Utility ────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Clear all registrations. Used in tests only."""
        self._agents.clear()


# ── Module-level singleton ────────────────────────────────────────────────────

agent_registry = AgentRegistry()


# ── Pre-register the built-in ARIA agents ─────────────────────────────────────

def _seed_builtin_agents() -> None:
    from aria.factory.agent_spec import AgentCapability

    _builtins = [
        AgentSpec(
            name="aria-core",
            role="AI Engineering Assistant",
            goal="Handle PR reviews, KPI investigations, QA, CI/CD analysis, and Jira delivery management",
            backstory=(
                "ARIA is the first AI Employee built on the Amar Ujala AI Platform. "
                "She has deep expertise in the media-tech engineering stack: "
                "recommendation engine, notification service, CMS ingestion, "
                "analytics pipeline, and feed ranking."
            ),
            capabilities=[
                AgentCapability(skill_name="pr_review",   action_tier="T2"),
                AgentCapability(skill_name="kpi",         action_tier="T2"),
                AgentCapability(skill_name="qa",          action_tier="T2"),
                AgentCapability(skill_name="test_review", action_tier="T2"),
                AgentCapability(skill_name="ci_cd",       action_tier="T2"),
                AgentCapability(skill_name="jira",        action_tier="T3"),
            ],
            status="active",
            version="v1",
        ),
    ]
    for spec in _builtins:
        agent_registry._agents[spec.name] = spec   # bypass deprecation for seeds


_seed_builtin_agents()
