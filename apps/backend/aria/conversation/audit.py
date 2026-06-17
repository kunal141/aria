"""
Work Ledger emission for conversation + memory-governance events (Week 32 §6).

The orchestrator emits only **conversation-flow** events here:
  conversation_started, message_received, workflow_invoked.

Memory governance decisions (approval_requested / approved / rejected) and memory
state transitions (memory_proposed / applied / recalled / …) are emitted by the
**store** (``aria.memory_v2.audit``), so the decision audit fires for any caller —
not just turns that go through the orchestrator. Memory-specific identifiers ride
in the sanitised ``metadata`` dict.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    ConversationStarted,
    LedgerEventType,
    MessageReceived,
    WorkflowInvoked,
)
from aria.ledger.events import make_envelope

_EVENT_CLASSES = {
    LedgerEventType.conversation_started: ConversationStarted,
    LedgerEventType.message_received:     MessageReceived,
    LedgerEventType.workflow_invoked:     WorkflowInvoked,
}


def build_conversation_event(
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


def emit_conversation_event(event_type: LedgerEventType, *, writer=None, **fields) -> bool:
    if writer is None:
        from aria.ledger.writer import get_default_writer

        writer = get_default_writer()
    return writer.append(build_conversation_event(event_type, **fields))
