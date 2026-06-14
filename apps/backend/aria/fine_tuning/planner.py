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
from typing import Any, Callable, Iterable, Optional, Protocol, runtime_checkable

from aria.ledger.privacy import contains_credential_pattern
from aria.model_registry.evaluator import (
    EVALUATOR_VERSION,
    default_pr_review_holdout,
    holdout_fingerprint,
)
from aria.ledger.events import ActionTier
from aria.training_data.models import canonical_content_hash
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


# ── Provenance verification (ledger-backed, injectable) ───────────────────────


@runtime_checkable
class PlanProvenanceVerifier(Protocol):
    """
    Corroborates that the ledger events an exported example cites are sound —
    *for the task that example belongs to, and for the exact content the row
    carries*. ``verify_events`` takes the example's ``task_id``, its cited
    ``source_events``, the canonical ``content_hash`` reconstructed from the
    row, and the ``required_event_type`` that may authorise this kind of row
    (``outcome_recorded`` for SFT, ``correction_recorded`` for DPO). It returns
    a list of human-readable problems; an empty list means the citation is
    sound.

    Provenance is TASK-BOUND and CONTENT-BOUND, not global: an event existing
    somewhere in the ledger is not enough — it must belong to the citing task
    AND have recorded the SAME content this row carries. A real verifier is
    dependency-injected; the planner never reaches out to the ledger itself.
    This keeps the planner offline and deterministic while still refusing
    fabricated, cross-task, malformed, inappropriately-typed, or
    content-mismatched provenance.
    """
    def verify_events(
        self,
        task_id: str,
        source_events: list[str],
        *,
        content_hash: str,
        required_event_type: str,
    ) -> list[str]: ...


@dataclass(frozen=True)
class _LedgerEventFacts:
    """
    What the verifier remembers about ONE recorded ledger event: its type and
    the canonical ``content_hash`` it bound (``None`` for events that recorded
    no hash — legacy / non-binding — which therefore can never authorise a
    training example).
    """
    event_type:   str
    content_hash: Optional[str]


