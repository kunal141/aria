"""
Typed Work Ledger v2 events.

All ledger writes go through one of the 15 typed event classes below. The
classes share a common envelope (``LedgerEventBase``) and add their own
required + optional fields. The ``LedgerEvent`` discriminated union is the
single type the writer/reader exchange — Pydantic v2 routes by the
``event_type`` literal so event-specific required fields are validated
per type, not against one permissive model.

Event taxonomy (15 types)
-------------------------
Lifecycle .................. task_created, routed, skill_invoked,
                              artifact_created, responded, failed
Governance ................. approval_requested, approved, rejected,
                              action_taken
Learning ................... outcome_recorded, correction_recorded
Model/cost ................. model_used, cost_recorded
Model lifecycle ............ model_lifecycle (Week 29 Priority 4 — registry
                              register/evaluate/approve/activate/rollback)

Legacy adapters
---------------
``LegacyTaskRecord`` and ``LegacyEvolutionRecord`` are typed views over
the pre-v2 JSONL files (``work_ledger.jsonl`` written by ``log_task``;
``evolution_events.jsonl`` written by ``log_evolution_event``). They are
NOT written by the v2 writer — they only appear in reads from the unified
``LedgerReader``.

Money + time
------------
- ``estimated_cost`` uses ``Decimal`` to avoid binary-float ambiguity.
- All timestamps are timezone-aware UTC ``datetime`` instances; the writer
  serialises to ISO-8601 strings on disk and the reader rehydrates them.
- ``event_id`` defaults to a UUID4 if not provided; callers MAY supply a
  deterministic key for idempotent retries (see ``writer.LedgerWriter``).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aria.ledger.privacy import (
    contains_credential_pattern,
    redact_freetext,
    sanitize_metadata,
)

# Structural correlation keys consumed by downstream systems (joins,
# traces, dedup). These MUST NOT carry credentials — credentials would
# leak into every consumer that touches the ID. Silently mutating them
# is also wrong (would corrupt joins), so the validator REJECTS rather
# than redacts. ``actor`` is NOT on this list — it's a free-text label,
# not a correlation key, and remains in ``_FREETEXT_FIELDS`` for
# redaction.
_STRUCTURAL_IDENTIFIERS: tuple[str, ...] = (
    "event_id",
    "task_id",
    "correlation_id",
    "parent_task_id",
    "workflow_id",
)

# Identifier fields that must be non-empty AND non-whitespace. Broader
# than structural — also covers ``actor`` (whitespace-only actor is
# meaningless even after redaction).
_NON_BLANK_FIELDS: tuple[str, ...] = (
    "event_id",
    "task_id",
    "correlation_id",
    "parent_task_id",
    "workflow_id",
    "actor",
)


# String fields on the envelope whose values are persisted free text and
# therefore may carry leaked credentials. The base-class validator pipes
# each of these through ``redact_freetext`` so a secret embedded inside
# ``error``, ``outcome``, ``actor`` etc. is masked before disk.
#
# Subclass-specific free-text fields (``routing_reason`` on ``Routed``)
# are also listed here. Because the base-class ``mode="before"``
# validator runs on the raw dict for any subclass, an entry that doesn't
# exist on a particular event type is simply ignored — but when it IS
# present (only on ``Routed``) it gets sanitised.
_FREETEXT_FIELDS: frozenset[str] = frozenset({
    "actor",
    "skill_name",
    "agent_role",
    "model_name",
    "model_version",
    "component_name",
    "component_version",
    "artifact_id",
    "approval_id",
    "status",
    "outcome",
    "error",
    "routing_reason",   # subclass-specific (Routed)
})


# ── Enums ──────────────────────────────────────────────────────────────────────


class LedgerEventType(str, Enum):
    task_created        = "task_created"
    routed              = "routed"
    skill_invoked       = "skill_invoked"
    artifact_created    = "artifact_created"
    approval_requested  = "approval_requested"
    approved            = "approved"
    rejected            = "rejected"
    action_taken        = "action_taken"
    failed              = "failed"
    responded           = "responded"
    outcome_recorded    = "outcome_recorded"
    correction_recorded = "correction_recorded"
    model_used          = "model_used"
    cost_recorded       = "cost_recorded"
    model_lifecycle     = "model_lifecycle"
    # ── Week 32: V2 conversation + domain-memory events ───────────────────────
    # Genuinely new concepts (conversation + SQLite domain memory). Approval
    # decisions reuse approval_requested / approved / rejected above; these
    # record conversation flow and memory-store state transitions. Memory-
    # specific identifiers (session_id, scope, memory_id, memory_version,
    # proposal_id, execution_mode) ride in the sanitised ``metadata`` dict.
    conversation_started = "conversation_started"
    message_received     = "message_received"
    workflow_invoked     = "workflow_invoked"
    memory_proposed      = "memory_proposed"
    memory_applied       = "memory_applied"
    memory_recalled      = "memory_recalled"
    memory_superseded    = "memory_superseded"
    memory_deleted       = "memory_deleted"
    memory_rolled_back   = "memory_rolled_back"
    # ── Week 33: persistent workspace events ──────────────────────────────────
    # Genuinely new concepts. The decision audit reuses approval_requested /
    # approved / rejected (Week 32) and conversation flow reuses
    # conversation_started / message_received / workflow_invoked — so no
    # api/approval event types are added. Workspace identifiers ride in metadata.
    workspace_created    = "workspace_created"
    workspace_updated    = "workspace_updated"
    # ── Week 34: read-only pilots (PR / CI-CD / Analytics) ────────────────────
    # Genuinely new concepts. Drafts are data artifacts only (no external write).
    read_only_connector_invoked = "read_only_connector_invoked"
    pilot_report_created        = "pilot_report_created"
    draft_action_created        = "draft_action_created"
    # ── V3.1: goal ownership / planning events ────────────────────────────────
    # Genuinely new concepts (goal intake → roadmap → task board → progress).
    # Planning only — NO execution, NO external write. Goal/roadmap/task
    # identifiers ride in the sanitised ``metadata`` dict, so existing
    # readers/metrics keep working and forward-compat is preserved.
    goal_created                 = "goal_created"
    problem_statement_generated  = "problem_statement_generated"
    roadmap_created              = "roadmap_created"
    task_board_created           = "task_board_created"
    task_status_updated          = "task_status_updated"
    goal_progress_reported       = "goal_progress_reported"
    # ── V3.2: governed work-execution loop events ─────────────────────────────
    # Planning/control execution only — a "work step" updates a task's planning
    # status and produces a planning artifact; it executes no tool and writes
    # nothing externally. Identifiers ride in the sanitised ``metadata`` dict.
    work_step_started            = "work_step_started"
    work_step_completed          = "work_step_completed"
    work_step_blocked            = "work_step_blocked"
    clarification_requested      = "clarification_requested"
    clarification_answered       = "clarification_answered"
    evidence_provided            = "evidence_provided"
    progress_report_created      = "progress_report_created"
    deliverable_tracked          = "deliverable_tracked"
    # Legacy compatibility tags (not emitted by the v2 writer; only appear
    # via the unified reader when adapting older JSONL files).
    legacy_task         = "legacy_task"
    legacy_evolution    = "legacy_evolution"


class ActorType(str, Enum):
    human    = "human"
    aria     = "aria"
    subagent = "subagent"
    system   = "system"
    tool     = "tool"


class ActionTier(str, Enum):
    T1 = "T1"   # Read
    T2 = "T2"   # Recommend
    T3 = "T3"   # Draft
    T4 = "T4"   # Execute-with-approval
    T5 = "T5"   # Autonomous


class RiskLevel(str, Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_event_id() -> str:
    return f"evt-{uuid.uuid4()}"


# ── Common envelope ────────────────────────────────────────────────────────────


class LedgerEventBase(BaseModel):
    """
    Fields shared by every Work Ledger v2 event. Concrete event classes
    declare their own ``event_type`` literal AND any event-specific
    required fields.

    Immutability: ``frozen=True`` — events are append-only records of
    what happened, not state to mutate.
    """
    model_config = ConfigDict(frozen=True)

    event_id:        str = Field(min_length=1)
    event_type:      LedgerEventType
    event_version:   Literal[2] = 2
    timestamp:       datetime
    task_id:         str = Field(min_length=1)
    correlation_id:  str = Field(min_length=1)
    parent_task_id:  str | None = None
    workflow_id:     str | None = None
    actor:           str = Field(min_length=1)
    actor_type:      ActorType
    skill_name:      str | None = None
    agent_role:      str | None = None
    model_name:      str | None = None
    model_version:   str | None = None
    component_name:  str | None = None
    component_version: str | None = None
    artifact_id:     str | None = None
    approval_id:     str | None = None
    action_tier:     ActionTier | None = None
    risk_level:      RiskLevel | None  = None
    status:          str | None = None
    outcome:         str | None = None
    error:           str | None = None
    started_at:      datetime | None = None
    completed_at:    datetime | None = None
    duration_ms:     int | None = None
    token_input:     int | None = None
    token_output:    int | None = None
    estimated_cost:  Decimal | None = None
    metadata:        dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", "started_at", "completed_at")
    @classmethod
    def _require_tzaware(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            raise ValueError(
                "Ledger timestamps must be timezone-aware (UTC). "
                f"Got naive datetime: {v!r}"
            )
        # Normalise everything to UTC so metric math is unambiguous.
        return v.astimezone(UTC)

    @field_validator("token_input", "token_output", "duration_ms")
    @classmethod
    def _nonneg(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError(
                f"Token counts and duration_ms must be non-negative; got {v!r}"
            )
        return v

    @field_validator("estimated_cost")
    @classmethod
    def _nonneg_cost(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError(f"estimated_cost must be non-negative; got {v!r}")
        return v

    @field_validator("metadata")
    @classmethod
    def _redact_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        # Redaction happens at the type boundary so writers cannot "forget"
        # to sanitize. Strict-mode enforcement is the writer's choice.
        return sanitize_metadata(v, strict=False)

    @model_validator(mode="before")
    @classmethod
    def _redact_freetext_fields(cls, data: Any) -> Any:
        """
        Mask credential-shaped substrings in every free-text envelope field
        BEFORE Pydantic finishes validating the model. This catches secrets
        embedded inside ``error``, ``status``, ``outcome``, ``actor``,
        ``skill_name``, etc. — fields that previously bypassed sanitisation
        because they live outside the ``metadata`` dict.

        Note: ``actor`` is listed in BOTH ``_FREETEXT_FIELDS`` and
        ``_STRUCTURAL_IDENTIFIERS``. The structural-identifier validator
        runs first (via ``mode="after"``) and rejects credential-shaped
        actors outright, so the redaction below is defence in depth.
        """
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        for field_name in _FREETEXT_FIELDS:
            if field_name in cleaned:
                cleaned[field_name] = redact_freetext(cleaned[field_name])
        return cleaned

    @model_validator(mode="after")
    def _validate_identifier_integrity(self) -> LedgerEventBase:
        """
        Two checks on identifier-shaped fields:

        1. **Non-blank** (``event_id``, ``task_id``, ``correlation_id``,
           ``parent_task_id``, ``workflow_id``, ``actor``): reject
           whitespace-only values. ``Field(min_length=1)`` only counts
           length; ``"   "`` passes that constraint.

        2. **Credential-shape rejection** (structural identifiers only —
           NOT ``actor``): reject any value containing a credential
           pattern. Correlation keys must not carry secrets, and we
           cannot silently mutate them because downstream consumers
           (joins, traces, dedup) need them stable. ``actor`` stays in
           ``_FREETEXT_FIELDS`` and is redacted instead.
        """
        for field_name in _NON_BLANK_FIELDS:
            value = getattr(self, field_name, None)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                raise ValueError(
                    f"Identifier {field_name!r} must not be whitespace-only."
                )

        for field_name in _STRUCTURAL_IDENTIFIERS:
            value = getattr(self, field_name, None)
            if value is None or not isinstance(value, str):
                continue
            if contains_credential_pattern(value):
                raise ValueError(
                    f"Structural identifier {field_name!r} contains a "
                    "credential-shaped substring; refusing to persist or mutate."
                )
        return self


# ── Concrete event classes ─────────────────────────────────────────────────────


class TaskCreated(LedgerEventBase):
    """A new task entered the system (intake)."""
    event_type:    Literal[LedgerEventType.task_created] = LedgerEventType.task_created


class Routed(LedgerEventBase):
    """Router selected a skill / handler for the task."""
    event_type:     Literal[LedgerEventType.routed] = LedgerEventType.routed
    routing_reason: str

    @field_validator("routing_reason")
    @classmethod
    def _routing_reason_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Routed.routing_reason must not be empty")
        return v


class SkillInvoked(LedgerEventBase):
    """Skill function call started."""
    event_type:  Literal[LedgerEventType.skill_invoked] = LedgerEventType.skill_invoked

    @model_validator(mode="after")
    def _require_skill_name(self) -> SkillInvoked:
        if not self.skill_name:
            raise ValueError("SkillInvoked requires skill_name")
        return self


class ArtifactCreated(LedgerEventBase):
    """A skill produced a typed artifact (PR review card, KPI report, etc.)."""
    event_type:  Literal[LedgerEventType.artifact_created] = LedgerEventType.artifact_created

    @model_validator(mode="after")
    def _require_artifact_id(self) -> ArtifactCreated:
        if not self.artifact_id:
            raise ValueError("ArtifactCreated requires artifact_id")
        return self


class ApprovalRequested(LedgerEventBase):
    """T4/T5 action paused, awaiting human verdict."""
    event_type:  Literal[LedgerEventType.approval_requested] = LedgerEventType.approval_requested

    @model_validator(mode="after")
    def _require_approval_id(self) -> ApprovalRequested:
        if not self.approval_id:
            raise ValueError("ApprovalRequested requires approval_id")
        return self


class Approved(LedgerEventBase):
    """Human approved a pending action."""
    event_type:  Literal[LedgerEventType.approved] = LedgerEventType.approved

    @model_validator(mode="after")
    def _require_approval(self) -> Approved:
        if not self.approval_id:
            raise ValueError("Approved requires approval_id")
        if self.actor_type != ActorType.human:
            raise ValueError(
                "Approved.actor_type must be 'human' — only humans can grant T4/T5 approval"
            )
        return self


class Rejected(LedgerEventBase):
    """Human rejected a pending action."""
    event_type:  Literal[LedgerEventType.rejected] = LedgerEventType.rejected

    @model_validator(mode="after")
    def _require_approval(self) -> Rejected:
        if not self.approval_id:
            raise ValueError("Rejected requires approval_id")
        if self.actor_type != ActorType.human:
            raise ValueError("Rejected.actor_type must be 'human'")
        return self


class ActionTaken(LedgerEventBase):
    """A governed action was executed (after approval if T4+)."""
    event_type:  Literal[LedgerEventType.action_taken] = LedgerEventType.action_taken

    @model_validator(mode="after")
    def _require_tier(self) -> ActionTaken:
        if self.action_tier is None:
            raise ValueError("ActionTaken requires action_tier")
        return self


class Failed(LedgerEventBase):
    """A task failed terminally (error path, no retry)."""
    event_type:  Literal[LedgerEventType.failed] = LedgerEventType.failed

    @model_validator(mode="after")
    def _require_error(self) -> Failed:
        if not self.error:
            raise ValueError("Failed requires non-empty error")
        return self


class Responded(LedgerEventBase):
    """Final response sent to the user. Marks the task as completed."""
    event_type:  Literal[LedgerEventType.responded] = LedgerEventType.responded


class OutcomeRecorded(LedgerEventBase):
    """
    Post-task outcome label captured (was the artifact useful? accepted?
    rejected? rolled-back?). Drives the dataset export and the ROI value.

    ``content_hash`` binds this outcome to the SPECIFIC content it judged.
    It is the canonical SHA-256 (64-char lowercase hex) of the
    (task, skill, input, output, rejected, corrected) tuple that was
    evaluated, recorded at outcome time. The Dataset Export verifier
    requires an SFT candidate's own content hash to equal a *cited*
    ``OutcomeRecorded`` event's ``content_hash`` — so an old ``approved``
    marker, which judged different content (or recorded none), cannot
    authorise newly-invented training content. Optional for backward
    compatibility: pre-binding records carry ``None`` and are therefore
    never eligible to authorise an SFT example (fail closed).
    """
    event_type:   Literal[LedgerEventType.outcome_recorded] = LedgerEventType.outcome_recorded
    content_hash: str | None = None

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError(
                "OutcomeRecorded.content_hash must be a 64-char "
                "lowercase hex SHA-256 digest"
            )
        return v

    @model_validator(mode="after")
    def _require_outcome(self) -> OutcomeRecorded:
        if not self.outcome:
            raise ValueError("OutcomeRecorded requires outcome")
        return self


class CorrectionRecorded(LedgerEventBase):
    """
    A human or downstream skill corrected an ARIA output. Pairs of
    (rejected_output, corrected_output) feed the DPO training set.

    ``content_hash`` binds this event to the SPECIFIC corrected content.
    It is the canonical SHA-256 (64-char lowercase hex) of the
    (task, skill, input, output, rejected, corrected) tuple the correction
    produced, recorded at correction time. The Dataset Export verifier
    requires a DPO candidate's own content hash to equal a *cited*
    ``CorrectionRecorded`` event's ``content_hash`` — so a stray correction
    marker, which records a different content (or none at all), cannot
    authorise newly-invented training content. Optional for backward
    compatibility: pre-binding records carry ``None`` and are therefore
    never eligible to authorise a DPO pair (fail closed).
    """
    event_type:   Literal[LedgerEventType.correction_recorded] = LedgerEventType.correction_recorded
    content_hash: str | None = None

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError(
                "CorrectionRecorded.content_hash must be a 64-char "
                "lowercase hex SHA-256 digest"
            )
        return v

    @model_validator(mode="after")
    def _require_correction(self) -> CorrectionRecorded:
        if self.actor_type not in (ActorType.human, ActorType.subagent):
            raise ValueError(
                "CorrectionRecorded.actor_type must be 'human' or 'subagent'"
            )
        return self


class ModelUsed(LedgerEventBase):
    """A model was invoked (frontier, SLM, fine-tuned, etc.)."""
    event_type:  Literal[LedgerEventType.model_used] = LedgerEventType.model_used

    @model_validator(mode="after")
    def _require_model(self) -> ModelUsed:
        if not self.model_name:
            raise ValueError("ModelUsed requires model_name")
        return self


class CostRecorded(LedgerEventBase):
    """A money cost was incurred (LLM tokens, vLLM compute, third-party API)."""
    event_type:  Literal[LedgerEventType.cost_recorded] = LedgerEventType.cost_recorded

    @model_validator(mode="after")
    def _require_cost(self) -> CostRecorded:
        if self.estimated_cost is None:
            raise ValueError("CostRecorded requires estimated_cost (Decimal)")
        return self


class ModelLifecycleEvent(LedgerEventBase):
    """
    A model lifecycle transition in the Model Lifecycle Registry (Week 29
    Priority 4): register / evaluate / request_approval / approve / reject /
    promote_canary / activate / deprecate / rollback / fail.

    Reuses the envelope's ``model_name`` (registry model_name),
    ``model_version`` (semantic_version), ``approval_id`` (set on the approve
    transition), ``outcome`` (evaluation summary or failure outcome) and
    ``status`` (``ok`` / ``failed`` processing status). Model-specific facts
    are TYPED fields below — not free-form metadata — so they are queryable
    and cannot smuggle secrets:

      - ``production_consumer`` — which skill / component consumes the model
      - ``from_status`` / ``to_status`` — the lifecycle transition
      - ``dataset_id`` / ``dataset_hash`` — training-data provenance

    Per the Week-29 governance rule, NO credentials, raw confidential
    content, or training examples are ever placed on this event.
    """
    event_type:          Literal[LedgerEventType.model_lifecycle] = LedgerEventType.model_lifecycle
    production_consumer: str
    to_status:           str
    from_status:         str | None = None
    dataset_id:          str | None = None
    dataset_hash:        str | None = None

    @field_validator("dataset_hash")
    @classmethod
    def _valid_dataset_hash(cls, v: str | None) -> str | None:
        if v is None:
            return v
        normalised = v.lower()
        if len(normalised) != 64 or not all(c in "0123456789abcdef" for c in normalised):
            raise ValueError(
                "dataset_hash must be a 64-char lowercase SHA-256 hex string."
            )
        return normalised

    @model_validator(mode="after")
    def _require_lifecycle_fields(self) -> ModelLifecycleEvent:
        if not self.model_name:
            raise ValueError("ModelLifecycleEvent requires model_name")
        if not self.model_version:
            raise ValueError("ModelLifecycleEvent requires model_version")
        for field_name in ("production_consumer", "to_status"):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(
                    f"ModelLifecycleEvent requires non-empty {field_name}"
                )
        # Reject (never silently mutate) credential-shaped values in the
        # consumer key and status fields — these are queryable identifiers,
        # not redactable free text.
        for field_name in ("production_consumer", "to_status", "from_status", "dataset_id"):
            value = getattr(self, field_name)
            if isinstance(value, str) and contains_credential_pattern(value):
                raise ValueError(
                    f"ModelLifecycleEvent.{field_name} contains a credential-shaped "
                    "substring; refusing to persist."
                )
        return self


# ── Week 32: V2 conversation + domain-memory events ───────────────────────────
# Minimal typed subclasses (like ModelUsed): the shared envelope already
# validates redaction, identifiers, and timestamps. Memory-specific facts
# (session_id, scope, memory_id, memory_version, proposal_id, execution_mode)
# travel in the sanitised ``metadata`` dict — no envelope field changes, so
# existing readers/metrics keep working and forward-compat is preserved.


class ConversationStarted(LedgerEventBase):
    """A V2 conversation session was opened."""
    event_type: Literal[LedgerEventType.conversation_started] = LedgerEventType.conversation_started


class MessageReceived(LedgerEventBase):
    """A user turn entered the conversation orchestrator."""
    event_type: Literal[LedgerEventType.message_received] = LedgerEventType.message_received


class WorkflowInvoked(LedgerEventBase):
    """The orchestrator handed a turn to the V1 graph boundary (run_workflow)."""
    event_type: Literal[LedgerEventType.workflow_invoked] = LedgerEventType.workflow_invoked


class MemoryProposed(LedgerEventBase):
    """A domain-memory proposal was created (pending human decision)."""
    event_type: Literal[LedgerEventType.memory_proposed] = LedgerEventType.memory_proposed


class MemoryApplied(LedgerEventBase):
    """An approved proposal was written as a new active domain-memory version."""
    event_type: Literal[LedgerEventType.memory_applied] = LedgerEventType.memory_applied


class MemoryRecalled(LedgerEventBase):
    """Approved domain memory was retrieved and cited in an answer."""
    event_type: Literal[LedgerEventType.memory_recalled] = LedgerEventType.memory_recalled


class MemorySuperseded(LedgerEventBase):
    """A prior memory version was superseded by a new approved version (update)."""
    event_type: Literal[LedgerEventType.memory_superseded] = LedgerEventType.memory_superseded


class MemoryDeleted(LedgerEventBase):
    """An active memory version was tombstoned (delete proposal approved)."""
    event_type: Literal[LedgerEventType.memory_deleted] = LedgerEventType.memory_deleted


class MemoryRolledBack(LedgerEventBase):
    """A prior approved memory version was restored as the active version."""
    event_type: Literal[LedgerEventType.memory_rolled_back] = LedgerEventType.memory_rolled_back


class WorkspaceCreated(LedgerEventBase):
    """A persistent task/session workspace was created (Week 33)."""
    event_type: Literal[LedgerEventType.workspace_created] = LedgerEventType.workspace_created


class WorkspaceUpdated(LedgerEventBase):
    """A persistent workspace was updated with new artifacts/citations/outcome."""
    event_type: Literal[LedgerEventType.workspace_updated] = LedgerEventType.workspace_updated


class ReadOnlyConnectorInvoked(LedgerEventBase):
    """A read-only connector (fixture by default) was queried by a pilot (Week 34)."""
    event_type: Literal[LedgerEventType.read_only_connector_invoked] = (
        LedgerEventType.read_only_connector_invoked
    )


class PilotReportCreated(LedgerEventBase):
    """A read-only pilot produced an investigation report artifact."""
    event_type: Literal[LedgerEventType.pilot_report_created] = LedgerEventType.pilot_report_created


class DraftActionCreated(LedgerEventBase):
    """A draft-only action (Jira draft / Teams preview / PR comment draft) was
    created as a data artifact — NOT posted/sent/created in any external system."""
    event_type: Literal[LedgerEventType.draft_action_created] = LedgerEventType.draft_action_created


# ── V3.1: goal ownership / planning events ────────────────────────────────────
# Minimal typed subclasses. Planning only — none of these execute work or write
# externally. Goal/roadmap/task identifiers ride in the sanitised ``metadata`` dict.


class GoalCreated(LedgerEventBase):
    """A goal-intake record was created (a vague request became a structured goal)."""
    event_type: Literal[LedgerEventType.goal_created] = LedgerEventType.goal_created


class ProblemStatementGenerated(LedgerEventBase):
    """A structured problem statement was generated for a goal."""
    event_type: Literal[LedgerEventType.problem_statement_generated] = (
        LedgerEventType.problem_statement_generated
    )


class RoadmapCreated(LedgerEventBase):
    """A roadmap (phases / evidence / deliverables) was created for a goal."""
    event_type: Literal[LedgerEventType.roadmap_created] = LedgerEventType.roadmap_created


class TaskBoardCreated(LedgerEventBase):
    """A planning task board (task list) was created from a roadmap."""
    event_type: Literal[LedgerEventType.task_board_created] = LedgerEventType.task_board_created


class TaskStatusUpdated(LedgerEventBase):
    """A task's planning status changed (planned/in_progress/blocked/awaiting_approval/
    completed/cancelled). Planning state only — no work was executed."""
    event_type: Literal[LedgerEventType.task_status_updated] = LedgerEventType.task_status_updated


class GoalProgressReported(LedgerEventBase):
    """A goal-progress summary was produced (counts + current phase + next action)."""
    event_type: Literal[LedgerEventType.goal_progress_reported] = (
        LedgerEventType.goal_progress_reported
    )


# ── V3.2: governed work-execution loop events ─────────────────────────────────
# Minimal typed subclasses. A "work step" is planning/control only — it moves a
# task's planning status and produces a planning artifact; no tool runs, nothing
# is written externally. Approval-required steps never auto-execute.


class WorkStepStarted(LedgerEventBase):
    """A governed execution step began (a task was selected to be worked)."""
    event_type: Literal[LedgerEventType.work_step_started] = LedgerEventType.work_step_started


class WorkStepCompleted(LedgerEventBase):
    """A governed execution step completed and produced a planning artifact."""
    event_type: Literal[LedgerEventType.work_step_completed] = LedgerEventType.work_step_completed


class WorkStepBlocked(LedgerEventBase):
    """A governed execution step was blocked (clarification / evidence / approval)
    or failed safely — nothing was executed or written."""
    event_type: Literal[LedgerEventType.work_step_blocked] = LedgerEventType.work_step_blocked


class ClarificationRequested(LedgerEventBase):
    """ARIA produced a clarification request because required context was missing."""
    event_type: Literal[LedgerEventType.clarification_requested] = (
        LedgerEventType.clarification_requested
    )


class ClarificationAnswered(LedgerEventBase):
    """A human answered a clarification request (unblocks the execution loop). The
    answer VALUES are not stored on the ledger — only the clarification_id + actor."""
    event_type: Literal[LedgerEventType.clarification_answered] = (
        LedgerEventType.clarification_answered
    )


class EvidenceProvided(LedgerEventBase):
    """A human supplied evidence references (ARIA never fabricates evidence). The
    refs ride in the sanitised metadata; this records who/when, for audit."""
    event_type: Literal[LedgerEventType.evidence_provided] = LedgerEventType.evidence_provided


class ProgressReportCreated(LedgerEventBase):
    """A goal execution-progress report was produced from persisted state."""
    event_type: Literal[LedgerEventType.progress_report_created] = (
        LedgerEventType.progress_report_created
    )


class DeliverableTracked(LedgerEventBase):
    """A planning/progress deliverable reference was recorded for a goal (NOT an
    external write — a tracked artifact only)."""
    event_type: Literal[LedgerEventType.deliverable_tracked] = LedgerEventType.deliverable_tracked


# ── Legacy adapter records ────────────────────────────────────────────────────


class LegacyTaskRecord(BaseModel):
    """
    A record from the pre-v2 ``work_ledger.jsonl`` file written by the
    Week-4 ``log_task`` function. Adapted on read so legacy entries
    surface alongside v2 events through ``LedgerReader``.

    Required fields are intentionally narrow because the legacy schema
    has been stable since Week 4. Records with no ``task_id`` are
    routed to ``MalformedLedgerRecord`` by the reader.
    """
    model_config = ConfigDict(frozen=True)

    event_type:        Literal[LedgerEventType.legacy_task] = LedgerEventType.legacy_task
    task_id:           str
    task_type:         str | None = None
    routing_reason:    str | None = None
    timestamp:         datetime
    error:             str | None = None
    platform_evidence: str | None = None
    week:              int | None = None

    @field_validator("timestamp")
    @classmethod
    def _coerce_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            # Legacy entries stored timezone-aware ISO strings; if any
            # historical naive entry slips through, assume UTC for safety.
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class LegacyEvolutionRecord(BaseModel):
    """
    A record from the pre-v2 ``evolution_events.jsonl`` file written by
    ``log_evolution_event``. The v1 ``EvolutionLedgerEvent`` model is
    re-validated here on read — unknown event_type values land in
    ``MalformedLedgerRecord`` instead.
    """
    model_config = ConfigDict(frozen=True)

    event_type:     Literal[LedgerEventType.legacy_evolution] = LedgerEventType.legacy_evolution
    original_type:  str
    task_id:        str
    proposal_id:    str | None = None
    update_id:      str | None = None
    component_name: str | None = None
    version:        str | None = None
    timestamp:      datetime
    actor:          str | None = None
    outcome:        str | None = None
    detail:         str | None = None

    @field_validator("timestamp")
    @classmethod
    def _coerce_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


# ── Discriminated union ───────────────────────────────────────────────────────


# Pydantic v2 discriminated union: routes by the ``event_type`` literal.
# Concrete classes only — legacy records are returned by the reader
# as their own typed objects (not part of this union) since they are
# never written by the v2 writer.
LedgerEvent = Annotated[
    TaskCreated | Routed | SkillInvoked | ArtifactCreated | ApprovalRequested | Approved | Rejected | ActionTaken | Failed | Responded | OutcomeRecorded | CorrectionRecorded | ModelUsed | CostRecorded | ModelLifecycleEvent | ConversationStarted | MessageReceived | WorkflowInvoked | MemoryProposed | MemoryApplied | MemoryRecalled | MemorySuperseded | MemoryDeleted | MemoryRolledBack | WorkspaceCreated | WorkspaceUpdated | ReadOnlyConnectorInvoked | PilotReportCreated | DraftActionCreated | GoalCreated | ProblemStatementGenerated | RoadmapCreated | TaskBoardCreated | TaskStatusUpdated | GoalProgressReported | WorkStepStarted | WorkStepCompleted | WorkStepBlocked | ClarificationRequested | ClarificationAnswered | EvidenceProvided | ProgressReportCreated | DeliverableTracked,
    Field(discriminator="event_type"),
]


# ── Construction helpers ──────────────────────────────────────────────────────


def make_envelope(
    *,
    task_id: str,
    actor: str,
    actor_type: ActorType,
    correlation_id: str | None = None,
    event_id: str | None = None,
    timestamp: datetime | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """
    Build a base envelope dict that any concrete event class can accept.
    Defaults:
      - ``event_id``       → new UUID4
      - ``correlation_id`` → ``task_id`` if not provided
      - ``timestamp``      → ``datetime.now(timezone.utc)``
    """
    # ``event_id`` and ``correlation_id`` fall back to defaults only when
    # explicitly None. An empty-string input is NOT swallowed — it falls
    # through to the model's ``min_length=1`` validator and is rejected.
    base: dict[str, Any] = {
        "event_id":       _new_event_id() if event_id is None else event_id,
        "timestamp":      timestamp or _utc_now(),
        "task_id":        task_id,
        "correlation_id": task_id if correlation_id is None else correlation_id,
        "actor":          actor,
        "actor_type":     actor_type,
    }
    base.update(extra)
    return base
