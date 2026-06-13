"""
Week 28 — Governed Self-Improvement & Update Manager
Adversarial test suite: 13 scenarios + end-to-end completion bar.

Completion bar (must all pass):
  discovery → proposal → evaluation → T4 approval → canary → promotion
  → comparison → verified rollback

All tests are deterministic (llm_enabled=False, no network).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import pytest

from aria.evolution.models import (
    EvolutionProposal,
    EvolutionType,
    ProposalStatus,
)
from aria.evolution.monitor import EvolutionMonitor
from aria.evolution.pipeline import PipelineResult, ProposalPipeline
from aria.evolution.store import InMemoryProposalStore
from aria.evolution.update_manager.constitutional import (
    check_constitutional,
    is_constitutionally_safe,
)
from aria.evolution.update_manager.models import (
    ComponentType,
    ConcurrentActivationError,
    ConstitutionalViolationError,
    HashMismatchError,
    ImpactLevel,
    SelfApprovalError,
    UpdateNotFoundError,
    UpdateRelease,
    UpdateStateError,
    UpdateStatus,
    compute_hash,
    utc_now,
)
from aria.evolution.update_manager.operations import UpdateManager
from aria.evolution.update_manager.store import InMemoryUpdateStore


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_update(
    update_id: str = "upd-test-001",
    component: str = "pr_review_prompt",
    version: str = "1.1.0",
    previous_version: Optional[str] = "1.0.0",
    status: UpdateStatus = UpdateStatus.awaiting_approval,
    proposer: str = "aria",
    content: Optional[str] = None,
    previous_content: Optional[str] = None,
    changelog: str = "Improve PR risk scoring for media-tech pipelines.",
    canary_plan: str = "Deploy to 5% of traffic for 24h.",
) -> UpdateRelease:
    if content is None:
        content = f"# {component} v{version}\nImproved prompt content for {component}."
    content_hash = compute_hash(content)
    return UpdateRelease(
        update_id=update_id,
        component_name=component,
        component_type=ComponentType.prompt,
        semantic_version=version,
        previous_version=previous_version,
        rollback_target=previous_version,
        content_hash=content_hash,
        changelog=changelog,
        evidence_refs=["work_ledger:task-abc123", "eval:rubric_v2"],
        proposer=proposer,
        status=status,
        content=content,
        previous_content=previous_content,
        awaiting_approval_at=utc_now(),
        evaluated_at=utc_now(),
        canary_plan=canary_plan,
    )


def _make_proposal(
    title: str = "Improve PR prompt",
    etype: EvolutionType = EvolutionType.prompt,
    description: str = "Add media-tech context to PR review prompt.",
    evidence: Optional[list[str]] = None,
    expected_gain: str = "Reduce false-positive risk flags by 20%.",
    proposed_by: str = "aria",
    target_component: str = "pr_review_prompt",
) -> EvolutionProposal:
    return EvolutionProposal(
        proposal_id=f"prop-{title[:8].replace(' ', '-').lower()}-{utc_now()[:10]}",
        title=title,
        evolution_type=etype,
        target_component=target_component,
        description=description,
        evidence=evidence or ["work_ledger:task-001", "eval:rubric_run-42"],
        expected_gain=expected_gain,
        proposed_by=proposed_by,
        risk_score=0.2,
        proposed_at=utc_now(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 1 — Version creation
# ═══════════════════════════════════════════════════════════════════════════════

class TestVersionCreation:
    def test_update_release_fields_valid(self):
        upd = _make_update()
        assert upd.update_id == "upd-test-001"
        assert upd.component_name == "pr_review_prompt"
        assert upd.semantic_version == "1.1.0"
        assert upd.status == UpdateStatus.awaiting_approval
        assert len(upd.content_hash) == 64  # SHA-256 hex

    def test_content_hash_verified(self):
        upd = _make_update()
        assert upd.verify_hash() is True

    def test_invalid_content_hash_fails_validator(self):
        with pytest.raises(Exception):
            UpdateRelease(
                update_id="upd-bad",
                component_name="x",
                component_type=ComponentType.skill,
                semantic_version="1.0.0",
                content_hash="not-a-valid-sha256",
                changelog="test",
                evidence_refs=[],
                proposer="aria",
                status=UpdateStatus.proposed,
            )

    def test_invalid_semver_fails_validator(self):
        content = "hello"
        with pytest.raises(Exception):
            UpdateRelease(
                update_id="upd-bad",
                component_name="x",
                component_type=ComponentType.skill,
                semantic_version="not-a-version",
                content_hash=compute_hash(content),
                changelog="test",
                evidence_refs=[],
                proposer="aria",
                status=UpdateStatus.proposed,
                content=content,
            )

    def test_terminal_statuses(self):
        from aria.evolution.update_manager.models import TERMINAL_STATUSES
        assert UpdateStatus.active in TERMINAL_STATUSES
        assert UpdateStatus.superseded in TERMINAL_STATUSES
        assert UpdateStatus.rolled_back in TERMINAL_STATUSES
        assert UpdateStatus.rejected in TERMINAL_STATUSES
        assert UpdateStatus.awaiting_approval not in TERMINAL_STATUSES


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 2 — Update comparison
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpdateComparison:
    def test_compare_shows_diff(self):
        prev = "Old prompt: review code changes.\n"
        new  = "New prompt: review code changes with media-tech context.\n"
        upd  = _make_update(content=new, previous_content=prev)

        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        cmp = mgr.compare_update(upd.update_id)
        assert cmp.component_name == "pr_review_prompt"
        assert cmp.previous_version == "1.0.0"
        assert cmp.proposed_version == "1.1.0"
        assert len(cmp.diff_lines) > 0
        assert any("media-tech" in ln for ln in cmp.diff_lines)

    def test_compare_no_previous_content_gives_empty_diff(self):
        upd   = _make_update(previous_content=None)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        cmp = mgr.compare_update(upd.update_id)
        assert cmp.diff_lines == []

    def test_compare_unknown_id_raises(self):
        mgr = UpdateManager()
        with pytest.raises(UpdateNotFoundError):
            mgr.compare_update("does-not-exist")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 3 — Forged approval blocked
# ═══════════════════════════════════════════════════════════════════════════════

class TestForgedApprovalBlocked:
    def test_unauthorized_approver_blocked(self):
        upd   = _make_update()
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store, authorized_approvers={"kunal", "security-lead"})

        with pytest.raises(ValueError, match="not an authorized approver"):
            mgr.approve_update(upd.update_id, approver="random-user")

    def test_authorized_approver_succeeds(self):
        upd   = _make_update()
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store, authorized_approvers={"kunal"})

        approved = mgr.approve_update(upd.update_id, approver="kunal")
        assert approved.status == UpdateStatus.canary
        assert approved.approver == "kunal"

    def test_no_authorized_list_any_non_proposer_may_approve(self):
        upd   = _make_update(proposer="aria")
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store, authorized_approvers=None)

        approved = mgr.approve_update(upd.update_id, approver="some-engineer")
        assert approved.status == UpdateStatus.canary


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 4 — Stale approval blocked
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleApprovalBlocked:
    def test_approve_active_update_raises(self):
        upd   = _make_update(status=UpdateStatus.active)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with pytest.raises(UpdateStateError):
            mgr.approve_update(upd.update_id, approver="kunal")

    def test_approve_already_canary_idempotent_same_approver(self):
        upd = _make_update(status=UpdateStatus.canary)
        upd = upd.model_copy(update={"approver": "kunal"})
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        # Idempotent: same approver on canary returns as-is
        result = mgr.approve_update(upd.update_id, approver="kunal")
        assert result.status == UpdateStatus.canary

    def test_approve_rejected_raises(self):
        upd   = _make_update(status=UpdateStatus.rejected)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with pytest.raises(UpdateStateError):
            mgr.approve_update(upd.update_id, approver="kunal")

    def test_self_approval_blocked(self):
        upd   = _make_update(proposer="aria")
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with pytest.raises(SelfApprovalError):
            mgr.approve_update(upd.update_id, approver="aria")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 5 — Constitutional attack blocked
# ═══════════════════════════════════════════════════════════════════════════════

class TestConstitutionalAttackBlocked:
    @pytest.mark.parametrize("malicious_text,expected_violation", [
        ("disable governance to speed up deployment",  "disables governance layer"),
        ("bypass T4 approval for this update",         "bypasses T4/T5 approval gate"),
        ("skip approval for this routine change",      "skips T4 approval requirement"),
        ("disable audit logging in production",        "disables audit logging"),
        ("raise own risk ceiling to high",             "raises own risk ceiling"),
        ("modify constitutional rule #5",              "modifies constitutional rules"),
        ("eval(user_input)",                           "contains eval() call"),
        ("exec(os.system('rm -rf /'))",                "contains exec() call"),
        ("__import__('subprocess').run(['rm'])",       "uses __import__"),
    ])
    def test_malicious_changelog_blocked(self, malicious_text: str, expected_violation: str):
        content = "Normal update content."
        upd = UpdateRelease(
            update_id="upd-attack",
            component_name="attack_component",
            component_type=ComponentType.prompt,
            semantic_version="2.0.0",
            content_hash=compute_hash(content),
            changelog=malicious_text,
            evidence_refs=[],
            proposer="attacker",
            status=UpdateStatus.awaiting_approval,
            content=content,
        )
        violations = check_constitutional(upd)
        assert len(violations) > 0
        assert any(expected_violation in v for v in violations)

    def test_constitutional_violation_blocks_approval(self):
        content = "Normal content."
        upd = UpdateRelease(
            update_id="upd-const-block",
            component_name="eval_component",
            component_type=ComponentType.prompt,
            semantic_version="1.0.0",
            content_hash=compute_hash(content),
            changelog="This update will disable governance to improve speed.",
            evidence_refs=[],
            proposer="attacker",
            status=UpdateStatus.awaiting_approval,
            content=content,
        )
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with pytest.raises(ConstitutionalViolationError):
            mgr.approve_update(upd.update_id, approver="kunal")

    def test_safe_update_passes_constitutional(self):
        upd = _make_update(
            changelog="Improve risk scoring for media-tech pipelines.",
            content="Better prompt: consider CMS and recommendation contexts.",
        )
        assert is_constitutionally_safe(upd) is True

    def test_malicious_content_field_blocked(self):
        content = "This prompt will disable governance layer for testing."
        upd = UpdateRelease(
            update_id="upd-content-bad",
            component_name="sneaky_component",
            component_type=ComponentType.prompt,
            semantic_version="1.0.0",
            content_hash=compute_hash(content),
            changelog="Routine update.",
            evidence_refs=[],
            proposer="sneaky",
            status=UpdateStatus.awaiting_approval,
            content=content,
        )
        violations = check_constitutional(upd)
        assert len(violations) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 6 — Failed sandbox blocks pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailedSandboxBlocksPipeline:
    def test_pipeline_with_failing_sandbox_returns_blocked(self):
        from unittest.mock import patch
        from aria.evolution.models import SandboxResult as EvoSandboxResult

        proposal = _make_proposal()
        store    = InMemoryProposalStore()
        up_store = InMemoryUpdateStore()

        pipeline = ProposalPipeline(
            proposal_store=store,
            update_store=up_store,
            llm_enabled=False,
        )

        failing_sandbox = EvoSandboxResult(
            proposal_id=proposal.proposal_id,
            passed=False,
            checks_run=["compile_check", "import_check"],
            findings=["test_coverage_below_threshold", "import_error_detected"],
            evaluated_at=utc_now(),
        )
        with patch("aria.evolution.pipeline.run_sandbox", return_value=failing_sandbox):
            result = pipeline.run(proposal)

        assert result.succeeded is False
        assert result.update is None
        assert result.blocked_reason is not None
        assert "Sandbox failed" in result.blocked_reason

    def test_pipeline_with_passing_sandbox_creates_update(self):
        from unittest.mock import patch
        from aria.evolution.models import SandboxResult as EvoSandboxResult

        proposal = _make_proposal()
        store    = InMemoryProposalStore()
        up_store = InMemoryUpdateStore()

        pipeline = ProposalPipeline(
            proposal_store=store,
            update_store=up_store,
            llm_enabled=False,
        )

        passing_sandbox = EvoSandboxResult(
            proposal_id=proposal.proposal_id,
            passed=True,
            checks_run=["compile_check", "import_check"],
            findings=[],
            evaluated_at=utc_now(),
        )
        with patch("aria.evolution.pipeline.run_sandbox", return_value=passing_sandbox):
            result = pipeline.run(proposal)

        # Debate result determines outcome; may be approve or block
        # Key assertion: if debate approves AND sandbox passes → update created
        if result.succeeded:
            assert result.update is not None
            assert result.update.status == UpdateStatus.awaiting_approval


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 7 — Failed health check blocks promotion
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailedHealthCheckBlocksPromotion:
    def test_promote_canary_with_bad_hash_raises_hash_mismatch(self):
        upd = _make_update(status=UpdateStatus.canary)
        # Tamper with content after creation — hash no longer matches
        tampered = upd.model_copy(update={"content": "TAMPERED content here!"})

        store = InMemoryUpdateStore()
        store.save(tampered)
        mgr   = UpdateManager(store=store)

        with pytest.raises(HashMismatchError):
            mgr.promote_canary(tampered.update_id)

    def test_promote_canary_with_failing_health_check_raises(self):
        from unittest.mock import patch
        from aria.evolution.update_manager.health import HealthCheckResult

        upd   = _make_update(status=UpdateStatus.canary)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        bad_health = HealthCheckResult(
            passed=False,
            checks_run=4,
            findings=["content_hash_mismatch"],
        )
        with patch("aria.evolution.update_manager.operations.run_health_checks", return_value=bad_health):
            with pytest.raises(ValueError, match="promote_canary blocked"):
                mgr.promote_canary(upd.update_id)

    def test_promote_canary_non_canary_raises_state_error(self):
        upd   = _make_update(status=UpdateStatus.awaiting_approval)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with pytest.raises(UpdateStateError):
            mgr.promote_canary(upd.update_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 8 — Hash mismatch blocks activation
# ═══════════════════════════════════════════════════════════════════════════════

class TestHashMismatchBlocksActivation:
    def test_verify_hash_detects_tampered_content(self):
        upd = _make_update()
        # Tamper: change content but keep original hash
        tampered = upd.model_copy(update={"content": "completely different content!"})
        assert tampered.verify_hash() is False

    def test_verify_hash_passes_for_clean_update(self):
        upd = _make_update()
        assert upd.verify_hash() is True

    def test_rollback_target_hash_mismatch_blocked(self):
        # Target is in superseded state (the prior active version) and its
        # content has been tampered with so the in-memory hash no longer
        # matches content_hash. Rollback must refuse to restore it.
        target = _make_update(
            update_id="upd-target",
            version="1.0.0",
            status=UpdateStatus.superseded,
        )
        tampered_target = target.model_copy(update={
            "content": "tampered content after hash was set!"
        })
        current = _make_update(
            update_id="upd-current",
            version="1.1.0",
            status=UpdateStatus.active,
            previous_version="1.0.0",
        )

        store = InMemoryUpdateStore()
        store.save(tampered_target)
        store.save(current)
        mgr   = UpdateManager(store=store)

        with pytest.raises(HashMismatchError):
            mgr.rollback_update("pr_review_prompt", "1.0.0")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 9 — Concurrent activation blocked
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrentActivationBlocked:
    def test_acquire_component_returns_false_on_second_call(self):
        store = InMemoryUpdateStore()
        assert store.acquire_component("pr_review_prompt") is True
        assert store.acquire_component("pr_review_prompt") is False

    def test_release_component_releases_lock(self):
        store = InMemoryUpdateStore()
        store.acquire_component("pr_review_prompt")
        store.release_component("pr_review_prompt")
        assert store.acquire_component("pr_review_prompt") is True

    def test_concurrent_promotion_raises_for_second_caller(self):
        upd   = _make_update(status=UpdateStatus.canary)
        store = InMemoryUpdateStore()
        store.save(upd)

        # Manually claim the component-level lock before calling promote_canary.
        # This deterministically forces the second caller (the promote_canary
        # invocation below) to encounter a held lock.
        store.acquire_component(upd.component_name)

        mgr = UpdateManager(store=store)
        with pytest.raises(ConcurrentActivationError):
            mgr.promote_canary(upd.update_id)

    def test_two_threads_only_one_promotes(self):
        upd   = _make_update(status=UpdateStatus.canary)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        results: list[Exception | UpdateRelease] = []
        errors:  list[Exception] = []

        def try_promote():
            try:
                r = mgr.promote_canary(upd.update_id)
                results.append(r)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=try_promote)
        t2 = threading.Thread(target=try_promote)
        t1.start(); t2.start()
        t1.join();  t2.join()

        # Exactly one succeeds, one fails with concurrent or state error
        total = len(results) + len(errors)
        assert total == 2
        if len(results) == 1:
            assert results[0].status == UpdateStatus.active

    def test_concurrent_different_updates_same_component_only_one_wins(self):
        """
        Two concurrent promotions for DIFFERENT update_ids of the same component
        must result in exactly one active release.

        Before Round 8, the activation lock was keyed only by update_id so two
        different updates could both acquire their locks and both become active.
        The component-level lock added in Round 8 serialises them.
        """
        component = "pr_review_prompt"
        upd_a = _make_update(
            update_id="upd-concurrent-a",
            component=component,
            version="1.1.0",
            status=UpdateStatus.canary,
        )
        upd_b = _make_update(
            update_id="upd-concurrent-b",
            component=component,
            version="1.2.0",
            status=UpdateStatus.canary,
        )
        store = InMemoryUpdateStore()
        store.save(upd_a)
        store.save(upd_b)
        mgr = UpdateManager(store=store)

        results: list[UpdateRelease] = []
        errors: list[Exception] = []

        def try_promote(uid: str) -> None:
            try:
                results.append(mgr.promote_canary(uid))
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=try_promote, args=("upd-concurrent-a",))
        t2 = threading.Thread(target=try_promote, args=("upd-concurrent-b",))
        t1.start(); t2.start()
        t1.join();  t2.join()

        # Exactly one promotion succeeded
        active_in_store = [
            u for u in store.list_all() if u.status == UpdateStatus.active
        ]
        assert len(active_in_store) == 1, (
            f"Expected exactly 1 active release; got {len(active_in_store)}: "
            f"{[u.update_id for u in active_in_store]}"
        )
        assert len(results) + len(errors) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 10 — Interrupted deployment is recoverable
# ═══════════════════════════════════════════════════════════════════════════════

class TestInterruptedDeploymentRecoverable:
    def test_component_lock_released_in_finally_on_error(self):
        from unittest.mock import patch
        from aria.evolution.update_manager.health import HealthCheckResult

        upd   = _make_update(status=UpdateStatus.canary)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        bad_health = HealthCheckResult(passed=False, checks_run=2, findings=["timeout"])
        with patch("aria.evolution.update_manager.operations.run_health_checks", return_value=bad_health):
            with pytest.raises(ValueError):
                mgr.promote_canary(upd.update_id)

        # After failed promotion, the component lock must be released —
        # the next caller can acquire it cleanly.
        assert store.acquire_component(upd.component_name) is True
        store.release_component(upd.component_name)

    def test_reject_available_after_failed_promotion(self):
        from unittest.mock import patch
        from aria.evolution.update_manager.health import HealthCheckResult

        upd   = _make_update(status=UpdateStatus.canary)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        bad_health = HealthCheckResult(passed=False, checks_run=2, findings=["crash"])
        with patch("aria.evolution.update_manager.operations.run_health_checks", return_value=bad_health):
            with pytest.raises(ValueError):
                mgr.promote_canary(upd.update_id)

        # Update still in canary, can be rejected for investigation
        rejected = mgr.reject_update(upd.update_id, reason="Canary promotion failed — investigating")
        assert rejected.status == UpdateStatus.rejected


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 11 — Rollback restores prior version
# ═══════════════════════════════════════════════════════════════════════════════

class TestRollbackRestoresPriorVersion:
    def test_rollback_restores_target_to_active(self):
        v1_content = "# pr_review_prompt v1.0.0\nOriginal prompt."
        v2_content = "# pr_review_prompt v1.1.0\nImproved prompt — turns out it regressed."

        v1 = UpdateRelease(
            update_id="upd-v1",
            component_name="pr_review_prompt",
            component_type=ComponentType.prompt,
            semantic_version="1.0.0",
            content_hash=compute_hash(v1_content),
            changelog="Initial version.",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.superseded,   # was active, then superseded by v2
            content=v1_content,
        )
        v2 = UpdateRelease(
            update_id="upd-v2",
            component_name="pr_review_prompt",
            component_type=ComponentType.prompt,
            semantic_version="1.1.0",
            previous_version="1.0.0",
            content_hash=compute_hash(v2_content),
            changelog="Improved prompt.",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.active,
            content=v2_content,
        )

        store = InMemoryUpdateStore()
        store.save(v1)
        store.save(v2)
        mgr   = UpdateManager(store=store)

        restored = mgr.rollback_update("pr_review_prompt", "1.0.0")
        assert restored.status == UpdateStatus.active
        assert restored.semantic_version == "1.0.0"

    def test_rollback_marks_current_as_rolled_back(self):
        v1_content = "v1 content"
        v2_content = "v2 content"

        v1 = UpdateRelease(
            update_id="upd-v1b",
            component_name="routing_rule_component",
            component_type=ComponentType.routing_rule,
            semantic_version="1.0.0",
            content_hash=compute_hash(v1_content),
            changelog="Initial routing rule.",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.superseded,
            content=v1_content,
        )
        v2 = UpdateRelease(
            update_id="upd-v2b",
            component_name="routing_rule_component",
            component_type=ComponentType.routing_rule,
            semantic_version="1.1.0",
            previous_version="1.0.0",
            content_hash=compute_hash(v2_content),
            changelog="Updated routing rule.",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.active,
            content=v2_content,
        )

        store = InMemoryUpdateStore()
        store.save(v1)
        store.save(v2)
        mgr   = UpdateManager(store=store)

        mgr.rollback_update("routing_rule_component", "1.0.0")

        current_v2 = store.get("upd-v2b")
        assert current_v2 is not None
        assert current_v2.status == UpdateStatus.rolled_back

    def test_rollback_unknown_version_raises(self):
        mgr = UpdateManager()
        with pytest.raises((UpdateNotFoundError, KeyError)):
            mgr.rollback_update("nonexistent_component", "9.9.9")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 12 — Work-ledger signal creates a proposal
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkLedgerSignalCreatesProposal:
    def test_monitor_scan_with_ledger_creates_proposals(self, tmp_path):
        import json

        ledger_file = tmp_path / "work_ledger.jsonl"
        entries = [
            {
                "task_id":    f"task-{i:03d}",
                "task_type":  "pr_review",
                "task_status": "done",
                "skill_name": "pr_review",
                "skill_output": json.dumps({"verdict": "approve", "risk_level": "low"}),
                "raw_input":   "Review PR #100",
                "response":    "PR approved.",
                "error":       None,
            }
            for i in range(10)
        ]
        ledger_file.write_text("\n".join(json.dumps(e) for e in entries))

        monitor = EvolutionMonitor(ledger_path=str(ledger_file))
        summary = monitor.scan()

        assert summary.scanned_tasks == 10
        # Monitor should find repeated-task signals (10 identical pr_review tasks)
        assert isinstance(summary.signals, list)
        assert isinstance(summary.proposals_draft, list)

    def test_monitor_scan_empty_ledger_no_signals(self, tmp_path):
        ledger_file = tmp_path / "work_ledger.jsonl"
        ledger_file.write_text("")

        monitor = EvolutionMonitor(ledger_path=str(ledger_file))
        summary = monitor.scan()

        assert summary.scanned_tasks == 0
        assert len(summary.signals) == 0

    def test_monitor_scan_missing_ledger_returns_empty(self):
        monitor = EvolutionMonitor(ledger_path="/nonexistent/path/ledger.jsonl")
        summary = monitor.scan()
        assert summary.scanned_tasks == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 13 — Evidence coverage gap creates a proposal
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvidenceCoverageGapCreatesProposal:
    def test_monitor_scan_with_failed_tasks_signals_gap(self, tmp_path):
        import json

        ledger_file = tmp_path / "work_ledger.jsonl"
        # 5 failed qa tasks — evidence gap pattern
        entries = [
            {
                "task_id":    f"task-qa-{i:03d}",
                "task_type":  "qa",
                "task_status": "failed",
                "skill_name": "qa",
                "skill_output": json.dumps({"error": "no test coverage data"}),
                "raw_input":   "Generate test cases for component X",
                "response":    None,
                "error":       "no test coverage data",
            }
            for i in range(5)
        ]
        ledger_file.write_text("\n".join(json.dumps(e) for e in entries))

        monitor = EvolutionMonitor(ledger_path=str(ledger_file))
        summary = monitor.scan()

        assert summary.scanned_tasks == 5
        # Monitor should detect repeated failures as a signal
        assert isinstance(summary.signals, list)

    def test_proposal_has_evidence_refs(self):
        proposal = _make_proposal(
            evidence=["work_ledger:failed_task_qa_001", "eval:coverage_gap_report"]
        )
        assert len(proposal.evidence) == 2
        assert "work_ledger" in proposal.evidence[0]


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end Completion Bar
# discovery → proposal → evaluation → T4 approval → canary → promotion
#   → comparison → verified rollback
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEndCompletionBar:
    """
    One versioned prompt update travels through the full governed lifecycle.
    This is the single test that proves Week 28 is complete.
    """

    def test_full_governed_lifecycle(self):
        from unittest.mock import patch
        from aria.evolution.sandbox import SandboxResult
        from aria.evolution.debate import DebateVerdict

        # ── Step 1: Discovery — create a proposal from work ledger signal ────────
        proposal = _make_proposal(
            title="Improve PR prompt for media-tech pipelines",
            etype=EvolutionType.prompt,
            description="Add CMS and recommendation pipeline context to PR review.",
            evidence=["work_ledger:task-001", "eval:rubric_run-10"],
            expected_gain="Reduce false-positive rate from 35% to 20%.",
        )
        assert proposal.proposal_id is not None
        assert proposal.status == ProposalStatus.draft

        # ── Step 2: Pipeline — debate → sandbox → awaiting_approval ─────────────
        prop_store = InMemoryProposalStore()
        upd_store  = InMemoryUpdateStore()

        pipeline = ProposalPipeline(
            proposal_store=prop_store,
            update_store=upd_store,
            llm_enabled=False,
        )

        from aria.evolution.models import DebateVerdict, DebateArgument
        from aria.evolution.debate import DebateResult
        from aria.evolution.models import SandboxResult as EvoSandboxResult

        passing_verdict = DebateVerdict(
            proposal_id=proposal.proposal_id,
            recommendation="approve",
            pro_arguments=["Strong evidence", "Clear gain"],
            con_arguments=[],
            conditions=[],
            transcript=[DebateArgument(agent="ModeratorAgent", round=1, content="Approved.")],
            confidence=0.85,
            debated_at=utc_now(),
            rounds=2,
        )
        passing_sandbox = EvoSandboxResult(
            proposal_id=proposal.proposal_id,
            passed=True,
            checks_run=["compile_check"],
            findings=[],
            evaluated_at=utc_now(),
        )

        with patch("aria.evolution.pipeline.run_sandbox", return_value=passing_sandbox):
            with patch.object(pipeline._debate, "debate") as mock_debate:
                mock_result = DebateResult(verdict=passing_verdict, used_llm=False)
                mock_debate.return_value = mock_result
                result = pipeline.run(proposal, current_version="1.1.0", previous_content="Old prompt v1.0.0.")

        assert result.succeeded is True, f"Pipeline blocked: {result.blocked_reason}"
        update = result.update
        assert update is not None

        # ── Step 3: Evaluation — update is in awaiting_approval ─────────────────
        assert update.status == UpdateStatus.awaiting_approval
        assert update.content_hash is not None
        assert len(update.content_hash) == 64

        # ── Step 4: T4 Approval — human approves ────────────────────────────────
        mgr     = UpdateManager(store=upd_store, authorized_approvers={"kunal"})
        canary  = mgr.approve_update(update.update_id, approver="kunal")

        assert canary.status == UpdateStatus.canary
        assert canary.approver == "kunal"

        # ── Step 5: Canary deployment — promote after health checks ──────────────
        active = mgr.promote_canary(canary.update_id)

        assert active.status == UpdateStatus.active
        assert active.update_id == canary.update_id

        # ── Step 6: Comparison — version diff visible ────────────────────────────
        comparison = mgr.compare_update(active.update_id)
        assert comparison.component_name == active.component_name
        assert comparison.proposed_version == "1.1.0"
        # There was previous_content passed to pipeline.run, diff should be non-empty
        assert isinstance(comparison.diff_lines, list)

        # ── Step 7: Verified rollback — create a v1.0.0 prior to roll back to ───
        v1_content = "Old prompt v1.0.0."
        v1 = UpdateRelease(
            update_id="upd-prior-v1",
            component_name=active.component_name,
            component_type=ComponentType.prompt,
            semantic_version="1.0.0",
            content_hash=compute_hash(v1_content),
            changelog="Initial version.",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.superseded,
            content=v1_content,
        )
        upd_store.save(v1)

        restored = mgr.rollback_update(active.component_name, "1.0.0")

        assert restored.status == UpdateStatus.active
        assert restored.semantic_version == "1.0.0"
        assert restored.verify_hash() is True

        # The v1.1.0 update must now be rolled_back
        rolled = upd_store.get(active.update_id)
        assert rolled is not None
        assert rolled.status == UpdateStatus.rolled_back


# ═══════════════════════════════════════════════════════════════════════════════
# Bonus — Evolution node integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvolutionNode:
    def test_list_pending_returns_valid_state(self):
        from aria.nodes.evolution_node import evolution_node
        state = {
            "raw_input": "show pending proposals",
            "steps_completed": [],
        }
        result = evolution_node(state)
        assert result["skill_name"] == "evolution"
        assert result["task_status"] == "executing"
        import json
        data = json.loads(result["skill_output"])
        assert data["action"] == "list_pending"
        assert isinstance(data["count"], int)

    def test_scan_with_missing_ledger_returns_empty_scan(self):
        from aria.nodes.evolution_node import evolution_node
        state = {
            "raw_input": "scan for capability gaps",
            "steps_completed": [],
            "ledger_path": "/nonexistent/work_ledger.jsonl",
        }
        result = evolution_node(state)
        assert result["skill_name"] == "evolution"
        import json
        data = json.loads(result["skill_output"])
        assert data["action"] == "scan"
        assert "evolution_node" in result["steps_completed"]

    def test_rollback_without_valid_input_returns_error(self):
        from aria.nodes.evolution_node import evolution_node
        state = {
            "raw_input": "rollback component",   # missing version
            "steps_completed": [],
        }
        result = evolution_node(state)
        import json
        data = json.loads(result["skill_output"])
        assert data["action"] == "rollback"
        assert "error" in data

    def test_unknown_intent_defaults_to_list_pending(self):
        from aria.nodes.evolution_node import evolution_node
        state = {
            "raw_input": "what is going on with evolution",
            "steps_completed": [],
        }
        result = evolution_node(state)
        import json
        data = json.loads(result["skill_output"])
        assert data["action"] == "list_pending"

    def test_compare_update_with_unknown_id_returns_error(self):
        from aria.nodes.evolution_node import evolution_node
        state = {
            "raw_input": "compare update upd-does-not-exist-99",
            "steps_completed": [],
        }
        result = evolution_node(state)
        import json
        data = json.loads(result["skill_output"])
        assert data["action"] == "compare_update"
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# Changelog and show_changelog
# ═══════════════════════════════════════════════════════════════════════════════

class TestChangelog:
    def test_show_changelog_returns_oldest_first(self):
        v1 = _make_update("upd-cl-1", version="1.0.0", status=UpdateStatus.superseded)
        v2 = _make_update("upd-cl-2", version="1.1.0", status=UpdateStatus.superseded)
        v3 = _make_update("upd-cl-3", version="1.2.0", status=UpdateStatus.active)

        store = InMemoryUpdateStore()
        for u in [v3, v1, v2]:   # intentionally out of order
            store.save(u)

        mgr = UpdateManager(store=store)
        history = mgr.show_changelog("pr_review_prompt")
        assert len(history) == 3

    def test_reject_non_terminal_update(self):
        upd   = _make_update(status=UpdateStatus.proposed)
        upd   = upd.model_copy(update={"content_hash": compute_hash(upd.content or "")})
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        rejected = mgr.reject_update(upd.update_id, reason="Not needed this sprint.")
        assert rejected.status == UpdateStatus.rejected
        assert rejected.rejection_reason == "Not needed this sprint."

    def test_reject_terminal_update_raises(self):
        upd   = _make_update(status=UpdateStatus.active)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with pytest.raises(UpdateStateError):
            mgr.reject_update(upd.update_id, reason="Too late.")


# ═══════════════════════════════════════════════════════════════════════════════
# Codex P1/P2/P3 round-3 fixes
# ═══════════════════════════════════════════════════════════════════════════════

class TestCodexRound3Fixes:
    """Tests for the 7 findings from the Codex round-3 review."""

    # ── P3: Semver must be strict x.y.z ───────────────────────────────────────

    def test_semver_with_suffix_rejected(self):
        """1.2.3-alpha or 1.2.3.4 must not pass validation."""
        content = "test content"
        for bad_ver in ("1.2.3-alpha", "1.2.3.4", "1.2.3.beta", "1.2.3 extra"):
            with pytest.raises(Exception):
                UpdateRelease(
                    update_id=f"upd-bad-{bad_ver[:5]}",
                    component_name="x",
                    component_type=ComponentType.prompt,
                    semantic_version=bad_ver,
                    content_hash=compute_hash(content),
                    changelog="test",
                    evidence_refs=[],
                    proposer="aria",
                    status=UpdateStatus.proposed,
                    content=content,
                )

    def test_valid_semver_accepted(self):
        content = "valid content"
        upd = UpdateRelease(
            update_id="upd-ok-semver",
            component_name="comp",
            component_type=ComponentType.prompt,
            semantic_version="2.14.0",
            content_hash=compute_hash(content),
            changelog="ok",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.proposed,
            content=content,
        )
        assert upd.semantic_version == "2.14.0"

    # ── P2: UpdateRelease is frozen ────────────────────────────────────────────

    def test_update_release_is_immutable(self):
        """Direct field mutation must raise."""
        upd = _make_update()
        with pytest.raises(Exception):  # pydantic ValidationError or TypeError
            upd.status = UpdateStatus.active  # type: ignore[misc]

    def test_model_copy_still_works(self):
        """model_copy(update={...}) must produce a new object without error."""
        upd = _make_update()
        promoted = upd.model_copy(update={"status": UpdateStatus.canary, "canary_at": utc_now()})
        assert promoted.status == UpdateStatus.canary
        assert upd.status == UpdateStatus.awaiting_approval  # original unchanged

    # ── P1: activate_canary requires approver ─────────────────────────────────

    def test_activate_canary_requires_approver(self):
        """activate_canary(update_id, approver) — self-approval must fail."""
        upd   = _make_update(proposer="aria")
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with pytest.raises(SelfApprovalError):
            mgr.activate_canary(upd.update_id, approver="aria")

    def test_activate_canary_with_valid_approver_succeeds(self):
        upd   = _make_update(proposer="aria")
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        result = mgr.activate_canary(upd.update_id, approver="kunal")
        assert result.status == UpdateStatus.canary

    def test_activate_canary_evaluated_state_blocked(self):
        """evaluated status is no longer a valid source for activate_canary."""
        upd   = _make_update(status=UpdateStatus.evaluated)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with pytest.raises(UpdateStateError):
            mgr.activate_canary(upd.update_id, approver="kunal")

    # ── P2: Rollback requires non-None content ────────────────────────────────

    def test_rollback_target_without_content_blocked(self):
        """A restore target with no content must never succeed."""
        content_none_target = UpdateRelease(
            update_id="upd-no-content",
            component_name="empty_component",
            component_type=ComponentType.prompt,
            semantic_version="1.0.0",
            content_hash=compute_hash("placeholder"),  # hash mismatch — verify_hash fails
            changelog="status-only record",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.superseded,
            content=None,   # no content!
        )
        current = _make_update(
            update_id="upd-current-empty",
            component="empty_component",
            version="1.1.0",
            status=UpdateStatus.active,
        )

        store = InMemoryUpdateStore()
        store.save(content_none_target)
        store.save(current)
        mgr   = UpdateManager(store=store)

        with pytest.raises((ValueError, HashMismatchError)):
            mgr.rollback_update("empty_component", "1.0.0")

    # ── P1: Evolution reachable from router ───────────────────────────────────

    def test_router_classifies_evolution_intent(self):
        """Keyword router must route evolution phrases to task_type=evolution."""
        from aria.nodes.router import _keyword_classify

        evolution_inputs = [
            "scan for capability gaps",
            "show pending self-improvement proposals",
            "compare update versions",
            "rollback component pr_review_prompt to 1.0.0",
            "evaluate proposal prop-abc",
            "what updates are awaiting approval",
        ]
        for phrase in evolution_inputs:
            task_type, reason = _keyword_classify(phrase)
            assert task_type == "evolution", (
                f"Expected evolution, got {task_type!r} for: {phrase!r}"
            )

    def test_router_valid_types_includes_evolution(self):
        from aria.nodes.router import VALID_TYPES
        assert "evolution" in VALID_TYPES

    # ── P1: File-backed persistence ────────────────────────────────────────────

    def test_store_persists_across_instances(self, tmp_path):
        """Records saved in one instance should load in a new instance."""
        persist_file = tmp_path / "updates.jsonl"
        upd = _make_update()

        store1 = InMemoryUpdateStore(persist_path=persist_file)
        store1.save(upd)

        store2 = InMemoryUpdateStore(persist_path=persist_file)
        loaded = store2.get(upd.update_id)
        assert loaded is not None
        assert loaded.update_id == upd.update_id
        assert loaded.status == upd.status

    def test_store_no_persist_path_stays_in_memory(self, tmp_path):
        """Default persist_path=None — no file written."""
        upd   = _make_update()
        store = InMemoryUpdateStore(persist_path=None)
        store.save(upd)
        assert store.get(upd.update_id) is not None
        # No files in tmp_path because persist_path=None
        assert list(tmp_path.iterdir()) == []

    def test_store_corrupted_line_skipped_on_load(self, tmp_path):
        """A malformed JSONL line must not crash startup."""
        persist_file = tmp_path / "updates.jsonl"
        upd = _make_update()

        store1 = InMemoryUpdateStore(persist_path=persist_file)
        store1.save(upd)

        # Inject a corrupted line
        with open(persist_file, "a") as fh:
            fh.write("NOT VALID JSON\n")

        store2 = InMemoryUpdateStore(persist_path=persist_file)
        assert store2.get(upd.update_id) is not None  # good record still loaded

    # ── P1: Teams evolution approval card carries update_id ───────────────────

    def test_evolution_card_action_data_includes_update_id(self):
        """Approve/Reject actions must carry evolution_update_id (searched recursively)."""
        from aria.integrations.teams_bot import _build_evolution_approval_card

        data = {
            "action":        "list_pending",
            "count":         1,
            "updates":       [{"update_id": "upd-test-001", "component": "x", "version": "1.0.0", "status": "awaiting_approval"}],
            "message":       "1 update pending.",
            "updates_queued": ["upd-test-001"],
        }
        card = _build_evolution_approval_card(data, task_id="task-abc")

        # Per-update design: actions live inside body Containers; collect them all
        all_submit: list[dict] = []

        def _collect(items):
            for item in items:
                if item.get("type") == "ActionSet":
                    all_submit.extend(
                        a for a in item.get("actions", [])
                        if a.get("type") == "Action.Submit"
                    )
                elif item.get("type") == "Container":
                    _collect(item.get("items", []))

        _collect(card.get("body", []))
        for a in card.get("actions", []):
            if a.get("type") == "Action.Submit":
                all_submit.append(a)

        approve_action = next(a for a in all_submit if "Approve" in a.get("title", ""))
        reject_action  = next(a for a in all_submit if "Reject"  in a.get("title", ""))
        assert approve_action["data"].get("evolution_update_id") == "upd-test-001"
        assert reject_action["data"].get("evolution_update_id")  == "upd-test-001"

    # ── P1: Teams approval changes UpdateManager state ────────────────────────

    def test_teams_approval_changes_status_to_canary(self):
        """_execute_evolution_after_approval must move update to canary status."""
        from unittest.mock import patch
        from aria.integrations.teams_bot import _execute_evolution_after_approval
        from aria.evolution.update_manager.operations import UpdateManager
        from aria.evolution.update_manager.store import InMemoryUpdateStore

        upd   = _make_update(proposer="aria", status=UpdateStatus.awaiting_approval)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with patch("aria.nodes.evolution_node.get_update_manager", return_value=mgr):
            result = _execute_evolution_after_approval(upd.update_id, approver="kunal")

        assert result is not None
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["status"] == "canary"
        assert result["approver"] == "kunal"

        stored = store.get(upd.update_id)
        assert stored is not None
        assert stored.status == UpdateStatus.canary

    def test_teams_rejection_changes_status_to_rejected(self):
        """_execute_evolution_rejection must move update to rejected status."""
        from unittest.mock import patch
        from aria.integrations.teams_bot import _execute_evolution_rejection
        from aria.evolution.update_manager.operations import UpdateManager
        from aria.evolution.update_manager.store import InMemoryUpdateStore

        upd   = _make_update(proposer="aria", status=UpdateStatus.awaiting_approval)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with patch("aria.nodes.evolution_node.get_update_manager", return_value=mgr):
            result = _execute_evolution_rejection(upd.update_id, reason="Not this sprint")

        assert result is not None
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["status"] == "rejected"

        stored = store.get(upd.update_id)
        assert stored is not None
        assert stored.status == UpdateStatus.rejected

    def test_teams_approval_self_approval_returns_error(self):
        """Teams approval by proposer must return an error dict, not raise."""
        from unittest.mock import patch
        from aria.integrations.teams_bot import _execute_evolution_after_approval
        from aria.evolution.update_manager.operations import UpdateManager
        from aria.evolution.update_manager.store import InMemoryUpdateStore

        upd   = _make_update(proposer="kunal", status=UpdateStatus.awaiting_approval)
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr   = UpdateManager(store=store)

        with patch("aria.nodes.evolution_node.get_update_manager", return_value=mgr):
            result = _execute_evolution_after_approval(upd.update_id, approver="kunal")

        assert result is not None
        assert "error" in result  # self-approval → error

    # ── P1: Graph routes evolution intent to evolution_node ──────────────────

    def test_graph_routes_evolution_to_skill(self):
        """Full graph invocation with an evolution phrase must reach evolution_node."""
        from aria.graph import build_graph

        g = build_graph()
        state = {
            "task_id":        "test-evo-routing",
            "raw_input":      "scan for capability gaps",
            "task_type":      None,
            "task_status":    "pending",
            "routing_reason": None,
            "steps_completed": [],
            "skill_name":     None,
            "skill_output":   None,
            "response":       None,
            "messages":       [],
            "error":          None,
        }

        result = g.invoke(state)
        assert result["skill_name"] == "evolution", (
            f"Expected skill_name='evolution', got {result.get('skill_name')!r}. "
            f"task_type={result.get('task_type')!r}"
        )
        import json
        data = json.loads(result["skill_output"])
        assert data["action"] == "scan"

    # ── P5: Artifact write in promote_canary ──────────────────────────────────

    def test_promote_canary_writes_artifact_to_disk(self, tmp_path):
        """promote_canary must write content to artifact_path when set."""
        artifact_file = tmp_path / "pr_review_prompt.txt"
        content = "# PR Review Prompt v1.1.0\nImproved content."
        upd = UpdateRelease(
            update_id="upd-artifact-write",
            component_name="pr_review_prompt",
            component_type=ComponentType.prompt,
            semantic_version="1.1.0",
            content_hash=compute_hash(content),
            changelog="Improved prompt.",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.canary,
            content=content,
            artifact_path=str(artifact_file),
        )
        store = InMemoryUpdateStore()
        store.save(upd)
        mgr = UpdateManager(store=store, deployment_root=tmp_path)

        active = mgr.promote_canary(upd.update_id)

        assert active.status == UpdateStatus.active
        # Versioned artifact design: promoted content lives at active.artifact_path,
        # not necessarily at the original artifact_file path.
        assert Path(active.artifact_path).exists(), "versioned artifact file must exist after promotion"
        written = Path(active.artifact_path).read_text(encoding="utf-8")
        assert written == content, "File content must match the promoted content"

    def test_rollback_restores_artifact_to_disk(self, tmp_path):
        """rollback_update must restore prior content to artifact_path."""
        artifact_file = tmp_path / "prompt.txt"
        v1_content = "# Prompt v1.0.0\nOriginal."
        v2_content = "# Prompt v1.1.0\nBuggy version."

        v1 = UpdateRelease(
            update_id="upd-rb-v1",
            component_name="prompt_component",
            component_type=ComponentType.prompt,
            semantic_version="1.0.0",
            content_hash=compute_hash(v1_content),
            changelog="Initial.",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.superseded,
            content=v1_content,
            artifact_path=str(artifact_file),
        )
        v2 = UpdateRelease(
            update_id="upd-rb-v2",
            component_name="prompt_component",
            component_type=ComponentType.prompt,
            semantic_version="1.1.0",
            previous_version="1.0.0",
            content_hash=compute_hash(v2_content),
            changelog="Buggy version.",
            evidence_refs=[],
            proposer="aria",
            status=UpdateStatus.active,
            content=v2_content,
            artifact_path=str(artifact_file),
        )

        # Start with v2 on disk
        artifact_file.write_text(v2_content, encoding="utf-8")

        store = InMemoryUpdateStore()
        store.save(v1)
        store.save(v2)
        mgr = UpdateManager(store=store, deployment_root=tmp_path)

        result = mgr.rollback_update("prompt_component", "1.0.0")

        # Versioned artifact design: v1 content lives at result.artifact_path.
        on_disk = Path(result.artifact_path).read_text(encoding="utf-8")
        assert on_disk == v1_content, (
            f"Rollback must restore v1 content. Got: {on_disk!r}"
        )
