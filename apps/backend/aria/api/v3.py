"""
FastAPI V3.1 goal-ownership API (Goal Ownership Foundation).

Localhost pilot only. **Additive** — it does NOT modify the V1 or V2 APIs. It
reuses the V3.1 ``GoalService`` (intake → roadmap → task board) and the V2
``WorkspaceStore``; no planning logic is duplicated here.

Endpoints:
    POST  /api/v3/goals
    GET   /api/v3/goals
    GET   /api/v3/goals/{goal_id}
    GET   /api/v3/goals/{goal_id}/roadmap
    GET   /api/v3/goals/{goal_id}/tasks
    PATCH /api/v3/goals/{goal_id}/tasks/{task_id}
    GET   /api/v3/goals/{goal_id}/progress

Governance (identical posture to V2):
  - PLANNING ONLY — no production execution, no external writes, no connector calls.
  - ``ARIA_USER_ID`` sets the actor label — ATTRIBUTION ONLY, never authentication.
  - errors are typed code + sanitised detail — never raw exception text.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aria.goals import GoalService, GoalStore
from aria.goals.models import TaskStatus
from aria.goals.store import GoalNotFound, TaskNotFound
from aria.llm import resolve_execution_mode
from aria.memory_v2.workspace import WorkspaceStore

_log = logging.getLogger("aria.api.v3")


def actor() -> str:
    """Configurable actor label (ATTRIBUTION ONLY — not authentication)."""
    value = os.getenv("ARIA_USER_ID")
    return value if value and value.strip() else "human:local"


def _build_components():
    mode = resolve_execution_mode().value
    store = GoalStore(execution_mode=mode)
    workspace_store = WorkspaceStore(execution_mode=mode)
    service = GoalService(store, workspace_store=workspace_store, execution_mode=mode, actor=actor())
    return store, workspace_store, service


def _close(*stores) -> None:
    for s in stores:
        try:
            if s is not None:
                s.close()
        except Exception:  # pragma: no cover - defensive
            pass


# ── Request / response models ────────────────────────────────────────────────


class CreateGoalRequest(BaseModel):
    raw_request: str = Field(min_length=1)
    scope: str = "general"
    stakeholders: list[str] = Field(default_factory=list)


class UpdateTaskRequest(BaseModel):
    status: str
    blocked_by: list[str] | None = None
    output_artifact: str | None = None


def _safe_error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error_code": code, "detail": detail})


def _dump(model: Any) -> dict[str, Any]:
    return json.loads(model.model_dump_json())


# ── Router ───────────────────────────────────────────────────────────────────

v3_router = APIRouter(prefix="/api/v3", tags=["v3"])


@v3_router.post("/goals")
def create_goal(body: CreateGoalRequest):
    store, workspace_store, service = _build_components()
    try:
        plan = service.own_goal(
            body.raw_request, scope=body.scope, owner=actor(),
            stakeholders=body.stakeholders,
        )
        return JSONResponse(status_code=201, content={
            "goal": _dump(plan.goal),
            "roadmap": _dump(plan.roadmap),
            "tasks": [_dump(t) for t in plan.tasks],
            "workspace_id": plan.workspace_id,
            "summary": plan.as_summary(),
        })
    except ValueError:
        # e.g. empty request — sanitised, never raw text.
        return _safe_error(400, "invalid_request", "Could not build a goal from this request.")
    except Exception as exc:  # never leak raw text — class only, in body AND logs
        _log.error("v3 create_goal error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not create the goal.")
    finally:
        _close(store, workspace_store)


@v3_router.get("/goals")
def list_goals(status: str | None = None, scope: str | None = None):
    store, workspace_store, service = _build_components()
    try:
        goals = service.list_goals(status=status, scope=scope)
        return {"goals": [_dump(g) for g in goals], "count": len(goals)}
    finally:
        _close(store, workspace_store)


@v3_router.get("/goals/{goal_id}")
def get_goal(goal_id: str):
    store, workspace_store, service = _build_components()
    try:
        goal = service.get_goal(goal_id)
        if goal is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        return _dump(goal)
    finally:
        _close(store, workspace_store)


@v3_router.get("/goals/{goal_id}/roadmap")
def get_roadmap(goal_id: str):
    store, workspace_store, service = _build_components()
    try:
        if service.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        roadmap = service.get_roadmap(goal_id)
        if roadmap is None:
            return _safe_error(404, "roadmap_not_found", "No roadmap for this goal.")
        return _dump(roadmap)
    finally:
        _close(store, workspace_store)


@v3_router.get("/goals/{goal_id}/tasks")
def get_tasks(goal_id: str):
    store, workspace_store, service = _build_components()
    try:
        if service.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        tasks = service.get_tasks(goal_id)
        return {"goal_id": goal_id, "tasks": [_dump(t) for t in tasks], "count": len(tasks)}
    finally:
        _close(store, workspace_store)


@v3_router.patch("/goals/{goal_id}/tasks/{task_id}")
def update_task(goal_id: str, task_id: str, body: UpdateTaskRequest):
    store, workspace_store, service = _build_components()
    try:
        # Validate the status value (sanitised error, never raw).
        try:
            new_status = TaskStatus(body.status)
        except ValueError:
            return _safe_error(400, "invalid_status",
                               f"Unknown task status. Valid: {[s.value for s in TaskStatus]}.")
        # The task must exist AND belong to the goal in the path.
        task = service._store.get_task(task_id)
        if task is None or task.goal_id != goal_id:
            return _safe_error(404, "task_not_found", "Unknown task for this goal.")
        updated = service.update_task_status(
            task_id, new_status, blocked_by=body.blocked_by, output_artifact=body.output_artifact,
        )
        return _dump(updated)
    except (GoalNotFound, TaskNotFound):
        return _safe_error(404, "not_found", "Unknown goal or task.")
    finally:
        _close(store, workspace_store)


@v3_router.get("/goals/{goal_id}/progress")
def get_progress(goal_id: str):
    store, workspace_store, service = _build_components()
    try:
        if service.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        progress = service.get_progress(goal_id, report=True)
        return _dump(progress)
    finally:
        _close(store, workspace_store)


def build_v3_app():
    """Standalone FastAPI app exposing only the V3 router (used by tests/uvicorn)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="ARIA V3 API", version="3.1.0",
                  description="V3.1 goal ownership — localhost pilot, planning only (no execution)")
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_methods=["POST", "GET", "PATCH"], allow_headers=["*"],
    )
    app.include_router(v3_router)
    return app
