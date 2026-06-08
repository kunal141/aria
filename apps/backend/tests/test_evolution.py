"""
Evolution Intelligence Tests — Week 27

All tests are deterministic; no LLM calls.
Covers: models, store, monitor, debate (heuristic), sandbox, RAPTOR, integration.
"""
import json
import tempfile
from pathlib import Path

import pytest

from aria.evolution import (
    RISK_CEILING,
    DebateEngine,
    EvolutionMonitor,
    EvolutionProposal,
    EvolutionType,
    IntegrationContext,
    IntegrationEngine,
    InMemoryProposalStore,
    ProposalStatus,
    RaptorBuilder,
    RaptorChunk,
    RaptorTree,
    SandboxResult,
    query_tree,
    run_sandbox,
    utc_now,
)
from aria.evolution.models import DebateVerdict, IntegrationResult


# ── Helpers ────────────────────────────────────────────────────────────────────

def _proposal(
    *,
    pid: str = "prop-001",
    etype: EvolutionType = EvolutionType.rag,
    risk: float = 0.30,
    evidence: list[str] | None = None,
    status: ProposalStatus = ProposalStatus.draft,
) -> EvolutionProposal:
    if evidence is None:
        evidence = [
            "kpi_node had 0 supported claims in 8 of last 10 runs",
            "retrieval quality dropped after schema migration",
        ]
    return EvolutionProposal(
        proposal_id=pid,
        title="Improve KPI RAG retrieval",
        description="Upgrade retrieval layer for KPI investigation skill.",
        evolution_type=etype,
        status=status,
        evidence=evidence,
        risk_score=risk,
        expected_gain="Reduce unsupported-claim rate from 80% to <10%",
        proposed_at=utc_now(),
        proposed_by="monitor:work_ledger",
    )


def _approved_proposal() -> EvolutionProposal:
    """Proposal that has passed all three gates."""
    p = _proposal(status=ProposalStatus.approved)
    debate = DebateVerdict(
        proposal_id=p.proposal_id,
        recommendation="approve",
        confidence=0.80,
        pro_arguments=["strong evidence"],
        con_arguments=[],
        conditions=["sandbox must pass"],
        transcript=[],
        debated_at=utc_now(),
        rounds=2,
    )
    sandbox = SandboxResult(
        proposal_id=p.proposal_id,
        passed=True,
        checks_run=["compile_check:skipped", "schema_check", "risk_ceiling_check", "golden_test"],
        findings=[],
        evaluated_at=utc_now(),
    )
    return p.model_copy(update={
        "debate_verdict": debate,
        "sandbox_result": sandbox,
        "approved_by": "kunal",
        "approved_at": utc_now(),
    })


# ── Model tests ────────────────────────────────────────────────────────────────

class TestEvolutionModels:
    def test_risk_ceiling_keys_cover_all_types(self):
        for et in EvolutionType:
            assert et.value in RISK_CEILING

    def test_risk_score_out_of_range_raises(self):
        with pytest.raises(ValueError):
            _proposal(risk=1.5)

    def test_exceeds_risk_ceiling_true(self):
        p = _proposal(etype=EvolutionType.prompt, risk=0.31)
        assert p.exceeds_risk_ceiling() is True

    def test_exceeds_risk_ceiling_false(self):
        p = _proposal(etype=EvolutionType.rag, risk=0.40)
        assert p.exceeds_risk_ceiling() is False

    def test_is_ready_for_integration_all_gates_green(self):
        p = _approved_proposal()
        assert p.is_ready_for_integration() is True

    def test_is_ready_for_integration_missing_approval(self):
        p = _proposal()
        assert p.is_ready_for_integration() is False

    def test_is_ready_for_integration_sandbox_failed(self):
        p = _approved_proposal()
        failed_sandbox = SandboxResult(
            proposal_id=p.proposal_id,
            passed=False,
            checks_run=["schema_check"],
            findings=["schema_check FAILED"],
            evaluated_at=utc_now(),
        )
        p2 = p.model_copy(update={"sandbox_result": failed_sandbox})
        assert p2.is_ready_for_integration() is False

    def test_is_ready_for_integration_wrong_status(self):
        p = _approved_proposal().model_copy(update={"status": ProposalStatus.sandbox_passed})
        assert p.is_ready_for_integration() is False

    def test_utc_now_is_parseable(self):
        from datetime import datetime
        ts = utc_now()
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ── Store tests ────────────────────────────────────────────────────────────────

