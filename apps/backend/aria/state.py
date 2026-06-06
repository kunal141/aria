from typing import TypedDict, Optional, Literal, List


class ARIAState(TypedDict):
    # ── Identity ──────────────────────────────────────────────────────────────
    task_id: str          # unique ID assigned by intake node
    raw_input: str        # the raw text the user sent to ARIA

    # ── Routing ───────────────────────────────────────────────────────────────
    # Literal = only these exact strings are valid. A typo like "pr_reveiw"
    # is caught by the type checker before the code ever runs.
    task_type: Optional[Literal["pr_review", "kpi", "ci_cd", "jira", "qa", "test_review", "general", "unknown"]]
    task_status: Literal["pending", "routing", "executing", "done", "failed"]

    # ── Traceability ──────────────────────────────────────────────────────────
    # These two fields are the seed of the Work Ledger (Pillar 16).
    # From Week 4, every task gets logged with these fields so ARIA can
    # later answer: "why did I route this task to PR review?"
    routing_reason: Optional[str]   # human-readable reason for the routing decision
    steps_completed: List[str]      # audit trail e.g. ['intake', 'router', 'respond']

    # ── Output ────────────────────────────────────────────────────────────────
    skill_name: Optional[str]       # which skill was invoked (Week 6+)
    skill_output: Optional[str]     # raw output from the skill
    response: Optional[str]         # final formatted text sent back to the user

    # ── Context ───────────────────────────────────────────────────────────────
    messages: List[dict]            # conversation history (used by LLM nodes)
    error: Optional[str]            # error message if task_status == 'failed'

    # ── Week 13 additions ─────────────────────────────────────────────────────
    # audience: set by caller (Teams channel, API param, CLI flag)
    # drives tone + depth of artifact rendering — same skill output, different surface
    audience: Optional[Literal["developer", "manager", "leadership"]]
    langsmith_run_id: Optional[str] # captured from tracer context; used for feedback logging

    # ── Week 16 additions ─────────────────────────────────────────────────────
    # routing_tier: set by ModelRouter in intake/router node; logged to Work Ledger
    routing_tier: Optional[Literal["fast", "smart", "frontier"]]
    # complexity: inferred from input length or set explicitly by caller
    complexity: Optional[Literal["simple", "normal", "complex"]]
    # approval_request_id: set when a T4 action is pending human approval
    approval_request_id: Optional[str]

    # ── Week 15 additions ─────────────────────────────────────────────────────
    # data_sensitivity: governs model routing (Week 16), LangSmith tracing,
    # and tool permission checks. Set by intake node; can be overridden by caller.
    #   public       → safe for external APIs + LangSmith
    #   internal     → logs OK; redact before LangSmith
    #   confidential → self-hosted model required (Week 25+); redact all external
    #   restricted   → no external calls; human approval required at T1+
    data_sensitivity: Optional[Literal["public", "internal", "confidential", "restricted"]]

    # ── Week 21 additions (Runtime Harness) ───────────────────────────────────
    # execution_mode: "dry_run" skips real tool calls — used for safe testing
    #                 and pre-flight checks before live execution.
    #                 "live" (default) calls tools for real.
    execution_mode: Optional[Literal["dry_run", "live"]]
    # token_budget: maximum tokens allowed for this task (enforced by BudgetTracker)
    token_budget: Optional[int]
    # token_budget_used: tokens consumed so far — set by respond node for observability
    token_budget_used: Optional[int]
