"""
DatasetExporter — Dataset Export Prototype orchestrator.

PROTOTYPE ONLY. This module prepares SFT / DPO candidate files and a
typed ``DatasetReport``. It does not train, score, fine-tune, or
deploy anything.

Fail-closed verification
------------------------
``export()`` REFUSES to run without a provenance verifier: an
``ExportConfig`` whose ``verifier`` is ``None`` raises
``ExporterConfigurationError``. Production callers supply a
``WorkLedgerVerifier``; offline demos and unit tests that deliberately
skip ledger checks must opt in explicitly with ``AcceptAllVerifier``.

Pipeline (per candidate)
------------------------
1. **Provenance check**       — non-empty ``provenance`` list.
2. **Structural privacy scan**— structural identifiers (task_id,
                                 skill_name, artifact_id, outcome_label)
                                 and every provenance event ID are scanned
                                 FIRST, before any verification logging can
                                 echo a credential-shaped identifier. A hit
                                 ALWAYS rejects (never redacts — a ledger
                                 reference must stay resolvable); strict
                                 mode aborts.
3. **Ledger verification**    — the configured verifier corroborates the
                                 candidate against per-task ledger views:
                                 every event belongs to the task, and the
                                 REQUIRED ledger evidence (content_hash for
                                 every candidate, outcome for SFT,
                                 correction for DPO) is present and matches.
4. **Sensitivity gate**       — confidential / restricted always rejected;
                                 unknown rejected in strict mode.
5. **Free-text privacy scan** — free-text content fields are scanned:
                                 strict mode aborts, non-strict +
                                 redact-allowed redacts, else reject.
6. **Content check**          — SFT needs input+output; DPO needs
                                 input+rejected+corrected.
7. **Label check (SFT only)** — explicit positive ``OutcomeRecorded``.
                                 Governance approval alone is NEVER
                                 enough — it is an action decision, not
                                 an output-quality label.
8. **Quality checks**         — minimum output length, identical
                                 chosen/rejected, malformed correction
                                 pair.
9. **Dedup**                  — content-hash key. Identical content
                                 across tasks collapses to one record.

Output
------
- ``sft_examples.jsonl``  — JSONL, deterministically ordered.
- ``dpo_pairs.jsonl``     — JSONL, deterministically ordered.
- ``dataset_report.json`` — typed ``DatasetReport`` (pretty-printed
                            JSON, sorted keys).

All three files are written as one transactional group via
``_commit_all_files``: content is staged to ``.tmp`` siblings and
fsync'd; any pre-existing finals are moved aside to ``.bak``; the temps
are then promoted. If any promotion fails, every promoted final is
removed and the ``.bak`` originals are restored — a failed export NEVER
destroys the previously written dataset and never leaves a partial one.
If restoration ITSELF fails, the rollback does not fail silently: it
raises a typed ``DatasetRecoveryError`` naming the affected files (whose
recoverable originals remain at their ``.bak`` siblings) so a
half-restored dataset surfaces loudly instead of corrupting quietly.

Path confinement REFUSES any configured filename that resolves outside
the root.

Privacy / safety guarantees
---------------------------
- Exported JSONL files never contain raw event objects, raw metadata,
  arbitrary actor identities, filesystem paths, exception strings, or
  provider credentials.
- Structural identifiers and provenance event IDs are scanned for
  credentials; a hit ALWAYS rejects the candidate (never redacted), so a
  poisoned ledger reference cannot reach ``source_events``.
- Free-text content credentials are redacted (non-strict + redaction) or
  block the export (strict).
- Sanitised, log-safe rejection summaries only.
- Confidential / restricted candidates are rejected, not redacted.
- Unknown sensitivity fails closed in strict mode.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from aria.training_data.models import (
    DatasetReport,
    DPOPair,
    RejectionReason,
    RejectionRecord,
    Sensitivity,
    SFTExample,
    TrainingCandidate,
)
from aria.training_data.privacy import (
    safe_summary,
    scan_structural_identifiers_for_credentials,
    scan_text_fields_for_credentials,
)
from aria.training_data.quality import (
    DEFAULT_QUALITY_POLICY,
    QualityPolicy,
    assess_readiness,
    dpo_dedup_key,
    dpo_pair_id,
    fails_minimum_output_length,
    identical_chosen_rejected,
    malformed_correction_pair,
    sft_dedup_key,
    sft_example_id,
)


_log = logging.getLogger("aria.training_data.exporter")


# ── Exceptions ───────────────────────────────────────────────────────────────


class ExportPathError(ValueError):
    """Raised when an output path resolves outside the configured root."""


class StrictPrivacyViolation(RuntimeError):
    """Raised in strict mode when a candidate has unresolved credentials."""


class ExporterConfigurationError(RuntimeError):
    """
    Raised when the exporter is asked to run in an unsafe configuration —
    currently, when no provenance ``verifier`` is supplied. The pipeline
    fails closed: it will not export training data that has not been
    corroborated against the Work Ledger (or explicitly bypassed with
    ``AcceptAllVerifier`` for demos / unit tests).
    """


class DatasetRecoveryError(RuntimeError):
    """
    Raised when an export fails AND the previous dataset could not be
    fully restored during rollback. It converts a silent, half-restored
    on-disk state into a loud, typed failure. The recoverable original of
    each unrestored file remains at its ``<final>.bak`` sibling so an
    operator can recover by hand. The message names only our own output
    filenames — never task content or credentials.
    """


# ── Config ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExportConfig:
    """All exporter knobs. Defaults are the prototype's safe defaults."""
    export_root:     Path
    sft_filename:    str         = "sft_examples.jsonl"
    dpo_filename:    str         = "dpo_pairs.jsonl"
    report_filename: str         = "dataset_report.json"
    strict_privacy:  bool        = True
    quality:         QualityPolicy = field(default_factory=lambda: DEFAULT_QUALITY_POLICY)
    # Provenance verifier. REQUIRED — ``export()`` fails closed with
    # ``ExporterConfigurationError`` when this is None. Every candidate is
    # corroborated against the Work Ledger before export. Production
    # pipelines supply a ``WorkLedgerVerifier``; offline demos and unit
    # tests that intentionally skip ledger checks must opt in explicitly
    # with ``AcceptAllVerifier``.
    verifier:        Optional[Any] = None


