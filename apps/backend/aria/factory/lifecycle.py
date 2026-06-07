"""
Agent Factory Lifecycle — V1

Complete lifecycle for creating, validating, approving, activating, and
rolling back agent specs. This is the production workflow that turns a
validated AgentSpec into a running registered agent.

Stages (in order):
  1. validate_scaffold(spec)           — compile + smoke-test generated code
  2. security_check(spec, source)      — scan for unsafe patterns (defence-in-depth)
  3. request_factory_approval(spec)    — T4 approval gate; human must confirm
  4. activate_agent(spec, source, ...) — write to workspace + register as active
  5. rollback_agent(name, registry)    — restore previous version from history

Orchestrated path:
  result = run_lifecycle(spec, registry, approved_by="kunal")
"""
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from aria.factory.agent_spec import AgentSpec
from aria.factory.registry import AgentRegistry
from aria.factory.scaffold import scaffold_agent

if TYPE_CHECKING:
    from aria.governance.approval_gate import ApprovalRequest


# ── Result models ─────────────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    passed: bool
    compile_ok: bool
    smoke_test_ok: bool
    issues: list[str] = []


class SecurityCheckResult(BaseModel):
    passed: bool
    issues: list[str] = []


class ActivationResult(BaseModel):
    agent_name: str
    source_path: str
    registered: bool


class LifecycleResult(BaseModel):
    spec_name: str
    stage_reached: str   # "validation"|"security"|"approval"|"activation"|"complete"
    validation: Optional[ValidationResult] = None
    security: Optional[SecurityCheckResult] = None
    approval_request_id: Optional[str] = None
    activation: Optional[ActivationResult] = None
    success: bool
    error: Optional[str] = None


# ── Unsafe patterns: must never appear in generated agent code ────────────────
# The scaffold template is known-safe, but this is a defence-in-depth gate
# that would catch any future template regression or unforeseen bypass.

_UNSAFE: list[tuple[str, str]] = [
    (r"\bimport os\b",         "raw 'import os'"),
    (r"\bimport sys\b",        "raw 'import sys'"),
    (r"\bimport subprocess\b", "'import subprocess'"),
    (r"\b__import__\s*\(",     "__import__() call"),
    (r"\bexec\s*\(",           "exec() call"),
    (r"\beval\s*\(",           "eval() call"),
    (r"\bopen\s*\(",           "open() call"),
    (r"os\.system\s*\(",       "os.system() call"),
    (r"subprocess\.",          "subprocess usage"),
]


# ── Stage 1: validation ───────────────────────────────────────────────────────

def validate_scaffold(spec: AgentSpec) -> ValidationResult:
    """
    Generate the scaffold, verify it compiles, then smoke-test the node
    function with a mock ARIAState.
    """
    issues: list[str] = []
    source = scaffold_agent(spec)
    module_name = spec.name.replace("-", "_")

    # Syntax check
    try:
        compile(source, "<scaffold>", "exec")
    except SyntaxError as exc:
        issues.append(f"SyntaxError: {exc}")
        return ValidationResult(passed=False, compile_ok=False, smoke_test_ok=False, issues=issues)

    # Runtime smoke-test
    ok, msg = _smoke_test(source, module_name)
    if not ok:
        issues.append(f"Smoke test failed: {msg}")

    return ValidationResult(
        passed=ok,
        compile_ok=True,
        smoke_test_ok=ok,
        issues=issues,
    )


def _smoke_test(source: str, module_name: str) -> tuple[bool, str]:
    """Execute the scaffolded module and call the node with a mock state."""
    ns: dict = {}
    try:
        exec(compile(source, "<scaffold>", "exec"), ns)
    except Exception as exc:
        return False, f"exec failed: {exc}"

    fn_name = f"{module_name}_node"
    fn = ns.get(fn_name)
    if fn is None:
        return False, f"node function '{fn_name}' not found"

    mock_state = {
        "task_id":          "lifecycle-smoke-test",
        "raw_input":        "Smoke test input",
        "steps_completed":  [],
        "data_sensitivity": "internal",
        "audience":         "developer",
    }
    try:
        result = fn(mock_state)
    except Exception as exc:
        return False, f"node raised: {exc}"

    if not isinstance(result, dict):
        return False, f"node returned {type(result).__name__}, expected dict"
    for key in ("skill_name", "skill_output", "steps_completed"):
        if key not in result:
            return False, f"node result missing key: {key!r}"
    return True, ""


# ── Stage 2: security check ───────────────────────────────────────────────────

