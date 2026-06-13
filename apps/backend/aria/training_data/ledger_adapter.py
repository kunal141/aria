"""
Real ledger adapter for provenance verification.

``WorkLedgerVerifier`` checks a candidate against a ``TaskLedgerView``.
On its own it accepts whatever ``dict[str, TaskLedgerView]`` a caller
hands it — fine for unit tests, but not a real provenance check. This
module closes that gap: ``LedgerTaskViewBuilder`` constructs the views
from ACTUAL Work Ledger v2 events read through ``LedgerReader``, so
verification is backed by recorded ledger events, not a caller-fabricated
mapping.

What the ledger does and does NOT hold
--------------------------------------
Work Ledger events record WHAT happened — the event IDs for a task and
the outcome label of an ``OutcomeRecorded`` event. They do NOT store the
training *content* itself (the input / output / corrected text) or its
canonical hash. Corroborating a candidate's ``content_hash`` (and the
DPO ``correction`` text) therefore requires a separate governed source:
the artifact / content store. That source is reached through a
``TaskContentResolver`` — an explicit adapter boundary.

This builder NEVER fabricates evidence. If no content resolver is
configured, or the resolver has no governed record for a task, the
view's ``content_hash`` / ``correction`` stay ``None`` and the verifier
fails closed (required-evidence rule in ``verifier.py``). A view is only
as strong as the governed sources behind it.

Malformed ledger lines are not silently dropped: by default the builder
raises ``LedgerAdapterError`` if the reader surfaced any malformed
record, because building views over a partially-parsed ledger could omit
event IDs and wrongly accept or reject a candidate. Callers that have
already inspected the corruption may opt out with
``allow_malformed=True``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from aria.ledger.events import CorrectionRecorded, OutcomeRecorded
from aria.ledger.reader import LedgerReader
from aria.training_data.verifier import (
    LedgerCorrectionEvent,
    LedgerOutcomeEvent,
    TaskLedgerView,
)


class LedgerAdapterError(RuntimeError):
    """
    Raised when ledger-backed views cannot be built safely — currently
    when the reader surfaced malformed records and ``allow_malformed`` is
    False. Building over a partially-parsed ledger could omit event IDs
    and corrupt verification, so the builder fails closed.
    """


@dataclass(frozen=True)
class ResolvedContent:
    """
    Governed content facts for a single task, sourced from the artifact /
    content store (NOT the ledger). Either field may be ``None`` when the
    store holds no such governed record; the builder then leaves the
    corresponding view field ``None`` and the verifier fails closed.
    """
    content_hash: Optional[str] = None
    correction:   Optional[str] = None


@runtime_checkable
class TaskContentResolver(Protocol):
    """
    Resolves the governed training *content* for a task — the part the
    Work Ledger does not store.

    A production implementation reads the artifact / content store under
    the same governance as the ledger and returns the canonical
    ``content_hash`` (and the corrected text, for DPO) it holds for the
    task. It returns ``None`` — or a ``ResolvedContent`` whose fields are
    ``None`` — when no governed content exists. An implementation MUST
    NOT invent a hash or a correction; doing so would defeat the
    provenance check the resolver exists to support.
    """

    def resolve(self, task_id: str) -> Optional[ResolvedContent]:
        ...


class LedgerTaskViewBuilder:
    """
    Builds ``TaskLedgerView`` objects from real Work Ledger v2 events.

    For each ``task_id`` seen in the ledger:
      - ``event_ids``           = every v2 ``event_id`` recorded for that
                                  task (what ``candidate.provenance``
                                  references; used for the cross-task
                                  membership check).
      - ``outcome_label``       = the outcome of the most recent
                                  ``OutcomeRecorded`` event, or ``None``.
      - ``outcome_events``      = the (event_id, outcome, content_hash) of
                                  EVERY ``OutcomeRecorded`` event — the typed
                                  evidence an SFT candidate must cite, bound
                                  to the specific judged content.
      - ``correction_events``   = the (event_id, content_hash) of every
                                  ``CorrectionRecorded`` event — the typed
                                  evidence a DPO candidate must cite, bound
                                  to the specific corrected content.
      - ``content_hash`` /
        ``correction``          = supplied by the ``TaskContentResolver``
                                  (the ledger does not store content);
                                  ``None`` when no resolver is configured
                                  or no governed record exists.

    Parameters
    ----------
    reader
        A configured ``LedgerReader`` over the real JSONL ledger
        source(s).
    content_resolver
        Optional governed content/artifact resolver. Without it,
        ``content_hash`` and ``correction`` are always ``None`` and the
        verifier rejects every candidate (fail closed) — a builder with
        no resolver can prove event provenance and outcome labels but
        cannot corroborate content.
    allow_malformed
        When ``False`` (default) the builder raises ``LedgerAdapterError``
        if the reader surfaced any malformed record.
    """

    def __init__(
        self,
        reader: LedgerReader,
        *,
        content_resolver: Optional[TaskContentResolver] = None,
        allow_malformed: bool = False,
    ) -> None:
        self._reader = reader
        self._resolver = content_resolver
        self._allow_malformed = allow_malformed

    def build(self) -> dict[str, TaskLedgerView]:
        """Group ledger events by task and materialise one view per task."""
        if not self._allow_malformed:
            malformed = self._reader.malformed()
            if malformed:
                raise LedgerAdapterError(
                    f"Refusing to build ledger views over a partially-parsed "
                    f"ledger: {len(malformed)} malformed record(s) surfaced by "
                    f"the reader. Reconcile the ledger, or pass "
                    f"allow_malformed=True after inspecting them."
                )

        event_ids_by_task: dict[str, set[str]] = {}
        latest_outcome: dict[str, tuple[datetime, str]] = {}
        outcome_events_by_task: dict[str, set[LedgerOutcomeEvent]] = {}
        correction_events_by_task: dict[str, set[LedgerCorrectionEvent]] = {}

        for event in self._reader.v2_events():
            event_ids_by_task.setdefault(event.task_id, set()).add(event.event_id)
            if isinstance(event, OutcomeRecorded) and event.outcome:
                outcome_events_by_task.setdefault(event.task_id, set()).add(
                    LedgerOutcomeEvent(
                        event_id=event.event_id,
                        outcome=event.outcome,
                        content_hash=event.content_hash,
                    )
                )
                prev = latest_outcome.get(event.task_id)
                if prev is None or event.timestamp >= prev[0]:
                    latest_outcome[event.task_id] = (event.timestamp, event.outcome)
            elif isinstance(event, CorrectionRecorded):
                correction_events_by_task.setdefault(event.task_id, set()).add(
                    LedgerCorrectionEvent(
                        event_id=event.event_id,
                        content_hash=event.content_hash,
                    )
                )

        views: dict[str, TaskLedgerView] = {}
        for task_id, event_ids in event_ids_by_task.items():
            resolved = (
                self._resolver.resolve(task_id) if self._resolver is not None else None
            )
            outcome = latest_outcome.get(task_id)
            views[task_id] = TaskLedgerView(
                task_id=task_id,
                event_ids=frozenset(event_ids),
                content_hash=resolved.content_hash if resolved else None,
                outcome_label=outcome[1] if outcome else None,
                correction=resolved.correction if resolved else None,
                outcome_events=frozenset(outcome_events_by_task.get(task_id, set())),
                correction_events=frozenset(
                    correction_events_by_task.get(task_id, set())
                ),
            )
        return views
