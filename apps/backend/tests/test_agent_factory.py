"""
Deterministic tests for the Agent Factory (Week 22, Pillar 13).
No LLM, no network, no filesystem.
"""
import pytest
from aria.factory.agent_spec import AgentSpec, AgentCapability, AgentStatus
from aria.factory.registry import AgentRegistry
from aria.factory.scaffold import scaffold_agent, _to_class


# ── AgentSpec ─────────────────────────────────────────────────────────────────

def _make_spec(**kwargs) -> AgentSpec:
    defaults = dict(
        name="analytics-aria",
        role="Analytics Specialist",
        goal="Investigate KPI anomalies for Amar Ujala's media platform",
        backstory="Expert data analyst with deep knowledge of media metrics.",
        capabilities=[
            AgentCapability(skill_name="kpi",  action_tier="T2"),
            AgentCapability(skill_name="qa",   action_tier="T2"),
        ],
    )
    defaults.update(kwargs)
    return AgentSpec(**defaults)


def test_agent_spec_defaults():
    spec = _make_spec()
    assert spec.status == "draft"
    assert spec.version == "v1"
    assert spec.owner == "aria-platform"
    assert spec.created_at   # non-empty ISO timestamp


def test_agent_spec_skill_names():
    spec = _make_spec()
    assert spec.skill_names == ["kpi", "qa"]


def test_agent_spec_promote_draft_to_sandbox():
    spec = _make_spec()
    promoted = spec.promote()
    assert promoted.status == "sandbox"
    assert spec.status == "draft"   # original unchanged (immutable copy)


def test_agent_spec_promote_sandbox_to_active():
    spec = _make_spec(status="sandbox")
    assert spec.promote().status == "active"


def test_agent_spec_promote_active_stays_active():
    spec = _make_spec(status="active")
    assert spec.promote().status == "active"


def test_agent_spec_deprecate():
    spec = _make_spec(status="active")
    assert spec.deprecate().status == "deprecated"


def test_agent_capability_defaults():
    cap = AgentCapability(skill_name="pr_review")
    assert cap.action_tier == "T2"
    assert cap.description == ""


# ── AgentRegistry ─────────────────────────────────────────────────────────────

@pytest.fixture()
def registry():
    r = AgentRegistry()
    yield r
    r.clear()


def test_registry_register_and_get(registry):
    spec = _make_spec()
    registry.register(spec)
    retrieved = registry.get("analytics-aria")
    assert retrieved is not None
    assert retrieved.name == "analytics-aria"


def test_registry_get_unknown_returns_none(registry):
    assert registry.get("nonexistent") is None


def test_registry_list_all(registry):
    registry.register(_make_spec(name="agent-a"))
    registry.register(_make_spec(name="agent-b"))
    assert len(registry.list_agents()) == 2


def test_registry_list_by_status(registry):
    registry.register(_make_spec(name="draft-agent",  status="draft"))
    registry.register(_make_spec(name="active-agent", status="active"))
    drafts  = registry.list_agents(status="draft")
    actives = registry.list_agents(status="active")
    assert len(drafts)  == 1
    assert len(actives) == 1
    assert drafts[0].name  == "draft-agent"
    assert actives[0].name == "active-agent"


def test_registry_list_by_capability(registry):
    registry.register(_make_spec(name="kpi-agent",  capabilities=[AgentCapability(skill_name="kpi")]))
    registry.register(_make_spec(name="qa-agent",   capabilities=[AgentCapability(skill_name="qa")]))
    kpi_agents = registry.list_agents(capability="kpi")
    assert len(kpi_agents) == 1
    assert kpi_agents[0].name == "kpi-agent"


def test_registry_count(registry):
    registry.register(_make_spec(name="a1", status="draft"))
    registry.register(_make_spec(name="a2", status="active"))
    assert registry.count() == 2
    assert registry.count(status="draft") == 1


def test_registry_update_status(registry):
    registry.register(_make_spec(name="my-agent", status="draft"))
    updated = registry.update_status("my-agent", "sandbox")
    assert updated.status == "sandbox"
    assert registry.get("my-agent").status == "sandbox"


def test_registry_update_unknown_returns_none(registry):
    result = registry.update_status("ghost", "active")
    assert result is None


def test_registry_re_register_deprecates_active(registry):
    spec_v1 = _make_spec(name="versioned-agent", status="active",  version="v1")
    spec_v2 = _make_spec(name="versioned-agent", status="sandbox", version="v2")
    registry.register(spec_v1)
    registry.register(spec_v2)
    # Current "versioned-agent" is v2
    current = registry.get("versioned-agent")
    assert current.version == "v2"
    # Old v1 stored under versioned key
    old = registry.get("versioned-agent@v1")
    assert old is not None
    assert old.status == "deprecated"


def test_registry_clear(registry):
    registry.register(_make_spec())
    registry.clear()
    assert registry.count() == 0


# ── scaffold_agent ────────────────────────────────────────────────────────────

def test_scaffold_returns_string():
    spec = _make_spec()
    source = scaffold_agent(spec)
    assert isinstance(source, str)
    assert len(source) > 0


def test_scaffold_contains_module_docstring():
    spec = _make_spec(name="analytics-aria", role="Analytics Specialist")
    source = scaffold_agent(spec)
    assert "Analytics Specialist" in source
    assert "analytics-aria" in source


def test_scaffold_contains_node_function():
    spec = _make_spec(name="analytics-aria")
    source = scaffold_agent(spec)
    assert "def analytics_aria_node(state: ARIAState)" in source


def test_scaffold_contains_guard_loop():
    spec = _make_spec()
    source = scaffold_agent(spec)
    assert "guard_loop(" in source


def test_scaffold_contains_steps_completed():
    spec = _make_spec(name="analytics-aria")
    source = scaffold_agent(spec)
    assert "steps_completed" in source
    assert "analytics_aria_node" in source


def test_scaffold_is_valid_python():
    spec = _make_spec(name="analytics-aria")
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")   # raises SyntaxError if invalid


def test_scaffold_single_capability():
    spec = AgentSpec(
        name="kpi-only-aria",
        role="KPI Specialist",
        goal="Investigate KPI anomalies.",
        backstory="Expert analyst.",
        capabilities=[AgentCapability(skill_name="kpi")],
    )
    source = scaffold_agent(spec)
    assert "kpi" in source
    compile(source, "<scaffold>", "exec")


def test_scaffold_no_capabilities_does_not_crash():
    spec = AgentSpec(
        name="empty-aria",
        role="Empty",
        goal="TBD",
        backstory="TBD",
        capabilities=[],
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")


# ── _to_class helper ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("skill, expected", [
    ("kpi",         "KPI"),
    ("ci_cd",       "CICD"),
    ("pr_review",   "PRReview"),
    ("qa",          "QA"),
    ("test_review", "TestReview"),
    ("jira",        "Jira"),
    ("unknown_xyz", "UnknownXyz"),
])
def test_to_class_conversion(skill, expected):
    assert _to_class(skill) == expected


# ── Builtin agent seeded at import ───────────────────────────────────────────

def test_builtin_aria_core_registered():
    from aria.factory.registry import agent_registry
    spec = agent_registry.get("aria-core")
    assert spec is not None
    assert spec.status == "active"
    assert "kpi" in spec.skill_names
    assert "pr_review" in spec.skill_names
