"""
FastAPI V3 goal-ownership + work-execution API (V3.1 Goal Ownership Foundation +
V3.2 Work Execution Loop).

Localhost pilot only. **Additive** — it does NOT modify the V1 or V2 APIs. It
reuses the V3.1 ``GoalService`` (intake → roadmap → task board), the V3.2
``ExecutionService`` (governed one-step-at-a-time loop), and the V2
``WorkspaceStore``; no planning/execution logic is duplicated here.

Endpoints:
    POST  /api/v3/goals                                  (V3.1)
    GET   /api/v3/goals                                  (V3.1)
    GET   /api/v3/goals/{goal_id}                        (V3.1)
    GET   /api/v3/goals/{goal_id}/roadmap                (V3.1)
    GET   /api/v3/goals/{goal_id}/tasks                  (V3.1)
    PATCH /api/v3/goals/{goal_id}/tasks/{task_id}        (V3.1)
    GET   /api/v3/goals/{goal_id}/progress               (V3.2 execution-aware report)
    POST  /api/v3/goals/{goal_id}/execute-next           (V3.2)
    POST  /api/v3/goals/{goal_id}/clarifications         (V3.2)
    POST  /api/v3/goals/{goal_id}/evidence               (V3.2)
    POST  /api/v3/goals/{goal_id}/agents/plan            (V3.3 dry-run workforce)
    POST  /api/v3/goals/{goal_id}/agents/run-dry         (V3.3)
    GET   /api/v3/goals/{goal_id}/agents                 (V3.3)
    GET   /api/v3/goals/{goal_id}/agents/summary         (V3.3)
    POST  /api/v3/goals/{goal_id}/agents/{assignment_id}/cancel  (V3.3)
    POST  /api/v3/goals/{goal_id}/agents/supervise-plan  (V3.4 governed plan)
    POST  /api/v3/goals/{goal_id}/agents/supervise-run   (V3.4 governed run)
    GET   /api/v3/goals/{goal_id}/agents/supervision     (V3.4)
    POST  /api/v3/goals/{goal_id}/agents/supervision/{run_id}/cancel  (V3.4)
    POST  /api/v3/skills/gaps/detect                     (V3.5 skill evolution)
    POST  /api/v3/skills/proposals                       (V3.5)
    GET   /api/v3/skills/proposals[/{id}]                (V3.5)
    POST  /api/v3/skills/proposals/{id}/spec|test-plan|evaluate|decision|rollback  (V3.5)
    POST  /api/v3/awareness/work-memory/consolidate      (V3.6 work-memory graph)
    GET   /api/v3/awareness/work-memory/nodes[/{id}]     (V3.6)
    POST  /api/v3/awareness/work-memory/nodes/{id}/redact (V3.6)
    GET   /api/v3/awareness/lessons[/{id}]               (V3.6)
    POST  /api/v3/awareness/lessons/{id}/disable         (V3.6)
    POST  /api/v3/awareness/world/sources/register       (V3.6 world awareness)
    GET   /api/v3/awareness/world/sources                (V3.6)
    POST  /api/v3/awareness/world/ingest-fixtures        (V3.6 fixture-only)
    GET   /api/v3/awareness/world/updates|brief          (V3.6)
    POST  /api/v3/awareness/improvements/from-update|from-node  (V3.6 → V3.5 proposal only)
    GET   /api/v3/awareness/improvements                 (V3.6)

Governance (identical posture to V2):
  - PLANNING ONLY — no production execution, no external writes, no connector calls.
    An approval-required task NEVER auto-executes (it becomes ``awaiting_approval``).
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

from aria.awareness import AwarenessService, AwarenessStore, ImprovementBlocked
from aria.awareness.store import AwarenessNotFound
from aria.goals import (
    AgentSupervisorService,
    AgentWorkforceService,
    ExecutionService,
    GoalService,
    GoalStore,
)
from aria.goals.models import TaskStatus
from aria.goals.store import GoalNotFound, TaskNotFound
from aria.llm import resolve_execution_mode
from aria.memory_v2.workspace import WorkspaceStore
from aria.skill_evolution import SkillEvolutionService, SkillStore
from aria.skill_evolution.store import InvalidSkillTransition, SkillNotFound

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


def _build_execution():
    mode = resolve_execution_mode().value
    store = GoalStore(execution_mode=mode)
    workspace_store = WorkspaceStore(execution_mode=mode)
    execution = ExecutionService(store, workspace_store=workspace_store, execution_mode=mode, actor=actor())
    return store, workspace_store, execution


def _build_agents():
    mode = resolve_execution_mode().value
    store = GoalStore(execution_mode=mode)
    workspace_store = WorkspaceStore(execution_mode=mode)
    agents = AgentWorkforceService(store, workspace_store=workspace_store, execution_mode=mode, actor=actor())
    return store, workspace_store, agents


def _build_supervisor():
    mode = resolve_execution_mode().value
    store = GoalStore(execution_mode=mode)
    workspace_store = WorkspaceStore(execution_mode=mode)
    supervisor = AgentSupervisorService(store, workspace_store=workspace_store, execution_mode=mode, actor=actor())
    return store, workspace_store, supervisor


def _build_skills():
    mode = resolve_execution_mode().value
    goal_store = GoalStore(execution_mode=mode)
    skill_store = SkillStore(execution_mode=mode)
    workspace_store = WorkspaceStore(execution_mode=mode)
    skills = SkillEvolutionService(skill_store, goal_store=goal_store, workspace_store=workspace_store,
                                   execution_mode=mode, actor=actor())
    return goal_store, skill_store, workspace_store, skills


def _build_awareness():
    """Build V3.6 work-memory + world-awareness components. The awareness service
    shares the SAME ``SkillStore`` as its V3.5 ``SkillEvolutionService`` so a routed
    improvement's gap is visible to the proposal it creates."""
    mode = resolve_execution_mode().value
    goal_store = GoalStore(execution_mode=mode)
    skill_store = SkillStore(execution_mode=mode)
    workspace_store = WorkspaceStore(execution_mode=mode)
    awareness_store = AwarenessStore(execution_mode=mode)
    skill_service = SkillEvolutionService(skill_store, goal_store=goal_store,
                                          workspace_store=workspace_store, execution_mode=mode,
                                          actor=actor())
    awareness = AwarenessService(awareness_store, goal_store=goal_store, skill_store=skill_store,
                                 skill_service=skill_service, workspace_store=workspace_store,
                                 execution_mode=mode, actor=actor())
    return goal_store, skill_store, workspace_store, awareness_store, awareness


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


class ClarificationAnswerRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    clarification_id: str | None = None


class ProvideEvidenceRequest(BaseModel):
    evidence_refs: list[str] = Field(min_length=1)


class CancelAssignmentRequest(BaseModel):
    reason: str = "cancelled by supervisor"
    killed: bool = False


class DetectGapsRequest(BaseModel):
    goal_id: str = Field(min_length=1)


class CreateSkillProposalRequest(BaseModel):
    gap_id: str = Field(min_length=1)


class SkillDecisionRequest(BaseModel):
    decision: str            # approve | reject


class ConsolidateGoalRequest(BaseModel):
    goal_id: str = Field(min_length=1)


class ImprovementFromUpdateRequest(BaseModel):
    update_id: str = Field(min_length=1)


class ImprovementFromNodeRequest(BaseModel):
    node_id: str = Field(min_length=1)


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
    store, workspace_store, execution = _build_execution()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        return _dump(execution.progress_report(goal_id))
    finally:
        _close(store, workspace_store)


@v3_router.post("/goals/{goal_id}/execute-next")
def execute_next(goal_id: str):
    """Move the goal forward ONE governed planning step. No external writes; an
    approval-required task becomes awaiting_approval (never auto-executed)."""
    store, workspace_store, execution = _build_execution()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        return _dump(execution.execute_next(goal_id))
    except Exception as exc:  # never leak raw text — class only, in body AND logs
        _log.error("v3 execute_next error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not execute the next step.")
    finally:
        _close(store, workspace_store)


