"""
aria.dashboard — V3.10 Manager Dashboard + ROI + Final V3 Proof.

A READ-ONLY aggregation layer over every V3 system (goals, tasks, agents, supervision,
skill evolution, work memory/world awareness, collaboration, routines, controlled
actions). It lets a manager inspect ARIA like an employee — what it worked on, learned,
needs, risks, and the value it produced — plus a transparent ESTIMATED ROI and a
deterministic, offline end-to-end V3 proof.

V3.10 is visibility, control, proof, ROI, and acceptance — NOT more autonomy. Nothing
here executes work, approves anything, activates a skill, or performs an external
action.

A SEPARATE package — importing it never drags in V1 LLM skills, and importing a V1
skill never loads this layer.
"""
from aria.dashboard.models import (
    DASHBOARD_BOUNDARY,
    ActionSummary,
    AgentWorkforceSummary,
    ApprovalQueueItem,
    ApprovalQueueSummary,
    CollaborationSummary,
    GoalProgressSummary,
    LearningSummary,
    ManagerDashboardSnapshot,
    RiskItem,
    RiskSummary,
    ROISummary,
    RoutineSummary,
)
from aria.dashboard.roi import MINUTES_SAVED, estimate_roi
from aria.dashboard.service import DashboardService
from aria.dashboard.store import (
    DashboardIntegrityError,
    DashboardNotFound,
    DashboardSecurityError,
    DashboardStore,
)

__all__ = [
    "DashboardService",
    "DashboardStore",
    "DashboardNotFound",
    "DashboardSecurityError",
    "DashboardIntegrityError",
    "estimate_roi",
    "MINUTES_SAVED",
    "ManagerDashboardSnapshot",
    "GoalProgressSummary",
    "AgentWorkforceSummary",
    "LearningSummary",
    "CollaborationSummary",
    "RoutineSummary",
    "ActionSummary",
    "ApprovalQueueItem",
    "ApprovalQueueSummary",
    "RiskItem",
    "RiskSummary",
    "ROISummary",
    "DASHBOARD_BOUNDARY",
]
