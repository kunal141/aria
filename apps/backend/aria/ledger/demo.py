"""
Work Ledger v2 demo.

Runs a fully offline lifecycle that exercises every event type, prints
the ROI-ready metrics summary, and demonstrates backwards compatibility
with the legacy ``work_ledger.jsonl`` and ``evolution_events.jsonl``
formats.

Usage
-----
    uv run python -m aria.ledger.demo
    uv run python -m aria.ledger.demo --tmp /path/to/tmp

No LLM, network, LangSmith, Teams, Jira, or paid API calls are made.
The script writes only inside a temporary directory.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from aria.ledger import (
    ActionTaken,
    ActorType,
    ApprovalRequested,
    Approved,
    ArtifactCreated,
    CorrectionRecorded,
    CostRecorded,
    Failed,
    LedgerMetrics,
    LedgerReader,
    LedgerWriter,
    ModelUsed,
    OutcomeRecorded,
    Rejected,
    Responded,
    Routed,
    SkillInvoked,
    TaskCreated,
)
from aria.ledger.events import ActionTier, RiskLevel, make_envelope


def _write_legacy_task_records(path: Path) -> None:
    """Drop two records in the Week-4 ``work_ledger.jsonl`` schema."""
    legacy = [
        {
            "task_id":        "legacy-task-001",
            "task_type":      "pr_review",
            "routing_reason": "keywords: PR review",
            "timestamp":      "2026-06-04T09:10:01.912418+00:00",
            "error":          None,
            "platform_evidence": None,
            "week":           4,
        },
        {
            "task_id":        "legacy-task-002",
            "task_type":      "kpi",
            "routing_reason": "keywords: kpi metric",
            "timestamp":      "2026-06-04T09:10:01.917211+00:00",
            "error":          "timeout after 30s",
            "platform_evidence": None,
            "week":           4,
        },
    ]
    with path.open("w", encoding="utf-8") as fh:
        for r in legacy:
            fh.write(json.dumps(r) + "\n")


def _write_legacy_evolution_records(path: Path) -> None:
    legacy = [
        {
            "event_type":     "approval",
            "task_id":        "upd-legacy",
            "proposal_id":    None,
            "update_id":      "upd-legacy",
            "component_name": "pr_review_prompt",
            "version":        "1.0.0",
            "timestamp":      "2026-06-09T09:51:58.844250+00:00",
            "actor":          "kunal",
            "outcome":        "approved_canary",
            "detail":         None,
        },
    ]
    with path.open("w", encoding="utf-8") as fh:
        for r in legacy:
            fh.write(json.dumps(r) + "\n")


def _run_full_lifecycle(writer: LedgerWriter) -> None:
    """Append one canonical PR-review lifecycle that exercises every event type."""
    now = datetime.now(timezone.utc)
    task_id = "demo-task-001"
    correlation_id = "demo-corr-001"
    workflow_id = "demo-wf-pr-review"

    def env(actor: str, actor_type: ActorType, **extra) -> dict:
        return make_envelope(
            task_id=task_id, actor=actor, actor_type=actor_type,
            correlation_id=correlation_id, **extra,
        )

    # ── Lifecycle ────────────────────────────────────────────────────────
    writer.append(TaskCreated(**env("aria", ActorType.aria,
        workflow_id=workflow_id, timestamp=now)))
    writer.append(Routed(**env("aria", ActorType.aria,
        timestamp=now + timedelta(milliseconds=50),
        routing_reason="keywords: PR, review, recommendation service")))
    writer.append(SkillInvoked(**env("aria", ActorType.aria,
        timestamp=now + timedelta(milliseconds=80),
        skill_name="pr_review",
        started_at=now + timedelta(milliseconds=80))))

    writer.append(ModelUsed(**env("aria", ActorType.aria,
        timestamp=now + timedelta(milliseconds=120),
        skill_name="pr_review",
        model_name="claude-opus-4-7", model_version="2026-05",
        token_input=2400, token_output=720)))
    writer.append(CostRecorded(**env("aria", ActorType.aria,
        timestamp=now + timedelta(milliseconds=125),
        skill_name="pr_review",
        model_name="claude-opus-4-7",
        estimated_cost=Decimal("0.0612"))))

    writer.append(ArtifactCreated(**env("aria", ActorType.aria,
        timestamp=now + timedelta(milliseconds=180),
        skill_name="pr_review",
        artifact_id="art-pr-review-001",
        component_name="pr_review_prompt", component_version="2.0.0")))

    writer.append(ApprovalRequested(**env("aria", ActorType.aria,
        timestamp=now + timedelta(milliseconds=200),
        approval_id="appr-001",
        action_tier=ActionTier.T4, risk_level=RiskLevel.medium)))
    writer.append(Approved(**env("kunal", ActorType.human,
        timestamp=now + timedelta(seconds=8),
        approval_id="appr-001",
        action_tier=ActionTier.T4, risk_level=RiskLevel.medium)))
    writer.append(ActionTaken(**env("aria", ActorType.aria,
        timestamp=now + timedelta(seconds=9),
        action_tier=ActionTier.T4, risk_level=RiskLevel.medium,
        outcome="comment_posted_on_pr")))

    writer.append(Responded(**env("aria", ActorType.aria,
        timestamp=now + timedelta(seconds=10),
        skill_name="pr_review",
        completed_at=now + timedelta(seconds=10),
        duration_ms=10_000)))

    writer.append(OutcomeRecorded(**env("kunal", ActorType.human,
        timestamp=now + timedelta(minutes=5),
        outcome="approved",
        metadata={"comments": "useful, merged the PR"})))

    # Subagent correction — exercises the future § 28.1 attach point.
    writer.append(CorrectionRecorded(**env(
        "subagent:test_review_agent", ActorType.subagent,
        timestamp=now + timedelta(minutes=6),
        parent_task_id=task_id, workflow_id=workflow_id,
        agent_role="test_review_agent",
        metadata={"correction_kind": "edge_case_added"})))

    # A second task that fails — exercises the failure path / metric.
    fail_task = "demo-task-002"
    writer.append(TaskCreated(**make_envelope(
        task_id=fail_task, actor="aria", actor_type=ActorType.aria,
        timestamp=now)))
    writer.append(SkillInvoked(**make_envelope(
        task_id=fail_task, actor="aria", actor_type=ActorType.aria,
        timestamp=now + timedelta(milliseconds=50),
        skill_name="kpi")))
    writer.append(Failed(**make_envelope(
        task_id=fail_task, actor="aria", actor_type=ActorType.aria,
        timestamp=now + timedelta(seconds=2),
        skill_name="kpi", error="upstream KPI source unavailable")))

    # A rejection — exercises the approval-denominator math.
    third = "demo-task-003"
    writer.append(TaskCreated(**make_envelope(
        task_id=third, actor="aria", actor_type=ActorType.aria,
        timestamp=now)))
    writer.append(ApprovalRequested(**make_envelope(
        task_id=third, actor="aria", actor_type=ActorType.aria,
        timestamp=now + timedelta(milliseconds=400),
        approval_id="appr-002",
        action_tier=ActionTier.T5, risk_level=RiskLevel.high)))
    writer.append(Rejected(**make_envelope(
        task_id=third, actor="kunal", actor_type=ActorType.human,
        timestamp=now + timedelta(seconds=12),
        approval_id="appr-002",
        action_tier=ActionTier.T5, risk_level=RiskLevel.high)))
    writer.append(Responded(**make_envelope(
        task_id=third, actor="aria", actor_type=ActorType.aria,
        timestamp=now + timedelta(seconds=13),
        outcome="action_blocked_by_approver",
        completed_at=now + timedelta(seconds=13))))


def _print_summary(summary) -> None:
    print("\n-- ROI Metrics Summary -----------------------------------------")
    print(f"v2 events          : {summary.v2_event_count}")
    print(f"legacy task records: {summary.legacy_task_count}")
    print(f"legacy evolution   : {summary.legacy_evolution_count}")
    print(f"malformed records  : {summary.malformed_count}")
    print()
    print(f"total tasks completed     : {summary.total_tasks_completed}")
    print(f"tasks by skill            : {summary.tasks_by_skill}")
    print(f"approvals granted/rejected: {summary.approvals_granted}/{summary.approvals_rejected}")
    print(f"approval rate             : {summary.approval_rate}")
    print(f"failure rate              : {summary.failure_rate}")
    print(f"failed / terminal tasks   : {summary.failed_tasks} / {summary.terminal_tasks}")
    print(f"avg time to resolution ms : {summary.avg_time_to_resolution_ms}")
    print(f"estimated cost total      : {summary.estimated_cost_total}")
    print(f"estimated cost / task     : {summary.estimated_cost_per_task}")
    print(f"human intervention rate   : {summary.human_intervention_rate}")
    print(f"artifact count            : {summary.artifact_count}")
    print(f"correction count          : {summary.correction_count}")
    print(f"model usage               : {summary.model_usage_breakdown}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Work Ledger v2 demo")
    parser.add_argument(
        "--tmp", type=Path, default=None,
        help="Optional directory to write demo ledgers into (default: a "
             "tempfile.mkdtemp tree).",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep the demo directory after exit (default: delete).",
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="Emit the dashboard-ready MetricsResponse JSON instead of "
             "the printed summary. Uses the real /api/v1/ledger/metrics "
             "code path against the demo ledgers. No network calls.",
    )
    args = parser.parse_args(argv)

    workdir = args.tmp if args.tmp is not None else Path(tempfile.mkdtemp(
        prefix="aria_ledger_demo_"))
    workdir.mkdir(parents=True, exist_ok=True)

    v2_path     = workdir / "work_ledger_v2.jsonl"
    legacy_task = workdir / "work_ledger.jsonl"
    legacy_evo  = workdir / "evolution_events.jsonl"

    # 1. Plant legacy records to prove the unified reader picks them up.
    _write_legacy_task_records(legacy_task)
    _write_legacy_evolution_records(legacy_evo)

    # 2. Run the v2 lifecycle.
    writer = LedgerWriter(v2_path)
    _run_full_lifecycle(writer)

    # 3. Demonstrate idempotency — re-running the lifecycle MUST NOT
    #    inflate the metrics (writes return False for known event_ids).
    pre_size = len(writer)
    # Replay a couple of events with the same event_ids by reading them
    # back and re-validating.
    reader_self = LedgerReader(v2_path=v2_path)
    for ev in reader_self.v2_events()[:3]:
        writer.append(ev)
    assert len(writer) == pre_size, "idempotency violated"

    # 4. Unified read + metric summary across ALL three sources.
    reader = LedgerReader(
        v2_path=v2_path,
        legacy_task_path=legacy_task,
        legacy_evolution_path=legacy_evo,
    )
    summary = LedgerMetrics(reader.read_all()).summary()

    if args.dashboard:
        # Dashboard-ready JSON — exact same shape the production API
        # returns. Uses the real /api/v1/ledger/metrics code path against
        # the demo ledgers; performs ZERO network / paid API calls.
        from aria.ledger.api import _summary_to_response
        from aria.ledger.api_models import FiltersApplied
        response = _summary_to_response(
            summary, FiltersApplied(),
        )
        # ensure_ascii so the output is identical across platforms /
        # locales for downstream verification.
        print(response.model_dump_json(indent=2))
    else:
        _print_summary(summary)

    if not args.dashboard:
        print(f"\nDemo directory: {workdir}")
    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)
        print("(demo directory removed; pass --keep to retain it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
