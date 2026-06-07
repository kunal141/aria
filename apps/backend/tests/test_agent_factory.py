"""
Deterministic tests for the Agent Factory (Week 22, Pillar 13).
No LLM, no network, no filesystem.
"""
import pytest
from aria.factory.agent_spec import AgentSpec, AgentCapability, AgentStatus
from aria.factory.registry import AgentRegistry
from aria.factory.scaffold import scaffold_agent, _to_class, _safe_comment


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


# ── P1: AgentSpec name validation ────────────────────────────────────────────

def test_spec_name_starting_with_digit_is_rejected():
    """'123-agent' → '123_agent' is not a valid Python identifier."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="invalid Python identifier"):
        AgentSpec(name="123-agent", role="R", goal="G", backstory="B")


def test_spec_name_with_space_is_rejected():
    """'bad agent' contains a space — produces an invalid Python identifier."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="invalid Python identifier"):
        AgentSpec(name="bad agent", role="R", goal="G", backstory="B")


def test_spec_name_kebab_case_is_accepted():
    """Standard kebab-case names must be accepted."""
    spec = AgentSpec(name="analytics-aria", role="R", goal="G", backstory="B")
    assert spec.name == "analytics-aria"


def test_spec_name_all_letters_is_accepted():
    spec = AgentSpec(name="aria", role="R", goal="G", backstory="B")
    assert spec.name == "aria"


# ── P1: scaffold escaping ────────────────────────────────────────────────────

def test_scaffold_role_with_triple_quotes_is_valid_python():
    """Triple-quotes in role must be escaped; generated code must compile."""
    spec = AgentSpec(
        name="test-agent",
        role='Analytics """Expert""" Specialist',
        goal="Investigate KPI anomalies.",
        backstory='Deep analyst with """industry""" knowledge.',
        capabilities=[AgentCapability(skill_name="kpi")],
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")   # must not raise SyntaxError


def test_scaffold_goal_with_triple_quotes_is_valid_python():
    spec = AgentSpec(
        name="test-agent",
        role="R",
        goal='Optimise """click-through""" rates on the feed.',
        backstory="B",
        capabilities=[],
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")


def test_scaffold_triple_quotes_appear_escaped_in_source():
    """_safe_embed must replace triple-double-quotes in the output."""
    from aria.factory.scaffold import _safe_embed
    assert '"""' not in _safe_embed('has """triple""" quotes')
    assert _safe_embed("no special chars") == "no special chars"


def test_scaffold_version_with_double_quote_is_valid_python():
    """version='v1\"oops' must not produce an unterminated string literal."""
    spec = AgentSpec(
        name="test-agent",
        role="R",
        goal="G",
        backstory="B",
        capabilities=[AgentCapability(skill_name="kpi")],
        version='v1"oops',
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")


def test_scaffold_capability_with_newline_is_valid_python():
    """A newline inside a capability skill_name must not break comment indentation."""
    spec = AgentSpec(
        name="test-agent",
        role="R",
        goal="G",
        backstory="B",
        capabilities=[AgentCapability(skill_name="kpi\nmalicious")],
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")


def test_scaffold_owner_with_backslash_is_valid_python():
    """Backslashes in owner must not produce an invalid escape sequence."""
    spec = AgentSpec(
        name="test-agent",
        role="R",
        goal="G",
        backstory="B",
        capabilities=[],
        owner=r"domain\user",
    )
    source = scaffold_agent(spec)
    compile(source, "<scaffold>", "exec")


def test_safe_comment_strips_newlines():
    assert "\n" not in _safe_comment("foo\nbar")
    assert "\r" not in _safe_comment("foo\r\nbar")
    assert _safe_comment("clean") == "clean"


# ── P2.1: update_status validation ───────────────────────────────────────────

def test_update_status_invalid_value_raises(registry):
    """model_validate must reject status values outside the AgentStatus Literal."""
    from pydantic import ValidationError
    registry.register(_make_spec(name="status-agent", status="draft"))
    with pytest.raises(ValidationError):
        registry.update_status("status-agent", "broken")   # type: ignore[arg-type]


def test_update_status_valid_values_accepted(registry):
    registry.register(_make_spec(name="status-agent2", status="draft"))
    for valid_status in ("sandbox", "active", "deprecated", "draft"):
        result = registry.update_status("status-agent2", valid_status)
        assert result is not None
        assert result.status == valid_status


# ── P2.2: history preserved for draft and sandbox ────────────────────────────

def test_registry_re_register_archives_draft(registry):
    """Replacing a draft agent must leave a history record."""
    spec_v1 = _make_spec(name="history-agent", status="draft",   version="v1")
    spec_v2 = _make_spec(name="history-agent", status="sandbox", version="v2")
    registry.register(spec_v1)
    registry.register(spec_v2)
    archived = registry.get("history-agent@v1")
    assert archived is not None, "draft v1 must be archived under history-agent@v1"
    assert archived.version == "v1"
    assert archived.status == "draft"   # draft stays draft, not force-deprecated


def test_registry_re_register_archives_sandbox(registry):
    """Replacing a sandbox agent must leave a history record."""
    spec_v1 = _make_spec(name="sb-agent", status="sandbox", version="v1")
    spec_v2 = _make_spec(name="sb-agent", status="active",  version="v2")
    registry.register(spec_v1)
    registry.register(spec_v2)
    archived = registry.get("sb-agent@v1")
    assert archived is not None, "sandbox v1 must be archived under sb-agent@v1"
    assert archived.status == "sandbox"   # sandbox stays sandbox


def test_registry_re_register_still_deprecates_active(registry):
    """Replacing an active agent must deprecate and archive it (existing behaviour)."""
    spec_v1 = _make_spec(name="act-agent", status="active",  version="v1")
    spec_v2 = _make_spec(name="act-agent", status="sandbox", version="v2")
    registry.register(spec_v1)
    registry.register(spec_v2)
    archived = registry.get("act-agent@v1")
    assert archived is not None
    assert archived.status == "deprecated"


def test_registry_three_generation_history_preserved(registry):
    """v1 → v2 → v3: both v1 and v2 must be in history."""
    v1 = _make_spec(name="gen-agent", status="active",  version="v1")
    v2 = _make_spec(name="gen-agent", status="active",  version="v2")
    v3 = _make_spec(name="gen-agent", status="sandbox", version="v3")
    registry.register(v1)
    registry.register(v2)
    registry.register(v3)
    assert registry.get("gen-agent@v1") is not None
    assert registry.get("gen-agent@v2") is not None
    assert registry.get("gen-agent").version == "v3"
