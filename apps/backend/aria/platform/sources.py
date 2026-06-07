"""
Platform Intelligence — Source Repository

Phase-1 authorization happens HERE, at retrieval time.
A caller with insufficient clearance never receives a restricted KnowledgeSource —
not even as an "access denied" object carrying the source's title or content.

Protocol + InMemory implementation follow the same persistence-interface pattern
as ServiceCatalog so a DB-backed store can be swapped in at V2 without changing callers.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    KnowledgeSource,
    SensitivityLevel,
    SourceTypeName,
    caller_can_access,
)


# ── Persistence protocol ──────────────────────────────────────────────────────

@runtime_checkable
class SourceStore(Protocol):
    """Persistence interface for raw KnowledgeSource storage (no auth logic here)."""

    def save(self, source: KnowledgeSource) -> None: ...
    def get(self, source_id: str) -> KnowledgeSource | None: ...
    def list_all(self) -> list[KnowledgeSource]: ...
    def delete(self, source_id: str) -> bool: ...


class InMemorySourceStore:
    """Dict-backed SourceStore."""

    def __init__(self) -> None:
        self._store: dict[str, KnowledgeSource] = {}

    def save(self, source: KnowledgeSource) -> None:
        self._store[source.source_id] = source

    def get(self, source_id: str) -> KnowledgeSource | None:
        return self._store.get(source_id)

    def list_all(self) -> list[KnowledgeSource]:
        return list(self._store.values())

    def delete(self, source_id: str) -> bool:
        if source_id in self._store:
            del self._store[source_id]
            return True
        return False


# ── Source Repository (Phase-1 auth at retrieval) ─────────────────────────────

class SourceRepository:
    """
    Retrieval layer with Phase-1 authorization baked in.

    INVARIANT: no method on this class ever returns a KnowledgeSource whose
    sensitivity exceeds the caller's level. Callers with insufficient clearance
    receive an empty list / None — never a filtered object carrying restricted data.
    """

    def __init__(self, store: SourceStore | None = None) -> None:
        self._store: SourceStore = store if store is not None else InMemorySourceStore()

    # ── Ingestion (no auth required — admin path) ─────────────────────────────

    def ingest(self, source: KnowledgeSource) -> None:
        self._store.save(source)

    def remove(self, source_id: str) -> bool:
        return self._store.delete(source_id)

    # ── Retrieval (Phase-1 auth enforced) ─────────────────────────────────────

    def get(
        self,
        source_id: str,
        caller_level: SensitivityLevel,
    ) -> KnowledgeSource | None:
        """
        Returns the source only if caller's level >= source's sensitivity.
        Returns None when the source doesn't exist OR when access is denied —
        callers cannot distinguish the two cases, preventing oracle attacks.
        """
        source = self._store.get(source_id)
        if source is None:
            return None
        if not caller_can_access(caller_level, source.sensitivity):
            return None
        return source

    def query(
        self,
        caller_level: SensitivityLevel,
        *,
        service_ids: list[str] | None = None,
        source_types: list[SourceTypeName] | None = None,
        keywords: list[str] | None = None,
    ) -> list[KnowledgeSource]:
        """
        Retrieve authorized sources matching the given filters.

        All three filters are optional AND-conditions:
        - service_ids: include only sources for these services
        - source_types: include only these source types
        - keywords: include sources whose title or content contains ANY keyword

        Phase-1 authorization is applied first — restricted sources are excluded
        before any filter is evaluated.
        """
        results: list[KnowledgeSource] = []

        for source in self._store.list_all():
            # Phase-1 auth: drop unauthorized sources unconditionally
            if not caller_can_access(caller_level, source.sensitivity):
                continue

            # Service filter
            if service_ids is not None and source.service_id not in service_ids:
                continue

            # Source-type filter
            if source_types is not None and source.source_type not in source_types:
                continue

            # Keyword filter (case-insensitive, any match)
            if keywords:
                text = (source.title + " " + source.content).lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue

            results.append(source)

        return results
