"""
Update Manager Models — Week 28

Immutable UpdateRelease records track versioned self-improvement proposals
through their full lifecycle. Status transitions are append-only; every
transition is recorded with a UTC timestamp.

Lifecycle:
  discovered → proposed → evaluated → awaiting_approval
    → canary → active → superseded / rolled_back
    (rejection possible from any non-terminal state)
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, field_validator


# ── Enumerations ───────────────────────────────────────────────────────────────

class UpdateStatus(str, Enum):
    discovered        = "discovered"
    proposed          = "proposed"
    evaluated         = "evaluated"
    awaiting_approval = "awaiting_approval"
    canary            = "canary"
    active            = "active"
    superseded        = "superseded"
    rolled_back       = "rolled_back"
    rejected          = "rejected"


class ComponentType(str, Enum):
    prompt             = "prompt"
    retrieval_config   = "retrieval_config"
    evaluation_rubric  = "evaluation_rubric"
    routing_rule       = "routing_rule"
    skill              = "skill"
    voice_ux           = "voice_ux"
    knowledge_ingestion = "knowledge_ingestion"


class ImpactLevel(str, Enum):
    none    = "none"
    low     = "low"
    medium  = "medium"
    high    = "high"
    unknown = "unknown"


# Terminal states — no further transitions allowed
TERMINAL_STATUSES: frozenset[UpdateStatus] = frozenset({
    UpdateStatus.active,
    UpdateStatus.superseded,
    UpdateStatus.rolled_back,
    UpdateStatus.rejected,
})

# ── Hash helper ────────────────────────────────────────────────────────────────

def compute_hash(content: str) -> str:
    """SHA-256 of content string, hex-encoded (64 chars)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Core model ─────────────────────────────────────────────────────────────────

class UpdateRelease(BaseModel):
    """
    An immutable versioned update record.

    Use model_copy(update={...}) to advance lifecycle state — never mutate fields
    directly.  The store always holds the latest version of each update_id.

    content_hash MUST equal sha256(content.encode()) when content is present.
    Activation and rollback operations verify this before proceeding.
    """
    update_id:          str
    component_name:     str
    component_type:     ComponentType
    semantic_version:   str           # e.g. "1.2.0"
    previous_version:   Optional[str] = None
    rollback_target:    Optional[str] = None   # version to restore on rollback

    content_hash:       str           # SHA-256 hex, 64 chars
    changelog:          str
    affected_components: list[str] = []
    evidence_refs:      list[str]  = []
    source_refs:        list[str]  = []
    evaluation_results: dict[str, Any] = {}

    security_impact:    ImpactLevel = ImpactLevel.unknown
    privacy_impact:     ImpactLevel = ImpactLevel.unknown
    cost_impact:        ImpactLevel = ImpactLevel.unknown
    latency_impact:     ImpactLevel = ImpactLevel.unknown

    proposer:           str
    approver:           Optional[str] = None
    proposal_id:        Optional[str] = None   # link to EvolutionProposal if present

    status:             UpdateStatus = UpdateStatus.discovered
    content:            Optional[str] = None   # proposed artifact / config text
    previous_content:   Optional[str] = None   # prior version content (for rollback)
    rejection_reason:   Optional[str] = None
    canary_plan:        Optional[str] = None   # human-readable canary description

    # Lifecycle timestamps (UTC ISO, set on each transition)
    discovered_at:        Optional[str] = None
    proposed_at:          Optional[str] = None
    evaluated_at:         Optional[str] = None
    awaiting_approval_at: Optional[str] = None
    canary_at:            Optional[str] = None
    active_at:            Optional[str] = None
    superseded_at:        Optional[str] = None
    rolled_back_at:       Optional[str] = None
    rejected_at:          Optional[str] = None

    @field_validator("content_hash")
    @classmethod
    def _valid_hash(cls, v: str) -> str:
        if not re.match(r"^[a-f0-9]{64}$", v):
            raise ValueError(f"content_hash must be 64-char SHA-256 hex, got {v!r}")
        return v

    @field_validator("semantic_version")
    @classmethod
    def _valid_semver(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+", v):
            raise ValueError(f"semantic_version must be semver (x.y.z), got {v!r}")
        return v

    def verify_hash(self) -> bool:
        """True iff content is present and its SHA-256 matches content_hash."""
        if self.content is None:
            return False
        return compute_hash(self.content) == self.content_hash

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


# ── Comparison model ───────────────────────────────────────────────────────────

class UpdateComparison(BaseModel):
    """Diff view between previous and proposed version of a component."""
    update_id:        str
    component_name:   str
    previous_version: Optional[str]
    proposed_version: str
    previous_content: Optional[str]
    proposed_content: Optional[str]
    changelog:        str
    diff_lines:       list[str] = []    # unified diff lines (populated by compare_update)
    evaluation_results: dict[str, Any] = {}
    security_impact:  ImpactLevel = ImpactLevel.unknown
    privacy_impact:   ImpactLevel = ImpactLevel.unknown
    cost_impact:      ImpactLevel = ImpactLevel.unknown
    latency_impact:   ImpactLevel = ImpactLevel.unknown
    evidence_refs:    list[str]   = []
    canary_plan:      Optional[str] = None
    rollback_target:  Optional[str] = None


# ── Operation result models ────────────────────────────────────────────────────

class UpdateOperationResult(BaseModel):
    """Wraps every mutating operation result."""
    success:    bool
    update_id:  str
    new_status: Optional[UpdateStatus] = None
    notes:      str = ""


# ── Exceptions ────────────────────────────────────────────────────────────────

class UpdateNotFoundError(KeyError):
    def __init__(self, update_id: str) -> None:
        super().__init__(f"Update not found: {update_id!r}")


class UpdateStateError(ValueError):
    """Raised when a transition is invalid for the current status."""
    def __init__(self, update_id: str, current: UpdateStatus, attempted: str) -> None:
        super().__init__(
            f"Update {update_id!r} is in state {current.value!r}; "
            f"cannot {attempted}"
        )


class SelfApprovalError(ValueError):
    def __init__(self, update_id: str, approver: str) -> None:
        super().__init__(
            f"Update {update_id!r}: proposer and approver are both {approver!r}. "
            "Self-approval is forbidden."
        )


class ConstitutionalViolationError(ValueError):
    """Raised when an update violates constitutional safety rules."""
    def __init__(self, update_id: str, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(
            f"Update {update_id!r} violates constitutional rules: "
            + "; ".join(violations)
        )


class HashMismatchError(ValueError):
    """Raised when content hash doesn't match stored hash."""
    def __init__(self, update_id: str) -> None:
        super().__init__(
            f"Update {update_id!r}: SHA-256 of content does not match content_hash. "
            "Activation blocked."
        )


class ConcurrentActivationError(RuntimeError):
    """Raised when activation of an update is already in progress."""
    def __init__(self, update_id: str) -> None:
        super().__init__(
            f"Update {update_id!r} is already being activated. "
            "Concurrent activation blocked."
        )
