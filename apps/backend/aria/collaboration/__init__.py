"""
aria.collaboration — V3.7 Team Collaboration Layer.

A governed, DRAFT-ONLY communication layer: ARIA assembles a read-only collaboration
context from goal/task/agent/memory state and renders manager/team updates,
stakeholder questions, handoff notes, blocker notes, summaries, decision memos, risk
escalations, and approval requests as cited DRAFT artifacts.

ARIA can draft, summarize, ask, escalate, and hand off. ARIA cannot send, post,
comment, email, or mutate any external system. Approval marks a draft approved as an
artifact only — there is no external send path.

A SEPARATE package — importing it never drags in V1 LLM skills, and importing a V1
skill never loads this layer.
"""
from aria.collaboration.models import (
    DRAFT_ONLY_BOUNDARY,
    ApprovalRequestDraft,
    ApprovalRequestStatus,
    Channel,
    CollaborationContext,
    CollaborationDraft,
    DraftStatus,
    DraftType,
)
from aria.collaboration.service import CollaborationService
from aria.collaboration.store import (
    CollaborationIntegrityError,
    CollaborationNotFound,
    CollaborationSecurityError,
    CollaborationStore,
)

__all__ = [
    "CollaborationService",
    "CollaborationStore",
    "CollaborationNotFound",
    "CollaborationSecurityError",
    "CollaborationIntegrityError",
    "CollaborationDraft",
    "CollaborationContext",
    "ApprovalRequestDraft",
    "DraftType",
    "Channel",
    "DraftStatus",
    "ApprovalRequestStatus",
    "DRAFT_ONLY_BOUNDARY",
]
