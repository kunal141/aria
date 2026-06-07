"""
Agent Factory Lifecycle tests — Week 22+
No LLM, no network. All lifecycle stages tested deterministically.
"""
import tempfile
from pathlib import Path

import pytest

from aria.factory.agent_spec import AgentCapability, AgentSpec
from aria.factory.lifecycle import (
    ActivationResult,
    LifecycleResult,
    SecurityCheckResult,
    ValidationResult,
    activate_agent,
    request_factory_approval,
    rollback_agent,
    run_lifecycle,
    security_check,
    validate_scaffold,
)
from aria.factory.registry import AgentRegistry
from aria.factory.scaffold import scaffold_agent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_spec(**kwargs) -> AgentSpec:
    defaults = dict(
        name="lifecycle-aria",
        role="Lifecycle Test Agent",
        goal="Verify the Agent Factory lifecycle end-to-end.",
        backstory="An agent created solely for testing the factory lifecycle.",
        capabilities=[AgentCapability(skill_name="kpi", action_tier="T2")],
    )
    defaults.update(kwargs)
    return AgentSpec(**defaults)


@pytest.fixture(autouse=True)
def clear_approval_gate():
    """Clear the in-memory approval gate before and after each test."""
    from aria.governance.approval_gate import clear
    clear()
    yield
    clear()


@pytest.fixture()
def registry():
    r = AgentRegistry()
    yield r
    r.clear()


# ── Stage 1: validate_scaffold ────────────────────────────────────────────────

def test_validate_scaffold_passes_for_clean_spec():
    spec = _make_spec()
    result = validate_scaffold(spec)
    assert isinstance(result, ValidationResult)
    assert result.passed
    assert result.compile_ok
    assert result.smoke_test_ok
    assert result.issues == []


def test_validate_scaffold_returns_validation_result_type():
    result = validate_scaffold(_make_spec())
    assert isinstance(result, ValidationResult)


def test_validate_scaffold_passes_for_no_capabilities():
    spec = _make_spec(capabilities=[])
    result = validate_scaffold(spec)
    assert result.passed


def test_validate_scaffold_passes_with_multiple_capabilities():
    spec = _make_spec(
        capabilities=[
            AgentCapability(skill_name="kpi", action_tier="T2"),
            AgentCapability(skill_name="pr_review", action_tier="T2"),
        ]
    )
    result = validate_scaffold(spec)
    assert result.passed


def test_validate_scaffold_fails_for_manually_broken_source(monkeypatch):
    """Monkeypatch scaffold_agent to return syntactically invalid Python."""
    import aria.factory.lifecycle as lc
    monkeypatch.setattr(lc, "scaffold_agent", lambda spec: "def bad syntax !!!")
    result = validate_scaffold(_make_spec())
    assert not result.passed
    assert not result.compile_ok
    assert any("SyntaxError" in issue for issue in result.issues)


def test_validate_scaffold_fails_when_node_function_missing(monkeypatch):
    """Monkeypatch scaffold_agent to return valid Python with wrong function name."""
    import aria.factory.lifecycle as lc

    def _broken_scaffold(spec):
        return (
            "from aria.state import ARIAState\n"
            "from aria.skills import skill_registry\n"
            "from aria.runtime.harness import guard_loop\n"
            "\n"
            "def wrong_name_node(state):\n"
            "    return {'skill_name': 'x', 'skill_output': 'y', 'steps_completed': []}\n"
        )

    monkeypatch.setattr(lc, "scaffold_agent", _broken_scaffold)
    result = validate_scaffold(_make_spec(name="lifecycle-aria"))
    # module_name = "lifecycle_aria", expected fn = "lifecycle_aria_node"
    assert not result.passed
    assert any("not found" in issue for issue in result.issues)


def test_validate_scaffold_fails_when_node_returns_wrong_type(monkeypatch):
    """Node function returns a string instead of dict."""
    import aria.factory.lifecycle as lc

    def _bad_return_scaffold(spec):
        return (
            "from aria.state import ARIAState\n"
            "from aria.skills import skill_registry\n"
            "from aria.runtime.harness import guard_loop\n"
            "\n"
            "def lifecycle_aria_node(state):\n"
            "    guard_loop(state['steps_completed'], state['task_id'])\n"
            "    return 'not a dict'\n"
        )

    monkeypatch.setattr(lc, "scaffold_agent", _bad_return_scaffold)
    result = validate_scaffold(_make_spec(name="lifecycle-aria"))
    assert not result.passed
    assert any("expected dict" in issue for issue in result.issues)


