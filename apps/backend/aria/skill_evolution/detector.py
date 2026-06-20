"""
Skill Gap Detector (V3.5) — deterministic, evidence-disciplined.

Inspects the V3.1–V3.4 record (tasks, execution steps, agent assignments, quality
failures, escalations) for REPEATED capability gaps. A single weak signal is never
enough — a gap requires at least ``MIN_REPEAT`` occurrences of the same pattern.
Output is a list of typed ``SkillGap`` PROPOSALS only; it never hallucinates a
business fact and never creates skill code.
"""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime

from aria.goals.models import AgentStatus
from aria.goals.store import GoalStore
from aria.skill_evolution.models import GapSourceType, SkillGap

# A pattern must repeat at least this many times to count as a (high-confidence) gap.
MIN_REPEAT = 2


def _now() -> datetime:
    return datetime.now(UTC)


def _confidence(count: int) -> float:
    return min(0.5 + 0.2 * (count - 1), 0.95)


class SkillGapDetector:
    """Deterministic gap detection over a goal's persisted record."""

    def __init__(self, goal_store: GoalStore) -> None:
        self._goals = goal_store

    def detect(self, goal_id: str) -> list[SkillGap]:
        goal = self._goals.get_goal(goal_id)
        if goal is None:
            return []
        gaps: list[SkillGap] = []
        assignments = self._goals.get_agent_assignments(goal_id)
        briefs = {b.agent_id: b for b in self._goals.get_agent_briefs(goal_id)}

        # 1) Repeated missing-evidence across agents — a recurring need ARIA cannot
        #    yet satisfy with a dedicated capability.
        ev_blocked = [a.assignment_id for a in assignments
                      if a.failure_reason == "blocked_for_evidence"]
        if len(ev_blocked) >= MIN_REPEAT:
            roles = {briefs[a.agent_id].role for a in assignments
                     if a.failure_reason == "blocked_for_evidence" and a.agent_id in briefs}
            gaps.append(self._gap(
                GapSourceType.repeated_missing_evidence, ev_blocked, goal_id,
                f"{len(ev_blocked)} specialist agents were blocked on missing evidence "
                f"({', '.join(sorted(roles)) or 'multiple roles'}) — an evidence-gathering skill "
                "would reduce repeated blockers.",
                "repeated_missing_evidence:agents", len(ev_blocked),
            ))

        # 2) Repeated blocker by the SAME specialist role (a role blocked >= MIN_REPEAT
        #    times implies a missing dedicated capability for that role).
        by_role: Counter[str] = Counter()
        role_refs: dict[str, list[str]] = defaultdict(list)
        for a in assignments:
            if a.status is AgentStatus.blocked:
                b = briefs.get(a.agent_id)
                role = b.role if b else "general"
                by_role[role] += 1
                role_refs[role].append(a.assignment_id)
        for role, count in by_role.items():
            if count >= MIN_REPEAT:
                gaps.append(self._gap(
                    GapSourceType.repeated_blocker, role_refs[role], goal_id,
                    f"the '{role}' role was blocked {count} times — a dedicated {role} skill is needed.",
                    f"repeated_blocker:{role}", count, target=role,
                ))

        # 3) Repeated quality failures.
        qf = [a.assignment_id for a in assignments
              if a.failure_reason == "blocked_for_quality_review"]
        if len(qf) >= MIN_REPEAT:
            gaps.append(self._gap(
                GapSourceType.repeated_quality_failure, qf, goal_id,
                f"{len(qf)} agent outputs failed quality review — a hardened skill is needed.",
                "repeated_quality_failure", len(qf),
            ))

        # 4) Repeated missing-evidence execution blockers (V3.2 work steps).
        steps = self._goals.get_execution_steps(goal_id)
        ev_steps = [s.step_id for s in steps
                    if s.outcome.value in ("blocked_for_evidence", "blocked_for_clarification")]
        if len(ev_steps) >= MIN_REPEAT:
            gaps.append(self._gap(
                GapSourceType.repeated_missing_evidence, ev_steps, goal_id,
                f"{len(ev_steps)} steps blocked on missing evidence/context — an evidence-"
                "gathering skill is needed.",
                "repeated_missing_evidence", len(ev_steps),
            ))

        # 5) Repeated escalations of the same reason class.
        escs = self._goals.list_escalations(goal_id)
        by_reason: dict[str, list[str]] = defaultdict(list)
        for e in escs:
            key = (e.reason or "")[:32]
            by_reason[key].append(e.escalation_id)
        for key, ids in by_reason.items():
            if len(ids) >= MIN_REPEAT:
                gaps.append(self._gap(
                    GapSourceType.repeated_escalation, ids, goal_id,
                    f"{len(ids)} escalations of the same class — a governance/automation skill "
                    "may reduce them.",
                    f"repeated_escalation:{key}", len(ids),
                ))
        return gaps

    def _gap(self, source_type, source_refs, goal_id, description, pattern, count, *, target=""):
        return SkillGap(
            gap_id=f"gap-{uuid.uuid4().hex}", source_type=source_type,
            source_refs=list(source_refs), description=description, repeated_pattern=pattern,
            affected_goals=[goal_id], affected_tasks=[], evidence_refs=[],
            confidence=_confidence(count), risk_level="low", created_at=_now(),
        )
