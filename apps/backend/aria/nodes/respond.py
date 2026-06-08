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