class LedgerEventProvenanceVerifier:
    """
    Production verifier: TASK-BOUND + CONTENT-BOUND provenance corroboration
    built from the REAL Work Ledger v2.

    It holds, per ``task_id``, each recorded event's id → (type, content_hash).
    An exported example's cited ``source_events`` are valid for a given
    ``task_id`` only when EVERY cited event:

      - is a well-formed, non-empty string,
      - was actually recorded in the Work Ledger (not fabricated),
      - belongs to *that same task* (no cross-task event borrowing), and
      - is of a type that can authorise training provenance — i.e. a learning
        event (``outcome_recorded`` / ``correction_recorded``).

    AND, on top of those structural checks, at least one cited event must be
    of the ``required_event_type`` for this row AND have recorded a
    ``content_hash`` equal to the canonical hash reconstructed from the row.
    This is the binding that stops a poisoned row from re-using an old, real,
    same-task approval marker that judged DIFFERENT content: the cited event
    and the exported content must be the SAME fact. A hashless legacy event
    (``content_hash is None``) can never satisfy the binding — it fails closed.

    Construct it from real ledger events via ``from_ledger_events`` — the
    verifier is only as trustworthy as the recorded events behind it, so it
    never trusts a caller-fabricated event set the way the old (global,
    untyped) constructor did.
    """

    # Only learning-outcome events authorise a training example's provenance.
    _AUTHORIZING_TYPES: frozenset[str] = frozenset(
        {"outcome_recorded", "correction_recorded"}
    )

    def __init__(self, events_by_task: dict[str, dict[str, _LedgerEventFacts]]) -> None:
        # task_id -> {event_id -> _LedgerEventFacts}
        self._by_task: dict[str, dict[str, _LedgerEventFacts]] = {
            str(task): {str(eid): facts for eid, facts in events.items()}
            for task, events in events_by_task.items()
        }
        # Reverse index event_id -> owning task_id, for cross-task detection.
        self._owner: dict[str, str] = {}
        for task, events in self._by_task.items():
            for eid in events:
                self._owner[eid] = task

    @classmethod
    def from_ledger_events(cls, events: Iterable[Any]) -> "LedgerEventProvenanceVerifier":
        """
        Build the ``task_id -> {event_id -> (event_type, content_hash)}`` map
        from real Work Ledger v2 events (as returned by
        ``LedgerReader.v2_events()``). Each event contributes its ``event_id``,
        ``event_type`` and — for the learning events that carry it —
        ``content_hash``, under its ``task_id``. This is the only constructor a
        production caller should use; it binds the verifier to recorded ledger
        facts, content hashes included.
        """
        by_task: dict[str, dict[str, _LedgerEventFacts]] = {}
        for ev in events:
            task_id = str(getattr(ev, "task_id"))
            event_id = str(getattr(ev, "event_id"))
            etype = getattr(ev, "event_type")
            etype_value = str(getattr(etype, "value", etype))
            raw_hash = getattr(ev, "content_hash", None)
            content_hash = str(raw_hash) if raw_hash is not None else None
            by_task.setdefault(task_id, {})[event_id] = _LedgerEventFacts(
                event_type=etype_value, content_hash=content_hash,
            )
        return cls(by_task)

    def verify_events(
        self,
        task_id: str,
        source_events: list[str],
        *,
        content_hash: str,
        required_event_type: str,
    ) -> list[str]:
        task_key = str(task_id) if task_id is not None else ""
        if not task_key.strip():
            return ["example is missing a task_id; cannot bind provenance to a task"]
        task_events = self._by_task.get(task_key)
        if task_events is None:
            return [f"task {task_key!r} has no events recorded in the Work Ledger"]

        problems: list[str] = []
        bound_to_content = False
        for raw in source_events:
            if not isinstance(raw, str) or not raw.strip():
                problems.append("a cited source event id is empty or malformed")
                continue
            facts = task_events.get(raw)
            if facts is None:
                owner = self._owner.get(raw)
                if owner is None:
                    problems.append(
                        f"source event {raw!r} is absent from the Work Ledger (fabricated)"
                    )
                else:
                    problems.append(
                        f"source event {raw!r} belongs to task {owner!r}, "
                        f"not {task_key!r} (cross-task provenance)"
                    )
                continue
            if facts.event_type not in self._AUTHORIZING_TYPES:
                problems.append(
                    f"source event {raw!r} is a {facts.event_type!r} event; only "
                    f"{sorted(self._AUTHORIZING_TYPES)} may authorise training provenance"
                )
                continue
            # Content binding: the cited authorising event of the REQUIRED type
            # must have recorded THIS exact content. Hashless events (None) and
            # events that judged different content never bind → fail closed.
            if (
                facts.event_type == required_event_type
                and facts.content_hash is not None
                and facts.content_hash == content_hash
            ):
                bound_to_content = True

        if not bound_to_content:
            problems.append(
                f"no cited {required_event_type!r} event is bound to this example's "
                f"content (its recorded content_hash must equal the canonical hash "
                f"reconstructed from the row); an event that judged different "
                f"content — or a hashless legacy event — cannot authorise it"
            )
        return problems


