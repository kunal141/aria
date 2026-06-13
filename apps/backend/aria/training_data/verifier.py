"""
Provenance verification for the Dataset Export Prototype.

A candidate is only training-eligible if its provenance can be
corroborated against the Work Ledger. The exporter FAILS CLOSED: if no
verifier is configured it refuses to run (see ``DatasetExporter.export``).

``WorkLedgerVerifier`` checks, per candidate, against a
``TaskLedgerView`` built from the ledger for that task. Required ledger
evidence is ENFORCED — it is not merely compared when supplied:

1. The task exists in the ledger AND the view's own ``task_id`` matches
   the candidate (a mislabelled/tampered view cannot corroborate a
   different task).
2. EVERY provenance event ID belongs to THIS task (no cross-task event
   borrowing).
3. The candidate's ``content_hash`` is REQUIRED in the ledger view and
   must match. Content corroboration is mandatory; a view with no
   recorded hash fails closed.
4. An SFT candidate (one asserting an ``outcome_label``) REQUIRES the
   ledger to record a matching outcome label AND the candidate's
   ``provenance`` MUST cite the ``OutcomeRecorded`` event that is BOUND to
   this exact content — i.e. whose recorded ``content_hash`` equals the
   candidate's own content hash. Governance-only data, an authorising
   outcome the record fails to cite, OR an outcome event that judged
   different content (an old ``approved`` marker re-used under the same
   task ID) never becomes an SFT example. The cited event and the judged
   content must be the same fact, not two facts that happen to co-exist.
   The exported ``source_events`` therefore always prove WHY the example
   is eligible.
5. A DPO candidate (one asserting a ``corrected_output``) REQUIRES the
   ledger to record a matching correction AND the candidate's
   ``provenance`` MUST cite a ``CorrectionRecorded`` event that is BOUND
   to this exact content — i.e. whose recorded ``content_hash`` equals the
   candidate's own content hash. A resolver-supplied correction with no
   corroborating ledger event, OR a correction event that merely exists
   for the task but recorded different content (a stray/unrelated marker),
   is rejected. The cited event and the corrected content must be the same
   fact, not two facts that happen to co-exist.

``AcceptAllVerifier`` is an explicit bypass for offline demos and unit
tests that do NOT exercise provenance verification. It must NEVER be
used in a production export pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from aria.training_data.models import TrainingCandidate


@runtime_checkable
class ProvenanceVerifier(Protocol):
    """Protocol satisfied by any object that can verify a candidate."""

    def verify(self, candidate: TrainingCandidate) -> list[str]:
        """
        Return a list of error messages. An empty list means the
        candidate's provenance is verified. A non-empty list means the
        candidate must be rejected with ``unverified_provenance``.
        """
        ...


@dataclass(frozen=True)
class LedgerOutcomeEvent:
    """
    One ``OutcomeRecorded`` event's identity, paired with the outcome
    label it carries and the canonical ``content_hash`` it recorded for the
    judged content (``None`` for a pre-binding legacy event). The verifier
    uses this to require that an SFT candidate's ``provenance`` cites the
    SPECIFIC event that authorises the asserted outcome AND that the cited
    event judged THIS content (matching hash) — not merely some approved
    event belonging to the task.
    """
    event_id:     str
    outcome:      str
    content_hash: Optional[str]


@dataclass(frozen=True)
class LedgerCorrectionEvent:
    """
    One ``CorrectionRecorded`` event's identity, paired with the canonical
    ``content_hash`` it recorded for the corrected pair (``None`` for a
    pre-binding legacy event). The verifier uses this to require that a DPO
    candidate's own content hash equals the hash a *cited* correction event
    actually recorded — binding the event to the specific (rejected,
    corrected) content. A correction marker that merely exists for the task
    (a stray/unrelated event, or one that recorded different content)
    cannot authorise newly-invented training content.
    """
    event_id:     str
    content_hash: Optional[str]


@dataclass(frozen=True)
class TaskLedgerView:
    """
    The ledger's view of a single task, used to corroborate a candidate.

    Built from Work Ledger v2 events for the task. The fields are
    ``Optional`` (or empty) so a view can faithfully represent what the
    ledger actually recorded (``None`` / empty = the ledger has no such
    evidence). The verifier then ENFORCES the evidence each export type
    requires:

    - ``content_hash`` must be present for every candidate.
    - For an SFT candidate: ``outcome_label`` must match AND
      ``outcome_events`` must contain an ``OutcomeRecorded`` event whose
      recorded ``content_hash`` equals the candidate's content hash AND
      that the candidate's ``provenance`` cites. Binding the cited event to
      the specific content stops an old outcome marker from authorising
      newly-invented training content.
    - For a DPO candidate: ``correction`` must match AND
      ``correction_events`` must contain a ``CorrectionRecorded`` event
      whose recorded ``content_hash`` equals the candidate's content hash
      AND that the candidate's ``provenance`` cites. Binding the cited
      event to the specific content stops a stray correction marker from
      authorising newly-invented training content.

    Absent-but-required evidence — or required evidence the candidate's
    provenance fails to cite — fails closed.

    ``event_ids`` is the union of EVERY event recorded for the task (used
    for the cross-task membership check); ``outcome_events`` and
    ``correction_events`` are the typed evidence subsets that authorise
    training. ``outcome_label`` is the most-recent outcome label (the
    label-tamper check); ``correction`` is the governed corrected text.
    """
    task_id:            str
    event_ids:          frozenset[str]
    content_hash:       Optional[str] = None
    outcome_label:      Optional[str] = None
    correction:         Optional[str] = None
    outcome_events:     frozenset[LedgerOutcomeEvent] = frozenset()
    correction_events:  frozenset[LedgerCorrectionEvent] = frozenset()


class WorkLedgerVerifier:
    """
    Verifies candidates against per-task ledger views.

    Parameters
    ----------
    task_views
        Mapping of ``task_id`` → ``TaskLedgerView``. A candidate whose
        task is absent is rejected; a view whose own ``task_id`` does not
        match its key is rejected (identity check).

        In production this mapping is built from real Work Ledger v2
        events by ``ledger_adapter.LedgerTaskViewBuilder`` — NOT
        hand-assembled. Tests may construct views directly to exercise a
        specific rejection path.
    """

    def __init__(self, task_views: dict[str, TaskLedgerView]) -> None:
        self._views = dict(task_views)

    def verify(self, candidate: TrainingCandidate) -> list[str]:
        view = self._views.get(candidate.task_id)
        if view is None:
            return [f"task_id not found in ledger: {candidate.task_id!r}"]

        # 1. View identity must match the key it was filed under. A view
        #    is keyed by task_id; if its OWN ``task_id`` names a different
        #    task, the mapping is mislabelled (or tampered) and the view
        #    cannot corroborate THIS candidate. Fail closed — never
        #    corroborate task-A against a view that is internally task-B.
        if view.task_id != candidate.task_id:
            return [
                f"ledger view identity mismatch: view filed under "
                f"{candidate.task_id!r} is internally for task "
                f"{view.task_id!r}; refusing to corroborate"
            ]

        errors: list[str] = []

        # 2. Every provenance event ID must belong to THIS task.
        for evt_id in candidate.provenance:
            if evt_id not in view.event_ids:
                errors.append(
                    f"event_id {evt_id!r} does not belong to task "
                    f"{candidate.task_id!r}"
                )

        # 3. content_hash evidence is REQUIRED for every candidate: the
        #    ledger must record the content hash AND it must match. We do
        #    not export content the ledger cannot corroborate.
        if view.content_hash is None:
            errors.append(
                "ledger has no content_hash for this task; content cannot "
                "be corroborated"
            )
        elif candidate.content_hash != view.content_hash:
            errors.append("content_hash does not match ledger record")

        provenance = set(candidate.provenance)

        # 4. SFT evidence: a candidate that asserts an outcome label (the
        #    SFT eligibility signal) REQUIRES the ledger to record a
        #    matching one AND the candidate's provenance must CITE the
        #    specific OutcomeRecorded event that is BOUND to this content.
        #    "Bound" means the cited event's recorded content_hash equals
        #    the candidate's own content hash — the outcome judged this
        #    exact (input, output) content. An outcome event that merely
        #    carries the right label for the task (an old approved marker
        #    judging different content, or a pre-binding legacy event with
        #    no hash) cannot authorise newly-invented training content.
        #    Citing only the SkillInvoked event is likewise not enough —
        #    the exported source_events must prove eligibility.
        if candidate.outcome_label is not None:
            if view.outcome_label is None:
                errors.append(
                    "ledger has no outcome_label for a candidate that "
                    "asserts one (SFT outcome evidence required)"
                )
            elif candidate.outcome_label != view.outcome_label:
                errors.append("outcome_label does not match ledger record")

            label_matching = {
                ev for ev in view.outcome_events
                if ev.outcome == candidate.outcome_label
            }
            bound_outcome_ids = {
                ev.event_id
                for ev in label_matching
                if ev.content_hash is not None
                and ev.content_hash == candidate.content_hash
            }
            if not label_matching:
                errors.append(
                    "ledger has no OutcomeRecorded event carrying the "
                    "asserted outcome_label; SFT eligibility is unproven"
                )
            elif not bound_outcome_ids:
                errors.append(
                    "no OutcomeRecorded event with the asserted label is "
                    "bound to this content (its recorded content_hash must "
                    "equal the candidate's); an outcome that judged different "
                    "content cannot authorise the SFT example"
                )
            elif provenance.isdisjoint(bound_outcome_ids):
                errors.append(
                    "provenance does not cite the OutcomeRecorded event "
                    "bound to this content (source_events cannot prove "
                    "eligibility)"
                )

        # 5. DPO evidence: a candidate that asserts a corrected output
        #    REQUIRES the ledger to record a matching correction AND the
        #    provenance must CITE a CorrectionRecorded event that is BOUND
        #    to this content. "Bound" means the cited event's recorded
        #    content_hash equals the candidate's own content hash — the
        #    correction event was written FOR this exact (rejected,
        #    corrected) pair. A correction marker that merely exists for the
        #    task (a stray/unrelated event, or one recording different
        #    content, or a pre-binding legacy event with no hash) cannot
        #    authorise newly-invented training content. The cited event ID
        #    and the resolved content must be the same fact, not two facts
        #    that happen to co-exist.
        if candidate.corrected_output is not None:
            if view.correction is None:
                errors.append(
                    "ledger has no correction for a candidate that asserts "
                    "a corrected_output (DPO correction evidence required)"
                )
            elif candidate.corrected_output != view.correction:
                errors.append("corrected_output does not match ledger record")

            bound_correction_ids = {
                ev.event_id
                for ev in view.correction_events
                if ev.content_hash is not None
                and ev.content_hash == candidate.content_hash
            }
            if not view.correction_events:
                errors.append(
                    "ledger has no CorrectionRecorded event; DPO eligibility "
                    "is unproven (a resolver correction alone is insufficient)"
                )
            elif not bound_correction_ids:
                errors.append(
                    "no CorrectionRecorded event is bound to this pair's "
                    "content (its recorded content_hash must equal the "
                    "candidate's); a correction marker that does not carry "
                    "this exact content cannot authorise the DPO pair"
                )
            elif provenance.isdisjoint(bound_correction_ids):
                errors.append(
                    "provenance does not cite the CorrectionRecorded event "
                    "bound to this pair's content (source_events cannot "
                    "prove eligibility)"
                )

        return errors


class AcceptAllVerifier:
    """
    Accepts any provenance without ledger verification.

    USE ONLY in offline demos and unit tests that do not exercise
    provenance verification. NEVER in a production export pipeline — it
    defeats the dataset-poisoning protection.
    """

    def verify(self, candidate: TrainingCandidate) -> list[str]:
        return []
