from aria.state import ARIAState
from aria.work_ledger import log_task
from aria.artifact_engine import render_artifact

_LABELS = {
    "pr_review": "PR Review",
    "kpi":       "KPI Investigation",
    "ci_cd":     "CI/CD Intelligence",
    "jira":      "Jira / Delivery Management",
    "general":   "General",
    "unknown":   "Unknown",
}


def respond(state: ARIAState) -> dict:
    task_type    = state.get("task_type", "unknown")
    label        = _LABELS.get(task_type, "Unknown")
    skill_output = state.get("skill_output")

    if skill_output and not skill_output.startswith("[Week"):
        # Real skill ran — render formatted artifact (audience-aware)
        response = render_artifact(
            task_type=task_type,
            skill_output=skill_output,
            task_id=state["task_id"],
            audience=state.get("audience"),
        )
    else:
        # Placeholder — skill not built yet
        response = (
            f"Routed to: {label}\n"
            f"Reason:    {state.get('routing_reason', '')}\n"
            f"{skill_output or '[Skill execution wires in at its build week]'}"
        )

    log_task(
        task_id=state["task_id"],
        task_type=task_type,
        routing_reason=state.get("routing_reason", ""),
    )

    # Record token consumption — estimate from output size (4 chars ≈ 1 token).
    # consume() is non-blocking; budget overrun is observable but not fatal in V1.
    token_budget_used = state.get("token_budget_used") or 0
    if skill_output:
        estimated = max(1, len(skill_output) // 4)
        try:
            from aria.runtime.budget import budget_tracker
            budget_tracker.consume(state["task_id"], estimated)
            token_budget_used += estimated
        except Exception:
            pass

    return {
        "response":          response,
        "task_status":       "done",
        "steps_completed":   state["steps_completed"] + ["respond"],
        "token_budget_used": token_budget_used,
    }
