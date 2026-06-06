"""
ControlPlane — Week 25 (Pillar 15).

Top-level API for the Agent Control Plane.
Combines AgentMonitor (health) + scaling decisions into a ControlPlaneReport.

Scaling rules (deterministic, V1):
  queue_depth >= 20 and agent is active → scale_up (medium urgency)
  queue_depth >= 50                     → scale_up (high urgency)
  queue_depth == 0 and active_tasks==0  → scale_down (low urgency)
  otherwise                             → hold
"""
from typing import Dict, List, Optional

from aria.control_plane.models import (
    AgentHealthRecord,
    AgentStatusLiteral,
    ControlPlaneReport,
    QueueStats,
    ScalingDecision,
)
from aria.control_plane.monitor import AgentMonitor
from aria.factory.registry import AgentRegistry

_SCALE_UP_URGENT   = 50
_SCALE_UP_NORMAL   = 20


def _scaling_decision(record: AgentHealthRecord) -> ScalingDecision:
    q = record.queue
    if q.queue_depth >= _SCALE_UP_URGENT:
        return ScalingDecision(
            agent_name=record.agent_name,
            action="scale_up",
            reason=f"Queue depth critical: {q.queue_depth} pending tasks",
            urgency="high",
        )
    if q.queue_depth >= _SCALE_UP_NORMAL and record.agent_status == "active":
        return ScalingDecision(
            agent_name=record.agent_name,
            action="scale_up",
            reason=f"Queue depth elevated: {q.queue_depth} pending tasks",
            urgency="medium",
        )
    if q.queue_depth == 0 and q.active_tasks == 0 and record.agent_status == "active":
        return ScalingDecision(
            agent_name=record.agent_name,
            action="scale_down",
            reason="No pending or active tasks",
            urgency="low",
        )
    return ScalingDecision(
        agent_name=record.agent_name,
        action="hold",
        reason="Queue within normal range",
        urgency="low",
    )


def _fleet_status(records: List[AgentHealthRecord]) -> AgentStatusLiteral:
    if not records:
        return "unknown"
    statuses = {r.health for r in records}
    if "offline" in statuses:
        return "degraded"
    if "degraded" in statuses:
        return "degraded"
    if all(r.health == "healthy" for r in records):
        return "healthy"
    return "unknown"


class ControlPlane:
    """
    Agent Control Plane — monitors fleet health and emits scaling decisions.

    Usage:
        cp = ControlPlane(registry)
        report = cp.report(queue_stats={...})
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._monitor = AgentMonitor(registry)

    def report(
        self,
        queue_stats: Optional[Dict[str, QueueStats]] = None,
    ) -> ControlPlaneReport:
        """Produce a full ControlPlaneReport for the current fleet state."""
        records    = self._monitor.check_all(queue_stats=queue_stats)
        decisions  = [_scaling_decision(r) for r in records]
        fleet      = _fleet_status(records)

        healthy    = sum(1 for r in records if r.health == "healthy")
        degraded   = sum(1 for r in records if r.health == "degraded")
        offline    = sum(1 for r in records if r.health == "offline")

        return ControlPlaneReport(
            total_agents=len(records),
            healthy_count=healthy,
            degraded_count=degraded,
            offline_count=offline,
            records=records,
            scaling_decisions=decisions,
            fleet_status=fleet,
        )
