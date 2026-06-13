"""
Ledger v2 writer — concurrency-safe append + event_id idempotency.

Design
------
- One ``LedgerWriter`` instance per JSONL file.
- All writes serialise on a ``threading.Lock`` (in-process concurrency
  guarantee).  Cross-process locking is a deliberate follow-up — see
  ``MULTI_PROCESS_NOTE`` below.
- Each ``event_id`` is unique.  On init the writer scans the file and
  loads the set of seen IDs; an ``append`` with a duplicate ID is a no-op
  (returns ``False``) — never raises, never double-writes.  This makes
  retries safe and prevents metric inflation.
- Persistence failure (any ``OSError`` during write) raises
  ``LedgerPersistenceError`` so callers cannot mistakenly believe an
  event was logged.  In particular, the writer NEVER fabricates a
  successful lifecycle event after a flush failure.
- Money values (``Decimal``) and timezone-aware datetimes are serialised
  via Pydantic's standard JSON mode (Decimal → string).

MULTI_PROCESS_NOTE
------------------
The lock used here is ``threading.Lock``.  Two separate Python processes
writing to the same JSONL file at the same time may interleave bytes.
This is acceptable for V1 (single backend process); cross-process
locking via ``portalocker`` or a tiny lock-file sidecar is queued for
Priority 2 follow-up if multi-process writers become real.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, TypeAdapter, ValidationError

from aria.ledger.events import LedgerEvent, LedgerEventType
from aria.ledger.exceptions import LedgerPersistenceError


# Terminal lifecycle event types — a task may have AT MOST ONE of these,
# and they must agree (Responded XOR Failed, not both). The writer
# enforces this invariant across appends so two callers cannot tag the
# same task as both completed and failed (which would corrupt
# completion / failure / failure_rate metrics).
_TERMINAL_EVENT_TYPES: frozenset[LedgerEventType] = frozenset({
    LedgerEventType.responded,
    LedgerEventType.failed,
})


class TerminalOutcomeConflict(ValueError):
    """Raised when a task already has a terminal outcome of a different type."""

    def __init__(
        self,
        task_id: str,
        existing: LedgerEventType,
        attempted: LedgerEventType,
    ) -> None:
        self.task_id = task_id
        self.existing = existing
        self.attempted = attempted
        super().__init__(
            f"Task {task_id!r} already has a terminal {existing.value!r} "
            f"event; refusing to append a conflicting terminal "
            f"{attempted.value!r} event. A task has at most one "
            "terminal outcome."
        )


# Environment overrides
#
# - ``ARIA_LEDGER_V2_PATH``     — overrides the singleton writer's file
#   path. Tests set this (via the autouse conftest fixture) so they
#   never touch the runtime ``apps/backend/work_ledger_v2.jsonl``.
# - ``ARIA_LEDGER_V2_DISABLED`` — when truthy (``1``, ``true``, ``yes``)
#   the singleton returns a ``_NullWriter`` whose ``append`` is a no-op.
#   Used by tests that don't care about ledger emission.
_ENV_PATH_VAR = "ARIA_LEDGER_V2_PATH"
_ENV_DISABLE_VAR = "ARIA_LEDGER_V2_DISABLED"


_LEDGER_ADAPTER: TypeAdapter[LedgerEvent] = TypeAdapter(LedgerEvent)


class LedgerWriter:
    """Append-only writer for Work Ledger v2 events."""

    def __init__(self, path: str | Path) -> None:
        self._path: Path = Path(path)
        self._lock: threading.Lock = threading.Lock()
        self._seen_event_ids: set[str] = set()
        self._seen_event_fingerprints: dict[str, str] = {}
        # Per-task terminal outcome already on disk.  Enforced on every
        # append of a Responded / Failed event.
        self._task_terminal_outcomes: dict[str, LedgerEventType] = {}
        self._load_seen_ids()

    # ── Idempotency / seen-set ───────────────────────────────────────────────

    def _load_seen_ids(self) -> None:
        """
        Populate the in-memory seen-set from the existing file on init.

        Each line is **validated against the discriminated union** before
        its ``event_id`` is registered. A malformed line therefore cannot
        suppress a later valid event with the same ID — the reader will
        surface the malformed record, and the writer will accept the
        valid retry.

        For each successfully validated record we also store a content
        fingerprint (``_seen_event_fingerprints``) so that a later
        ``append`` with the same ``event_id`` but **different content**
        is rejected as a logic bug rather than silently treated as a
        retry.
        """
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                try:
                    validated = _LEDGER_ADAPTER.validate_python(obj)
                except ValidationError:
                    # Don't reserve the ID for an invalid record.
                    continue
                self._seen_event_ids.add(validated.event_id)
                self._seen_event_fingerprints[validated.event_id] = (
                    self._fingerprint(validated)
                )
                if validated.event_type in _TERMINAL_EVENT_TYPES:
                    # Round 6: a pre-existing file MAY contain two
                    # conflicting terminal records (legacy bug or
                    # tampering). If startup silently overwrites the
                    # earlier value with the later, metrics will hide
                    # the conflict and a task will appear as a single
                    # outcome when on disk there are two. Detect the
                    # conflict at load time and refuse to open — the
                    # operator must reconcile the ledger before the
                    # process starts persisting more data on top of an
                    # already-inconsistent state.
                    existing_terminal = self._task_terminal_outcomes.get(
                        validated.task_id
                    )
                    if (
                        existing_terminal is not None
                        and existing_terminal != validated.event_type
                    ):
                        raise TerminalOutcomeConflict(
                            task_id=validated.task_id,
                            existing=existing_terminal,
                            attempted=validated.event_type,
                        )
                    self._task_terminal_outcomes[validated.task_id] = (
                        validated.event_type
                    )

    @staticmethod
    def _fingerprint(validated_event: LedgerEvent) -> str:
        """Stable content hash used for idempotent-retry vs. conflict detection."""
        canonical = validated_event.model_dump_json(by_alias=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ── Append ───────────────────────────────────────────────────────────────

    def append(self, event: object, *, idempotent_on_collision: bool = False) -> bool:
        """
        Persist one event.  The writer is the FINAL sanitisation
        boundary: every input (model instance OR raw dict) is dumped to
        a plain payload and re-validated through the discriminated
        union, so all redaction / required-field validators are
        guaranteed to run. This closes the
        ``model_copy(update={"error": "sk-..."})`` bypass — those
        updates skip validators on the source model, but the writer
        re-runs them here before anything is fingerprinted or written.

        Parameters
        ----------
        event :
            A typed event model or raw dict matching the discriminated
            union schema.
        idempotent_on_collision :
            Opt-in for callers using **deterministic** ``event_id``
            values (e.g. lifecycle events). When True, an event_id that
            is already on disk returns ``False`` REGARDLESS of payload
            fingerprint differences. This is the atomic check-and-append
            primitive required by ``respond.py``: two concurrent retries
            for the same lifecycle event collapse to one durable line,
            with no fingerprint-conflict ``ValueError`` for stale
            timestamps. Default ``False`` preserves the strict-conflict
            behaviour for non-deterministic callers.

        Returns
        -------
        ``True``  on a new event durably written.
        ``False`` if ``event.event_id`` is already on disk and either
                 (a) the payload is byte-identical (idempotent retry), or
                 (b) ``idempotent_on_collision=True`` was passed.

        Raises
        ------
        - ``LedgerPersistenceError`` on any flush failure.
        - ``ValueError`` when an event_id has already been written with
          a DIFFERENT payload and ``idempotent_on_collision=False``.
        - ``TerminalOutcomeConflict`` when the task already has a
          terminal outcome of a different type (Responded vs Failed).
        - ``pydantic.ValidationError`` for schema violations.
        """
        if isinstance(event, BaseModel):
            payload = event.model_dump(mode="json")
        else:
            payload = event
        validated = _LEDGER_ADAPTER.validate_python(payload)
        ev_id = validated.event_id
        fingerprint = self._fingerprint(validated)
        is_terminal = validated.event_type in _TERMINAL_EVENT_TYPES

        with self._lock:
            # Atomic check-and-append boundary. Holding the lock here is
            # what makes ``idempotent_on_collision`` safe under
            # concurrent retries: two threads calling for the same
            # event_id serialise — the second sees the seen-set updated
            # by the first and returns False.
            if ev_id in self._seen_event_ids:
                if idempotent_on_collision:
                    return False
                prior = self._seen_event_fingerprints.get(ev_id)
                if prior is not None and prior != fingerprint:
                    raise ValueError(
                        f"event_id {ev_id!r} already persisted with a different "
                        "payload; refusing to overwrite or double-count. This "
                        "indicates a logic bug — two semantically distinct "
                        "events were given the same event_id."
                    )
                return False

            # Cross-event invariant: a task has at most one terminal
            # outcome. Reject a Failed when Responded already won (or
            # vice versa), so the failure_rate metric cannot
            # simultaneously classify a task as completed and failed.
            if is_terminal:
                existing_terminal = self._task_terminal_outcomes.get(validated.task_id)
                if existing_terminal is not None and existing_terminal != validated.event_type:
                    raise TerminalOutcomeConflict(
                        task_id=validated.task_id,
                        existing=existing_terminal,
                        attempted=validated.event_type,
                    )

            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise LedgerPersistenceError(
                    f"Failed to create parent directory for {self._path}: {exc}"
                ) from exc

            line = validated.model_dump_json()
            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError as exc:
                raise LedgerPersistenceError(
                    f"Failed to append event {ev_id!r} to {self._path}: {exc}"
                ) from exc

            self._seen_event_ids.add(ev_id)
            self._seen_event_fingerprints[ev_id] = fingerprint
            if is_terminal:
                self._task_terminal_outcomes[validated.task_id] = validated.event_type
            return True

    def append_many(self, events: Iterable[object]) -> int:
        """Append a batch.  Returns the count of newly-written events."""
        written = 0
        for ev in events:
            if self.append(ev):
                written += 1
        return written

    # ── Introspection ────────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    def has_event_id(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._seen_event_ids

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen_event_ids)


# ── Singleton entry point for production writers ──────────────────────────────


_DEFAULT_LEDGER_V2_PATH: Path = (
    Path(__file__).parent.parent.parent / "work_ledger_v2.jsonl"
)


class _NullWriter:
    """No-op writer returned when ARIA_LEDGER_V2_DISABLED is set."""

    path: Path = Path("/dev/null-ledger")

    def append(self, _event: object) -> bool:  # pragma: no cover - trivial
        return False

    def append_many(self, _events: Iterable[object]) -> int:  # pragma: no cover
        return 0

    def has_event_id(self, _event_id: str) -> bool:  # pragma: no cover
        return False

    def __len__(self) -> int:  # pragma: no cover
        return 0


_default_writer: Optional[LedgerWriter | _NullWriter] = None
_default_writer_lock = threading.Lock()


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_default_path() -> Path:
    override = os.environ.get(_ENV_PATH_VAR)
    if override:
        return Path(override)
    return _DEFAULT_LEDGER_V2_PATH


def get_default_writer() -> "LedgerWriter | _NullWriter":
    """
    Lazy singleton for the production ledger.

    Resolution order on first call:
      1. ``ARIA_LEDGER_V2_DISABLED`` truthy → ``_NullWriter`` (no I/O).
      2. ``ARIA_LEDGER_V2_PATH`` set       → writer at that path.
      3. fallback                          → ``work_ledger_v2.jsonl`` next
                                              to the package.

    Tests rely on this resolution via an autouse fixture in
    ``apps/backend/tests/conftest.py`` that sets
    ``ARIA_LEDGER_V2_PATH=<tmp_path>/ledger.jsonl`` and resets the
    singleton, guaranteeing graph invocations during tests cannot
    touch the runtime ledger file.
    """
    global _default_writer
    with _default_writer_lock:
        if _default_writer is None:
            if _truthy(os.environ.get(_ENV_DISABLE_VAR)):
                _default_writer = _NullWriter()
            else:
                _default_writer = LedgerWriter(_resolve_default_path())
        return _default_writer


def configure_default_writer(writer: Optional["LedgerWriter | _NullWriter"]) -> None:
    """Override the default writer (used by tests + the demo script)."""
    global _default_writer
    with _default_writer_lock:
        _default_writer = writer


def reset_default_writer() -> None:
    """Drop the singleton so the next ``get_default_writer`` re-reads env."""
    global _default_writer
    with _default_writer_lock:
        _default_writer = None
