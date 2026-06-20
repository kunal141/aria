"""
Skill Evolution Service (V3.5) — governed, approval-gated lifecycle.

Drives the sandbox skill lifecycle:

    gap_detected → proposal_created → spec_generated → test_plan_generated →
    sandbox_ready → evaluated → approval_requested → approved/rejected →
    activated/deprecated/rolled_back

Hard boundaries (V2/V3 preserved):
  - NO live production code is created or modified; a "skill" is a proposal + spec +
    test plan + evaluation + a registry STATUS.
  - activation is APPROVAL-GATED and only happens through an explicit decision; an
    UNSAFE skill can never activate, even with admin-looking caller metadata
    (``ARIA_USER_ID`` is attribution only, never authorization).
  - rejected proposals cannot activate; activation is reversible (deprecate/rollback).
  - secrets are sanitised out of every persisted/returned string.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aria.goals.sanitize import sanitize_text
from aria.ledger import LedgerEventType
from aria.skill_evolution.detector import SkillGapDetector
from aria.skill_evolution.generators import (
    SAFE_THRESHOLD,
    evaluate_proposal,
    generate_spec,
    generate_test_plan,
)
from aria.skill_evolution.models import (
    FORBIDDEN_SKILL_TOOLS,
    GapSourceType,
    SkillDecisionRecord,
    SkillEvaluation,
    SkillProposal,
    SkillProposalStatus,
    is_terminal_status,
)
from aria.skill_evolution.store import SkillNotFound, SkillStore

# Read-only tools an evolving skill may request by default.
_DEFAULT_READONLY_TOOLS = ("recall_memory", "read_events", "read_schema", "read_docs")
# Statuses from which an approve decision may legitimately activate (an approval
# state — evaluation always advances to awaiting_approval before a decision).
_APPROVABLE = (SkillProposalStatus.awaiting_approval, SkillProposalStatus.approved)


def _now() -> datetime:
    return datetime.now(UTC)


class SkillEvolutionService:
    def __init__(
        self, store: SkillStore, *, goal_store: Any = None, workspace_store: Any = None,
        execution_mode: str | None = None, actor: str = "aria",
    ) -> None:
        self._store = store
        self._goals = goal_store
        self._workspace_store = workspace_store
        self._execution_mode = execution_mode
        self._actor = actor

    # ── 1. Gap detection ──────────────────────────────────────────────────────

    def detect_gaps(self, goal_id: str, *, actor: str | None = None) -> list:
        actor = actor or self._actor
        if self._goals is None:
            return []
        ws_id = self._workspace_for_goal(goal_id)
        gaps = SkillGapDetector(self._goals).detect(goal_id)
        persisted = [self._store.create_gap(g, actor=actor, workspace_id=ws_id) for g in gaps]
        for g in persisted:
            self._attach_ws(ws_id, f"skill_gap:{g.gap_id}", "skills_gap_detected", actor=actor)
        return persisted

    # ── 2. Proposal ───────────────────────────────────────────────────────────

    def propose_skill(self, gap_id: str, *, actor: str | None = None) -> SkillProposal:
        actor = actor or self._actor
        gap = self._store.get_gap(gap_id)
        if gap is None:
            raise SkillNotFound(f"gap {gap_id!r} not found")
        now = _now()
        name = self._derive_name(gap)
        proposal = SkillProposal(
            proposal_id=f"prop-{uuid.uuid4().hex}", gap_id=gap_id, name=name,
            purpose=sanitize_text(gap.description) or gap.description,
            target_domain=self._derive_domain(gap),
            expected_inputs=list(gap.evidence_refs) or ["evidence ref"],
            expected_outputs=["findings", "evidence citations"],
            required_tools=list(_DEFAULT_READONLY_TOOLS),
            forbidden_tools=list(FORBIDDEN_SKILL_TOOLS),       # write tools forbidden by default
            required_permissions=["read-only"], risk_level=gap.risk_level,
            approval_required=True, status=SkillProposalStatus.proposed,
            created_at=now, updated_at=now,
        )
        ws_id = self._workspace_for_goal(gap.affected_goals[0] if gap.affected_goals else None)
        created = self._store.create_proposal(proposal, actor=actor, workspace_id=ws_id)
        self._attach_ws(ws_id, f"skill_proposal:{created.proposal_id}", "skills_proposed", actor=actor)
        return created

    # ── 3/4. Spec + test plan ─────────────────────────────────────────────────

    def generate_spec(self, proposal_id: str, *, actor: str | None = None):
        actor = actor or self._actor
        proposal = self._require_proposal(proposal_id)
        spec = generate_spec(proposal)
        saved = self._store.save_spec(spec, SkillProposalStatus.spec_generated, actor=actor,
                                     workspace_id=self._ws_for_proposal(proposal))
        self._attach_ws(self._ws_for_proposal(proposal), f"skill_spec:{saved.spec_id}",
                        "skills_spec_generated", actor=actor)
        return saved

    def generate_test_plan(self, proposal_id: str, *, actor: str | None = None):
        actor = actor or self._actor
        proposal = self._require_proposal(proposal_id)
        spec = self._store.get_spec(proposal_id)
        if spec is None:
            raise SkillNotFound(f"no spec for proposal {proposal_id!r}; generate the spec first")
        tp = generate_test_plan(spec)
        saved = self._store.save_test_plan(tp, SkillProposalStatus.sandbox_ready, actor=actor,
                                          workspace_id=self._ws_for_proposal(proposal))
        self._attach_ws(self._ws_for_proposal(proposal), f"skill_test_plan:{saved.test_plan_id}",
                        "skills_test_plan_generated", actor=actor)
        return saved

    # ── 5/6. Evaluate + request approval ──────────────────────────────────────

    def evaluate(self, proposal_id: str, *, actor: str | None = None) -> SkillEvaluation:
        actor = actor or self._actor
        proposal = self._require_proposal(proposal_id)
        spec = self._store.get_spec(proposal_id)
        tp = self._store.get_test_plan(proposal_id)
        if spec is None or tp is None:
            raise SkillNotFound(f"proposal {proposal_id!r} needs a spec + test plan before evaluation")
        ev = evaluate_proposal(proposal, spec, tp)
        ws_id = self._ws_for_proposal(proposal)
        self._store.save_evaluation(ev, SkillProposalStatus.evaluated, actor=actor, workspace_id=ws_id)
        # Route for explicit human approval (no auto-approval).
        self._store.transition(
            proposal_id, SkillProposalStatus.awaiting_approval,
            LedgerEventType.skill_approval_requested, actor=actor, workspace_id=ws_id,
            outcome="approval_requested", recommended_decision=ev.recommended_decision.value,
        )
        self._attach_ws(ws_id, f"skill_evaluation:{ev.evaluation_id}", "skills_evaluated", actor=actor)
        return ev

    # ── 7. Approval-gated activation + rejection ──────────────────────────────

    def decide(self, proposal_id: str, decision: str, *, decided_by: str | None = None,
               actor: str | None = None) -> SkillDecisionRecord:
        actor = actor or self._actor
        decided_by = decided_by or actor
        proposal = self._require_proposal(proposal_id)
        ws_id = self._ws_for_proposal(proposal)
        now = _now()

        # A terminal proposal (rejected/deprecated/rolled_back) accepts NO decision.
        if is_terminal_status(proposal.status):
            return self._refuse(proposal, decided_by,
                                f"proposal is {proposal.status.value}; terminal, no further decision", now)

        if decision == "reject":
            self._store.transition(proposal_id, SkillProposalStatus.rejected,
                                  LedgerEventType.skill_rejected, actor=actor, workspace_id=ws_id,
                                  outcome="rejected")
            self._attach_ws(ws_id, f"skill_decision:{proposal_id}:rejected", "skills_rejected", actor=actor)
            return SkillDecisionRecord(decision="reject", proposal_id=proposal_id,
                                       status=SkillProposalStatus.rejected, activated=False,
                                       decided_by=decided_by, reason="rejected by reviewer", decided_at=now)

        if decision != "approve":
            return self._refuse(proposal, decided_by, "unknown decision", now)

        if proposal.status not in _APPROVABLE:
            return self._refuse(proposal, decided_by, f"not ready for approval (status={proposal.status.value})", now)

        # Activation gate is the EVALUATION SAFETY — never the caller's identity.
        ev = self._store.get_evaluation(proposal_id)
        if ev is None:
            return self._refuse(proposal, decided_by, "no evaluation; cannot approve", now)
        if ev.safety_score < SAFE_THRESHOLD:
            # Unsafe: cannot activate even with admin-looking metadata.
            self._attach_ws(ws_id, f"skill_decision:{proposal_id}:blocked_unsafe", "skills_unsafe", actor=actor)
            return self._refuse(proposal, decided_by,
                                f"unsafe: safety score {ev.safety_score:.2f} < {SAFE_THRESHOLD}", now)

        # Activation goes through the narrow store authority (re-checks approval +
        # safety) — there is no generic transition path to ``activated``.
        activated = self._store.activate_after_approval(
            proposal_id, actor=actor, workspace_id=ws_id,
            recommended_decision=ev.recommended_decision.value,
        )
        self._attach_ws(ws_id, f"skill_decision:{proposal_id}:activated", "skills_activated", actor=actor)
        return SkillDecisionRecord(decision="approve", proposal_id=proposal_id,
                                   status=activated.status, activated=True, decided_by=decided_by,
                                   reason="approved + activated (registry status only)", decided_at=now)

    # ── 8. Rollback / deprecation ─────────────────────────────────────────────

    def rollback(self, proposal_id: str, *, actor: str | None = None) -> SkillProposal:
        actor = actor or self._actor
        proposal = self._require_proposal(proposal_id)
        if proposal.status is not SkillProposalStatus.activated:
            raise SkillNotFound(f"proposal {proposal_id!r} is {proposal.status.value}; only an "
                                "activated skill can be rolled back")
        ws_id = self._ws_for_proposal(proposal)
        rb = self._store.transition(proposal_id, SkillProposalStatus.rolled_back,
                                   LedgerEventType.skill_rolled_back, actor=actor, workspace_id=ws_id,
                                   outcome="rolled_back")
        self._attach_ws(ws_id, f"skill_rollback:{proposal_id}", "skills_rolled_back", actor=actor)
        return rb

    def deprecate(self, proposal_id: str, *, actor: str | None = None) -> SkillProposal:
        actor = actor or self._actor
        proposal = self._require_proposal(proposal_id)
        if proposal.status is not SkillProposalStatus.activated:
            raise SkillNotFound(f"proposal {proposal_id!r} is {proposal.status.value}; only an "
                                "activated skill can be deprecated")
        ws_id = self._ws_for_proposal(proposal)
        dep = self._store.transition(proposal_id, SkillProposalStatus.deprecated,
                                    LedgerEventType.skill_deprecated, actor=actor, workspace_id=ws_id,
                                    outcome="deprecated")
        self._attach_ws(ws_id, f"skill_deprecate:{proposal_id}", "skills_deprecated", actor=actor)
        return dep

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_proposal_bundle(self, proposal_id: str) -> dict[str, Any]:
        p = self._store.get_proposal(proposal_id)
        if p is None:
            raise SkillNotFound(f"proposal {proposal_id!r} not found")
        spec = self._store.get_spec(proposal_id)
        tp = self._store.get_test_plan(proposal_id)
        ev = self._store.get_evaluation(proposal_id)
        return {
            "proposal": p.model_dump(mode="json"),
            "spec": spec.model_dump(mode="json") if spec else None,
            "test_plan": tp.model_dump(mode="json") if tp else None,
            "evaluation": ev.model_dump(mode="json") if ev else None,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _require_proposal(self, proposal_id: str) -> SkillProposal:
        p = self._store.get_proposal(proposal_id)
        if p is None:
            raise SkillNotFound(f"proposal {proposal_id!r} not found")
        return p

    @staticmethod
    def _refuse(proposal, decided_by, reason, now) -> SkillDecisionRecord:
        return SkillDecisionRecord(decision="approve", proposal_id=proposal.proposal_id,
                                   status=proposal.status, activated=False, decided_by=decided_by,
                                   reason=reason, decided_at=now)

    @staticmethod
    def _derive_name(gap) -> str:
        if gap.source_type is GapSourceType.repeated_blocker:
            target = gap.repeated_pattern.split(":", 1)[-1]
            return f"{target} Skill".strip()
        return {
            GapSourceType.repeated_quality_failure: "Output Quality Hardening Skill",
            GapSourceType.repeated_missing_evidence: "Evidence Gathering Skill",
            GapSourceType.repeated_escalation: "Escalation Reduction Skill",
        }.get(gap.source_type, "Capability Skill")

    @staticmethod
    def _derive_domain(gap) -> str:
        return {
            GapSourceType.repeated_blocker: "analytics",
            GapSourceType.repeated_quality_failure: "quality",
            GapSourceType.repeated_missing_evidence: "analytics",
            GapSourceType.repeated_escalation: "governance",
        }.get(gap.source_type, "general")

    def _workspace_for_goal(self, goal_id: str | None) -> str | None:
        if not goal_id or self._goals is None:
            return None
        goal = self._goals.get_goal(goal_id)
        return goal.workspace_id if goal else None

    def _ws_for_proposal(self, proposal: SkillProposal) -> str | None:
        gap = self._store.get_gap(proposal.gap_id)
        if gap and gap.affected_goals:
            return self._workspace_for_goal(gap.affected_goals[0])
        return None

    def _attach_ws(self, ws_id: str | None, ref: str, status: str, *, actor: str) -> None:
        if self._workspace_store is None or not ws_id:
            return
        try:
            self._workspace_store.update_workspace(ws_id, status=status, add_ledger_refs=[ref], actor=actor)
        except Exception:  # pragma: no cover - workspace bookkeeping is best-effort
            pass
