"""
Unified Work Ledger reader.

Surfaces three on-disk sources through one typed interface:

  ``work_ledger_v2.jsonl``     → v2 ``LedgerEvent`` records
  ``work_ledger.jsonl``        → ``LegacyTaskRecord`` (Week-4 schema)
  ``evolution_events.jsonl``   → ``LegacyEvolutionRecord``

Records that fail to parse are returned as ``MalformedLedgerRecord``
objects (NOT silently skipped) so the caller can observe corruption,
unknown schemas, or partial writes.  Per the Week-29 persistence rule,
silent deletion of malformed lines is forbidden — callers must see them
to decide what to do.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union

from pydantic import TypeAdapter, ValidationError

from aria.ledger.events import (
    LedgerEvent,
    LedgerEventType,
    LegacyEvolutionRecord,
    LegacyTaskRecord,
)
from aria.ledger.exceptions import MalformedLedgerRecord


_LEDGER_ADAPTER: TypeAdapter[LedgerEvent] = TypeAdapter(LedgerEvent)

# Evolution event types known to the legacy writer.  Anything outside
# this set in evolution_events.jsonl is treated as malformed (it cannot
# be safely adapted to LegacyEvolutionRecord).
_LEGACY_EVOLUTION_KNOWN_TYPES: frozenset[str] = frozenset({
    "proposal", "generation", "sandbox", "approval_request", "approval",
    "canary", "verification", "promotion", "activation", "failure",
})


class LedgerSource(str, Enum):
    v2               = "v2"
    legacy_task      = "legacy_task"
    legacy_evolution = "legacy_evolution"


# Public union type returned by ``LedgerReader.read_all``.
LedgerRecord = Union[
    LedgerEvent,
    LegacyTaskRecord,
    LegacyEvolutionRecord,
    MalformedLedgerRecord,
]


@dataclass(frozen=True)
class SourceFile:
    """One on-disk source the reader knows how to parse."""
    source: LedgerSource
    path:   Path


class LedgerReader:
    """
    Read all configured sources and yield typed records.

    Typical use:

      reader = LedgerReader(
          v2_path=...,
          legacy_task_path=...,
          legacy_evolution_path=...,
      )
      for record in reader.read_all():
          ...
    """

    def __init__(
        self,
        *,
        v2_path:               Optional[Path | str] = None,
        legacy_task_path:      Optional[Path | str] = None,
        legacy_evolution_path: Optional[Path | str] = None,
    ) -> None:
        self._sources: list[SourceFile] = []
        if v2_path is not None:
            self._sources.append(SourceFile(LedgerSource.v2, Path(v2_path)))
        if legacy_task_path is not None:
            self._sources.append(SourceFile(LedgerSource.legacy_task, Path(legacy_task_path)))
        if legacy_evolution_path is not None:
            self._sources.append(SourceFile(LedgerSource.legacy_evolution, Path(legacy_evolution_path)))

    # ── Public API ──────────────────────────────────────────────────────────

    def read_all(self) -> list[LedgerRecord]:
        return list(self.iter_all())

    def iter_all(self) -> Iterator[LedgerRecord]:
        for src in self._sources:
            yield from self._iter_source(src)

    def read_by_source(self, source: LedgerSource) -> list[LedgerRecord]:
        return [
            r
            for sf in self._sources if sf.source == source
            for r in self._iter_source(sf)
        ]

    def v2_events(self) -> list[LedgerEvent]:
        """Convenience: only v2 events, malformed records discarded."""
        return [r for r in self.iter_all() if _is_v2_event(r)]

    def malformed(self) -> list[MalformedLedgerRecord]:
        return [r for r in self.iter_all() if isinstance(r, MalformedLedgerRecord)]

    @property
    def sources(self) -> list[SourceFile]:
        return list(self._sources)

    # ── Internals ───────────────────────────────────────────────────────────

    def _iter_source(self, src: SourceFile) -> Iterator[LedgerRecord]:
        if not src.path.exists():
            return
        with src.path.open(encoding="utf-8") as fh:
            for idx, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                yield self._parse_line(src.source, src.path, idx, line)

    def _parse_line(
        self,
        source: LedgerSource,
        path: Path,
        line_number: int,
        line: str,
    ) -> LedgerRecord:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return MalformedLedgerRecord(
                source=str(path), line_number=line_number, raw=line,
                parse_error=f"JSONDecodeError: {exc}",
            )
        if not isinstance(obj, dict):
            return MalformedLedgerRecord(
                source=str(path), line_number=line_number, raw=line,
                parse_error=f"Top-level JSON must be an object; got {type(obj).__name__}",
            )

        if source is LedgerSource.v2:
            return _parse_v2(obj, path, line_number, line)
        if source is LedgerSource.legacy_task:
            return _parse_legacy_task(obj, path, line_number, line)
        if source is LedgerSource.legacy_evolution:
            return _parse_legacy_evolution(obj, path, line_number, line)
        return MalformedLedgerRecord(
            source=str(path), line_number=line_number, raw=line,
            parse_error=f"Unknown source: {source}",
        )


# ── Per-source parsers ────────────────────────────────────────────────────────


def _parse_v2(
    obj: dict, path: Path, line_number: int, raw: str,
) -> LedgerRecord:
    try:
        return _LEDGER_ADAPTER.validate_python(obj)
    except ValidationError as exc:
        return MalformedLedgerRecord(
            source=str(path), line_number=line_number, raw=raw,
            parse_error=f"v2 validation failed: {exc.errors()[0] if exc.errors() else exc}",
        )


def _parse_legacy_task(
    obj: dict, path: Path, line_number: int, raw: str,
) -> LedgerRecord:
    # Reject anything that doesn't carry a task_id — the legacy writer
    # always set one, so an entry without it is genuine corruption.
    if "task_id" not in obj or not obj.get("task_id"):
        return MalformedLedgerRecord(
            source=str(path), line_number=line_number, raw=raw,
            parse_error="legacy task record missing task_id",
        )
    try:
        return LegacyTaskRecord.model_validate(obj)
    except ValidationError as exc:
        return MalformedLedgerRecord(
            source=str(path), line_number=line_number, raw=raw,
            parse_error=f"legacy task validation failed: {exc.errors()[0] if exc.errors() else exc}",
        )


def _parse_legacy_evolution(
    obj: dict, path: Path, line_number: int, raw: str,
) -> LedgerRecord:
    original = obj.get("event_type")
    if not isinstance(original, str) or original not in _LEGACY_EVOLUTION_KNOWN_TYPES:
        return MalformedLedgerRecord(
            source=str(path), line_number=line_number, raw=raw,
            parse_error=(
                f"unknown legacy evolution event_type: {original!r} "
                f"(known: {sorted(_LEGACY_EVOLUTION_KNOWN_TYPES)})"
            ),
        )
    adapted = dict(obj)
    adapted["original_type"] = original
    adapted["event_type"] = LedgerEventType.legacy_evolution.value
    try:
        return LegacyEvolutionRecord.model_validate(adapted)
    except ValidationError as exc:
        return MalformedLedgerRecord(
            source=str(path), line_number=line_number, raw=raw,
            parse_error=f"legacy evolution validation failed: {exc.errors()[0] if exc.errors() else exc}",
        )


def _is_v2_event(record: LedgerRecord) -> bool:
    return (
        not isinstance(record, MalformedLedgerRecord)
        and not isinstance(record, LegacyTaskRecord)
        and not isinstance(record, LegacyEvolutionRecord)
    )


def filter_v2(records: Iterable[LedgerRecord]) -> list[LedgerEvent]:
    """Helper: keep only the v2 events from a mixed-record stream."""
    return [r for r in records if _is_v2_event(r)]  # type: ignore[return-value]
