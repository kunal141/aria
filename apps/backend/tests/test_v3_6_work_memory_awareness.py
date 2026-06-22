"""
V3.6 — Work Memory Graph + World Awareness Engine tests.

Covers the governed, fixture-first, advisory memory/awareness layer:
  - work-history consolidation into a source-linked graph (nodes + typed edges +
    reusable lessons), with the no-orphan / no-weak-signal-lesson discipline;
  - memory inspection + disable/redact controls (audit-preserving);
  - world-awareness source registry, FIXTURE-ONLY ingestion (no live network),
    deterministic relevance scoring, security escalation, low-trust roadmap guard;
  - improvement routing to V3.5 as a PROPOSAL only (never approve/activate), with
    governance blocks for low-trust / high-risk / low-relevance / redacted sources;
  - workspace integration, Work Ledger events, API surface, secrets/confinement/
    restart-safety/package-isolation safety.

Advisory/contextual ONLY — nothing here approves actions, activates skills, browses
the live web, or proves facts without evidence.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aria.awareness import (
    AwarenessIntegrityError,
    AwarenessSecurityError,
    AwarenessService,
    AwarenessStore,
    ImprovementBlocked,
    WorkHistoryConsolidator,
    assess,
    score_relevance,
)
from aria.awareness.fixtures import FIXTURE_SOURCES, FIXTURE_UPDATES
from aria.awareness.models import (
    ImprovementOrigin,
    ImprovementProposal,
    LessonApprovalStatus,
    NodeStatus,
    NodeType,
    RelationType,
    TrustLevel,
    UpdateStatus,
    WorkLesson,
    WorkMemoryEdge,
    WorkMemoryNode,
    WorldSource,
    WorldSourceType,
    WorldUpdate,
)
from aria.goals import (
    AgentSupervisorService,
    AgentWorkforceService,
    GoalService,
    GoalStore,
)
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir
from aria.memory_v2.workspace import WorkspaceStore
from aria.skill_evolution import SkillEvolutionService, SkillProposalStatus, SkillStore

_CTR = "Our notification CTR is dropping. Own this."


# ── Fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v36_ledger.jsonl")


@pytest.fixture
def env(writer: LedgerWriter):
    mode = "offline_mock"
    gstore = GoalStore(writer=writer, execution_mode=mode)
    sstore = SkillStore(writer=writer, execution_mode=mode)
    astore = AwarenessStore(writer=writer, execution_mode=mode)
    ws = WorkspaceStore(writer=writer, execution_mode=mode)
    gsvc = GoalService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    aw = AgentWorkforceService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    sup = AgentSupervisorService(gstore, workspace_store=ws, execution_mode=mode, actor="human:test")
    skills = SkillEvolutionService(sstore, goal_store=gstore, workspace_store=ws,
                                   execution_mode=mode, actor="human:test")
    awareness = AwarenessService(astore, goal_store=gstore, skill_store=sstore, skill_service=skills,
                                 workspace_store=ws, execution_mode=mode, actor="human:test")
    return gstore, sstore, astore, ws, gsvc, aw, sup, skills, awareness


def _blocked_goal(gsvc, aw, sup):
    """A goal whose supervised run blocks several agents on missing evidence."""
    plan = gsvc.own_goal(_CTR, scope="analytics.notifications")
    aw.plan(plan.goal.goal_id)
    sup.run(plan.goal.goal_id)
    return plan


def _event_types(writer: LedgerWriter) -> list[str]:
    if not writer.path.exists():
        return []
    return [json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()]


def _now() -> datetime:
    return datetime.now(UTC)


def _node(summary: str, *, confidence: float = 0.6, source_refs=None, status=NodeStatus.active,
          node_type=NodeType.evidence_pattern) -> WorkMemoryNode:
    now = _now()
    return WorkMemoryNode(
        node_id=f"node-{uuid.uuid4().hex}", node_type=node_type, title="t", summary=summary,
        source_refs=(["ref-1"] if source_refs is None else source_refs), confidence=confidence,
        status=status, created_at=now, updated_at=now,
    )


def _lesson(lesson_text: str = "a reusable lesson", *, source_node_ids=None, source_refs=None,
            required_evidence=None) -> WorkLesson:
    now = _now()
    return WorkLesson(
        lesson_id=f"lesson-{uuid.uuid4().hex}", title="t", lesson=lesson_text, applies_to=["analytics"],
        source_node_ids=(["node-x"] if source_node_ids is None else source_node_ids),
        source_refs=(["ref-x"] if source_refs is None else source_refs),
        required_evidence=(["evidence-x"] if required_evidence is None else required_evidence),
        created_at=now, updated_at=now,
    )


def _edge(from_id: str = "node-a", to_id: str = "node-b", *, source_refs=None) -> WorkMemoryEdge:
    return WorkMemoryEdge(
        edge_id=f"edge-{uuid.uuid4().hex}", from_node_id=from_id, to_node_id=to_id,
        relation_type=RelationType.requires_evidence,
        source_refs=(["ref-1"] if source_refs is None else source_refs),
        confidence=0.6, created_at=_now(),
    )


def _source(source_id=None) -> WorldSource:
    return WorldSource(
        source_id=source_id or f"src-{uuid.uuid4().hex}", name="n",
        source_type=WorldSourceType.official_doc, url="fixture://x", topic_tags=["governance"],
        created_at=_now(),
    )


def _update(update_id=None, source_id: str = "src-1", *, citations=None) -> WorldUpdate:
    return WorldUpdate(
        update_id=update_id or f"upd-{uuid.uuid4().hex}", source_id=source_id, title="t",
        summary="s", captured_at=_now(), source_url="fixture://x",
        citations=(["fixture://x#1"] if citations is None else citations), topic_tags=["governance"],
    )


def _improvement(*, origin_ref: str = "node-1", source_refs=None) -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id=f"imp-{uuid.uuid4().hex}", origin_type=ImprovementOrigin.work_memory,
        origin_ref=origin_ref, title="t", description="d",
        source_refs=(["node-1"] if source_refs is None else source_refs),
        relevance_score=0.6, risk_level="low", created_at=_now(),
    )


def _blob(writer: LedgerWriter, subdir: str = "awareness") -> str:
    """The combined ledger + SQLite/WAL bytes — used to assert a secret never lands."""
    blob = writer.path.read_text(encoding="utf-8") if writer.path.exists() else ""
    for dbf in (aria_data_dir() / subdir).glob("store.sqlite*"):
        blob += dbf.read_bytes().decode("utf-8", "ignore")
    return blob


# ── Minimal deterministic goal-store stub (for threshold tests) ───────────────


class _FakeOutcome:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeGoal:
    def __init__(self, gid: str) -> None:
        self.goal_id = gid
        self.title = "Investigate CTR"
        self.workspace_id = None
        self.scope = "analytics"
        self.clarifying_questions = ["What is the CTR baseline?"]
        self.missing_context = ["CTR baseline window"]


class _FakeAssignment:
    def __init__(self, aid: str, reason: str | None) -> None:
        self.assignment_id = aid
        self.failure_reason = reason
        self.agent_id = "ag-" + aid


class _FakeStep:
    def __init__(self, sid: str, outcome: str) -> None:
        self.step_id = sid
        self.outcome = _FakeOutcome(outcome)


class _FakeGoalStore:
    def __init__(self, goal: _FakeGoal, assignments: list, steps: list) -> None:
        self._goal, self._a, self._s = goal, assignments, steps

    def get_goal(self, gid: str):
        return self._goal if self._goal.goal_id == gid else None

    def get_agent_assignments(self, gid: str):
        return self._a

    def get_execution_steps(self, gid: str):
        return self._s


# ── 1. Consolidation / work-memory graph ──────────────────────────────────────


class TestConsolidation:
    def test_builds_source_linked_graph_and_lessons(self, env):
        *_, gsvc, aw, sup, skills, awareness = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        result = awareness.consolidate_goal(gid)
        assert result.nodes                                  # at least the goal node
        # every node cites its source records
        assert all(n.source_refs for n in result.nodes)
        # at least one evidence pattern + a cited lesson
        assert any(n.node_type is NodeType.evidence_pattern for n in result.nodes)
        assert result.lessons
        assert result.edges

    def test_lessons_are_never_orphan(self, env):
        *_, gsvc, aw, sup, skills, awareness = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        result = awareness.consolidate_goal(gid)
        for l in result.lessons:
            assert l.source_node_ids, "lesson must cite source nodes"
            assert l.required_evidence, "lesson must carry an evidence checklist"
            assert l.approval_status is LessonApprovalStatus.pending   # not auto-approved

    def test_fresh_goal_invents_no_lessons(self, env):
        *_, gsvc, aw, sup, skills, awareness = env
        # No supervised run → no blockers → only the goal node, zero lessons.
        plan = gsvc.own_goal(_CTR, scope="analytics.notifications")
        result = awareness.consolidate_goal(plan.goal.goal_id)
        assert len(result.nodes) == 1 and result.nodes[0].node_type is NodeType.goal_pattern
        assert result.lessons == []

    def test_single_weak_signal_makes_node_not_lesson(self, env):
        """One missing-evidence block → a low-confidence node, but NO lesson."""
        _, sstore, astore, *_ = env
        fake = _FakeGoalStore(_FakeGoal("goal-1"),
                              [_FakeAssignment("a1", "blocked_for_evidence")], [])
        result = WorkHistoryConsolidator(astore, fake).consolidate("goal-1")
        ev = [n for n in result.nodes if n.node_type is NodeType.evidence_pattern]
        assert ev and ev[0].confidence <= 0.5                # weak → low confidence
        assert result.lessons == []                          # below MIN_REPEAT → no lesson

    def test_two_signals_make_a_lesson(self, env):
        _, sstore, astore, *_ = env
        fake = _FakeGoalStore(
            _FakeGoal("goal-2"),
            [_FakeAssignment("a1", "blocked_for_evidence"),
             _FakeAssignment("a2", "blocked_for_evidence")], [])
        result = WorkHistoryConsolidator(astore, fake).consolidate("goal-2")
        assert result.lessons and result.lessons[0].confidence >= 0.7


# ── 2. Inspection + memory controls ───────────────────────────────────────────


class TestMemoryControls:
    def test_inspect_node_returns_provenance(self, env):
        *_, gsvc, aw, sup, skills, awareness = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        result = awareness.consolidate_goal(gid)
        ev = next(n for n in result.nodes if n.node_type is NodeType.evidence_pattern)
        insp = awareness.inspect_node(ev.node_id)
        assert insp["node"]["node_id"] == ev.node_id
        assert insp["source_refs"]
        assert any(l for l in insp["lessons"])               # the lesson cites this node

    def test_disable_lesson_drops_it_from_usable(self, env):
        *_, gsvc, aw, sup, skills, awareness = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        lid = awareness.consolidate_goal(gid).lessons[0].lesson_id
        awareness.disable_lesson(lid)
        assert lid not in {l.lesson_id for l in awareness.list_lessons(usable_only=True)}
        assert awareness.get_lesson(lid).status is NodeStatus.disabled

    def test_redact_node_preserves_audit_row(self, env):
        *_, gsvc, aw, sup, skills, awareness = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        nid = awareness.consolidate_goal(gid).nodes[0].node_id
        red = awareness.redact_node(nid)
        assert red.status is NodeStatus.redacted
        assert "redacted" in red.summary.lower()
        assert awareness.get_node(nid) is not None            # row + source links preserved
        assert awareness.get_node(nid).source_refs


# ── 3. World awareness (fixture-first, deterministic) ─────────────────────────


class TestWorldAwareness:
    def test_fixtures_are_offline_only(self):
        # Every fixture source/update URL is a fixture:// reference — no live network.
        for s in FIXTURE_SOURCES:
            assert s["url"].startswith("fixture://")
        for u in FIXTURE_UPDATES:
            assert u["source_url"].startswith("fixture://")
            assert all(c.startswith("fixture://") for c in u["citations"])

    def test_register_and_ingest_scores_updates(self, env):
        *_, awareness = env
        awareness.register_world_sources()
        updates = awareness.ingest_world()
        assert updates
        # each update carries a citation + a source + a deterministic relevance score
        for u in updates:
            assert u.source_id and u.citations
            assert u.relevance_score == score_relevance(u) or u.status is UpdateStatus.escalated

    def test_security_advisory_escalates(self, env):
        *_, awareness = env
        updates = awareness.ingest_world()
        sec = [u for u in updates if u.risk_level == "high"]
        assert sec and sec[0].status is UpdateStatus.escalated
        assert "human review" in sec[0].recommendation.lower()

    def test_low_trust_cannot_change_roadmap(self, env):
        *_, awareness = env
        updates = awareness.ingest_world()
        low = [u for u in updates if u.trust_level is TrustLevel.low]
        assert low and not low[0].can_change_roadmap
        assert "advisory" in low[0].recommendation.lower()

    def test_scoring_is_deterministic(self, env):
        *_, awareness = env
        updates = awareness.ingest_world()
        for u in updates:
            assert score_relevance(u) == score_relevance(u)

    def test_ingest_is_idempotent(self, env):
        *_, awareness = env
        first = awareness.ingest_world()
        second = awareness.ingest_world()
        # second pass ingests nothing new (dedup by stable source_url)
        assert second == []
        assert len(awareness.list_world_updates()) == len(first)

    def test_world_brief_is_source_cited(self, env):
        *_, awareness = env
        awareness.ingest_world()
        brief = awareness.world_brief()
        assert brief["count"] >= 1
        assert all(item["citations"] for item in brief["updates"])
        assert "advisory" in brief["boundary_note"].lower()


# ── 4. Improvement routing into V3.5 (governed, proposal-only) ────────────────


class TestImprovementRouting:
    def test_relevant_update_routes_to_proposed_only(self, env):
        _, sstore, *_rest, awareness = env
        updates = awareness.ingest_world()
        target = next(u for u in updates if u.trust_level is TrustLevel.high
                      and u.risk_level != "high" and u.relevance_score >= 0.5)
        imp = awareness.propose_improvement_from_update(target.update_id)
        assert imp.status == "pending"
        assert imp.skill_gap_id and imp.skill_proposal_id
        prop = sstore.get_proposal(imp.skill_proposal_id)
        # routed proposal stays in V3.5's PROPOSED state — never activated here
        assert prop.status is SkillProposalStatus.proposed

    def test_low_trust_update_is_blocked(self, env):
        *_, awareness = env
        updates = awareness.ingest_world()
        low = next(u for u in updates if u.trust_level is TrustLevel.low)
        with pytest.raises(ImprovementBlocked):
            awareness.propose_improvement_from_update(low.update_id)

    def test_high_risk_update_is_blocked(self, env):
        *_, awareness = env
        updates = awareness.ingest_world()
        high = next(u for u in updates if u.risk_level == "high")
        with pytest.raises(ImprovementBlocked):
            awareness.propose_improvement_from_update(high.update_id)

    def test_node_routing_and_redacted_node_blocked(self, env):
        _, sstore, astore, *_rest, awareness = env
        node = astore.create_node(_node("a reusable capability pattern", confidence=0.8))
        imp = awareness.propose_improvement_from_node(node.node_id)
        assert sstore.get_proposal(imp.skill_proposal_id).status is SkillProposalStatus.proposed
        # a redacted node can no longer be routed
        astore.redact_node(node.node_id)
        with pytest.raises(ImprovementBlocked):
            awareness.propose_improvement_from_node(node.node_id)

    def test_weak_node_is_blocked(self, env):
        _, sstore, astore, *_rest, awareness = env
        weak = astore.create_node(_node("weak signal", confidence=0.3))
        with pytest.raises(ImprovementBlocked):
            awareness.propose_improvement_from_node(weak.node_id)

    def test_memory_cannot_activate_a_skill(self, env):
        # The awareness layer exposes NO activation path; routed proposals stay pending.
        _, sstore, *_rest, awareness = env
        updates = awareness.ingest_world()
        target = next(u for u in updates if u.trust_level is TrustLevel.high
                      and u.risk_level != "high")
        awareness.propose_improvement_from_update(target.update_id)
        assert all(i.status == "pending" for i in awareness.list_improvements())
        assert not any(hasattr(awareness, m) for m in ("activate", "approve", "decide"))


# ── 5. Workspace integration ──────────────────────────────────────────────────


class TestWorkspaceIntegration:
    def test_consolidation_attaches_refs_to_workspace(self, env):
        _, _s, _a, ws, gsvc, aw, sup, skills, awareness = env
        plan = _blocked_goal(gsvc, aw, sup)
        awareness.consolidate_goal(plan.goal.goal_id)
        refs = ws.get_workspace(plan.goal.workspace_id).ledger_refs
        assert any(r.startswith("work_node:") for r in refs)
        assert any(r.startswith("work_lesson:") for r in refs)


# ── 6. Work Ledger events ─────────────────────────────────────────────────────


class TestLedger:
    def test_all_v36_events_emitted(self, env, writer):
        _, sstore, astore, ws, gsvc, aw, sup, skills, awareness = env
        gid = _blocked_goal(gsvc, aw, sup).goal.goal_id
        result = awareness.consolidate_goal(gid)
        awareness.disable_lesson(result.lessons[0].lesson_id)
        updates = awareness.ingest_world()
        target = next(u for u in updates if u.trust_level is TrustLevel.high and u.risk_level != "high")
        awareness.propose_improvement_from_update(target.update_id)
        types = set(_event_types(writer))
        for expected in ("work_memory_node_created", "work_memory_edge_created",
                         "work_lesson_created", "work_lesson_disabled", "work_memory_consolidated",
                         "world_source_registered", "world_update_ingested", "world_update_scored",
                         "improvement_proposal_created"):
            assert expected in types, f"missing event {expected}"

    def test_legacy_ledger_compatibility(self, env, writer):
        *_, gsvc, aw, sup, skills, awareness = env
        awareness.consolidate_goal(_blocked_goal(gsvc, aw, sup).goal.goal_id)
        v2 = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "work_memory_node_created" for e in v2)


# ── 7. Safety: secrets, confinement, restart, isolation ───────────────────────


class TestStructuralSecretRejection:
    """P1 — structural identifiers / join keys must NEVER persist a secret verbatim.
    They are REJECTED at the persistence boundary (never silently masked, which would
    corrupt referential meaning). The secret must not reach SQLite/WAL or the ledger."""

    def test_secret_in_source_node_ids_rejected(self, env, writer):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessSecurityError):
            astore.create_lesson(_lesson(source_node_ids=["password=SOURCESECRET999"]))
        astore.close()
        assert "SOURCESECRET999" not in _blob(writer)

    def test_secret_in_node_id_rejected(self, env, writer):
        _, _s, astore, *_rest = env
        bad = _node("ok").model_copy(update={"node_id": "node password=STRUCTSECRET888"})
        with pytest.raises(AwarenessSecurityError):
            astore.create_node(bad)
        astore.close()
        assert "STRUCTSECRET888" not in _blob(writer)

    def test_secret_in_node_source_refs_rejected(self, env, writer):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessSecurityError):
            astore.create_node(_node("ok", source_refs=["token=REFSECRET222"]))
        astore.close()
        assert "REFSECRET222" not in _blob(writer)

    def test_secret_in_edge_node_ids_rejected(self, env, writer):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessSecurityError):
            astore.create_edge(_edge(from_id="from password=EDGESECRET777"))
        with pytest.raises(AwarenessSecurityError):
            astore.create_edge(_edge(to_id="to Bearer EDGESECRET776abcdef"))
        astore.close()
        blob = _blob(writer)
        assert "EDGESECRET777" not in blob and "EDGESECRET776abcdef" not in blob

    def test_secret_in_source_id_rejected(self, env, writer):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessSecurityError):
            astore.register_source(_source(source_id="src password=SRCSECRET666"))
        astore.close()
        assert "SRCSECRET666" not in _blob(writer)

    def test_secret_in_update_ids_and_citations_rejected(self, env, writer):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessSecurityError):
            astore.ingest_update(_update(update_id="upd password=UPDSECRET555"))
        with pytest.raises(AwarenessSecurityError):
            astore.ingest_update(_update(source_id="src password=USRCSECRET554"))
        with pytest.raises(AwarenessSecurityError):
            astore.ingest_update(_update(citations=["api_key=CITESECRET553"]))
        astore.close()
        blob = _blob(writer)
        for s in ("UPDSECRET555", "USRCSECRET554", "CITESECRET553"):
            assert s not in blob

    def test_secret_in_improvement_ids_and_refs_rejected(self, env, writer):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessSecurityError):
            astore.create_improvement(_improvement(origin_ref="node password=ORIGSECRET444"))
        with pytest.raises(AwarenessSecurityError):
            astore.create_improvement(_improvement(source_refs=["token=IMPSECRET443"]))
        astore.close()
        blob = _blob(writer)
        assert "ORIGSECRET444" not in blob and "IMPSECRET443" not in blob


class TestFreeTextSecretsMasked:
    """Free-text fields (title/summary/lesson) still MASK secrets — the prose stays
    usable while the secret value is withheld."""

    def test_free_text_secret_is_masked_not_leaked(self, env, writer):
        _, _s, astore, *_rest = env
        astore.create_node(_node("leak password=NODESECRET111 here"))
        astore.create_lesson(_lesson(lesson_text="api_key=LESSONSECRET333 inside"))
        astore.close()
        blob = _blob(writer)
        for secret in ("NODESECRET111", "LESSONSECRET333"):
            assert secret not in blob, f"secret {secret!r} leaked into SQLite/WAL/ledger"


class TestNoOrphanRecords:
    """P1 — the store authority rejects source-less / orphan memory records, even on a
    DIRECT store call (not only via the service / consolidation path)."""

    def test_source_less_node_rejected(self, env):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessIntegrityError):
            astore.create_node(_node("no sources", source_refs=[]))

    def test_orphan_lesson_rejected(self, env):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessIntegrityError):
            astore.create_lesson(_lesson(source_node_ids=[]))

    def test_lesson_without_refs_or_evidence_rejected(self, env):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessIntegrityError):
            astore.create_lesson(_lesson(source_refs=[]))
        with pytest.raises(AwarenessIntegrityError):
            astore.create_lesson(_lesson(required_evidence=[]))

    def test_edge_without_source_refs_rejected(self, env):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessIntegrityError):
            astore.create_edge(_edge(source_refs=[]))

    def test_update_without_citations_rejected(self, env):
        _, _s, astore, *_rest = env
        with pytest.raises(AwarenessIntegrityError):
            astore.ingest_update(_update(citations=[]))


class TestRedactionAudit:
    """P2 — redacting a node is a durable, audited state change (outbox-recoverable)."""

    def test_redact_emits_ledger_event(self, env, writer):
        _, _s, astore, *_rest = env
        node = astore.create_node(_node("durable pattern"))
        astore.redact_node(node.node_id)
        types = _event_types(writer)
        assert "work_memory_node_created" in types
        assert "work_memory_node_redacted" in types

    def test_redact_audit_recovers_through_outbox(self, tmp_path):
        # If the ledger is down, the redaction audit stays PENDING in the transactional
        # outbox (state + audit never diverge) and flushes when a writer recovers.
        class _FailingWriter:
            def append(self, *a, **k):
                raise RuntimeError("ledger down")

        astore = AwarenessStore(writer=_FailingWriter(), execution_mode="offline_mock")
        try:
            node = astore.create_node(_node("durable"))
            astore.redact_node(node.node_id)
            assert astore.pending_audit_count() >= 1          # nothing lost while down
            good = LedgerWriter(tmp_path / "recover.jsonl")
            astore.flush_outbox(good)
            assert astore.pending_audit_count() == 0
            types = [json.loads(l)["event_type"]
                     for l in good.path.read_text(encoding="utf-8").splitlines()]
            assert "work_memory_node_redacted" in types
        finally:
            astore.close()


class TestSafety:
    def test_store_is_path_confined_and_restart_safe(self, env, writer):
        _, sstore, astore, *_rest = env
        node = astore.create_node(_node("durable pattern"))
        assert str(astore.db_path).startswith(str(aria_data_dir()))
        source_pkg = Path(__file__).resolve().parents[1] / "aria" / "awareness"
        assert not list(source_pkg.glob("*.sqlite"))
        astore.close()
        astore2 = AwarenessStore(writer=writer, execution_mode="offline_mock")
        assert astore2.get_node(node.node_id) is not None

    def test_v1_skill_import_does_not_load_awareness(self):
        code = (
            "import sys; import aria.skills.pr_review_skill; "
            "bad=[m for m in ('aria.awareness.service','aria.awareness.store',"
            "'aria.awareness.consolidation') if m in sys.modules]; "
            "print('LOADED', bad); assert not bad, bad"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "LOADED []" in r.stdout


# ── 8. API ────────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


def _blocked_goal_via_api(client) -> str:
    gid = client.post("/api/v3/goals", json={"raw_request": _CTR}).json()["goal"]["goal_id"]
    client.post(f"/api/v3/goals/{gid}/agents/plan")
    client.post(f"/api/v3/goals/{gid}/agents/supervise-run")
    return gid


class TestApi:
    def test_consolidate_inspect_disable_flow(self, client):
        gid = _blocked_goal_via_api(client)
        con = client.post("/api/v3/awareness/work-memory/consolidate", json={"goal_id": gid})
        assert con.status_code == 201
        body = con.json()
        assert body["nodes"] and body["lessons"]
        nid = body["nodes"][0]["node_id"]
        assert client.get(f"/api/v3/awareness/work-memory/nodes/{nid}").status_code == 200
        assert client.get("/api/v3/awareness/work-memory/nodes").json()["count"] >= 1
        lid = body["lessons"][0]["lesson_id"]
        assert client.post(f"/api/v3/awareness/lessons/{lid}/disable").status_code == 200
        assert client.post(f"/api/v3/awareness/work-memory/nodes/{nid}/redact").status_code == 200

    def test_world_and_improvement_flow(self, client):
        reg = client.post("/api/v3/awareness/world/sources/register")
        assert reg.status_code == 201 and reg.json()["count"] >= 1
        ing = client.post("/api/v3/awareness/world/ingest-fixtures")
        assert ing.status_code == 201
        updates = ing.json()["updates"]
        # a relevant high-trust, non-high-risk update routes to a proposal
        target = next(u for u in updates if u["trust_level"] == "high" and u["risk_level"] != "high")
        routed = client.post("/api/v3/awareness/improvements/from-update",
                             json={"update_id": target["update_id"]})
        assert routed.status_code == 201 and routed.json()["status"] == "pending"
        # a high-risk/security update is blocked by governance
        high = next(u for u in updates if u["risk_level"] == "high")
        blocked = client.post("/api/v3/awareness/improvements/from-update",
                             json={"update_id": high["update_id"]})
        assert blocked.status_code == 409
        assert client.get("/api/v3/awareness/world/brief").status_code == 200
        assert client.get("/api/v3/awareness/improvements").json()["count"] >= 1

    def test_safe_errors(self, client):
        assert client.post("/api/v3/awareness/work-memory/consolidate",
                          json={"goal_id": "goal-x"}).status_code == 404
        assert client.get("/api/v3/awareness/work-memory/nodes/node-x").status_code == 404
        assert client.get("/api/v3/awareness/lessons/lesson-x").status_code == 404
        assert client.post("/api/v3/awareness/improvements/from-update",
                          json={"update_id": "upd-x"}).status_code == 404
        assert client.post("/api/v3/awareness/improvements/from-node",
                          json={"node_id": "node-x"}).status_code == 404
