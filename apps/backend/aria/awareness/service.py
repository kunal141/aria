"""
Awareness Service (V3.6) — governed orchestrator for work memory + world awareness.

Ties the V3.6 components together behind one typed surface:
  - **Work memory**: consolidate a goal's history into a source-linked graph + lessons.
  - **Inspection / controls**: inspect node provenance, disable/supersede lessons,
    redact node content (audit-preserving) — the user stays in control of memory.
  - **World awareness**: register the allowed FIXTURE sources, ingest + score updates
    (fixture-only, no live network), and produce source-cited advisory briefs.
  - **Improvement routing**: turn a high-signal lesson/node or a relevant world update
    into a V3.5 skill PROPOSAL — and stop. It never approves, evaluates-to-activate,
    or activates anything; V3.5 owns the governed approval/activation gate.

Hard boundaries (V2/V3 preserved):
  - advisory/contextual ONLY — memory cannot approve actions, activate skills, or
    prove current facts without evidence;
  - world knowledge is NOT company truth — low-trust updates cannot change the
    roadmap and high-risk/security advisories ESCALATE to human review (never auto
    routed to an improvement);
  - improvement proposals are created in V3.5's ``proposed`` state and left there;
  - secrets are sanitised out at the store layer (incl. list fields).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.awareness.consolidation import WorkHistoryConsolidator
from aria.awareness.models import (
    ConsolidationResult,
    ImprovementOrigin,
    ImprovementProposal,
    LessonApprovalStatus,
    NodeStatus,
    TrustLevel,
    UpdateStatus,
    WorkLesson,
    WorkMemoryNode,
    WorldSource,
    WorldUpdate,
)
from aria.awareness.store import AwarenessNotFound, AwarenessStore
from aria.awareness import world as world_logic
from aria.ledger import LedgerEventType
from aria.skill_evolution.models import GapSourceType, SkillGap

# An improvement is only worth routing to V3.5 above this relevance/confidence floor.
_ROUTE_THRESHOLD = 0.5


def _now() -> datetime:
    return datetime.now(UTC)


class ImprovementBlocked(ValueError):
    """A source is not eligible to be routed into a V3.5 improvement proposal
    (low trust / high risk / low relevance / redacted) — by governance, not error."""


class AwarenessService:
    def __init__(
        self, store: AwarenessStore, *, goal_store: Any = None, skill_store: Any = None,
        skill_service: Any = None, workspace_store: Any = None,
        execution_mode: str | None = None, actor: str = "aria",
    ) -> None:
        self._store = store
        self._goals = goal_store
        self._skill_store = skill_store
        self._skills = skill_service
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor

    # ── 1–4. Work-memory consolidation ────────────────────────────────────────

    def consolidate_goal(self, goal_id: str, *, actor: str | None = None) -> ConsolidationResult:
        """Inspect ARIA's own prior work on this goal and build the work-memory graph
        (source-linked nodes + typed edges + reusable lessons)."""
        actor = actor or self._actor
        result = WorkHistoryConsolidator(
            self._store, self._goals, skill_store=self._skill_store,
        ).consolidate(goal_id, actor=actor)
        ws_id = self._workspace_for_goal(goal_id)
        refs = [f"work_node:{n.node_id}" for n in result.nodes]
        refs += [f"work_lesson:{l.lesson_id}" for l in result.lessons]
        self._attach_ws(ws_id, refs, "work_memory_consolidated", actor=actor)
        return result

    # ── 5. Inspection ─────────────────────────────────────────────────────────

    def list_nodes(self, *, node_type: str | None = None, status: str | None = None) -> list[WorkMemoryNode]:
        return self._store.list_nodes(node_type=node_type, status=status)

    def get_node(self, node_id: str) -> WorkMemoryNode | None:
        return self._store.get_node(node_id)

    def inspect_node(self, node_id: str) -> dict[str, Any]:
        """Full provenance for a node: the node, its outgoing edges, and the lessons
        that cite it — so the user can see exactly what ARIA learned and from where."""
        node = self._store.get_node(node_id)
        if node is None:
            raise AwarenessNotFound(f"node {node_id!r} not found")
        edges = self._store.list_edges(from_node_id=node_id)
        lessons = [l for l in self._store.list_lessons() if node_id in l.source_node_ids]
        return {
            "node": node.model_dump(mode="json"),
            "edges": [e.model_dump(mode="json") for e in edges],
            "lessons": [l.model_dump(mode="json") for l in lessons],
            "source_refs": list(node.source_refs),
            "boundary_note": "Advisory work-memory only — it cannot approve actions, "
                             "activate skills, or prove current facts without evidence.",
        }

    def list_lessons(self, *, usable_only: bool = False) -> list[WorkLesson]:
        return self._store.list_lessons(usable_only=usable_only)

    def get_lesson(self, lesson_id: str) -> WorkLesson | None:
        return self._store.get_lesson(lesson_id)

    def snapshot(self) -> dict[str, Any]:
        """Export the current memory + awareness state for inspection / portability."""
        return {
            "nodes": [n.model_dump(mode="json") for n in self._store.list_nodes()],
            "lessons": [l.model_dump(mode="json") for l in self._store.list_lessons()],
            "sources": [s.model_dump(mode="json") for s in self._store.list_sources()],
            "updates": [u.model_dump(mode="json") for u in self._store.list_updates()],
            "improvements": [i.model_dump(mode="json") for i in self._store.list_improvements()],
        }

    # ── 6. Disable / redact controls ──────────────────────────────────────────

    def disable_lesson(self, lesson_id: str, *, actor: str | None = None) -> WorkLesson:
        """Turn a lesson OFF so it no longer informs future recommendations. The row
        and its citations remain (audit trail preserved)."""
        actor = actor or self._actor
        return self._store.set_lesson_status(
            lesson_id, approval_status=LessonApprovalStatus.disabled, status=NodeStatus.disabled,
            event=LedgerEventType.work_lesson_disabled, actor=actor,
        )

    def supersede_lesson(self, lesson_id: str, *, actor: str | None = None) -> WorkLesson:
        actor = actor or self._actor
        return self._store.set_lesson_status(
            lesson_id, approval_status=LessonApprovalStatus.superseded, status=NodeStatus.superseded,
            event=LedgerEventType.work_lesson_disabled, actor=actor,
        )

    def redact_node(self, node_id: str, *, actor: str | None = None) -> WorkMemoryNode:
        """Withhold a node's human-readable content (privacy/redaction) while KEEPING
        the audit row + source links — a governed delete, not a silent erase."""
        actor = actor or self._actor
        return self._store.redact_node(node_id, actor=actor)

    # ── 7. World source registry ──────────────────────────────────────────────

    def register_world_sources(self, *, actor: str | None = None) -> list[WorldSource]:
        actor = actor or self._actor
        return world_logic.register_default_sources(self._store, actor=actor)

    def list_world_sources(self) -> list[WorldSource]:
        return self._store.list_sources()

    # ── 8–10. Ingest + relevance scoring ──────────────────────────────────────

    def ingest_world(self, *, actor: str | None = None) -> list[WorldUpdate]:
        """Ensure sources are registered, ingest the FIXTURE updates (no live network),
        then deterministically score each for relevance/risk and persist the verdict."""
        actor = actor or self._actor
        world_logic.register_default_sources(self._store, actor=actor)
        ingested = world_logic.ingest_fixtures(self._store, actor=actor)
        scored: list[WorldUpdate] = []
        for u in ingested:
            relevance, risk, status, recommendation = world_logic.assess(u)
            scored.append(self._store.score_update(
                u.update_id, relevance_score=relevance, risk_level=risk, status=status,
                recommendation=recommendation, actor=actor,
            ))
        return scored

    def list_world_updates(self) -> list[WorldUpdate]:
        return self._store.list_updates()

    # ── 9. Source-cited advisory brief ────────────────────────────────────────

    def world_brief(self) -> dict[str, Any]:
        """A source-cited, advisory-only digest of scored world updates. Each item
        carries its citation and recommendation; nothing here changes ARIA."""
        updates = self._store.list_updates()
        items = []
        for u in updates:
            items.append({
                "update_id": u.update_id, "title": u.title, "summary": u.summary,
                "source_id": u.source_id, "source_url": u.source_url, "citations": list(u.citations),
                "trust_level": u.trust_level.value, "relevance_score": u.relevance_score,
                "risk_level": u.risk_level, "status": u.status.value,
                "recommendation": u.recommendation, "can_change_roadmap": u.can_change_roadmap,
            })
        return {
            "updates": items, "count": len(items),
            "boundary_note": "World knowledge is advisory only and is NOT company truth. "
                             "Low-trust updates cannot change the roadmap; high-risk/security "
                             "advisories escalate to human review.",
        }

    # ── 11. Improvement routing into V3.5 (governed, proposal-only) ────────────

    def propose_improvement_from_update(self, update_id: str, *,
                                        actor: str | None = None) -> ImprovementProposal:
        """Route a RELEVANT, sufficiently-trusted world update to V3.5 as a skill
        PROPOSAL. Refuses low-trust / high-risk / low-relevance / escalated updates."""
        actor = actor or self._actor
        u = self._store.get_update(update_id)
        if u is None:
            raise AwarenessNotFound(f"update {update_id!r} not found")
        if u.status is UpdateStatus.escalated or u.risk_level == "high":
            raise ImprovementBlocked("high-risk/security update escalates to human review — "
                                     "it is not auto-routed to an improvement proposal.")
        if u.trust_level is TrustLevel.low:
            raise ImprovementBlocked("low-trust source cannot change roadmap/skills — advisory only.")
        if u.relevance_score < _ROUTE_THRESHOLD:
            raise ImprovementBlocked(f"relevance {u.relevance_score:.2f} < {_ROUTE_THRESHOLD} — "
                                     "no improvement routed.")
        gap = self._make_gap(
            description=f"World update suggests a capability improvement: {u.title}",
            pattern=f"world_update:{update_id}", source_refs=[update_id, *u.citations],
            affected_goals=[], evidence_refs=list(u.citations), confidence=u.relevance_score,
            risk_level=u.risk_level,
        )
        return self._route(
            origin=ImprovementOrigin.world_update, origin_ref=update_id, gap=gap,
            title=f"Skill improvement from world update: {u.title}",
            description=u.summary, source_refs=[update_id, *u.citations],
            relevance=u.relevance_score, risk=u.risk_level, workspace_id=None, actor=actor,
        )

    def propose_improvement_from_node(self, node_id: str, *,
                                      actor: str | None = None) -> ImprovementProposal:
        """Route a high-signal, active work-memory node to V3.5 as a skill PROPOSAL."""
        actor = actor or self._actor
        node = self._store.get_node(node_id)
        if node is None:
            raise AwarenessNotFound(f"node {node_id!r} not found")
        if node.status is not NodeStatus.active:
            raise ImprovementBlocked(f"node is {node.status.value}; only an active node may route.")
        if node.confidence < _ROUTE_THRESHOLD:
            raise ImprovementBlocked(f"confidence {node.confidence:.2f} < {_ROUTE_THRESHOLD} — "
                                     "too weak a signal to route.")
        gap = self._make_gap(
            description=f"Work-memory pattern suggests a capability: {node.title}",
            pattern=f"work_memory:{node_id}", source_refs=[node_id, *node.source_refs],
            affected_goals=list(node.goal_ids), evidence_refs=list(node.evidence_refs),
            confidence=node.confidence, risk_level="low",
        )
        ws_id = node.workspace_ids[0] if node.workspace_ids else None
        return self._route(
            origin=ImprovementOrigin.work_memory, origin_ref=node_id, gap=gap,
            title=f"Skill improvement from work memory: {node.title}",
            description=node.summary, source_refs=[node_id, *node.source_refs],
            relevance=node.confidence, risk="low", workspace_id=ws_id, actor=actor,
        )

    def list_improvements(self) -> list[ImprovementProposal]:
        return self._store.list_improvements()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _route(self, *, origin: ImprovementOrigin, origin_ref: str, gap: SkillGap,
               title: str, description: str, source_refs: list[str], relevance: float,
               risk: str, workspace_id: str | None, actor: str) -> ImprovementProposal:
        """Persist the gap, ask V3.5 to PROPOSE a skill (and stop — never approve or
        activate), and record a linked, pending improvement proposal."""
        skill_gap_id: str | None = None
        skill_proposal_id: str | None = None
        if self._skill_store is not None and self._skills is not None:
            self._skill_store.create_gap(gap, actor=actor, workspace_id=workspace_id)
            skill_gap_id = gap.gap_id
            # propose_skill yields a PROPOSED proposal — governed approval/activation
            # stays entirely inside V3.5; we deliberately do NOT advance it here.
            proposal = self._skills.propose_skill(gap.gap_id, actor=actor)
            skill_proposal_id = proposal.proposal_id
        imp = ImprovementProposal(
            proposal_id=f"imp-{uuid.uuid4().hex}", origin_type=origin, origin_ref=origin_ref,
            title=title, description=description, source_refs=list(source_refs),
            skill_gap_id=skill_gap_id, skill_proposal_id=skill_proposal_id,
            relevance_score=relevance, risk_level=risk, status="pending", created_at=_now(),
        )
        created = self._store.create_improvement(imp, actor=actor, workspace_id=workspace_id)
        self._attach_ws(workspace_id, [f"improvement:{created.proposal_id}"],
                        "improvement_proposed", actor=actor)
        return created

    @staticmethod
    def _make_gap(*, description: str, pattern: str, source_refs: list[str],
                  affected_goals: list[str], evidence_refs: list[str], confidence: float,
                  risk_level: str) -> SkillGap:
        # Curated improvement opportunities are ``manual_task`` gaps (NOT auto-detected
        # repeated blockers) — they still flow through V3.5's full approval lifecycle.
        return SkillGap(
            gap_id=f"gap-{uuid.uuid4().hex}", source_type=GapSourceType.manual_task,
            source_refs=list(source_refs), description=description, repeated_pattern=pattern,
            affected_goals=list(affected_goals), affected_tasks=[], evidence_refs=list(evidence_refs),
            confidence=min(max(confidence, 0.0), 0.95), risk_level=risk_level, created_at=_now(),
        )

    def _workspace_for_goal(self, goal_id: str | None) -> str | None:
        if not goal_id or self._goals is None:
            return None
        goal = self._goals.get_goal(goal_id)
        return goal.workspace_id if goal else None

    def _attach_ws(self, ws_id: str | None, refs: list[str], status: str, *, actor: str) -> None:
        if self._workspace_store is None or not ws_id or not refs:
            return
        try:
            self._workspace_store.update_workspace(
                ws_id, status=status, add_ledger_refs=list(refs), actor=actor)
        except Exception:  # pragma: no cover - workspace bookkeeping is best-effort
            pass
