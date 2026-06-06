"""
Agent Control Plane data models — Week 25 (Pillar 15).

AgentHealthRecord  → snapshot of one agent's current health
QueueStats         → task queue metrics for an agent
ScalingDecision    → recommendation: scale_up | scale_down | hold
ControlPlaneReport → full fleet health summary
"""
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


AgentStatusLiteral   = Literal["healthy", "degraded", "offline", "unknown"]
ScalingAction        = Literal["scale_up", "scale_down", "hold"]


class QueueStats(BaseModel):
    """Task queue metrics for a single agent."""
    agent_name:       str
    queue_depth:      int   = 0       # pending tasks waiting for this agent
    active_tasks:     int   = 0       # tasks currently executing
    completed_total:  int   = 0       # lifetime completed tasks
    failed_total:     int   = 0       # lifetime failed tasks

    @property
    def error_rate(self) -> float:
        total = self.completed_total + self.failed_total
        return round(self.failed_total / total, 4) if total > 0 else 0.0


class AgentHealthRecord(BaseModel):
    """Health snapshot for a single registered agent."""
    agent_name:   str
    agent_status: str                              # from AgentSpec.status (draft/sandbox/active/deprecated)
    health:       AgentStatusLiteral = "unknown"
    queue:        QueueStats
    last_checked: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error_message: Optional[str] = None

    @property
    def is_healthy(self) -> bool:
        return self.health == "healthy"


class ScalingDecision(BaseModel):
    """Scaling recommendation for one agent."""
    agent_name: str
    action:     ScalingAction
    reason:     str
    urgency:    Literal["low", "medium", "high"] = "low"


class ControlPlaneReport(BaseModel):
    """Full fleet health summary produced by ControlPlane.report()."""
    generated_at:      str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    total_agents:      int
    healthy_count:     int
    degraded_count:    int
    offline_count:     int
    records:           List[AgentHealthRecord]
    scaling_decisions: List[ScalingDecision]
    fleet_status:      AgentStatusLiteral

    @property
    def health_ratio(self) -> float:
        if self.total_agents == 0:
            return 0.0
        return round(self.healthy_count / self.total_agents, 4)
