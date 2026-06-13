"""
Stable typed API response models for GET /api/v1/ledger/metrics.

These models are the PUBLIC contract for downstream consumers (the ROI
Dashboard, future BI integrations, future ledger exporters). They are
INTENTIONALLY separate from the internal ``MetricsSummary`` dataclass so
that the ledger's internal shape can evolve without breaking dashboard
consumers — the conversion happens in ``api.py``.

Money values
------------
``Decimal`` cost fields are serialised as strings (not floats) so the
dashboard sees exact, stable representation. ``None`` is preserved for
unavailable values — the spec demands "Return null for unavailable
rates, costs, and durations. Do not fabricate zeros."

Privacy
-------
Only aggregate counts / rates / breakdowns are exposed. No raw events,
metadata, error strings, prompts, transcripts, credentials, actor
identities. The ledger has its own redaction at write time; the API
response model is the second wall: it only carries the metric shape,
so even if a field were to leak through redaction the API never reads
it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_serializer


class FiltersApplied(BaseModel):
    """Echoes the query-string filters that were actually applied."""
    model_config = ConfigDict(extra="forbid")
    start_date:  Optional[str] = None   # ISO-8601 UTC
    end_date:    Optional[str] = None   # ISO-8601 UTC
    skill:       Optional[str] = None
    actor_type:  Optional[str] = None
    workflow_id: Optional[str] = None


class ExecutionPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_tasks_completed: int
    tasks_by_skill:        dict[str, int]


class ApprovalPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_rate:          Optional[float]
    approvals_granted:      int
    approvals_rejected:     int
    approval_rate_by_skill: dict[str, Optional[float]]


class FailurePanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failure_rate:          Optional[float]
    failed_tasks:          int
    terminal_tasks:        int
    failure_rate_by_skill: dict[str, Optional[float]]


class ResolutionPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    avg_time_to_resolution_ms: Optional[float]


class CostPanel(BaseModel):
    """All money is serialised as a decimal STRING (never float)."""
    model_config = ConfigDict(extra="forbid")
    estimated_cost_total:    Decimal
    estimated_cost_per_task: Optional[Decimal]
    tasks_with_cost:         int

    @field_serializer("estimated_cost_total")
    def _ser_total(self, v: Decimal) -> str:
        return str(v)

    @field_serializer("estimated_cost_per_task")
    def _ser_per_task(self, v: Optional[Decimal]) -> Optional[str]:
        return None if v is None else str(v)


class HumanInterventionPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate: Optional[float]


class ArtifactsPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int


class CorrectionsPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int


class ModelsPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usage_breakdown: dict[str, int]


class SourcesPanel(BaseModel):
    """Counts by ledger source — drives the legacy vs v2 split panel."""
    model_config = ConfigDict(extra="forbid")
    v2_event_count:         int
    legacy_task_count:      int
    legacy_evolution_count: int
    malformed_count:        int


class MetricsResponse(BaseModel):
    """
    Top-level GET /api/v1/ledger/metrics response.

    The dashboard treats every nested panel as independent so a single
    metric being unavailable does not cause other panels to disappear.
    """
    model_config = ConfigDict(extra="forbid")
    api_version:       str = "v1"
    filters_applied:   FiltersApplied
    execution:         ExecutionPanel
    approval:          ApprovalPanel
    failure:           FailurePanel
    resolution:        ResolutionPanel
    cost:              CostPanel
    human_intervention: HumanInterventionPanel
    artifacts:         ArtifactsPanel
    corrections:       CorrectionsPanel
    models:            ModelsPanel
    sources:           SourcesPanel


class MetricsErrorResponse(BaseModel):
    """Typed error payload for non-2xx responses."""
    model_config = ConfigDict(extra="forbid")
    api_version: str = "v1"
    error_code:  str   # ``config_error`` | ``filesystem_error`` | ``oversized_ledger`` | ``invalid_filter`` | ``unexpected``
    detail:      str