class TestInMemoryProposalStore:
    def test_save_and_get(self):
        store = InMemoryProposalStore()
        p = _proposal()
        store.save(p)
        assert store.get(p.proposal_id) == p

    def test_get_missing_returns_none(self):
        store = InMemoryProposalStore()
        assert store.get("nonexistent") is None

    def test_list_all(self):
        store = InMemoryProposalStore()
        store.save(_proposal(pid="a"))
        store.save(_proposal(pid="b"))
        assert len(store.list_all()) == 2

    def test_list_by_status(self):
        store = InMemoryProposalStore()
        store.save(_proposal(pid="d", status=ProposalStatus.draft))
        store.save(_proposal(pid="a", status=ProposalStatus.approved))
        assert len(store.list_by_status(ProposalStatus.draft)) == 1
        assert len(store.list_by_status(ProposalStatus.approved)) == 1

    def test_delete_existing(self):
        store = InMemoryProposalStore()
        p = _proposal()
        store.save(p)
        assert store.delete(p.proposal_id) is True
        assert store.get(p.proposal_id) is None

    def test_delete_missing_returns_false(self):
        store = InMemoryProposalStore()
        assert store.delete("ghost") is False

    def test_overwrite_with_save(self):
        store = InMemoryProposalStore()
        p = _proposal(risk=0.20)
        store.save(p)
        p2 = p.model_copy(update={"risk_score": 0.30})
        store.save(p2)
        assert store.get(p.proposal_id).risk_score == 0.30


# ── Monitor tests ──────────────────────────────────────────────────────────────

class TestEvolutionMonitor:
    def _write_ledger(self, tasks: list[dict], path: Path) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for t in tasks:
                fh.write(json.dumps(t) + "\n")

    def test_no_ledger_returns_empty_summary(self):
        monitor = EvolutionMonitor(ledger_path="/nonexistent/path.jsonl")
        summary = monitor.scan()
        assert summary.scanned_tasks == 0
        assert summary.signals == []

    def test_detects_high_error_rate(self, tmp_path):
        tasks = [
            {"task_type": "kpi", "error": "timeout"}
            for _ in range(4)
        ] + [
            {"task_type": "kpi", "error": None}
            for _ in range(1)
        ]
        lpath = tmp_path / "ledger.jsonl"
        self._write_ledger(tasks, lpath)
        monitor = EvolutionMonitor(ledger_path=str(lpath))
        summary = monitor.scan()
        signal_types = [s.signal_type for s in summary.signals]
        assert "high_error_rate" in signal_types

    def test_detects_low_support_rate(self, tmp_path):
        unsupported_ev = json.dumps({"is_safe_to_surface": False})
        tasks = [
            {"task_type": "kpi", "platform_evidence": unsupported_ev, "error": None}
            for _ in range(4)
        ] + [
            {"task_type": "kpi", "platform_evidence": None, "error": None}
            for _ in range(1)
        ]
        lpath = tmp_path / "ledger.jsonl"
        self._write_ledger(tasks, lpath)
        monitor = EvolutionMonitor(ledger_path=str(lpath))
        summary = monitor.scan()
        signal_types = [s.signal_type for s in summary.signals]
        assert "low_support_rate" in signal_types

    def test_proposals_are_draft(self, tmp_path):
        tasks = [{"task_type": "kpi", "error": "fail"} for _ in range(4)]
        tasks += [{"task_type": "kpi", "error": None}]
        lpath = tmp_path / "ledger.jsonl"
        self._write_ledger(tasks, lpath)
        monitor = EvolutionMonitor(ledger_path=str(lpath))
        summary = monitor.scan()
        for p in summary.proposals_draft:
            assert p.status == ProposalStatus.draft

    def test_stable_proposal_id_is_deterministic(self):
        from aria.evolution.monitor import _stable_id
        id1 = _stable_id("high_error_rate", "kpi", "work_ledger")
        id2 = _stable_id("high_error_rate", "kpi", "work_ledger")
        assert id1 == id2

    def test_proposal_risk_score_within_ceiling(self, tmp_path):
        tasks = [{"task_type": "kpi", "error": "fail"} for _ in range(4)]
        tasks += [{"task_type": "kpi", "error": None}]
        lpath = tmp_path / "ledger.jsonl"
        self._write_ledger(tasks, lpath)
        monitor = EvolutionMonitor(ledger_path=str(lpath))
        summary = monitor.scan()
        for p in summary.proposals_draft:
            ceiling = RISK_CEILING.get(p.evolution_type.value, 1.0)
            assert p.risk_score <= ceiling

    def test_fewer_than_3_tasks_no_signal(self, tmp_path):
        tasks = [{"task_type": "kpi", "error": "fail"}, {"task_type": "kpi", "error": "fail"}]
        lpath = tmp_path / "ledger.jsonl"
        self._write_ledger(tasks, lpath)
        monitor = EvolutionMonitor(ledger_path=str(lpath))
        summary = monitor.scan()
        assert summary.signals == []


