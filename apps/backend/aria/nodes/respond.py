"""
respond.py — Week 26 (Platform Intelligence gate added)

Evidence gate contract:
  - kpi and ci_cd responses require platform_evidence in state.
  - If platform_evidence is absent or is_safe_to_surface=False → response is withheld.
  - Stale-but-supported evidence surfaces with a citation footer showing staleness flags.
  - All other task types pass through without the gate (pr_review, qa, jira, etc.).

The gate lives here, not in skill nodes, because the surface presentation decision
belongs to the output layer — not to the execution layer.
"""
import json as _json
from typing import Optional

from aria.ledger.exceptions import LedgerPersistenceError
from aria.state import ARIAState
from aria.work_ledger import log_task
from aria.artifact_engine import render_artifact, render_artifact_with_citations

_LABELS = {
    "pr_review":    "PR Review",
    "kpi":          "KPI Investigation",
    "ci_cd":        "CI/CD Intelligence",
    "jira":         "Jira / Delivery Management",
    "analytics_qa": "Analytics + QA Crew",
    "general":      "General",
    "unknown":      "Unknown",
}

# Task types where platform_evidence is required before response can be published.
# Absent or unsafe evidence → response withheld (fail closed).
_EVIDENCE_REQUIRED_TYPES: frozenset[str] = frozenset({"kpi", "ci_cd"})


# ── Evidence parsing ──────────────────────────────────────────────────────────

def _parse_evidence(platform_evidence_json: Optional[str]) -> Optional[dict]:
    """
    Parse the JSON-serialised EvidencedAnswer from state.
    Returns None if absent or unparseable — callers treat this as evidence-unavailable.
    """
    if not platform_evidence_json:
        return None
    try:
        return _json.loads(platform_evidence_json)
    except Exception:
        return None


# ── Response builder with evidence gate ──────────────────────────────────────

def _build_response(
    task_type: str,
    skill_output: str,
    task_id: str,
    audience: Optional[str],
    platform_evidence_json: Optional[str],
) -> str:
    """
    Build the final response string, enforcing the evidence gate for
    evidence-required task types.

    Evidence gate states for kpi / ci_cd:
      1. platform_evidence absent (None)     → withheld, "evidence unavailable"
      2. is_safe_to_surface=False            → withheld, blocked_reason surfaced
      3. is_safe_to_surface=True, no stale  → full artifact + citation footer
      4. is_safe_to_surface=True, stale     → full artifact + citation footer with stale flags

    Non-evidence-required types (pr_review, qa, jira, general) → pass through.
    """
    if task_type in _EVIDENCE_REQUIRED_TYPES:
        evidenced = _parse_evidence(platform_evidence_json)

        if evidenced is None:
            return (
                f"[EVIDENCE UNAVAILABLE — {task_type.upper()} RESPONSE WITHHELD]\n"
                f"Platform evidence assembly did not complete for task {task_id[:12]}.\n"
                f"The skill output has been withheld pending evidence verification.\n"
                f"Retry the query or contact the platform team."
            )

        if not evidenced.get("is_safe_to_surface", False):
            blocked = evidenced.get("blocked_reason") or "Unsupported claims detected."
            return (
                f"[RESPONSE WITHHELD — UNSUPPORTED CLAIMS]\n"
                f"Task {task_id[:12]}: {blocked}"
            )

        # Safe to surface — render with citation footer
        return render_artifact_with_citations(
            task_type=task_type,
            skill_output=skill_output,
            task_id=task_id,
            audience=audience,
            evidenced=evidenced,
        )

    # Evidence not required for this task type — standard rendering
    return render_artifact(
        task_type=task_type,
        skill_output=skill_output,
        task_id=task_id,
        audience=audience,
    )


# ── Respond node ──────────────────────────────────────────────────────────────

