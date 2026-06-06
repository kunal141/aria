"""
Model Router v1 — Week 16

Routes each task to the right LLM tier based on task signals.
No single-model approach after Week 16 (CLAUDE.md Rule 7).

Three tiers in v1:
  fast      → cheap SLM or Haiku — classification, routing, simple extraction
              ~$0 cost/call with Ollama or Groq free tier
  smart     → standard model (Haiku/Sonnet) — PR review, KPI, normal tasks
              ~$0.001–0.01/call
  frontier  → best available (Opus) — leadership briefs, high-risk decisions
              ~$0.01–0.10/call; reserved for genuinely complex/high-stakes tasks

Routing signals (in priority order):
  1. data_sensitivity (confidential/restricted) → privacy note; self-hosted in Week 25+
  2. task_type == "general" OR complexity == "simple" → fast
  3. audience == "leadership" OR complexity == "complex" → frontier
  4. task_type in engineering skills (pr_review, kpi) → smart
  5. default → smart

Future versions:
  v2 (Week 25) — add vLLM self-hosted tier for confidential/restricted data
  v3 (Week 29) — add fine-tuned specialist routing (pr_review → fine-tuned Qwen)

Why this matters:
  Using Opus for task classification wastes 100× more money than needed.
  Using Haiku for a leadership brief risks quality on a high-visibility output.
  The router makes the right cost/quality tradeoff automatically — no manual switching.
"""
from typing import Optional, Literal
from pydantic import BaseModel


RoutingTier = Literal["fast", "smart", "frontier"]


class RoutingDecision(BaseModel):
    tier: RoutingTier
    reason: str
    estimated_cost: str         # human-readable: "~$0", "~$0.001", "~$0.01+"
    privacy_note: Optional[str] = None   # set when self-hosted should be used


# ── Routing table ─────────────────────────────────────────────────────────────
# Each rule is (condition_fn, tier, reason, cost_estimate).
# Rules are checked in order — first match wins.

_FAST_TASK_TYPES  = frozenset(["general", "routing", "unknown"])
_SMART_TASK_TYPES = frozenset(["pr_review", "kpi", "ci_cd", "jira"])
_HIGH_SENSITIVITY = frozenset(["confidential", "restricted"])


class ModelRouter:
    """
    Stateless router — no LLM call needed. Pure rule evaluation.

    Usage:
        decision = ModelRouter().route(
            task_type="pr_review",
            data_sensitivity="internal",
            audience="leadership",
        )
        llm = get_llm_for_tier(decision.tier)
    """

    def route(
        self,
        task_type: Optional[str] = None,
        data_sensitivity: Optional[str] = None,
        audience: Optional[str] = None,
        complexity: Optional[str] = None,   # "simple" | "normal" | "complex"
        input_length: int = 0,
    ) -> RoutingDecision:
        """
        Determine the appropriate LLM tier for a task.

        Args:
            task_type:        classified task type from router node
            data_sensitivity: from ARIAState (inferred or explicit)
            audience:         "developer" | "manager" | "leadership"
            complexity:       "simple" | "normal" | "complex" (None = infer)
            input_length:     character count of raw input (used for complexity inference)

        Returns:
            RoutingDecision with tier, reason, and cost estimate
        """
        # Infer complexity from input length if not provided
        if complexity is None:
            if input_length < 200:
                complexity = "simple"
            elif input_length > 2000:
                complexity = "complex"
            else:
                complexity = "normal"

        privacy_note = None

        # ── Rule 1: sensitivity — note for future self-hosted routing ─────────
        if data_sensitivity in _HIGH_SENSITIVITY:
            privacy_note = (
                f"Data sensitivity '{data_sensitivity}' — "
                "Week 25+: route to self-hosted vLLM instead of external API"
            )
            # In v1 we can't enforce self-hosted yet, but we flag it
            # and we use smart (not frontier) to minimise data exposure surface
            return RoutingDecision(
                tier="smart",
                reason=f"Sensitivity={data_sensitivity}: capped at smart tier; self-hosted required in Week 25+",
                estimated_cost="~$0.001",
                privacy_note=privacy_note,
            )

        # ── Rule 2: simple tasks → fast ───────────────────────────────────────
        if task_type in _FAST_TASK_TYPES or complexity == "simple":
            return RoutingDecision(
                tier="fast",
                reason=f"task_type={task_type}, complexity={complexity} → fast SLM",
                estimated_cost="~$0",
            )

        # ── Rule 3: leadership audience or complex tasks → frontier ───────────
        if audience == "leadership" or complexity == "complex":
            return RoutingDecision(
                tier="frontier",
                reason=f"audience={audience}, complexity={complexity} → frontier for quality",
                estimated_cost="~$0.01+",
            )

        # ── Rule 4: engineering skills → smart ────────────────────────────────
        if task_type in _SMART_TASK_TYPES:
            return RoutingDecision(
                tier="smart",
                reason=f"task_type={task_type} → smart model",
                estimated_cost="~$0.001",
            )

        # ── Rule 5: default → smart ───────────────────────────────────────────
        return RoutingDecision(
            tier="smart",
            reason="default routing → smart",
            estimated_cost="~$0.001",
        )

    def explain(
        self,
        task_type: Optional[str] = None,
        data_sensitivity: Optional[str] = None,
        audience: Optional[str] = None,
        complexity: Optional[str] = None,
        input_length: int = 0,
    ) -> str:
        """Human-readable routing explanation (for Work Ledger + debugging)."""
        d = self.route(task_type, data_sensitivity, audience, complexity, input_length)
        lines = [
            f"Tier     : {d.tier}",
            f"Reason   : {d.reason}",
            f"Est. cost: {d.estimated_cost}",
        ]
        if d.privacy_note:
            lines.append(f"Privacy  : {d.privacy_note}")
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────

_router = ModelRouter()


def route(
    task_type: Optional[str] = None,
    data_sensitivity: Optional[str] = None,
    audience: Optional[str] = None,
    complexity: Optional[str] = None,
    input_length: int = 0,
) -> RoutingDecision:
    """Module-level shortcut to the singleton router."""
    return _router.route(task_type, data_sensitivity, audience, complexity, input_length)
