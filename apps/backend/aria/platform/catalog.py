"""
Platform Intelligence — Service Catalog

Provides a typed registry of platform services with:
- CatalogStore Protocol  (swap out backing store without changing callers)
- InMemoryCatalogStore   (V1 default; persistence interface ready)
- ServiceCatalog         (business logic: lookup, list, dependency graph, impact analysis)

Impact analysis walks the REVERSE-dependency graph via BFS.
Example: analytics-pipeline fails → recommendation-service + feed-ranking-service affected.
"""
from __future__ import annotations

from collections import deque
from typing import Protocol, runtime_checkable

from .models import ServiceEntry, ServiceStatus


# ── Persistence protocol ──────────────────────────────────────────────────────

@runtime_checkable
class CatalogStore(Protocol):
    """Persistence interface. V1 uses InMemoryCatalogStore; swap in DB at V2."""

    def save(self, entry: ServiceEntry) -> None: ...
    def get(self, service_id: str) -> ServiceEntry | None: ...
    def list_all(self) -> list[ServiceEntry]: ...
    def delete(self, service_id: str) -> bool: ...


# ── In-memory implementation ──────────────────────────────────────────────────

class InMemoryCatalogStore:
    """Dict-backed CatalogStore. Thread-safe for single-process use only."""

    def __init__(self) -> None:
        self._store: dict[str, ServiceEntry] = {}

    def save(self, entry: ServiceEntry) -> None:
        self._store[entry.service_id] = entry

    def get(self, service_id: str) -> ServiceEntry | None:
        return self._store.get(service_id)

    def list_all(self) -> list[ServiceEntry]:
        return list(self._store.values())

    def delete(self, service_id: str) -> bool:
        if service_id in self._store:
            del self._store[service_id]
            return True
        return False


# ── Service Catalog ───────────────────────────────────────────────────────────

class ServiceCatalog:
    """
    Business logic layer over a CatalogStore.

    Dependency graph is derived lazily from registered ServiceEntry.dependencies
    — no separate adjacency structure to keep in sync.

    Impact analysis: given a failing service, return all services that
    transitively depend on it (BFS over the reverse-dependency graph).
    """

    def __init__(self, store: CatalogStore | None = None) -> None:
        self._store: CatalogStore = store if store is not None else InMemoryCatalogStore()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def register(self, entry: ServiceEntry) -> None:
        self._store.save(entry)

    def get(self, service_id: str) -> ServiceEntry | None:
        return self._store.get(service_id)

    def require(self, service_id: str) -> ServiceEntry:
        """Like get() but raises KeyError when missing — use in assertion-critical paths."""
        entry = self._store.get(service_id)
        if entry is None:
            raise KeyError(f"Service not registered: {service_id!r}")
        return entry

    def list_services(self) -> list[ServiceEntry]:
        return self._store.list_all()

    def update_status(self, service_id: str, status: ServiceStatus) -> None:
        entry = self.require(service_id)
        self._store.save(entry.model_copy(update={"status": status}))

    # ── Dependency graph ──────────────────────────────────────────────────────

    def _reverse_dependency_graph(self) -> dict[str, list[str]]:
        """
        Build reverse-adjacency map: service_id → list of service_ids that
        DEPEND ON it (i.e., would be affected if it goes down).
        """
        rdeps: dict[str, list[str]] = {}
        for entry in self._store.list_all():
            rdeps.setdefault(entry.service_id, [])
            for dep in entry.dependencies:
                rdeps.setdefault(dep, []).append(entry.service_id)
        return rdeps

    def direct_dependents(self, service_id: str) -> list[str]:
        """Services that directly depend on service_id."""
        return self._reverse_dependency_graph().get(service_id, [])

    def impact_analysis(self, service_id: str) -> list[str]:
        """
        All services transitively affected if service_id fails, ordered BFS
        (closest dependents first). Does NOT include service_id itself.

        Handles cycles defensively (visited set).
        """
        rdeps = self._reverse_dependency_graph()
        visited: set[str] = set()
        queue: deque[str] = deque([service_id])
        affected: list[str] = []

        while queue:
            current = queue.popleft()
            for dependent in rdeps.get(current, []):
                if dependent not in visited:
                    visited.add(dependent)
                    affected.append(dependent)
                    queue.append(dependent)

        return affected