# ── Debate tests ───────────────────────────────────────────────────────────────

class TestDebateEngine:
    def test_heuristic_approve_low_risk_good_evidence(self):
        engine = DebateEngine(llm_enabled=False, rounds=1)
        p = _proposal(risk=0.20, evidence=[
            "10 of last 10 runs had no supported claims",
            "RAG retrieval quality dropped 40% after migration",
        ])
        result = engine.debate(p)
        assert result.used_llm is False
        assert result.verdict.recommendation == "approve"

    def test_heuristic_defer_medium_risk(self):
        engine = DebateEngine(llm_enabled=False, rounds=1)
        p = _proposal(etype=EvolutionType.skill, risk=0.50, evidence=[
            "error rate 25% detected in recent tasks"
        ])
        result = engine.debate(p)
        assert result.verdict.recommendation in ("defer", "reject")

    def test_heuristic_reject_high_risk_no_evidence(self):
        engine = DebateEngine(llm_enabled=False, rounds=1)
        p = _proposal(etype=EvolutionType.agent, risk=0.70, evidence=["some general observation"])
        result = engine.debate(p)
        # high risk and only 1 evidence item → reject
        assert result.verdict.recommendation == "reject"

    def test_auto_reject_exceeds_ceiling(self):
        engine = DebateEngine(llm_enabled=False)
        p = _proposal(etype=EvolutionType.prompt, risk=0.50)  # ceiling is 0.30
        result = engine.debate(p)
        assert result.verdict.recommendation == "reject"
        assert result.verdict.confidence == 1.0
        assert "auto-rejected" in result.verdict.con_arguments[0]

    def test_transcript_contains_all_agents(self):
        engine = DebateEngine(llm_enabled=False, rounds=2)
        p = _proposal(risk=0.20, evidence=[
            "8 of 10 runs failed evidence check",
            "dropped 40% quality after schema change",
        ])
        result = engine.debate(p)
        agents = {arg.agent for arg in result.verdict.transcript}
        assert "ResearchAgent" in agents
        assert "ScepticAgent" in agents
        assert "ModeratorAgent" in agents

    def test_verdict_confidence_in_range(self):
        engine = DebateEngine(llm_enabled=False, rounds=1)
        p = _proposal()
        result = engine.debate(p)
        assert 0.0 <= result.verdict.confidence <= 1.0

    def test_conditions_empty_on_reject(self):
        engine = DebateEngine(llm_enabled=False)
        p = _proposal(etype=EvolutionType.agent, risk=0.70, evidence=["minor observation"])
        result = engine.debate(p)
        if result.verdict.recommendation == "reject":
            assert result.verdict.conditions == []


# ── Sandbox tests ──────────────────────────────────────────────────────────────

class TestSandbox:
    def test_clean_proposal_passes(self):
        result = run_sandbox(_proposal())
        assert result.passed is True
        assert result.findings == []

    def test_valid_python_passes_compile(self):
        src = "def hello():\n    return 42\n"
        result = run_sandbox(_proposal(), artifact_source=src)
        assert result.passed is True

    def test_invalid_python_fails_compile(self):
        src = "def broken(\n    return 42\n"
        result = run_sandbox(_proposal(), artifact_source=src)
        assert result.passed is False
        assert any("compile_check FAILED" in f for f in result.findings)

    def test_empty_evidence_fails_schema(self):
        p = _proposal(evidence=[])
        result = run_sandbox(p)
        assert result.passed is False
        assert any("evidence" in f for f in result.findings)

    def test_exceeds_ceiling_fails_risk_check(self):
        p = _proposal(etype=EvolutionType.prompt, risk=0.50)
        result = run_sandbox(p)
        assert result.passed is False
        assert any("risk_ceiling_check" in f for f in result.findings)

    def test_weak_evidence_fails_golden_test(self):
        p = _proposal(evidence=["ok", "yes"])
        result = run_sandbox(p)
        assert result.passed is False
        assert any("golden_test" in f for f in result.findings)

    def test_checks_run_recorded(self):
        result = run_sandbox(_proposal())
        assert "schema_check" in result.checks_run
        assert "risk_ceiling_check" in result.checks_run
        assert "golden_test" in result.checks_run

    def test_compile_skipped_when_no_source(self):
        result = run_sandbox(_proposal())
        assert any("compile_check:skipped" in c for c in result.checks_run)

    def test_proposal_id_in_result(self):
        p = _proposal(pid="test-sandbox-123")
        result = run_sandbox(p)
        assert result.proposal_id == "test-sandbox-123"


