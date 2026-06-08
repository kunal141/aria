"""
ARIA Evolution Intelligence — Week 27

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
from aria.evolution.raptor import RaptorBuilder, RaptorChunk, RaptorTree, query_tree
from aria.evolution.sandbox import run_sandbox
from aria.evolution.store import InMemoryProposalStore, ProposalStore

__all__ = [
    # Models
    "EvolutionType",
    "EvolutionProposal",
    "ProposalStatus",
    "DebateArgument",
    "DebateVerdict",
    "SandboxResult",
    "IntegrationResult",
    "RISK_CEILING",
    "utc_now",
    # Store
    "ProposalStore",
    "InMemoryProposalStore",
    # Monitor
    "EvolutionMonitor",
    "MonitorSummary",
    "MonitorSignal",
    # Debate
    "DebateEngine",
    "DebateResult",
    # Sandbox
    "run_sandbox",
    # RAPTOR
    "RaptorBuilder",
    "RaptorTree",
    "RaptorChunk",
    "query_tree",
    # Integration
    "IntegrationEngine",
    "IntegrationContext",
]