@v3_router.post("/goals/{goal_id}/clarifications")
def answer_clarification(goal_id: str, body: ClarificationAnswerRequest):
    store, workspace_store, execution = _build_execution()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        clar = execution.submit_clarification(
            goal_id, body.answers, clarification_id=body.clarification_id,
        )
        return _dump(clar)
    except GoalNotFound:
        return _safe_error(404, "clarification_not_found", "No open clarification for this goal.")
    finally:
        _close(store, workspace_store)


@v3_router.post("/goals/{goal_id}/evidence")
def provide_evidence(goal_id: str, body: ProvideEvidenceRequest):
    """Record human-provided evidence references (ARIA never fabricates evidence)."""
    store, workspace_store, execution = _build_execution()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        refs = execution.provide_evidence(goal_id, body.evidence_refs)
        return {"goal_id": goal_id, "evidence": refs, "count": len(refs)}
    finally:
        _close(store, workspace_store)


# ── V3.3: dynamic agent workforce (DRY-RUN / fixture-first) ──────────────────


@v3_router.post("/goals/{goal_id}/agents/plan")
def plan_agents(goal_id: str):
    """Decompose the goal into a bounded set of specialist agent briefs (planning
    only — no agent process is spawned)."""
    store, workspace_store, agents = _build_agents()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        plan = agents.plan(goal_id)
        return JSONResponse(status_code=201, content={
            "goal_id": goal_id,
            "briefs": [_dump(b) for b in plan.briefs],
            "assignments": [_dump(a) for a in plan.assignments],
            "count": len(plan.briefs),
        })
    except Exception as exc:  # class only, never raw text
        _log.error("v3 plan_agents error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not plan the agent workforce.")
    finally:
        _close(store, workspace_store)


@v3_router.post("/goals/{goal_id}/agents/run-dry")
def run_dry_agents(goal_id: str):
    """Run the planned agents in a deterministic DRY-RUN (no external process / write)
    and return the merged result."""
    store, workspace_store, agents = _build_agents()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        return _dump(agents.run_dry(goal_id))
    except Exception as exc:
        _log.error("v3 run_dry_agents error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not run the agent workforce.")
    finally:
        _close(store, workspace_store)


@v3_router.get("/goals/{goal_id}/agents")
def list_agents(goal_id: str):
    store, workspace_store, agents = _build_agents()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        briefs = agents.get_briefs(goal_id)
        assignments = agents.get_assignments(goal_id)
        return {
            "goal_id": goal_id,
            "briefs": [_dump(b) for b in briefs],
            "assignments": [_dump(a) for a in assignments],
            "count": len(briefs),
        }
    finally:
        _close(store, workspace_store)


@v3_router.get("/goals/{goal_id}/agents/summary")
def agents_summary(goal_id: str):
    store, workspace_store, agents = _build_agents()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        return _dump(agents.summary(goal_id))
    finally:
        _close(store, workspace_store)


@v3_router.post("/goals/{goal_id}/agents/{assignment_id}/cancel")
def cancel_agent(goal_id: str, assignment_id: str, body: CancelAssignmentRequest):
    store, workspace_store, agents = _build_agents()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        a = store.get_agent_assignment(assignment_id)
        if a is None or a.goal_id != goal_id:
            return _safe_error(404, "assignment_not_found", "Unknown assignment for this goal.")
        updated = agents.cancel_assignment(assignment_id, reason=body.reason, killed=body.killed)
        return _dump(updated)
    finally:
        _close(store, workspace_store)


# ── V3.4: agent supervisor + multi-agent governance ─────────────────────────


@v3_router.post("/goals/{goal_id}/agents/supervise-plan")
def supervise_plan(goal_id: str):
    """Build a governed, dependency-ordered, budget-estimated execution plan."""
    store, workspace_store, supervisor = _build_supervisor()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        plan = supervisor.plan(goal_id)
        return JSONResponse(status_code=201, content=_dump(plan))
    except Exception as exc:
        _log.error("v3 supervise_plan error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not build the supervision plan.")
    finally:
        _close(store, workspace_store)


