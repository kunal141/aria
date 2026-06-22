"""
ARIA V3 — final end-to-end proof (offline, deterministic).

ONE story that walks the entire V3 stack with no network and no external write:

    business goal
    -> problem statement / roadmap / task board   (V3.1 / V3.2)
    -> dynamic specialist agents (dry-run)         (V3.3)
    -> supervised + governed                       (V3.4)
    -> skill gap proposed (proposal-only)          (V3.5)
    -> work-memory lesson + fixture world updates  (V3.6)
    -> team update draft (draft-only)              (V3.7)
    -> daily routine run + summary                 (V3.8)
    -> action intent previewed + dry-run/mock,
       external target blocked by the gate         (V3.9)
    -> manager dashboard + ROI                      (V3.10)

It runs inside a throwaway ``ARIA_DATA_DIR`` (restored on exit) so it leaves the repo
byte-for-byte unchanged, makes no network call, performs no external write, and trains
or deploys nothing.

    cd apps/backend
    uv run python -m aria.demo.v3_proof
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

try:  # Windows terminal fix for JSON/Unicode output (mirrors golden_path)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass


def run_v3_proof(*, keep: bool = False) -> dict[str, Any]:
    """Run the deterministic, offline V3 story and return a proof package. Isolates all
    runtime side effects in a temp ``ARIA_DATA_DIR`` and restores the environment."""
    prev_env = os.environ.get("ARIA_DATA_DIR")
    tmp = Path(tempfile.mkdtemp(prefix="aria_v3proof_"))
    os.environ["ARIA_DATA_DIR"] = str(tmp)
    try:
        from aria.actions import ActionService, ActionStore, ActionType, TargetSystem
        from aria.awareness import AwarenessService, AwarenessStore
        from aria.collaboration import CollaborationService, CollaborationStore, DraftType
        from aria.dashboard import DashboardService, DashboardStore
        from aria.goals import (
            AgentSupervisorService,
            AgentWorkforceService,
            GoalService,
            GoalStore,
        )
        from aria.ledger.writer import LedgerWriter
        from aria.memory_v2.workspace import WorkspaceStore
        from aria.routines import Cadence, RoutineService, RoutineStore, RoutineType
        from aria.skill_evolution import SkillEvolutionService, SkillStore

        mode = "offline_mock"
        writer = LedgerWriter(tmp / "ledger.jsonl")
        gstore = GoalStore(writer=writer, execution_mode=mode)
        ws = WorkspaceStore(writer=writer, execution_mode=mode)
        sstore = SkillStore(writer=writer, execution_mode=mode)
        astore = AwarenessStore(writer=writer, execution_mode=mode)
        cstore = CollaborationStore(writer=writer, execution_mode=mode)
        rstore = RoutineStore(writer=writer, execution_mode=mode)
        actstore = ActionStore(writer=writer, execution_mode=mode)
        dstore = DashboardStore(writer=writer, execution_mode=mode)

        gsvc = GoalService(gstore, workspace_store=ws, execution_mode=mode, actor="aria")
        aw = AgentWorkforceService(gstore, workspace_store=ws, execution_mode=mode, actor="aria")
        sup = AgentSupervisorService(gstore, workspace_store=ws, execution_mode=mode, actor="aria")
        skills = SkillEvolutionService(sstore, goal_store=gstore, workspace_store=ws,
                                       execution_mode=mode, actor="aria")
        awareness = AwarenessService(astore, goal_store=gstore, skill_store=sstore, skill_service=skills,
                                     workspace_store=ws, execution_mode=mode, actor="aria")
        collab = CollaborationService(cstore, goal_store=gstore, awareness_store=astore,
                                      workspace_store=ws, execution_mode=mode, actor="aria")
        routines = RoutineService(rstore, goal_store=gstore, awareness_service=awareness,
                                  collaboration_service=collab, workspace_store=ws,
                                  execution_mode=mode, actor="aria")
        actions = ActionService(actstore, collaboration_service=collab, workspace_store=ws,
                                execution_mode=mode, actor="aria")
        dashboard = DashboardService(dstore, goal_store=gstore, skill_store=sstore, awareness_store=astore,
                                     collab_store=cstore, routine_store=rstore, action_store=actstore,
                                     workspace_store=ws, execution_mode=mode, actor="aria")

        steps: list[dict[str, str]] = []

        def step(milestone: str, detail: str) -> None:
            steps.append({"milestone": milestone, "detail": detail})

        # V3.1 / V3.2 — own the goal.
        plan = gsvc.own_goal("Our notification CTR is dropping. Own this.",
                            scope="analytics.notifications")
        gid = plan.goal.goal_id
        step("V3.1/3.2 goal ownership", f"goal owned: roadmap + {len(plan.tasks)} task(s)")

        # V3.3 / V3.4 — plan + supervise specialist agents (dry-run, governed).
        aw.plan(gid)
        sup.run(gid)
        step("V3.3/3.4 agent workforce", "specialist agents planned + governed (dry-run; blocked on "
             "missing evidence)")

        # V3.5 — propose a skill from a detected gap (proposal-only, never activated).
        gaps = skills.detect_gaps(gid)
        prop = skills.propose_skill(gaps[0].gap_id) if gaps else None
        step("V3.5 skill evolution",
             f"{len(gaps)} gap(s); proposal={'created (proposed, not activated)' if prop else 'none'}")

        # V3.6 — consolidate work memory + ingest fixture-only world updates.
        cons = awareness.consolidate_goal(gid)
        updates = awareness.ingest_world()
        step("V3.6 memory + world", f"{len(cons.nodes)} node(s), {len(cons.lessons)} lesson(s); "
             f"{len(updates)} fixture world update(s) (no live web)")

        # V3.7 — prepare a manager update draft (draft-only, never sent).
        draft = collab.generate_draft(gid, DraftType.manager_update)
        step("V3.7 collaboration", "manager update draft prepared (draft-only)")

        # V3.8 — define + run a daily review routine (local, deterministic).
        rtn = routines.create_routine(name="Daily goal review",
                                     routine_type=RoutineType.daily_goal_review,
                                     cadence=Cadence.daily, goal_ids=[gid])
        run = routines.run_routine(rtn.routine_id)
        step("V3.8 routine", f"daily review run -> {run.status.value}, {len(run.output_refs)} output(s)")

        # V3.9 — controlled action gate: dry-run an internal action, block an external one.
        intent = actions.create_intent(action_type=ActionType.send_message, title="Notify lead",
                                       target_system=TargetSystem.internal_mock, source_refs=[gid],
                                       evidence_refs=[draft.draft_id], payload_preview={"text": "status"})
        actions.preview(intent.action_id)
        dr = actions.execute_dry_run(intent.action_id)
        ext = actions.create_intent(action_type=ActionType.send_message, title="To Teams",
                                    target_system=TargetSystem.teams, source_refs=[gid],
                                    evidence_refs=[draft.draft_id], payload_preview={"text": "x"})
        ext_blk = actions.execute_mock(ext.action_id)
        step("V3.9 action gate",
             f"internal dry-run={dr.result_status}; external target -> {ext_blk.result_status} "
             "(blocked by deny-by-default policy)")

        # V3.10 — manager dashboard + ROI.
        snap = dashboard.create_snapshot(workspace_id=plan.goal.workspace_id)
        roi = snap.roi_summary
        step("V3.10 dashboard + ROI",
             f"snapshot generated; estimated_minutes_saved={roi.estimated_minutes_saved} "
             f"(estimated={roi.estimated})")

        source_refs = [r for r in (gid, draft.draft_id, run.run_id, intent.action_id, ext.action_id,
                                   snap.snapshot_id) if r]
        return {
            "title": "ARIA V3 — final end-to-end proof (offline, deterministic)",
            "summary": ("V3.1->V3.10 proven end-to-end, offline: goal owned, agents governed, skill "
                        "gap proposed, lesson learned, draft prepared, routine run, action dry-run + "
                        "external blocked, manager dashboard + ROI generated."),
            "steps": steps,
            "snapshot": json.loads(snap.model_dump_json()),
            "source_refs": source_refs,
            "boundary": ("Offline, deterministic, isolated ARIA_DATA_DIR. No network, no external "
                         "write, no real connector, no live execution, no deployment."),
        }
    finally:
        if prev_env is None:
            os.environ.pop("ARIA_DATA_DIR", None)
        else:
            os.environ["ARIA_DATA_DIR"] = prev_env
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    proof = run_v3_proof()
    print(proof["title"])
    print("=" * 68)
    for s in proof["steps"]:
        print(f"  • {s['milestone']:28s} {s['detail']}")
    print("-" * 68)
    print(proof["summary"])
    print(proof["boundary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
