"""
Dataset Export Prototype — offline demo.

Runs the full pipeline against hand-crafted typed candidates inside an
isolated temporary directory, prints the typed dataset report, and
exits.

PROTOTYPE ONLY. No network, no LLM, no fine-tuning. The demo's last
line of output explicitly states "Prototype only. No model training
was performed." to make this unmistakable in logs.

Usage
-----

    cd apps/backend
    uv run python -m aria.training_data.demo
    uv run python -m aria.training_data.demo --keep   # retain tmp dir
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from aria.training_data import (
    AcceptAllVerifier,
    DatasetExporter,
    Sensitivity,
    TrainingCandidate,
    canonical_content_hash,
)
from aria.training_data.exporter import ExportConfig
from aria.training_data.quality import QualityPolicy


def _candidate(**fields) -> TrainingCandidate:
    """
    Build a candidate, computing its ``content_hash`` from the canonical
    content so the integrity invariant holds (no fabricated hashes).
    """
    fields.setdefault("input_text", None)
    fields.setdefault("output_text", None)
    fields.setdefault("rejected_output", None)
    fields.setdefault("corrected_output", None)
    fields["content_hash"] = canonical_content_hash(
        task_id=fields["task_id"],
        skill_name=fields["skill_name"],
        input_text=fields["input_text"],
        output_text=fields["output_text"],
        rejected_output=fields["rejected_output"],
        corrected_output=fields["corrected_output"],
    )
    return TrainingCandidate(**fields)


def _sample_candidates() -> list[TrainingCandidate]:
    """Hand-crafted typed candidates exercising every pipeline branch."""
    ts = datetime(2026, 6, 12, 9, 0, 0, tzinfo=timezone.utc)
    return [
        # 1. Valid SFT — approved outcome, clean content, public.
        _candidate(
            task_id="task-pr-ok-001",
            skill_name="pr_review",
            input_text="Review this PR for the recommendation service.",
            output_text=(
                "Risk MEDIUM. Add a regression test covering the empty-"
                "candidate path; otherwise looks good."
            ),
            artifact_id="art-001",
            sensitivity=Sensitivity.public,
            allowed_for_training=True,
            provenance=["evt-skill-001", "evt-outcome-001"],
            outcome_label="approved",
            created_at=ts,
        ),
        # 2. Valid DPO — explicit rejected + corrected.
        _candidate(
            task_id="task-pr-dpo-002",
            skill_name="pr_review",
            input_text="Review this PR for the recommendation service.",
            rejected_output="Looks fine, ship it.",
            corrected_output=(
                "Risk MEDIUM — needs a regression test for the empty-"
                "candidate code path before deploy."
            ),
            artifact_id="art-002",
            sensitivity=Sensitivity.public,
            allowed_for_training=True,
            provenance=["evt-correction-002"],
            created_at=ts,
        ),
        # 3. Privacy rejection — output contains a credential pattern.
        _candidate(
            task_id="task-leak-003",
            skill_name="ci_cd",
            input_text="Help debug this CI failure.",
            output_text=(
                "Add the token sk-1234567890abcdef to the env and rerun."
            ),
            sensitivity=Sensitivity.public,
            allowed_for_training=True,
            provenance=["evt-skill-003"],
            outcome_label="approved",
            created_at=ts,
        ),
        # 4. Quality rejection — output below minimum length.
        _candidate(
            task_id="task-short-004",
            skill_name="pr_review",
            input_text="Quick review please.",
            output_text="ok",
            sensitivity=Sensitivity.public,
            allowed_for_training=True,
            provenance=["evt-skill-004"],
            outcome_label="approved",
            created_at=ts,
        ),
        # 5. Sensitivity rejection — confidential is NEVER trained on.
        _candidate(
            task_id="task-conf-005",
            skill_name="pr_review",
            input_text="Internal-only finance review.",
            output_text="Detailed safe finance feedback.",
            sensitivity=Sensitivity.confidential,
            allowed_for_training=False,
            provenance=["evt-skill-005"],
            outcome_label="approved",
            created_at=ts,
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dataset Export Prototype demo")
    parser.add_argument(
        "--tmp", type=Path, default=None,
        help="Optional directory to write the export into (default: "
             "tempfile.mkdtemp tree).",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep the demo directory after exit (default: delete).",
    )
    args = parser.parse_args(argv)

    workdir = args.tmp if args.tmp is not None else Path(
        tempfile.mkdtemp(prefix="aria_training_demo_")
    )
    workdir.mkdir(parents=True, exist_ok=True)

    # Non-strict so the privacy rejection is recorded rather than
    # aborting the whole run. AcceptAllVerifier is used because the demo
    # does not have a real Work Ledger — production pipelines MUST supply
    # a WorkLedgerVerifier. The strict-mode and verifier paths are
    # exercised in the test suite.
    print(
        "WARNING: demo uses AcceptAllVerifier (provenance not checked "
        "against a real Work Ledger). PROTOTYPE ONLY."
    )
    config = ExportConfig(
        export_root=workdir,
        strict_privacy=False,
        verifier=AcceptAllVerifier(),
        # Smaller threshold so the demo's tiny dataset can be reasoned
        # about; the prototype's production default is 50.
        quality=QualityPolicy(minimum_examples_per_skill=2),
    )
    exporter = DatasetExporter(config)
    report = exporter.export(_sample_candidates())

    print("-- Dataset Export Report --------------------------------------")
    print(json.dumps(report.model_dump(), indent=2, sort_keys=True))
    print()
    print(f"SFT examples : {report.total_sft_examples}")
    print(f"DPO pairs    : {report.total_dpo_pairs}")
    print(f"Privacy rejs : {report.rejected_for_privacy}")
    print(f"Quality rejs : {report.rejected_for_quality}")
    print(f"Sensitivity rejs : {report.rejected_for_sensitivity}")
    print(f"Output dir   : {workdir}")

    # Clean up BEFORE the final line so "Prototype only..." is genuinely
    # the last line printed (a hard requirement of the prototype contract).
    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)
        print("(demo directory removed; pass --keep to retain it)")

    print()
    print("Prototype only. No model training was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