@v3_router.post("/goals/{goal_id}/agents/supervise-run")
def supervise_run(goal_id: str):
    """Run the planned workforce under governance (dependency / budget / risk /
    retry / quality / escalation). Dry-run only — no external execution."""
    store, workspace_store, supervisor = _build_supervisor()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        return _dump(supervisor.run(goal_id))
    except Exception as exc:
        _log.error("v3 supervise_run error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not run supervision.")
    finally:
        _close(store, workspace_store)


@v3_router.get("/goals/{goal_id}/agents/supervision")
def get_supervision(goal_id: str):
    store, workspace_store, supervisor = _build_supervisor()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        return supervisor.get_supervision(goal_id)
    finally:
        _close(store, workspace_store)


@v3_router.post("/goals/{goal_id}/agents/supervision/{run_id}/cancel")
def cancel_supervision(goal_id: str, run_id: str, body: CancelAssignmentRequest):
    store, workspace_store, supervisor = _build_supervisor()
    try:
        if store.get_goal(goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        run = store.get_supervision_run(run_id)
        if run is None or run.goal_id != goal_id:
            return _safe_error(404, "run_not_found", "Unknown supervision run for this goal.")
        return _dump(supervisor.cancel_run(run_id, reason=body.reason))
    finally:
        _close(store, workspace_store)


# ── V3.5: skill evolution engine (governed, approval-gated, no live code) ────


@v3_router.post("/skills/gaps/detect")
def detect_skill_gaps(body: DetectGapsRequest):
    """Detect repeated capability gaps from a goal's record (proposals only)."""
    goal_store, skill_store, workspace_store, skills = _build_skills()
    try:
        if goal_store.get_goal(body.goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        gaps = skills.detect_gaps(body.goal_id)
        return {"goal_id": body.goal_id, "gaps": [_dump(g) for g in gaps], "count": len(gaps)}
    finally:
        _close(goal_store, skill_store, workspace_store)


@v3_router.post("/skills/proposals")
def create_skill_proposal(body: CreateSkillProposalRequest):
    goal_store, skill_store, workspace_store, skills = _build_skills()
    try:
        proposal = skills.propose_skill(body.gap_id)
        return JSONResponse(status_code=201, content=_dump(proposal))
    except SkillNotFound:
        return _safe_error(404, "gap_not_found", "Unknown skill gap.")
    finally:
        _close(goal_store, skill_store, workspace_store)


@v3_router.get("/skills/proposals")
def list_skill_proposals(status: str | None = None):
    goal_store, skill_store, workspace_store, skills = _build_skills()
    try:
        proposals = skill_store.list_proposals(status=status)
        return {"proposals": [_dump(p) for p in proposals], "count": len(proposals)}
    finally:
        _close(goal_store, skill_store, workspace_store)


@v3_router.get("/skills/proposals/{proposal_id}")
def get_skill_proposal(proposal_id: str):
    goal_store, skill_store, workspace_store, skills = _build_skills()
    try:
        return skills.get_proposal_bundle(proposal_id)
    except SkillNotFound:
        return _safe_error(404, "proposal_not_found", "Unknown skill proposal.")
    finally:
        _close(goal_store, skill_store, workspace_store)


def _skill_step(proposal_id: str, fn_name: str, status_code: int = 200):
    goal_store, skill_store, workspace_store, skills = _build_skills()
    try:
        result = getattr(skills, fn_name)(proposal_id)
        return JSONResponse(status_code=status_code, content=_dump(result))
    except SkillNotFound:
        return _safe_error(404, "proposal_not_found", "Unknown skill proposal or missing prerequisite.")
    except InvalidSkillTransition:
        return _safe_error(409, "invalid_transition", "Illegal skill lifecycle transition.")
    except Exception as exc:  # class only, never raw text
        _log.error("v3 skill step error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not complete the skill step.")
    finally:
        _close(goal_store, skill_store, workspace_store)


@v3_router.post("/skills/proposals/{proposal_id}/spec")
def generate_skill_spec(proposal_id: str):
    return _skill_step(proposal_id, "generate_spec", status_code=201)


@v3_router.post("/skills/proposals/{proposal_id}/test-plan")
def generate_skill_test_plan(proposal_id: str):
    return _skill_step(proposal_id, "generate_test_plan", status_code=201)


@v3_router.post("/skills/proposals/{proposal_id}/evaluate")
def evaluate_skill_proposal(proposal_id: str):
    return _skill_step(proposal_id, "evaluate")


@v3_router.post("/skills/proposals/{proposal_id}/decision")
def decide_skill_proposal(proposal_id: str, body: SkillDecisionRequest):
    goal_store, skill_store, workspace_store, skills = _build_skills()
    try:
        if skill_store.get_proposal(proposal_id) is None:
            return _safe_error(404, "proposal_not_found", "Unknown skill proposal.")
        return _dump(skills.decide(proposal_id, body.decision, decided_by=actor()))
    finally:
        _close(goal_store, skill_store, workspace_store)


@v3_router.post("/skills/proposals/{proposal_id}/rollback")
def rollback_skill(proposal_id: str):
    goal_store, skill_store, workspace_store, skills = _build_skills()
    try:
        return _dump(skills.rollback(proposal_id))
    except SkillNotFound:
        return _safe_error(409, "rollback_not_allowed", "Only an activated skill can be rolled back.")
    finally:
        _close(goal_store, skill_store, workspace_store)


# ── V3.6: work-memory graph + world awareness (governed, fixture-first) ──────


@v3_router.post("/awareness/work-memory/consolidate")
def consolidate_work_memory(body: ConsolidateGoalRequest):
    """Consolidate a goal's own work history into the source-linked memory graph
    (nodes + typed edges + reusable lessons). Advisory only."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        if goal_store.get_goal(body.goal_id) is None:
            return _safe_error(404, "goal_not_found", "Unknown goal.")
        result = awareness.consolidate_goal(body.goal_id)
        return JSONResponse(status_code=201, content={
            "goal_id": result.goal_id,
            "nodes": [_dump(n) for n in result.nodes],
            "edges": [_dump(e) for e in result.edges],
            "lessons": [_dump(l) for l in result.lessons],
            "summary": result.as_summary(),
            "boundary_note": result.boundary_note,
        })
    except Exception as exc:  # class only, never raw text
        _log.error("v3 consolidate_work_memory error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not consolidate work memory.")
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.get("/awareness/work-memory/nodes")
def list_work_memory_nodes(node_type: str | None = None, status: str | None = None):
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        nodes = awareness.list_nodes(node_type=node_type, status=status)
        return {"nodes": [_dump(n) for n in nodes], "count": len(nodes)}
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.get("/awareness/work-memory/nodes/{node_id}")
def inspect_work_memory_node(node_id: str):
    """Full provenance for a node — the node, its edges, and the lessons citing it."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        return awareness.inspect_node(node_id)
    except AwarenessNotFound:
        return _safe_error(404, "node_not_found", "Unknown work-memory node.")
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.post("/awareness/work-memory/nodes/{node_id}/redact")
def redact_work_memory_node(node_id: str):
    """Withhold a node's content (privacy/redaction) while preserving the audit row."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        return _dump(awareness.redact_node(node_id))
    except AwarenessNotFound:
        return _safe_error(404, "node_not_found", "Unknown work-memory node.")
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.get("/awareness/lessons")
def list_work_lessons(usable_only: bool = False):
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        lessons = awareness.list_lessons(usable_only=usable_only)
        return {"lessons": [_dump(l) for l in lessons], "count": len(lessons)}
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.get("/awareness/lessons/{lesson_id}")
def get_work_lesson(lesson_id: str):
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        lesson = awareness.get_lesson(lesson_id)
        if lesson is None:
            return _safe_error(404, "lesson_not_found", "Unknown lesson.")
        return _dump(lesson)
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.post("/awareness/lessons/{lesson_id}/disable")
def disable_work_lesson(lesson_id: str):
    """Turn a lesson OFF (it no longer informs recommendations); audit row preserved."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        return _dump(awareness.disable_lesson(lesson_id))
    except AwarenessNotFound:
        return _safe_error(404, "lesson_not_found", "Unknown lesson.")
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.post("/awareness/world/sources/register")
def register_world_sources():
    """Register the allowed FIXTURE sources (idempotent). No live network."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        sources = awareness.register_world_sources()
        return JSONResponse(status_code=201, content={
            "sources": [_dump(s) for s in sources], "count": len(sources)})
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.get("/awareness/world/sources")
def list_world_sources():
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        sources = awareness.list_world_sources()
        return {"sources": [_dump(s) for s in sources], "count": len(sources)}
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.post("/awareness/world/ingest-fixtures")
def ingest_world_fixtures():
    """Ingest the deterministic FIXTURE updates (NO live browsing/network) and score
    each for relevance/risk. High-risk/security advisories escalate to human review."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        updates = awareness.ingest_world()
        return JSONResponse(status_code=201, content={
            "updates": [_dump(u) for u in updates], "count": len(updates)})
    except Exception as exc:  # class only, never raw text
        _log.error("v3 ingest_world_fixtures error (class only): %s", type(exc).__name__)
        return _safe_error(500, "internal_error", "Could not ingest world fixtures.")
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.get("/awareness/world/updates")
def list_world_updates():
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        updates = awareness.list_world_updates()
        return {"updates": [_dump(u) for u in updates], "count": len(updates)}
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.get("/awareness/world/brief")
def world_brief():
    """A source-cited, advisory-only digest of scored world updates."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        return awareness.world_brief()
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.post("/awareness/improvements/from-update")
def propose_improvement_from_update(body: ImprovementFromUpdateRequest):
    """Route a relevant, trusted world update to V3.5 as a skill PROPOSAL (only).
    Low-trust / high-risk / low-relevance updates are refused by governance."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        imp = awareness.propose_improvement_from_update(body.update_id)
        return JSONResponse(status_code=201, content=_dump(imp))
    except AwarenessNotFound:
        return _safe_error(404, "update_not_found", "Unknown world update.")
    except ImprovementBlocked as exc:
        return _safe_error(409, "improvement_blocked", str(exc))
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.post("/awareness/improvements/from-node")
def propose_improvement_from_node(body: ImprovementFromNodeRequest):
    """Route a high-signal, active work-memory node to V3.5 as a skill PROPOSAL (only)."""
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        imp = awareness.propose_improvement_from_node(body.node_id)
        return JSONResponse(status_code=201, content=_dump(imp))
    except AwarenessNotFound:
        return _safe_error(404, "node_not_found", "Unknown work-memory node.")
    except ImprovementBlocked as exc:
        return _safe_error(409, "improvement_blocked", str(exc))
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


@v3_router.get("/awareness/improvements")
def list_improvements():
    goal_store, skill_store, workspace_store, awareness_store, awareness = _build_awareness()
    try:
        improvements = awareness.list_improvements()
        return {"improvements": [_dump(i) for i in improvements], "count": len(improvements)}
    finally:
        _close(goal_store, skill_store, workspace_store, awareness_store)


def build_v3_app():
    """Standalone FastAPI app exposing only the V3 router (used by tests/uvicorn)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="ARIA V3 API", version="3.6.0",
                  description=("V3.1–V3.6 goal ownership + work-execution loop + dry-run agent "
                               "workforce + supervisor/governance + skill evolution engine + "
                               "work-memory graph & world awareness — localhost pilot, "
                               "planning/dry-run/proposal/fixture-first only (no external writes, "
                               "no live connectors, no real agent process, no live code, no live "
                               "browsing/network)"))
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_methods=["POST", "GET", "PATCH"], allow_headers=["*"],
    )
    app.include_router(v3_router)
    return app