# ── RAPTOR tests ───────────────────────────────────────────────────────────────

class TestRaptor:
    _DOC = "\n\n".join([
        "Paragraph one about retrieval augmented generation and knowledge bases.",
        "Paragraph two discusses the challenge of long documents and summarisation.",
        "Paragraph three covers chunking strategies for embedding pipelines.",
        "Paragraph four explores hierarchical indexing and multi-level retrieval.",
        "Paragraph five concludes with evaluation metrics for RAG quality.",
    ])

    def test_tree_has_leaves(self):
        builder = RaptorBuilder(chunk_size=50, group_size=2)
        tree = builder.build("doc1", self._DOC)
        assert len(tree.leaves()) > 0

    def test_all_leaf_levels_are_zero(self):
        builder = RaptorBuilder(chunk_size=50, group_size=2)
        tree = builder.build("doc1", self._DOC)
        for leaf in tree.leaves():
            assert leaf.level == 0

    def test_level1_chunks_exist(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        assert len(tree.level(1)) > 0

    def test_root_id_set(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        assert tree.root_id is not None

    def test_root_in_chunks(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        assert tree.root_id in tree.chunks

    def test_parent_child_consistency(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        for chunk in tree.chunks.values():
            for child_id in chunk.children:
                assert child_id in tree.chunks
                child = tree.chunks[child_id]
                assert child.parent == chunk.chunk_id

    def test_path_to_root_terminates(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        for leaf in tree.leaves():
            path = tree.get_path_to_root(leaf.chunk_id)
            assert len(path) >= 1

    def test_query_returns_results(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        results = query_tree(tree, "retrieval chunking", top_k=3)
        assert len(results) >= 1

    def test_query_top_k_respected(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        results = query_tree(tree, "paragraph", top_k=2)
        assert len(results) <= 2

    def test_short_doc_single_leaf(self):
        builder = RaptorBuilder(chunk_size=200, group_size=3)
        tree = builder.build("tiny", "Only one paragraph here.")
        assert len(tree.leaves()) == 1

    def test_level2_root_text_is_nonempty(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        root = tree.chunks.get(tree.root_id)
        assert root is not None
        assert len(root.text.strip()) > 0

    def test_chunk_ids_are_unique(self):
        builder = RaptorBuilder(chunk_size=30, group_size=2)
        tree = builder.build("doc1", self._DOC)
        ids = list(tree.chunks.keys())
        assert len(ids) == len(set(ids))


# ── Integration engine tests ───────────────────────────────────────────────────

class TestIntegrationEngine:
    def test_dry_run_succeeds_on_approved_proposal(self):
        store = InMemoryProposalStore()
        p = _approved_proposal()
        store.save(p)
        engine = IntegrationEngine(store=store)
        ctx = IntegrationContext(dry_run=True)
        result = engine.integrate(p.proposal_id, ctx)
        assert result.success is True
        assert "dry_run" in (result.artifact_path or "")

    def test_proposal_status_updated_to_integrated(self):
        store = InMemoryProposalStore()
        p = _approved_proposal()
        store.save(p)
        engine = IntegrationEngine(store=store)
        engine.integrate(p.proposal_id, IntegrationContext(dry_run=True))
        updated = store.get(p.proposal_id)
        assert updated.status == ProposalStatus.integrated

    def test_fails_when_not_ready(self):
        store = InMemoryProposalStore()
        p = _proposal()  # draft — not ready
        store.save(p)
        engine = IntegrationEngine(store=store)
        result = engine.integrate(p.proposal_id, IntegrationContext(dry_run=True))
        assert result.success is False
        assert "blocked" in result.notes.lower()

    def test_fails_when_proposal_not_found(self):
        store = InMemoryProposalStore()
        engine = IntegrationEngine(store=store)
        result = engine.integrate("ghost-id", IntegrationContext(dry_run=True))
        assert result.success is False
        assert "not found" in result.notes.lower()

    def test_rollback_sets_rolled_back_status(self):
        store = InMemoryProposalStore()
        p = _approved_proposal()
        store.save(p)
        engine = IntegrationEngine(store=store)
        engine.integrate(p.proposal_id, IntegrationContext(dry_run=True))
        ok = engine.rollback(p.proposal_id)
        assert ok is True
        assert store.get(p.proposal_id).status == ProposalStatus.rolled_back

    def test_rollback_fails_when_not_integrated(self):
        store = InMemoryProposalStore()
        p = _proposal()
        store.save(p)
        engine = IntegrationEngine(store=store)
        ok = engine.rollback(p.proposal_id)
        assert ok is False

    def test_rollback_false_for_unknown_proposal(self):
        store = InMemoryProposalStore()
        engine = IntegrationEngine(store=store)
        assert engine.rollback("ghost") is False

    def test_filesystem_integration_writes_file(self, tmp_path):
        store = InMemoryProposalStore()
        p = _approved_proposal()
        store.save(p)
        engine = IntegrationEngine(store=store)
        ctx = IntegrationContext(
            artifact_dir=str(tmp_path / "artifacts"),
            archive_dir=str(tmp_path / "archive"),
            dry_run=False,
        )
        result = engine.integrate(p.proposal_id, ctx)
        assert result.success is True
        assert result.artifact_path is not None
        assert Path(result.artifact_path).exists()

    def test_archive_written_when_not_dry_run(self, tmp_path):
        store = InMemoryProposalStore()
        p = _approved_proposal()
        store.save(p)
        engine = IntegrationEngine(store=store)
        archive_dir = tmp_path / "archive"
        ctx = IntegrationContext(
            artifact_dir=str(tmp_path / "artifacts"),
            archive_dir=str(archive_dir),
            dry_run=False,
        )
        result = engine.integrate(p.proposal_id, ctx)
        assert result.rollback_available is True
        archive_files = list(archive_dir.iterdir())
        assert len(archive_files) == 1


# ── Full lifecycle round-trip ─────────────────────────────────────────────────

class TestEvolutionLifecycleRoundTrip:
    def test_full_lifecycle_draft_to_integrated(self):
        """
        draft → debate_pending → debate_complete → sandbox_pending →
        sandbox_passed → approved → integrated
        """
        store = InMemoryProposalStore()

        # 1. Create draft
        p = _proposal(pid="lifecycle-001")
        assert p.status == ProposalStatus.draft
        store.save(p)

        # 2. Debate
        engine = DebateEngine(llm_enabled=False, rounds=1)
        result = engine.debate(p)
        p = p.model_copy(update={
            "debate_verdict": result.verdict,
            "status": ProposalStatus.debate_complete,
        })
        store.save(p)
        assert p.status == ProposalStatus.debate_complete

        # 3. Sandbox (only proceed if debate approved)
        if result.verdict.recommendation != "approve":
            # For this test, we force an approvable proposal
            p = _proposal(pid="lifecycle-001b", risk=0.20, evidence=[
                "10 of 10 recent runs failed evidence gate",
                "retrieval quality dropped 50% after schema change",
            ])
            result = engine.debate(p)

        sandbox_result = run_sandbox(p)
        status_after_sandbox = (
            ProposalStatus.sandbox_passed if sandbox_result.passed
            else ProposalStatus.sandbox_failed
        )
        p = p.model_copy(update={
            "sandbox_result": sandbox_result,
            "status": status_after_sandbox,
        })
        store.save(p)

        if not sandbox_result.passed:
            # Can't proceed — that's a valid outcome
            assert p.status == ProposalStatus.sandbox_failed
            return

        # 4. Human approval (simulated)
        p = p.model_copy(update={
            "approved_by": "kunal",
            "approved_at": utc_now(),
            "status": ProposalStatus.approved,
        })
        store.save(p)
        assert p.is_ready_for_integration() is True

        # 5. Integrate
        integration_engine = IntegrationEngine(store=store)
        int_result = integration_engine.integrate(p.proposal_id, IntegrationContext(dry_run=True))
        assert int_result.success is True
        assert store.get(p.proposal_id).status == ProposalStatus.integrated

    def test_sandbox_failed_blocks_integration(self):
        store = InMemoryProposalStore()
        p = _proposal(evidence=[])  # empty evidence → sandbox fails schema_check
        failed_sandbox = run_sandbox(p)
        assert failed_sandbox.passed is False

        # Even if we somehow mark approved, is_ready_for_integration fails
        verdict = DebateEngine(llm_enabled=False).debate(p).verdict
        p2 = p.model_copy(update={
            "debate_verdict": verdict.model_copy(update={"recommendation": "approve"}),
            "sandbox_result": failed_sandbox,
            "approved_by": "kunal",
            "status": ProposalStatus.approved,
        })
        store.save(p2)
        engine = IntegrationEngine(store=store)
        result = engine.integrate(p2.proposal_id, IntegrationContext(dry_run=True))
        assert result.success is False
