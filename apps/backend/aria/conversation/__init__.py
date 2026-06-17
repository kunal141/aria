"""
aria.conversation — Week 32 Conversational Orchestrator (above the V1 graph).

Produces typed decisions (converse / run_workflow / propose_memory / clarify),
preserves V1 graph governance, and never executes tools directly — workflows go
through the governed ``aria.chat.ask`` graph boundary. Domain knowledge becomes
approval-gated proposals in the SQLite memory authority (``aria.memory_v2``).

Import-safety: importing this package has no side effects (no Ollama, no DB, no
graph build at import time).
"""
from aria.conversation.decision import OrchestratorAction, OrchestratorDecision
from aria.conversation.extraction import (
    derive_scope,
    extract_memory,
    is_recall_question,
    parse_recall_target,
)
from aria.conversation.orchestrator import (
    ConversationOrchestrator,
    OrchestratorTurnResult,
)

__all__ = [
    "ConversationOrchestrator",
    "OrchestratorTurnResult",
    "OrchestratorAction",
    "OrchestratorDecision",
    "extract_memory",
    "is_recall_question",
    "parse_recall_target",
    "derive_scope",
]
