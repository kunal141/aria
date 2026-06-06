"""
Tool Permission System — Week 15

Every ARIA tool is registered with:
  - min_action_tier   : lowest tier allowed to invoke this tool
  - sensitivity_ceiling: highest data_sensitivity level allowed (None = any)
  - description        : what the tool does (for audit log readability)

Action Tiers (from CLAUDE.md Section 11):
  T1 — Read         : fetches data, reads docs, observes — automatic
  T2 — Recommend    : proposes action, posts suggestion — automatic
  T3 — Draft        : creates draft (PR note, ticket) — automatic; human edits before send
  T4 — Execute      : takes real action after explicit approval — requires human approval
  T5 — Autonomous   : acts without asking — only pre-approved routine patterns

V1 enforces Tiers 1–3 only. Any tool claiming T4/T5 is blocked until Week 16
adds the approval gate infrastructure.

Data sensitivity levels:
  public       → output/input can go to LangSmith, logs, external APIs
  internal     → logs OK, not LangSmith or external APIs without redaction
  confidential → self-hosted model required (Week 25+); redact before all logging
  restricted   → no external API calls; human approval required at T1+
"""
from typing import Optional, Literal
from pydantic import BaseModel


# ── Types ─────────────────────────────────────────────────────────────────────

ActionTier = Literal["T1", "T2", "T3", "T4", "T5"]
DataSensitivity = Literal["public", "internal", "confidential", "restricted"]

_TIER_RANK: dict[str, int] = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
_SENS_RANK: dict[str, int] = {
    "public": 1, "internal": 2, "confidential": 3, "restricted": 4
}


class ToolPermission(BaseModel):
    tool_name: str
    min_action_tier: ActionTier = "T1"
    sensitivity_ceiling: Optional[DataSensitivity] = None   # None = no ceiling
    description: str = ""


class PermissionCheckResult(BaseModel):
    allowed: bool
    tool_name: str
    reason: str


# ── Registry ──────────────────────────────────────────────────────────────────

# V1 read/recommend/draft tools — Tiers 1-3 only
_REGISTRY: dict[str, ToolPermission] = {
    # ── Knowledge / RAG ──────────────────────────────────────────────────────
    "knowledge_search": ToolPermission(
        tool_name="knowledge_search",
        min_action_tier="T1",
        sensitivity_ceiling="confidential",
        description="Search the ARIA knowledge vault (RAG index)",
    ),
    "code_search": ToolPermission(
        tool_name="code_search",
        min_action_tier="T1",
        sensitivity_ceiling="confidential",
        description="Search the code intelligence AST/dependency index",
    ),
    # ── Skills (read-only execution) ──────────────────────────────────────────
    "kpi_skill": ToolPermission(
        tool_name="kpi_skill",
        min_action_tier="T1",
        sensitivity_ceiling="confidential",
        description="KPI investigation — reads metrics, produces analysis",
    ),
    "pr_review_skill": ToolPermission(
        tool_name="pr_review_skill",
        min_action_tier="T1",
        sensitivity_ceiling="confidential",
        description="PR review — reads code diff, produces review artifact",
    ),
    # ── Draft creation (T3) ───────────────────────────────────────────────────
    "jira_draft": ToolPermission(
        tool_name="jira_draft",
        min_action_tier="T3",
        sensitivity_ceiling="internal",
        description="Draft a Jira ticket — does NOT create it; human reviews first",
    ),
    "pr_comment_draft": ToolPermission(
        tool_name="pr_comment_draft",
        min_action_tier="T3",
        sensitivity_ceiling="internal",
        description="Draft a PR comment — does NOT post it; human reviews first",
    ),
    "teams_message_draft": ToolPermission(
        tool_name="teams_message_draft",
        min_action_tier="T3",
        sensitivity_ceiling="internal",
        description="Draft a Teams message — does NOT send it; human reviews first",
    ),
    # ── Execute-with-Approval (T4 — blocked in V1) ───────────────────────────
    "jira_create": ToolPermission(
        tool_name="jira_create",
        min_action_tier="T4",
        sensitivity_ceiling="internal",
        description="Create a real Jira ticket — requires explicit human approval",
    ),
    "github_pr_comment": ToolPermission(
        tool_name="github_pr_comment",
        min_action_tier="T4",
        sensitivity_ceiling="internal",
        description="Post a comment on a real GitHub PR — requires explicit human approval",
    ),
    "teams_message_send": ToolPermission(
        tool_name="teams_message_send",
        min_action_tier="T4",
        sensitivity_ceiling="internal",
        description="Send a real Teams message — requires explicit human approval",
    ),
}

# V1 enforcement: T4 now allowed with approval gate (Week 16). T5 = autonomous, still blocked.
_V1_MAX_TIER = "T4"


# ── Public API ────────────────────────────────────────────────────────────────

def register(permission: ToolPermission) -> None:
    """Register a new tool permission. Called by skill/tool modules."""
    _REGISTRY[permission.tool_name] = permission


