"""
Dashboard Service (V3.10) — read-only manager view + ROI + final V3 proof.

Aggregates every V3 system into a source-cited manager snapshot, estimates ROI
transparently, summarises the (read-only) approval queue and risk/blocker view, and
generates a deterministic, offline end-to-end V3 proof. It NEVER executes work,
approves anything, activates a skill, or performs an external action.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from aria.dashboard import roi as roi_mod
from aria.dashboard import summary as agg
from aria.dashboard.models import (
    DASHBOARD_BOUNDARY,
    ApprovalQueueSummary,
    ManagerDashboardSnapshot,
    ROISummary,
    RiskSummary,
)
from aria.dashboard.store import DashboardStore


def _now() -> datetime:
    return datetime.now(UTC)


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


class DashboardService:
    def __init__(
        self, store: DashboardStore, *, goal_store: Any = None, skill_store: Any = None,
        awareness_store: Any = None, collab_store: Any = None, routine_store: Any = None,
        action_store: Any = None, workspace_store: Any = None, execution_mode: str | None = None,
        actor: str = "aria",
    ) -> None:
        self._store = store
        self._goals = goal_store
        self._skills = skill_store
        self._awareness = awareness_store
        self._collab = collab_store
        self._routines = routine_store
        self._actions = action_store
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def create_snapshot(self, *, workspace_id: str | None = None, hourly_cost: float | None = None,
                       actor: str | None = None) -> ManagerDashboardSnapshot:
        actor = actor or self._actor
        goal_sum, goal_refs = agg.goal_progress(self._goals)
        agent_sum = agg.agent_workforce(self._goals)
        learn_sum = agg.learning(self._awareness, self._skills)
        collab_sum = agg.collaboration(self._collab)
        routine_sum = agg.routines(self._routines)
        action_sum = agg.actions(self._actions)
        approval = agg.approval_queue(skill_store=self._skills, collab_store=self._collab,
                                      action_store=self._actions, awareness_store=self._awareness)
        risk = agg.risks(goal_store=self._goals, routine_store=self._routines,
                         action_store=self._actions, awareness_store=self._awareness,
                         skill_store=self._skills)
        rc = agg.roi_counts(collab_store=self._collab, routine_store=self._routines,
                            action_store=self._actions, awareness_store=self._awareness,
                            goal_store=self._goals)
        roi = roi_mod.estimate_roi(
            rc["counts"], hourly_cost=hourly_cost, blocked_unsafe_actions=rc["blocked_unsafe_actions"],
            evidence_refs=rc["evidence_refs"], tasks_completed=rc["tasks_completed"],
            drafts_created=rc["drafts_created"], routines_completed=rc["routines_completed"],
            action_previews_created=rc["action_previews_created"],
            approvals_prepared=action_sum.approvals_requested,
        )
        snapshot_id = f"dash-{uuid.uuid4().hex}"
        snap = ManagerDashboardSnapshot(
            snapshot_id=snapshot_id, generated_at=_now(), workspace_id=workspace_id,
            goal_summary=goal_sum,
            task_summary={"total": goal_sum.total_tasks, "completed": goal_sum.completed_tasks,
                          "blocked": goal_sum.blocked_tasks},
            agent_summary=agent_sum, memory_summary=learn_sum,
            skill_summary={"skill_gaps": learn_sum.skill_gaps, "skill_proposals": learn_sum.skill_proposals,
                           "activated": learn_sum.activated_skills, "rejected": learn_sum.rejected_skills},
            collaboration_summary=collab_sum, routine_summary=routine_sum, action_summary=action_sum,
            approval_summary=approval, risk_summary=risk, roi_summary=roi,
            source_refs=_dedupe([snapshot_id] + goal_refs)[:50],
        )
        created = self._store.create_snapshot(snap, actor=actor)
        # Persist ROI + emit the read-only sub-summary events (one snapshot, full audit).
        self._store.create_roi(roi, snapshot_id=snapshot_id, workspace_id=workspace_id, actor=actor)
        self._store.emit_approval_queue(count=approval.count, snapshot_id=snapshot_id,
                                       workspace_id=workspace_id, actor=actor)
        self._store.emit_risk_summary(count=risk.count, high=risk.high_severity, snapshot_id=snapshot_id,
                                     workspace_id=workspace_id, actor=actor)
        self._attach_ws(workspace_id, [f"dashboard_snapshot:{snapshot_id}",
                                       f"roi_summary:{roi.roi_summary_id}"],
                        "dashboard_snapshot_created", actor=actor)
        return created

    def get_snapshot(self, snapshot_id: str) -> ManagerDashboardSnapshot | None:
        return self._store.get_snapshot(snapshot_id)

    def list_snapshots(self) -> list[dict[str, Any]]:
        return self._store.list_snapshots()

    # ── Standalone read-only views ────────────────────────────────────────────

    def approval_queue(self, *, actor: str | None = None) -> ApprovalQueueSummary:
        actor = actor or self._actor
        q = agg.approval_queue(skill_store=self._skills, collab_store=self._collab,
                               action_store=self._actions, awareness_store=self._awareness)
        self._store.emit_approval_queue(count=q.count, actor=actor)
        return q

    def risks(self, *, actor: str | None = None) -> RiskSummary:
        actor = actor or self._actor
        r = agg.risks(goal_store=self._goals, routine_store=self._routines, action_store=self._actions,
                     awareness_store=self._awareness, skill_store=self._skills)
        self._store.emit_risk_summary(count=r.count, high=r.high_severity, actor=actor)
        return r

    def roi(self, *, hourly_cost: float | None = None, workspace_id: str | None = None,
           actor: str | None = None) -> ROISummary:
        actor = actor or self._actor
        rc = agg.roi_counts(collab_store=self._collab, routine_store=self._routines,
                           action_store=self._actions, awareness_store=self._awareness,
                           goal_store=self._goals)
        roi = roi_mod.estimate_roi(
            rc["counts"], hourly_cost=hourly_cost, blocked_unsafe_actions=rc["blocked_unsafe_actions"],
            evidence_refs=rc["evidence_refs"], tasks_completed=rc["tasks_completed"],
            drafts_created=rc["drafts_created"], routines_completed=rc["routines_completed"],
            action_previews_created=rc["action_previews_created"])
        self._store.create_roi(roi, workspace_id=workspace_id, actor=actor)
        self._attach_ws(workspace_id, [f"roi_summary:{roi.roi_summary_id}"], "roi_summary_created",
                        actor=actor)
        return roi

    # ── Final V3 proof (deterministic, offline) ───────────────────────────────

    def generate_proof(self, *, workspace_id: str | None = None, actor: str | None = None
                      ) -> dict[str, Any]:
        actor = actor or self._actor
        from aria.demo.v3_proof import run_v3_proof

        proof = run_v3_proof()                         # offline, isolated temp dir, no pollution
        proof_id = f"proof-{uuid.uuid4().hex}"
        record = self._store.create_proof(
            proof_id=proof_id, summary=proof["summary"], proof_json=json.dumps(proof),
            source_refs=proof.get("source_refs") or [proof_id], workspace_id=workspace_id, actor=actor)
        self._store.emit_acceptance(proof_id=proof_id, workspace_id=workspace_id,
                                   outcome="v3_proof", actor=actor)
        self._attach_ws(workspace_id, [f"v3_proof:{proof_id}"], "v3_proof_demo_generated", actor=actor)
        return record

    def get_proof(self, proof_id: str) -> dict[str, Any] | None:
        return self._store.get_proof(proof_id)

    @staticmethod
    def boundary_note() -> str:
        return DASHBOARD_BOUNDARY

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _attach_ws(self, ws_id: str | None, refs: list[str], status: str, *, actor: str) -> None:
        if self._workspace_store is None or not ws_id or not refs:
            return
        try:
            self._workspace_store.update_workspace(
                ws_id, status=status, add_ledger_refs=list(refs), actor=actor)
        except Exception:  # pragma: no cover - workspace bookkeeping is best-effort
            pass
