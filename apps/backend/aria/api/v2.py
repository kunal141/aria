"""
FastAPI V2 chat / memory / workspace API (Week 33).

Localhost pilot only. Additive — it does NOT modify the existing V1 voice / ledger
APIs. All endpoints REUSE the Week-32 conversation orchestrator + SQLite domain
memory authority + the Week-33 workspace store and approval service; no
conversation/memory logic is duplicated here.

Endpoints:
    POST /api/v2/chat/sessions
    POST /api/v2/chat/sessions/{session_id}/messages          (streamed, NDJSON)
    POST /api/v2/memory/proposals/{proposal_id}/decision
    GET  /api/v2/memory
    GET  /api/v2/memory/{memory_id}/versions
    GET  /api/v2/workspaces/{workspace_id}

Governance:
  - actor is configurable via ``ARIA_USER_ID`` (default ``human:local``) — it is
    ATTRIBUTION ONLY, never authentication.
  - no raw chain-of-thought, no raw exception text (errors are class/code only).
  - no production execution, no external writes (approval records a decision only).
  - Week 31 execution modes + Week 32 memory boundaries are preserved (the API
    drives the same orchestrator/store).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from aria.conversation.approval import AlreadyDecided, ApprovalService, Decision
from aria.conversation.orchestrator import ConversationOrchestrator
from aria.conversation.streaming import stream_turn
from aria.llm import resolve_execution_mode
from aria.memory_v2.store import DomainMemoryStore, MemoryNotFound
from aria.memory_v2.workspace import WorkspaceStore
from aria.pilots import PilotService

_log = logging.getLogger("aria.api.v2")

# NDJSON: one JSON object per line, read by the browser via fetch()+ReadableStream
# (NOT EventSource). The content-type is documented and frozen here.
STREAM_MEDIA_TYPE = "application/x-ndjson"


def actor() -> str:
    """Configurable actor label (ATTRIBUTION ONLY — not authentication)."""
    value = os.getenv("ARIA_USER_ID")
    return value if value and value.strip() else "human:local"


# ── Per-request components (fresh, short-lived) ──────────────────────────────
#
# Each SQLite connection is thread-bound, but FastAPI runs sync endpoints (and
# iterates streaming generators) across threadpool threads. So components are
# built fresh per request/generator — each opens its own connection IN ITS OWN
# THREAD; the SQLite file is the shared, durable state. They bind to the ambient
# ARIA_DATA_DIR at build time (tests redirect it to a tmp dir).


def _build_components():
    mode = resolve_execution_mode().value
    store = DomainMemoryStore(execution_mode=mode)
    workspace_store = WorkspaceStore(execution_mode=mode)
    pilot_service = PilotService(store, workspace_store, execution_mode=mode)
    orchestrator = ConversationOrchestrator(store, execution_mode=mode, pilot_service=pilot_service)
    approval = ApprovalService(orchestrator)
    return store, workspace_store, orchestrator, approval


def _close(*stores) -> None:
    for s in stores:
        try:
            if s is not None:
                s.close()
        except Exception:  # pragma: no cover - defensive
            pass


def reset_components() -> None:
    """No-op (kept for API stability): components are per-request, not singletons."""
    return None


# ── Request / response models ────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    scope: str = "analytics.events"


class CreateSessionResponse(BaseModel):
    session_id: str
    owner: str
    scope: str
    created_at: str


class MessageRequest(BaseModel):
    message: str


class DecisionRequest(BaseModel):
    decision: Decision
    session_id: str | None = None


def _safe_error(status_code: int, code: str, detail: str) -> JSONResponse:
    """Typed error response. ``detail`` is a stable, sanitised string — never raw
    exception text (which can carry secrets / paths)."""
    return JSONResponse(status_code=status_code, content={"error_code": code, "detail": detail})


# ── Router ───────────────────────────────────────────────────────────────────

v2_router = APIRouter(prefix="/api/v2", tags=["v2"])


@v2_router.post("/chat/sessions", response_model=CreateSessionResponse)
def create_session(body: CreateSessionRequest) -> CreateSessionResponse:
    store, workspace_store, orch, _ = _build_components()
    try:
        session = orch.start_session(owner=actor(), scope=body.scope)
        return CreateSessionResponse(
            session_id=session.session_id, owner=session.owner, scope=session.scope,
            created_at=session.created_at.isoformat(),
        )
    finally:
        _close(store, workspace_store)


@v2_router.post("/chat/sessions/{session_id}/messages")
def post_message(session_id: str, body: MessageRequest):
    # Quick same-thread validation: does the session exist?
    store0, ws0, _, _ = _build_components()
    try:
        exists = store0.get_session(session_id) is not None
    finally:
        _close(store0, ws0)
    if not exists:
        return _safe_error(404, "session_not_found", "Unknown session.")

    def _generate():
        # Build components INSIDE the generator so the SQLite connections live in
        # the same thread that iterates the stream.
        store, workspace_store, orch, _ = _build_components()
        try:
            session = store.get_session(session_id)
            if session is None:  # raced away — emit a redacted error, do not corrupt
                yield json.dumps({"event": "error",
                                  "data": {"error_type": "SessionMissing", "detail": "redacted"}}) + "\n"
                return
            for ev in stream_turn(orch, session, body.message,
                                  workspace_store=workspace_store, actor=actor()):
                yield json.dumps(ev) + "\n"
        except Exception as exc:  # never leak raw text — class only, in body AND logs
            _log.error("v2 stream error (class only): %s", type(exc).__name__)
            yield json.dumps({"event": "error",
                              "data": {"error_type": type(exc).__name__, "detail": "redacted"}}) + "\n"
        finally:
            _close(store, workspace_store)

    return StreamingResponse(_generate(), media_type=STREAM_MEDIA_TYPE)


@v2_router.post("/memory/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: str, body: DecisionRequest):
    store, workspace_store, _, approval = _build_components()
    try:
        record = approval.decide_memory(
            proposal_id, body.decision, decided_by=actor(), session_id=body.session_id,
        )
    except MemoryNotFound:
        return _safe_error(404, "proposal_not_found", "Unknown proposal.")
    except AlreadyDecided as exc:
        # Idempotent / safe failure: the decision is not re-applied.
        return _safe_error(409, "already_decided", f"Proposal already {exc.current_status}.")
    finally:
        _close(store, workspace_store)
    return JSONResponse(status_code=200, content=json.loads(record.model_dump_json()))


@v2_router.get("/memory")
def list_memory(scope: str | None = None):
    store, workspace_store, _, _ = _build_components()
    try:
        versions = store.list_active_memories(scope=scope)
        items: list[dict[str, Any]] = []
        for v in versions:
            value = v.approved_value or {}
            items.append({
                "memory_id": v.memory_id,
                "version": v.version,
                "scope": v.scope,
                "table": value.get("table"),
                "field": value.get("field"),
                "mapping": value.get("mapping"),
                "approved_value": value,
                "approver": v.approver,
                "created_at": v.created_at.isoformat(),
                "is_active": v.is_active,
            })
        return {"memory": items, "count": len(items)}
    finally:
        _close(store, workspace_store)


@v2_router.get("/memory/{memory_id}/versions")
def list_memory_versions(memory_id: str):
    store, workspace_store, _, _ = _build_components()
    try:
        versions = store.list_versions(memory_id)
        if not versions:
            return _safe_error(404, "memory_not_found", "Unknown memory.")
        return {
            "memory_id": memory_id,
            "versions": [
                {
                    "version": v.version,
                    "approved_value": v.approved_value,   # None on a tombstone
                    "scope": v.scope,
                    "approver": v.approver,
                    "created_at": v.created_at.isoformat(),
                    "is_active": v.is_active,
                    "is_tombstone": v.is_tombstone,
                    "superseded_by": v.superseded_by,
                    "rollback_target": v.rollback_target,
                }
                for v in versions
            ],
        }
    finally:
        _close(store, workspace_store)


@v2_router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str):
    store, workspace_store, _, _ = _build_components()
    try:
        ws = workspace_store.get_workspace(workspace_id)
    finally:
        _close(store, workspace_store)
    if ws is None:
        return _safe_error(404, "workspace_not_found", "Unknown workspace.")
    # Safe metadata + artifact REFERENCES only (relative refs, never raw paths).
    return {
        "workspace_id": ws.workspace_id,
        "session_id": ws.session_id,
        "task_id": ws.task_id,
        "correlation_id": ws.correlation_id,
        "owner": ws.owner,
        "scope": ws.scope,
        "status": ws.status,
        "artifact_refs": ws.artifact_refs,
        "memory_citations": ws.memory_citations,
        "approval_refs": ws.approval_refs,
        "ledger_refs": ws.ledger_refs,
        "final_outcome": ws.final_outcome,
        "created_at": ws.created_at.isoformat(),
        "updated_at": ws.updated_at.isoformat(),
    }


def build_v2_app():
    """Standalone FastAPI app exposing only the V2 router (used by tests/uvicorn)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="ARIA V2 API", version="2.0.0",
                  description="V2 chat / domain memory / workspace — localhost pilot, read-only/draft-only")
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_methods=["POST", "GET"], allow_headers=["*"],
    )
    app.include_router(v2_router)
    return app
