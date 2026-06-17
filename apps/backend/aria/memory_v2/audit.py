"""
Work Ledger event construction for the domain-memory store (Week 32 §6).

The **store** owns both the memory-store *state* events (memory_proposed /
memory_applied / memory_recalled / memory_superseded / memory_deleted /
memory_rolled_back) AND the reused governance *decision* events
(approval_requested / approved / rejected). It emits them through the
transactional **audit outbox** (see ``aria.memory_v2.store``): every event is
built here, then enqueued into SQLite inside the same transaction as the state
change and flushed to the Work Ledger, so state and audit can never diverge.

Conversation-flow events (conversation_started / message_received /
workflow_invoked) are emitted separately by the orchestrator — see
``aria.conversation.audit``.

Memory-specific identifiers (session_id, scope, memory_id, memory_version,
proposal_id, execution_mode) ride in the sanitised ``metadata`` dict; the
governance ``approval_id`` is a typed envelope field. No envelope field changes
are needed and redaction still runs.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    ApprovalRequested,
    Approved,
    LedgerEventType,
    MemoryApplied,
    MemoryDeleted,
    MemoryProposed,
    MemoryRecalled,
    MemoryRolledBack,
    MemorySuperseded,
    Rejected,
)
from aria.ledger.events import make_envelope

# The store emits BOTH memory state-transition events AND the reused governance
# decision events (approval_requested / approved / rejected), so the decision
# audit always fires regardless of entry path (direct store OR via orchestrator).
_EVENT_CLASSES = {
    LedgerEventType.memory_proposed:    MemoryProposed,
    LedgerEventType.memory_applied:     MemoryApplied,
    LedgerEventType.memory_recalled:    MemoryRecalled,
    LedgerEventType.memory_superseded:  MemorySuperseded,
    LedgerEventType.memory_deleted:     MemoryDeleted,
    LedgerEventType.memory_rolled_back: MemoryRolledBack,
    LedgerEventType.approval_requested: ApprovalRequested,
    LedgerEventType.approved:           Approved,
    LedgerEventType.rejected:           Rejected,
}


def build_memory_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    session_id: str | None = None,
    scope: str | None = None,
    memory_id: str | None = None,
    memory_version: int | None = None,
    proposal_id: str | None = None,
    approval_id: str | None = None,
    execution_mode: str | None = None,
    model: str | None = None,
    outcome: str | None = None,
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("session_id", session_id),
        ("scope", scope),
        ("memory_id", memory_id),
        ("memory_version", memory_version),
        ("proposal_id", proposal_id),
        ("execution_mode", execution_mode),
    ):
        if value is not None:
            meta[key] = value
    # ``approval_id`` is a typed envelope field (required by ApprovalRequested /
    # Approved / Rejected), not metadata.
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or session_id or task_id,
        approval_id=approval_id,
        model_name=model,
        outcome=outcome,
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)


def emit_memory_event(event_type: LedgerEventType, *, writer=None, **fields) -> bool:
    """Append a memory state-transition event. Uses the default (test-isolated)
    v2 writer unless one is injected."""
    if writer is None:
        from aria.ledger.writer import get_default_writer

        writer = get_default_writer()
    return writer.append(build_memory_event(event_type, **fields))