def security_check(spec: AgentSpec, source: str) -> SecurityCheckResult:
    """
    Scan the generated source for unsafe patterns that should never appear
    regardless of what values were in the spec.
    """
    issues: list[str] = []
    for pattern, label in _UNSAFE:
        if re.search(pattern, source):
            issues.append(f"Unsafe pattern: {label}")
    return SecurityCheckResult(passed=not issues, issues=issues)


# ── Stage 3: approval ─────────────────────────────────────────────────────────

def request_factory_approval(spec: AgentSpec) -> "ApprovalRequest":
    """
    Create a T4 approval request.  The caller is responsible for waiting
    for the human to approve before calling activate_agent().
    """
    from aria.governance.approval_gate import request_approval
    return request_approval(
        task_id=f"factory:{spec.name}:{spec.version}",
        tool_name="agent_activate",
        proposed_action=(
            f"Activate agent '{spec.name}' v{spec.version} — "
            f"role: {spec.role}, "
            f"capabilities: {', '.join(spec.skill_names) or 'none'}"
        ),
        action_tier="T4",
    )


# ── Stage 4: activation ───────────────────────────────────────────────────────

def activate_agent(
    spec: AgentSpec,
    source: str,
    registry: AgentRegistry,
    *,
    workspace_dir: Optional[Path] = None,
) -> ActivationResult:
    """
    Write the agent source to workspace_dir/{name}.py and register it as
    active.  The caller must verify approval before calling this function.
    """
    if workspace_dir is None:
        workspace_dir = Path(tempfile.mkdtemp(prefix="aria_agents_"))
    workspace_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{spec.name.replace('-', '_')}.py"
    dest = workspace_dir / filename
    dest.write_text(source, encoding="utf-8")

    active_spec = spec.model_copy(update={"status": "active"})
    registry.register(active_spec)

    return ActivationResult(
        agent_name=spec.name,
        source_path=str(dest),
        registered=True,
    )


# ── Stage 5: rollback ─────────────────────────────────────────────────────────

def rollback_agent(name: str, registry: AgentRegistry) -> Optional[AgentSpec]:
    """
    Restore the most recent archived version of an agent.

    Deprecates the currently registered version, re-registers the previous
    archived version as active.  Returns the restored spec or None if there
    is no history record.
    """
    history_keys = sorted(
        [k for k in registry._agents if k.startswith(f"{name}@")],
        key=lambda k: registry._agents[k].created_at,
    )
    if not history_keys:
        return None

    previous = registry._agents[history_keys[-1]]

    # Deprecate current
    current = registry.get(name)
    if current and current.status == "active":
        deprecated = current.model_copy(update={"status": "deprecated"})
        versioned_key = f"{name}@{current.version}"
        registry._agents[name] = deprecated
        registry._agents[versioned_key] = deprecated

    # Restore previous as active
    restored = previous.model_copy(update={"status": "active"})
    registry._agents[name] = restored
    return restored


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_lifecycle(
    spec: AgentSpec,
    registry: AgentRegistry,
    *,
    approved_by: str,
    workspace_dir: Optional[Path] = None,
) -> LifecycleResult:
    """
    Run all five lifecycle stages for a spec.

    In production the approval stage is asynchronous — the human clicks Approve
    in the Teams card and a webhook resumes the flow.  For headless / test use,
    pass approved_by to auto-approve immediately after the request is created.

    Returns a LifecycleResult describing the outcome of every stage.
    """
    source = scaffold_agent(spec)

    # Stage 1 — validate
    validation = validate_scaffold(spec)
    if not validation.passed:
        return LifecycleResult(
            spec_name=spec.name, stage_reached="validation",
            validation=validation, success=False,
            error="; ".join(validation.issues),
        )

    # Stage 2 — security
    sec = security_check(spec, source)
    if not sec.passed:
        return LifecycleResult(
            spec_name=spec.name, stage_reached="security",
            validation=validation, security=sec, success=False,
            error="; ".join(sec.issues),
        )

    # Stage 3 — request + auto-approve (headless path)
    req = request_factory_approval(spec)
    from aria.governance.approval_gate import approve as _gate_approve
    _gate_approve(req.request_id, approved_by=approved_by)

    # Stage 4 — activate
    activation = activate_agent(spec, source, registry, workspace_dir=workspace_dir)

    return LifecycleResult(
        spec_name=spec.name,
        stage_reached="complete",
        validation=validation,
        security=sec,
        approval_request_id=req.request_id,
        activation=activation,
        success=True,
    )
