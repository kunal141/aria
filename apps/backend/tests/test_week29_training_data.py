"""
Week 29 Priority 3 — Dataset Export Prototype tests.

Covers every Definition-of-Done requirement:
  - SFT example from completed task + explicit positive outcome
  - governance approval ALONE does NOT create an SFT example
  - DPO pair from explicit rejected + corrected outputs
  - missing input / output / label / provenance rejected
  - confidential / restricted candidate rejected
  - unknown sensitivity fails closed in strict mode
  - strict privacy violation aborts export (no files written)
  - credential-bearing content is rejected, never redacted-and-exported
  - secret never reaches output (rejected before any write)
  - arbitrary metadata is NOT interpreted as training content
  - legacy ledger records do NOT become examples automatically
  - duplicate examples deduplicated
  - deterministic content-hash IDs
  - deterministic output ordering (across runs)
  - identical chosen/rejected pair rejected
  - skill-wise counts computed
  - below-50 threshold reported
  - readiness stays false below thresholds
  - path traversal rejected
  - atomic write failure does not leave partial output
  - repeated export produces byte-identical files

PROTOTYPE ONLY. No LLM, network, or paid API calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from aria.training_data import (
    AcceptAllVerifier,
    DatasetExporter,
    DatasetRecoveryError,
    DatasetReport,
    DPOPair,
    ExporterConfigurationError,
    ExportPathError,
    LedgerAdapterError,
    LedgerCorrectionEvent,
    LedgerOutcomeEvent,
    LedgerTaskViewBuilder,
    RejectionReason,
    ResolvedContent,
    Sensitivity,
    SFTExample,
    StrictPrivacyViolation,
    TaskLedgerView,
    TrainingCandidate,
    WorkLedgerVerifier,
    canonical_content_hash,
)
from aria.ledger.events import (
    ActorType,
    CorrectionRecorded,
    OutcomeRecorded,
    SkillInvoked,
    make_envelope,
)
from aria.ledger.reader import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.training_data.exporter import ExportConfig
from aria.training_data.privacy import safe_summary
from aria.training_data.quality import QualityPolicy


# ── Shared helpers ───────────────────────────────────────────────────────────


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def _ts(seconds: int = 0) -> datetime:
    return datetime(2026, 6, 12, 9, 0, 0, tzinfo=timezone.utc).replace(
        microsecond=0,
    )


def _config(tmp_path: Path, *, strict: bool = True,
            min_per_skill: int = 50, min_output: int = 5,
            verifier=None) -> ExportConfig:
    # Inject an AcceptAllVerifier by default so tests that are NOT about
    # ledger verification still run (the exporter fails closed without a
    # verifier). Tests that exercise verification pass an explicit one.
    return ExportConfig(
        export_root=tmp_path,
        strict_privacy=strict,
        verifier=verifier if verifier is not None else AcceptAllVerifier(),
        quality=QualityPolicy(
            minimum_examples_per_skill=min_per_skill,
            minimum_output_length=min_output,
        ),
    )


def _canon_hash(fields: dict) -> str:
    return canonical_content_hash(
        task_id=fields["task_id"],
        skill_name=fields["skill_name"],
        input_text=fields.get("input_text"),
        output_text=fields.get("output_text"),
        rejected_output=fields.get("rejected_output"),
        corrected_output=fields.get("corrected_output"),
    )


def _good_sft_candidate(**overrides) -> TrainingCandidate:
    defaults = dict(
        task_id="task-001",
        skill_name="pr_review",
        input_text="Review PR #42 in recommendation-service.",
        output_text="Risk MEDIUM. Add edge-case test for empty candidates.",
        rejected_output=None,
        corrected_output=None,
        artifact_id="art-001",
        sensitivity=Sensitivity.public,
        allowed_for_training=True,
        provenance=["evt-001"],
        outcome_label="approved",
        created_at=_ts(),
    )
    defaults.update(overrides)
    # Auto-compute the canonical content hash from the (possibly
    # overridden) content unless the caller explicitly supplied one (the
    # invalid-hash tests do).
    if "content_hash" not in overrides:
        defaults["content_hash"] = _canon_hash(defaults)
    return TrainingCandidate(**defaults)


def _good_dpo_candidate(**overrides) -> TrainingCandidate:
    defaults = dict(
        task_id="task-dpo-001",
        skill_name="pr_review",
        input_text="Review PR #43 in recommendation-service.",
        output_text=None,
        rejected_output="ship it",
        corrected_output="Risk MEDIUM — needs a regression test before deploy.",
        artifact_id="art-dpo-001",
        sensitivity=Sensitivity.public,
        allowed_for_training=True,
        provenance=["evt-correction-001"],
        outcome_label=None,
        created_at=_ts(),
    )
    defaults.update(overrides)
    if "content_hash" not in overrides:
        defaults["content_hash"] = _canon_hash(defaults)
    return TrainingCandidate(**defaults)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ── Section A — SFT happy / governance not enough / DPO happy ───────────────


def test_sft_example_from_completed_task_with_positive_outcome(tmp_path):
    exp = DatasetExporter(_config(tmp_path))
    report = exp.export([_good_sft_candidate()])
    assert report.total_sft_examples == 1
    sft = _read_jsonl(tmp_path / "sft_examples.jsonl")
    assert sft[0]["task_id"] == "task-001"
    assert sft[0]["skill_name"] == "pr_review"
    assert sft[0]["approved"] is True
    assert sft[0]["outcome_label"] == "approved"
    assert sft[0]["quality_score"] is None
    assert sft[0]["source_events"] == ["evt-001"]


def test_governance_approval_alone_does_not_make_sft_example(tmp_path):
    """
    Governance ``Approved`` is an action decision. Without an explicit
    positive OutcomeRecorded label on the candidate it MUST NOT become
    an SFT example.
    """
    candidate = _good_sft_candidate(outcome_label=None)
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.total_sft_examples == 0
    assert report.rejected_missing_label == 1


def test_dpo_pair_from_explicit_rejected_and_corrected(tmp_path):
    report = DatasetExporter(_config(tmp_path)).export([_good_dpo_candidate()])
    assert report.total_dpo_pairs == 1
    dpo = _read_jsonl(tmp_path / "dpo_pairs.jsonl")
    assert dpo[0]["task_id"] == "task-dpo-001"
    assert dpo[0]["chosen"]   == "Risk MEDIUM — needs a regression test before deploy."
    assert dpo[0]["rejected"] == "ship it"
    assert dpo[0]["correction"] == dpo[0]["chosen"]


# ── Section B — Missing-content / label / provenance ────────────────────────


def test_missing_input_rejected(tmp_path):
    candidate = _good_sft_candidate(input_text=None)
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.total_sft_examples == 0
    assert report.rejected_missing_content == 1


def test_missing_output_rejected(tmp_path):
    candidate = _good_sft_candidate(output_text=None)
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.total_sft_examples == 0
    assert report.rejected_missing_content == 1


def test_missing_label_rejected(tmp_path):
    candidate = _good_sft_candidate(outcome_label=None)
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.rejected_missing_label == 1


def test_missing_provenance_rejected(tmp_path):
    candidate = _good_sft_candidate(provenance=[])
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.rejected_missing_provenance == 1


# ── Section C — Sensitivity / training-allowed ──────────────────────────────


def test_confidential_candidate_rejected(tmp_path):
    candidate = _good_sft_candidate(sensitivity=Sensitivity.confidential)
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.rejected_for_sensitivity == 1
    assert report.total_sft_examples == 0


def test_restricted_candidate_rejected(tmp_path):
    candidate = _good_sft_candidate(sensitivity=Sensitivity.restricted)
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.rejected_for_sensitivity == 1


def test_unknown_sensitivity_fails_closed_in_strict_mode(tmp_path):
    candidate = _good_sft_candidate(sensitivity=Sensitivity.unknown)
    report = DatasetExporter(_config(tmp_path, strict=True)).export([candidate])
    assert report.rejected_for_sensitivity == 1


def test_unknown_sensitivity_still_rejected_in_non_strict_mode(tmp_path):
    """Non-strict relaxes PRIVACY, not sensitivity gating."""
    candidate = _good_sft_candidate(sensitivity=Sensitivity.unknown)
    report = DatasetExporter(_config(tmp_path, strict=False)).export([candidate])
    assert report.rejected_for_sensitivity == 1


def test_allowed_for_training_false_rejected(tmp_path):
    candidate = _good_sft_candidate(allowed_for_training=False)
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.rejected_for_sensitivity == 1


# ── Section D — Privacy ────────────────────────────────────────────────────


def test_strict_privacy_violation_aborts_export(tmp_path):
    leaky = _good_sft_candidate(
        output_text="here is the token sk-1234567890abcdef",
        task_id="task-leak",
    )
    clean = _good_sft_candidate(task_id="task-clean")
    with pytest.raises(StrictPrivacyViolation):
        DatasetExporter(_config(tmp_path, strict=True)).export([clean, leaky])
    # No files written on abort.
    assert not (tmp_path / "sft_examples.jsonl").exists()
    assert not (tmp_path / "dpo_pairs.jsonl").exists()
    assert not (tmp_path / "dataset_report.json").exists()


def test_non_strict_credential_content_rejected_never_redacted(tmp_path):
    """
    Non-strict mode does NOT redact-and-export credential-bearing content.
    Redaction would mutate the content and recompute its content_hash,
    producing a derived artifact no ledger event authorises — breaking the
    content-hash binding. The candidate is rejected for privacy and the
    secret never reaches disk.
    """
    leaky = _good_sft_candidate(
        output_text="ok use ghp_aaaaaaaaaaaaaaaaaaaa for auth",
        task_id="task-redact",
    )
    cfg = _config(tmp_path, strict=False)
    report = DatasetExporter(cfg).export([leaky])
    assert report.rejected_for_privacy == 1
    assert report.total_sft_examples == 0
    # Nothing written, so the secret cannot have leaked to the file.
    assert _read_jsonl(tmp_path / "sft_examples.jsonl") == []


def test_non_strict_secret_never_reaches_output(tmp_path):
    """
    A credential in training content is rejected BEFORE any write — the
    secret never lands in the dataset file in any form (masked or raw).
    """
    leaky = _good_sft_candidate(
        output_text="see token ghp_aaaaaaaaaaaaaaaaaaaa",
        task_id="task-noredact",
    )
    cfg = _config(tmp_path, strict=False)
    report = DatasetExporter(cfg).export([leaky])
    assert report.rejected_for_privacy == 1
    sft = _read_jsonl(tmp_path / "sft_examples.jsonl")
    assert sft == []


def test_credential_in_input_field_also_caught(tmp_path):
    leaky = _good_sft_candidate(
        input_text="use token sk-ant-1234567890abcdef please",
        task_id="task-input-leak",
    )
    with pytest.raises(StrictPrivacyViolation):
        DatasetExporter(_config(tmp_path, strict=True)).export([leaky])


def test_arbitrary_metadata_is_not_interpreted_as_training_content(tmp_path):
    """
    The exporter has no access to ``metadata`` on a TrainingCandidate.
    Even if a caller stuffs free text into ``artifact_id`` (a structural
    identifier), it is NOT used as input/output text.
    """
    candidate = _good_sft_candidate(
        input_text="legit input",
        output_text="legit output that is plenty long",
        artifact_id="this is not training content",
    )
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.total_sft_examples == 1
    sft = _read_jsonl(tmp_path / "sft_examples.jsonl")
    assert sft[0]["input"] == "legit input"
    assert sft[0]["output"] == "legit output that is plenty long"
    # artifact_id retained for provenance but NOT injected as input/output.
    assert "not training content" not in sft[0]["input"]
    assert "not training content" not in sft[0]["output"]


def test_legacy_ledger_records_do_not_become_examples_automatically(tmp_path):
    """
    The exporter consumes ``TrainingCandidate`` objects only — there is
    no path from a raw ``LegacyTaskRecord`` into the pipeline. A caller
    who wants to map legacy records into training data must build a
    typed candidate explicitly (and supply provenance / sensitivity /
    label / content) — there is no implicit conversion.
    """
    from aria.ledger import LegacyTaskRecord
    legacy = LegacyTaskRecord(
        task_id="legacy-1", task_type="pr_review", routing_reason="kw",
        timestamp=datetime(2026, 6, 4, 9, 10, 1, tzinfo=timezone.utc),
        week=4,
    )
    # The exporter accepts an Iterable[TrainingCandidate]; legacy records
    # are NOT TrainingCandidate, so callers must not pass them. We verify
    # that doing so raises rather than silently coercing.
    with pytest.raises(Exception):
        DatasetExporter(_config(tmp_path)).export([legacy])


# ── Section E — Quality ────────────────────────────────────────────────────


def test_output_below_minimum_length_rejected_for_quality(tmp_path):
    short = _good_sft_candidate(output_text="ok", task_id="task-short")
    report = DatasetExporter(_config(tmp_path)).export([short])
    assert report.rejected_for_quality == 1


def test_identical_chosen_and_rejected_dpo_rejected(tmp_path):
    same = _good_dpo_candidate(
        rejected_output="same answer",
        corrected_output="same answer",
        task_id="task-dpo-same",
    )
    report = DatasetExporter(_config(tmp_path)).export([same])
    assert report.total_dpo_pairs == 0
    assert report.rejected_for_quality == 1


def test_malformed_correction_pair_only_rejected(tmp_path):
    """rejected XOR corrected without the other side."""
    half = _good_dpo_candidate(
        rejected_output="bad answer",
        corrected_output=None,
        task_id="task-half-dpo",
    )
    report = DatasetExporter(_config(tmp_path)).export([half])
    assert report.rejected_for_quality == 1


# ── Section F — Dedup ──────────────────────────────────────────────────────


def test_duplicate_sft_examples_deduplicated(tmp_path):
    a = _good_sft_candidate(task_id="task-dup-a")
    b = _good_sft_candidate(task_id="task-dup-b")  # same content, different task
    report = DatasetExporter(_config(tmp_path)).export([a, b])
    assert report.total_sft_examples == 1
    assert report.rejected_duplicate == 1


def test_duplicate_dpo_pairs_deduplicated(tmp_path):
    a = _good_dpo_candidate(task_id="task-dpo-a")
    b = _good_dpo_candidate(task_id="task-dpo-b")
    report = DatasetExporter(_config(tmp_path)).export([a, b])
    assert report.total_dpo_pairs == 1
    assert report.rejected_duplicate == 1


# ── Section G — Deterministic IDs and ordering ─────────────────────────────


def test_deterministic_content_hash_ids(tmp_path):
    a = _good_sft_candidate(task_id="t-A")
    b = _good_sft_candidate(task_id="t-B", input_text="completely different input",
                              output_text="completely different output text")
    exp = DatasetExporter(_config(tmp_path))
    exp.export([a, b])
    sft = _read_jsonl(tmp_path / "sft_examples.jsonl")
    ids = [r["example_id"] for r in sft]
    # IDs are deterministic for the content; re-running with the same
    # candidates produces the SAME ids.
    (tmp_path / "x").mkdir()
    cfg2 = _config(tmp_path / "x")
    DatasetExporter(cfg2).export([a, b])
    sft2 = _read_jsonl(tmp_path / "x" / "sft_examples.jsonl")
    assert [r["example_id"] for r in sft2] == ids


def test_deterministic_output_ordering(tmp_path):
    """Inserted in different orders, the output is byte-identical."""
    c1 = _good_sft_candidate(task_id="t-1", input_text="x", output_text="output one")
    c2 = _good_sft_candidate(task_id="t-2", skill_name="kpi",
                              input_text="y", output_text="output two")
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    DatasetExporter(_config(a)).export([c1, c2])
    DatasetExporter(_config(b)).export([c2, c1])
    assert (a / "sft_examples.jsonl").read_bytes() \
        == (b / "sft_examples.jsonl").read_bytes()


def test_repeated_export_produces_byte_identical_files(tmp_path):
    candidates = [
        _good_sft_candidate(task_id="t-A"),
        _good_sft_candidate(task_id="t-B",
                            input_text="other input",
                            output_text="other output sufficient length"),
        _good_dpo_candidate(task_id="t-D"),
    ]
    a = tmp_path / "run-a"; a.mkdir()
    b = tmp_path / "run-b"; b.mkdir()
    DatasetExporter(_config(a)).export(candidates)
    DatasetExporter(_config(b)).export(candidates)
    for fname in ("sft_examples.jsonl", "dpo_pairs.jsonl", "dataset_report.json"):
        assert (a / fname).read_bytes() == (b / fname).read_bytes(), (
            f"{fname} differs between runs — output is not deterministic"
        )


# ── Section H — Skill counts / readiness ──────────────────────────────────


def test_skill_wise_counts_in_report(tmp_path):
    a = _good_sft_candidate(task_id="pr-1")
    b = _good_sft_candidate(task_id="pr-2",
                             input_text="other pr input",
                             output_text="other pr output sufficient length")
    c = _good_sft_candidate(task_id="kpi-1", skill_name="kpi",
                             input_text="kpi input",
                             output_text="kpi output sufficient length")
    report = DatasetExporter(_config(tmp_path)).export([a, b, c])
    assert report.examples_by_skill == {"pr_review": 2, "kpi": 1}


def test_below_50_threshold_reported(tmp_path):
    a = _good_sft_candidate(task_id="pr-only")
    report = DatasetExporter(_config(tmp_path)).export([a])
    assert "pr_review" in report.skills_below_50_examples
    assert report.minimum_examples_per_skill == 50


def test_ready_for_finetuning_stays_false_below_threshold(tmp_path):
    a = _good_sft_candidate(task_id="pr-only")
    report = DatasetExporter(_config(tmp_path)).export([a])
    assert report.ready_for_finetuning is False
    assert "below" in report.recommended_next_action.lower() or "collect" in report.recommended_next_action.lower()


def test_ready_for_finetuning_true_when_thresholds_met(tmp_path):
    candidates = [
        _good_sft_candidate(
            task_id=f"t-{i}",
            input_text=f"input {i}",
            output_text=f"output {i} of sufficient length to pass min-len",
        )
        for i in range(3)
    ]
    cfg = _config(tmp_path, min_per_skill=3)
    report = DatasetExporter(cfg).export(candidates)
    assert report.examples_by_skill["pr_review"] == 3
    assert report.ready_for_finetuning is True
    assert "ready" in report.recommended_next_action.lower()


def test_ready_stays_false_with_unresolved_privacy(tmp_path):
    """Even meeting count thresholds, any unresolved privacy keeps readiness false."""
    candidates = [
        _good_sft_candidate(task_id=f"t-{i}",
                             input_text=f"in {i}", output_text=f"output {i} adequate length")
        for i in range(3)
    ]
    candidates.append(_good_sft_candidate(
        task_id="t-leak",
        input_text="x", output_text="leak ghp_aaaaaaaaaaaaaaaaaaaa",
    ))
    cfg = _config(tmp_path, strict=False, min_per_skill=3)
    report = DatasetExporter(cfg).export(candidates)
    assert report.rejected_for_privacy == 1
    assert report.ready_for_finetuning is False


# ── Section I — Path confinement ──────────────────────────────────────────


def test_path_traversal_in_filename_rejected(tmp_path):
    cfg = ExportConfig(
        export_root=tmp_path,
        sft_filename="../escape.jsonl",
        dpo_filename="dpo.jsonl",
        report_filename="report.json",
    )
    with pytest.raises(ExportPathError):
        DatasetExporter(cfg).export([_good_sft_candidate()])


def test_path_traversal_via_separator_in_filename_rejected(tmp_path):
    for bad in ("foo/bar.jsonl", "foo\\bar.jsonl"):
        cfg = ExportConfig(
            export_root=tmp_path, sft_filename=bad,
            dpo_filename="dpo.jsonl", report_filename="report.json",
        )
        with pytest.raises(ExportPathError):
            DatasetExporter(cfg).export([_good_sft_candidate()])


def test_empty_filename_rejected(tmp_path):
    cfg = ExportConfig(
        export_root=tmp_path, sft_filename="",
        dpo_filename="dpo.jsonl", report_filename="report.json",
    )
    with pytest.raises(ExportPathError):
        DatasetExporter(cfg).export([_good_sft_candidate()])


# ── Section J — Atomic / transactional writes ─────────────────────────────


def _fail_replace_on_dpo(real_replace):
    """
    Return an os.replace wrapper that raises only when PROMOTING the dpo
    temp to its final path (stage-3, second file). Backup moves (stage-2,
    src is the final, not a .tmp) pass through to the real os.replace so
    the failure exercises a genuine partial-commit.
    """
    def flaky(src, dst):
        if str(src).endswith(".tmp") and str(dst).endswith("dpo_pairs.jsonl"):
            raise OSError("simulated disk failure promoting dpo file")
        return real_replace(src, dst)
    return flaky


def test_commit_failure_on_fresh_dir_leaves_no_partial_output(tmp_path):
    """
    Real os.replace failure on the second file (no prior dataset): none
    of the three finals exist, and no ``.tmp`` / ``.bak`` remain.
    """
    import aria.training_data.exporter as exp_mod

    real_replace = exp_mod.os.replace
    with patch.object(exp_mod.os, "replace", _fail_replace_on_dpo(real_replace)):
        with pytest.raises(OSError):
            DatasetExporter(_config(tmp_path)).export([_good_sft_candidate()])

    assert not (tmp_path / "sft_examples.jsonl").exists()
    assert not (tmp_path / "dpo_pairs.jsonl").exists()
    assert not (tmp_path / "dataset_report.json").exists()
    for child in tmp_path.iterdir():
        assert not child.name.endswith((".tmp", ".bak")), (
            f"Partial write left behind: {child}"
        )


def test_commit_failure_restores_previous_dataset(tmp_path):
    """
    A failed second export must NOT destroy the dataset written by a
    prior successful export — the originals are restored byte-for-byte
    and no ``.tmp`` / ``.bak`` remain.
    """
    import aria.training_data.exporter as exp_mod

    # First export succeeds and populates the directory.
    first = _good_sft_candidate(
        task_id="t-first",
        input_text="first input",
        output_text="first output sufficiently long",
    )
    DatasetExporter(_config(tmp_path)).export([first])
    original_sft    = (tmp_path / "sft_examples.jsonl").read_bytes()
    original_dpo    = (tmp_path / "dpo_pairs.jsonl").read_bytes()
    original_report = (tmp_path / "dataset_report.json").read_bytes()

    # Second export has different content but the dpo promotion fails.
    second = _good_sft_candidate(
        task_id="t-second",
        input_text="second input",
        output_text="second output sufficiently long",
    )
    real_replace = exp_mod.os.replace
    with patch.object(exp_mod.os, "replace", _fail_replace_on_dpo(real_replace)):
        with pytest.raises(OSError):
            DatasetExporter(_config(tmp_path)).export([second])

    # Previous dataset fully restored.
    assert (tmp_path / "sft_examples.jsonl").read_bytes() == original_sft
    assert (tmp_path / "dpo_pairs.jsonl").read_bytes() == original_dpo
    assert (tmp_path / "dataset_report.json").read_bytes() == original_report
    # No stray transactional artifacts.
    for child in tmp_path.iterdir():
        assert not child.name.endswith((".tmp", ".bak")), (
            f"Transactional artifact left behind: {child}"
        )


def _fail_dpo_promote_and_sft_restore(real_replace):
    """
    Fail promoting the dpo temp (triggers rollback) AND fail restoring the
    sft backup during rollback — reproduces a partial-restoration fault
    where the previous sft file cannot be put back.
    """
    def flaky(src, dst):
        s, d = str(src), str(dst)
        # Stage-3 dpo promotion fails → triggers rollback.
        if s.endswith(".tmp") and d.endswith("dpo_pairs.jsonl"):
            raise OSError("simulated disk failure promoting dpo file")
        # Rollback's sft restore (bak → final) fails too.
        if s.endswith("sft_examples.jsonl.bak") and d.endswith("sft_examples.jsonl"):
            raise OSError("simulated disk failure restoring sft backup")
        return real_replace(src, dst)
    return flaky


def test_rollback_restoration_failure_surfaces_typed_error(tmp_path):
    """
    A failed export whose rollback ALSO fails to restore a previous file
    must raise a typed ``DatasetRecoveryError`` (never silently leave a
    half-restored dataset). The unrestored file's recoverable ``.bak``
    backup is preserved; the files that COULD be restored are restored.
    """
    import aria.training_data.exporter as exp_mod

    # Seed a prior successful dataset.
    first = _good_sft_candidate(
        task_id="t-first", input_text="first input",
        output_text="first output sufficiently long",
    )
    DatasetExporter(_config(tmp_path)).export([first])
    original_dpo    = (tmp_path / "dpo_pairs.jsonl").read_bytes()
    original_report = (tmp_path / "dataset_report.json").read_bytes()

    second = _good_sft_candidate(
        task_id="t-second", input_text="second input",
        output_text="second output sufficiently long",
    )
    real_replace = exp_mod.os.replace
    with patch.object(exp_mod.os, "replace",
                      _fail_dpo_promote_and_sft_restore(real_replace)):
        with pytest.raises(DatasetRecoveryError):
            DatasetExporter(_config(tmp_path)).export([second])

    # sft could not be restored → it is missing, but its recoverable backup
    # remains for manual recovery (NOT silently dropped).
    assert not (tmp_path / "sft_examples.jsonl").exists()
    assert (tmp_path / "sft_examples.jsonl.bak").exists()
    # The files that COULD be restored were restored byte-for-byte.
    assert (tmp_path / "dpo_pairs.jsonl").read_bytes() == original_dpo
    assert (tmp_path / "dataset_report.json").read_bytes() == original_report


# ── Section J2 — P2: unresolved recovery backup blocks a retry ──────────────


def test_preexisting_recovery_backup_blocks_export(tmp_path):
    """
    A leftover ``.bak`` is the ONLY recoverable copy of a previous dataset
    after a ``DatasetRecoveryError``. A retry must FAIL CLOSED rather than
    overwrite-then-delete it (Codex P2 probe: "sft.bak existed before
    retry / sft.bak missing after retry / new SFT installed").

    This reproduces the probe's precondition — both the current final and
    an unresolved ``.bak`` present — and proves the opposite now holds: the
    backup is preserved byte-for-byte, the export refuses before staging
    anything, and no new dataset is installed over the recoverable copy.
    """
    backup_bytes  = b'{"recoverable":"previous sft dataset"}\n'
    current_bytes = b'{"current":"sft final present"}\n'
    (tmp_path / "sft_examples.jsonl").write_bytes(current_bytes)
    (tmp_path / "sft_examples.jsonl.bak").write_bytes(backup_bytes)

    with pytest.raises(DatasetRecoveryError):
        DatasetExporter(_config(tmp_path)).export([_good_sft_candidate()])

    # The recoverable backup is untouched — never overwritten, never deleted.
    assert (tmp_path / "sft_examples.jsonl.bak").read_bytes() == backup_bytes
    # The export refused before staging: current final intact, no new SFT
    # installed over it, no stray temp.
    assert (tmp_path / "sft_examples.jsonl").read_bytes() == current_bytes
    assert not (tmp_path / "sft_examples.jsonl.tmp").exists()


def test_export_succeeds_after_recovery_backup_is_resolved(tmp_path):
    """
    Once the operator resolves the leftover ``.bak`` (restores or removes
    it), a subsequent export proceeds normally — the guard only blocks the
    UNRESOLVED state, it is not a permanent lock.
    """
    (tmp_path / "sft_examples.jsonl").write_bytes(b'{"current":"x"}\n')
    (tmp_path / "sft_examples.jsonl.bak").write_bytes(b'{"recoverable":"y"}\n')

    # Operator resolves the recovery: removes the stale backup.
    (tmp_path / "sft_examples.jsonl.bak").unlink()

    report = DatasetExporter(_config(tmp_path)).export([_good_sft_candidate()])
    assert report.total_sft_examples == 1
    # Clean state: a successful export leaves no transactional artifacts.
    for child in tmp_path.iterdir():
        assert not child.name.endswith((".tmp", ".bak"))


# ── Section K — Privacy summary safety ────────────────────────────────────


def test_rejection_summary_never_contains_raw_content(tmp_path):
    leaky_payload = "secret sk-1234567890abcdef do not log this"
    leaky = _good_sft_candidate(output_text=leaky_payload, task_id="task-leaky")
    cfg = _config(tmp_path, strict=False)
    report = DatasetExporter(cfg).export([leaky])
    # The report carries counts only — never the offending text.
    report_json = json.dumps(report.model_dump())
    assert "sk-1234567890abcdef" not in report_json
    assert leaky_payload not in report_json


# ── Section L — Sanity: empty input ──────────────────────────────────────


def test_empty_candidate_list_yields_empty_files_and_report(tmp_path):
    report = DatasetExporter(_config(tmp_path)).export([])
    assert report.total_candidates == 0
    assert report.total_sft_examples == 0
    assert report.total_dpo_pairs == 0
    assert (tmp_path / "sft_examples.jsonl").read_text(encoding="utf-8") == ""
    assert (tmp_path / "dpo_pairs.jsonl").read_text(encoding="utf-8") == ""
    rep = json.loads((tmp_path / "dataset_report.json").read_text(encoding="utf-8"))
    assert rep["ready_for_finetuning"] is False


# ── Section M — P1-1: secrets in provenance (new adversarial tests) ────────


def test_credential_in_provenance_strict_mode_aborts_export(tmp_path):
    """
    A ghp_ token embedded in a provenance event ID triggers
    StrictPrivacyViolation and leaves no files on disk.
    """
    candidate = _good_sft_candidate(
        task_id="task-prov-leak",
        provenance=["evt-ok", "ghp_aaaaaaaaaaaaaaaaaaaa"],
    )
    with pytest.raises(StrictPrivacyViolation):
        DatasetExporter(_config(tmp_path, strict=True)).export([candidate])
    assert not (tmp_path / "sft_examples.jsonl").exists()
    assert not (tmp_path / "dpo_pairs.jsonl").exists()
    assert not (tmp_path / "dataset_report.json").exists()


def test_credential_in_provenance_non_strict_no_redaction_rejects(tmp_path):
    """
    Non-strict + no redaction: provenance credential → rejected_for_privacy.
    """
    candidate = _good_sft_candidate(
        task_id="task-prov-reject",
        provenance=["ghp_aaaaaaaaaaaaaaaaaaaa"],
    )
    cfg = _config(tmp_path, strict=False)
    report = DatasetExporter(cfg).export([candidate])
    assert report.rejected_for_privacy == 1
    assert report.total_sft_examples == 0


def test_credential_in_provenance_rejected(tmp_path):
    """
    Provenance event IDs are ledger references, NOT content. A credential
    in a provenance ID rejects the candidate (redacting it would destroy
    ledger resolution). No example is produced and no identifier reaches
    source_events.
    """
    candidate = _good_sft_candidate(
        task_id="task-prov-redact",
        provenance=["ghp_aaaaaaaaaaaaaaaaaaaa"],
    )
    cfg = _config(tmp_path, strict=False)
    report = DatasetExporter(cfg).export([candidate])
    assert report.total_sft_examples == 0
    assert report.rejected_for_privacy == 1
    assert _read_jsonl(tmp_path / "sft_examples.jsonl") == []


def test_credential_in_artifact_id_rejected(tmp_path):
    """
    A credential embedded in a structural identifier (artifact_id) rejects
    the candidate in non-strict mode (structural IDs are never redacted).
    """
    candidate = _good_sft_candidate(
        task_id="task-artifact-leak",
        artifact_id="art-ghp_aaaaaaaaaaaaaaaaaaaa",
    )
    cfg = _config(tmp_path, strict=False)
    report = DatasetExporter(cfg).export([candidate])
    assert report.total_sft_examples == 0
    assert report.rejected_for_privacy == 1


def test_credential_in_structural_identifier_strict_aborts(tmp_path):
    """A credential in a structural identifier aborts the whole strict export."""
    candidate = _good_sft_candidate(
        task_id="task-artifact-strict",
        artifact_id="art-ghp_aaaaaaaaaaaaaaaaaaaa",
    )
    with pytest.raises(StrictPrivacyViolation):
        DatasetExporter(_config(tmp_path, strict=True)).export([candidate])
    assert not (tmp_path / "sft_examples.jsonl").exists()


# ── Section M2 — P1: structural credentials must never reach logs ───────────


def test_safe_summary_redacts_credential_shaped_identifiers():
    """
    ``safe_summary`` must never echo a raw credential-shaped identifier —
    a poisoned task_id / skill_name is passed through redaction first.
    """
    token = "ghp_aaaaaaaaaaaaaaaaaaaa"
    summary = safe_summary(
        task_id=token,
        primary=RejectionReason.for_privacy.value,
        skill_name=f"skill-{token}",
    )
    assert token not in summary
    assert "[REDACTED]" in summary


def test_safe_summary_preserves_ordinary_identifiers():
    """Ordinary identifiers are unchanged (redaction only rewrites secrets)."""
    summary = safe_summary(
        task_id="task-001",
        primary=RejectionReason.unverified_provenance.value,
        skill_name="pr_review",
    )
    assert "task-001" in summary
    assert "pr_review" in summary
    assert "[REDACTED]" not in summary


def test_structural_scan_precedes_verification_and_no_credential_logged(tmp_path, caplog):
    """
    A credential-shaped task_id is caught by the structural scan BEFORE
    ledger verification runs, so the verification path never executes (and
    never logs the raw identifier). The raw token appears in no log line.
    """
    token = "ghp_aaaaaaaaaaaaaaaaaaaa"
    candidate = _good_sft_candidate(task_id=token)
    # A real verifier whose views are empty WOULD log "Unverified
    # provenance" with the task_id — but structural rejection happens first,
    # so verification is never reached.
    verifier = WorkLedgerVerifier(task_views={})
    cfg = _verifier_cfg(tmp_path, verifier, strict=False)
    with caplog.at_level(logging.DEBUG, logger="aria.training_data.exporter"):
        report = DatasetExporter(cfg).export([candidate])
    assert report.rejected_for_privacy == 1
    assert report.rejected_unverified_provenance == 0   # verification not reached
    assert token not in caplog.text


def test_credential_task_id_redacted_in_strict_abort_log(tmp_path, caplog):
    """
    In strict mode a credential-shaped task_id aborts the export, and the
    abort log line carries only the redacted form — never the raw token.
    """
    token = "ghp_aaaaaaaaaaaaaaaaaaaa"
    candidate = _good_sft_candidate(task_id=token)
    cfg = _verifier_cfg(tmp_path, AcceptAllVerifier(), strict=True)
    with caplog.at_level(logging.DEBUG, logger="aria.training_data.exporter"):
        with pytest.raises(StrictPrivacyViolation):
            DatasetExporter(cfg).export([candidate])
    assert token not in caplog.text
    assert "[REDACTED]" in caplog.text


# ── Section N — P1-2: content_hash format + ledger verification ─────────────


def test_invalid_content_hash_rejected_by_pydantic(tmp_path):
    """content_hash must be a 64-character lowercase hex string (SHA-256)."""
    with pytest.raises(Exception):
        _good_sft_candidate(content_hash="not-a-sha256")
    with pytest.raises(Exception):
        _good_sft_candidate(content_hash="tooshort")
    with pytest.raises(Exception):
        # 63 chars — one short of valid SHA-256
        _good_sft_candidate(content_hash="a" * 63)


def test_valid_sha256_content_hash_accepted(tmp_path):
    """A well-formed 64-char hex content_hash matching the content passes."""
    candidate = _good_sft_candidate()  # canonical hash auto-computed
    report = DatasetExporter(_config(tmp_path)).export([candidate])
    assert report.total_sft_examples == 1


def test_fabricated_content_hash_rejected_by_model(tmp_path):
    """
    A well-formed but WRONG content_hash (does not match the candidate's
    content) is rejected at construction time — a fabricated hash can
    never enter the pipeline, independent of any verifier.
    """
    wrong_but_valid_hex = _sha256("a-hash-of-unrelated-text")
    with pytest.raises(Exception):
        _good_sft_candidate(content_hash=wrong_but_valid_hex)


def _verifier_cfg(tmp_path, verifier, *, min_per_skill=50, strict=True):
    return ExportConfig(
        export_root=tmp_path,
        strict_privacy=strict,
        verifier=verifier,
        quality=QualityPolicy(minimum_examples_per_skill=min_per_skill),
    )


def test_task_absent_from_ledger_rejected(tmp_path):
    """A candidate whose task_id is not in any ledger view is rejected."""
    verifier = WorkLedgerVerifier(task_views={})   # empty ledger
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([_good_sft_candidate()])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_fabricated_event_id_rejected_by_ledger_verifier(tmp_path):
    """
    The task exists in the ledger, but a provenance event ID it claims is
    not one of that task's events → rejected (no example produced).
    """
    view = TaskLedgerView(task_id="task-001", event_ids=frozenset({"evt-001"}))
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    candidate = _good_sft_candidate(provenance=["fabricated-evt-99"])
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([candidate])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_cross_task_event_borrowing_rejected(tmp_path):
    """
    A candidate cannot corroborate itself with an event that belongs to a
    DIFFERENT task — the per-task view membership check catches it.
    """
    views = {
        "task-001": TaskLedgerView(task_id="task-001", event_ids=frozenset({"evt-001"})),
        "task-002": TaskLedgerView(task_id="task-002", event_ids=frozenset({"evt-002"})),
    }
    verifier = WorkLedgerVerifier(task_views=views)
    # task-001 tries to claim evt-002 (which belongs to task-002).
    candidate = _good_sft_candidate(task_id="task-001", provenance=["evt-002"])
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([candidate])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_valid_provenance_accepted_by_ledger_verifier(tmp_path):
    """
    All event IDs belong to the task, hash/outcome match, AND the
    provenance cites the OutcomeRecorded evidence event → accepted. The
    exported source_events therefore prove WHY the example is eligible.
    """
    cand = _good_sft_candidate(provenance=["evt-001", "evt-outcome-1"])
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-001", "evt-outcome-1"}),
        content_hash=cand.content_hash,
        outcome_label="approved",
        outcome_events=frozenset(
            {LedgerOutcomeEvent("evt-outcome-1", "approved", cand.content_hash)}
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 0
    assert report.total_sft_examples == 1
    # The authorising OutcomeRecorded event is preserved in source_events.
    sft = _read_jsonl(tmp_path / "sft_examples.jsonl")
    assert "evt-outcome-1" in sft[0]["source_events"]


def test_content_hash_mismatch_with_ledger_rejected(tmp_path):
    """
    The ledger view records a DIFFERENT content_hash for the task than
    the candidate carries → rejected (tamper / stale content detection).
    """
    cand = _good_sft_candidate()
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-001"}),
        content_hash=_sha256("a-different-content-hash-than-the-candidate"),
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_outcome_label_mismatch_with_ledger_rejected(tmp_path):
    """A self-asserted outcome that disagrees with the ledger is rejected."""
    cand = _good_sft_candidate(outcome_label="approved")
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-001"}),
        content_hash=cand.content_hash,
        outcome_label="rejected",   # ledger says rejected, candidate claims approved
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_corrected_output_mismatch_with_ledger_rejected(tmp_path):
    """A DPO correction that disagrees with the ledger record is rejected."""
    cand = _good_dpo_candidate()  # task-dpo-001, evt-correction-001
    view = TaskLedgerView(
        task_id="task-dpo-001",
        event_ids=frozenset({"evt-correction-001"}),
        content_hash=cand.content_hash,
        correction="a totally different correction than the candidate's",
    )
    verifier = WorkLedgerVerifier(task_views={"task-dpo-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_dpo_pairs == 0


def test_accept_all_verifier_bypasses_ledger_check(tmp_path):
    """AcceptAllVerifier passes any provenance — for demo / unit tests only."""
    cfg = _verifier_cfg(tmp_path, AcceptAllVerifier())
    candidate = _good_sft_candidate(provenance=["completely-fabricated-event-id"])
    report = DatasetExporter(cfg).export([candidate])
    assert report.rejected_unverified_provenance == 0
    assert report.total_sft_examples == 1


def test_export_without_verifier_fails_closed(tmp_path):
    """
    The exporter REFUSES to run without a provenance verifier — fail
    closed. No files are written.
    """
    cfg = ExportConfig(
        export_root=tmp_path,
        verifier=None,   # explicitly unconfigured
        quality=QualityPolicy(minimum_examples_per_skill=50),
    )
    with pytest.raises(ExporterConfigurationError):
        DatasetExporter(cfg).export([_good_sft_candidate()])
    assert not (tmp_path / "sft_examples.jsonl").exists()
    assert not (tmp_path / "dpo_pairs.jsonl").exists()
    assert not (tmp_path / "dataset_report.json").exists()


def test_path_confinement_runs_before_verifier_check(tmp_path):
    """
    Path confinement must surface BEFORE the fail-closed verifier check,
    so a bad filename raises ExportPathError even when verifier is None.
    """
    cfg = ExportConfig(
        export_root=tmp_path,
        sft_filename="../escape.jsonl",
        verifier=None,
        quality=QualityPolicy(minimum_examples_per_skill=50),
    )
    with pytest.raises(ExportPathError):
        DatasetExporter(cfg).export([_good_sft_candidate()])


# ── Section N2 — P1: required ledger evidence (not just compared) ────────────


def test_candidate_requires_ledger_content_hash_evidence(tmp_path):
    """
    A candidate whose ledger view records NO content hash is rejected —
    content corroboration is REQUIRED, not merely compared when supplied.
    The task and events are otherwise valid.
    """
    cand = _good_sft_candidate()
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-001"}),
        content_hash=None,            # ledger has no hash evidence
        outcome_label="approved",
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_sft_requires_ledger_outcome_evidence(tmp_path):
    """
    An SFT candidate (asserts an outcome label) whose ledger view records
    the content hash but NO outcome label is rejected — SFT outcome
    evidence is REQUIRED. Closes the "SFT exported without ledger
    outcome evidence" hole.
    """
    cand = _good_sft_candidate()  # asserts outcome_label="approved"
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-001"}),
        content_hash=cand.content_hash,
        outcome_label=None,           # ledger has NO outcome evidence
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_dpo_requires_ledger_correction_evidence(tmp_path):
    """
    A DPO candidate (asserts a corrected output) whose ledger view records
    the content hash but NO correction is rejected — DPO correction
    evidence is REQUIRED. Closes the "DPO exported without ledger
    correction evidence" hole.
    """
    cand = _good_dpo_candidate()
    view = TaskLedgerView(
        task_id="task-dpo-001",
        event_ids=frozenset({"evt-correction-001"}),
        content_hash=cand.content_hash,
        correction=None,              # ledger has NO correction evidence
    )
    verifier = WorkLedgerVerifier(task_views={"task-dpo-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_dpo_pairs == 0


# ── Section N3 — P1: view identity + real ledger-backed views ───────────────


def test_ledger_view_identity_mismatch_rejected(tmp_path):
    """
    A view filed under task-A whose OWN ``task_id`` is a different task
    cannot corroborate task-A. Reproduces the probe that previously
    ACCEPTED a candidate for task-A against a view internally identifying
    itself as task-B; it is now rejected (fail closed).
    """
    cand = _good_sft_candidate()  # task-001
    mislabelled = TaskLedgerView(
        task_id="task-OTHER",                  # internally a DIFFERENT task
        event_ids=frozenset({"evt-001"}),
        content_hash=cand.content_hash,
        outcome_label="approved",
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": mislabelled})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def _seed_ledger_for_task_001(
    ledger_path: Path, *, content_hash: str | None = None
) -> None:
    """
    Write real Work Ledger v2 events for task-001 via the real writer.

    When given, ``content_hash`` binds the OutcomeRecorded event to the
    specific judged content (the canonical hash the candidate also derives).
    Passing ``None`` writes a pre-binding/stray marker that records no hash.
    """
    writer = LedgerWriter(ledger_path)
    writer.append(SkillInvoked(**make_envelope(
        task_id="task-001", actor="aria", actor_type=ActorType.aria,
        event_id="evt-001", skill_name="pr_review", timestamp=_ts(),
    )))
    writer.append(OutcomeRecorded(**make_envelope(
        task_id="task-001", actor="human:kunal", actor_type=ActorType.human,
        event_id="evt-outcome-1", outcome="approved", timestamp=_ts(),
        content_hash=content_hash,
    )))


def test_ledger_backed_views_accept_corroborated_candidate(tmp_path):
    """
    End-to-end: views built from REAL ledger events (via LedgerReader) plus
    a governed content resolver corroborate a genuine candidate. This is
    the production path the verifier is meant to run on — not a
    hand-assembled dict.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    # SFT provenance must cite the OutcomeRecorded evidence event.
    cand = _good_sft_candidate(provenance=["evt-001", "evt-outcome-1"])
    # The outcome event records THIS candidate's canonical hash — binding it.
    _seed_ledger_for_task_001(ledger_path, content_hash=cand.content_hash)

    class _Resolver:
        def resolve(self, task_id):
            if task_id == "task-001":
                return ResolvedContent(content_hash=cand.content_hash)
            return None

    reader = LedgerReader(v2_path=ledger_path)
    views = LedgerTaskViewBuilder(reader, content_resolver=_Resolver()).build()

    # The view came from real events: event_ids collected, outcome captured,
    # and the typed OutcomeRecorded evidence preserved for citation, bound
    # to the judged content.
    assert views["task-001"].event_ids == frozenset({"evt-001", "evt-outcome-1"})
    assert views["task-001"].outcome_label == "approved"
    assert views["task-001"].outcome_events == frozenset(
        {LedgerOutcomeEvent("evt-outcome-1", "approved", cand.content_hash)}
    )

    verifier = WorkLedgerVerifier(task_views=views)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report = DatasetExporter(_verifier_cfg(out_dir, verifier)).export([cand])
    assert report.rejected_unverified_provenance == 0
    assert report.total_sft_examples == 1


def test_ledger_backed_views_without_resolver_fail_closed(tmp_path):
    """
    A builder with NO content resolver cannot corroborate content: the
    ledger does not store training content, so ``content_hash`` stays
    ``None`` and the required-evidence rule rejects the candidate.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    _seed_ledger_for_task_001(ledger_path)
    cand = _good_sft_candidate()

    reader = LedgerReader(v2_path=ledger_path)
    views = LedgerTaskViewBuilder(reader).build()   # no resolver
    assert views["task-001"].content_hash is None

    verifier = WorkLedgerVerifier(task_views=views)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report = DatasetExporter(_verifier_cfg(out_dir, verifier)).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_ledger_builder_refuses_malformed_records(tmp_path):
    """
    The builder fails closed if the reader surfaced malformed records —
    building views over a partially-parsed ledger could omit event IDs and
    corrupt verification. Malformed lines are never silently dropped.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text(
        '{"event_version": 2, "event_type": "not_a_real_type"}\n'
        "{ this is not json\n",
        encoding="utf-8",
    )
    reader = LedgerReader(v2_path=ledger_path)
    assert reader.malformed()   # sanity: reader sees the corruption
    with pytest.raises(LedgerAdapterError):
        LedgerTaskViewBuilder(reader).build()


def test_ledger_builder_latest_outcome_wins(tmp_path):
    """
    When a task has multiple OutcomeRecorded events, the most RECENT
    outcome is the one the view reports.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    writer = LedgerWriter(ledger_path)
    writer.append(OutcomeRecorded(**make_envelope(
        task_id="task-x", actor="human:k", actor_type=ActorType.human,
        event_id="evt-old", outcome="rejected",
        timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )))
    writer.append(OutcomeRecorded(**make_envelope(
        task_id="task-x", actor="human:k", actor_type=ActorType.human,
        event_id="evt-new", outcome="approved",
        timestamp=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )))
    reader = LedgerReader(v2_path=ledger_path)
    views = LedgerTaskViewBuilder(reader).build()
    assert views["task-x"].outcome_label == "approved"
    assert views["task-x"].event_ids == frozenset({"evt-old", "evt-new"})


# ── Section N4 — P1: provenance must CITE the authorising evidence event ─────
#
# Belonging-to-the-task is not enough. An exported record's source_events
# must prove WHY it is training-eligible: an SFT example must cite the
# OutcomeRecorded event that carries its outcome; a DPO pair must cite a
# CorrectionRecorded event. These reproduce Codex's three runtime probes.


def test_sft_provenance_must_cite_outcome_event(tmp_path):
    """
    PROBE: SFT exported while source_events contained only the SkillInvoked
    event, omitting the OutcomeRecorded event. The candidate cites a valid
    task event ('evt-001') but NOT the OutcomeRecorded event that
    authorises the outcome → rejected.
    """
    cand = _good_sft_candidate(provenance=["evt-001"])  # cites skill, not outcome
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-001", "evt-outcome-1"}),
        content_hash=cand.content_hash,
        outcome_label="approved",
        outcome_events=frozenset(
            {LedgerOutcomeEvent("evt-outcome-1", "approved", cand.content_hash)}
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_sft_rejected_when_ledger_has_no_outcome_event(tmp_path):
    """
    The asserted outcome label matches the ledger's latest label, but the
    view holds NO typed OutcomeRecorded evidence (outcome_events empty) —
    eligibility is unproven, so the candidate is rejected.
    """
    cand = _good_sft_candidate(provenance=["evt-001"])
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-001"}),
        content_hash=cand.content_hash,
        outcome_label="approved",          # label present…
        outcome_events=frozenset(),        # …but no typed evidence event
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_dpo_provenance_must_cite_correction_event(tmp_path):
    """
    A DPO candidate that cites a non-correction task event (the skill
    event) instead of the CorrectionRecorded event is rejected — the
    exported pair could not prove the correction authorised it.
    """
    cand = _good_dpo_candidate(provenance=["evt-dpo-skill"])  # cites skill
    view = TaskLedgerView(
        task_id="task-dpo-001",
        event_ids=frozenset({"evt-dpo-skill", "evt-correction-001"}),
        content_hash=cand.content_hash,
        correction=cand.corrected_output,
        correction_events=frozenset(
            {LedgerCorrectionEvent("evt-correction-001", cand.content_hash)}
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-dpo-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_dpo_pairs == 0


def test_dpo_resolver_correction_without_ledger_event_rejected(tmp_path):
    """
    PROBE: DPO exported with a resolver-supplied correction but NO
    CorrectionRecorded event anywhere in the ledger. The resolver
    correction alone is insufficient — without a typed correction event,
    eligibility is unproven → rejected.
    """
    cand = _good_dpo_candidate()  # provenance ["evt-correction-001"]
    view = TaskLedgerView(
        task_id="task-dpo-001",
        event_ids=frozenset({"evt-correction-001"}),
        content_hash=cand.content_hash,
        correction=cand.corrected_output,   # resolver supplied the text…
        correction_events=frozenset(),      # …but the ledger has no event
    )
    verifier = WorkLedgerVerifier(task_views={"task-dpo-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_dpo_pairs == 0


def _seed_dpo_ledger(
    ledger_path: Path,
    *,
    with_correction_event: bool,
    content_hash: str | None = None,
) -> None:
    """
    Write real DPO-task ledger events; optionally include the correction.

    When a correction event is written, ``content_hash`` binds it to the
    specific corrected pair (the canonical hash the candidate also derives).
    Passing ``None`` writes a pre-binding/stray marker that records no hash.
    """
    writer = LedgerWriter(ledger_path)
    writer.append(SkillInvoked(**make_envelope(
        task_id="task-dpo-001", actor="aria", actor_type=ActorType.aria,
        event_id="evt-dpo-skill", skill_name="pr_review", timestamp=_ts(),
    )))
    if with_correction_event:
        writer.append(CorrectionRecorded(**make_envelope(
            task_id="task-dpo-001", actor="human:kunal",
            actor_type=ActorType.human,
            event_id="evt-correction-001", timestamp=_ts(),
            content_hash=content_hash,
        )))


def test_ledger_backed_dpo_accepts_with_correction_event(tmp_path):
    """
    End-to-end via the real builder: a CorrectionRecorded event exists and
    the candidate cites it; the resolver supplies the matching content →
    the DPO pair is accepted and its source_events cite the correction.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    cand = _good_dpo_candidate()  # provenance ["evt-correction-001"]
    # The correction event records THIS pair's canonical hash — binding it.
    _seed_dpo_ledger(
        ledger_path, with_correction_event=True, content_hash=cand.content_hash
    )

    class _Resolver:
        def resolve(self, task_id):
            if task_id == "task-dpo-001":
                return ResolvedContent(
                    content_hash=cand.content_hash,
                    correction=cand.corrected_output,
                )
            return None

    reader = LedgerReader(v2_path=ledger_path)
    views = LedgerTaskViewBuilder(reader, content_resolver=_Resolver()).build()
    assert views["task-dpo-001"].correction_events == frozenset(
        {LedgerCorrectionEvent("evt-correction-001", cand.content_hash)}
    )

    verifier = WorkLedgerVerifier(task_views=views)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report = DatasetExporter(_verifier_cfg(out_dir, verifier)).export([cand])
    assert report.rejected_unverified_provenance == 0
    assert report.total_dpo_pairs == 1
    dpo = _read_jsonl(out_dir / "dpo_pairs.jsonl")
    assert "evt-correction-001" in dpo[0]["source_events"]


def test_ledger_backed_dpo_rejects_when_no_correction_event(tmp_path):
    """
    End-to-end via the real builder: the ledger holds only the skill event
    (no CorrectionRecorded). Even though the resolver supplies the
    correction text, the absent typed evidence event fails the chain →
    rejected. This is the truest reproduction of the resolver-only probe.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    _seed_dpo_ledger(ledger_path, with_correction_event=False)
    cand = _good_dpo_candidate(provenance=["evt-dpo-skill"])

    class _Resolver:
        def resolve(self, task_id):
            if task_id == "task-dpo-001":
                return ResolvedContent(
                    content_hash=cand.content_hash,
                    correction=cand.corrected_output,
                )
            return None

    reader = LedgerReader(v2_path=ledger_path)
    views = LedgerTaskViewBuilder(reader, content_resolver=_Resolver()).build()
    assert views["task-dpo-001"].correction_events == frozenset()

    verifier = WorkLedgerVerifier(task_views=views)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report = DatasetExporter(_verifier_cfg(out_dir, verifier)).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_dpo_pairs == 0


# ── Section N5 — P1: the cited correction event must be BOUND to the content ─
#
# Citing *a* CorrectionRecorded event for the task is not enough. The cited
# event must have RECORDED this exact (rejected, corrected) content — its
# content_hash must equal the candidate's. Otherwise an unrelated historical
# correction marker authorises newly-invented rejected/corrected text. These
# reproduce Codex's Round-4 runtime probe.


def test_dpo_stray_correction_marker_with_different_hash_rejected(tmp_path):
    """
    PROBE: a correction event exists for the task and the candidate cites it,
    the resolver corroborates the (invented) correction text — but the cited
    event recorded a DIFFERENT content hash. The event is not bound to this
    pair, so it cannot authorise it → rejected.
    """
    cand = _good_dpo_candidate()  # provenance ["evt-correction-001"]
    view = TaskLedgerView(
        task_id="task-dpo-001",
        event_ids=frozenset({"evt-correction-001"}),
        content_hash=cand.content_hash,
        correction=cand.corrected_output,          # resolver corroborates text…
        correction_events=frozenset(
            # …but the cited event recorded a DIFFERENT pair's content.
            {LedgerCorrectionEvent("evt-correction-001", _sha256("some other pair"))}
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-dpo-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_dpo_pairs == 0


def test_dpo_correction_event_without_hash_cannot_bind(tmp_path):
    """
    PROBE: a pre-binding/legacy correction marker that recorded NO content
    hash cannot authorise a DPO pair — even when cited and text-corroborated.
    A correction event must carry the content hash to bind (fail closed).
    """
    cand = _good_dpo_candidate()  # provenance ["evt-correction-001"]
    view = TaskLedgerView(
        task_id="task-dpo-001",
        event_ids=frozenset({"evt-correction-001"}),
        content_hash=cand.content_hash,
        correction=cand.corrected_output,
        correction_events=frozenset(
            {LedgerCorrectionEvent("evt-correction-001", None)}  # no bound hash
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-dpo-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_dpo_pairs == 0


def test_dpo_bound_correction_event_accepted(tmp_path):
    """
    The cited correction event recorded THIS pair's content hash → it is
    bound to the pair and authorises it. Positive control for the binding
    rule (manual view).
    """
    cand = _good_dpo_candidate()  # provenance ["evt-correction-001"]
    view = TaskLedgerView(
        task_id="task-dpo-001",
        event_ids=frozenset({"evt-correction-001"}),
        content_hash=cand.content_hash,
        correction=cand.corrected_output,
        correction_events=frozenset(
            {LedgerCorrectionEvent("evt-correction-001", cand.content_hash)}
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-dpo-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 0
    assert report.total_dpo_pairs == 1


def test_ledger_backed_dpo_rejects_stray_marker_with_mismatched_hash(tmp_path):
    """
    End-to-end via the REAL builder — the truest reproduction of Codex's
    Round-4 probe. A genuine CorrectionRecorded event exists for the task and
    the candidate cites it, but the event recorded a DIFFERENT pair's hash.
    The builder surfaces the recorded hash; the verifier refuses to let the
    unrelated marker authorise the invented content.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    cand = _good_dpo_candidate()  # provenance ["evt-correction-001"]
    # Correction event records a hash for some OTHER pair, not this candidate.
    _seed_dpo_ledger(
        ledger_path,
        with_correction_event=True,
        content_hash=_sha256("an unrelated historical correction"),
    )

    class _Resolver:
        def resolve(self, task_id):
            if task_id == "task-dpo-001":
                return ResolvedContent(
                    content_hash=cand.content_hash,
                    correction=cand.corrected_output,
                )
            return None

    reader = LedgerReader(v2_path=ledger_path)
    views = LedgerTaskViewBuilder(reader, content_resolver=_Resolver()).build()
    # The view faithfully surfaces the event's recorded (mismatched) hash.
    bound = next(iter(views["task-dpo-001"].correction_events))
    assert bound.event_id == "evt-correction-001"
    assert bound.content_hash != cand.content_hash

    verifier = WorkLedgerVerifier(task_views=views)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report = DatasetExporter(_verifier_cfg(out_dir, verifier)).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_dpo_pairs == 0


# ── Section N6 — P1: SFT outcome event must be BOUND to the exported content ─
#
# Citing *an* OutcomeRecorded event with the right label is not enough. The
# cited outcome must have JUDGED this exact (input, output) content — its
# recorded content_hash must equal the candidate's. Otherwise an old `approved`
# marker authorises completely new content under the same task ID. These
# reproduce Codex's Round-5 runtime probe (symmetric to the DPO binding in N5).


def test_sft_stray_outcome_marker_with_different_hash_rejected(tmp_path):
    """
    PROBE: an approved outcome event exists for the task and the candidate
    cites it, the resolver corroborates the (invented) content hash — but the
    cited outcome event recorded a DIFFERENT content hash. The outcome is not
    bound to this content, so it cannot authorise the SFT example → rejected.
    """
    cand = _good_sft_candidate(provenance=["evt-outcome-1"])
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-outcome-1"}),
        content_hash=cand.content_hash,            # resolver corroborates content…
        outcome_label="approved",
        outcome_events=frozenset(
            # …but the cited outcome judged DIFFERENT content.
            {LedgerOutcomeEvent("evt-outcome-1", "approved", _sha256("other content"))}
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_sft_outcome_event_without_hash_cannot_bind(tmp_path):
    """
    PROBE: a pre-binding/legacy outcome marker that recorded NO content hash
    cannot authorise an SFT example — even when cited and content-corroborated.
    An outcome event must carry the content hash to bind (fail closed).
    """
    cand = _good_sft_candidate(provenance=["evt-outcome-1"])
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-outcome-1"}),
        content_hash=cand.content_hash,
        outcome_label="approved",
        outcome_events=frozenset(
            {LedgerOutcomeEvent("evt-outcome-1", "approved", None)}  # no bound hash
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


def test_sft_bound_outcome_event_accepted(tmp_path):
    """
    The cited outcome event recorded THIS content's hash → it is bound to the
    content and authorises the SFT example. Positive control for the binding
    rule (manual view).
    """
    cand = _good_sft_candidate(provenance=["evt-outcome-1"])
    view = TaskLedgerView(
        task_id="task-001",
        event_ids=frozenset({"evt-outcome-1"}),
        content_hash=cand.content_hash,
        outcome_label="approved",
        outcome_events=frozenset(
            {LedgerOutcomeEvent("evt-outcome-1", "approved", cand.content_hash)}
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-001": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier)
    ).export([cand])
    assert report.rejected_unverified_provenance == 0
    assert report.total_sft_examples == 1


def test_ledger_backed_sft_rejects_stray_marker_with_mismatched_hash(tmp_path):
    """
    End-to-end via the REAL builder — the truest reproduction of Codex's
    Round-5 probe: an old `approved` outcome event authorising completely new
    resolver-backed content under the same task ID. A genuine OutcomeRecorded
    event exists and the candidate cites it, the resolver corroborates the
    candidate's content — but the outcome event recorded a DIFFERENT hash. The
    builder surfaces the recorded hash; the verifier refuses to let the
    unrelated approval authorise the invented content.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    cand = _good_sft_candidate(provenance=["evt-001", "evt-outcome-1"])
    # The approved outcome was recorded for some OTHER content, not this one.
    _seed_ledger_for_task_001(
        ledger_path,
        content_hash=_sha256("an unrelated historical approval"),
    )

    class _Resolver:
        def resolve(self, task_id):
            if task_id == "task-001":
                return ResolvedContent(content_hash=cand.content_hash)
            return None

    reader = LedgerReader(v2_path=ledger_path)
    views = LedgerTaskViewBuilder(reader, content_resolver=_Resolver()).build()
    # The view faithfully surfaces the outcome event's recorded (mismatched) hash.
    bound = next(iter(views["task-001"].outcome_events))
    assert bound.event_id == "evt-outcome-1"
    assert bound.content_hash != cand.content_hash

    verifier = WorkLedgerVerifier(task_views=views)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report = DatasetExporter(_verifier_cfg(out_dir, verifier)).export([cand])
    assert report.rejected_unverified_provenance == 1
    assert report.total_sft_examples == 0


# ── Section N7 — P1: redaction must never silently break the content binding ─
#
# The verifier corroborates a candidate by its content_hash (the SFT/DPO
# binding of N4–N6). Redacting content AFTER verification would mutate it and
# recompute that hash, so the exported example would carry a hash NO ledger
# event authorises. The exporter therefore rejects credential-bearing content
# outright rather than redact-and-export. This reproduces Codex's Round-6 probe
# ("Redacted example exported: true / Authorizing event hash matches exported
# content: false") and proves it can no longer happen.


def test_credential_content_rejected_under_real_binding_verifier(tmp_path):
    """
    PROBE: a candidate that is fully ledger-bound — its content_hash matches
    the authorising OutcomeRecorded event — but carries a credential in its
    content. Pre-fix the exporter redacted the content, recomputed the hash,
    and wrote an example whose hash no longer matched the authorising event
    (binding silently broken). Now the candidate is rejected for privacy and
    nothing is written; the binding can never be invalidated post-verification.
    """
    cand = _good_sft_candidate(
        task_id="task-bind-leak",
        output_text="Risk MEDIUM. deploy token ghp_aaaaaaaaaaaaaaaaaaaa",
        provenance=["evt-outcome-1"],
    )
    view = TaskLedgerView(
        task_id="task-bind-leak",
        event_ids=frozenset({"evt-outcome-1"}),
        content_hash=cand.content_hash,            # binding WOULD pass…
        outcome_label="approved",
        outcome_events=frozenset(
            {LedgerOutcomeEvent("evt-outcome-1", "approved", cand.content_hash)}
        ),
    )
    verifier = WorkLedgerVerifier(task_views={"task-bind-leak": view})
    report = DatasetExporter(
        _verifier_cfg(tmp_path, verifier, strict=False)
    ).export([cand])
    # …but the credential makes it ineligible, and it is NOT redacted-exported.
    assert report.rejected_for_privacy == 1
    assert report.total_sft_examples == 0
    assert _read_jsonl(tmp_path / "sft_examples.jsonl") == []


# ── Section O — P2-2: readiness accounts for rejected-candidate skills ───────


def test_readiness_false_when_skill_only_has_sensitivity_rejected_candidates(tmp_path):
    """
    A skill (kpi) that had only a sensitivity-rejected candidate must block
    readiness even when the other skill (pr_review) meets the threshold.
    """
    pr_ok = [
        _good_sft_candidate(
            task_id=f"pr-ok-{i}",
            input_text=f"pr input {i}",
            output_text=f"pr output {i} with sufficient length",
        )
        for i in range(2)
    ]
    kpi_rejected = _good_sft_candidate(
        task_id="kpi-conf",
        skill_name="kpi",
        sensitivity=Sensitivity.confidential,
    )
    cfg = _config(tmp_path, min_per_skill=2)
    report = DatasetExporter(cfg).export(pr_ok + [kpi_rejected])
    assert report.rejected_for_sensitivity == 1
    assert report.ready_for_finetuning is False
    assert "kpi" in report.skills_below_50_examples


def test_readiness_false_when_skill_only_has_quality_rejected_candidates(tmp_path):
    """
    A skill with all its candidates rejected for quality appears in
    skills_below_50_examples and blocks readiness.
    """
    pr_ok = [
        _good_sft_candidate(
            task_id=f"pr-qual-{i}",
            input_text=f"pr quality input {i}",
            output_text=f"pr quality output {i} sufficient length",
        )
        for i in range(2)
    ]
    kpi_short = _good_sft_candidate(
        task_id="kpi-short",
        skill_name="kpi",
        output_text="ok",  # below minimum_output_length=5
    )
    cfg = _config(tmp_path, min_per_skill=2)
    report = DatasetExporter(cfg).export(pr_ok + [kpi_short])
    assert report.rejected_for_quality >= 1
    assert report.ready_for_finetuning is False
    assert "kpi" in report.skills_below_50_examples
