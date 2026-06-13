"""
Update Store — Week 28

UpdateStore Protocol + InMemoryUpdateStore.

Concurrency boundary
--------------------
The store exposes a single, component-keyed concurrency primitive:
``acquire_component(component_name)`` / ``release_component(component_name)``.
Every lifecycle mutation (promotion, rollback) MUST be performed inside this
lock. Two operations targeting the same component serialize; operations on
different components proceed in parallel. There is no update_id-keyed lock —
the component is the only correctness boundary.

Invariant
---------
After every successful ``save_batch``, the store guarantees that at most one
release per component holds ``status == active``. If a batch would violate
this invariant, the entire batch is rejected atomically (no record is committed
to memory or disk) and ``MultipleActiveReleasesError`` is raised. This is the
final defensive guarantee — even if a caller bypasses the component lock, the
store will not silently install two simultaneously-active releases.

Persistence
-----------
``InMemoryUpdateStore`` accepts an optional ``persist_path``. When set, every
successful mutation rewrites the file (JSON Lines, one UpdateRelease per line)
via atomic tmp+replace. On init the file is loaded if it exists. This gives
update records restart-survival without a database dependency in V1.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from aria.evolution.update_manager.models import (
    MultipleActiveReleasesError,
    UpdateRelease,
    UpdateStatus,
)


class PersistenceError(RuntimeError):
    """Raised when the update store cannot durably flush a record to disk."""


@runtime_checkable
class UpdateStore(Protocol):
    def save(self, update: UpdateRelease) -> None: ...
    def save_batch(self, updates: list[UpdateRelease]) -> None: ...
    def get(self, update_id: str) -> Optional[UpdateRelease]: ...
    def list_all(self) -> list[UpdateRelease]: ...
    def list_by_status(self, status: UpdateStatus) -> list[UpdateRelease]: ...
    def list_by_component(self, component_name: str) -> list[UpdateRelease]: ...
    def delete(self, update_id: str) -> bool: ...
    def acquire_component(self, component_name: str) -> bool: ...
    def release_component(self, component_name: str) -> None: ...


class InMemoryUpdateStore:
    """
    In-memory UpdateStore with optional file persistence and a component-level
    activation lock. See module docstring for the concurrency and invariant
    contracts this store guarantees.
    """

    def __init__(self, persist_path: Optional[Path | str] = None) -> None:
        self._store: dict[str, UpdateRelease] = {}
        self._rw_lock         = threading.Lock()
        self._component_lock  = threading.Lock()
        self._held_components: set[str] = set()
        self._persist_path    = Path(persist_path) if persist_path is not None else None
        if self._persist_path is not None:
            self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load existing records from JSONL file on startup."""
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            with open(self._persist_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        update = UpdateRelease.model_validate(data)
                        self._store[update.update_id] = update
                    except Exception:
                        pass  # skip malformed lines — never crash on startup
        except OSError:
            pass

    def _flush(self) -> None:
        """Rewrite the JSONL file with current in-memory state. Raises OSError on failure."""
        if self._persist_path is None:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._persist_path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for update in self._store.values():
                fh.write(update.model_dump_json() + "\n")
        os.replace(tmp, self._persist_path)  # atomic rename on all platforms

    # ── Invariant ──────────────────────────────────────────────────────────────

    def _check_active_invariant(self) -> None:
        """
        Raise MultipleActiveReleasesError if the current in-memory state holds
        more than one active release for any component. Called inside save_batch
        BEFORE the disk flush so an invariant violation aborts the commit.
        """
        active_by_component: dict[str, list[str]] = {}
        for u in self._store.values():
            if u.status == UpdateStatus.active:
                active_by_component.setdefault(u.component_name, []).append(u.update_id)
        violators = {c: ids for c, ids in active_by_component.items() if len(ids) > 1}
        if violators:
            raise MultipleActiveReleasesError(violators)

    # ── CRUD ───────────────────────────────────────────────────────────────────

    def save(self, update: UpdateRelease) -> None:
        """
        Persist a single update record. Fail-closed: if the disk flush OR the
        active-release invariant fails, in-memory state is restored to the last
        durable value and the appropriate exception is raised so callers never
        see a false success.
        """
        with self._rw_lock:
            old = self._store.get(update.update_id)
            self._store[update.update_id] = update
            try:
                self._check_active_invariant()
            except MultipleActiveReleasesError:
                if old is not None:
                    self._store[update.update_id] = old
                else:
                    self._store.pop(update.update_id, None)
                raise
            try:
                self._flush()
            except OSError as exc:
                if old is not None:
                    self._store[update.update_id] = old
                else:
                    self._store.pop(update.update_id, None)
                raise PersistenceError(
                    f"Failed to flush update {update.update_id!r} to "
                    f"{self._persist_path}: {exc}"
                ) from exc

    def save_batch(self, updates: list[UpdateRelease]) -> None:
        """
        Atomically persist multiple update records in a single flush.

        Order of operations:
          1. Snapshot every record being changed (for rollback).
          2. Apply all records in memory.
          3. Check the at-most-one-active-per-component invariant. If violated,
             restore every record to its prior durable value and raise
             MultipleActiveReleasesError — no record from the batch is visible.
          4. Flush to disk. If the flush fails, restore every record and raise
             PersistenceError. Again, no partial commit is ever visible.
        """
        if not updates:
            return
        with self._rw_lock:
            snapshots: dict[str, UpdateRelease | None] = {
                u.update_id: self._store.get(u.update_id) for u in updates
            }
            for u in updates:
                self._store[u.update_id] = u

            try:
                self._check_active_invariant()
            except MultipleActiveReleasesError:
                for u in updates:
                    old = snapshots[u.update_id]
                    if old is not None:
                        self._store[u.update_id] = old
                    else:
                        self._store.pop(u.update_id, None)
                raise

            try:
                self._flush()
            except OSError as exc:
                for u in updates:
                    old = snapshots[u.update_id]
                    if old is not None:
                        self._store[u.update_id] = old
                    else:
                        self._store.pop(u.update_id, None)
                raise PersistenceError(
                    f"Batch save of {[u.update_id for u in updates]!r} failed — "
                    f"all changes rolled back: {exc}"
                ) from exc

    def get(self, update_id: str) -> Optional[UpdateRelease]:
        with self._rw_lock:
            return self._store.get(update_id)

    def list_all(self) -> list[UpdateRelease]:
        with self._rw_lock:
            return list(self._store.values())

    def list_by_status(self, status: UpdateStatus) -> list[UpdateRelease]:
        with self._rw_lock:
            return [u for u in self._store.values() if u.status == status]

    def list_by_component(self, component_name: str) -> list[UpdateRelease]:
        with self._rw_lock:
            return [u for u in self._store.values() if u.component_name == component_name]

    def delete(self, update_id: str) -> bool:
        with self._rw_lock:
            if update_id in self._store:
                del self._store[update_id]
                self._flush()
                return True
        return False

    # ── Component-level activation lock ────────────────────────────────────────

    def acquire_component(self, component_name: str) -> bool:
        """
        Acquire the activation lock for ``component_name``.

        Returns True if acquired; False if another caller already holds it.
        Different components may be acquired concurrently; the same component
        serialises strictly. Callers MUST release in a finally block.
        """
        with self._component_lock:
            if component_name in self._held_components:
                return False
            self._held_components.add(component_name)
            return True

    def release_component(self, component_name: str) -> None:
        """Release the component-level activation lock. Idempotent — safe in finally."""
        with self._component_lock:
            self._held_components.discard(component_name)

    def is_component_locked(self, component_name: str) -> bool:
        with self._component_lock:
            return component_name in self._held_components

    def __len__(self) -> int:
        with self._rw_lock:
            return len(self._store)
