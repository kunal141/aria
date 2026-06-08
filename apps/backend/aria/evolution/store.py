"""
Evolution Proposal Store — Week 27

ProposalStore Protocol + InMemoryProposalStore.
Persistence layer for evolution proposals; V1 uses in-memory dict.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from aria.evolution.models import EvolutionProposal, ProposalStatus


@runtime_checkable
class ProposalStore(Protocol):
    def save(self, proposal: EvolutionProposal) -> None: ...
    def get(self, proposal_id: str) -> Optional[EvolutionProposal]: ...
    def list_all(self) -> list[EvolutionProposal]: ...
    def list_by_status(self, status: ProposalStatus) -> list[EvolutionProposal]: ...
    def delete(self, proposal_id: str) -> bool: ...


class InMemoryProposalStore:
    """Thread-unsafe in-memory store — sufficient for V1 single-process use."""

    def __init__(self) -> None:
        self._store: dict[str, EvolutionProposal] = {}

    def save(self, proposal: EvolutionProposal) -> None:
        self._store[proposal.proposal_id] = proposal

    def get(self, proposal_id: str) -> Optional[EvolutionProposal]:
        return self._store.get(proposal_id)

    def list_all(self) -> list[EvolutionProposal]:
        return list(self._store.values())

    def list_by_status(self, status: ProposalStatus) -> list[EvolutionProposal]:
        return [p for p in self._store.values() if p.status == status]

    def delete(self, proposal_id: str) -> bool:
        if proposal_id in self._store:
            del self._store[proposal_id]
            return True
        return False

    def __len__(self) -> int:
        return len(self._store)
