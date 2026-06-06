"""
AgentMonitor — Week 25 (Pillar 15).

Reads agent specs from the AgentRegistry and produces AgentHealthRecords.
Health classification is deterministic (no LLM, no network):

  error_rate >= 0.5  → degraded
  queue_depth >= 50  → degraded
  agent_status == "deprecated" → offline
  agent_status == "draft"      → unknown
  otherwise                    → healthy
"""
from typing import Dict, List

from aria.control_plane.models import (
    AgentHealthRecord,
    AgentStatusLiteral,
    QueueStats,
)
from aria.factory.registry import AgentRegistry

_HIGH_QUEUE_THRESHOLD   = 50
_HIGH_ERROR_RATE        = 0.5


def _classify_health(
    agent_status: str,
    queue: QueueStats,
) -> AgentStatusLiteral:
    if agent_status == "deprecated":
        return "offline"
    if agent_status == "draft":
        return "unknown"
    if queue.error_rate >= _HIGH_ERROR_RATE:
        return "degraded"
    if queue.queue_depth >= _HIGH_QUEUE_THRESHOLD:
        return "degraded"
    return "healthy"


class AgentMonitor:
    """
    Reads all agents from a registry and produces health records.

    In V1, queue stats are injected externally (e.g., from the Work Ledger
    or a metrics store). In V2, this pulls live data from a task queue.
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def check_all(
        self,
        queue_stats: Dict[str, QueueStats] | None = None,
    ) -> List[AgentHealthRecord]:
        """
        Produce a health record for every agent in the registry.

        Args:
            queue_stats: Optional dict mapping agent_name → QueueStats.
                         Missing agents get a zero-depth QueueStats.
        """
        queue_stats = queue_stats or {}
        records: List[AgentHealthRecord] = []

        for spec in self._registry.list_agents():
            q = queue_stats.get(
                spec.name,
                QueueStats(agent_name=spec.name),
            )
            health = _classify_health(spec.status, q)
            records.append(
                AgentHealthRecord(
                    agent_name=spec.name,
                    agent_status=spec.status,
                    health=health,
                    queue=q,
                )
            )

        return records
