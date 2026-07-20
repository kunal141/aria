"""Offline proof of ARIA's integrated goal-to-manager-output employee loop.

Run from ``apps/backend``::

    uv run python -m aria.demo.virtual_employee

The proof pins ``offline_mock`` without reading or changing provider credentials, confines all state
to a temporary ``ARIA_DATA_DIR``, intentionally fails the first output quality
check, repairs it, and completes on the second bounded attempt. No network,
provider, external write, deployment, or uncontrolled self-modification occurs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

_ENV = ("ARIA_DATA_DIR", "ARIA_LEDGER_V2_PATH", "ARIA_EXECUTION_MODE", "ARIA_USER_ID")


def _build(writer):
    from aria.employee import EmployeeOrchestratorService, EmployeeRunStore
    from aria.goals import AgentSupervisorService, AgentWorkforceService, GoalService, GoalStore
    from aria.memory_v2.workspace import WorkspaceStore
    from aria.model_routing import ModelRoutingService, ModelRoutingStore
    from aria.runtime_adapters import RuntimeAdapterService, RuntimeAdapterStore

    mode = "offline_mock"
    actor = "human:demo"
    goals = GoalStore(writer=writer, execution_mode=mode)
    workspaces = WorkspaceStore(writer=writer, execution_mode=mode)
    routing_store = ModelRoutingStore(writer=writer, execution_mode=mode)
    adapter_store = RuntimeAdapterStore(writer=writer, execution_mode=mode)
    employee_store = EmployeeRunStore(
        writer=writer, execution_mode=mode, routing_store=routing_store,
        adapter_store=adapter_store, goal_store=goals, workspace_store=workspaces)
    service = EmployeeOrchestratorService(
        employee_store,
        goal_service=GoalService(
            goals, workspace_store=workspaces, execution_mode=mode, actor=actor),
        goal_store=goals,
        workforce_service=AgentWorkforceService(
            goals, workspace_store=workspaces, execution_mode=mode, actor=actor),
        supervisor_service=AgentSupervisorService(
            goals, workspace_store=workspaces, execution_mode=mode, actor=actor),
        routing_service=ModelRoutingService(
            routing_store, execution_mode=mode, actor=actor),
        routing_store=routing_store,
        adapter_service=RuntimeAdapterService(
            adapter_store, workspace_store=workspaces, execution_mode=mode, actor=actor),
        adapter_store=adapter_store,
        workspace_store=workspaces, actor=actor, execution_mode=mode,
    )
    return service, (employee_store, adapter_store, routing_store, workspaces, goals)


def run_demo(write=print, *, keep: bool = False) -> dict[str, Any]:
    saved = {key: os.environ.get(key) for key in _ENV}
    temp = Path(tempfile.mkdtemp(prefix="aria_employee_proof_"))
    data_dir = temp / "aria_data"
    ledger_path = temp / "work_ledger_v2.jsonl"
    os.environ["ARIA_DATA_DIR"] = str(data_dir)
    os.environ["ARIA_LEDGER_V2_PATH"] = str(ledger_path)
    os.environ["ARIA_EXECUTION_MODE"] = "offline_mock"
    os.environ.pop("ARIA_USER_ID", None)

    from aria.employee import default_business_fixture
    from aria.ledger.writer import LedgerWriter, reset_default_writer

    reset_default_writer()
    writer = LedgerWriter(ledger_path)
    stores = ()
    summary: dict[str, Any] = {
        "execution_mode": "offline_mock", "data_dir": str(data_dir),
        "ledger_path": str(ledger_path),
    }
    try:
        service, stores = _build(writer)
        pending = service.run_business_analysis(
            goal_text=("Investigate the notification CTR decline, coordinate the work, "
                       "and produce an evidence-backed manager report."),
            dataset=default_business_fixture(), max_attempts=2,
            intentional_quality_failures=1,
        )
        if pending.run.status.value != "awaiting_approval":
            raise RuntimeError("CompletionApprovalWasNotRequested")
        view = service.approve_completion(pending.run.run_id, actor="human:demo-manager")
        events = []
        if ledger_path.exists():
            events = [json.loads(line) for line in ledger_path.read_text(
                encoding="utf-8").splitlines() if line.strip()]
        summary.update({
            "ok": view.run.status.value == "completed",
            "run_id": view.run.run_id,
            "goal_id": view.run.goal_id,
            "workspace_id": view.run.workspace_id,
            "attempt_statuses": [attempt.status.value for attempt in view.attempts],
            "approval_sequence": ["awaiting_approval", view.run.status.value],
            "repair_failure_codes": [
                code for plan in view.repair_plans for code in plan.failure_codes],
            "quality_score": view.quality_score,
            "selected_provider_id": view.run.selected_provider_id,
            "selected_model_id": view.run.selected_model_id,
            "selected_adapter_id": view.run.selected_adapter_id,
            "receipt_count": len(view.receipt_refs),
            "evidence_refs": view.evidence_refs,
            "estimated_minutes_saved": view.estimated_minutes_saved,
            "ledger_event_count": len(events),
            "correlated_employee_events": sum(
                1 for event in events if event.get("correlation_id") == view.run.run_id),
            "boundary_note": view.boundary_note,
        })
        write("ARIA INTEGRATED VIRTUAL EMPLOYEE PROOF")
        write("goal -> plan -> workforce -> route -> adapter -> evaluate -> repair -> report")
        write(f"status: {view.run.status.value}")
        write(f"attempts: {', '.join(summary['attempt_statuses'])}")
        write(f"repair: {', '.join(summary['repair_failure_codes'])}")
        write(f"quality: {view.quality_score:.2f}")
        write("approval: explicit local manager decision recorded")
        write(f"route: {view.run.selected_provider_id}/{view.run.selected_model_id}")
        write(f"adapter: {view.run.selected_adapter_id} (internal mock only)")
        write(f"receipts: {len(view.receipt_refs)}")
        write(view.boundary_note)
        return summary
    finally:
        for store in stores:
            try:
                store.close()
            except Exception:
                pass
        reset_default_writer()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if keep:
            summary["temp_cleaned"] = False
            summary["temp_dir"] = str(temp)
            write(f"retained proof state: {temp}")
        else:
            shutil.rmtree(temp, ignore_errors=True)
            summary["temp_cleaned"] = not temp.exists()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline ARIA employee proof.")
    parser.add_argument("--keep", action="store_true", help="retain isolated proof state")
    args = parser.parse_args(argv)
    result = run_demo(keep=args.keep)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
