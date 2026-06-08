"""
Update Store — Week 28

UpdateStore Protocol + InMemoryUpdateStore.

Thread-safety note: V1 is single-process; concurrency protection is via a
per-operation lock for activation to prevent double-activation. General store
operations are not thread-safe (add a threading.Lock in V2 if needed).
"""
from __future__ import annotations

import threading
from typing import Optional, Protocol, runtime_checkable

from aria.evolution.update_manager.models import UpdateRelease, UpdateStatus


@runtime_checkable
class UpdateStore(Protocol):
    def save(self, update: UpdateRelease) -> None: ...
    def get(self, update_id: str) -> Optional[UpdateRelease]: ...
    def list_all(self) -> list[UpdateRelease]: ...
    def list_by_status(self, status: UpdateStatus) -> list[UpdateRelease]: ...
    def list_by_component(self, component_name: str) -> list[UpdateRelease]: ...
    def delete(self, update_id: str) -> bool: ...


class InMemoryUpdateStore:
    """In-memory UpdateStore with an activation lock for concurrency safety."""

    def __init__(self) -> None:
        self._store: dict[str, UpdateRelease] = {}
        self._activation_lock   = threading.Lock()
        self._activating: set[str] = set()   # update_ids currently being activated

    # ── CRUD ───────────────────────────────────────────────────────────────────

    def save(self, update: UpdateRelease) -> None:
        self._store[update.update_id] = update

    def get(self, update_id: str) -> Optional[UpdateRelease]:
        return self._store.get(update_id)

    def list_all(self) -> list[UpdateRelease]:
        return list(self._store.values())

    def list_by_status(self, status: UpdateStatus) -> list[UpdateRelease]:
        return [u for u in self._store.values() if u.status == status]

    def list_by_component(self, component_name: str) -> list[UpdateRelease]:
        return [u for u in self._store.values() if u.component_name == component_name]

    def delete(self, update_id: str) -> bool:
        if update_id in self._store:
            del self._store[update_id]
            return True
        return False

    # ── Activation lock ────────────────────────────────────────────────────────

    def begin_activation(self, update_id: str) -> bool:
        """
        Acquire the activation lock for update_id.
        Returns True if acquired; False if already activating.
        """
        with self._activation_lock:
            if update_id in self._activating:
                return False
            self._activating.add(update_id)
            return True

    def end_activation(self, update_id: str) -> None:
        """Release the activation lock (call in finally block)."""
        with self._activation_lock:
            self._activating.discard(update_id)

    def is_activating(self, update_id: str) -> bool:
        with self._activation_lock:
            return update_id in self._activating

    def __len__(self) -> int:
        return len(self._store)