def get(tool_name: str) -> Optional[ToolPermission]:
    """Return permission config for a tool, or None if unregistered."""
    return _REGISTRY.get(tool_name)


def check(
    tool_name: str,
    current_sensitivity: Optional[str] = None,
) -> PermissionCheckResult:
    """
    Check whether a tool call is allowed given the current task's data sensitivity.

    Args:
        tool_name:           Name of the tool being invoked.
        current_sensitivity: data_sensitivity from ARIAState. None = "public".

    Returns:
        PermissionCheckResult(allowed=True/False, reason=...)
    """
    perm = _REGISTRY.get(tool_name)
    if perm is None:
        # Unregistered tools are blocked — fail-closed, not fail-open
        return PermissionCheckResult(
            allowed=False,
            tool_name=tool_name,
            reason=f"Tool '{tool_name}' is not registered in the permission system. "
                   "Register it before use.",
        )

    # T5 (autonomous) still blocked in V1 — needs trust built first
    if _TIER_RANK[perm.min_action_tier] > _TIER_RANK[_V1_MAX_TIER]:
        return PermissionCheckResult(
            allowed=False,
            tool_name=tool_name,
            reason=(
                f"Tool '{tool_name}' requires tier {perm.min_action_tier} "
                f"(V1 maximum is {_V1_MAX_TIER}). "
                "Autonomous (T5) actions are deferred to V2."
            ),
        )

    # T4 requires approval gate — check if an approval exists
    if perm.min_action_tier == "T4":
        # The caller must pass task_id for T4 approval check
        # Without task_id we cannot verify approval — block with guidance
        return PermissionCheckResult(
            allowed=False,
            tool_name=tool_name,
            reason=(
                f"Tool '{tool_name}' is T4 (Execute-with-Approval). "
                "Call check_with_approval(tool_name, task_id) to verify human approval first."
            ),
        )

    # Sensitivity ceiling check
    if perm.sensitivity_ceiling and current_sensitivity:
        task_rank    = _SENS_RANK.get(current_sensitivity, 0)
        ceiling_rank = _SENS_RANK.get(perm.sensitivity_ceiling, 0)
        if task_rank > ceiling_rank:
            return PermissionCheckResult(
                allowed=False,
                tool_name=tool_name,
                reason=(
                    f"Tool '{tool_name}' ceiling is '{perm.sensitivity_ceiling}' "
                    f"but task sensitivity is '{current_sensitivity}'. "
                    "Route to a self-hosted model or escalate to human."
                ),
            )

    return PermissionCheckResult(
        allowed=True,
        tool_name=tool_name,
        reason=f"Allowed at {perm.min_action_tier}",
    )


def check_with_approval(
    tool_name: str,
    task_id: str,
    current_sensitivity: Optional[str] = None,
) -> PermissionCheckResult:
    """
    Check a T4 tool — passes only if the approval gate has an approved request.
    For T1-T3 tools, delegates to the standard check().
    """
    perm = _REGISTRY.get(tool_name)
    if perm is None:
        return PermissionCheckResult(
            allowed=False,
            tool_name=tool_name,
            reason=f"Tool '{tool_name}' is not registered.",
        )

    # T1–T3: no approval needed — use standard check
    if _TIER_RANK[perm.min_action_tier] <= _TIER_RANK["T3"]:
        return check(tool_name, current_sensitivity)

    # T4: verify approval gate
    if perm.min_action_tier == "T4":
        from aria.governance.approval_gate import is_approved
        if is_approved(task_id, tool_name):
            # Also verify sensitivity ceiling
            if perm.sensitivity_ceiling and current_sensitivity:
                task_rank    = _SENS_RANK.get(current_sensitivity, 0)
                ceiling_rank = _SENS_RANK.get(perm.sensitivity_ceiling, 0)
                if task_rank > ceiling_rank:
                    return PermissionCheckResult(
                        allowed=False,
                        tool_name=tool_name,
                        reason=f"Sensitivity ceiling exceeded even with approval.",
                    )
            return PermissionCheckResult(
                allowed=True,
                tool_name=tool_name,
                reason=f"T4 action approved by human for task {task_id[:8]}",
            )
        return PermissionCheckResult(
            allowed=False,
            tool_name=tool_name,
            reason=f"T4 action requires approval. Call approval_gate.request_approval('{task_id}', '{tool_name}', ...).",
        )

    # T5: blocked
    return PermissionCheckResult(
        allowed=False,
        tool_name=tool_name,
        reason=f"T5 (autonomous) actions are not permitted in V1.",
    )


def list_tools() -> list[str]:
    return list(_REGISTRY)


def list_blocked_in_v1() -> list[str]:
    """Return tool names blocked in V1 (Tier > T3)."""
    return [
        name for name, p in _REGISTRY.items()
        if _TIER_RANK[p.min_action_tier] > _TIER_RANK[_V1_MAX_TIER]
    ]
