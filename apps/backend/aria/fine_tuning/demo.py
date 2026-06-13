"""
Fine-Tuning Prototype — offline demo (Week 29 Priority 5).

Builds a small, privacy-safe, deterministic dataset of accepted outputs,
runs the REAL Priority-3 exporter over it, snapshots a tamper-evident
manifest, then runs the fine-tuning pipeline end-to-end:

    plan -> offline mock (dry-run) -> register candidate -> evaluate
    -> (request approval if it wins)

Everything happens inside an isolated temp directory. NOTHING is trained,
downloaded, deployed, approved, or activated. The candidate is left in
``evaluated`` / ``awaiting_approval`` only, and the production consumer is
asserted to still have no active model.

PROTOTYPE ONLY. The data here is privacy-safe fixtures, explicitly marked
prototype-only — it is not real Work-Ledger content and proves nothing
about production readiness (which requires 50 accepted examples per skill).

Usage
-----

    cd apps/backend
    uv run python -m aria.fine_tuning.demo
    uv run python -m aria.fine_tuning.demo --keep   # retain tmp dir
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from aria.ledger.reader import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.model_registry import InMemoryModelStore, ModelRegistry, utc_now
from aria.training_data import (
    AcceptAllVerifier,
    DatasetExporter,
    Sensitivity,
    TrainingCandidate,
    canonical_content_hash,
)
from aria.training_data.exporter import ExportConfig
from aria.fine_tuning import FineTuningPipeline


FIXED_TS = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
CONSUMER = "pr_review_skill"


def _sft_candidate(i: int) -> TrainingCandidate:
    """One privacy-safe accepted SFT example (deterministic, unique content)."""
    task_id = f"demo-sft-{i:02d}"
    skill = "pr_review_skill" if i % 2 == 0 else "qa_skill"
    input_text = (
        f"Review PR #{100 + i}: adds a null check to the recommendation ranker "
        f"path number {i}."
    )
    output_text = (
        f"Risk LOW. The null check on branch {i} is correct and guarded; add one "
        f"regression test for the empty-candidates case before merge."
    )
    return TrainingCandidate(
        task_id=task_id,
        skill_name=skill,
        input_text=input_text,
        output_text=output_text,
        sensitivity=Sensitivity.internal,
        allowed_for_training=True,
        provenance=[f"evt-{task_id}-outcome"],
        content_hash=canonical_content_hash(
            task_id=task_id,
            skill_name=skill,
            input_text=input_text,
            output_text=output_text,
            rejected_output=None,
            corrected_output=None,
        ),
        outcome_label="approved",
        created_at=FIXED_TS,
    )


def _dpo_candidate(i: int) -> TrainingCandidate:
    """One privacy-safe DPO preference pair (deterministic, unique content)."""
    task_id = f"demo-dpo-{i:02d}"
    skill = "pr_review_skill"
    input_text = f"Review PR #{200 + i}: refactors the notification batching loop {i}."
    rejected = f"Looks fine to me, ship it (variant {i})."
    corrected = (
        f"Risk MEDIUM (variant {i}). Verify message ordering is preserved under "
        f"the new batch size and add a coverage test before merge."
    )
    return TrainingCandidate(
        task_id=task_id,
        skill_name=skill,
        input_text=input_text,
        output_text=None,
        rejected_output=rejected,
        corrected_output=corrected,
        sensitivity=Sensitivity.internal,
        allowed_for_training=True,
        provenance=[f"evt-{task_id}-correction"],
        content_hash=canonical_content_hash(
            task_id=task_id,
            skill_name=skill,
            input_text=input_text,
            output_text=None,
            rejected_output=rejected,
            corrected_output=corrected,
        ),
        outcome_label=None,
        created_at=FIXED_TS,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fine-Tuning Prototype demo (offline)")
    parser.add_argument("--tmp", type=Path, default=None, help="Directory to use (default: tempdir).")
    parser.add_argument("--keep", action="store_true", help="Keep the demo directory after exit.")
    args = parser.parse_args(argv)

    workdir = args.tmp if args.tmp is not None else Path(tempfile.mkdtemp(prefix="aria_finetune_demo_"))
    workdir.mkdir(parents=True, exist_ok=True)
    export_dir    = workdir / "dataset"
    artifact_root = workdir / "artifacts"
    store_path    = workdir / "registry.jsonl"
    ledger_path   = workdir / "ledger_v2.jsonl"
    export_dir.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)

    # 1. Build privacy-safe fixtures and run the REAL Priority-3 exporter.
    candidates = [_sft_candidate(i) for i in range(8)] + [_dpo_candidate(i) for i in range(2)]
    exporter = DatasetExporter(ExportConfig(export_root=export_dir, verifier=AcceptAllVerifier()))
    report = exporter.export(candidates)
    print("-- Priority-3 dataset export ----------------------------------")
    print(f"  SFT examples: {report.total_sft_examples}   DPO pairs: {report.total_dpo_pairs}")
    print(f"  ready_for_finetuning (production 50/skill bar): {report.ready_for_finetuning}")
    print("  (prototype proceeds on its own lower sufficiency bar; see note below)")

    # 2. Registry wired to a Work Ledger v2 writer + artifact root.
    registry = ModelRegistry(
        store=InMemoryModelStore(persist_path=store_path),
        known_consumers={CONSUMER},
        authorized_approvers={"human:kunal"},
        artifact_root=artifact_root,
        writer=LedgerWriter(ledger_path),
        clock=utc_now,
    )

    # 3. Run the prototype pipeline (dry-run: no artifact written, no training).
    pipeline = FineTuningPipeline(
        registry,
        artifact_root=artifact_root,
        production_consumer=CONSUMER,
        clock=utc_now,
    )
    result = pipeline.run(export_dir, dry_run=True)

    plan = result.plan
    print("\n-- Fine-tuning plan (deterministic) ---------------------------")
    print(f"  training_run_id : {plan.training_run_id}")
    print(f"  base_model      : {plan.base_model}")
    print(f"  method          : {plan.training_method.value}")
    print(f"  examples        : {plan.sft_example_count} SFT / {plan.dpo_pair_count} DPO")
    print(f"  skills          : {', '.join(plan.skills)}")
    print(f"  est. tokens     : {plan.estimated_tokens}")
    print(f"  est. cost (USD) : {plan.estimated_cost_usd}")
    print(f"  risk tier       : {plan.risk_tier.value}   approval_required: {plan.approval_required}")
    print(f"  config_hash     : {plan.config_hash}")

    mock = result.training_result
    print("\n-- Mock training result (offline, no real training) -----------")
    print(f"  status          : {mock.status.value}")
    print(f"  trained_examples: {mock.trained_examples}")
    print(f"  adapter_path    : {mock.adapter_path}")

    ev = result.evaluation
    print("\n-- Candidate vs baseline (offline holdout) --------------------")
    print(f"  dimensions won  : {ev.dimensions_won}/{ev.dimensions_total}")
    print(f"  candidate_wins  : {ev.candidate_wins}")
    print(f"  metric deltas   : {ev.metric_deltas}")

    cand = result.candidate
    active = registry.get_active_model(CONSUMER)
    print("\n-- Registry state ---------------------------------------------")
    print(f"  candidate status   : {cand.status.value}")
    print(f"  approval_requested : {result.approval_requested}")
    print(f"  provider           : {cand.provider.value}  (never served to prod)")
    print(f"  active model       : {active.model_id if active else 'NONE (correct - not activated)'}")

    lifecycle_events = [
        e for e in LedgerReader(v2_path=ledger_path).v2_events()
        if e.event_type.value == "model_lifecycle"
    ]
    print(f"\n-- Work Ledger v2: {len(lifecycle_events)} model_lifecycle events emitted --")
    for e in lifecycle_events:
        print(f"  {e.model_version:8s}  {str(e.from_status):16s} -> {e.to_status}")

    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)
        print("\n(demo directory removed; pass --keep to retain it)")
    else:
        print(f"\n(demo directory retained at {workdir})")

    print()
    print("Prototype only. No real model training or deployment was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
