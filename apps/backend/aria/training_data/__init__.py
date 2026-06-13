"""
Week 29 Priority 3 — Dataset Export Prototype.

PROTOTYPE ONLY. No model training, no fine-tuning, no model deployment
happens here. This package prepares training-ready candidate datasets
from explicit typed inputs and writes deterministic JSONL files.

Public surface
--------------
- ``TrainingCandidate``    — the typed contract callers MUST provide.
                              The exporter never scrapes arbitrary
                              ledger metadata; it only consumes this
                              object (or a ``CandidateResolver``).
- ``CandidateResolver``    — Protocol for future production wiring
                              (resolves task_id → TrainingCandidate).
- ``Sensitivity``          — enum: public / internal / confidential /
                              restricted / unknown.
- ``SFTExample``,
  ``DPOPair``,
  ``DatasetReport``        — typed output schemas.
- ``RejectionReason``,
  ``RejectionRecord``      — deterministic rejection accounting.
- ``DatasetExporter``      — main entry point.
- ``ExportPathError``,
  ``StrictPrivacyViolation``,
  ``ExporterConfigurationError``,
  ``DatasetRecoveryError``   — typed exceptions. ``ExporterConfigurationError``
                              is raised when no verifier is configured
                              (fail-closed); ``DatasetRecoveryError`` is
                              raised when a failed export cannot restore
                              the previous dataset (loud, never silent).
- ``WorkLedgerVerifier``,
  ``TaskLedgerView``,
  ``LedgerOutcomeEvent``,
  ``LedgerCorrectionEvent`` — verify provenance against the Work Ledger.
                              An SFT candidate must cite the
                              ``OutcomeRecorded`` event that authorises it;
                              a DPO candidate must cite the
                              ``CorrectionRecorded`` event BOUND to its
                              content (matching content_hash).
                              ``source_events`` therefore prove WHY a record
                              is eligible.
- ``LedgerTaskViewBuilder`` — builds ``TaskLedgerView`` objects from REAL
                              Work Ledger v2 events (via ``LedgerReader``)
                              so verification is ledger-backed, not
                              caller-fabricated.
- ``TaskContentResolver``,
  ``ResolvedContent``      — governed content/artifact resolver boundary
                              (the ledger does not store training content,
                              so content_hash / correction come from here).
- ``LedgerAdapterError``   — raised when views cannot be built safely
                              (e.g. malformed ledger records present).
- ``AcceptAllVerifier``   — prototype bypass (tests and offline demo only).
- ``canonical_content_hash`` — the single definition of a candidate's
                              content hash (tamper-evident integrity).
"""
from aria.training_data.models import (
    CandidateResolver,
    DatasetReport,
    DPOPair,
    RejectionReason,
    RejectionRecord,
    Sensitivity,
    SFTExample,
    TrainingCandidate,
    canonical_content_hash,
)
from aria.training_data.exporter import (
    DatasetExporter,
    DatasetRecoveryError,
    ExporterConfigurationError,
    ExportPathError,
    StrictPrivacyViolation,
)
from aria.training_data.verifier import (
    AcceptAllVerifier,
    LedgerCorrectionEvent,
    LedgerOutcomeEvent,
    ProvenanceVerifier,
    TaskLedgerView,
    WorkLedgerVerifier,
)
from aria.training_data.ledger_adapter import (
    LedgerAdapterError,
    LedgerTaskViewBuilder,
    ResolvedContent,
    TaskContentResolver,
)

__all__ = [
    "AcceptAllVerifier",
    "CandidateResolver",
    "DatasetExporter",
    "DatasetRecoveryError",
    "DatasetReport",
    "DPOPair",
    "ExporterConfigurationError",
    "ExportPathError",
    "LedgerAdapterError",
    "LedgerCorrectionEvent",
    "LedgerOutcomeEvent",
    "LedgerTaskViewBuilder",
    "ProvenanceVerifier",
    "RejectionReason",
    "RejectionRecord",
    "ResolvedContent",
    "Sensitivity",
    "SFTExample",
    "StrictPrivacyViolation",
    "TaskContentResolver",
    "TaskLedgerView",
    "TrainingCandidate",
    "WorkLedgerVerifier",
    "canonical_content_hash",
]
