"""
Streaming event generator for the V2 chat message endpoint (Week 33 §2).

Runs one turn through the conversation orchestrator and yields **typed** events.
The transport is newline-delimited JSON (NDJSON): the API serialises each event
dict as one ``{"event": ..., "data": {...}}`` line, and the browser consumes it
via ``fetch()`` + a ``ReadableStream`` reader (NOT ``EventSource``).

Determinism + safety:
  - The turn is executed FULLY (state committed) before any token is streamed, so
    a client disconnect during streaming cannot corrupt session/memory state.
  - Event order is deterministic per decision type (asserted in tests).
  - Errors are redacted (exception class only — never raw text / chain-of-thought).
  - ``approval.required`` only SIGNALS that a proposal awaits a decision; it never
    executes anything (the decision is a separate, explicit endpoint).

Allowed event types (the agreed contract):
    message.started, token, workflow.started, workflow.completed, memory.proposed,
    approval.required, memory.applied, memory.recalled, artifact.created,
    workspace.updated, message.completed, error
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aria.conversation.decision import OrchestratorAction
from aria.conversation.orchestrator import ConversationOrchestrator, OrchestratorTurnResult
from aria.memory_v2.models import ChatSession

# The agreed event-type vocabulary (frontend + backend must match).
EVENT_TYPES = (
    "message.started", "token", "workflow.started", "workflow.completed",
    "memory.proposed", "approval.required", "memory.applied", "memory.recalled",
    "artifact.created", "workspace.updated", "message.completed", "error",
    # Week 34 pilots:
    "pilot.report", "draft.created",
)


def _event(event: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": event, "data": data}


def _tokenize(text: str) -> list[str]:
    """Deterministic word-level chunks, whitespace preserved on the right."""
    if not text:
        return []
    parts = text.split(" ")
    return [p + (" " if i < len(parts) - 1 else "") for i, p in enumerate(parts)]


def _is_serious(result: OrchestratorTurnResult) -> bool:
    """A workspace is created only for meaningful turns — not trivial chit-chat,
    empty input, clarify, or a refused sensitive proposal."""
    action = result.decision.action
    if action is OrchestratorAction.run_workflow:
        return True
    if action is OrchestratorAction.propose_memory and result.proposal is not None:
        return True
    if action is OrchestratorAction.converse and result.citation is not None:
        return True
    return False


def _citation_dict(result: OrchestratorTurnResult) -> dict[str, Any] | None:
    if result.citation is None:
        return None
    return {
        "memory_id": result.citation.memory_id,
        "version": result.citation.version,
        "retrieval_reason": result.citation.retrieval_reason,
        "relevant_fields": result.citation.relevant_fields,
    }


def stream_turn(
    orchestrator: ConversationOrchestrator,
    session: ChatSession,
    text: str,
    *,
    workspace_store: Any = None,
    actor: str = "human:local",
) -> Iterator[dict[str, Any]]:
    """Yield the ordered stream of typed events for one chat turn."""
    yield _event("message.started", {"session_id": session.session_id})

    try:
        result = orchestrator.handle(text, session=session)
    except Exception as exc:  # never leak raw text / chain-of-thought
        yield _event("error", {"error_type": type(exc).__name__, "detail": "redacted"})
        return

    action = result.decision.action

    pilot = result.extras.get("pilot")

    # ── Structural events (deterministic per decision type) ──────────────────
    if action is OrchestratorAction.run_workflow:
        wf = result.workflow_result or {}
        task_type = wf.get("task_type")
        yield _event("workflow.started", {"task_type": task_type})
        yield _event("workflow.completed", {"task_type": task_type})
        if wf.get("skill_output"):
            yield _event("artifact.created", {"artifact_type": task_type})
        if pilot is not None:
            yield _event("pilot.report", {
                "pilot": pilot.pilot.value,
                "title": pilot.report.title,
                "summary": pilot.report.summary,
                "connector_mode": pilot.connector_mode,
                "evidence_references": [e.source for e in pilot.report.evidence_references],
                "memory_citations": pilot.report.memory_citations,
                "boundary": pilot.report.boundary,
                "workspace_id": pilot.workspace_id,
            })
            for d in pilot.report.drafts:
                # Draft is a DATA artifact only — never posted/sent/created.
                yield _event("draft.created", {
                    "draft_id": d.draft_id, "kind": d.kind.value, "title": d.title,
                    "boundary": d.boundary,
                })
    elif action is OrchestratorAction.propose_memory and result.proposal is not None:
        yield _event("memory.proposed", {
            "proposal_id": result.proposal.proposal_id,
            "scope": result.proposal.scope,
            "structured_value": result.proposal.structured_value,
        })
        # Signals only — does NOT execute anything.
        yield _event("approval.required", {
            "proposal_id": result.proposal.proposal_id, "kind": "memory",
        })
    elif action is OrchestratorAction.converse and result.citation is not None:
        yield _event("memory.recalled", _citation_dict(result))

    # ── Persistent workspace for serious turns only ──────────────────────────
    workspace_id: str | None = None
    if pilot is not None and pilot.workspace_id:
        # The pilot already created/updated the workspace (with its report artifact).
        workspace_id = pilot.workspace_id
        yield _event("workspace.updated", {"workspace_id": workspace_id})
    elif workspace_store is not None and _is_serious(result):
        workspace_id = _touch_workspace(workspace_store, session, result, actor)
        yield _event("workspace.updated", {"workspace_id": workspace_id})

    # ── Token stream of the final response ───────────────────────────────────
    for tok in _tokenize(result.response):
        yield _event("token", {"text": tok})

    # ── Terminal event (carries citation + full response + workspace) ────────
    yield _event("message.completed", {
        "decision": action.value,
        "response": result.response,
        "citation": _citation_dict(result),
        "proposal_id": result.proposal.proposal_id if result.proposal else None,
        "refused": result.refused,
        "workspace_id": workspace_id,
    })


def _touch_workspace(workspace_store, session: ChatSession, result, actor: str) -> str:
    """Create-or-reuse the session's workspace and record this turn's references."""
    ws = workspace_store.get_by_session(session.session_id)
    if ws is None:
        ws = workspace_store.create_workspace(
            owner=session.owner, scope=session.scope, session_id=session.session_id,
            correlation_id=session.session_id,
        )
    citation = _citation_dict(result)
    status = result.decision.action.value
    workspace_store.update_workspace(
        ws.workspace_id, status=status,
        add_citation=citation if citation else None,
        final_outcome=status, actor=actor,
    )
    return ws.workspace_id
