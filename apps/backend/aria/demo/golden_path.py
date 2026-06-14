"""
Golden end-to-end demo — Week 30 Launch Readiness (offline, deterministic).

ONE command that walks the whole ARIA loop with no paid API call and no
network:

    request -> routing -> skill -> evidence gate -> artifact
            -> Work Ledger v2 -> ROI metrics

Run it from the backend directory:

    cd apps/backend
    uv run python -m aria.demo.golden_path

What it does (all local, all offline):

  1. Forces a key-gated provider with NO key, so every skill takes its
     deterministic ``has_llm() is False`` mock path. A guard aborts the run
     if any provider key is still visible — a paid call must be impossible.
  2. Isolates the Work Ledger (v2 + legacy) into a throwaway temp directory,
     so the demo never touches the real gitignored runtime ledgers.
  3. LIVE: invokes the real ``aria_graph`` on four representative requests
     (PR review, KPI, CI/CD, Jira). This exercises real intake -> keyword
     routing -> real skill (mock output) -> evidence gate -> respond, and
     each run writes a real ``Responded`` event to the isolated v2 ledger.
  4. SEEDED: appends a representative *governed* lifecycle using the real
     typed v2 events — an approval-granted task, an approval-rejected task,
     a terminal failure, and a rollback/correction task. These demonstrate
     the approval path, the failure path, and the rollback/evolution proof
     that the live graph's terminal-only v2 mirror does not emit on its own.
  5. Aggregates everything through the real ``LedgerReader`` ->
     ``LedgerMetrics.summary()`` and prints the ROI snapshot the dashboard
     consumes.

Nothing here is production code. No model is trained, served, or deployed.
The temp ledger is deleted on exit (pass ``--keep`` to inspect it).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

try:  # Windows terminal fix for JSON/Unicode output (mirrors main.py)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - reconfigure missing on exotic stdouts
    pass


# Every provider key has_llm() consults. We strip ALL of them after dotenv so
# the offline guarantee does not depend on which provider .env happens to set.
_PROVIDER_KEY_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "MOONSHOT_API_KEY",
    "DASHSCOPE_API_KEY",
)

_BAR = "=" * 68
_RULE = "-" * 68


def _force_offline() -> None:
    """
    Make a paid call impossible, then prove it.

    Force a key-gated provider (``anthropic``) and import config so its
    ``load_dotenv()`` runs, THEN pop every provider key. ``has_llm()`` reads
    ``os.environ`` live, so with the key gone it returns False and every skill
    takes its deterministic mock path. We re-assert the provider afterwards
    because .env may have set ``LLM_PROVIDER=ollama`` (which is always "have
    llm" and would skip the mock path).
    """
    os.environ["LLM_PROVIDER"] = "anthropic"
    import aria.config  # noqa: F401  — import triggers load_dotenv()

    for var in _PROVIDER_KEY_VARS:
        os.environ.pop(var, None)
    os.environ.pop("LANGCHAIN_API_KEY", None)
    os.environ.pop("LANGSMITH_API_KEY", None)
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LLM_PROVIDER"] = "anthropic"  # re-assert after dotenv

    from aria.config import has_llm

    if has_llm():
        raise SystemExit(
            "OFFLINE GUARD FAILED: a provider key is still visible after "
            "stripping. Aborting to avoid a paid API call."
        )


# ── Live graph runs ────────────────────────────────────────────────────────────

# Four representative requests, each routing (by keyword, no LLM) to a skill
# with a deterministic offline mock. Jira exercises the real T4 approval gate;
# KPI and CI/CD exercise the Platform-Intelligence evidence gate.
_LIVE_INPUTS = [
    "Review my PR for the recommendation-service ranking change",
    "Our notification-service CTR dropped 18% this week, can you investigate?",
    "The CI/CD pipeline is failing on the deploy step for notification-service",
    "Create a Jira ticket for the notification-service push bug",
]

_WITHHELD_MARKERS = ("[EVIDENCE UNAVAILABLE", "[RESPONSE WITHHELD")


def _blank_state(raw_input: str) -> dict:
    """The ARIAState init dict, identical in shape to main.py's invoke."""
    return {
        "task_id": "",
        "raw_input": raw_input,
        "task_type": None,
        "task_status": "pending",
        "routing_reason": None,
        "steps_completed": [],
        "skill_name": None,
        "skill_output": None,
        "response": None,
        "messages": [],
        "error": None,
    }


def _run_live() -> None:
    from aria.graph import aria_graph

    print(_BAR)
    print("STAGE 1 — LIVE graph runs (real routing + real skill, offline mock)")
    print(_BAR)
    for raw in _LIVE_INPUTS:
        result = aria_graph.invoke(_blank_state(raw))
        response = result.get("response") or ""
        withheld = any(m in response for m in _WITHHELD_MARKERS)
        first_line = response.strip().splitlines()[0] if response.strip() else "(empty)"
        print(f"\nINPUT   : {raw}")
        print(f"TYPE    : {result.get('task_type')}")
        print(f"TRAIL   : {result.get('steps_completed')}")
        print(f"SKILL   : {result.get('skill_name', '-')}")
        print(f"GATE    : {'WITHHELD (evidence gate fired)' if withheld else 'surfaced'}")
        print(f"ARTIFACT: {first_line[:88]}")
    print(f"\n{_RULE}")
    print("Each live run wrote one real `Responded` event to the isolated v2 ledger.")
    print("(The live graph mirrors only the terminal event today; the full per-event")
    print(" governance taxonomy is shown in STAGE 2 with real typed events.)")


# ── Seeded governed lifecycle (representative, real typed events) ───────────────

_BASE_TS = datetime(2026, 1, 2, 9, 0, 0, tzinfo=timezone.utc)


def _ts(seconds: int) -> datetime:
    return _BASE_TS + timedelta(seconds=seconds)


def _seed_governed(writer) -> None:
    """
    Append a representative governed lifecycle using the real typed v2 events.

    These are clearly-labelled *seeded* records (deterministic ids + UTC
    timestamps) — they demonstrate the approval, failure, and rollback paths
    the metrics aggregate. No values here are invented ROI numbers; they are
    ordinary domain events that the same ``LedgerMetrics`` counts.
    """
    from aria.ledger.events import (
        ActionTaken,
        ActionTier,
        ActorType,
        ApprovalRequested,
        Approved,
        ArtifactCreated,
        CorrectionRecorded,
        CostRecorded,
        Failed,
        ModelLifecycleEvent,
        ModelUsed,
        OutcomeRecorded,
        Rejected,
        Responded,
        Routed,
        RiskLevel,
        SkillInvoked,
        TaskCreated,
        make_envelope,
    )

    def env(task_id: str, seq: int, actor: str, actor_type: ActorType, **extra):
        return make_envelope(
            task_id=task_id,
            correlation_id=task_id,
            event_id=f"seed-{task_id}-{seq:02d}",
            timestamp=_ts(seq),
            actor=actor,
            actor_type=actor_type,
            **extra,
        )

    A, H = ActorType.aria, ActorType.human

    events = [
        # ── Approval-GRANTED task: full happy governed lifecycle (T4) ──────────
        TaskCreated(**env("gold-approval", 0, "aria", A)),
        Routed(**env("gold-approval", 1, "aria", A), routing_reason="keyword match -> jira"),
        SkillInvoked(**env("gold-approval", 2, "aria", A, skill_name="jira")),
        ModelUsed(**env("gold-approval", 3, "aria", A, model_name="claude-haiku-4-5")),
        CostRecorded(**env("gold-approval", 4, "aria", A,
                           estimated_cost=Decimal("0.0117"),
                           token_input=1200, token_output=300)),
        ArtifactCreated(**env("gold-approval", 5, "aria", A, artifact_id="art-gold-approval")),
        ApprovalRequested(**env("gold-approval", 6, "aria", A,
                                approval_id="appr-gold-approval",
                                action_tier=ActionTier.T4, risk_level=RiskLevel.medium)),
        Approved(**env("gold-approval", 7, "human:kunal", H, approval_id="appr-gold-approval")),
        ActionTaken(**env("gold-approval", 8, "aria", A, action_tier=ActionTier.T4)),
        OutcomeRecorded(**env("gold-approval", 9, "aria", A, outcome="approved")),
        Responded(**env("gold-approval", 10, "aria", A)),

        # ── Approval-REJECTED task: governed stop, no action taken ─────────────
        TaskCreated(**env("gold-rejected", 20, "aria", A)),
        Routed(**env("gold-rejected", 21, "aria", A), routing_reason="keyword match -> jira"),
        SkillInvoked(**env("gold-rejected", 22, "aria", A, skill_name="jira")),
        ArtifactCreated(**env("gold-rejected", 23, "aria", A, artifact_id="art-gold-rejected")),
        ApprovalRequested(**env("gold-rejected", 24, "aria", A,
                                approval_id="appr-gold-rejected",
                                action_tier=ActionTier.T4, risk_level=RiskLevel.high)),
        Rejected(**env("gold-rejected", 25, "human:kunal", H, approval_id="appr-gold-rejected")),

        # ── FAILURE path: terminal failure, no Responded ───────────────────────
        TaskCreated(**env("gold-failure", 40, "aria", A)),
        Routed(**env("gold-failure", 41, "aria", A), routing_reason="keyword match -> ci_cd"),
        SkillInvoked(**env("gold-failure", 42, "aria", A, skill_name="ci_cd")),
        Failed(**env("gold-failure", 43, "aria", A,
                     error="upstream build artifact missing; deterministic demo failure path")),

        # ── ROLLBACK / evolution proof: correction + rolled_back outcome ───────
        TaskCreated(**env("gold-rollback", 60, "aria", A)),
        Routed(**env("gold-rollback", 61, "aria", A), routing_reason="evolution canary review"),
        SkillInvoked(**env("gold-rollback", 62, "aria", A, skill_name="evolution")),
        ArtifactCreated(**env("gold-rollback", 63, "aria", A, artifact_id="art-gold-rollback")),
        CorrectionRecorded(**env("gold-rollback", 64, "human:kunal", H)),
        OutcomeRecorded(**env("gold-rollback", 65, "aria", A, outcome="rolled_back")),
        Responded(**env("gold-rollback", 66, "aria", A)),
        ModelLifecycleEvent(**env("gold-rollback", 67, "aria", A,
                                  model_name="qwen2.5-coder-7b-aria-pr",
                                  model_version="0.1.0-proto",
                                  production_consumer="pr_review",
                                  from_status="canary", to_status="rolled_back")),
    ]

    print(f"\n{_BAR}")
    print("STAGE 2 — SEEDED governed lifecycle (real typed v2 events)")
    print(_BAR)
    for ev in events:
        writer.append(ev)
    print(f"Appended {len(events)} typed events across 4 governed tasks:")
    print("  gold-approval  — T4 approval GRANTED -> action taken -> completed")
    print("  gold-rejected  — T4 approval REJECTED -> action withheld (non-terminal)")
    print("  gold-failure   — terminal FAILURE (no response)")
    print("  gold-rollback  — correction + rolled_back outcome + model rollback")


# ── ROI aggregation ────────────────────────────────────────────────────────────


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(f"not JSON-serialisable: {type(o)!r}")


def _report_roi(v2_path: Path, legacy_task_path: Path, legacy_evo_path: Path) -> None:
    from aria.ledger.reader import LedgerReader
    from aria.ledger.metrics import LedgerMetrics

    records = LedgerReader(
        v2_path=v2_path,
        legacy_task_path=legacy_task_path,
        legacy_evolution_path=legacy_evo_path,
    ).read_all()
    summary = LedgerMetrics(records).summary()

    print(f"\n{_BAR}")
    print("STAGE 3 — ROI snapshot (real LedgerReader -> LedgerMetrics.summary())")
    print(_BAR)
    print(f"tasks completed         : {summary.total_tasks_completed}")
    print(f"tasks by skill          : {summary.tasks_by_skill}")
    print(f"approvals granted/reject : {summary.approvals_granted} / {summary.approvals_rejected}")
    print(f"approval_rate           : {summary.approval_rate}")
    print(f"failed / terminal tasks : {summary.failed_tasks} / {summary.terminal_tasks}")
    print(f"failure_rate            : {summary.failure_rate}")
    print(f"artifacts created       : {summary.artifact_count}")
    print(f"corrections (DPO signal): {summary.correction_count}")
    print(f"cost total / per task   : {summary.estimated_cost_total} / {summary.estimated_cost_per_task}")
    print(f"human intervention rate : {summary.human_intervention_rate}")
    print(f"model usage             : {summary.model_usage_breakdown}")
    print(f"v2 events / legacy / bad : {summary.v2_event_count} / "
          f"{summary.legacy_task_count} / {summary.malformed_count}")
    print(f"\n{_RULE}")
    print("Full MetricsSummary (the GET /api/v1/ledger/metrics payload shape):")
    print(json.dumps(dataclasses.asdict(summary), indent=2, default=_json_default))


# ── Entry point ────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m aria.demo.golden_path",
        description="Offline, deterministic end-to-end ARIA demo (no paid API).",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="keep the temp ledger directory instead of deleting it on exit",
    )
    args = parser.parse_args(argv)

    _force_offline()

    tmp = Path(tempfile.mkdtemp(prefix="aria_golden_"))
    v2_path = tmp / "work_ledger_v2.jsonl"
    legacy_task_path = tmp / "work_ledger.jsonl"
    legacy_evo_path = tmp / "evolution_events.jsonl"

    from aria.ledger.writer import LedgerWriter, configure_default_writer, reset_default_writer

    writer = LedgerWriter(v2_path)
    configure_default_writer(writer)

    # Redirect the legacy log_task / evolution writers off the real gitignored
    # runtime files so the demo is fully self-contained.
    import aria.work_ledger as wl
    wl.LEDGER_FILE = legacy_task_path
    wl.EVOLUTION_EVENTS_FILE = legacy_evo_path

    print(_BAR)
    print("ARIA — GOLDEN PATH (Week 30 Launch Readiness)")
    print("offline · deterministic · local-only · no paid API, no network")
    print(f"isolated ledger: {tmp}")
    print(_BAR)

    try:
        _run_live()
        _seed_governed(writer)
        _report_roi(v2_path, legacy_task_path, legacy_evo_path)
    finally:
        reset_default_writer()
        if args.keep:
            print(f"\n[--keep] temp ledger retained at: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_BAR}")
    print("Prototype / demonstration only. No paid API call, no network call,")
    print("no model training, and no deployment occurred during this run.")
    print(_BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