class AcceptAllPlanProvenance:
    """
    Offline bypass for demos / unit tests ONLY. Accepts any provenance without
    a ledger lookup. It is NEVER appropriate in production — it performs no
    corroboration whatsoever and exists solely so offline callers can opt out
    of ledger verification explicitly (mirroring Priority-3's AcceptAllVerifier).
    """

    def verify_events(
        self,
        task_id: str,
        source_events: list[str],
        *,
        content_hash: str,
        required_event_type: str,
    ) -> list[str]:
        return []


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
        provenance_verifier: Optional[PlanProvenanceVerifier] = None,
    ) -> None:
        self._policy = policy
        self._clock = clock
        self._provenance_verifier = provenance_verifier

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

        # Counts + per-skill breakdown are derived from the PHYSICAL rows — not
        # taken on trust from the report. The report is then required to AGREE
        # exactly with that physical truth. A report that under/over-states the
        # dataset, or mislabels its skills, is a tampered export and is rejected
        # here, before any plan is built. (``verify_manifest`` only catches
        # changes made AFTER the snapshot; a report that is already inconsistent
        # with its JSONL at snapshot time would otherwise pass hashing untouched,
        # so it must be caught now.)
        sft_rows = _iter_jsonl(sft_path)
        dpo_rows = _iter_jsonl(dpo_path)
        physical_sft = len(sft_rows)
        physical_dpo = len(dpo_rows)
        derived_examples_by_skill = self._count_by_skill(sft_rows)
        derived_pairs_by_skill    = self._count_by_skill(dpo_rows)

        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_sft = int(report.get("total_sft_examples", 0))
        report_dpo = int(report.get("total_dpo_pairs", 0))
        report_examples_by_skill = {
            str(k): int(v) for k, v in dict(report.get("examples_by_skill", {})).items()
        }
        report_pairs_by_skill = {
            str(k): int(v) for k, v in dict(report.get("pairs_by_skill", {})).items()
        }
        if report_sft != physical_sft or report_dpo != physical_dpo:
            raise DatasetIntegrityError(
                f"Dataset report disagrees with the physical export: report claims "
                f"{report_sft} SFT / {report_dpo} DPO, but the files contain "
                f"{physical_sft} SFT / {physical_dpo} DPO."
            )
        if report_examples_by_skill != derived_examples_by_skill:
            raise DatasetIntegrityError(
                "Dataset report's examples_by_skill disagrees with the physical "
                "SFT rows (per-skill count mismatch)."
            )
        if report_pairs_by_skill != derived_pairs_by_skill:
            raise DatasetIntegrityError(
                "Dataset report's pairs_by_skill disagrees with the physical "
                "DPO rows (per-skill count mismatch)."
            )
        skills = sorted(set(derived_examples_by_skill) | set(derived_pairs_by_skill))

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
            sft_count=physical_sft,
            dpo_count=physical_dpo,
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

        # 3. Provenance — two layers, both fail closed.
        #    3a. Structural: every exported example carries a non-empty
        #        source_events list. Cheap and runs first, so a missing-
        #        provenance row is rejected without needing a verifier.
        self._scan_provenance(sft_rows)
        self._scan_provenance(dpo_rows)
        #    3b. Ledger-backed: the cited events must ACTUALLY exist in the Work
        #        Ledger. A non-empty list is not enough — it could be fabricated.
        #        Requires an injected verifier; absent one, the planner refuses
        #        to proceed rather than trust unverifiable provenance.
        self._verify_provenance_against_ledger(sft_rows, kind="sft")
        self._verify_provenance_against_ledger(dpo_rows, kind="dpo")

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
    def _count_by_skill(rows: list[dict[str, Any]]) -> dict[str, int]:
        """
        Count physical rows per ``skill_name``. A row without a usable
        ``skill_name`` cannot be attributed, which makes the per-skill
        breakdown unverifiable — so it fails closed with
        ``DatasetIntegrityError`` rather than silently dropping the row.
        """
        counts: dict[str, int] = {}
        for row in rows:
            skill = row.get("skill_name")
            if not isinstance(skill, str) or not skill:
                raise DatasetIntegrityError(
                    "Exported example is missing a 'skill_name'; cannot derive a "
                    "verifiable per-skill breakdown from the physical rows."
                )
            counts[skill] = counts.get(skill, 0) + 1
        return counts

    def _verify_provenance_against_ledger(
        self, rows: list[dict[str, Any]], *, kind: str
    ) -> None:
        """
        Confirm every exported example's cited source events are sound for the
        task that example belongs to AND bound to the exact content the row
        carries, via the injected verifier. Provenance is task-bound and
        content-bound: the verifier receives the row's ``task_id``, its cited
        ``source_events``, the canonical ``content_hash`` reconstructed from the
        row, and the ``required_event_type`` that may authorise this ``kind`` of
        row (``outcome_recorded`` for SFT, ``correction_recorded`` for DPO). It
        rejects fabricated, cross-task, malformed, mistyped, or
        content-mismatched citations.

        For DPO rows the canonical binding covers ``correction``; because the
        preferred response actually used in training is ``chosen``, this method
        also requires ``chosen == correction`` so the content-bound correction
        transitively authorises the exact preferred response (a row that swaps
        only ``chosen`` is rejected).

        Identifiers are NOT coerced (Finding 2): a row whose ``task_id`` — or
        any cited ``source_events`` entry — is not a non-empty string is
        rejected here, before the verifier is consulted. ``str()``-coercing a
        structural identifier would let an integer ``123`` masquerade as the
        ledger's string event id ``"123"``.

        Fail closed: with no verifier configured, refuse to proceed (a
        fabricated or cross-task source_events list would otherwise pass the
        structural scan unchallenged).
        """
        if self._provenance_verifier is None:
            raise DatasetProvenanceError(
                "No provenance verifier configured. Supply a "
                "LedgerEventProvenanceVerifier (production) or "
                "AcceptAllPlanProvenance (offline demo / unit tests) to "
                "FineTuningPlanner — it will not plan a fine-tune over "
                "provenance it cannot corroborate against the Work Ledger."
            )
        required_event_type = (
            "outcome_recorded" if kind == "sft" else "correction_recorded"
        )
        for row in rows:
            task_id = row.get("task_id")
            if not isinstance(task_id, str) or not task_id.strip():
                raise DatasetProvenanceError(
                    f"Exported {kind} example has a non-string or empty task_id "
                    f"({task_id!r}); structural identifiers are not coerced."
                )
            events = row.get("source_events") or []
            for ev in events:
                if not isinstance(ev, str) or not ev.strip():
                    raise DatasetProvenanceError(
                        f"Exported {kind} example (task_id={task_id!r}) cites a "
                        f"non-string or empty source event id ({ev!r}); structural "
                        f"identifiers are not coerced."
                    )
            if kind == "dpo":
                # Content binding (below) covers the DPO ``correction`` — the
                # ledger-authorised corrected output — but the preferred response
                # DPO actually trains toward is ``chosen``. The exporter always
                # sets chosen == correction (both are the candidate's
                # corrected_output), so requiring equality here makes the
                # content-bound correction transitively authorise the exact
                # preferred response. A row that keeps a valid ``correction`` while
                # swapping only ``chosen`` — poisoning what training optimises
                # toward — is rejected. Fail closed on any inequality, including a
                # missing or non-string ``chosen``.
                if row.get("chosen") != row.get("correction"):
                    raise DatasetProvenanceError(
                        f"Exported dpo example (task_id={task_id!r}) has a "
                        f"`chosen` preferred response that does not equal its "
                        f"ledger-authorised `correction`; the response DPO trains "
                        f"toward must be the same content the ledger approved "
                        f"(chosen != correction)."
                    )
            content_hash = self._row_content_hash(row, kind=kind)
            problems = self._provenance_verifier.verify_events(
                task_id,
                list(events),
                content_hash=content_hash,
                required_event_type=required_event_type,
            )
            if problems:
                raise DatasetProvenanceError(
                    f"Exported example provenance failed ledger-backed "
                    f"verification (task_id={task_id!r}): "
                    + "; ".join(str(p) for p in problems)
                )

    @staticmethod
    def _row_content_hash(row: dict[str, Any], *, kind: str) -> str:
        """
        Reconstruct the canonical content hash from an exported row, matching
        ``aria.training_data.models.canonical_content_hash`` exactly so it can
        be compared against the ``content_hash`` the authorising ledger event
        recorded.

        The mapping mirrors the exporter:
          - SFT  row → input_text=``input``,  output_text=``output``,
                       rejected/corrected = None
          - DPO  row → input_text=``prompt``, output_text = None,
                       rejected_output=``rejected``, corrected_output=``correction``

        Eligible exports reconstruct EXACTLY: the exporter requires the
        relevant fields to be non-empty, so the row carries the same strings
        the candidate hashed at ingestion.
        """
        task_id = row.get("task_id")
        skill_name = row.get("skill_name")
        if not isinstance(task_id, str) or not isinstance(skill_name, str):
            # Should never reach here — task_id is validated by the caller and
            # skill_name by _count_by_skill — but fail closed rather than hash
            # over a non-string identifier.
            raise DatasetProvenanceError(
                "Cannot reconstruct content hash: task_id/skill_name missing."
            )
        if kind == "sft":
            return canonical_content_hash(
                task_id=task_id,
                skill_name=skill_name,
                input_text=row.get("input"),
                output_text=row.get("output"),
                rejected_output=None,
                corrected_output=None,
            )
        return canonical_content_hash(
            task_id=task_id,
            skill_name=skill_name,
            input_text=row.get("prompt"),
            output_text=None,
            rejected_output=row.get("rejected"),
            corrected_output=row.get("correction"),
        )

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
