"""
Update Store — Week 28

UpdateStore Protocol + InMemoryUpdateStore.

Persistence: InMemoryUpdateStore accepts an optional `persist_path`. When set,
every save() rewrites the file (JSON Lines, one UpdateRelease per line). On init
the file is loaded if it exists. This gives update records restart-survival
without a database dependency in V1.

Thread-safety note: general CRUD operations are protected by a single RW lock.
The activation set has its own lock so promotion/rollback never block reads.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
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
    """
    In-memory UpdateStore with optional file persistence and activation lock.

    Parameters
    ----------
    persist_path : Path or str, optional
        If given, each save() rewrites this JSONL file so records survive
        a process restart. Default: ``None`` (no persistence — safe for tests).
        Production callers should pass an explicit path, e.g.:
          InMemoryUpdateStore(persist_path=Path("update_releases.jsonl"))
    """

    def __init__(self, persist_path: Optional[Path | str] = None) -> None:
        self._store: dict[str, UpdateRelease] = {}
        self._rw_lock         = threading.Lock()
        self._activation_lock = threading.Lock()
        self._activating: set[str] = set()
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
        """Rewrite the JSONL file with current in-memory state."""
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                for update in self._store.values():
                    fh.write(update.model_dump_json() + "\n")
            os.replace(tmp, self._persist_path)  # atomic rename on all platforms
        except OSError:
            pass  # persistence is best-effort; never block the caller

    # ── CRUD ───────────────────────────────────────────────────────────────────

    def save(self, update: UpdateRelease) -> None:
        with self._rw_lock:
            self._store[update.update_id] = update
            self._flush()

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
        with self._rw_lock:
            return len(self._store)
