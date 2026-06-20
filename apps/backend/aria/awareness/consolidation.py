"""
Work-History Consolidation (V3.6) — deterministic, source-linked.

Inspects ARIA's own prior work (goals, tasks, execution steps, agent assignments,
quality failures, escalations, skill gaps) and consolidates it into a governed
work-memory graph: source-linked nodes, typed dependency edges, and reusable
LESSONS. A single weak signal produces at most a low-confidence node (never a
high-confidence lesson). It invents no business facts — nodes/lessons describe
PATTERNS (counts, what was blocked, what to verify), never metric values. It never
creates or activates a skill — improvement routing (V3.5) is a separate, governed
step in the service.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from aria.awareness.models import (
    ConsolidationResult,
    LessonApprovalStatus,
    NodeStatus,
    NodeType,
    RelationType,
    WorkLesson,
    WorkMemoryEdge,
    WorkMemoryNode,
)

# A pattern must repeat at least this many times to yield a high-confidence lesson.
MIN_REPEAT = 2


def _now() -> datetime:
    return datetime.now(UTC)


def _conf(count: int) -> float:
    return round(min(0.5 + 0.2 * (count - 1), 0.95), 2) if count >= 1 else 0.4


class WorkHistoryConsolidator:
    """Builds the work-memory graph for a goal and persists it via the store."""

    def __init__(self, store, goal_store, *, skill_store=None) -> None:
        self._store = store
        self._goals = goal_store
        self._skills = skill_store

    def consolidate(self, goal_id: str, *, actor: str = "aria") -> ConsolidationResult:
        goal = self._goals.get_goal(goal_id)
        if goal is None:
            return ConsolidationResult(goal_id=goal_id)
        ws = [goal.workspace_id] if goal.workspace_id else []
        nodes: list[WorkMemoryNode] = []
        edges: list[WorkMemoryEdge] = []
        lessons: list[WorkLesson] = []

        # 1) The goal itself, as a goal_pattern node.
        goal_node = self._node(NodeType.goal_pattern, f"Goal: {goal.title}",
                               f"Goal '{goal.title}' worked under governance.", [goal_id],
                               goal_ids=[goal_id], workspace_ids=ws, confidence=0.6)
        nodes.append(self._store.create_node(goal_node, actor=actor))

        assignments = self._goals.get_agent_assignments(goal_id)
        steps = self._goals.get_execution_steps(goal_id)

        # 2) Repeated missing-evidence pattern (agents + execution steps).
        ev_refs = [a.assignment_id for a in assignments if a.failure_reason == "blocked_for_evidence"]
        ev_refs += [s.step_id for s in steps
                    if s.outcome.value in ("blocked_for_evidence", "blocked_for_clarification")]
        if ev_refs:
            count = len(ev_refs)
            ev_node = self._node(
                NodeType.evidence_pattern, "Repeated missing-evidence blocks",
                f"Work repeatedly blocked on missing evidence/context ({count} occurrence(s)).",
                ev_refs, goal_ids=[goal_id], workspace_ids=ws, confidence=_conf(count),
                evidence_refs=list(goal.missing_context),
            )
            ev_node = self._store.create_node(ev_node, actor=actor)
            nodes.append(ev_node)
            edges.append(self._store.create_edge(self._edge(
                goal_node.node_id, ev_node.node_id, RelationType.requires_evidence, ev_refs,
                _conf(count)), actor=actor))
            if count >= MIN_REPEAT:
                lessons.append(self._evidence_lesson(goal, ev_node, count, actor=actor))

        # 3) Repeated quality-failure pattern.
        qf = [a.assignment_id for a in assignments
              if a.failure_reason == "blocked_for_quality_review"]
        if qf:
            count = len(qf)
            q_node = self._node(
                NodeType.quality_pattern, "Repeated agent quality failures",
                f"{count} agent output(s) failed quality review.", qf, goal_ids=[goal_id],
                workspace_ids=ws, confidence=_conf(count),
                agent_ids=[a.agent_id for a in assignments if a.failure_reason == "blocked_for_quality_review"],
            )
            q_node = self._store.create_node(q_node, actor=actor)
            nodes.append(q_node)
            edges.append(self._store.create_edge(self._edge(
                q_node.node_id, goal_node.node_id, RelationType.blocked_by, qf, _conf(count)),
                actor=actor))
            if count >= MIN_REPEAT:
                lessons.append(self._store.create_lesson(WorkLesson(
                    lesson_id=f"lesson-{uuid.uuid4().hex}",
                    title="Harden agent outputs against quality failures",
                    lesson="Outputs in this domain repeatedly failed quality review; require "
                           "evidence-backed findings, schema validation, and no forbidden actions.",
                    applies_to=[goal.scope], source_node_ids=[q_node.node_id], source_refs=qf,
                    required_evidence=["agent output schema", "evidence references"],
                    confidence=_conf(count),
                    recommended_use="Apply as a quality checklist before accepting agent output.",
                    approval_status=LessonApprovalStatus.pending, status=NodeStatus.active,
                    created_at=_now(), updated_at=_now(),
                ), actor=actor, workspace_id=goal.workspace_id))

        # 4) Skill-gap patterns (links memory ↔ the V3.5 skill record).
        if self._skills is not None:
            try:
                gaps = [g for g in self._skills.list_gaps() if goal_id in g.affected_goals]
            except Exception:  # pragma: no cover - defensive
                gaps = []
            for g in gaps[:5]:
                s_node = self._node(
                    NodeType.skill_pattern, f"Skill gap: {g.repeated_pattern}",
                    g.description, [g.gap_id], goal_ids=[goal_id], workspace_ids=ws,
                    skill_ids=[g.gap_id], confidence=g.confidence)
                s_node = self._store.create_node(s_node, actor=actor)
                nodes.append(s_node)
                edges.append(self._store.create_edge(self._edge(
                    goal_node.node_id, s_node.node_id, RelationType.produced_skill_gap, [g.gap_id],
                    g.confidence), actor=actor))

        self._store.emit_consolidated(
            goal_id, outcome=f"nodes={len(nodes)};edges={len(edges)};lessons={len(lessons)}",
            actor=actor, workspace_id=goal.workspace_id)
        return ConsolidationResult(goal_id=goal_id, nodes=nodes, edges=edges, lessons=lessons)

    # ── Builders ──────────────────────────────────────────────────────────────

    def _evidence_lesson(self, goal, ev_node, count, *, actor) -> WorkLesson:
        # The checklist is the goal's own clarifying questions + missing context —
        # what to VERIFY (never asserting any value).
        checklist = list(goal.clarifying_questions) + [
            m for m in goal.missing_context if m not in goal.clarifying_questions]
        return self._store.create_lesson(WorkLesson(
            lesson_id=f"lesson-{uuid.uuid4().hex}",
            title=f"Verify context before working: {goal.title}",
            lesson="Before this kind of work, verify the required context/evidence up front to "
                   "avoid repeated mid-task blocks:\n- " + "\n- ".join(checklist or ["required evidence"]),
            applies_to=[goal.scope], source_node_ids=[ev_node.node_id],
            source_refs=ev_node.source_refs, required_evidence=checklist or ["required evidence"],
            confidence=_conf(count),
            recommended_use="Use as a pre-flight checklist when planning similar goals.",
            approval_status=LessonApprovalStatus.pending, status=NodeStatus.active,
            created_at=_now(), updated_at=_now(),
        ), actor=actor, workspace_id=goal.workspace_id)

    @staticmethod
    def _node(node_type, title, summary, source_refs, *, goal_ids=None, task_ids=None,
              agent_ids=None, skill_ids=None, workspace_ids=None, evidence_refs=None,
              memory_refs=None, confidence=0.5) -> WorkMemoryNode:
        now = _now()
        return WorkMemoryNode(
            node_id=f"node-{uuid.uuid4().hex}", node_type=node_type, title=title, summary=summary,
            source_refs=list(source_refs), goal_ids=goal_ids or [], task_ids=task_ids or [],
            agent_ids=agent_ids or [], skill_ids=skill_ids or [], workspace_ids=workspace_ids or [],
            evidence_refs=evidence_refs or [], memory_refs=memory_refs or [], confidence=confidence,
            status=NodeStatus.active, created_at=now, updated_at=now,
        )

    @staticmethod
    def _edge(from_id, to_id, relation, source_refs, confidence) -> WorkMemoryEdge:
        return WorkMemoryEdge(
            edge_id=f"edge-{uuid.uuid4().hex}", from_node_id=from_id, to_node_id=to_id,
            relation_type=relation, source_refs=list(source_refs), confidence=confidence,
            created_at=_now(),
        )