def test_validate_scaffold_fails_when_result_missing_key(monkeypatch):
    """Node function omits a required key from the return dict."""
    import aria.factory.lifecycle as lc

    def _missing_key_scaffold(spec):
        return (
            "from aria.state import ARIAState\n"
            "from aria.skills import skill_registry\n"
            "from aria.runtime.harness import guard_loop\n"
            "\n"
            "def lifecycle_aria_node(state):\n"
            "    guard_loop(state['steps_completed'], state['task_id'])\n"
            "    return {'skill_name': 'x', 'skill_output': 'y'}\n"
            # Missing 'steps_completed'
        )

    monkeypatch.setattr(lc, "scaffold_agent", _missing_key_scaffold)
    result = validate_scaffold(_make_spec(name="lifecycle-aria"))
    assert not result.passed
    assert any("missing key" in issue for issue in result.issues)


# ── Stage 2: security_check ───────────────────────────────────────────────────

def test_security_check_passes_for_clean_scaffold():
    spec = _make_spec()
    source = scaffold_agent(spec)
    result = security_check(spec, source)
    assert isinstance(result, SecurityCheckResult)
    assert result.passed
    assert result.issues == []


def test_security_check_blocks_import_os():
    spec = _make_spec()
    result = security_check(spec, "import os\nprint(os.getcwd())")
    assert not result.passed
    assert any("import os" in issue for issue in result.issues)


def test_security_check_blocks_import_sys():
    spec = _make_spec()
    result = security_check(spec, "import sys")
    assert not result.passed


def test_security_check_blocks_import_subprocess():
    spec = _make_spec()
    result = security_check(spec, "import subprocess")
    assert not result.passed


def test_security_check_blocks_exec():
    spec = _make_spec()
    result = security_check(spec, "exec('malicious code')")
    assert not result.passed
    assert any("exec()" in issue for issue in result.issues)


def test_security_check_blocks_eval():
    spec = _make_spec()
    result = security_check(spec, "x = eval('1+1')")
    assert not result.passed
    assert any("eval()" in issue for issue in result.issues)


def test_security_check_blocks_open():
    spec = _make_spec()
    result = security_check(spec, "f = open('/etc/passwd', 'r')")
    assert not result.passed


def test_security_check_blocks_os_system():
    spec = _make_spec()
    result = security_check(spec, "os.system('rm -rf /')")
    assert not result.passed


def test_security_check_blocks_dunder_import():
    spec = _make_spec()
    result = security_check(spec, "mod = __import__('os')")
    assert not result.passed


def test_security_check_blocks_subprocess_usage():
    spec = _make_spec()
    result = security_check(spec, "subprocess.run(['ls'])")
    assert not result.passed


def test_security_check_reports_multiple_issues():
    spec = _make_spec()
    source = "import os\nimport sys\nexec('x')"
    result = security_check(spec, source)
    assert not result.passed
    assert len(result.issues) >= 3


# ── Stage 3: request_factory_approval ────────────────────────────────────────

def test_request_factory_approval_creates_pending_request():
    from aria.governance.approval_gate import get
    spec = _make_spec()
    req = request_factory_approval(spec)
    stored = get(req.request_id)
    assert stored is not None
    assert stored.status == "pending"


def test_request_factory_approval_action_tier_is_t4():
    spec = _make_spec()
    req = request_factory_approval(spec)
    assert req.action_tier == "T4"


def test_request_factory_approval_tool_name_is_agent_activate():
    spec = _make_spec()
    req = request_factory_approval(spec)
    assert req.tool_name == "agent_activate"


def test_request_factory_approval_proposed_action_contains_spec_name():
    spec = _make_spec(name="lifecycle-aria")
    req = request_factory_approval(spec)
    assert "lifecycle-aria" in req.proposed_action


def test_request_factory_approval_idempotent():
    """Requesting approval twice for same task+tool returns existing request."""
    spec = _make_spec()
    req1 = request_factory_approval(spec)
    req2 = request_factory_approval(spec)
    assert req1.request_id == req2.request_id


# ── Stage 4: activate_agent ───────────────────────────────────────────────────

