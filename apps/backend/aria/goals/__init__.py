"""
aria.goals — V3.1 Goal Ownership Foundation.

Planning / control layer that turns a vague request into a structured goal, a
phased roadmap, and a task board, with optional V2-workspace integration and full
Work Ledger tracing. PLANNING ONLY — no execution, no external writes, fixtures and
governance boundaries from V2 fully preserved.
"""
from aria.goals.intake import build_roadmap, run_intake
from aria.goals.models import (
    GoalIntake,
    GoalPlan,
    GoalProgress,
    GoalStatus,
    OwnerType,
    Priority,
    Roadmap,
    RoadmapPhase,
    TaskItem,
    TaskStatus,
)
from aria.goals.sanitize import sanitize_goal_intake, sanitize_text
from aria.goals.service import GoalService, render_goal_brief, render_roadmap
from aria.goals.store import GoalNotFound, GoalStore, TaskNotFound

__all__ = [
    "run_intake",
    "build_roadmap",
    "sanitize_goal_intake",
    "sanitize_text",
    "GoalIntake",
    "GoalPlan",
    "GoalProgress",
    "GoalStatus",
    "OwnerType",
    "Priority",
    "Roadmap",
    "RoadmapPhase",
    "TaskItem",
    "TaskStatus",
    "GoalService",
    "render_goal_brief",
    "render_roadmap",
    "GoalStore",
    "GoalNotFound",
    "TaskNotFound",
]
