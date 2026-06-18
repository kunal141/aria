"""
Pilot Service (Week 34).

Runs a read-only pilot, writes its report artifact to the session workspace,
records draft actions, and emits the Work Ledger traces — all behind the existing
V2 orchestrator/workspace shell (no parallel agent runner). Read-only and
draft-only throughout.

It is invoked by the conversation orchestrator's governed ``run_workflow`` path
(see ``ConversationOrchestrator._do_run_workflow``) for pilot task types, so it
never bypasses the Week 32/33 governance path and never executes tools directly.

Audit/state consistency (P1 fix): ALL pilot ledger events flow through the
workspace store's **transactional outbox**. ``read_only_connector_invoked`` is
emitted (durably) before the workspace; ``pilot_report_created`` and
``draft_action_created`` are enqueued in the SAME transaction as the artifact
reference (``update_workspace(extra_events=...)``). So the report artifact and its
pilot ledger trace commit atomically and survive a ledger outage (queued +
recoverable), in causal order:

    read_only_connector_invoked → workspace_created/updated (artifact)
    → pilot_report_created → draft_action_created
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from aria.connectors import get_connector, resolve_connector_mode
from aria.conversation.extraction import derive_scope
from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.models import ChatSession
from aria.pilots.analytics import run_analytics
from aria.pilots.ci_cd import run_ci_cd
from aria.pilots.models import PilotKind, PilotReport
from aria.pilots.pr_review import run_pr_review

# Map the orchestrator's task types to pilots. ``analytics_qa`` is the
# events-data investigation the orchestrator routes via ``_looks_like_analytics``;
# generic ``kpi`` prompts (no events table) are intentionally NOT mapped — they
# keep flowing through the governed V1 graph (evidence gate) unchanged.
_TASK_TYPE_TO_PILOT: dict[str, PilotKind] = {
    "pr_review": PilotKind.pr_review,
    "ci_cd": PilotKind.ci_cd,
    "analytics_qa": PilotKind.analytics,
}

# Tables the analytics pilot has fixtures for (used to pick the queried table).
_KNOWN_TABLES = ("story_events",)


class PilotRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    pilot: PilotKind
    report: PilotReport
    workspace_id: str | None = None
    summary: str
    connector_mode: str


class PilotService:
    def __init__(
        self, store: Any, workspace_store: Any, *, writer: Any = None,
        execution_mode: str = "offline_mock",
    ) -> None:
        self._store = store
        self._workspace_store = workspace_store
        self._writer = writer
        self._execution_mode = execution_mode

    @staticmethod
    def pilot_for_task_type(task_type: str | None) -> PilotKind | None:
        return _TASK_TYPE_TO_PILOT.get(task_type or "")

    def maybe_run(self, task_type: str | None, text: str, *, session: ChatSession):
        kind = self.pilot_for_task_type(task_type)
        if kind is None:
            return None
        return self.run(kind, text, session=session)

    def run(self, kind: PilotKind, text: str, *, session: ChatSession) -> PilotRunResult:
        connector = get_connector()
        mode = resolve_connector_mode().value
        base = dict(
            actor="aria", actor_type=ActorType.aria, session_id=session.session_id,
            scope=session.scope, execution_mode=self._execution_mode,
        )

        # 1) read-only connector invoked — durable + ordered, BEFORE the workspace.
        self._workspace_store.emit_event(
            LedgerEventType.read_only_connector_invoked, task_id=f"pilot-{kind.value}",
            connector=mode, pilot=kind.value, outcome="read", **base,
        )

        # 2) run the pilot (read-only).
        if kind is PilotKind.pr_review:
            report = run_pr_review(connector)
        elif kind is PilotKind.ci_cd:
            report = run_ci_cd(connector)
        else:
            report = run_analytics(connector, table=self._pick_table(text),
                                  recall=self._recall_fn(session))

        # 3) workspace artifact + atomic pilot audit (one transaction).
        workspace_id = self._write_workspace(session, report, kind, base)

        return PilotRunResult(
            pilot=kind, report=report, workspace_id=workspace_id,
            summary=report.summary, connector_mode=mode,
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _pick_table(text: str) -> str:
        low = (text or "").lower()
        for t in _KNOWN_TABLES:
            if t in low:
                return t
        return _KNOWN_TABLES[0]

    def _recall_fn(self, session: ChatSession):
        def recall(table: str, field: str):
            scope = derive_scope(table, field)
            hit = self._store.recall(
                scope=scope, table=table, field=field,
                session_id=session.session_id, actor="aria",
            )
            if hit is None:
                return None
            version, citation = hit
            mapping = (version.approved_value or {}).get("mapping", {})
            return mapping, {
                "memory_id": citation.memory_id, "version": citation.version,
                "retrieval_reason": citation.retrieval_reason,
            }
        return recall

    def _write_workspace(
        self, session: ChatSession, report: PilotReport, kind: PilotKind, base: dict,
    ) -> str:
        ws = self._workspace_store.get_by_session(session.session_id)
        if ws is None:
            ws = self._workspace_store.create_workspace(
                owner=session.owner, scope=session.scope, session_id=session.session_id,
                correlation_id=session.session_id,
            )
        ref = self._workspace_store.write_artifact(
            ws.workspace_id, f"{report.pilot.value}_report.md", report.render(),
        )
        # Pilot audit events, enqueued atomically with the artifact ref + in order.
        extra_events: list[tuple[LedgerEventType, dict]] = [(
            LedgerEventType.pilot_report_created,
            dict(task_id=ws.workspace_id, workspace_id=ws.workspace_id, pilot=kind.value,
                 outcome="created", **base),
        )]
        for d in report.drafts:
            extra_events.append((
                LedgerEventType.draft_action_created,
                dict(task_id=d.draft_id, workspace_id=ws.workspace_id, pilot=kind.value,
                     draft=d.kind.value, outcome="draft_only", **base),
            ))
        self._workspace_store.update_workspace(
            ws.workspace_id, status=f"pilot:{report.pilot.value}",
            add_artifact_refs=[ref], add_citations=report.memory_citations,
            add_approval_refs=[f"draft:{d.draft_id}" for d in report.drafts],
            final_outcome=report.summary, extra_events=extra_events,
        )
        return ws.workspace_id
