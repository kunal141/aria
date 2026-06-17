"""
aria.memory_v2 — SQLite Domain Memory Authority (Week 32).

The authoritative, approval-gated, versioned, scope-isolated, restart-safe V2
domain-memory store. Old ``aria.memory`` JSON store remains compatibility-only.

Import-safety: importing this package has no side effects and creates no DB. The
SQLite file + schema are created lazily on first store method call.
"""
from aria.memory_v2.models import (
    ChatSession,
    ChatTurn,
    DomainMemoryProposal,
    DomainMemoryVersion,
    MemoryCitation,
    MemoryOperation,
    ProposalStatus,
    Sensitivity,
)
from aria.memory_v2.paths import (
    PathConfinementError,
    aria_data_dir,
    ensure_confined,
    is_confined,
    memory_db_path,
    workspaces_db_path,
)
from aria.memory_v2.sensitivity import SensitiveMemoryError, classify, is_sensitive
from aria.memory_v2.store import (
    DomainMemoryStore,
    MemoryNotFound,
    ProposalNotPending,
)
from aria.memory_v2.workspace import Workspace, WorkspaceNotFound, WorkspaceStore

__all__ = [
    "DomainMemoryStore",
    "MemoryNotFound",
    "ProposalNotPending",
    "WorkspaceStore",
    "Workspace",
    "WorkspaceNotFound",
    "PathConfinementError",
    "ensure_confined",
    "workspaces_db_path",
    "SensitiveMemoryError",
    "ChatSession",
    "ChatTurn",
    "DomainMemoryProposal",
    "DomainMemoryVersion",
    "MemoryCitation",
    "MemoryOperation",
    "ProposalStatus",
    "Sensitivity",
    "classify",
    "is_sensitive",
    "aria_data_dir",
    "memory_db_path",
    "is_confined",
]