# ── Path confinement ─────────────────────────────────────────────────────────


def _confined_inside(root: Path, name: str) -> Path:
    """
    Resolve ``root / name`` and verify the result is strictly inside
    ``root``. Refuses traversal segments, absolute paths, and any
    target that resolves outside ``root``. The export pipeline calls
    this before EVERY file write.
    """
    if not name or "\x00" in name or "/" in name or "\\" in name:
        raise ExportPathError(
            f"Output filename {name!r} is not allowed; supply a bare filename."
        )
    if ".." in name.split("."):
        raise ExportPathError(
            f"Output filename {name!r} contains a parent-traversal segment."
        )
    candidate = (root / name).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ExportPathError(
            f"Output path {candidate} is outside export_root {root_resolved}."
        ) from exc
    return candidate


# ── Atomic grouped write ─────────────────────────────────────────────────────


def _quiet_unlink(path: Path) -> None:
    """Best-effort unlink; never raises (used in rollback / cleanup)."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _commit_all_files(file_contents: list[tuple[Path, str]]) -> None:
    """
    Write all (path, content) pairs as one transactional group.

    Stage 1 — stage every content string to a ``.tmp`` sibling and
              ``fsync`` it.
    Stage 2 — move every pre-existing final out of the way to a ``.bak``
              sibling, so the previous dataset is recoverable.
    Stage 3 — promote every ``.tmp`` to its final path (``os.replace``).

    On success the ``.bak`` backups are removed.

    On ANY failure the operation rolls back: every final that was already
    promoted in stage 3 is removed, every ``.bak`` original is restored to
    its final path, and every leftover ``.tmp`` is deleted. This
    guarantees a failed export neither leaves a partial dataset NOR
    destroys the previously written one — and the original commit error is
    re-raised so callers see why the export failed.

    If a restoration ITSELF fails, the failure is NOT swallowed: every
    surviving original stays at its ``.bak`` sibling and a typed
    ``DatasetRecoveryError`` (chained from the original commit error) is
    raised naming the files that could not be restored, so a
    half-restored dataset is surfaced loudly rather than corrupting
    silently.

    A leftover ``.bak`` only ever persists across calls after such a
    ``DatasetRecoveryError`` (every other path removes its backups). So
    BEFORE touching anything, this function fails closed if any target
    ``.bak`` already exists: a prior export's only recoverable copy is
    sitting there unresolved, and Stage 2's ``os.replace(path, bak)``
    would overwrite — then a successful retry would delete — it. The
    operator must restore or remove the ``.bak`` before another export.
    """
    # Pre-flight: refuse to run on top of an unresolved recovery backup.
    preexisting_baks = [
        path.with_suffix(path.suffix + ".bak")
        for path, _ in file_contents
        if path.with_suffix(path.suffix + ".bak").exists()
    ]
    if preexisting_baks:
        raise DatasetRecoveryError(
            "Refusing to export: unresolved recovery backup(s) from a prior "
            "failed export already exist. Overwriting them would destroy the "
            "only recoverable copy of the previous dataset. Restore or remove "
            "these first: "
            + ", ".join(sorted(b.name for b in preexisting_baks))
        )

    tmp_paths:  list[Path] = []
    backups:    list[tuple[Path, Path]] = []   # (final_path, backup_path)
    committed:  list[Path] = []
    try:
        # Stage 1 — stage temps (fsync'd).
        for path, content in file_contents:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp_paths.append(tmp)
            path.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())

        # Stage 2 — move existing finals aside (recoverable).
        for path, _ in file_contents:
            if path.exists():
                bak = path.with_suffix(path.suffix + ".bak")
                os.replace(path, bak)
                backups.append((path, bak))

        # Stage 3 — promote temps to finals.
        for (path, _), tmp in zip(file_contents, tmp_paths):
            os.replace(tmp, path)
            committed.append(path)
    except BaseException as commit_exc:
        # Roll back: remove promoted finals, restore originals, delete any
        # leftover temps. A previously written dataset is restored intact.
        restore_failures: list[Path] = []
        for path in committed:
            _quiet_unlink(path)
        for path, bak in backups:
            # Clear any promoted final still occupying the slot so the
            # backup can move back into place.
            if path.exists():
                _quiet_unlink(path)
            if bak.exists():
                try:
                    os.replace(bak, path)
                except Exception:
                    # The recoverable original stays at <final>.bak; do
                    # NOT delete it. Surface this as a typed failure below.
                    restore_failures.append(path)
        for tmp in tmp_paths:
            _quiet_unlink(tmp)

        if restore_failures:
            raise DatasetRecoveryError(
                "Export failed and the previous dataset could not be fully "
                "restored. Recoverable originals remain at '<name>.bak' "
                "for: " + ", ".join(sorted(p.name for p in restore_failures))
            ) from commit_exc
        # Previous dataset fully restored (or never existed) — re-raise the
        # original commit failure so the caller sees the root cause.
        raise
    else:
        # Success — drop the now-redundant backups; temps were consumed by
        # stage-3 promotion.
        for _, bak in backups:
            _quiet_unlink(bak)


# ── Exporter ─────────────────────────────────────────────────────────────────


class DatasetExporter:
    """Orchestrator. Stateless across runs; takes ``ExportConfig`` per call."""

    def __init__(self, config: ExportConfig) -> None:
        self._config = config

    # ── Public entry point ─────────────────────────────────────────────────

    def export(
        self, candidates: Iterable[TrainingCandidate]
    ) -> DatasetReport:
        """
        Run the export pipeline and write all three files atomically.
        Returns the typed report. Strict mode: raises
        ``StrictPrivacyViolation`` on the first unresolved credential —
        no files are written.
        """
        cfg = self._config

        # Resolve all output paths up front (path confinement before any work).
        sft_path    = _confined_inside(cfg.export_root, cfg.sft_filename)
        dpo_path    = _confined_inside(cfg.export_root, cfg.dpo_filename)
        report_path = _confined_inside(cfg.export_root, cfg.report_filename)

        # Fail closed: refuse to export without provenance verification.
        # (After path confinement so invalid paths still surface first.)
        if cfg.verifier is None:
            raise ExporterConfigurationError(
                "No provenance verifier configured. Supply a "
                "WorkLedgerVerifier (production) or AcceptAllVerifier "
                "(offline demo / unit tests) on ExportConfig.verifier — "
                "the exporter will not emit unverified training data."
            )

        sft_records:   list[SFTExample]      = []
        dpo_records:   list[DPOPair]         = []
        rejections:    list[RejectionRecord] = []
        seen_sft:      set[str] = set()
        seen_dpo:      set[str] = set()

        total_candidates = 0

        for candidate in candidates:
            total_candidates += 1
            self._process(
                candidate,
                sft_records=sft_records, dpo_records=dpo_records,
                rejections=rejections,
                seen_sft=seen_sft, seen_dpo=seen_dpo,
            )

        # Deterministic ordering for both files.
        sft_records.sort(key=lambda e: (e.skill_name, e.example_id))
        dpo_records.sort(key=lambda p: (p.skill_name, p.pair_id))

        report = self._build_report(
            total_candidates=total_candidates,
            sft_records=sft_records, dpo_records=dpo_records,
            rejections=rejections,
        )

        # Transactional 3-file commit — all-or-nothing, and a failure
        # restores any previously written dataset rather than destroying it.
        _commit_all_files([
            (sft_path,    _jsonl(sft_records)),
            (dpo_path,    _jsonl(dpo_records)),
            (report_path, json.dumps(report.model_dump(), indent=2, sort_keys=True)),
        ])
        return report

    # ── Per-candidate pipeline ─────────────────────────────────────────────

    def _process(
        self,
        candidate: TrainingCandidate,
        *,
        sft_records:   list[SFTExample],
        dpo_records:   list[DPOPair],
        rejections:    list[RejectionRecord],
        seen_sft:      set[str],
        seen_dpo:      set[str],
    ) -> None:
        cfg = self._config

        # 1. Provenance — fail closed if missing.
        if not candidate.provenance:
            rejections.append(_reject(
                candidate, RejectionReason.missing_provenance,
            ))
            return

        # 2. Structural-identifier / provenance credentials — scanned
        #    FIRST, before any verification log can echo a credential-shaped
        #    task_id or skill_name. ALWAYS reject (never redact): redacting
        #    a ledger reference would destroy its ability to resolve back to
        #    the Work Ledger, defeating auditability. Strict mode aborts the
        #    whole export.
        structural_hits = scan_structural_identifiers_for_credentials(candidate)
        if structural_hits:
            if cfg.strict_privacy:
                _log.error(
                    "Strict-mode privacy violation (structural identifier): %s",
                    safe_summary(
                        task_id=candidate.task_id,
                        primary=RejectionReason.for_privacy.value,
                        skill_name=candidate.skill_name,
                        hit_fields=structural_hits,
                    ),
                )
                raise StrictPrivacyViolation(
                    "Credential pattern in a structural identifier; "
                    "refusing to export."
                )
            rejections.append(_reject(
                candidate, RejectionReason.for_privacy,
                summary_extra="structural_identifier_credential",
            ))
            return

        # 3. Ledger verification — the verifier corroborates the candidate
        #    against per-task ledger views (events belong to the task, and
        #    the required content_hash / outcome / correction evidence is
        #    present and matches). Runs AFTER the structural scan so a
        #    poisoned identifier can never reach this log. ``export()`` has
        #    already guaranteed a verifier is configured (fail-closed).
        errors = cfg.verifier.verify(candidate)
        if errors:
            _log.warning(
                "Unverified provenance: %s",
                safe_summary(
                    task_id=candidate.task_id,
                    primary=RejectionReason.unverified_provenance.value,
                    skill_name=candidate.skill_name,
                ),
            )
            rejections.append(_reject(
                candidate, RejectionReason.unverified_provenance,
            ))
            return

        # 4. Sensitivity gate.
        if candidate.sensitivity in (Sensitivity.confidential, Sensitivity.restricted):
            rejections.append(_reject(
                candidate, RejectionReason.for_sensitivity,
            ))
            return
        if candidate.sensitivity is Sensitivity.unknown:
            rejections.append(_reject(
                candidate, RejectionReason.for_sensitivity,
            ))
            return

        if not candidate.allowed_for_training:
            rejections.append(_reject(
                candidate, RejectionReason.for_sensitivity,
                summary_extra="allowed_for_training=False",
            ))
            return

        # 5. Free-text content credentials — strict aborts the whole run;
        #    non-strict rejects this candidate. We NEVER redact-and-export.
        #    The candidate was just verified against the ledger by its
        #    ``content_hash`` (steps 3 above; verifier points 3–5). Redacting
        #    would mutate the content and recompute that hash, producing a
        #    DERIVED artifact that NO ledger event authorises — silently
        #    breaking the content-hash binding. Exported content is always
        #    the exact content a ledger event approved by hash; credential-
        #    bearing content cannot meet that bar, so it is rejected.
        text_hits = scan_text_fields_for_credentials(candidate)
        if text_hits:
            if cfg.strict_privacy:
                _log.error(
                    "Strict-mode privacy violation: %s",
                    safe_summary(
                        task_id=candidate.task_id,
                        primary=RejectionReason.for_privacy.value,
                        skill_name=candidate.skill_name,
                        hit_fields=text_hits,
                    ),
                )
                raise StrictPrivacyViolation(
                    "Unresolved credential pattern in candidate content; "
                    "refusing to export."
                )
            rejections.append(_reject(
                candidate, RejectionReason.for_privacy,
            ))
            return

        # 6. Branch: try SFT then DPO.
        sft_made = self._maybe_make_sft(
            candidate, sft_records, seen_sft, rejections,
        )
        dpo_made = self._maybe_make_dpo(
            candidate, dpo_records, seen_dpo, rejections,
        )

        if (
            not sft_made and not dpo_made
            and not any(r.task_id == candidate.task_id for r in rejections)
        ):
            rejections.append(_reject(
                candidate, RejectionReason.missing_content,
            ))

    # ── SFT branch ─────────────────────────────────────────────────────────

    def _maybe_make_sft(
        self,
        candidate: TrainingCandidate,
        sft_records: list[SFTExample],
        seen_sft: set[str],
        rejections: list[RejectionRecord],
    ) -> bool:
        if not candidate.has_sft_content:
            return False

        if not candidate.outcome_label:
            rejections.append(_reject(
                candidate, RejectionReason.missing_label,
            ))
            return False
        if not candidate.has_positive_outcome:
            rejections.append(_reject(
                candidate, RejectionReason.missing_label,
                summary_extra=f"outcome={candidate.outcome_label!r}",
            ))
            return False

        if fails_minimum_output_length(candidate, self._config.quality):
            rejections.append(_reject(
                candidate, RejectionReason.for_quality,
                summary_extra=(
                    f"output_len<{self._config.quality.minimum_output_length}"
                ),
            ))
            return False

        key = sft_dedup_key(candidate)
        if key in seen_sft:
            rejections.append(_reject(
                candidate, RejectionReason.duplicate,
            ))
            return False
        seen_sft.add(key)

        sft_records.append(SFTExample(
            example_id    = sft_example_id(candidate),
            task_id       = candidate.task_id,
            skill_name    = candidate.skill_name,
            input         = candidate.input_text or "",
            output        = candidate.output_text or "",
            source_events = sorted(candidate.provenance),
            artifact_id   = candidate.artifact_id,
            outcome_label = candidate.outcome_label or "",
            approved      = candidate.has_positive_outcome,
            quality_score = None,
            created_at    = candidate.created_at,
        ))
        return True

    # ── DPO branch ─────────────────────────────────────────────────────────

    def _maybe_make_dpo(
        self,
        candidate: TrainingCandidate,
        dpo_records: list[DPOPair],
        seen_dpo: set[str],
        rejections: list[RejectionRecord],
    ) -> bool:
        if malformed_correction_pair(candidate):
            rejections.append(_reject(
                candidate, RejectionReason.for_quality,
                summary_extra="malformed_correction_pair",
            ))
            return False
        if not candidate.has_dpo_content:
            return False

        if identical_chosen_rejected(candidate, self._config.quality):
            rejections.append(_reject(
                candidate, RejectionReason.for_quality,
                summary_extra="identical_chosen_rejected",
            ))
            return False

        key = dpo_dedup_key(candidate)
        if key in seen_dpo:
            rejections.append(_reject(
                candidate, RejectionReason.duplicate,
            ))
            return False
        seen_dpo.add(key)

        dpo_records.append(DPOPair(
            pair_id       = dpo_pair_id(candidate),
            task_id       = candidate.task_id,
            skill_name    = candidate.skill_name,
            prompt        = candidate.input_text or "",
            chosen        = candidate.corrected_output or "",
            rejected      = candidate.rejected_output or "",
            correction    = candidate.corrected_output or "",
            source_events = sorted(candidate.provenance),
            artifact_id   = candidate.artifact_id,
            created_at    = candidate.created_at,
        ))
        return True

    # ── Report ─────────────────────────────────────────────────────────────

    def _build_report(
        self,
        *,
        total_candidates: int,
        sft_records:      list[SFTExample],
        dpo_records:      list[DPOPair],
        rejections:       list[RejectionRecord],
    ) -> DatasetReport:
        cfg = self._config

        examples_by_skill: dict[str, int] = {}
        for e in sft_records:
            examples_by_skill[e.skill_name] = examples_by_skill.get(e.skill_name, 0) + 1
        pairs_by_skill: dict[str, int] = {}
        for p in dpo_records:
            pairs_by_skill[p.skill_name] = pairs_by_skill.get(p.skill_name, 0) + 1

        def count(reason: RejectionReason) -> int:
            return sum(1 for r in rejections if r.primary == reason)

        # Track ALL skills that appeared in any candidate (including rejected
        # ones) so that a skill with only rejected candidates is still counted
        # as below-threshold rather than silently omitted.
        all_skills: set[str] = set(examples_by_skill.keys())
        for r in rejections:
            if r.skill_name:
                all_skills.add(r.skill_name)

        skills_below = sorted(
            s for s in all_skills
            if examples_by_skill.get(s, 0) < cfg.quality.minimum_examples_per_skill
        )

        rejected_for_privacy            = count(RejectionReason.for_privacy)
        rejected_unverified_provenance  = count(RejectionReason.unverified_provenance)

        readiness = assess_readiness(
            total_sft_examples              = len(sft_records),
            examples_by_skill               = examples_by_skill,
            minimum_examples_per_skill      = cfg.quality.minimum_examples_per_skill,
            rejected_for_privacy            = rejected_for_privacy,
            rejected_unverified_provenance  = rejected_unverified_provenance,
            skills_below_threshold          = skills_below,
        )

        return DatasetReport(
            total_candidates                = total_candidates,
            total_sft_examples              = len(sft_records),
            total_dpo_pairs                 = len(dpo_records),
            examples_by_skill               = dict(sorted(examples_by_skill.items())),
            pairs_by_skill                  = dict(sorted(pairs_by_skill.items())),
            rejected_missing_provenance     = count(RejectionReason.missing_provenance),
            rejected_missing_label          = count(RejectionReason.missing_label),
            rejected_missing_content        = count(RejectionReason.missing_content),
            rejected_for_sensitivity        = count(RejectionReason.for_sensitivity),
            rejected_for_privacy            = rejected_for_privacy,
            rejected_for_quality            = count(RejectionReason.for_quality),
            rejected_duplicate              = count(RejectionReason.duplicate),
            rejected_unverified_provenance  = rejected_unverified_provenance,
            skills_below_50_examples        = skills_below,
            minimum_examples_per_skill      = cfg.quality.minimum_examples_per_skill,
            ready_for_finetuning            = readiness.ready,
            recommended_next_action         = readiness.next_action,
        )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _reject(
    candidate: TrainingCandidate,
    primary:   RejectionReason,
    *,
    summary_extra: Optional[str] = None,
    diagnostics:   Optional[list[RejectionReason]] = None,
) -> RejectionRecord:
    summary = safe_summary(
        task_id=candidate.task_id, primary=primary.value,
        skill_name=candidate.skill_name,
    )
    if summary_extra:
        summary = f"{summary}; {summary_extra}"
    return RejectionRecord(
        task_id     = candidate.task_id,
        skill_name  = candidate.skill_name,
        primary     = primary,
        diagnostics = list(diagnostics or []),
        summary     = summary,
    )


def _jsonl(records: list) -> str:
    """Build a deterministic JSONL blob from a list of Pydantic models."""
    if not records:
        return ""
    lines = []
    for r in records:
        lines.append(json.dumps(r.model_dump(mode="json"), sort_keys=True))
    return "\n".join(lines) + "\n"
