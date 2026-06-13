"""
Fine-Tuning Prototype — dataset manifest + deterministic plan builder.

PROTOTYPE ONLY. Nothing here trains, downloads, or deploys a model. The
planner's job is to turn a *verified* Priority-3 dataset export into an
immutable ``FineTuningPlan`` — and to REFUSE any export that is tampered
with, privacy-invalid, provenance-invalid, or below the prototype's
minimum example count.

The Priority-3 ``DatasetExporter`` writes three files but no hash
manifest. ``build_manifest`` snapshots a SHA-256 of each file plus a
combined ``dataset_hash``; ``verify_manifest`` re-reads and recomputes
those hashes so a dataset modified after export is caught before any
plan is built. ``plan`` runs the full gate sequence and emits the plan.

All checks are pure, offline, and deterministic.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from aria.ledger.privacy import contains_credential_pattern
from aria.model_registry.evaluator import (
    EVALUATOR_VERSION,
    default_pr_review_holdout,
    holdout_fingerprint,
)
from aria.ledger.events import ActionTier
from aria.fine_tuning.models import (
    ArtifactPathError,
    DatasetInsufficientError,
    DatasetIntegrityError,
    DatasetManifest,
    DatasetPrivacyError,
    DatasetProvenanceError,
    EvaluationPlan,
    FineTuningPlan,
    HyperparameterProposal,
    TrainingMethod,
    compute_config_hash,
    compute_dataset_hash,
    utc_now,
)


# ── Policy ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FineTuningPolicy:
    """
    Prototype gating + estimation knobs.

    ``min_total_examples`` is the PROTOTYPE sufficiency bar — the smallest
    dataset the pipeline will plan against to prove the machinery. It is
    deliberately decoupled from (and far below) the Priority-3 production
    readiness bar of 50 examples *per skill*; a plan being buildable here
    is NOT a statement that the dataset is production-ready.
    """
    min_total_examples:      int   = 6
    base_model:              str   = "Qwen2.5-Coder-7B-Instruct"
    default_method:          TrainingMethod = TrainingMethod.sft_then_dpo
    # Token / cost estimation (nominal — no real training is billed).
    tokens_per_sft_example:  int   = 512
    tokens_per_dpo_pair:     int   = 1024
    usd_per_million_tokens:  float = 0.80


# ── Path confinement ──────────────────────────────────────────────────────────


def _confined_file(root: Path, name: str) -> Path:
    """Resolve ``root / name`` and verify it stays strictly inside ``root``."""
    if not name or "\x00" in name or "/" in name or "\\" in name:
        raise ArtifactPathError(f"Unsafe filename {name!r}; supply a bare filename.")
    if ".." in name.split("."):
        raise ArtifactPathError(f"Filename {name!r} contains a parent-traversal segment.")
    candidate = (root / name).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ArtifactPathError(
            f"Path {candidate} resolves outside root {root_resolved}."
        ) from exc
    return candidate


def confined_dir(root: Path, *parts: str) -> Path:
    """Resolve ``root/parts...`` and verify it stays strictly beneath ``root``."""
    for p in parts:
        if not p or "\x00" in p or "/" in p or "\\" in p or ".." in p.split("."):
            raise ArtifactPathError(f"Unsafe path segment {p!r}.")
    candidate = root.joinpath(*parts).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ArtifactPathError(
            f"Artifact location {candidate} is outside artifact root {root_resolved}."
        ) from exc
    return candidate


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse a (possibly empty) JSONL file into a list of dicts."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


# ── Planner ───────────────────────────────────────────────────────────────────


class FineTuningPlanner:
    """Builds + verifies a ``DatasetManifest`` and emits a ``FineTuningPlan``."""

    def __init__(
        self,
        policy: FineTuningPolicy = FineTuningPolicy(),
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._policy = policy
        self._clock = clock

    # ── Manifest ────────────────────────────────────────────────────────────

    def build_manifest(
        self,
        export_dir: Path,
        *,
        sft_filename: str = "sft_examples.jsonl",
        dpo_filename: str = "dpo_pairs.jsonl",
        report_filename: str = "dataset_report.json",
    ) -> DatasetManifest:
        """
        Snapshot a Priority-3 export into a tamper-evident manifest.

        Reads the three export files, computes a SHA-256 of each, derives the
        combined ``dataset_hash`` and a content-addressed ``dataset_id``, and
        lifts the counts / skills / readiness flag out of the report.
        """
        export_dir = Path(export_dir)
        sft_path    = _confined_file(export_dir, sft_filename)
        dpo_path    = _confined_file(export_dir, dpo_filename)
        report_path = _confined_file(export_dir, report_filename)

        for p in (sft_path, dpo_path, report_path):
            if not p.exists():
                raise DatasetIntegrityError(
                    f"Export file {p.name!r} is missing from {export_dir}."
                )

        sft_sha    = _sha256_file(sft_path)
        dpo_sha    = _sha256_file(dpo_path)
        report_sha = _sha256_file(report_path)
        dataset_hash = compute_dataset_hash(sft_sha, dpo_sha, report_sha)

        report = json.loads(report_path.read_text(encoding="utf-8"))
        examples_by_skill = dict(report.get("examples_by_skill", {}))
        pairs_by_skill    = dict(report.get("pairs_by_skill", {}))
        skills = sorted(set(examples_by_skill) | set(pairs_by_skill))

        return DatasetManifest(
            export_dir=str(export_dir),
            sft_filename=sft_filename,
            dpo_filename=dpo_filename,
            report_filename=report_filename,
            sft_sha256=sft_sha,
            dpo_sha256=dpo_sha,
            report_sha256=report_sha,
            dataset_hash=dataset_hash,
            dataset_id="ds-" + dataset_hash[:16],
            sft_count=int(report.get("total_sft_examples", 0)),
            dpo_count=int(report.get("total_dpo_pairs", 0)),
            skills=skills,
            ready_for_finetuning=bool(report.get("ready_for_finetuning", False)),
            minimum_examples_per_skill=int(report.get("minimum_examples_per_skill", 50)),
            created_at=self._clock(),
        )

    def verify_manifest(self, manifest: DatasetManifest) -> None:
        """
        Re-read the export files and recompute their hashes; raise
        ``DatasetIntegrityError`` if any file is missing or has changed
        since the manifest was built (i.e. modified after export).
        """
        export_dir = Path(manifest.export_dir)
        sft_path    = _confined_file(export_dir, manifest.sft_filename)
        dpo_path    = _confined_file(export_dir, manifest.dpo_filename)
        report_path = _confined_file(export_dir, manifest.report_filename)

        for p, recorded in (
            (sft_path, manifest.sft_sha256),
            (dpo_path, manifest.dpo_sha256),
            (report_path, manifest.report_sha256),
        ):
            if not p.exists():
                raise DatasetIntegrityError(f"Export file {p.name!r} is missing.")
            actual = _sha256_file(p)
            if actual != recorded:
                raise DatasetIntegrityError(
                    f"Export file {p.name!r} was modified after export "
                    "(hash mismatch)."
                )

        recombined = compute_dataset_hash(
            manifest.sft_sha256, manifest.dpo_sha256, manifest.report_sha256
        )
        if recombined != manifest.dataset_hash:
            raise DatasetIntegrityError("Combined dataset_hash does not match file hashes.")

    # ── Plan ────────────────────────────────────────────────────────────────

    def plan(
        self,
        manifest: DatasetManifest,
        *,
        artifact_root: Path,
        base_model: Optional[str] = None,
        training_method: Optional[TrainingMethod] = None,
        training_run_id: Optional[str] = None,
    ) -> FineTuningPlan:
        """
        Produce a deterministic ``FineTuningPlan`` from a verified manifest.

        Gate sequence (each raises a distinct, testable error):
          1. integrity  — files unchanged since export   (DatasetIntegrityError)
          2. privacy    — no credential-shaped content    (DatasetPrivacyError)
          3. provenance — every example cites source_events (DatasetProvenanceError)
          4. sufficiency— total examples >= prototype min  (DatasetInsufficientError)
        """
        artifact_root = Path(artifact_root)

        # 1. Integrity — tamper detection first.
        self.verify_manifest(manifest)

        export_dir = Path(manifest.export_dir)
        sft_rows = _iter_jsonl(_confined_file(export_dir, manifest.sft_filename))
        dpo_rows = _iter_jsonl(_confined_file(export_dir, manifest.dpo_filename))

        # 2. Privacy — defence in depth over the exported content itself.
        self._scan_privacy(sft_rows, ("input", "output"))
        self._scan_privacy(dpo_rows, ("prompt", "chosen", "rejected", "correction"))

        # 3. Provenance — every exported example must carry source_events.
        self._scan_provenance(sft_rows)
        self._scan_provenance(dpo_rows)

        # 4. Sufficiency — prototype minimum (NOT the 50/skill production bar).
        total = manifest.total_examples
        if total < self._policy.min_total_examples:
            raise DatasetInsufficientError(
                f"Dataset has {total} example(s); the prototype requires at least "
                f"{self._policy.min_total_examples}."
            )

        base = base_model or self._policy.base_model
        method = training_method or (
            TrainingMethod.sft_then_dpo if manifest.dpo_count > 0 else TrainingMethod.sft
        )
        hyper = HyperparameterProposal(method=method)

        config_hash = compute_config_hash(
            base_model=base,
            dataset_hash=manifest.dataset_hash,
            training_method=method,
            hyperparameters=hyper,
            sft_count=manifest.sft_count,
            dpo_count=manifest.dpo_count,
            skills=manifest.skills,
        )
        run_id = training_run_id or (
            "ftrun-" + hashlib.sha256(
                f"{manifest.dataset_hash}::{base}::{method.value}".encode("utf-8")
            ).hexdigest()[:16]
        )

        estimated_tokens = (
            manifest.sft_count * self._policy.tokens_per_sft_example
            + manifest.dpo_count * self._policy.tokens_per_dpo_pair
        ) * hyper.epochs
        estimated_cost = round(
            estimated_tokens / 1_000_000 * self._policy.usd_per_million_tokens, 6
        )

        output_location = confined_dir(artifact_root, run_id)

        holdout = default_pr_review_holdout()
        evaluation_plan = EvaluationPlan(
            holdout_id=holdout_fingerprint(holdout)[:12],
            evaluator_version=EVALUATOR_VERSION,
            dimensions=["accuracy", "pass_rate", "rubric_score"],
            promote_threshold_dimensions=2,
        )

        return FineTuningPlan(
            training_run_id=run_id,
            base_model=base,
            dataset_id=manifest.dataset_id,
            dataset_hash=manifest.dataset_hash,
            sft_example_count=manifest.sft_count,
            dpo_pair_count=manifest.dpo_count,
            skills=list(manifest.skills),
            training_method=method,
            hyperparameters=hyper,
            estimated_tokens=estimated_tokens,
            estimated_cost_usd=estimated_cost,
            evaluation_plan=evaluation_plan,
            risk_tier=ActionTier.T3,
            approval_required=True,
            output_artifact_location=str(output_location),
            config_hash=config_hash,
            created_at=self._clock(),
        )

    # ── Internal scans ──────────────────────────────────────────────────────

    @staticmethod
    def _scan_privacy(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
        for row in rows:
            for f in fields:
                value = row.get(f)
                if isinstance(value, str) and contains_credential_pattern(value):
                    raise DatasetPrivacyError(
                        f"Exported example contains a credential-shaped value in "
                        f"field {f!r}; refusing to plan a fine-tune over it."
                    )

    @staticmethod
    def _scan_provenance(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            events = row.get("source_events")
            if not isinstance(events, list) or not events:
                raise DatasetProvenanceError(
                    "Exported example is missing source-event provenance."
                )
