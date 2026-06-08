"""
ARIA Evolution Intelligence — Weeks 27–28

Governed self-evolution: monitor → debate → sandbox → integrate.
Human approval is required at every gate. ARIA never modifies production
behaviour without explicit sign-off.

Public API
----------
Models      : EvolutionProposal, EvolutionType, ProposalStatus, DebateVerdict,
              SandboxResult, IntegrationResult, RISK_CEILING
Store       : ProposalStore (Protocol), InMemoryProposalStore
Monitor     : EvolutionMonitor, MonitorSummary, MonitorSignal
Debate      : DebateEngine, DebateResult
Sandbox     : run_sandbox
RAPTOR      : RaptorBuilder, RaptorTree, RaptorChunk, query_tree
Integration : IntegrationEngine, IntegrationContext
Pipeline    : ProposalPipeline, PipelineResult   (Week 28)
UpdateMgr   : UpdateManager                       (Week 28)
UpdateModel : UpdateRelease, UpdateStatus, ComponentType, ImpactLevel,
              UpdateComparison, UpdateNotFoundError, UpdateStateError,
              SelfApprovalError, ConstitutionalViolationError,
              HashMismatchError, ConcurrentActivationError,
              compute_hash                         (Week 28)
"""

from aria.evolution.debate import DebateEngine, DebateResult
from aria.evolution.integration import IntegrationContext, IntegrationEngine
from aria.evolution.models import (
    RISK_CEILING,
    DebateArgument,
    DebateVerdict,
    EvolutionProposal,
    EvolutionType,
    IntegrationResult,
    ProposalStatus,
    SandboxResult,
    utc_now,
)
from aria.evolution.monitor import EvolutionMonitor, MonitorSignal, MonitorSummary
from aria.evolution.pipeline import PipelineResult, ProposalPipeline
from aria.evolution.raptor import RaptorBuilder, RaptorChunk, RaptorTree, query_tree
from aria.evolution.sandbox import run_sandbox
from aria.evolution.store import InMemoryProposalStore, ProposalStore
from aria.evolution.update_manager.models import (
    ComponentType,
    ConcurrentActivationError,
    ConstitutionalViolationError,
    HashMismatchError,
    ImpactLevel,
    SelfApprovalError,
    UpdateComparison,
    UpdateNotFoundError,
    UpdateRelease,
    UpdateStateError,
    UpdateStatus,
    compute_hash,
)
from aria.evolution.update_manager.operations import UpdateManager
from aria.evolution.update_manager.store import InMemoryUpdateStore, UpdateStore

__all__ = [
    # Models (Week 27)
    "EvolutionType",
    "EvolutionProposal",
    "ProposalStatus",
    "DebateArgument",
    "DebateVerdict",
    "SandboxResult",
    "IntegrationResult",
    "RISK_CEILING",
    "utc_now",
    # Store (Week 27)
    "ProposalStore",
    "InMemoryProposalStore",
    # Monitor (Week 27)
    "EvolutionMonitor",
    "MonitorSummary",
    "MonitorSignal",
    # Debate (Week 27)
    "DebateEngine",
    "DebateResult",
    # Sandbox (Week 27)
    "run_sandbox",
    # RAPTOR (Week 27)
    "RaptorBuilder",
    "RaptorTree",
    "RaptorChunk",
    "query_tree",
    # Integration (Week 27)
    "IntegrationEngine",
    "IntegrationContext",
    # Pipeline (Week 28)
    "ProposalPipeline",
    "PipelineResult",
    # Update Manager models (Week 28)
    "UpdateRelease",
    "UpdateStatus",
    "ComponentType",
    "ImpactLevel",
    "UpdateComparison",
    "UpdateNotFoundError",
    "UpdateStateError",
    "SelfApprovalError",
    "ConstitutionalViolationError",
    "HashMismatchError",
    "ConcurrentActivationError",
    "compute_hash",
    # Update Manager store (Week 28)
    "UpdateStore",
    "InMemoryUpdateStore",
    # Update Manager operations (Week 28)
    "UpdateManager",
]
