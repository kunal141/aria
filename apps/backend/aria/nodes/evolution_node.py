"""
Evolution Node — Week 28

Handles task_type="evolution" requests in the ARIA graph.

Supported intents (parsed from raw_input):
  scan / capability gaps        → run EvolutionMonitor + pipeline on top proposals
  pending / show proposals      → list pending UpdateReleases
  evaluate proposal <id>        → run pipeline on a specific EvolutionProposal
  compare update <id>           → show version diff + changelog
  promote canary <id>           → promote canary release to active
  rollback component <n>        → rollback component to previous version

All ARIA governance rules apply:
  - ARIA may only PROPOSE updates, not activate them autonomously.
  - Activation (canary → active) requires human T4 approval.
  - Constitutional rules are checked before any update is queued.
"""
from __future__ import annotations

import json
import re

from aria.evolution.models import ProposalStatus
from aria.evolution.monitor import EvolutionMonitor
from aria.evolution.pipeline import ProposalPipeline
from aria.evolution.update_manager.models import (
    UpdateRelease,
    UpdateStatus,
    utc_now,
)
from aria.evolution.update_manager.operations import UpdateManager
from aria.evolution.store import InMemoryProposalStore

# ── Module-level proposal store (not shared with component_loader) ────────────
_proposal_store = InMemoryProposalStore()


def _get_cl():
    """Lazy import to avoid circular imports at module load time."""
    import aria.evolution.component_loader as cl
    return cl


def _get_update_store():
    return _get_cl().get_store()


def _get_update_manager():
    return UpdateManager(store=_get_update_store())


def evolution_node(state: dict) -> dict:
    """
    Route evolution intent from raw_input to the appropriate handler.
    Returns skill_output as JSON-serialisable dict for the respond node.
    """
    raw = (state.get("raw_input") or "").lower()

    try:
        if _matches(raw, ["scan", "capability gap", "discover", "find gaps"]):
            # State-changing: the scan pipeline persists UpdateReleases to the
            # store. Gated by the caller's execution policy — a read-only/dry-run
            # surface (e.g. local chat) gets a blocked result and the pipeline
            # never runs, so nothing is persisted.
            result = (
                _handle_scan(state)
                if _mutations_allowed(state)
                else _mutation_blocked("scan", state)
            )
        elif _matches(raw, ["promote canary", "activate canary", "promote update"]):
            # Mutating action — gated by the caller's execution policy. When the
            # surface is read-only/dry-run (e.g. local chat), this returns a
            # blocked result WITHOUT touching real components.
            result = (
                _handle_promote_canary(raw)
                if _mutations_allowed(state)
                else _mutation_blocked("promote_canary", state)
            )
        elif _matches(raw, ["pending", "show proposal", "list proposal", "self-improvement"]):
            result = _handle_list_pending()
        elif _matches(raw, ["evaluate proposal", "run evaluation", "evaluate prop"]):
            # State-changing: evaluating a proposal runs the pipeline, which
            # persists an UpdateRelease. Gated like scan/promote/rollback.
            result = (
                _handle_evaluate_proposal(raw, state)
                if _mutations_allowed(state)
                else _mutation_blocked("evaluate_proposal", state)
            )
        elif _matches(raw, ["compare update", "show diff", "compare version"]):
            result = _handle_compare_update(raw)
        elif _matches(raw, ["rollback component", "rollback ", "revert component"]):
            # Mutating action — gated by the caller's execution policy (see above).
            result = (
                _handle_rollback(raw)
                if _mutations_allowed(state)
                else _mutation_blocked("rollback", state)
            )
        else:
            result = _handle_list_pending()

        return {
            "skill_name":        "evolution",
            "skill_output":      json.dumps(result, default=str),
            "task_status":       "executing",
            "steps_completed":   state.get("steps_completed", []) + ["evolution_node"],
        }
    except Exception as exc:
        # Never embed raw exception text — it can carry secrets (e.g. a provider
        # error echoing an API key/password). Surface only a redacted, typed
        # envelope so nothing sensitive reaches skill_output / response / error.
        safe = _safe_error(exc)
        return {
            "skill_name":      "evolution",
            "skill_output":    json.dumps(safe),
            "task_status":     "executing",
            "error":           f"{safe['error_type']}: details redacted",
            "steps_completed": state.get("steps_completed", []) + ["evolution_node"],
        }


# ── Intent handlers ────────────────────────────────────────────────────────────

