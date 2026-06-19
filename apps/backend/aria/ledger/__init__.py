"""
AI Work Ledger v2 — Week 29 Priority 1

The Work Ledger v2 is the source of truth for ROI, dataset export, model
lifecycle, future subagent traces, and the Human-like Work Intelligence
Layer (see CLAUDE.md § 28). It is a discriminated-typed, idempotent,
concurrency-safe JSONL ledger with explicit redaction at the metadata
boundary.

Public surface
--------------
- ``LedgerEvent``           — discriminated union of all 15 event types
- ``LedgerEventType``       — enum tag for each event type
- ``LedgerWriter``          — concurrency-safe append + event_id idempotency
- ``LedgerReader``          — unified reader (v2 + legacy task + legacy evolution)
- ``LedgerMetrics``         — ROI metric helpers with documented semantics
- ``sanitize_metadata``     — redaction boundary for metadata dicts
- Typed exceptions: ``MalformedLedgerRecord``, ``LedgerPersistenceError``,
                    ``RedactionViolation``

Legacy compatibility
--------------------
Existing ``work_ledger.jsonl`` and ``evolution_events.jsonl`` files are
preserved byte-for-byte. The unified reader exposes them through the same
typed surface tagged with their compatibility source.
"""
from aria.ledger.events import (
    ActionTaken,
    ActorType,
    ApprovalRequested,
    Approved,
    ArtifactCreated,
    ConversationStarted,
    CorrectionRecorded,
    CostRecorded,
    Failed,
    LedgerEvent,
    LedgerEventType,
    LegacyEvolutionRecord,
    LegacyTaskRecord,
    MemoryApplied,
    MemoryDeleted,
    MemoryProposed,
    MemoryRecalled,
    MemoryRolledBack,
    MemorySuperseded,
    MessageReceived,
    ModelLifecycleEvent,
    ModelUsed,
    OutcomeRecorded,
    Rejected,
    Responded,
    Routed,
    SkillInvoked,
    TaskCreated,
    WorkflowInvoked,
    WorkspaceCreated,
    WorkspaceUpdated,
    ReadOnlyConnectorInvoked,
    PilotReportCreated,
    DraftActionCreated,
    GoalCreated,
    ProblemStatementGenerated,
    RoadmapCreated,
    TaskBoardCreated,
    TaskStatusUpdated,
    GoalProgressReported,
    WorkStepStarted,
    WorkStepCompleted,
    WorkStepBlocked,
    ClarificationRequested,
    ClarificationAnswered,
    EvidenceProvided,
    ProgressReportCreated,
    DeliverableTracked,
    AgentWorkforcePlanned,
    AgentAssignmentCreated,
    AgentAssignmentStarted,
    AgentAssignmentCompleted,
    AgentAssignmentBlocked,
    AgentAssignmentCancelled,
    AgentResultMerged,
    AgentSupervisionPlanned,
    AgentSupervisionStarted,
    AgentSupervisionCompleted,
    AgentSupervisionBlocked,
    AgentQualityCheckFailed,
    AgentEscalationRequired,
    AgentBudgetBlocked,
    AgentDependencyBlocked,
)
from aria.ledger.exceptions import (
    LedgerPersistenceError,
    MalformedLedgerRecord,
    RedactionViolation,
)
from aria.ledger.metrics import LedgerMetrics
from aria.ledger.privacy import REDACTED, sanitize_metadata
from aria.ledger.reader import LedgerReader, LedgerSource
from aria.ledger.writer import LedgerWriter, TerminalOutcomeConflict

__all__ = [
    # Events
    "LedgerEvent",
    "LedgerEventType",
    "ActorType",
    "TaskCreated",
    "Routed",
    "SkillInvoked",
    "ArtifactCreated",
    "ApprovalRequested",
    "Approved",
    "Rejected",
    "ActionTaken",
    "Failed",
    "Responded",
    "OutcomeRecorded",
    "CorrectionRecorded",
    "ModelUsed",
    "CostRecorded",
    "ModelLifecycleEvent",
    # Week 32 — conversation + domain-memory events
    "ConversationStarted",
    "MessageReceived",
    "WorkflowInvoked",
    "MemoryProposed",
    "MemoryApplied",
    "MemoryRecalled",
    "MemorySuperseded",
    "MemoryDeleted",
    "MemoryRolledBack",
    "WorkspaceCreated",
    "WorkspaceUpdated",
    "ReadOnlyConnectorInvoked",
    "PilotReportCreated",
    "DraftActionCreated",
    # V3.1 — goal ownership / planning events
    "GoalCreated",
    "ProblemStatementGenerated",
    "RoadmapCreated",
    "TaskBoardCreated",
    "TaskStatusUpdated",
    "GoalProgressReported",
    # V3.2 — work-execution loop events
    "WorkStepStarted",
    "WorkStepCompleted",
    "WorkStepBlocked",
    "ClarificationRequested",
    "ClarificationAnswered",
    "EvidenceProvided",
    "ProgressReportCreated",
    "DeliverableTracked",
    # V3.3 — dynamic agent workforce (dry-run) events
    "AgentWorkforcePlanned",
    "AgentAssignmentCreated",
    "AgentAssignmentStarted",
    "AgentAssignmentCompleted",
    "AgentAssignmentBlocked",
    "AgentAssignmentCancelled",
    "AgentResultMerged",
    # V3.4 — agent supervisor + governance events
    "AgentSupervisionPlanned",
    "AgentSupervisionStarted",
    "AgentSupervisionCompleted",
    "AgentSupervisionBlocked",
    "AgentQualityCheckFailed",
    "AgentEscalationRequired",
    "AgentBudgetBlocked",
    "AgentDependencyBlocked",
    # Legacy adapters
    "LegacyTaskRecord",
    "LegacyEvolutionRecord",
    # Core machinery
    "LedgerWriter",
    "LedgerReader",
    "LedgerMetrics",
    "LedgerSource",
    "sanitize_metadata",
    "REDACTED",
    # Exceptions
    "MalformedLedgerRecord",
    "LedgerPersistenceError",
    "RedactionViolation",
    "TerminalOutcomeConflict",
]
