"""
Typed records for the SQLite Domain Memory Authority (Week 32).

These Pydantic models mirror the five SQLite tables and are what the store
returns. ``structured_value`` / ``approved_value`` are arbitrary JSON-able dicts
(stored as JSON text in SQLite).

Field names match the Week 32 spec exactly.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryOperation(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"


class ProposalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Sensitivity(str, Enum):
    """Sensitivity classification of a memory request.

    V2 has no authenticated identity layer, so anything above ``normal`` is
    out of scope and must be refused on both persist and retrieve.
    """
    normal = "normal"
    confidential = "confidential"
    restricted = "restricted"
    sensitive = "sensitive"


SENSITIVE_LEVELS = frozenset({
    Sensitivity.confidential, Sensitivity.restricted, Sensitivity.sensitive,
})


class ChatSession(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    owner: str
    scope: str
    created_at: datetime
    updated_at: datetime


class ChatTurn(BaseModel):
    model_config = ConfigDict(frozen=True)
    turn_id: str
    session_id: str
    role: str
    content: str
    model: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    timestamp: datetime


class DomainMemoryProposal(BaseModel):
    model_config = ConfigDict(frozen=True)
    proposal_id: str
    operation: MemoryOperation
    structured_value: dict[str, Any]
    source_turn_id: str | None = None
    owner: str
    scope: str
    confidence: float = 0.0
    status: ProposalStatus = ProposalStatus.pending
    created_at: datetime
    decided_at: datetime | None = None
    # The memory this proposal targets (set for update/delete; None for create).
    target_memory_id: str | None = None


class DomainMemoryVersion(BaseModel):
    model_config = ConfigDict(frozen=True)
    memory_id: str
    version: int = Field(ge=1)
    approved_value: dict[str, Any] | None   # None on a tombstone (delete)
    source_turn_id: str | None = None
    proposal_id: str
    owner: str
    approver: str
    scope: str
    created_at: datetime
    superseded_by: int | None = None        # version that replaced this one
    rollback_target: int | None = None      # version this one restored (rollback)
    is_active: bool = True
    is_tombstone: bool = False


class MemoryCitation(BaseModel):
    model_config = ConfigDict(frozen=True)
    memory_id: str
    version: int
    relevant_fields: list[str] = Field(default_factory=list)
    retrieval_reason: str