def respond(state: ARIAState) -> dict:
    task_type    = state.get("task_type", "unknown")
    label        = _LABELS.get(task_type, "Unknown")
    skill_output = state.get("skill_output")

    if skill_output and not skill_output.startswith("[Week"):
        response = _build_response(
            task_type=task_type,
            skill_output=skill_output,
            task_id=state["task_id"],
            audience=state.get("audience"),
            platform_evidence_json=state.get("platform_evidence"),
        )
    else:
        # Placeholder or budget-exceeded — no evidence gate needed
        response = (
            f"Routed to: {label}\n"
            f"Reason:    {state.get('routing_reason', '')}\n"
            f"{skill_output or '[Skill execution wires in at its build week]'}"
        )

    log_task(
        task_id=state["task_id"],
        task_type=task_type,
        routing_reason=state.get("routing_reason", ""),
        error=state.get("error"),
        platform_evidence=state.get("platform_evidence"),
    )

    # Week 29 Priority 1 — emit the v2 mirror event alongside the legacy
    # log_task write. Failures here MUST NOT break graph execution;
    # the legacy writer is still the source of truth for V1 callers.
    _emit_v2_responded(
        task_id=state["task_id"],
        task_type=task_type,
        routing_reason=state.get("routing_reason", ""),
        error=state.get("error"),
    )

    token_budget_used = 0
    try:
        from aria.runtime.budget import budget_tracker
        initial = state.get("token_budget") or 50000
        token_budget_used = budget_tracker.used(state["task_id"], initial_budget=initial)
    except Exception:
        pass

    return {
        "response":          response,
        "task_status":       "done",
        "steps_completed":   state["steps_completed"] + ["respond"],
        "token_budget_used": token_budget_used,
    }


def _emit_v2_responded(
    *,
    task_id: str,
    task_type: str,
    routing_reason: str,
    error: Optional[str],
) -> None:
    """
    Best-effort v2 ledger mirror of the legacy ``log_task`` call. Wrapped
    in try/except so a ledger problem (disk full, permission error, etc.)
    cannot fail the graph — the legacy writer remains source of truth
    while v2 adoption rolls out.

    Emits ONE event per task completion:
      - ``Failed``   if state.error is set
      - ``Responded`` otherwise

    Idempotency: ``event_id`` is deterministic over ``(task_id,
    event_type)`` so retrying respond() for the same task_id writes a
    single ledger entry. Without this a graph-level retry would inflate
    completion counts. If the same task transitions from Responded to
    Failed (or vice versa) the writer's fingerprint-conflict guard
    catches it as a logic bug.

    The default singleton writer is configurable via
    ``ARIA_LEDGER_V2_PATH`` (tests use ``tests/conftest.py``'s autouse
    fixture; production uses ``apps/backend/work_ledger_v2.jsonl``).
    """
    try:
        from aria.ledger import ActorType, Failed, Responded
        from aria.ledger.events import make_envelope
        from aria.ledger.writer import get_default_writer

        writer = get_default_writer()
        lifecycle = "failed" if error else "responded"
        deterministic_event_id = f"respond:{lifecycle}:{task_id}"

        envelope = make_envelope(
            task_id=task_id,
            actor="aria",
            actor_type=ActorType.aria,
            event_id=deterministic_event_id,
            skill_name=task_type if task_type and task_type != "unknown" else None,
            metadata={"routing_reason": routing_reason} if routing_reason else {},
        )
        # ``idempotent_on_collision=True`` makes the check-and-append
        # atomic inside the writer lock. Concurrent retries for the
        # same lifecycle event collapse to one durable line — the
        # second caller sees the first's seen-set update and returns
        # False rather than raising on a stale-timestamp fingerprint
        # diff. The Responded-vs-Failed cross-type check still fires
        # via ``TerminalOutcomeConflict`` so a task that legitimately
        # flipped lifecycle is surfaced as a logic bug.
        if error:
            writer.append(
                Failed(error=error, **envelope),
                idempotent_on_collision=True,
            )
        else:
            writer.append(
                Responded(**envelope),
                idempotent_on_collision=True,
            )
    except (ImportError, OSError, LedgerPersistenceError):
        # Narrow except: ledger import failure or disk I/O failure
        # cannot fail the graph. ValidationError / ValueError /
        # TerminalOutcomeConflict from the ledger surface as actual
        # bugs and propagate.
        pass
