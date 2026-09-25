"""Local FastAPI app for the ARIA founder braintrust console."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse

from aria.braintrust.build_review import (
    ApplyAcceptedRequest,
    BuildReviewError,
    BuildReviewManager,
    BuildReviewRequest,
    CancelBuildReviewRequest,
    FindingWaiverRequest,
)
from aria.braintrust.runner import (
    BraintrustManager,
    DebateRequest,
    FounderMessageRequest,
    InvalidContextPathError,
)

STATIC_ROOT = Path(__file__).with_name("static")
manager = BraintrustManager()
build_review_manager = BuildReviewManager()
app = FastAPI(
    title="ARIA Braintrust Console",
    version="1.1.0",
    description="Local strategy debate and isolated Codex-build / Claude-review console.",
)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/build-review", include_in_schema=False)
def build_review_index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "build-review.html")


@app.get("/api/braintrust/health")
def health() -> dict[str, object]:
    return {
        "status": "ready",
        "local_only": True,
        "modes": ["strategy_braintrust", "build_review"],
        "workers": [
            {"id": "claude", "model": "claude-opus-5", "access": "read-only plan"},
            {"id": "codex", "model": "gpt-5.6-sol", "reasoning": "xhigh", "access": "read-only"},
        ],
    }


@app.post("/api/build-review/sessions", status_code=202)
async def create_build_review_session(request: BuildReviewRequest) -> dict[str, object]:
    try:
        session = await build_review_manager.create(request)
    except BuildReviewError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    return {
        "session_id": session.control.session_id,
        "status": session.control.status,
        "next_actor": session.control.next_actor,
        "base_commit": session.control.base_commit,
        "approval_token_path": str(
            build_review_manager.approval_token_path(session.control.session_id)
        ),
    }


@app.get("/api/build-review/sessions/{session_id}")
def get_build_review_session(session_id: str) -> dict[str, object]:
    try:
        session = build_review_manager.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown build-review session") from exc
    return {
        "control": session.control.model_dump(mode="json"),
        "work_order": session.request.model_dump(mode="json"),
        "event_count": len(session.events),
        "events": [event.model_dump(mode="json") for event in session.events],
        "approval_token_path": str(
            build_review_manager.approval_token_path(session.control.session_id)
        ),
    }


@app.get("/api/build-review/sessions/{session_id}/events")
async def stream_build_review_events(
    session_id: str,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    try:
        build_review_manager.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown build-review session") from exc

    async def generate():
        async for event in build_review_manager.events(session_id, after=after):
            payload = event.model_dump_json()
            event_id = "" if event.metadata.get("ephemeral") else f"id: {event.event_id}\n"
            yield f"{event_id}event: {event.kind}\ndata: {payload}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/build-review/sessions/{session_id}/cancel")
async def cancel_build_review_session(
    session_id: str, request: CancelBuildReviewRequest
) -> dict[str, str]:
    try:
        await build_review_manager.cancel(session_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown build-review session") from exc
    except BuildReviewError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    return {"session_id": session_id, "status": "cancelled"}


@app.post("/api/build-review/sessions/{session_id}/apply")
async def apply_build_review_session(
    session_id: str, request: ApplyAcceptedRequest
) -> dict[str, object]:
    try:
        control = await build_review_manager.apply_accepted(session_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown build-review session") from exc
    except BuildReviewError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    return control.model_dump(mode="json")


@app.post("/api/build-review/sessions/{session_id}/waive-p2")
async def waive_build_review_p2(
    session_id: str, request: FindingWaiverRequest
) -> dict[str, object]:
    try:
        control = await build_review_manager.waive_p2(session_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown build-review session") from exc
    except BuildReviewError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    return control.model_dump(mode="json")


@app.post("/api/braintrust/sessions", status_code=202)
async def create_session(request: DebateRequest) -> dict[str, object]:
    try:
        session = await manager.create(request)
    except InvalidContextPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "session_id": session.session_id,
        "status": session.status,
        "rounds": request.rounds,
    }


@app.post("/api/braintrust/sessions/{session_id}/messages", status_code=202)
async def add_founder_message(session_id: str, request: FounderMessageRequest) -> dict[str, str]:
    try:
        disposition = await manager.add_founder_message(session_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown braintrust session") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "session_id": session_id,
        "status": disposition,
        "recipient": request.recipient,
    }


@app.get("/api/braintrust/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, object]:
    try:
        session = manager.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown braintrust session") from exc
    return {
        "session_id": session.session_id,
        "status": session.status,
        "phase": session.current_phase,
        "question": session.request.question,
        "rounds": session.request.rounds,
        "context_paths": session.request.context_paths,
        "event_count": len(session.events),
        "events": [event.model_dump(mode="json") for event in session.events],
    }


@app.get("/api/braintrust/sessions/{session_id}/events")
async def stream_events(
    session_id: str,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    try:
        manager.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown braintrust session") from exc

    async def generate():
        async for event in manager.events(session_id, after=after):
            payload = event.model_dump_json()
            event_id = "" if event.metadata.get("ephemeral") else f"id: {event.event_id}\n"
            yield f"{event_id}event: {event.kind}\ndata: {payload}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/braintrust/sessions/{session_id}/cancel")
async def cancel_session(session_id: str) -> dict[str, str]:
    try:
        await manager.cancel(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown braintrust session") from exc
    return {"session_id": session_id, "status": "cancelled"}


@app.get("/api/braintrust/sessions/{session_id}/export")
def export_session(session_id: str) -> FileResponse:
    try:
        manager.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown braintrust session") from exc
    path = manager.data_dir / f"{session_id}.jsonl"
    return FileResponse(path, media_type="application/x-ndjson", filename=f"{session_id}.jsonl")


@app.get("/api/braintrust/sessions/{session_id}/export.md")
def export_session_markdown(session_id: str) -> Response:
    try:
        content = manager.export_markdown(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown braintrust session") from exc
    return Response(
        content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{session_id}.md"',
        },
    )


@app.get("/api/braintrust/config", include_in_schema=False)
def config() -> dict[str, int]:
    return {
        "max_rounds": 2,
        "max_question_characters": 30_000,
        "max_founder_message_characters": 12_000,
        "max_context_paths": 16,
        "max_follow_ups": 30,
    }


__all__ = ["app", "build_review_manager", "manager"]
