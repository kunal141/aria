"""
Update Manager — Week 28

Versioned self-improvement lifecycle with canary, promotion, and verified rollback.
"""
from aria.evolution.update_manager.constitutional import (
    check_constitutional,
    is_constitutionally_safe,
)
from aria.evolution.update_manager.health import HealthCheckResult, run_health_checks
from aria.evolution.update_manager.models import (
    TERMINAL_STATUSES,
    ConcurrentActivationError,
    ComponentType,
    ConstitutionalViolationError,
    HashMismatchError,
    ImpactLevel,
    SelfApprovalError,
    UpdateComparison,
    UpdateNotFoundError,
    UpdateOperationResult,
    UpdateRelease,
    UpdateStateError,
    UpdateStatus,
    compute_hash,
    utc_now,
)
from aria.evolution.update_manager.operations import UpdateManager
from aria.evolution.update_manager.store import InMemoryUpdateStore, UpdateStore

__all__ = [
    "UpdateRelease", "UpdateStatus", "ComponentType", "ImpactLevel",
    "UpdateComparison", "UpdateOperationResult",
    "TERMINAL_STATUSES", "compute_hash", "utc_now",
    "UpdateNotFoundError", "UpdateStateError", "SelfApprovalError",
    "ConstitutionalViolationError", "HashMismatchError", "ConcurrentActivationError",
    "UpdateStore", "InMemoryUpdateStore",
    "HealthCheckResult", "run_health_checks",
    "check_constitutional", "is_constitutionally_safe",
    "UpdateManager",
]
