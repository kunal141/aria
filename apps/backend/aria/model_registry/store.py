"""
Model Registry Store — Week 29 Priority 4.

``ModelStore`` Protocol + ``InMemoryModelStore``.

This store mirrors ``aria.evolution.update_manager.store.InMemoryUpdateStore``
deliberately — same atomic-flush, fail-closed, snapshot-rollback, and
component-keyed-lock design — so the registry reuses a hardened pattern rather
than inventing a weaker parallel one. The differences are domain-specific:

  - records are keyed by ``model_id`` (immutable version identity);
  - the lifecycle invariant is *at most one ``ACTIVE`` model per
    ``production_consumer``* (a consumer can have only one live model);
  - the concurrency primitive is keyed by ``production_consumer`` (two
    activations targeting the same consumer serialize; different consumers
    proceed in parallel).

Persistence
-----------
``InMemoryModelStore`` accepts an optional ``persist_path``. When set, every
successful mutation rewrites the file (JSON Lines, one ``ModelRecord`` per
line) via atomic tmp+replace. On init the file is loaded if it exists, giving
the registry restart-survival without a database dependency in V1.

Fail-closed
-----------
If a disk flush fails, in-memory state is rolled back to the last durable
value and ``RegistryPersistenceError`` is raised — a caller never sees a false
success. If a batch would leave more than one ACTIVE model for a consumer, the
whole batch is rejected atomically and ``MultipleActiveModelsError`` is raised
before any disk write.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from aria.model_registry.models import (
    ModelRecord,
    ModelStatus,
    MultipleActiveModelsError,
    RegistryCorruptionError,
    RegistryPersistenceError,
)


@runtime_checkable
class ModelStore(Protocol):
    def save(self, record: ModelRecord) -> None: ...
    def save_batch(self, records: list[ModelRecord]) -> None: ...
    def get(self, model_id: str) -> Optional[ModelRecord]: ...
    def list_all(self) -> list[ModelRecord]: ...
    def list_by_status(self, status: ModelStatus) -> list[ModelRecord]: ...
    def list_by_consumer(self, production_consumer: str) -> list[ModelRecord]: ...
    def delete(self, model_id: str) -> bool: ...
    def acquire_consumer(self, production_consumer: str) -> bool: ...
    def release_consumer(self, production_consumer: str) -> None: ...


class InMemoryModelStore:
    """
    In-memory ``ModelStore`` with optional file persistence and a
    consumer-level activation lock. See the module docstring for the
    concurrency and invariant contracts this store guarantees.
    """

    def __init__(self, persist_path: Optional[Path | str] = None) -> None:
        self._store: dict[str, ModelRecord] = {}
        self._rw_lock        = threading.Lock()
        self._consumer_lock  = threading.Lock()
        self._held_consumers: set[str] = set()
        self._persist_path   = Path(persist_path) if persist_path is not None else None
        if self._persist_path is not None:
            self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """
        Load existing records from the JSONL file on startup — FAIL CLOSED.

        A persisted registry is governance evidence: it decides which model is
        ACTIVE in production. Silently skipping a malformed, duplicate, or
        invariant-violating line would let a corrupted file boot a registry
        into a wrong/ambiguous state without anyone noticing. So every defect
        is escalated to ``RegistryCorruptionError`` and the registry refuses to
        start, rather than starting on partial state.
        """
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            raw = self._persist_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RegistryCorruptionError(
                f"Could not read registry file {self._persist_path}: {exc}"
            ) from exc

        loaded: dict[str, ModelRecord] = {}
        for lineno, line in enumerate(raw.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = ModelRecord.model_validate(json.loads(line))
            except Exception as exc:
                raise RegistryCorruptionError(
                    f"Malformed record at line {lineno} of "
                    f"{self._persist_path}: {exc}"
                ) from exc
            if record.model_id in loaded:
                raise RegistryCorruptionError(
                    f"Duplicate model_id {record.model_id!r} at line {lineno} "
                    f"of {self._persist_path} — registry identity must be unique."
                )
            loaded[record.model_id] = record

        self._store = loaded
        try:
            self._check_active_invariant()
        except MultipleActiveModelsError as exc:
            self._store = {}
            raise RegistryCorruptionError(
                f"Persisted registry {self._persist_path} violates the "
                f"at-most-one-active invariant: {exc.violators!r}"
            ) from exc

    def _flush(self) -> None:
        """Rewrite the JSONL file with current in-memory state. Raises OSError on failure."""
        if self._persist_path is None:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._persist_path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for record in self._store.values():
                fh.write(record.model_dump_json() + "\n")
        os.replace(tmp, self._persist_path)  # atomic rename on all platforms

    # ── Invariant ──────────────────────────────────────────────────────────────

    def _check_active_invariant(self) -> None:
        """
        Raise ``MultipleActiveModelsError`` if the current in-memory state holds
        more than one ACTIVE model for any production consumer. Called inside
        ``save`` / ``save_batch`` BEFORE the disk flush so an invariant
        violation aborts the commit.
        """
        active_by_consumer: dict[str, list[str]] = {}
        for r in self._store.values():
            if r.status == ModelStatus.active:
                active_by_consumer.setdefault(r.production_consumer, []).append(r.model_id)
        violators = {c: ids for c, ids in active_by_consumer.items() if len(ids) > 1}
        if violators:
            raise MultipleActiveModelsError(violators)

    # ── CRUD ───────────────────────────────────────────────────────────────────

    def save(self, record: ModelRecord) -> None:
        """
        Persist a single record. Fail-closed: if the active-model invariant OR
        the disk flush fails, in-memory state is restored to the last durable
        value and the appropriate exception is raised so callers never see a
        false success.
        """
        with self._rw_lock:
            old = self._store.get(record.model_id)
            self._store[record.model_id] = record
            try:
                self._check_active_invariant()
            except MultipleActiveModelsError:
                self._restore(record.model_id, old)
                raise
            try:
                self._flush()
            except OSError as exc:
                self._restore(record.model_id, old)
                raise RegistryPersistenceError(
                    f"Failed to flush model {record.model_id!r} to "
                    f"{self._persist_path}: {exc}"
                ) from exc

    def save_batch(self, records: list[ModelRecord]) -> None:
        """
        Atomically persist multiple records in a single flush.

        Order of operations:
          1. Snapshot every record being changed (for rollback).
          2. Apply all records in memory.
          3. Check the at-most-one-active-per-consumer invariant. If violated,
             restore every record to its prior durable value and raise
             ``MultipleActiveModelsError`` — no record from the batch is visible.
          4. Flush to disk. If the flush fails, restore every record and raise
             ``RegistryPersistenceError``. No partial commit is ever visible.
        """
        if not records:
            return
        with self._rw_lock:
            snapshots: dict[str, ModelRecord | None] = {
                r.model_id: self._store.get(r.model_id) for r in records
            }
            for r in records:
                self._store[r.model_id] = r

            try:
                self._check_active_invariant()
            except MultipleActiveModelsError:
                for r in records:
                    self._restore(r.model_id, snapshots[r.model_id])
                raise

            try:
                self._flush()
            except OSError as exc:
                for r in records:
                    self._restore(r.model_id, snapshots[r.model_id])
                raise RegistryPersistenceError(
                    f"Batch save of {[r.model_id for r in records]!r} failed — "
                    f"all changes rolled back: {exc}"
                ) from exc

    def _restore(self, model_id: str, old: Optional[ModelRecord]) -> None:
        if old is not None:
            self._store[model_id] = old
        else:
            self._store.pop(model_id, None)

    def get(self, model_id: str) -> Optional[ModelRecord]:
        with self._rw_lock:
            return self._store.get(model_id)

    def list_all(self) -> list[ModelRecord]:
        with self._rw_lock:
            return list(self._store.values())

    def list_by_status(self, status: ModelStatus) -> list[ModelRecord]:
        with self._rw_lock:
            return [r for r in self._store.values() if r.status == status]

    def list_by_consumer(self, production_consumer: str) -> list[ModelRecord]:
        with self._rw_lock:
            return [
                r for r in self._store.values()
                if r.production_consumer == production_consumer
            ]

    def delete(self, model_id: str) -> bool:
        with self._rw_lock:
            if model_id in self._store:
                old = self._store.pop(model_id)
                try:
                    self._flush()
                except OSError as exc:
                    self._store[model_id] = old
                    raise RegistryPersistenceError(
                        f"Failed to flush after deleting {model_id!r}: {exc}"
                    ) from exc
                return True
        return False

    # ── Consumer-level activation lock ─────────────────────────────────────────

    def acquire_consumer(self, production_consumer: str) -> bool:
        """
        Acquire the activation lock for ``production_consumer``.

        Returns True if acquired; False if another caller already holds it.
        Different consumers may be acquired concurrently; the same consumer
        serialises strictly. Callers MUST release in a finally block.
        """
        with self._consumer_lock:
            if production_consumer in self._held_consumers:
                return False
            self._held_consumers.add(production_consumer)
            return True

    def release_consumer(self, production_consumer: str) -> None:
        """Release the consumer-level activation lock. Idempotent — safe in finally."""
        with self._consumer_lock:
            self._held_consumers.discard(production_consumer)

    def is_consumer_locked(self, production_consumer: str) -> bool:
        with self._consumer_lock:
            return production_consumer in self._held_consumers

    def __len__(self) -> int:
        with self._rw_lock:
            return len(self._store)
