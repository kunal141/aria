"""
Week 28 Stabilization Acceptance Tests

38 tests covering the 10 checklist items, Round 9 architectural adversarial
scenarios, Round 10 narrow fixes, and Round 12 fail-closed coverage. No
skips, no xfail.

Core checklist items:
  1  — Duplicate Release Scan Prevention            (2 tests)
  2  — Teams Pending-Update Approval IDs            (2 tests)
  3  — Governed Canary Promotion                    (2 tests)
  4  — Graph Uses Promoted Version                  (1 test)
  5  — Rollback Restores Old Version                (1 test)
  6  — Path Confinement                             (3 tests)
  7  — Persistence Fail-Closed Behavior             (3 tests)
  9  — Typed Work Ledger Lifecycle Events           (2 tests)

Supplementary regression tests (items 7 & 9 depth):  6 tests

Round 9 — Architectural Stabilization (single source-of-truth,
component-level concurrency boundary, store invariant defense):
  - promotion×promotion / promotion×rollback / rollback×rollback exactly-one-succeeds (3 tests)
  - store rejects two active releases per component in one batch (1 test)
  - runtime reads committed artifact_path                       (1 test)
  - missing / corrupted active artifact fails closed            (2 tests)
  - persistence failure removes uncommitted staged artifact     (1 test)
  - different components run concurrently                       (1 test)

Round 10 — Narrow fixes following Codex re-audit:
  - update_id traversal/non-filename-safe input rejected before any IO (2 tests)
  - production pipeline assigns confined artifact_path on every release (1 test)
  - non-UTF-8 corrupted artifact surfaces ComponentArtifactError, not raw UnicodeError (1 test)

Round 12 — Narrow fixes following Codex re-audit:
  - monitor → pipeline end-to-end produces proposals_found == 1 AND
    updates_queued == 1 for a pr_review high_error_rate signal     (1 test)
  - graph fails closed when active artifact is missing              (1 test)
  - graph fails closed when active artifact is corrupted            (1 test)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from aria.evolution.update_manager.models import (
    ComponentType,
    ImpactLevel,
    UpdateRelease,
    UpdateStatus,
    compute_hash,
    utc_now,
)
from aria.evolution.update_manager.store import InMemoryUpdateStore, PersistenceError
from aria.evolution.update_manager.operations import UpdateManager, _confined_path


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_proposal(**kwargs):
    """Create a minimal valid EvolutionProposal with defaults that pass heuristic debate.

    Heuristic approve rule: risk_score <= 0.35 AND len(evidence) >= 2.
    """
    import uuid
    from aria.evolution.models import EvolutionProposal, EvolutionType
    defaults = dict(
        proposal_id=str(uuid.uuid4()),
        title="Test proposal",
        description="Test description",
        evolution_type=EvolutionType.prompt,
        target_component="pr_review_prompt",
        expected_gain="Better quality",
        evidence=["test-evidence-1", "test-evidence-2"],
        proposed_by="aria-agent",
        risk_score=0.1,
        proposed_at=utc_now(),
    )
    defaults.update(kwargs)
    return EvolutionProposal(**defaults)

def _make_release(
    update_id: str,
    component_name: str = "prompt_component",
    semantic_version: str = "1.0.0",
    status: UpdateStatus = UpdateStatus.awaiting_approval,
    content: str = "# Sample content",
    proposer: str = "aria-agent",
    approver: Optional[str] = None,
    artifact_path: Optional[str] = None,
) -> UpdateRelease:
    ch = compute_hash(content)
    return UpdateRelease(
        update_id=update_id,
        component_name=component_name,
        component_type=ComponentType.prompt,
        semantic_version=semantic_version,
        content_hash=ch,
        changelog=f"Update {semantic_version}",
        proposer=proposer,
        approver=approver,
        status=status,
        content=content,
        artifact_path=artifact_path,
        awaiting_approval_at=utc_now() if status == UpdateStatus.awaiting_approval else None,
        canary_at=utc_now() if status == UpdateStatus.canary else None,
        active_at=utc_now() if status == UpdateStatus.active else None,
    )


def _make_manager(store: InMemoryUpdateStore) -> UpdateManager:
    return UpdateManager(store=store)


# ═══════════════════════════════════════════════════════════════════════════════
# Item 1 — Duplicate Release Scan Prevention
# ═══════════════════════════════════════════════════════════════════════════════

def test_duplicate_scan_is_idempotent_for_active_release():
    """
    Rescanning an identical proposal/content hash returns the existing release
    unchanged.  The active release keeps its ID, version, lifecycle state, and
    approval metadata.  No second release is created.
    """
    from aria.evolution.pipeline import ProposalPipeline
    from aria.evolution.store import InMemoryProposalStore
    from aria.evolution.models import EvolutionProposal, EvolutionType

    proposal_store = InMemoryProposalStore()
    update_store = InMemoryUpdateStore()
    pipeline = ProposalPipeline(
        proposal_store=proposal_store,
        update_store=update_store,
        llm_enabled=False,
    )

    proposal = _make_proposal(
        title="Better prompt",
        description="Improved PR review prompt",
        expected_gain="Higher accuracy",
        evidence=["test_evidence_1", "test_evidence_2"],
    )

    # First run — should create a new release
    r1 = pipeline.run(proposal, current_version="1.0.0")
    assert r1.succeeded
    assert r1.update is not None
    uid = r1.update.update_id
    assert uid.endswith("-v1.0.0"), f"Expected update_id ending in -v1.0.0, got {uid}"

    # Manually promote the release to active to test immutability
    active = r1.update.model_copy(update={
        "status":    UpdateStatus.active,
        "approver":  "human-approver",
        "active_at": utc_now(),
    })
    update_store.save(active)

    store_count_before = len(update_store.list_all())

    # Second run with same proposal and version — must be idempotent
    r2 = pipeline.run(proposal, current_version="1.0.0")
    assert r2.succeeded
    assert r2.update is not None
    assert r2.update.update_id == uid, "Duplicate scan must return existing update_id"

    store_count_after = len(update_store.list_all())
    assert store_count_after == store_count_before, (
        "Duplicate scan must not create a second release"
    )

    # The existing active release is unchanged
    stored = update_store.get(uid)
    assert stored is not None
    assert stored.status == UpdateStatus.active, "Active release must remain active after rescan"
    assert stored.approver == "human-approver", "Approval metadata must be preserved"


def test_changed_proposal_creates_new_semver_without_overwrite():
    """
    A materially changed proposal submitted with a bumped version creates a new
    immutable release and leaves the previous release completely unchanged.
    """
    from aria.evolution.pipeline import ProposalPipeline
    from aria.evolution.store import InMemoryProposalStore
    from aria.evolution.models import EvolutionProposal, EvolutionType

    proposal_store = InMemoryProposalStore()
    update_store = InMemoryUpdateStore()
    pipeline = ProposalPipeline(
        proposal_store=proposal_store,
        update_store=update_store,
        llm_enabled=False,
    )

    proposal_v1 = _make_proposal(
        title="Prompt v1",
        description="First version",
        expected_gain="Better quality",
        evidence=["evidence-1", "evidence-2"],
    )

    r1 = pipeline.run(proposal_v1, current_version="1.0.0")
    assert r1.succeeded
    uid_v1 = r1.update.update_id

    # Manually mark v1 as active
    active_v1 = r1.update.model_copy(update={
        "status": UpdateStatus.active,
        "active_at": utc_now(),
    })
    update_store.save(active_v1)

    # Same proposal_id + same version + DIFFERENT content → must raise, not silently discard
    import uuid
    proposal_v1_changed = _make_proposal(
        proposal_id=proposal_v1.proposal_id,  # same identity
        title="Prompt v1 CHANGED",
        description="Changed content that produces a different hash",
        expected_gain="Better quality with change",
        evidence=["evidence-changed-1", "evidence-changed-2"],
    )
    with pytest.raises(ValueError, match="different content hash"):
        pipeline.run(proposal_v1_changed, current_version="1.0.0")

    # New proposal with bumped version — same content as v1, new semver
    r2 = pipeline.run(proposal_v1, current_version="1.1.0")
    assert r2.succeeded
    uid_v2 = r2.update.update_id

    assert uid_v2 != uid_v1, "Bumped version must produce a different update_id"
    assert uid_v2.endswith("-v1.1.0"), f"New update_id must encode the new version, got {uid_v2}"

    # v1 must be unchanged
    stored_v1 = update_store.get(uid_v1)
    assert stored_v1 is not None
    assert stored_v1.status == UpdateStatus.active, "v1 release must still be active"
    assert stored_v1.semantic_version == "1.0.0"

    # v2 is a new awaiting_approval release
    stored_v2 = update_store.get(uid_v2)
    assert stored_v2 is not None
    assert stored_v2.semantic_version == "1.1.0"


# ═══════════════════════════════════════════════════════════════════════════════
# Item 2 — Teams Pending-Update Approval IDs
# ═══════════════════════════════════════════════════════════════════════════════

def test_pending_update_card_actions_include_exact_update_id():
    """
    Each pending update's Approve/Reject actions must carry that update's exact
    update_id — never a list position, never the first update's ID.
    """
    from aria.integrations.teams_bot import _build_evolution_approval_card

    updates = [
        {
            "update_id":      "upd-aaaa1111-v1.0.0",
            "component":      "prompt_component",
            "version":        "1.0.0",
            "status":         "awaiting_approval",
            "changelog":      "First proposal",
            "proposer":       "aria-agent",
            "awaiting_since": "2026-01-01T00:00:00",
        },
        {
            "update_id":      "upd-bbbb2222-v2.0.0",
            "component":      "routing_component",
            "version":        "2.0.0",
            "status":         "awaiting_approval",
            "changelog":      "Second proposal",
            "proposer":       "aria-agent",
            "awaiting_since": "2026-01-02T00:00:00",
        },
    ]

    card = _build_evolution_approval_card(
        {"action": "list_pending", "updates": updates, "count": 2,
         "message": "2 updates pending."},
        task_id="task-123",
    )

    # Find all Action.Submit actions in the card (including inside Containers)
    all_submit_actions: list[dict] = []

    def collect_actions(body_items: list) -> None:
        for item in body_items:
            if item.get("type") == "ActionSet":
                for a in item.get("actions", []):
                    if a.get("type") == "Action.Submit":
                        all_submit_actions.append(a)
            elif item.get("type") == "Container":
                collect_actions(item.get("items", []))

    collect_actions(card.get("body", []))
    # Also check top-level actions
    for a in card.get("actions", []):
        if a.get("type") == "Action.Submit":
            all_submit_actions.append(a)

    # Must have at least 4 submit actions (2 per update × 2 updates)
    assert len(all_submit_actions) >= 4, (
        f"Expected ≥4 Action.Submit buttons, got {len(all_submit_actions)}"
    )

    update_id_1 = "upd-aaaa1111-v1.0.0"
    update_id_2 = "upd-bbbb2222-v2.0.0"

    ids_in_buttons = {
        a["data"].get("evolution_update_id") for a in all_submit_actions
    }
    assert update_id_1 in ids_in_buttons, (
        f"First update_id not found in card buttons. Found: {ids_in_buttons}"
    )
    assert update_id_2 in ids_in_buttons, (
        f"Second update_id not found in card buttons. Found: {ids_in_buttons}"
    )


def test_pending_update_approval_updates_only_selected_release():
    """
    Approving one release from a list of pending releases must transition only
    that release to canary. All other releases remain unchanged in the store.
    """
    store = InMemoryUpdateStore()
    mgr = _make_manager(store)

    r1 = _make_release("upd-first-v1.0.0",  proposer="alice", status=UpdateStatus.awaiting_approval)
    r2 = _make_release("upd-second-v1.0.0", proposer="alice", status=UpdateStatus.awaiting_approval)
    store.save(r1)
    store.save(r2)

    # Approve only the first release
    approved = mgr.approve_update("upd-first-v1.0.0", approver="bob")
    assert approved.status == UpdateStatus.canary
    assert approved.approver == "bob"

    # Second release must be unchanged
    r2_after = store.get("upd-second-v1.0.0")
    assert r2_after is not None
    assert r2_after.status == UpdateStatus.awaiting_approval, (
        "Second release must remain in awaiting_approval"
    )
    assert r2_after.approver is None


# ═══════════════════════════════════════════════════════════════════════════════
# Item 3 — Governed Canary Promotion
# ═══════════════════════════════════════════════════════════════════════════════

def test_unapproved_promotion_is_blocked():
    """
    Calling promote_canary on a release that is not in canary status raises
    UpdateStateError. Promotion cannot bypass the approval gate.
    """
    from aria.evolution.update_manager.models import UpdateStateError

    store = InMemoryUpdateStore()
    mgr = _make_manager(store)

    # Release is in awaiting_approval — not yet approved
    r = _make_release("upd-unapproved-v1.0.0", status=UpdateStatus.awaiting_approval)
    store.save(r)

    with pytest.raises(UpdateStateError):
        mgr.promote_canary("upd-unapproved-v1.0.0")


def test_approved_canary_health_pass_promotes_active():
    """
    Full governed flow: awaiting_approval → canary → active.
    promote_canary succeeds only after T4 approval and health checks pass.
    """
    store = InMemoryUpdateStore()
    mgr = _make_manager(store)

    content = "# Healthy prompt content"
    r = _make_release(
        "upd-healthy-v1.0.0",
        proposer="alice",
        status=UpdateStatus.awaiting_approval,
        content=content,
    )
    store.save(r)

    # Step 1: approve (requires different proposer)
    canary = mgr.approve_update("upd-healthy-v1.0.0", approver="bob")
    assert canary.status == UpdateStatus.canary

    # Step 2: promote to active
    active = mgr.promote_canary("upd-healthy-v1.0.0")
    assert active.status == UpdateStatus.active
    assert active.active_at is not None

    # Verify it's persisted
    stored = store.get("upd-healthy-v1.0.0")
    assert stored is not None
    assert stored.status == UpdateStatus.active


# ═══════════════════════════════════════════════════════════════════════════════
# Item 4 — Graph Uses Promoted Version
# ═══════════════════════════════════════════════════════════════════════════════

def test_graph_uses_promoted_component_version(tmp_path, monkeypatch):
    """
    End-to-end identity test (Round 11): a real ``EvolutionProposal`` for the
    registered ``pr_review_prompt`` component is run through
    ``ProposalPipeline`` → ``approve_update`` → ``promote_canary``; the
    resulting active release is read by ``component_loader.load`` from disk,
    and ``aria_graph.invoke()`` for a pr_review task reports the promoted
    ``component_hash`` and ``component_version``. The store is then reloaded
    from its JSONL persistence file into a fresh ``InMemoryUpdateStore``
    instance and the graph invocation is re-run to prove that the active
    identity survives a process restart.

    No ``_make_release`` shortcut is used — every state mutation goes through
    the real production code path.

    Asserts:
      - ``release.component_name == "pr_review_prompt"`` (registry-driven)
      - the versioned ``artifact_path`` file exists on disk
      - the on-disk bytes hash to the release's ``content_hash``
      - the graph reports the promoted version/hash before reload
      - the graph still reports the same promoted version/hash AFTER reloading
        the store from its persistence file
    """
    import aria.evolution.component_loader as cl
    from aria.evolution.models import EvolutionProposal, EvolutionType
    from aria.evolution.pipeline import ProposalPipeline
    from aria.evolution.update_manager import operations as ops
    from aria.graph import aria_graph

    # Point the operations module + loader at tmp_path so the deployment root
    # confinement check passes for artifacts the pipeline assigns.
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    # Persist the store on disk so we can reload it in a fresh instance and
    # prove restart-survival of the active component identity.
    persist_path = tmp_path / "update_releases.jsonl"
    store = InMemoryUpdateStore(persist_path=persist_path)
    monkeypatch.setattr(cl, "_store", store)

    # ── Real EvolutionProposal ─────────────────────────────────────────────
    proposal = EvolutionProposal(
        proposal_id="prop-graph-promoted-v2",
        title="Promoted PR review prompt",
        description="Replace stock prompt with media-tech-tuned variant.",
        evolution_type=EvolutionType.prompt,
        target_component="pr_review_prompt",
        expected_gain="Reduce false-positive risk flags by 20%.",
        evidence=["work_ledger:t-101", "eval:rubric-v3"],
        proposed_by="aria-agent",
        risk_score=0.1,
        proposed_at=utc_now(),
    )

    # ── Pipeline → awaiting_approval release ───────────────────────────────
    pipeline = ProposalPipeline(
        update_store=store,
        llm_enabled=False,
        debate_rounds=1,
    )
    pipeline_result = pipeline.run(proposal, current_version="2.0.0")
    assert pipeline_result.succeeded, (
        f"Pipeline did not produce a release: {pipeline_result.blocked_reason}"
    )
    release = pipeline_result.update
    assert release is not None
    # Identity contract #1: release targets the registered component.
    assert release.component_name == "pr_review_prompt", (
        f"Release must target pr_review_prompt; got {release.component_name!r}"
    )
    assert release.artifact_path is not None
    promoted_hash    = release.content_hash
    promoted_version = release.semantic_version  # "2.0.0"

    # ── Approval → canary ──────────────────────────────────────────────────
    mgr = UpdateManager(store=store, deployment_root=tmp_path)
    mgr.approve_update(release.update_id, approver="kunal")

    # ── Promotion → active ─────────────────────────────────────────────────
    active = mgr.promote_canary(release.update_id)
    assert active.status == UpdateStatus.active
    assert active.component_name == "pr_review_prompt"
    assert active.artifact_path is not None

    # Identity contract #2: versioned artifact exists on disk and hash matches.
    versioned = Path(active.artifact_path)
    assert versioned.exists(), (
        f"Versioned artifact must exist on disk after promotion: {versioned}"
    )
    on_disk_bytes = versioned.read_text(encoding="utf-8")
    assert compute_hash(on_disk_bytes) == promoted_hash, (
        "On-disk artifact bytes must hash to the release's content_hash."
    )

    # ── Graph invocation reports the promoted version/hash ─────────────────
    def _make_pr_state(task_id: str) -> dict:
        return {
            "task_id": task_id,
            "raw_input": "review the recommendation service PR",
            "task_type": "pr_review",
            "task_status": "pending",
            "routing_reason": "test",
            "steps_completed": ["intake", "router"],
            "skill_name": None,
            "skill_output": None,
            "response": None,
            "messages": [],
            "error": None,
        }

    output_after = json.loads(
        aria_graph.invoke(_make_pr_state("test-graph-promoted")).get("skill_output", "{}")
    )
    assert output_after.get("component_hash") == promoted_hash, (
        f"Graph must report promoted component_hash {promoted_hash[:12]}…, "
        f"got {output_after.get('component_hash')}"
    )
    assert output_after.get("component_version") == promoted_version, (
        f"Graph must report promoted component_version {promoted_version!r}, "
        f"got {output_after.get('component_version')}"
    )

    # ── Persisted store reload ─────────────────────────────────────────────
    # A fresh InMemoryUpdateStore loaded from the same persist_path must
    # still serve the promoted identity to the graph. This proves the active
    # release survives process restart through the JSONL persistence layer.
    reloaded = InMemoryUpdateStore(persist_path=persist_path)
    monkeypatch.setattr(cl, "_store", reloaded)

    reloaded_active = [
        u for u in reloaded.list_by_component("pr_review_prompt")
        if u.status == UpdateStatus.active
    ]
    assert len(reloaded_active) == 1, (
        f"Reloaded store must contain exactly 1 active pr_review_prompt release; "
        f"got {len(reloaded_active)}"
    )
    assert reloaded_active[0].update_id == release.update_id

    output_reload = json.loads(
        aria_graph.invoke(_make_pr_state("test-graph-promoted-reload"))
        .get("skill_output", "{}")
    )
    assert output_reload.get("component_hash") == promoted_hash, (
        "After store reload, graph must still report the promoted component_hash."
    )
    assert output_reload.get("component_version") == promoted_version, (
        "After store reload, graph must still report the promoted component_version."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Item 5 — Rollback Restores Old Version
# ═══════════════════════════════════════════════════════════════════════════════

def test_rollback_restores_artifact_and_graph_version(tmp_path: Path, monkeypatch):
    """
    rollback_update restores the old component bytes, updates the store so the
    old release is active, and a subsequent graph call reports the old hash.
    """
    import aria.evolution.component_loader as cl
    from aria.evolution.update_manager import operations as ops
    from aria.graph import aria_graph

    # Loader's confinement check uses the module-level deployment root —
    # point it at tmp_path so the test artifact passes confinement.
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    test_store = InMemoryUpdateStore()
    original_store = cl._store

    v1_content = "# Old PR Review Prompt v1"
    v2_content = "# New PR Review Prompt v2"
    v1_hash = compute_hash(v1_content)
    v2_hash = compute_hash(v2_content)

    artifact_file = tmp_path / "pr_review_prompt.txt"
    artifact_file.write_text(v2_content, encoding="utf-8")

    v1_release = _make_release(
        "upd-prprompt-v1.0.0",
        component_name="pr_review_prompt",
        semantic_version="1.0.0",
        status=UpdateStatus.superseded,
        content=v1_content,
        artifact_path=str(artifact_file),
    )
    v2_release = _make_release(
        "upd-prprompt-v2.0.0",
        component_name="pr_review_prompt",
        semantic_version="2.0.0",
        status=UpdateStatus.active,
        content=v2_content,
        artifact_path=str(artifact_file),
    )
    test_store.save(v1_release)
    test_store.save(v2_release)

    try:
        cl._store = test_store
        mgr = UpdateManager(store=test_store, deployment_root=tmp_path)

        # Roll back to v1
        restored = mgr.rollback_update("pr_review_prompt", "1.0.0")

        # Store reflects v1 as active
        assert restored.status == UpdateStatus.active
        assert restored.semantic_version == "1.0.0"

        # Active release's artifact_path holds v1 content (versioned artifact design)
        assert Path(restored.artifact_path).read_text(encoding="utf-8") == v1_content

        # v2 is marked rolled_back
        v2_after = test_store.get("upd-prprompt-v2.0.0")
        assert v2_after is not None
        assert v2_after.status == UpdateStatus.rolled_back

        # A new graph invocation uses the restored version
        state = {
            "task_id": "test-rollback-graph",
            "raw_input": "review the recommendation service PR after rollback",
            "task_type": "pr_review",
            "task_status": "pending",
            "routing_reason": "test",
            "steps_completed": ["intake", "router"],
            "skill_name": None,
            "skill_output": None,
            "response": None,
            "messages": [],
            "error": None,
        }
        result = aria_graph.invoke(state)
        output = json.loads(result.get("skill_output", "{}"))
        assert output.get("component_hash") == v1_hash, (
            f"After rollback, graph must use v1 hash {v1_hash[:12]}…, "
            f"got {output.get('component_hash')}"
        )
    finally:
        cl._store = original_store


# ═══════════════════════════════════════════════════════════════════════════════
# Item 6 — Path Confinement
# ═══════════════════════════════════════════════════════════════════════════════

def test_allowed_deployment_path_succeeds(tmp_path: Path):
    """
    A path that resolves inside the deployment root writes successfully.
    """
    from aria.evolution.update_manager.operations import _write_artifact_atomic

    target = tmp_path / "components" / "prompt.txt"
    _write_artifact_atomic(str(target), "hello world", deployment_root=tmp_path)
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello world"


def test_absolute_outside_deployment_root_rejected(tmp_path: Path):
    """
    An absolute path that resolves outside the deployment root raises ValueError
    before any filesystem operation.
    """
    from aria.evolution.update_manager.operations import _write_artifact_atomic

    outside = tmp_path.parent / "malicious.txt"
    with pytest.raises(ValueError, match="outside deployment root"):
        _write_artifact_atomic(str(outside), "evil", deployment_root=tmp_path)

    # No file should have been created
    assert not outside.exists()


def test_parent_traversal_rejected(tmp_path: Path):
    """
    A ``..`` traversal that resolves outside the deployment root raises ValueError.
    """
    from aria.evolution.update_manager.operations import _write_artifact_atomic
    import os

    # Build a path like <tmp_path>/a/../../malicious.txt
    traversal = str(tmp_path / "a" / ".." / ".." / "traversal.txt")
    with pytest.raises(ValueError, match="outside deployment root"):
        _write_artifact_atomic(traversal, "evil", deployment_root=tmp_path)

    # Verify no file escaped
    escaped = tmp_path.parent / "traversal.txt"
    assert not escaped.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# Item 7 — Persistence Fail-Closed Behavior
# ═══════════════════════════════════════════════════════════════════════════════

def test_persistence_failure_blocks_approval_without_state_change(tmp_path: Path):
    """
    When the store flush fails during approve_update, PersistenceError is raised
    and the release remains in awaiting_approval — unchanged in both memory and
    on-disk.
    """
    persist_file = tmp_path / "releases.jsonl"
    store = InMemoryUpdateStore(persist_path=persist_file)
    mgr = _make_manager(store)

    r = _make_release("upd-persist-test-v1.0.0", proposer="alice",
                       status=UpdateStatus.awaiting_approval)
    store.save(r)  # initial save succeeds

    assert persist_file.exists(), "Initial save should write to disk"

    with patch.object(store, "_flush", side_effect=OSError("disk full")):
        with pytest.raises(PersistenceError):
            mgr.approve_update("upd-persist-test-v1.0.0", approver="bob")

    # In-memory state must be unchanged
    still = store.get("upd-persist-test-v1.0.0")
    assert still is not None
    assert still.status == UpdateStatus.awaiting_approval, (
        "Approval must not advance in-memory state if flush fails"
    )

    # On-disk state must be unchanged (reload from file)
    store2 = InMemoryUpdateStore(persist_path=persist_file)
    on_disk = store2.get("upd-persist-test-v1.0.0")
    assert on_disk is not None
    assert on_disk.status == UpdateStatus.awaiting_approval


def test_persistence_failure_blocks_promotion_without_state_change(tmp_path: Path):
    """
    When the store flush fails during promote_canary, PersistenceError is raised
    and the release remains in canary status.
    """
    persist_file = tmp_path / "releases.jsonl"
    store = InMemoryUpdateStore(persist_path=persist_file)
    mgr = _make_manager(store)

    content = "# Canary content"
    r = _make_release("upd-canary-persist-v1.0.0", proposer="alice",
                       status=UpdateStatus.canary, content=content)
    r = r.model_copy(update={"approver": "bob", "canary_at": utc_now()})
    store.save(r)  # initial save succeeds

    with patch.object(store, "_flush", side_effect=OSError("disk full")):
        with pytest.raises(PersistenceError):
            mgr.promote_canary("upd-canary-persist-v1.0.0")

    still = store.get("upd-canary-persist-v1.0.0")
    assert still is not None
    assert still.status == UpdateStatus.canary, (
        "Promotion must not advance in-memory state if flush fails"
    )


def test_persistence_failure_blocks_rollback_without_state_change(tmp_path: Path):
    """
    When the store flush fails at the first save during rollback_update (marking
    active as rolled_back), PersistenceError is raised and the active release
    remains active.
    """
    persist_file = tmp_path / "releases.jsonl"
    store = InMemoryUpdateStore(persist_path=persist_file)
    mgr = _make_manager(store)

    v1_content = "# Version 1"
    v2_content = "# Version 2 (current)"

    v1 = _make_release("upd-v1-persist-v1.0.0", component_name="comp",
                        semantic_version="1.0.0",
                        status=UpdateStatus.superseded, content=v1_content)
    v2 = _make_release("upd-v2-persist-v2.0.0", component_name="comp",
                        semantic_version="2.0.0",
                        status=UpdateStatus.active, content=v2_content)
    store.save(v1)
    store.save(v2)  # both initial saves succeed

    with patch.object(store, "_flush", side_effect=OSError("disk full")):
        with pytest.raises(PersistenceError):
            mgr.rollback_update("comp", "1.0.0")

    # v2 must still be active — not rolled_back
    v2_after = store.get("upd-v2-persist-v2.0.0")
    assert v2_after is not None
    assert v2_after.status == UpdateStatus.active, (
        "Active release must remain active if rollback flush fails"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Item 9 — Typed Work Ledger Lifecycle Events
# ═══════════════════════════════════════════════════════════════════════════════

def test_evolution_lifecycle_emits_ordered_typed_ledger_events(tmp_path, monkeypatch):
    """
    The full success path (proposal → pipeline → approval → promotion) emits
    typed, ordered EvolutionLedgerEvents with matching correlation IDs.
    """
    from aria.evolution.pipeline import ProposalPipeline
    from aria.evolution.store import InMemoryProposalStore
    from aria.evolution.models import EvolutionProposal, EvolutionType
    from aria.evolution.update_manager import operations as ops
    from aria.work_ledger import EvolutionEventType, EvolutionLedgerEvent

    # Confine all deployment-artifact writes to tmp_path so the full suite never
    # pollutes apps/backend/deployments/ (Codex Finding 3). The pipeline reads
    # ops.DEPLOYMENT_ROOT to build artifact paths; UpdateManager writes/confines
    # promotion against its own deployment_root — both must be isolated.
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    proposal_store = InMemoryProposalStore()
    update_store = InMemoryUpdateStore()
    pipeline = ProposalPipeline(
        proposal_store=proposal_store,
        update_store=update_store,
        llm_enabled=False,
    )

    proposal = _make_proposal(
        title="Lifecycle test prompt",
        description="Test lifecycle events",
        expected_gain="Better quality",
        evidence=["evidence-lifecycle-1", "evidence-lifecycle-2"],
    )

    captured: list[EvolutionLedgerEvent] = []
    _cap = lambda e: captured.append(e)

    with patch("aria.work_ledger.log_evolution_event", side_effect=_cap), \
         patch("aria.evolution.pipeline.log_evolution_event", side_effect=_cap):

        result = pipeline.run(proposal, current_version="1.0.0")
        assert result.succeeded, f"Pipeline failed: {result.blocked_reason}"

    mgr = UpdateManager(store=update_store, deployment_root=tmp_path)

    # Approve the update — operations.py uses lazy import so aria.work_ledger patch is enough
    with patch("aria.work_ledger.log_evolution_event", side_effect=_cap):
        approved = mgr.approve_update(result.update.update_id, approver="human-approver")

    # Promote to active
    with patch("aria.work_ledger.log_evolution_event", side_effect=_cap):
        active = mgr.promote_canary(result.update.update_id)

    # ── Membership checks ─────────────────────────────────────────────────────
    event_types = [e.event_type for e in captured]

    for expected_type in [
        EvolutionEventType.proposal,
        EvolutionEventType.generation,
        EvolutionEventType.sandbox,
        EvolutionEventType.approval_request,
        EvolutionEventType.approval,
        EvolutionEventType.canary,
        EvolutionEventType.verification,
        EvolutionEventType.promotion,
        EvolutionEventType.activation,
    ]:
        assert expected_type in event_types, (
            f"Expected event type {expected_type.value!r} not found. "
            f"Got: {[e.value for e in event_types]}"
        )

    # ── Ordering check ────────────────────────────────────────────────────────
    # Pipeline events must come before approval which must come before promotion.
    # Use first-occurrence indices.
    idx = {et: next(i for i, e in enumerate(captured) if e.event_type == et)
           for et in event_types}

    # proposal < generation < sandbox < approval_request
    assert idx[EvolutionEventType.proposal] < idx[EvolutionEventType.generation], \
        "proposal must precede generation"
    assert idx[EvolutionEventType.generation] < idx[EvolutionEventType.sandbox], \
        "generation must precede sandbox"
    assert idx[EvolutionEventType.sandbox] < idx[EvolutionEventType.approval_request], \
        "sandbox must precede approval_request"

    # approval_request < approval < canary
    assert idx[EvolutionEventType.approval_request] < idx[EvolutionEventType.approval], \
        "approval_request must precede approval"
    assert idx[EvolutionEventType.approval] < idx[EvolutionEventType.canary], \
        "approval must precede canary"

    # canary < verification < promotion < activation
    assert idx[EvolutionEventType.canary] < idx[EvolutionEventType.verification], \
        "canary must precede verification"
    assert idx[EvolutionEventType.verification] < idx[EvolutionEventType.promotion], \
        "verification must precede promotion"
    assert idx[EvolutionEventType.promotion] < idx[EvolutionEventType.activation], \
        "promotion must precede activation"

    # ── Correlation fields ────────────────────────────────────────────────────
    for event in captured:
        corr = event.update_id or event.proposal_id or event.task_id
        assert corr, f"Event {event.event_type} has no correlation field"
        assert isinstance(event, EvolutionLedgerEvent)
        assert event.event_type in EvolutionEventType.__members__.values()


def test_failed_lifecycle_operation_emits_failed_event():
    """
    A rejected proposal emits a failure event with outcome="debate_rejected" or
    "sandbox_failed".  The failure event correlates to the proposal via task_id.
    """
    from aria.evolution.pipeline import ProposalPipeline
    from aria.evolution.store import InMemoryProposalStore
    from aria.evolution.models import EvolutionProposal, EvolutionType
    from aria.evolution.debate import DebateEngine
    from aria.work_ledger import EvolutionEventType, EvolutionLedgerEvent

    proposal_store = InMemoryProposalStore()
    update_store = InMemoryUpdateStore()

    # Force the debate to always reject
    class AlwaysRejectDebate(DebateEngine):
        def debate(self, proposal):
            from aria.evolution.debate import DebateResult
            from aria.evolution.models import DebateVerdict
            verdict = DebateVerdict(
                proposal_id=proposal.proposal_id,
                recommendation="reject",
                pro_arguments=[],
                con_arguments=["Always reject in test"],
                confidence=0.0,
                conditions=[],
                transcript=[],
                debated_at=utc_now(),
                rounds=1,
            )
            return DebateResult(verdict=verdict, used_llm=False)

    pipeline = ProposalPipeline(
        proposal_store=proposal_store,
        update_store=update_store,
        llm_enabled=False,
    )
    pipeline._debate = AlwaysRejectDebate(llm_enabled=False)

    proposal = _make_proposal(
        title="Doomed proposal",
        description="Will be rejected by debate",
        expected_gain="Nothing",
        evidence=["bad-evidence-1", "bad-evidence-2"],
    )

    captured: list[EvolutionLedgerEvent] = []
    _cap = lambda e: captured.append(e)

    with patch("aria.work_ledger.log_evolution_event", side_effect=_cap), \
         patch("aria.evolution.pipeline.log_evolution_event", side_effect=_cap):
        result = pipeline.run(proposal, current_version="1.0.0")

    assert not result.succeeded, "Pipeline should have been blocked"

    event_types = [e.event_type for e in captured]
    assert EvolutionEventType.failure in event_types, (
        f"failure event must be emitted for rejected proposal. "
        f"Got: {[e.value for e in event_types]}"
    )

    failure_events = [e for e in captured if e.event_type == EvolutionEventType.failure]
    assert len(failure_events) >= 1
    for fe in failure_events:
        assert fe.task_id == proposal.proposal_id, (
            "Failure event must correlate to the proposal via task_id"
        )
        assert fe.outcome is not None


def test_successful_rollback_emits_failure_typed_audit_event():
    """
    On a SUCCESSFUL rollback, rollback_update emits a failure-typed ledger event
    with outcome="rollback". This is intentional audit design: rollbacks are
    tracked as failure events so the Work Ledger can surface rollback frequency.
    This is the NOMINAL path — not an error case.
    """
    from aria.work_ledger import EvolutionEventType, EvolutionLedgerEvent

    store = InMemoryUpdateStore()
    mgr = _make_manager(store)

    v1 = _make_release(
        "upd-v1-rollback-evt",
        component_name="prompt_component",
        semantic_version="1.0.0",
        status=UpdateStatus.superseded,
        content="# v1 content",
    )
    v2 = _make_release(
        "upd-v2-rollback-evt",
        component_name="prompt_component",
        semantic_version="2.0.0",
        status=UpdateStatus.active,
        content="# v2 content",
    )
    store.save(v1)
    store.save(v2)

    captured: list[EvolutionLedgerEvent] = []

    with patch("aria.work_ledger.log_evolution_event",
               side_effect=lambda e: captured.append(e)):
        mgr.rollback_update("prompt_component", "1.0.0")

    event_types = [e.event_type for e in captured]
    assert EvolutionEventType.failure in event_types, (
        f"rollback_update must emit a failure event. Got: {[e.value for e in event_types]}"
    )

    rollback_events = [
        e for e in captured
        if e.event_type == EvolutionEventType.failure
        and (e.outcome or "").lower() == "rollback"
    ]
    assert len(rollback_events) >= 1, (
        "failure event for rollback must have outcome='rollback'"
    )
    assert rollback_events[0].component_name == "prompt_component"
    assert rollback_events[0].version == "1.0.0"


def test_promote_canary_hash_failure_emits_failure_event():
    """
    HashMismatchError during promote_canary emits a failure ledger event.
    Hash validation occurs before any write, so this specifically exercises
    the outer failure-event handler (not the inner artifact-restore handler).
    """
    from aria.work_ledger import EvolutionEventType, EvolutionLedgerEvent

    store = InMemoryUpdateStore()
    mgr = _make_manager(store)

    # Deliberately mismatched content hash — verify_hash() will return False
    bad = UpdateRelease(
        update_id="upd-bad-hash-promo",
        component_name="prompt_component",
        component_type=ComponentType.prompt,
        semantic_version="1.0.0",
        content_hash="deadbeef" * 8,   # wrong hash
        changelog="Bad hash.",
        proposer="aria-agent",
        status=UpdateStatus.canary,
        content="# Content that does not match the hash above",
        canary_at=utc_now(),
    )
    store.save(bad)

    captured: list[EvolutionLedgerEvent] = []

    from aria.evolution.update_manager.models import HashMismatchError
    with patch("aria.work_ledger.log_evolution_event", side_effect=lambda e: captured.append(e)):
        with pytest.raises(HashMismatchError):
            mgr.promote_canary("upd-bad-hash-promo")

    event_types = [e.event_type for e in captured]
    assert EvolutionEventType.failure in event_types, (
        f"failure event must be emitted on hash mismatch. "
        f"Got: {[e.value for e in event_types]}"
    )
    failure_events = [e for e in captured if e.event_type == EvolutionEventType.failure]
    assert any((e.outcome or "").lower() == "promotion_failed" for e in failure_events), (
        f"failure event must carry outcome='promotion_failed'. "
        f"Got outcomes: {[e.outcome for e in failure_events]}"
    )


def test_promote_canary_persistence_failure_emits_failure_event():
    """
    When save_batch raises PersistenceError during promote_canary, a failure
    ledger event with outcome='promotion_failed' is emitted before the exception
    propagates. The release stays in canary (no false-active state).
    """
    from aria.work_ledger import EvolutionEventType, EvolutionLedgerEvent
    from aria.evolution.update_manager.store import PersistenceError

    store = InMemoryUpdateStore()
    mgr = _make_manager(store)

    upd = _make_release(
        "upd-promo-persist-fail",
        component_name="prompt_component",
        semantic_version="1.0.0",
        status=UpdateStatus.canary,
        content="# Canary content",
    )
    store.save(upd)

    captured: list[EvolutionLedgerEvent] = []

    with patch("aria.work_ledger.log_evolution_event", side_effect=lambda e: captured.append(e)):
        with patch.object(store, "save_batch", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                mgr.promote_canary("upd-promo-persist-fail")

    event_types = [e.event_type for e in captured]
    assert EvolutionEventType.failure in event_types, (
        f"failure event must be emitted on promotion persistence failure. "
        f"Got: {[e.value for e in event_types]}"
    )

    failure_events = [e for e in captured if e.event_type == EvolutionEventType.failure]
    assert any((e.outcome or "").lower() == "promotion_failed" for e in failure_events), (
        f"failure event must carry outcome='promotion_failed'. "
        f"Got outcomes: {[e.outcome for e in failure_events]}"
    )

    # Release must remain in canary — not falsely promoted to active
    stored = store.get("upd-promo-persist-fail")
    assert stored is not None and stored.status == UpdateStatus.canary, (
        f"Release must stay in canary after failed promotion, got {stored}"
    )


def test_promote_canary_nonutf8_artifact_restored_on_save_batch_failure(tmp_path: Path):
    """
    Regression: the active artifact must not be lost when save_batch fails,
    even when it contains non-UTF-8 bytes.

    With the staging design promote_canary writes new content to a .next
    staging path rather than overwriting the active artifact.  If save_batch
    fails the staging file is deleted and the active artifact is never touched,
    so no read-back or restoration of the original bytes is needed.
    """
    from aria.evolution.update_manager.store import PersistenceError

    non_utf8_bytes = b"\xff\xfe" + "Legacy binary artifact".encode("utf-16-le")
    artifact_file = tmp_path / "legacy.bin"
    artifact_file.write_bytes(non_utf8_bytes)

    content = "# New UTF-8 prompt content"
    upd = _make_release(
        "upd-nonutf8-restore",
        component_name="prompt_component",
        semantic_version="1.0.0",
        status=UpdateStatus.canary,
        content=content,
        artifact_path=str(artifact_file),
    )
    store = InMemoryUpdateStore()
    store.save(upd)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    with patch.object(store, "save_batch", side_effect=PersistenceError("disk full")):
        with pytest.raises(PersistenceError):
            mgr.promote_canary("upd-nonutf8-restore")

    # Non-UTF-8 bytes must be restored exactly — not deleted
    assert artifact_file.exists(), "Non-UTF-8 artifact must not be deleted on save_batch failure"
    assert artifact_file.read_bytes() == non_utf8_bytes, (
        "Non-UTF-8 artifact must be restored to original bytes"
    )


def test_promote_canary_artifact_restored_on_save_batch_failure(tmp_path: Path):
    """
    When save_batch raises PersistenceError, the active artifact must still
    contain the pre-promotion content.

    With the staging design promote_canary writes new content to a .next path
    rather than overwriting the active artifact.  If save_batch fails the
    staging file is deleted and the active artifact is untouched — its
    pre-promotion content is preserved without any restoration step.
    """
    from aria.evolution.update_manager.store import PersistenceError

    old_content = "# Old prompt content"
    new_content = "# New promoted prompt content"

    artifact_file = tmp_path / "prompt.txt"
    artifact_file.write_text(old_content, encoding="utf-8")

    upd = _make_release(
        "upd-restore-artifact",
        component_name="prompt_component",
        semantic_version="1.0.0",
        status=UpdateStatus.canary,
        content=new_content,
        artifact_path=str(artifact_file),
    )
    store = InMemoryUpdateStore()
    store.save(upd)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    with patch.object(store, "save_batch", side_effect=PersistenceError("disk full")):
        with pytest.raises(PersistenceError):
            mgr.promote_canary("upd-restore-artifact")

    # Artifact must be restored to old content — not left with new content
    on_disk = artifact_file.read_text(encoding="utf-8")
    assert on_disk == old_content, (
        f"Artifact must be restored to old content after save_batch failure. "
        f"Got: {on_disk!r}"
    )
    # Store state must be unchanged
    stored = store.get("upd-restore-artifact")
    assert stored is not None and stored.status == UpdateStatus.canary


def test_rollback_persistence_error_leaves_no_partial_state():
    """
    When save_batch raises PersistenceError during rollback, the exception
    propagates to the caller and neither state transition (rolled_back or
    restored-active) is committed — the store remains at its pre-rollback state.

    This verifies that the atomic save_batch design prevents the partial-state
    bug where the old active release was marked rolled_back but no new active
    release was committed.
    """
    from aria.evolution.update_manager.store import PersistenceError

    store = InMemoryUpdateStore()
    mgr = _make_manager(store)

    v1 = _make_release(
        "upd-v1-persist-err",
        component_name="prompt_component",
        semantic_version="1.0.0",
        status=UpdateStatus.superseded,
        content="# v1 content",
    )
    v2 = _make_release(
        "upd-v2-persist-err",
        component_name="prompt_component",
        semantic_version="2.0.0",
        status=UpdateStatus.active,
        content="# v2 content",
    )
    store.save(v1)
    store.save(v2)

    with patch.object(store, "save_batch", side_effect=PersistenceError("simulated disk failure")):
        with pytest.raises(PersistenceError):
            mgr.rollback_update("prompt_component", "1.0.0")

    # Both records must remain at their pre-rollback state (no partial commit)
    v1_after = store.get("upd-v1-persist-err")
    v2_after = store.get("upd-v2-persist-err")
    assert v1_after is not None and v1_after.status == UpdateStatus.superseded, (
        f"v1 must still be superseded after failed rollback, got {v1_after}"
    )
    assert v2_after is not None and v2_after.status == UpdateStatus.active, (
        f"v2 must still be active after failed rollback, got {v2_after}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Round 9 — Architectural Stabilization Adversarial Tests
#
# These tests exercise the single source-of-truth + single concurrency
# boundary contract end-to-end. They are deterministic — no Sleep/Barrier
# timing races — using the component lock either manually held in-thread
# or pre-acquired before invoking the operation.
#
# Coverage:
#   - promotion vs promotion          (same component, lock blocks the loser)
#   - promotion vs rollback           (same component, lock blocks the loser)
#   - rollback vs rollback            (same component, lock blocks the loser)
#   - store rejects two active in one batch (invariant defense)
#   - runtime reads committed artifact_path (loader returns disk content)
#   - missing active artifact fails closed
#   - corrupted active artifact fails closed
#   - persistence failure removes uncommitted artifact
#   - different components run concurrently (lock scoped per component)
# ═══════════════════════════════════════════════════════════════════════════════

from aria.evolution.update_manager.models import (
    ConcurrentActivationError,
    MultipleActiveReleasesError,
)


def _make_canary_release(
    *, update_id: str, component_name: str, semantic_version: str,
    content: str, artifact_path: Path,
) -> UpdateRelease:
    """Build a canary-status UpdateRelease wired to a versioned artifact path."""
    return UpdateRelease(
        update_id=update_id,
        component_name=component_name,
        component_type=ComponentType.prompt,
        semantic_version=semantic_version,
        content_hash=compute_hash(content),
        changelog=f"{component_name} {semantic_version}",
        proposer="aria-agent",
        approver="kunal",
        status=UpdateStatus.canary,
        content=content,
        artifact_path=str(artifact_path),
        canary_at=utc_now(),
    )


def _versioned(artifact_path: Path, update_id: str) -> Path:
    """Compute the versioned (immutable) on-disk artifact path for an update."""
    return artifact_path.parent / (update_id + artifact_path.suffix)


def _assert_single_active_with_valid_artifact(
    store: InMemoryUpdateStore,
    component_name: str,
    expected_update_id: str,
    expected_content: str,
) -> UpdateRelease:
    """Shared assertions for every concurrency test."""
    actives = [u for u in store.list_all() if u.status == UpdateStatus.active]
    assert len(actives) == 1, (
        f"Exactly one active release expected; got {len(actives)}: "
        f"{[(u.update_id, u.semantic_version) for u in actives]}"
    )
    active = actives[0]
    assert active.update_id == expected_update_id
    assert active.component_name == component_name
    assert active.artifact_path, "active release must have artifact_path committed"
    on_disk_path = Path(active.artifact_path)
    assert on_disk_path.exists(), "committed artifact file must exist on disk"
    on_disk = on_disk_path.read_text(encoding="utf-8")
    assert on_disk == expected_content
    assert compute_hash(on_disk) == active.content_hash
    return active


# ── Concurrency: exactly-one-succeeds under contention ─────────────────────────
#
# Each test below models two competing operations targeting the same component
# lock. The "contender" runs while the component lock is held (representing the
# "other operation already in flight") — it MUST raise ConcurrentActivationError.
# The "winner" runs after the lock is released — it MUST succeed and leave the
# store with exactly one active release whose disk artifact and component_loader
# read both reflect the winner's version.
#
# Across the two attempts: exactly one succeeded; exactly one raised
# ConcurrentActivationError. This is what "exactly one of two competing
# operations succeeds" means when the lock is the correctness boundary.


def _run_contender(callable_op, *, exception_class=ConcurrentActivationError):
    """Run one operation expecting ConcurrentActivationError. Returns ('blocked', exc)."""
    try:
        callable_op()
    except exception_class as exc:
        return ("blocked", exc)
    raise AssertionError(
        f"Contender did not raise {exception_class.__name__}; the lock did not block it."
    )


def _run_winner(callable_op):
    """Run one operation expecting it to succeed. Returns ('success', result)."""
    return ("success", callable_op())


def _assert_two_attempts_one_succeeded_one_blocked(outcomes):
    successes = [o for o in outcomes if o[0] == "success"]
    blocked   = [o for o in outcomes if o[0] == "blocked"]
    assert len(outcomes) == 2, f"Expected 2 attempts; got {len(outcomes)}"
    assert len(successes) == 1, (
        f"Expected exactly 1 succeeded operation; got {len(successes)} successes."
    )
    assert len(blocked) == 1, (
        f"Expected exactly 1 blocked operation; got {len(blocked)} blocked."
    )
    assert isinstance(blocked[0][1], ConcurrentActivationError), (
        f"Blocked attempt must raise ConcurrentActivationError; got {type(blocked[0][1]).__name__}"
    )
    return successes[0][1]  # the successful result


def test_promotion_vs_promotion_same_component_exactly_one_succeeds(tmp_path, monkeypatch):
    artifact_path = tmp_path / "pr_review_prompt.txt"

    upd_a = _make_canary_release(
        update_id="upd-promo-a",
        component_name="pr_review_prompt",
        semantic_version="1.1.0",
        content="# v1.1.0 content",
        artifact_path=artifact_path,
    )
    upd_b = _make_canary_release(
        update_id="upd-promo-b",
        component_name="pr_review_prompt",
        semantic_version="1.2.0",
        content="# v1.2.0 content",
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(upd_a)
    store.save(upd_b)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    outcomes: list[tuple[str, object]] = []

    # Contender — promotion of B while lock is held (representing A's promotion
    # currently in flight). It must raise ConcurrentActivationError.
    assert store.acquire_component("pr_review_prompt") is True
    try:
        outcomes.append(_run_contender(lambda: mgr.promote_canary("upd-promo-b")))
    finally:
        store.release_component("pr_review_prompt")

    # Winner — promotion of A succeeds with no contention.
    outcomes.append(_run_winner(lambda: mgr.promote_canary("upd-promo-a")))

    winner = _assert_two_attempts_one_succeeded_one_blocked(outcomes)
    assert winner.status == UpdateStatus.active
    assert winner.update_id == "upd-promo-a"
    _assert_single_active_with_valid_artifact(
        store, "pr_review_prompt", "upd-promo-a", "# v1.1.0 content"
    )

    # Runtime authority: component_loader reads from the winner's artifact.
    import aria.evolution.component_loader as cl
    from aria.evolution.update_manager import operations as ops
    monkeypatch.setattr(cl, "_store", store)
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    content, content_hash, version = cl.load("pr_review_prompt", default="")
    assert content == "# v1.1.0 content"
    assert content_hash == winner.content_hash
    assert version == "1.1.0"


def test_promotion_vs_rollback_same_component_exactly_one_succeeds(tmp_path, monkeypatch):
    artifact_path = tmp_path / "prompt_component.txt"
    v1_content = "# v1.0.0 content"
    v2_content = "# v2.0.0 content"

    v1 = UpdateRelease(
        update_id="upd-v1",
        component_name="prompt_component",
        component_type=ComponentType.prompt,
        semantic_version="1.0.0",
        content_hash=compute_hash(v1_content),
        changelog="v1",
        proposer="aria",
        status=UpdateStatus.superseded,
        content=v1_content,
        artifact_path=str(artifact_path),
    )
    v2 = _make_canary_release(
        update_id="upd-v2",
        component_name="prompt_component",
        semantic_version="2.0.0",
        content=v2_content,
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(v1)
    store.save(v2)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    outcomes: list[tuple[str, object]] = []

    # Contender — rollback to v1 while lock is held. Must raise.
    assert store.acquire_component("prompt_component") is True
    try:
        outcomes.append(_run_contender(
            lambda: mgr.rollback_update("prompt_component", "1.0.0"),
        ))
    finally:
        store.release_component("prompt_component")

    # Winner — promotion of v2 succeeds with no contention.
    outcomes.append(_run_winner(lambda: mgr.promote_canary("upd-v2")))

    winner = _assert_two_attempts_one_succeeded_one_blocked(outcomes)
    assert winner.status == UpdateStatus.active
    assert winner.update_id == "upd-v2"
    _assert_single_active_with_valid_artifact(
        store, "prompt_component", "upd-v2", v2_content
    )

    import aria.evolution.component_loader as cl
    from aria.evolution.update_manager import operations as ops
    monkeypatch.setattr(cl, "_store", store)
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    content, content_hash, version = cl.load("prompt_component", default="")
    assert content == v2_content
    assert content_hash == winner.content_hash
    assert version == "2.0.0"


def test_rollback_vs_rollback_same_component_exactly_one_succeeds(tmp_path, monkeypatch):
    artifact_path = tmp_path / "prompt_component.txt"
    v1_content = "# v1.0.0"
    v2_content = "# v2.0.0"
    v3_content = "# v3.0.0"

    def _superseded(uid, ver, content):
        return UpdateRelease(
            update_id=uid,
            component_name="prompt_component",
            component_type=ComponentType.prompt,
            semantic_version=ver,
            content_hash=compute_hash(content),
            changelog=f"v{ver}",
            proposer="aria",
            status=UpdateStatus.superseded,
            content=content,
            artifact_path=str(artifact_path),
        )

    v1 = _superseded("upd-v1", "1.0.0", v1_content)
    v2 = _superseded("upd-v2", "2.0.0", v2_content)
    v3 = UpdateRelease(
        update_id="upd-v3",
        component_name="prompt_component",
        component_type=ComponentType.prompt,
        semantic_version="3.0.0",
        content_hash=compute_hash(v3_content),
        changelog="v3",
        proposer="aria",
        status=UpdateStatus.active,
        content=v3_content,
        artifact_path=str(artifact_path),
        active_at=utc_now(),
    )

    store = InMemoryUpdateStore()
    store.save(v1); store.save(v2); store.save(v3)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    outcomes: list[tuple[str, object]] = []

    # Contender — rollback to v1 while lock is held. Must raise.
    assert store.acquire_component("prompt_component") is True
    try:
        outcomes.append(_run_contender(
            lambda: mgr.rollback_update("prompt_component", "1.0.0"),
        ))
    finally:
        store.release_component("prompt_component")

    # Winner — rollback to v2 succeeds with no contention.
    outcomes.append(_run_winner(
        lambda: mgr.rollback_update("prompt_component", "2.0.0"),
    ))

    winner = _assert_two_attempts_one_succeeded_one_blocked(outcomes)
    assert winner.status == UpdateStatus.active
    assert winner.update_id == "upd-v2"
    _assert_single_active_with_valid_artifact(
        store, "prompt_component", "upd-v2", v2_content
    )

    import aria.evolution.component_loader as cl
    from aria.evolution.update_manager import operations as ops
    monkeypatch.setattr(cl, "_store", store)
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    content, content_hash, version = cl.load("prompt_component", default="")
    assert content == v2_content
    assert content_hash == winner.content_hash
    assert version == "2.0.0"


# ── Store invariant: two actives in one batch is rejected atomically ───────────

def test_store_rejects_two_active_releases_in_one_batch():
    store = InMemoryUpdateStore()

    c1 = "v1 content"
    c2 = "v2 content"
    rel_a = UpdateRelease(
        update_id="upd-batch-a",
        component_name="comp-x",
        component_type=ComponentType.prompt,
        semantic_version="1.0.0",
        content_hash=compute_hash(c1),
        changelog="v1",
        proposer="aria",
        status=UpdateStatus.active,
        content=c1,
        active_at=utc_now(),
    )
    rel_b = UpdateRelease(
        update_id="upd-batch-b",
        component_name="comp-x",
        component_type=ComponentType.prompt,
        semantic_version="2.0.0",
        content_hash=compute_hash(c2),
        changelog="v2",
        proposer="aria",
        status=UpdateStatus.active,
        content=c2,
        active_at=utc_now(),
    )

    with pytest.raises(MultipleActiveReleasesError):
        store.save_batch([rel_a, rel_b])

    # Atomic rejection — neither record is visible in the store.
    assert store.get("upd-batch-a") is None
    assert store.get("upd-batch-b") is None
    assert [u for u in store.list_all() if u.status == UpdateStatus.active] == []


# ── Runtime authority: loader returns the committed disk artifact ──────────────

def test_runtime_reads_committed_artifact_path(tmp_path, monkeypatch):
    artifact_path = tmp_path / "pr_review_prompt.txt"
    content = "# committed artifact content"

    upd = _make_canary_release(
        update_id="upd-runtime-read",
        component_name="pr_review_prompt",
        semantic_version="1.0.0",
        content=content,
        artifact_path=artifact_path,
    )

    store = InMemoryUpdateStore()
    store.save(upd)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    active = mgr.promote_canary("upd-runtime-read")

    # The active record now points at the versioned path under tmp_path.
    versioned = _versioned(artifact_path, "upd-runtime-read")
    assert Path(active.artifact_path) == versioned
    assert versioned.exists()
    assert versioned.read_text(encoding="utf-8") == content

    import aria.evolution.component_loader as cl
    from aria.evolution.update_manager import operations as ops
    monkeypatch.setattr(cl, "_store", store)
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    loaded_content, loaded_hash, loaded_version = cl.load(
        "pr_review_prompt", default=""
    )
    assert loaded_content == content
    assert loaded_hash == active.content_hash
    assert loaded_version == "1.0.0"


# ── Fail-closed: missing active artifact ───────────────────────────────────────

def test_missing_active_artifact_fails_closed(tmp_path, monkeypatch):
    from aria.evolution.component_loader import ComponentArtifactError

    artifact_path = tmp_path / "prompt.txt"
    content = "# prompt content"

    upd = _make_canary_release(
        update_id="upd-missing",
        component_name="prompt_component",
        semantic_version="1.0.0",
        content=content,
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(upd)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)
    mgr.promote_canary("upd-missing")

    # Delete the committed artifact — loader must refuse to fall back to content.
    versioned = _versioned(artifact_path, "upd-missing")
    assert versioned.exists()
    versioned.unlink()

    import aria.evolution.component_loader as cl
    from aria.evolution.update_manager import operations as ops
    monkeypatch.setattr(cl, "_store", store)
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    with pytest.raises(ComponentArtifactError):
        cl.load("prompt_component", default="fallback")


# ── Fail-closed: corrupted active artifact ─────────────────────────────────────

def test_corrupted_active_artifact_fails_closed(tmp_path, monkeypatch):
    from aria.evolution.component_loader import ComponentArtifactError

    artifact_path = tmp_path / "prompt.txt"
    content = "# original honest content"

    upd = _make_canary_release(
        update_id="upd-corrupt",
        component_name="prompt_component",
        semantic_version="1.0.0",
        content=content,
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(upd)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)
    mgr.promote_canary("upd-corrupt")

    # Overwrite the committed artifact with tampered content — hash will not match.
    versioned = _versioned(artifact_path, "upd-corrupt")
    versioned.write_text("# tampered content", encoding="utf-8")

    import aria.evolution.component_loader as cl
    from aria.evolution.update_manager import operations as ops
    monkeypatch.setattr(cl, "_store", store)
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    with pytest.raises(ComponentArtifactError):
        cl.load("prompt_component", default="fallback")


# ── Persistence failure removes the uncommitted staged artifact ────────────────

def test_persistence_failure_removes_uncommitted_artifact(tmp_path):
    artifact_path = tmp_path / "pr_review_prompt.txt"
    content = "# would-be active content"

    upd = _make_canary_release(
        update_id="upd-flush-fail",
        component_name="pr_review_prompt",
        semantic_version="1.0.0",
        content=content,
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(upd)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    versioned = _versioned(artifact_path, "upd-flush-fail")
    assert not versioned.exists()

    with patch.object(store, "save_batch", side_effect=PersistenceError("simulated")):
        with pytest.raises(PersistenceError):
            mgr.promote_canary("upd-flush-fail")

    # The staged artifact must have been deleted — store is unchanged AND disk
    # is unchanged. No half-written artifact, no half-applied state.
    assert not versioned.exists(), (
        "uncommitted staged artifact must be deleted when save_batch fails"
    )
    after = store.get("upd-flush-fail")
    assert after is not None and after.status == UpdateStatus.canary


# ── Different components run concurrently ──────────────────────────────────────

def test_different_components_run_concurrently(tmp_path, monkeypatch):
    artifact_a = tmp_path / "comp_a.txt"
    artifact_b = tmp_path / "comp_b.txt"

    upd_a = _make_canary_release(
        update_id="upd-comp-a",
        component_name="comp_a",
        semantic_version="1.0.0",
        content="# A content",
        artifact_path=artifact_a,
    )
    upd_b = _make_canary_release(
        update_id="upd-comp-b",
        component_name="comp_b",
        semantic_version="1.0.0",
        content="# B content",
        artifact_path=artifact_b,
    )
    store = InMemoryUpdateStore()
    store.save(upd_a)
    store.save(upd_b)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    # Hold the lock for comp_a — a promotion on comp_b must proceed unaffected.
    assert store.acquire_component("comp_a") is True
    try:
        active_b = mgr.promote_canary("upd-comp-b")
        assert active_b.status == UpdateStatus.active
        _assert_single_active_with_valid_artifact(
            store, "comp_b", "upd-comp-b", "# B content"
        )
    finally:
        store.release_component("comp_a")

    # And after release, comp_a promotes — both components end up active in
    # parallel because the lock is per-component, not global.
    active_a = mgr.promote_canary("upd-comp-a")
    assert active_a.status == UpdateStatus.active
    actives = sorted(
        [u for u in store.list_all() if u.status == UpdateStatus.active],
        key=lambda u: u.component_name,
    )
    assert [u.component_name for u in actives] == ["comp_a", "comp_b"]


# ═══════════════════════════════════════════════════════════════════════════════
# Round 10 — Narrow Fixes
#   - update_id is validated; derived versioned path is re-confined
#   - production pipeline assigns a confined deployment artifact_path
#   - component_loader treats UnicodeDecodeError as a closed-failure path
# ═══════════════════════════════════════════════════════════════════════════════


def test_update_id_with_traversal_segment_rejected_before_filesystem_touch(
    tmp_path, monkeypatch,
):
    """
    A hostile update_id containing a parent-traversal segment must be rejected
    by the filename-safety check BEFORE any exists()/read()/write() touches the
    filesystem. This is the input-validation layer of the defence-in-depth.
    """
    from aria.evolution.update_manager.operations import _versioned_artifact_path

    declared = tmp_path / "pr_review_prompt.txt"
    declared.write_text("# legitimate file", encoding="utf-8")

    # A traversal segment in update_id is rejected outright.
    with pytest.raises(ValueError):
        _versioned_artifact_path(
            str(declared),
            update_id="../escape",
            deployment_root=tmp_path,
            module_root=None,
        )
    # A separator character is rejected outright.
    with pytest.raises(ValueError):
        _versioned_artifact_path(
            str(declared),
            update_id="evil/sub",
            deployment_root=tmp_path,
            module_root=None,
        )
    # Empty update_id is rejected.
    with pytest.raises(ValueError):
        _versioned_artifact_path(
            str(declared),
            update_id="",
            deployment_root=tmp_path,
            module_root=None,
        )


def test_promote_canary_rejects_traversal_update_id_before_artifact_touch(
    tmp_path, monkeypatch,
):
    """
    End-to-end check: even if a release somehow held a malicious update_id,
    promote_canary refuses before reading or writing any artifact file.
    """
    artifact_path = tmp_path / "pr_review_prompt.txt"
    # A pre-existing outside-target file we want to verify is NOT touched.
    outside = tmp_path / "escape.txt"
    outside.write_text("# untouched", encoding="utf-8")

    upd = _make_canary_release(
        update_id="upd-good-id",   # valid id at construction time
        component_name="pr_review_prompt",
        semantic_version="1.0.0",
        content="# content",
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(upd)

    # Manually re-save with a hostile update_id — this models a corrupted
    # store entry getting past the constructor.
    hostile = upd.model_copy(update={"update_id": "../escape"})
    # Re-saving with a different update_id needs bypassing the model immutability
    # via dict assignment in the store. The store keys by update_id so we
    # insert a new record under the hostile key.
    with store._rw_lock:  # internal access for this targeted simulation
        store._store["../escape"] = hostile

    mgr = UpdateManager(store=store, deployment_root=tmp_path)

    with pytest.raises(ValueError):
        mgr.promote_canary("../escape")

    # The outside file must be untouched — fail-closed BEFORE any IO.
    assert outside.read_text(encoding="utf-8") == "# untouched"


def test_pipeline_assigns_confined_artifact_path_to_release(tmp_path, monkeypatch):
    """
    Production ProposalPipeline must set a deterministic, confined artifact_path
    on every UpdateRelease it produces — runtime authority cannot be bypassed
    by an in-memory-only release with artifact_path=None.
    """
    from aria.evolution.update_manager import operations as ops
    from aria.evolution.pipeline import ProposalPipeline
    from aria.evolution.models import EvolutionProposal, EvolutionType

    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    proposal = EvolutionProposal(
        proposal_id="prop-pipeline-artifact",
        title="Test proposal",
        description="Pipeline must assign a confined artifact_path.",
        evolution_type=EvolutionType.prompt,
        target_component="pr_review_prompt",
        expected_gain="Better PR review accuracy.",
        evidence=["work_ledger:t-1", "eval:rubric-v2"],
        proposed_by="aria-agent",
        risk_score=0.1,
        proposed_at=utc_now(),
    )

    store = InMemoryUpdateStore()
    pipeline = ProposalPipeline(update_store=store, llm_enabled=False, debate_rounds=1)
    result = pipeline.run(proposal, current_version="1.0.0")

    assert result.succeeded, f"pipeline did not produce release: {result.blocked_reason}"
    release = result.update
    assert release is not None
    assert release.artifact_path, "pipeline must assign artifact_path on the release"

    # The assigned path is under the configured deployment root.
    assigned = Path(release.artifact_path)
    assert tmp_path in assigned.resolve().parents, (
        f"artifact_path {assigned} must resolve under deployment root {tmp_path}"
    )
    # And confinement re-check on the assigned path succeeds.
    confined = _confined_path(str(assigned), root=tmp_path)
    assert confined == assigned.resolve()


def test_corrupted_binary_artifact_raises_typed_error_not_unicode_decode(
    tmp_path, monkeypatch,
):
    """
    A non-UTF-8 byte sequence at the active artifact path must surface
    as ComponentArtifactError, NOT a raw UnicodeDecodeError. This ensures
    consumers can rely on the documented typed exception for fail-closed
    handling regardless of corruption mode.
    """
    from aria.evolution.component_loader import ComponentArtifactError

    artifact_path = tmp_path / "prompt.txt"
    content = "# original content"
    upd = _make_canary_release(
        update_id="upd-binary-corrupt",
        component_name="prompt_component",
        semantic_version="1.0.0",
        content=content,
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(upd)
    mgr = UpdateManager(store=store, deployment_root=tmp_path)
    mgr.promote_canary("upd-binary-corrupt")

    # Overwrite the committed artifact with bytes that are not valid UTF-8.
    versioned = _versioned(artifact_path, "upd-binary-corrupt")
    versioned.write_bytes(b"\xff\xfe\xfd\x00binary garbage \xc3\x28")

    import aria.evolution.component_loader as cl
    from aria.evolution.update_manager import operations as ops
    monkeypatch.setattr(cl, "_store", store)
    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    with pytest.raises(ComponentArtifactError):
        cl.load("prompt_component", default="fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# Round 12 — Narrow Fixes
#   - Monitor → pipeline → updates_queued must actually produce a release
#   - pr_review_skill must NOT swallow ComponentArtifactError; the graph
#     must fail the task when the active artifact is missing or corrupted
# ═══════════════════════════════════════════════════════════════════════════════


def test_monitor_scan_produces_proposal_and_pipeline_queues_update(tmp_path, monkeypatch):
    """
    A high_error_rate signal on the ``pr_review`` task type must result in
    EXACTLY one proposal AND EXACTLY one queued UpdateRelease. The monitor
    and the pipeline have to agree on the registered component identity
    end-to-end; otherwise "scan for capability gaps" detects signals but
    queues nothing.

    Asserts ``proposals_found == 1`` and ``updates_queued == 1``.
    """
    from aria.evolution.update_manager import operations as ops
    from aria.evolution.monitor import EvolutionMonitor
    from aria.evolution.pipeline import ProposalPipeline

    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    # Build a small work-ledger that triggers ``high_error_rate`` for
    # task_type=pr_review (>20% error rate over ≥3 tasks).
    ledger_path = tmp_path / "work_ledger.jsonl"
    tasks = [
        {"task_type": "pr_review", "error": "timeout"} for _ in range(4)
    ] + [
        {"task_type": "pr_review", "error": None} for _ in range(1)
    ]
    with ledger_path.open("w", encoding="utf-8") as fh:
        for t in tasks:
            fh.write(json.dumps(t) + "\n")

    monitor = EvolutionMonitor(ledger_path=str(ledger_path))
    summary = monitor.scan()

    # Signal layer detected the gap
    signal_types = [s.signal_type for s in summary.signals]
    assert "high_error_rate" in signal_types

    # Proposal layer produced a deployable proposal
    proposals_found = len(summary.proposals_draft)
    assert proposals_found == 1, (
        f"Expected exactly 1 proposal from a pr_review high_error_rate signal; "
        f"got {proposals_found}. Monitor must map (task_type, signal_type) to a "
        "registered target_component."
    )
    proposal = summary.proposals_draft[0]
    assert proposal.target_component == "pr_review_prompt", (
        f"Proposal must target the registered pr_review_prompt component; "
        f"got {proposal.target_component!r}"
    )

    # Pipeline accepts the proposal and queues an UpdateRelease in the store
    update_store = InMemoryUpdateStore()
    pipeline = ProposalPipeline(
        update_store=update_store,
        llm_enabled=False,
        debate_rounds=1,
    )
    pipeline_result = pipeline.run(proposal, current_version="2.0.0")
    assert pipeline_result.succeeded, (
        f"Pipeline must queue an update for a monitor-produced proposal; "
        f"blocked_reason={pipeline_result.blocked_reason!r}"
    )

    updates_queued = len(update_store.list_all())
    assert updates_queued == 1, (
        f"Expected exactly 1 UpdateRelease queued in the store; got {updates_queued}."
    )
    queued = update_store.list_all()[0]
    assert queued.component_name == "pr_review_prompt"
    assert queued.status == UpdateStatus.awaiting_approval


def test_graph_fails_when_active_artifact_is_missing(tmp_path, monkeypatch):
    """
    pr_review_skill must NOT swallow ``ComponentArtifactError``. If an active
    release exists for ``pr_review_prompt`` but the on-disk artifact is
    missing, invoking the graph for a pr_review task MUST fail closed — the
    graph completing on the hardcoded fallback prompt would defeat the
    runtime artifact-authority contract.
    """
    import aria.evolution.component_loader as cl
    from aria.evolution.component_loader import ComponentArtifactError
    from aria.evolution.update_manager import operations as ops
    from aria.graph import aria_graph

    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    artifact_path = tmp_path / "prompts" / "pr_review_prompt.txt"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    content = "# active prompt"

    upd = _make_canary_release(
        update_id="upd-fail-closed",
        component_name="pr_review_prompt",
        semantic_version="2.0.0",
        content=content,
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(upd)
    monkeypatch.setattr(cl, "_store", store)

    mgr = UpdateManager(store=store, deployment_root=tmp_path)
    active = mgr.promote_canary("upd-fail-closed")
    versioned = Path(active.artifact_path)
    assert versioned.exists()

    # Delete the committed artifact — the store still says an active release
    # exists, but the runtime authority on disk is gone.
    versioned.unlink()

    state = {
        "task_id": "test-fail-closed-missing",
        "raw_input": "review the recommendation service PR",
        "task_type": "pr_review",
        "task_status": "pending",
        "routing_reason": "test",
        "steps_completed": ["intake", "router"],
        "skill_name": None,
        "skill_output": None,
        "response": None,
        "messages": [],
        "error": None,
    }
    with pytest.raises(ComponentArtifactError):
        aria_graph.invoke(state)


def test_graph_fails_when_active_artifact_is_corrupted(tmp_path, monkeypatch):
    """
    Same fail-closed contract for hash-mismatched artifacts: if the on-disk
    bytes no longer hash to the active release's content_hash, the graph
    must fail rather than fall back to the hardcoded prompt.
    """
    import aria.evolution.component_loader as cl
    from aria.evolution.component_loader import ComponentArtifactError
    from aria.evolution.update_manager import operations as ops
    from aria.graph import aria_graph

    monkeypatch.setattr(ops, "DEPLOYMENT_ROOT", tmp_path)

    artifact_path = tmp_path / "prompts" / "pr_review_prompt.txt"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    content = "# honest active content"

    upd = _make_canary_release(
        update_id="upd-fail-closed-corrupt",
        component_name="pr_review_prompt",
        semantic_version="2.0.0",
        content=content,
        artifact_path=artifact_path,
    )
    store = InMemoryUpdateStore()
    store.save(upd)
    monkeypatch.setattr(cl, "_store", store)

    mgr = UpdateManager(store=store, deployment_root=tmp_path)
    active = mgr.promote_canary("upd-fail-closed-corrupt")

    # Tamper with the committed artifact so its hash no longer matches.
    versioned = Path(active.artifact_path)
    versioned.write_text("# tampered prompt", encoding="utf-8")

    state = {
        "task_id": "test-fail-closed-corrupt",
        "raw_input": "review the recommendation service PR",
        "task_type": "pr_review",
        "task_status": "pending",
        "routing_reason": "test",
        "steps_completed": ["intake", "router"],
        "skill_name": None,
        "skill_output": None,
        "response": None,
        "messages": [],
        "error": None,
    }
    with pytest.raises(ComponentArtifactError):
        aria_graph.invoke(state)
