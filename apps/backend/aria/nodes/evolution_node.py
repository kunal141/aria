"""
Evolution Node — Week 28

Handles task_type="evolution" requests in the ARIA graph.

Supported intents (parsed from raw_input):
  scan / capability gaps   → run EvolutionMonitor + pipeline on top proposals
  pending / show proposals → list pending UpdateReleases
  evaluate proposal <id>   → run pipeline on a specific EvolutionProposal
  compare update <id>      → show version diff + changelog
  rollback component <n>   → rollback component to previous version

All ARIA governance rules apply:
  - ARIA may only PROPOSE updates, not activate them autonomously.
  - Activation (canary → active) requires human T4 approval.
  - Constitutional rules are checked before any update is queued.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from aria.evolution.models import ProposalStatus
from aria.evolution.monitor import EvolutionMonitor
from aria.evolution.pipeline import ProposalPipeline
from aria.evolution.update_manager.models import (
    UpdateRelease,
    UpdateStatus,
    utc_now,
)
from aria.evolution.update_manager.operations import UpdateManager
from aria.evolution.update_manager.store import InMemoryUpdateStore
from aria.evolution.store import InMemoryProposalStore

# ── Module-level singletons ────────────────────────────────────────────────────
# update_releases.jsonl lives next to work_ledger.jsonl in the backend root.
_UPDATE_RELEASES_PATH = Path(__file__).parent.parent.parent / "update_releases.jsonl"

_proposal_store = InMemoryProposalStore()
_update_store   = InMemoryUpdateStore(persist_path=_UPDATE_RELEASES_PATH)
_update_manager = UpdateManager(store=_update_store)


def evolution_node(state: dict) -> dict:
    """
    Route evolution intent from raw_input to the appropriate handler.
    Returns skill_output as JSON-serialisable dict for the respond node.
    """
    raw = (state.get("raw_input") or "").lower()

    try:
        if _matches(raw, ["scan", "capability gap", "capability gap", "discover", "find gaps"]):
            result = _handle_scan(state)
        elif _matches(raw, ["pending", "show proposal", "list proposal", "self-improvement"]):
            result = _handle_list_pending()
        elif _matches(raw, ["evaluate proposal", "run evaluation", "evaluate prop"]):
            result = _handle_evaluate_proposal(raw, state)
        elif _matches(raw, ["compare update", "show diff", "compare version"]):
            result = _handle_compare_update(raw)
        elif _matches(raw, ["rollback component", "rollback ", "revert component"]):
            result = _handle_rollback(raw)
        else:
            result = _handle_list_pending()

        return {
            "skill_name":        "evolution",
            "skill_output":      json.dumps(result, default=str),
            "task_status":       "executing",
            "steps_completed":   state.get("steps_completed", []) + ["evolution_node"],
        }
    except Exception as exc:
        return {
            "skill_name":    "evolution",
            "skill_output":  json.dumps({"error": str(exc)}),
            "task_status":   "executing",
            "error":         str(exc),
            "steps_completed": state.get("steps_completed", []) + ["evolution_node"],
        }


# ── Intent handlers ────────────────────────────────────────────────────────────

def _handle_scan(state: dict) -> dict:
    """Run monitor scan → pipeline first 3 approved proposals."""
    ledger_path = state.get("ledger_path")   # optional override for tests
    monitor = EvolutionMonitor(ledger_path=ledger_path)
    summary = monitor.scan()

    pipeline = ProposalPipeline(
        proposal_store=_proposal_store,
        update_store=_update_store,
        llm_enabled=False,
    )

    updates_queued: list[str] = []
    blocked: list[str] = []

    for proposal in summary.ranked_proposals()[:3]:
        result = pipeline.run(proposal)
        if result.succeeded and result.update:
            updates_queued.append(result.update.update_id)
        else:
            blocked.append(result.blocked_reason or "unknown")

    return {
        "action":           "scan",
        "scanned_tasks":    summary.scanned_tasks,
        "signals_detected": len(summary.signals),
        "proposals_found":  len(summary.proposals_draft),
        "updates_queued":   updates_queued,
        "blocked":          blocked,
        "message": (
            f"Scanned {summary.scanned_tasks} work ledger entries. "
            f"Detected {len(summary.signals)} signal(s). "
            f"Queued {len(updates_queued)} update(s) for T4 approval."
            if summary.scanned_tasks > 0
            else "Work ledger is empty or not configured. No signals detected."
        ),
    }


def _handle_list_pending() -> dict:
    pending = _update_manager.list_pending_updates()
    items = [
        {
            "update_id":      u.update_id,
            "component":      u.component_name,
            "version":        u.semantic_version,
            "status":         u.status.value,
            "changelog":      u.changelog[:120],
            "proposer":       u.proposer,
            "awaiting_since": u.awaiting_approval_at or u.evaluated_at or "",
        }
        for u in pending
    ]
    return {
        "action":        "list_pending",
        "count":         len(items),
        "updates":       items,
        "message": (
            f"{len(items)} update(s) pending human review."
            if items
            else "No updates are currently pending approval."
        ),
    }


def _handle_evaluate_proposal(raw: str, state: dict) -> dict:
    # Try to extract proposal ID from raw input
    match = re.search(r"(prop[-_][a-zA-Z0-9_\-]+|[a-z0-9]{8,})", raw)
    proposal_id = match.group(1) if match else None

    if not proposal_id:
        return {"action": "evaluate_proposal", "error": "Could not extract proposal ID from input."}

    proposal = _proposal_store.get(proposal_id)
    if proposal is None:
        return {"action": "evaluate_proposal", "error": f"Proposal {proposal_id!r} not found."}

    pipeline = ProposalPipeline(
        proposal_store=_proposal_store,
        update_store=_update_store,
        llm_enabled=False,
    )
    result = pipeline.run(proposal)

    return {
        "action":          "evaluate_proposal",
        "proposal_id":     proposal_id,
        "proposal_status": result.proposal.status.value,
        "update_id":       result.update.update_id if result.update else None,
        "succeeded":       result.succeeded,
        "blocked_reason":  result.blocked_reason,
        "message": (
            f"Proposal {proposal_id!r} passed debate + sandbox. "
            f"Update {result.update.update_id!r} queued for T4 approval."
            if result.succeeded
            else f"Proposal {proposal_id!r} was blocked: {result.blocked_reason}"
        ),
    }


def _handle_compare_update(raw: str) -> dict:
    match = re.search(r"(upd[-_][a-zA-Z0-9_\-]+|[a-z0-9]{8,})", raw)
    update_id = match.group(1) if match else None

    if not update_id:
        return {"action": "compare_update", "error": "Could not extract update ID from input."}

    try:
        comparison = _update_manager.compare_update(update_id)
        return {
            "action":           "compare_update",
            "update_id":        update_id,
            "component":        comparison.component_name,
            "from_version":     comparison.previous_version,
            "to_version":       comparison.proposed_version,
            "changelog":        comparison.changelog,
            "diff_lines":       comparison.diff_lines[:50],
            "security_impact":  comparison.security_impact.value,
            "privacy_impact":   comparison.privacy_impact.value,
            "canary_plan":      comparison.canary_plan,
            "rollback_target":  comparison.rollback_target,
            "evidence_refs":    comparison.evidence_refs[:5],
        }
    except KeyError as exc:
        return {"action": "compare_update", "error": str(exc)}


def _handle_rollback(raw: str) -> dict:
    # Expected: "rollback component <name> to <version>" or "rollback <name> <version>"
    match = re.search(r"(?:rollback\s+(?:component\s+)?)([\w\-_]+)\s+(?:to\s+)?(\d+\.\d+\.\d+)", raw)
    if not match:
        return {
            "action": "rollback",
            "error": "Could not parse component name and version. "
                     "Use: 'rollback component <name> to <version>'",
        }

    component = match.group(1)
    version   = match.group(2)

    try:
        restored = _update_manager.rollback_update(component, version)
        return {
            "action":    "rollback",
            "component": component,
            "restored_to": version,
            "update_id": restored.update_id,
            "message":   f"Component '{component}' successfully rolled back to version {version}.",
        }
    except (KeyError, ValueError) as exc:
        return {"action": "rollback", "error": str(exc)}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _matches(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


# ── Expose the module-level stores for testing ─────────────────────────────────

def get_update_manager() -> UpdateManager:
    return _update_manager


def get_update_store() -> InMemoryUpdateStore:
    return _update_store


def get_proposal_store() -> InMemoryProposalStore:
    return _proposal_store
