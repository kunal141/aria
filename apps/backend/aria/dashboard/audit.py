"""
Work Ledger event construction for the V3.10 manager-dashboard store.

Mirrors the other audit modules: events are built here, enqueued into the dashboard
store's transactional **audit outbox** in the same SQLite transaction as the state
change, and flushed to the Work Ledger — so state and audit can never diverge.
Identifiers (snapshot/roi/proof ids, goal/workspace ids) ride in the sanitised
``metadata`` dict. Nothing here executes work or performs an external action.
"""
from __future__ import annotations

from typing import Any

from aria.ledger import (
    ActorType,
    ApprovalQueueSummarized,
    DashboardSnapshotCreated,
    LedgerEventType,
    RiskSummaryCreated,
    RoiSummaryCreated,
    V3AcceptancePackageCreated,
    V3ProofDemoGenerated,
)
from aria.ledger.events import make_envelope

_EVENT_CLASSES = {
    LedgerEventType.dashboard_snapshot_created:    DashboardSnapshotCreated,
    LedgerEventType.roi_summary_created:           RoiSummaryCreated,
    LedgerEventType.approval_queue_summarized:     ApprovalQueueSummarized,
    LedgerEventType.risk_summary_created:          RiskSummaryCreated,
    LedgerEventType.v3_proof_demo_generated:       V3ProofDemoGenerated,
    LedgerEventType.v3_acceptance_package_created: V3AcceptancePackageCreated,
}


def build_dashboard_event(
    event_type: LedgerEventType,
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType = ActorType.aria,
    correlation_id: str | None = None,
    snapshot_id: str | None = None,
    roi_summary_id: str | None = None,
    proof_id: str | None = None,
    goal_id: str | None = None,
    workspace_id: str | None = None,
    status: str | None = None,
    execution_mode: str | None = None,
    outcome: str | None = None,
):
    meta: dict[str, Any] = {}
    for key, value in (
        ("snapshot_id", snapshot_id),
        ("roi_summary_id", roi_summary_id),
        ("proof_id", proof_id),
        ("goal_id", goal_id),
        ("workspace_id", workspace_id),
        ("status", status),
        ("execution_mode", execution_mode),
    ):
        if value is not None:
            meta[key] = value
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id or snapshot_id or task_id,
        outcome=outcome,
        metadata=meta,
    )
    return _EVENT_CLASSES[event_type](**envelope)
