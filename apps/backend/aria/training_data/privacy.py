"""
Privacy boundary for the Dataset Export Prototype.

Reuses ``aria.ledger.privacy.contains_credential_pattern`` and
``redact_freetext`` so the export pipeline applies the SAME credential
detection that already protects the Work Ledger.

Two classes of field are scanned; a credential in EITHER rejects the
candidate. Training content is NEVER redacted-and-exported:

- **Free-text content fields** (``input_text``, ``output_text``,
  ``rejected_output``, ``corrected_output``) — actual training content.
  A credential here rejects the candidate. We do not redact-and-export:
  redaction mutates the content and recomputes its ``content_hash``,
  producing a derived artifact that NO ledger event authorises — which
  would silently break the content-hash binding the verifier enforces
  (verifier points 3–5). Exported content is always the exact content a
  ledger event approved by hash. See ``scan_text_fields_for_credentials``.

- **Structural identifiers** (``task_id``, ``skill_name``,
  ``artifact_id``, ``outcome_label``) AND every ``provenance`` event ID
  — references into the Work Ledger / artifact store. A credential here
  also rejects the candidate. Redacting a structural identifier would
  destroy its ability to resolve back to the ledger, defeating the very
  auditability the provenance exists to provide. See
  ``scan_structural_identifiers_for_credentials``.

Strict mode is enforced in ``exporter.py``: any unresolved credential
pattern (in either class) aborts the entire export with
``StrictPrivacyViolation``. In non-strict mode the offending candidate is
rejected (``for_privacy``); the rest of the batch still exports.
"""
from __future__ import annotations

from typing import Iterable

from aria.ledger.privacy import contains_credential_pattern, redact_freetext

from aria.training_data.models import TrainingCandidate


# Free-text content fields — actual training content. A credential here
# rejects the candidate (content is never redacted-and-exported; see the
# module docstring).
_FREE_TEXT_CONTENT_FIELDS: tuple[str, ...] = (
    "input_text",
    "output_text",
    "rejected_output",
    "corrected_output",
)

# Structural identifiers — references into the ledger / artifact store.
# A credential in any of these (or in a provenance event ID) ALWAYS
# rejects the candidate; these are never redacted.
_STRUCTURAL_FIELDS: tuple[str, ...] = (
    "task_id",
    "skill_name",
    "artifact_id",
    "outcome_label",
)


def scan_text_fields_for_credentials(candidate: TrainingCandidate) -> list[str]:
    """
    Return the free-text content field names whose value contains a
    credential-shaped substring. Empty list = clean. A non-empty result
    means the candidate MUST be rejected — training content is never
    redacted-and-exported (see the module docstring).
    """
    hits: list[str] = []
    for field in _FREE_TEXT_CONTENT_FIELDS:
        value = getattr(candidate, field, None)
        if isinstance(value, str) and contains_credential_pattern(value):
            hits.append(field)
    return hits


def scan_structural_identifiers_for_credentials(
    candidate: TrainingCandidate,
) -> list[str]:
    """
    Return the structural-identifier names (and ``provenance[i]`` slots)
    whose value contains a credential-shaped substring. Empty list =
    clean.

    A non-empty result means the candidate MUST be rejected — these
    identifiers are ledger references and must never be mutated /
    redacted (doing so would break audit resolution).
    """
    hits: list[str] = []
    for field in _STRUCTURAL_FIELDS:
        value = getattr(candidate, field, None)
        if isinstance(value, str) and contains_credential_pattern(value):
            hits.append(field)
    for i, evt_id in enumerate(candidate.provenance):
        if contains_credential_pattern(evt_id):
            hits.append(f"provenance[{i}]")
    return hits


def safe_summary(
    *,
    task_id: str,
    primary: str,
    skill_name: str | None = None,
    hit_fields: Iterable[str] | None = None,
) -> str:
    """
    Build a sanitised one-line rejection summary. Includes the
    rejection-reason code and field NAMES only; never the raw content,
    never the underlying exception text.

    Structural identifiers (``task_id``, ``skill_name``) are themselves
    passed through ``redact_freetext`` before inclusion: a poisoned,
    credential-shaped identifier must never be echoed verbatim into a log
    line or a stored ``RejectionRecord.summary``. Ordinary identifiers are
    unchanged (``redact_freetext`` only rewrites credential-shaped
    substrings).
    """
    safe_task_id = redact_freetext(task_id)
    parts = [f"task_id={safe_task_id!r}", f"reason={primary}"]
    if skill_name:
        parts.append(f"skill={redact_freetext(skill_name)!r}")
    if hit_fields:
        parts.append(f"fields={sorted(hit_fields)}")
    return "; ".join(parts)
