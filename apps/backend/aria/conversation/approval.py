"""
Approval Decision Service (Week 33 §6).

A backend service that records human approve/reject decisions on memory proposals
and returns a typed, auditable **decision record**. In Week 33 the only decisions
are memory approve/reject — there are NO external writes, NO connector execution,
NO Jira/Teams/PR actions. Approval is a *decision record*, not an external action
trigger.

The underlying state change + ledger audit (approved/rejected events) are emitted
by the domain-memory store's transactional outbox (so they can never diverge from
state). This service wraps that and adds the richer approval record.

Governance:
  - approval is auditable (links to the proposal + the store's approved/rejected
    ledger events)
  - approval does not execute external actions (memory-only in Week 33)
  - approval cannot bypass evidence gates (memory approval never touches the
    evidence path; evidence gating governs workflow *outputs*, not memory)
  - prompt injection cannot approve — a decision happens only via this explicit
    service call with a real ``proposal_id``, never from conversational text
  - caller metadata (``decided_by`` / ``ARIA_USER_ID``) is attribution only, not
    authentication
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from aria.conversation.orchestrator import ConversationOrchestrator
from aria.memory_v2.models import ChatSession, ProposalStatus
from aria.memory_v2.store import MemoryNotFound, ProposalNotPending


class Decision(str, Enum):
    approve = "approve"
    reject = "reject"


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    approval_id: str
    proposal_id: str | None = None
    action_id: str | None = None
    action_type: str                 # "memory" in Week 33
    target_system: str               # "domain_memory" — internal, never external
    risk_level: str = "low"
    evidence_summary: str | None = None
    decision: Decision
    decided_by: str                  # attribution only, NOT authentication
    decided_at: datetime
    rollback_or_reversal_note: str
    ledger_event_id: str | None = None
    # Outcome fields (memory): the active version after an approve.
    memory_id: str | None = None
    memory_version: int | None = None
    status: str | None = None        # resulting proposal status


class AlreadyDecided(ValueError):
    """A decision was attempted on a proposal that is no longer pending."""

    def __init__(self, proposal_id: str, current_status: str) -> None:
        super().__init__(
            f"proposal {proposal_id!r} is already {current_status}; decisions are not re-applied"
        )
        self.proposal_id = proposal_id
        self.current_status = current_status


class ApprovalService:
    """Records memory approve/reject decisions. No external execution."""

    def __init__(self, orchestrator: ConversationOrchestrator) -> None:
        self._orch = orchestrator

    def decide_memory(
        self, proposal_id: str, decision: Decision | str, *, decided_by: str,
        session_id: str | None = None,
    ) -> ApprovalRecord:
        decision = Decision(decision) if not isinstance(decision, Decision) else decision
        now = datetime.now(UTC)
        approval_id = f"appr-{uuid.uuid4().hex}"

        prop = self._orch._store.get_proposal(proposal_id)
        if prop is None:
            raise MemoryNotFound(f"proposal {proposal_id!r} not found")
        # Synthesise a minimal session context (the orchestrator's decision path
        # only reads ``session_id``). ``decided_by`` is attribution only.
        session = ChatSession(
            session_id=session_id or prop.proposal_id, owner=decided_by, scope=prop.scope,
            created_at=now, updated_at=now,
        )

        try:
            if decision is Decision.approve:
                version = self._orch.approve_memory(
                    proposal_id, approver=decided_by, session=session
                )
                return ApprovalRecord(
                    approval_id=approval_id, proposal_id=proposal_id, action_type="memory",
                    target_system="domain_memory", risk_level="low",
                    evidence_summary="Memory approval records a decision only; no external write.",
                    decision=decision, decided_by=decided_by, decided_at=now,
                    rollback_or_reversal_note=(
                        "Reversible: a later delete proposal tombstones it; rollback restores a "
                        "prior approved version."
                    ),
                    memory_id=version.memory_id, memory_version=version.version, status="approved",
                )
            proposal = self._orch.reject_memory(
                proposal_id, actor=decided_by, session=session
            )
            return ApprovalRecord(
                approval_id=approval_id, proposal_id=proposal_id, action_type="memory",
                target_system="domain_memory", risk_level="low",
                evidence_summary="Rejected memory never becomes retrievable.",
                decision=decision, decided_by=decided_by, decided_at=now,
                rollback_or_reversal_note="Rejected proposals are terminal; re-state the fact to re-propose.",
                status=proposal.status.value,
            )
        except ProposalNotPending as exc:
            # Idempotency / safe failure: surface the current status, do not re-apply.
            current = self._orch._store.get_proposal(proposal_id)  # read-only status peek
            status = current.status.value if current else ProposalStatus.rejected.value
            raise AlreadyDecided(proposal_id, status) from exc