def test_activate_agent_registers_as_active(registry):
    spec = _make_spec()
    source = scaffold_agent(spec)
    with tempfile.TemporaryDirectory() as tmpdir:
        result = activate_agent(spec, source, registry, workspace_dir=Path(tmpdir))
    assert isinstance(result, ActivationResult)
    assert result.registered
    stored = registry.get("lifecycle-aria")
    assert stored is not None
    assert stored.status == "active"


def test_activate_agent_writes_source_file(registry):
    spec = _make_spec()
    source = scaffold_agent(spec)
    with tempfile.TemporaryDirectory() as tmpdir:
        result = activate_agent(spec, source, registry, workspace_dir=Path(tmpdir))
        written = Path(result.source_path)
        assert written.exists()
        assert written.read_text(encoding="utf-8") == source


def test_activate_agent_filename_matches_module_name(registry):
    spec = _make_spec(name="my-specialist-aria")
    source = scaffold_agent(spec)
    with tempfile.TemporaryDirectory() as tmpdir:
        result = activate_agent(spec, source, registry, workspace_dir=Path(tmpdir))
        assert Path(result.source_path).name == "my_specialist_aria.py"


def test_activate_agent_uses_temp_dir_when_none_given(registry):
    spec = _make_spec()
    source = scaffold_agent(spec)
    result = activate_agent(spec, source, registry, workspace_dir=None)
    # Should have created a tempdir and written the file there
    assert Path(result.source_path).exists()
    assert result.agent_name == "lifecycle-aria"


def test_activate_agent_creates_workspace_dir_if_missing(registry):
    spec = _make_spec()
    source = scaffold_agent(spec)
    with tempfile.TemporaryDirectory() as tmpdir:
        new_dir = Path(tmpdir) / "nested" / "workspace"
        result = activate_agent(spec, source, registry, workspace_dir=new_dir)
        assert new_dir.exists()
        assert Path(result.source_path).exists()


# ── Stage 5: rollback_agent ───────────────────────────────────────────────────

def test_rollback_agent_returns_none_when_no_history(registry):
    registry.register(_make_spec(name="no-history-aria", status="active"))
    result = rollback_agent("no-history-aria", registry)
    assert result is None


def test_rollback_agent_returns_none_for_unknown_agent(registry):
    result = rollback_agent("ghost-aria", registry)
    assert result is None


def test_rollback_agent_restores_previous_version(registry):
    v1 = _make_spec(name="rollback-aria", version="v1", status="active")
    v2 = _make_spec(name="rollback-aria", version="v2", status="sandbox")
    registry.register(v1)
    registry.register(v2)

    restored = rollback_agent("rollback-aria", registry)
    assert restored is not None
    assert restored.status == "active"
    assert restored.version == "v1"


def test_rollback_agent_deprecates_current_active(registry):
    v1 = _make_spec(name="rollback-aria", version="v1", status="active")
    v2 = _make_spec(name="rollback-aria", version="v2", status="active")
    registry.register(v1)
    registry.register(v2)

    rollback_agent("rollback-aria", registry)
    # After rollback, v1 should be active; v2 should be deprecated
    current = registry.get("rollback-aria")
    assert current.version == "v1"
    assert current.status == "active"


def test_rollback_agent_uses_most_recent_history_entry(registry):
    """With v1 and v2 in history, rollback should restore the most recent (v2)."""
    v1 = _make_spec(name="multi-aria", version="v1", status="active")
    v2 = _make_spec(name="multi-aria", version="v2", status="active")
    v3 = _make_spec(name="multi-aria", version="v3", status="active")
    registry.register(v1)
    registry.register(v2)
    registry.register(v3)

    # v1 and v2 are now in history; v3 is current
    restored = rollback_agent("multi-aria", registry)
    assert restored is not None
    assert restored.version == "v2"


# ── run_lifecycle — full orchestration ────────────────────────────────────────

def test_run_lifecycle_success_path(registry):
    spec = _make_spec()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_lifecycle(
            spec, registry,
            approved_by="kunal",
            workspace_dir=Path(tmpdir),
        )
    assert isinstance(result, LifecycleResult)
    assert result.success
    assert result.stage_reached == "complete"
    assert result.spec_name == "lifecycle-aria"


