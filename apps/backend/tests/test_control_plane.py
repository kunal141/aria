"""
Deterministic tests for the Agent Control Plane — Week 25 (Pillar 15).
No LLM, no network. Uses a fresh AgentRegistry for each test.
"""
import pytest

from aria.factory.agent_spec import AgentSpec, AgentCapability
from aria.factory.registry import AgentRegistry
from aria.control_plane import (
    QueueStats, AgentHealthRecord, ScalingDecision, ControlPlaneReport,
    AgentMonitor, ControlPlane,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _spec(name: str, status: str = "active") -> AgentSpec:
    return AgentSpec(
        name=name,
        role="R",
        goal="G",
        backstory="B",
        capabilities=[AgentCapability(skill_name="kpi")],
        status=status,
    )


def _fresh_registry(*agents: AgentSpec) -> AgentRegistry:
    r = AgentRegistry()
    for a in agents:
        r._agents[a.name] = a   # bypass deprecation for test setup
    return r


def _queue(name: str, **kwargs) -> QueueStats:
    return QueueStats(agent_name=name, **kwargs)


# ── QueueStats ────────────────────────────────────────────────────────────────

def test_queue_stats_defaults():
    q = QueueStats(agent_name="aria-core")
    assert q.queue_depth   == 0
    assert q.active_tasks  == 0
    assert q.error_rate    == 0.0


def test_queue_stats_error_rate_zero_when_no_tasks():
    q = QueueStats(agent_name="x", completed_total=0, failed_total=0)
    assert q.error_rate == 0.0


def test_queue_stats_error_rate():
    q = QueueStats(agent_name="x", completed_total=8, failed_total=2)
    assert q.error_rate == pytest.approx(0.2)


def test_queue_stats_error_rate_all_failed():
    q = QueueStats(agent_name="x", completed_total=0, failed_total=5)
    assert q.error_rate == pytest.approx(1.0)


# ── AgentHealthRecord ─────────────────────────────────────────────────────────

def test_agent_health_record_is_healthy():
    q = QueueStats(agent_name="x")
    r = AgentHealthRecord(agent_name="x", agent_status="active", health="healthy", queue=q)
    assert r.is_healthy is True


def test_agent_health_record_is_not_healthy_when_degraded():
    q = QueueStats(agent_name="x")
    r = AgentHealthRecord(agent_name="x", agent_status="active", health="degraded", queue=q)
    assert r.is_healthy is False


def test_agent_health_record_has_timestamp():
    q = QueueStats(agent_name="x")
    r = AgentHealthRecord(agent_name="x", agent_status="active", health="healthy", queue=q)
    assert r.last_checked


# ── AgentMonitor — health classification ──────────────────────────────────────

def test_monitor_active_agent_with_zero_queue_is_healthy():
    registry = _fresh_registry(_spec("a"))
    monitor  = AgentMonitor(registry)
    records  = monitor.check_all()
    assert len(records) == 1
    assert records[0].health == "healthy"


def test_monitor_deprecated_agent_is_offline():
    registry = _fresh_registry(_spec("a", status="deprecated"))
    monitor  = AgentMonitor(registry)
    records  = monitor.check_all()
    assert records[0].health == "offline"


def test_monitor_draft_agent_is_unknown():
    registry = _fresh_registry(_spec("a", status="draft"))
    monitor  = AgentMonitor(registry)
    records  = monitor.check_all()
    assert records[0].health == "unknown"


def test_monitor_high_error_rate_is_degraded():
    registry = _fresh_registry(_spec("a"))
    monitor  = AgentMonitor(registry)
    q = _queue("a", completed_total=2, failed_total=8)   # 80% error rate
    records  = monitor.check_all(queue_stats={"a": q})
    assert records[0].health == "degraded"


def test_monitor_high_queue_depth_is_degraded():
    registry = _fresh_registry(_spec("a"))
    monitor  = AgentMonitor(registry)
    q = _queue("a", queue_depth=50)
    records  = monitor.check_all(queue_stats={"a": q})
    assert records[0].health == "degraded"


def test_monitor_moderate_queue_is_healthy():
    registry = _fresh_registry(_spec("a"))
    monitor  = AgentMonitor(registry)
    q = _queue("a", queue_depth=10)
    records  = monitor.check_all(queue_stats={"a": q})
    assert records[0].health == "healthy"


def test_monitor_missing_queue_stats_defaults_to_zero():
    registry = _fresh_registry(_spec("a"), _spec("b"))
    monitor  = AgentMonitor(registry)
    q_a = _queue("a", queue_depth=5)
    records  = monitor.check_all(queue_stats={"a": q_a})
    b_rec = next(r for r in records if r.agent_name == "b")
    assert b_rec.queue.queue_depth == 0


def test_monitor_excludes_versioned_aliases():
    """Monitor must not double-count @v1 versioned keys (P2.8 fix)."""
    registry = AgentRegistry()
    spec_v1  = _spec("multi", status="active")
    spec_v2  = _spec("multi", status="sandbox")
    spec_v1  = spec_v1.model_copy(update={"version": "v1"})
    spec_v2  = spec_v2.model_copy(update={"version": "v2"})
    registry.register(spec_v1)
    registry.register(spec_v2)
    monitor  = AgentMonitor(registry)
    records  = monitor.check_all()
    # Only one record for "multi", the v2 version; v1 is internal history
    names = [r.agent_name for r in records]
    assert names.count("multi") == 1


# ── ScalingDecision ───────────────────────────────────────────────────────────

def test_scaling_decision_fields():
    d = ScalingDecision(agent_name="x", action="scale_up", reason="Queue critical")
    assert d.action   == "scale_up"
    assert d.urgency  == "low"


def test_scaling_decision_serialises():
    d = ScalingDecision(agent_name="x", action="hold", reason="Normal", urgency="medium")
    dd = d.model_dump()
    assert dd["action"] == "hold"


# ── ControlPlane.report() ─────────────────────────────────────────────────────

def test_control_plane_report_empty_registry():
    cp     = ControlPlane(_fresh_registry())
    report = cp.report()
    assert report.total_agents   == 0
    assert report.healthy_count  == 0
    assert report.fleet_status   == "unknown"


def test_control_plane_report_single_healthy_agent():
    registry = _fresh_registry(_spec("aria-core"))
    cp       = ControlPlane(registry)
    report   = cp.report()
    assert report.total_agents  == 1
    assert report.healthy_count == 1
    assert report.fleet_status  == "healthy"


def test_control_plane_report_degraded_agent_flags_fleet():
    registry = _fresh_registry(_spec("a"))
    cp       = ControlPlane(registry)
    report   = cp.report(queue_stats={"a": _queue("a", queue_depth=50)})
    assert report.degraded_count == 1
    assert report.fleet_status   == "degraded"


def test_control_plane_report_offline_agent_flags_fleet():
    registry = _fresh_registry(_spec("a", status="deprecated"))
    cp       = ControlPlane(registry)
    report   = cp.report()
    assert report.offline_count == 1
    assert report.fleet_status  == "degraded"


def test_control_plane_scaling_scale_up_high_urgency():
    registry = _fresh_registry(_spec("a"))
    cp       = ControlPlane(registry)
    report   = cp.report(queue_stats={"a": _queue("a", queue_depth=50)})
    decision = next(d for d in report.scaling_decisions if d.agent_name == "a")
    assert decision.action  == "scale_up"
    assert decision.urgency == "high"


def test_control_plane_scaling_scale_up_medium_urgency():
    registry = _fresh_registry(_spec("a"))
    cp       = ControlPlane(registry)
    report   = cp.report(queue_stats={"a": _queue("a", queue_depth=20)})
    decision = next(d for d in report.scaling_decisions if d.agent_name == "a")
    assert decision.action  == "scale_up"
    assert decision.urgency == "medium"


def test_control_plane_scaling_scale_down_idle_agent():
    registry = _fresh_registry(_spec("a"))
    cp       = ControlPlane(registry)
    report   = cp.report(queue_stats={"a": _queue("a", queue_depth=0, active_tasks=0)})
    decision = next(d for d in report.scaling_decisions if d.agent_name == "a")
    assert decision.action == "scale_down"


def test_control_plane_scaling_hold_normal():
    registry = _fresh_registry(_spec("a"))
    cp       = ControlPlane(registry)
    report   = cp.report(queue_stats={"a": _queue("a", queue_depth=5, active_tasks=2)})
    decision = next(d for d in report.scaling_decisions if d.agent_name == "a")
    assert decision.action == "hold"


def test_control_plane_health_ratio_all_healthy():
    registry = _fresh_registry(_spec("a"), _spec("b"), _spec("c"))
    cp       = ControlPlane(registry)
    report   = cp.report()
    assert report.health_ratio == pytest.approx(1.0)


def test_control_plane_health_ratio_partial():
    registry = _fresh_registry(_spec("a"), _spec("b", status="deprecated"))
    cp       = ControlPlane(registry)
    report   = cp.report()
    assert report.health_ratio == pytest.approx(0.5)


def test_control_plane_report_serialises():
    registry = _fresh_registry(_spec("a"))
    cp       = ControlPlane(registry)
    report   = cp.report()
    d = report.model_dump()
    assert "total_agents"      in d
    assert "scaling_decisions" in d
    assert "fleet_status"      in d


def test_control_plane_report_has_timestamp():
    cp     = ControlPlane(_fresh_registry())
    report = cp.report()
    assert report.generated_at