def _handle_scan(state: dict) -> dict:
    """Run monitor scan → pipeline first 3 approved proposals."""
    ledger_path = state.get("ledger_path")
    monitor = EvolutionMonitor(ledger_path=ledger_path)
    summary = monitor.scan()

    pipeline = ProposalPipeline(
        proposal_store=_proposal_store,
        update_store=_get_update_store(),
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
    mgr = _get_update_manager()
    pending = mgr.list_pending_updates()
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
    match = re.search(r"(prop[-_][a-zA-Z0-9_\-]+|[a-z0-9]{8,})", raw)
    proposal_id = match.group(1) if match else None

    if not proposal_id:
        return {"action": "evaluate_proposal", "error": "Could not extract proposal ID from input."}

    proposal = _proposal_store.get(proposal_id)
    if proposal is None:
        return {"action": "evaluate_proposal", "error": f"Proposal {proposal_id!r} not found."}

    pipeline = ProposalPipeline(
        proposal_store=_proposal_store,
        update_store=_get_update_store(),
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
        mgr = _get_update_manager()
        comparison = mgr.compare_update(update_id)
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


def _handle_promote_canary(raw: str) -> dict:
    """Promote a canary release to active (requires prior T4 approval)."""
    match = re.search(r"(upd[-_][a-zA-Z0-9_\-\.]+)", raw)
    update_id = match.group(1) if match else None

    if not update_id:
        return {
            "action": "promote_canary",
            "error": (
                "Could not extract update ID. "
                "Use: 'promote canary upd-xxxx-v1.0.0'"
            ),
        }

    try:
        mgr = _get_update_manager()
        promoted = mgr.promote_canary(update_id)
        return {
            "action":    "promote_canary",
            "update_id": promoted.update_id,
            "component": promoted.component_name,
            "version":   promoted.semantic_version,
            "status":    promoted.status.value,
            "message":   (
                f"Update {update_id!r} promoted from canary to active. "
                f"Component '{promoted.component_name}' v{promoted.semantic_version} is now active."
            ),
        }
    except (KeyError, ValueError, RuntimeError) as exc:
        return {"action": "promote_canary", "error": str(exc)}


def _handle_rollback(raw: str) -> dict:
    match = re.search(
        r"(?:rollback\s+(?:component\s+)?)([\w\-_]+)\s+(?:to\s+)?(\d+\.\d+\.\d+)", raw
    )
    if not match:
        return {
            "action": "rollback",
            "error": "Could not parse component name and version. "
                     "Use: 'rollback component <name> to <version>'",
        }

    component = match.group(1)
    version   = match.group(2)

    try:
        mgr = _get_update_manager()
        restored = mgr.rollback_update(component, version)
        return {
            "action":      "rollback",
            "component":   component,
            "restored_to": version,
            "update_id":   restored.update_id,
            "message":     f"Component '{component}' successfully rolled back to version {version}.",
        }
    except (KeyError, ValueError) as exc:
        return {"action": "rollback", "error": str(exc)}


# ── Surface execution policy (safe-chat) ────────────────────────────────────────

def _mutations_allowed(state: dict) -> bool:
    """Whether mutating evolution actions (promote/rollback) may execute.

    This is a structured policy check, NOT a keyword denylist. A caller opts
    OUT of mutations by declaring a read-only/dry-run execution policy on the
    state envelope:
      - allow_mutations=False        → deny
      - execution_mode in {dry_run, read_only} → deny
    Absence of both → default-allow, so the normal governed graph (and every
    existing test that passes no policy) keeps its prior behaviour.
    """
    if state.get("allow_mutations") is False:
        return False
    if state.get("execution_mode") in ("dry_run", "read_only"):
        return False
    return True


def _mutation_blocked(action: str, state: dict) -> dict:
    """Result returned when a state-changing action is blocked by surface policy.

    No pipeline / UpdateManager call is made — nothing is scanned-into-the-store,
    evaluated-into-a-release, promoted, restored, or otherwise mutated. The user
    can still ASK about evolution; this is the safe dry-run answer.
    """
    surface = state.get("surface") or "this surface"
    pretty = action.replace("_", " ")
    return {
        "action":   action,
        "blocked":  True,
        "dry_run":  True,
        "surface":  state.get("surface"),
        "message": (
            f"'{pretty}' is a state-changing evolution action and is blocked "
            f"from {surface} (read-only / dry-run). It would persist or activate "
            f"runtime components, which requires the governed T4 approval path — "
            f"not a local chat surface. No evolution state was modified."
        ),
    }


def _safe_error(exc: Exception) -> dict:
    """Redacted error envelope for internally-caught exceptions.

    Raw exception text can carry secrets (e.g. a provider error echoing an API
    key/password). We surface only the exception class name plus a fixed
    'details redacted' note — never ``str(exc)`` — so nothing sensitive reaches
    skill_output / response / error, nor the chat REPL's display layer.
    """
    return {
        "action":     "error",
        "error":      "internal_error",
        "error_type": type(exc).__name__,
        "detail":     "details redacted",
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _matches(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


# ── Expose the module-level stores for testing ─────────────────────────────────

def get_update_manager() -> UpdateManager:
    return _get_update_manager()


def get_update_store() -> InMemoryUpdateStore:
    return _get_update_store()


def get_proposal_store() -> InMemoryProposalStore:
    return _proposal_store


# Avoid name errors from prior direct import
from aria.evolution.update_manager.store import InMemoryUpdateStore  # noqa: E402