def test_run_lifecycle_populates_all_stage_results(registry):
    spec = _make_spec()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_lifecycle(spec, registry, approved_by="kunal", workspace_dir=Path(tmpdir))
    assert result.validation is not None
    assert result.security is not None
    assert result.approval_request_id is not None
    assert result.activation is not None
    assert result.error is None


def test_run_lifecycle_agent_registered_as_active_after_success(registry):
    spec = _make_spec()
    with tempfile.TemporaryDirectory() as tmpdir:
        run_lifecycle(spec, registry, approved_by="kunal", workspace_dir=Path(tmpdir))
    stored = registry.get("lifecycle-aria")
    assert stored is not None
    assert stored.status == "active"


def test_run_lifecycle_source_file_written_after_success(registry):
    spec = _make_spec()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_lifecycle(spec, registry, approved_by="kunal", workspace_dir=Path(tmpdir))
        assert result.activation is not None
        assert Path(result.activation.source_path).exists()


def test_run_lifecycle_stops_at_validation_stage(registry, monkeypatch):
    """If validation fails, lifecycle must not proceed to security or activation."""
    import aria.factory.lifecycle as lc
    monkeypatch.setattr(lc, "scaffold_agent", lambda spec: "def bad syntax !!!")

    spec = _make_spec()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_lifecycle(spec, registry, approved_by="kunal", workspace_dir=Path(tmpdir))

    assert not result.success
    assert result.stage_reached == "validation"
    assert result.security is None
    assert result.activation is None
    assert registry.get("lifecycle-aria") is None


def test_run_lifecycle_stops_at_security_stage(registry, monkeypatch):
    """If security check fails, lifecycle must not proceed to activation."""
    import aria.factory.lifecycle as lc

    def _unsafe_scaffold(spec):
        source = scaffold_agent(spec)
        return source + "\nimport os\n"

    monkeypatch.setattr(lc, "scaffold_agent", _unsafe_scaffold)

    spec = _make_spec()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_lifecycle(spec, registry, approved_by="kunal", workspace_dir=Path(tmpdir))

    assert not result.success
    assert result.stage_reached == "security"
    assert result.validation is not None   # validation ran
    assert result.activation is None       # activation did not run
    assert registry.get("lifecycle-aria") is None


def test_run_lifecycle_approval_request_is_auto_approved(registry):
    """In headless mode, the approval request should end up approved."""
    from aria.governance.approval_gate import get

    spec = _make_spec()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_lifecycle(spec, registry, approved_by="kunal", workspace_dir=Path(tmpdir))

    assert result.approval_request_id is not None
    req = get(result.approval_request_id)
    assert req is not None
    assert req.status == "approved"
    assert req.approved_by == "kunal"


def test_run_lifecycle_error_field_set_on_failure(registry, monkeypatch):
    import aria.factory.lifecycle as lc
    monkeypatch.setattr(lc, "scaffold_agent", lambda spec: "def bad syntax !!!")

    result = run_lifecycle(_make_spec(), registry, approved_by="kunal")
    assert result.error is not None
    assert len(result.error) > 0


def test_run_lifecycle_security_error_lists_issues(registry, monkeypatch):
    import aria.factory.lifecycle as lc

    def _unsafe_scaffold(spec):
        return scaffold_agent(spec) + "\nimport os\nimport sys\n"

    monkeypatch.setattr(lc, "scaffold_agent", _unsafe_scaffold)

    result = run_lifecycle(_make_spec(), registry, approved_by="kunal")
    assert not result.success
    assert result.error is not None
    assert "import os" in result.error or "import sys" in result.error


# ── Full round-trip: lifecycle → rollback ─────────────────────────────────────

def test_lifecycle_then_rollback_restores_previous(registry):
    """Run lifecycle twice; rollback from v2 should restore v1."""
    v1_spec = _make_spec(version="v1")
    v2_spec = _make_spec(version="v2")

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        run_lifecycle(v1_spec, registry, approved_by="kunal", workspace_dir=ws)
        run_lifecycle(v2_spec, registry, approved_by="kunal", workspace_dir=ws)

    # v2 is now current active
    assert registry.get("lifecycle-aria").version == "v2"

    # Rollback should return v1 as active
    restored = rollback_agent("lifecycle-aria", registry)
    assert restored is not None
    assert restored.version == "v1"
    assert restored.status == "active"
