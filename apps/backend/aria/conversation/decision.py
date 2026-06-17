"""
Typed orchestrator decision (Week 32 §1).

The conversation orchestrator emits exactly one of four typed decisions. This
model is backward-compatible with Week 31's frozen ``MinimalRoutingDecision``
(``action`` + ``rationale``) — it only adds optional fields, so the Week-31
fitness contract still holds.

``rationale`` is a short, surfaced reason — NEVER raw chain-of-thought.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrchestratorAction(str, Enum):
    converse = "converse"          # answer conversationally
    run_workflow = "run_workflow"  # invoke the governed V1 graph boundary
    propose_memory = "propose_memory"  # extract reusable domain knowledge
    clarify = "clarify"            # ask a focused clarification question


class OrchestratorDecision(BaseModel):
    """Backward-compatible with Week 31 ``MinimalRoutingDecision`` (action + rationale)."""

    model_config = ConfigDict(extra="ignore")

    action: OrchestratorAction
    rationale: str = Field(min_length=1)
    confidence: float = 0.5
    correlation_id: str = Field(min_length=1)
    # Optional structured payload (e.g. an extracted memory proposal, or parsed
    # recall target). Never carries chain-of-thought.
    payload: dict[str, Any] = Field(default_factory=dict)
