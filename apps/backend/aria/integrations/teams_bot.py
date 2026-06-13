"""
ARIA Teams Bot — Week 13

Makes ARIA available as a Microsoft Teams bot.
Users @mention ARIA in any channel → she runs the task → replies with an Adaptive Card.

Architecture:
  Teams channel
    → POST /api/messages  (teams_adapter.py — FastAPI endpoint)
    → ARIAActivityHandler.on_message_activity()
    → ARIA LangGraph (same graph as main.py)
    → Adaptive Card response

Setup (one-time, needs Azure):
  1. Create Azure Bot resource: portal.azure.com → Create Bot
  2. Set messaging endpoint: https://<your-domain>/api/messages
  3. Copy App ID + App Password → TEAMS_APP_ID, TEAMS_APP_PASSWORD in .env
  4. Install the bot in your Teams channel via App Studio or manifest upload
  5. For local dev: use ngrok to expose localhost → ngrok http 3978

Adaptive Cards:
  Schema-driven JSON UI rendered natively by Teams.
  ARIA emits card schemas — Teams renders them safely (no raw HTML).
  Cards include Approve/Reject buttons → foundation for T4 actions (Week 16).
"""
import os
import json
import asyncio
from typing import Optional

from botbuilder.core import ActivityHandler, TurnContext, MessageFactory
from botbuilder.schema import Activity, ActivityTypes


# ─────────────────────────────────────────────────────────────────────────────
# Audience detection
# ─────────────────────────────────────────────────────────────────────────────

# Teams channel name patterns → audience mapping
# Engineering channels → developer, management/leadership channels → manager/leadership
_CHANNEL_AUDIENCE = {
    "engineering": "developer",
    "dev":         "developer",
    "backend":     "developer",
    "frontend":    "developer",
    "platform":    "developer",
    "management":  "manager",
    "managers":    "manager",
    "leads":       "manager",
    "leadership":  "leadership",
    "exec":        "leadership",
    "board":       "leadership",
}

def _detect_audience(channel_name: Optional[str], from_name: Optional[str]) -> str:
    """
    Infer audience from Teams channel name or sender display name.
    Default: developer (most detailed output).
    """
    if channel_name:
        lower = channel_name.lower()
        for pattern, audience in _CHANNEL_AUDIENCE.items():
            if pattern in lower:
                return audience
    return "developer"


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive Card builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_pr_review_card(data: dict, task_id: str) -> dict:
    """Adaptive Card schema for PR review output."""
    verdict   = data.get("verdict", "unknown").replace("_", " ").title()
    risk      = data.get("risk_level", "unknown").upper()
    summary   = data.get("summary", "")
    impact    = data.get("business_impact", "")
    issues    = data.get("code_issues", [])

    verdict_colors = {
        "Approve":           "Good",
        "Request Changes":   "Attention",
        "Needs Discussion":  "Warning",
    }
    color = verdict_colors.get(verdict, "Default")

    issue_facts = [
        {
            "title": f"[{i.get('severity','?').upper()}] {i.get('category','')}",
            "value": i.get("description", ""),
        }
        for i in issues[:3]  # top 3 issues in the card
    ]

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "🔍 ARIA PR Review",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Verdict", "value": verdict},
                    {"title": "Risk", "value": risk},
                    {"title": "Task ID", "value": task_id[:12]},
                ],
            },
            {
                "type": "TextBlock",
                "text": summary,
                "wrap": True,
                "color": color,
            },
            *([{
                "type": "TextBlock",
                "text": "**Business Impact**",
                "weight": "Bolder",
                "spacing": "Medium",
            },
            {
                "type": "TextBlock",
                "text": impact,
                "wrap": True,
            }] if impact else []),
            *([{
                "type": "TextBlock",
                "text": f"**Top Issues ({len(issues)})**",
                "weight": "Bolder",
                "spacing": "Medium",
            },
            {
                "type": "FactSet",
                "facts": issue_facts,
            }] if issue_facts else []),
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Approve",
                "style": "positive",
                "data": {"aria_action": "approve", "task_id": task_id},
            },
            {
                "type": "Action.Submit",
                "title": "❌ Request Changes",
                "style": "destructive",
                "data": {"aria_action": "reject", "task_id": task_id},
            },
            {
                "type": "Action.ShowCard",
                "title": "📋 Full Details",
                "card": {
                    "type": "AdaptiveCard",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "Full PR review details available in ARIA Work Ledger.",
                            "wrap": True,
                        }
                    ],
                },
            },
        ],
    }


def _build_kpi_card(data: dict, task_id: str, evidenced: dict | None = None) -> dict:
    """Adaptive Card schema for KPI investigation output."""
    summary  = data.get("summary", "")
    conf     = data.get("confidence_score", 0.0)
    causes   = data.get("root_causes", [])
    actions  = data.get("recommended_actions", [])

    cause_facts = [
        {
            "title": f"[{c.get('likelihood','?').upper()}] Hypothesis",
            "value": c.get("hypothesis", ""),
        }
        for c in causes[:3]
    ]

    action_texts = "\n".join(f"• {a}" for a in actions[:3])

    body = [
        {
            "type": "TextBlock",
            "text": "📊 ARIA KPI Investigation",
            "weight": "Bolder",
            "size": "Medium",
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Confidence", "value": f"{conf:.0%}"},
                {"title": "Task ID",    "value": task_id[:12]},
            ],
        },
        {
            "type": "TextBlock",
            "text": summary,
            "wrap": True,
        },
        *([{
            "type": "TextBlock",
            "text": "**Root Cause Hypotheses**",
            "weight": "Bolder",
            "spacing": "Medium",
        },
        {
            "type": "FactSet",
            "facts": cause_facts,
        }] if cause_facts else []),
        *([{
            "type": "TextBlock",
            "text": "**Recommended Actions**",
            "weight": "Bolder",
            "spacing": "Medium",
        },
        {
            "type": "TextBlock",
            "text": action_texts,
            "wrap": True,
        }] if actions else []),
    ]

    # Evidence provenance section — shows claim-level citations (no source content)
    if evidenced:
        evidence_facts = _build_evidence_facts(evidenced)
        if evidence_facts:
            body += [
                {
                    "type": "TextBlock",
                    "text": "**Evidence Sources**",
                    "weight": "Bolder",
                    "spacing": "Medium",
                    "color": "Accent",
                },
                {"type": "FactSet", "facts": evidence_facts},
            ]
        warnings = evidenced.get("freshness_warnings", [])
        if warnings:
            body.append({
                "type": "TextBlock",
                "text": f"⚠️ {warnings[0][:80]}",
                "color": "Warning",
                "wrap": True,
                "spacing": "Small",
            })

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Useful",
                "style": "positive",
                "data": {"aria_action": "approve", "task_id": task_id},
            },
            {
                "type": "Action.Submit",
                "title": "❌ Missed the point",
                "style": "destructive",
                "data": {"aria_action": "reject", "task_id": task_id},
            },
        ],
    }


def _build_cicd_card(data: dict, task_id: str, evidenced: dict | None = None) -> dict:
    """Adaptive Card schema for CI/CD failure output with dependency impact."""
    failure_summary = data.get("failure_summary", "")
    severity        = data.get("severity", "unknown").upper()
    failed_stage    = data.get("failed_stage", "")
    hypotheses      = data.get("root_cause_hypotheses", [])
    fixes           = data.get("suggested_fixes", [])
    verdict         = data.get("deployment_verdict", "unknown")

    severity_colors = {
        "CRITICAL": "Attention",
        "HIGH":     "Warning",
        "MEDIUM":   "Default",
        "LOW":      "Good",
    }
    color = severity_colors.get(severity, "Default")

    hyp_facts = [
        {
            "title": f"[{h.get('likelihood','?').upper()}]",
            "value": h.get("hypothesis", ""),
        }
        for h in hypotheses[:3]
    ]

    body = [
        {
            "type": "TextBlock",
            "text": "🔧 ARIA CI/CD Intelligence",
            "weight": "Bolder",
            "size": "Medium",
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Severity",       "value": severity},
                {"title": "Failed Stage",   "value": failed_stage or "unknown"},
                {"title": "Verdict",        "value": verdict},
                {"title": "Task ID",        "value": task_id[:12]},
            ],
        },
        {
            "type": "TextBlock",
            "text": failure_summary,
            "wrap": True,
            "color": color,
        },
        *([{
            "type": "TextBlock",
            "text": "**Root Cause Hypotheses**",
            "weight": "Bolder",
            "spacing": "Medium",
        },
        {"type": "FactSet", "facts": hyp_facts}] if hyp_facts else []),
        *([{
            "type": "TextBlock",
            "text": "**Suggested Fixes**",
            "weight": "Bolder",
            "spacing": "Medium",
        },
        {
            "type": "TextBlock",
            "text": "\n".join(f"• {f}" for f in fixes[:3]),
            "wrap": True,
        }] if fixes else []),
    ]

    # Evidence provenance + dependency impact
    if evidenced:
        evidence_facts = _build_evidence_facts(evidenced)
        if evidence_facts:
            body += [
                {
                    "type": "TextBlock",
                    "text": "**Platform Evidence & Dependency Impact**",
                    "weight": "Bolder",
                    "spacing": "Medium",
                    "color": "Accent",
                },
                {"type": "FactSet", "facts": evidence_facts},
            ]
        warnings = evidenced.get("freshness_warnings", [])
        if warnings:
            body.append({
                "type": "TextBlock",
                "text": f"⚠️ {warnings[0][:80]}",
                "color": "Warning",
                "wrap": True,
                "spacing": "Small",
            })

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Acknowledged",
                "style": "positive",
                "data": {"aria_action": "approve", "task_id": task_id},
            },
            {
                "type": "Action.Submit",
                "title": "❌ Wrong analysis",
                "style": "destructive",
                "data": {"aria_action": "reject", "task_id": task_id},
            },
        ],
    }


def _build_evidence_facts(evidenced: dict) -> list[dict]:
    """
    Build Adaptive Card FactSet facts from claim-level evidence.
    Shows only source_id and authority — never source.content or source.title.
    """
    facts = []
    for ce in evidenced.get("claim_evidence_map", []):
        claim_id    = ce.get("claim_id", "?")
        is_supported = ce.get("is_supported", False)
        selected    = ce.get("selected_evidence")

        if not is_supported:
            facts.append({"title": claim_id, "value": "No authorized evidence found"})
            continue

        if selected:
            source_id = selected.get("source_id", "?")
            authority = selected.get("authority", "?")
            is_stale  = selected.get("is_stale", False)
            stale_h   = selected.get("staleness_hours")
            stale_flag = (
                f" [stale {stale_h:.0f}h]" if is_stale and stale_h is not None
                else " [stale]" if is_stale else ""
            )
            facts.append({
                "title": claim_id,
                "value": f"{source_id} (auth={authority}{stale_flag})",
            })

    return facts


def _build_jira_card(data: dict, task_id: str) -> dict:
    """Adaptive Card schema for Jira ticket draft output."""
    draft    = data.get("ticket_draft", {})
    title    = draft.get("title", "Untitled ticket")
    ttype    = draft.get("ticket_type", "task").title()
    priority = draft.get("priority", "medium").upper()
    points   = draft.get("story_points")
    points_str = str(points) if points is not None else "N/A"
    ac       = draft.get("acceptance_criteria", [])[:3]
    labels   = draft.get("labels", [])
    sprint_impact = data.get("sprint_impact", "")
    blocker  = data.get("blocker_detected", False)

    priority_colors = {
        "CRITICAL": "Attention",
        "HIGH":     "Warning",
        "MEDIUM":   "Default",
        "LOW":      "Good",
    }
    color = priority_colors.get(priority, "Default")

    ac_facts = [
        {"title": f"AC {i + 1}", "value": crit}
        for i, crit in enumerate(ac)
    ]

    body: list = [
        {"type": "TextBlock", "text": "🎫 ARIA Jira Draft", "weight": "Bolder", "size": "Medium"},
        {"type": "TextBlock", "text": title, "wrap": True, "weight": "Bolder"},
        {
            "type": "FactSet",
            "facts": [
                {"title": "Type",     "value": ttype},
                {"title": "Priority", "value": priority},
                {"title": "Points",   "value": points_str},
                {"title": "Task ID",  "value": task_id[:12]},
            ],
        },
    ]

    if blocker and sprint_impact:
        body.append({
            "type": "TextBlock",
            "text": f"⚠️ **Sprint Blocker** — {sprint_impact}",
            "color": "Attention",
            "wrap": True,
        })
    elif sprint_impact:
        body.append({"type": "TextBlock", "text": sprint_impact, "wrap": True, "color": color})

    if ac_facts:
        body += [
            {"type": "TextBlock", "text": "**Acceptance Criteria**", "weight": "Bolder", "spacing": "Medium"},
            {"type": "FactSet", "facts": ac_facts},
        ]

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Create in Jira",
                "style": "positive",
                "data": {"aria_action": "approve", "task_id": task_id},
            },
            {
                "type": "Action.Submit",
                "title": "❌ Discard Draft",
                "style": "destructive",
                "data": {"aria_action": "reject", "task_id": task_id},
            },
            {
                "type": "Action.ShowCard",
                "title": "📋 Labels & Details",
                "card": {
                    "type": "AdaptiveCard",
                    "body": [{
                        "type": "TextBlock",
                        "text": f"Labels: {', '.join(labels)}" if labels else "No labels assigned.",
                        "wrap": True,
                    }],
                },
            },
        ],
    }


def _build_evolution_approval_card(data: dict, task_id: str) -> dict:
    """
    Adaptive Card schema for a governed self-improvement update awaiting T4 approval.

    Shows: version diff, changelog, why ARIA proposes the update, supporting evidence,
    risk assessment, canary plan, rollback target, and approve/reject actions.
    """
    action   = data.get("action", "")
    updates  = data.get("updates", [])
    message  = data.get("message", "")

    # For scan/evaluate flows, grab the first queued update for detail display
    update_ids = data.get("updates_queued", [])
    update_id  = update_ids[0] if update_ids else data.get("update_id", "")

    body: list = [
        {
            "type": "TextBlock",
            "text": "🧬 ARIA Self-Improvement Proposal",
            "weight": "Bolder",
            "size": "Large",
        },
        {
            "type": "TextBlock",
            "text": message or "ARIA has submitted a governed self-improvement proposal.",
            "wrap": True,
        },
    ]

    # ── Pending updates list (list_pending action) ─────────────────────────────
    # Each pending update gets its own Container with inline Approve/Reject
    # buttons that carry the exact update_id.  Selecting one release changes
    # only that release; other pending releases are unaffected.
    if action == "list_pending" and updates:
        for u in updates[:5]:
            uid = u.get("update_id", "")
            body.append({
                "type": "Container",
                "separator": True,
                "items": [
                    {
                        "type": "FactSet",
                        "facts": [
                            {"title": "Update ID",  "value": uid[:24]},
                            {"title": "Component",  "value": u.get("component", "?")},
                            {"title": "Version",    "value": u.get("version", "?")},
                            {"title": "Status",     "value": u.get("status", "?")},
                            {"title": "Proposer",   "value": u.get("proposer", "?")},
                        ],
                    },
                    {
                        "type": "ActionSet",
                        "actions": [
                            {
                                "type":  "Action.Submit",
                                "title": "✅ Approve",
                                "style": "positive",
                                "data": {
                                    "aria_action":          "approve",
                                    "aria_source":          "evolution_card",
                                    "task_id":              task_id,
                                    "evolution_update_id":  uid,
                                },
                            },
                            {
                                "type":  "Action.Submit",
                                "title": "❌ Reject",
                                "style": "destructive",
                                "data": {
                                    "aria_action":          "reject",
                                    "aria_source":          "evolution_card",
                                    "task_id":              task_id,
                                    "evolution_update_id":  uid,
                                },
                            },
                        ],
                    },
                ],
            })

    # ── Version comparison card (compare_update action) ────────────────────────
    elif action == "compare_update":
        from_ver   = data.get("from_version", "N/A")
        to_ver     = data.get("to_version", "N/A")
        component  = data.get("component", "unknown")
        changelog  = data.get("changelog", "")
        diff_lines = data.get("diff_lines", [])[:8]
        sec_impact = data.get("security_impact", "none")
        prv_impact = data.get("privacy_impact", "none")
        canary     = data.get("canary_plan", "")
        rollback   = data.get("rollback_target", "")
        evidence   = data.get("evidence_refs", [])[:3]

        impact_color = "Attention" if sec_impact not in ("none", "minimal") else "Default"

        body += [
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Component",   "value": component},
                    {"title": "From",        "value": from_ver or "N/A"},
                    {"title": "To",          "value": to_ver},
                    {"title": "Security",    "value": sec_impact},
                    {"title": "Privacy",     "value": prv_impact},
                    {"title": "Update ID",   "value": (update_id or data.get("update_id", "?"))[:20]},
                    {"title": "Task ID",     "value": task_id[:12]},
                ],
            },
            {
                "type": "TextBlock",
                "text": f"**Changelog:** {changelog}" if changelog else "No changelog provided.",
                "wrap": True,
                "color": impact_color,
            },
        ]

        if diff_lines:
            body.append({
                "type": "TextBlock",
                "text": "**Diff preview:**\n" + "\n".join(f"`{ln}`" for ln in diff_lines),
                "wrap": True,
                "fontType": "Monospace",
            })

        if canary:
            body.append({"type": "TextBlock", "text": f"🐤 **Canary plan:** {canary}", "wrap": True})

        if rollback:
            body.append({"type": "TextBlock", "text": f"↩️ **Rollback target:** {rollback}", "wrap": True})

        if evidence:
            body.append({
                "type": "FactSet",
                "facts": [{"title": f"Evidence {i + 1}", "value": str(e)} for i, e in enumerate(evidence)],
            })

    # ── Scan / evaluate summary ────────────────────────────────────────────────
    elif action in ("scan", "evaluate_proposal"):
        blocked      = data.get("blocked", [])
        proposal_id  = data.get("proposal_id", "")
        succeeded    = data.get("succeeded")
        reason       = data.get("blocked_reason", "")

        facts = [{"title": "Task ID", "value": task_id[:12]}]
        if action == "scan":
            facts += [
                {"title": "Scanned tasks",    "value": str(data.get("scanned_tasks", 0))},
                {"title": "Signals detected", "value": str(data.get("signals_detected", 0))},
                {"title": "Proposals found",  "value": str(data.get("proposals_found", 0))},
                {"title": "Updates queued",   "value": str(len(update_ids))},
            ]
        else:
            facts += [
                {"title": "Proposal",  "value": proposal_id[:20]},
                {"title": "Succeeded", "value": "Yes" if succeeded else "No"},
            ]
            if reason:
                facts.append({"title": "Blocked reason", "value": reason[:120]})

        body.append({"type": "FactSet", "facts": facts})

        if blocked:
            body.append({
                "type": "TextBlock",
                "text": f"⚠️ Blocked: {'; '.join(blocked[:3])}",
                "color": "Warning",
                "wrap": True,
            })

    # ── Rollback result ────────────────────────────────────────────────────────
    elif action == "rollback":
        component  = data.get("component", "?")
        restored   = data.get("restored_to", "?")
        err        = data.get("error", "")
        body.append({
            "type": "FactSet",
            "facts": [
                {"title": "Component",   "value": component},
                {"title": "Restored to", "value": restored},
                {"title": "Status",      "value": "Error: " + err if err else "Rolled back"},
                {"title": "Task ID",     "value": task_id[:12]},
            ],
        })

    # ── Governance notice ──────────────────────────────────────────────────────
    body.append({
        "type": "TextBlock",
        "text": (
            "⚖️ **ARIA Governance**: ARIA may only PROPOSE updates. "
            "Activation requires explicit T4 human approval. "
            "Constitutional rules are enforced before any update is queued."
        ),
        "wrap": True,
        "size": "Small",
        "color": "Accent",
    })

    # Determine the specific update_id for single-update actions.
    # For compare_update and evaluate_proposal there is exactly one update.
    # For scan/list (non-list_pending), include the first queued update_id.
    action_update_id = (
        data.get("update_id")
        or (update_ids[0] if update_ids else None)
        or ""
    )

    # For list_pending the per-update Containers above carry all action buttons;
    # only add global footer actions for single-update flows.
    if action == "list_pending":
        card_actions: list = []
    else:
        card_actions = [
            {
                "type": "Action.Submit",
                "title": "✅ Approve Update",
                "style": "positive",
                "data": {
                    "aria_action":          "approve",
                    "aria_source":          "evolution_card",
                    "task_id":              task_id,
                    "evolution_update_id":  action_update_id,
                },
            },
            {
                "type": "Action.Submit",
                "title": "❌ Reject Update",
                "style": "destructive",
                "data": {
                    "aria_action":          "reject",
                    "aria_source":          "evolution_card",
                    "task_id":              task_id,
                    "evolution_update_id":  action_update_id,
                },
            },
        ]
        # Add "Promote Canary → Active" button when the update is in canary status
        single_update_status = data.get("status", "")
        if single_update_status == "canary" or action == "compare_update":
            card_actions.append({
                "type": "Action.Submit",
                "title": "🚀 Promote Canary → Active",
                "style": "positive",
                "data": {
                    "aria_action":          "promote_canary",
                    "aria_source":          "evolution_card",
                    "task_id":              task_id,
                    "evolution_update_id":  action_update_id,
                },
            })

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
        "actions": card_actions,
    }


def _execute_jira_after_approval(task_id: str) -> Optional[dict]:
    """
    Execute Jira ticket creation immediately after T4 approval from a Teams card.

    Returns the created ticket dict on success, None on any failure.
    Callers MUST surface a failure to the user — never substitute a fabricated ticket.

    Real REST client integration arrives in V2 (needs credentials).
    """
    try:
        from aria.runtime.harness import execute, make_idem_key, ToolCall

        def _mock_create(_draft=None):
            return {
                "ticket_id": "AU-ENG-MOCK",
                "url":       "https://jira.amar-ujala.internal/browse/AU-ENG-MOCK",
                "status":    "created (mock — real Jira API integration arrives in V2)",
            }

        idem_key = make_idem_key(task_id, "jira_create", "teams_card_approval")
        call = ToolCall(
            task_id=task_id,
            tool_name="jira_create",
            action_tier="T4",
            dry_run=False,
            idem_key=idem_key,
        )
        result = execute(call, _mock_create)
        if result.success and result.output:
            return result.output
    except Exception:
        pass
    return None


def _execute_evolution_after_approval(update_id: str, approver: str) -> Optional[dict]:
    """
    Call UpdateManager.approve_update() when a Teams evolution card is approved.

    Returns {"update_id": ..., "status": "canary", "approver": ...} on success.
    Returns {"error": ...} on failure.
    Never raises — caller surfaces the outcome to the user.
    """
    if not update_id:
        return {"error": "No update_id in card payload — cannot approve."}
    try:
        from aria.nodes.evolution_node import get_update_manager
        mgr = get_update_manager()
        approved = mgr.approve_update(update_id, approver=approver)
        return {
            "update_id":  approved.update_id,
            "component":  approved.component_name,
            "version":    approved.semantic_version,
            "status":     approved.status.value,
            "approver":   approved.approver,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _execute_evolution_promote_canary(update_id: str) -> Optional[dict]:
    """
    Call UpdateManager.promote_canary() when a Teams canary card is promoted.

    Returns dict with update_id, component, version, status on success.
    Returns {"error": ...} on failure.  Never raises.
    """
    if not update_id:
        return {"error": "No update_id in card payload — cannot promote canary."}
    try:
        from aria.nodes.evolution_node import get_update_manager
        mgr = get_update_manager()
        promoted = mgr.promote_canary(update_id)
        return {
            "update_id": promoted.update_id,
            "component": promoted.component_name,
            "version":   promoted.semantic_version,
            "status":    promoted.status.value,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _execute_evolution_rejection(update_id: str, reason: str) -> Optional[dict]:
    """
    Call UpdateManager.reject_update() when a Teams evolution card is rejected.
    """
    if not update_id:
        return {"error": "No update_id in card payload — cannot reject."}
    try:
        from aria.nodes.evolution_node import get_update_manager
        mgr = get_update_manager()
        rejected = mgr.reject_update(update_id, reason=reason)
        return {
            "update_id": rejected.update_id,
            "status":    rejected.status.value,
        }
    except Exception as exc:
        return {"error": str(exc)}


# Task types that require safe platform_evidence before a card is published.
_EVIDENCE_REQUIRED_CARD_TYPES: frozenset[str] = frozenset({"kpi", "ci_cd"})


def _parse_platform_evidence(pe_json: Optional[str]) -> Optional[dict]:
    if not pe_json:
        return None
    try:
        return json.loads(pe_json)
    except Exception:
        return None


def _build_card(
    task_type: str,
    skill_output: Optional[str],
    task_id: str,
    platform_evidence_json: Optional[str] = None,
) -> Optional[dict]:
    """
    Parse skill output and build the right Adaptive Card schema.
    Returns None if output is a placeholder, unparseable, or evidence-gated.

    For kpi and ci_cd: returns None (falling back to gated text) when
    platform_evidence is absent or is_safe_to_surface=False.
    """
    if not skill_output or skill_output.startswith("["):
        return None
    try:
        data = json.loads(skill_output)
    except json.JSONDecodeError:
        return None

    evidenced = _parse_platform_evidence(platform_evidence_json)

    # Evidence gate — kpi and ci_cd cards require safe evidence
    if task_type in _EVIDENCE_REQUIRED_CARD_TYPES:
        if evidenced is None or not evidenced.get("is_safe_to_surface", False):
            return None  # let _handle_text_message fall back to response_text (gated)

    if task_type == "pr_review":
        return _build_pr_review_card(data, task_id)
    if task_type == "kpi":
        return _build_kpi_card(data, task_id, evidenced=evidenced)
    if task_type == "ci_cd":
        return _build_cicd_card(data, task_id, evidenced=evidenced)
    if task_type == "jira":
        return _build_jira_card(data, task_id)
    if task_type == "evolution":
        return _build_evolution_approval_card(data, task_id)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# ARIA Activity Handler
# ─────────────────────────────────────────────────────────────────────────────

class ARIAActivityHandler(ActivityHandler):
    """
    Microsoft Teams Activity Handler for ARIA.

    Handles:
      - on_message_activity   : @ARIA mention → run task → Adaptive Card reply
      - on_members_added_activity : welcome message when ARIA is added to a channel

    The handler is stateless — each message creates a fresh graph run.
    Session memory is stored in ARIA's memory fabric (aria.memory), not in Teams state.
    """

    def __init__(self):
        super().__init__()
        # Import graph lazily so bot can be imported without full LangGraph init
        self._graph = None

    def _get_graph(self):
        if self._graph is None:
            from aria.graph import aria_graph
            self._graph = aria_graph
        return self._graph

    async def on_message_activity(self, turn_context: TurnContext):
        # Adaptive Card Action.Submit sends a message activity with value payload
        value = turn_context.activity.value
        if isinstance(value, dict) and "aria_action" in value:
            await self._handle_card_action(turn_context, value)
            return
        # Normal text message — delegate to parent which routes to on_message_activity
        await self._handle_text_message(turn_context)

    async def _handle_card_action(self, turn_context: TurnContext, value: dict):
        """Handle Approve / Reject button presses from Adaptive Cards.

        Cards submit a task_id; the gate stores requests by request_id.
        We look up all pending requests for the task, then approve/reject each.
        """
        action  = value.get("aria_action")
        task_id = value.get("task_id", "unknown")
        if action not in ("approve", "reject", "promote_canary"):
            await turn_context.send_activity(
                MessageFactory.text(f"Unknown card action: {action}")
            )
            return
        from_name = (
            getattr(turn_context.activity.from_property, "name", None)
            or (turn_context.activity.from_property or {}).get("name", "teams-user")
        )
        evolution_update_id: str = value.get("evolution_update_id", "")
        aria_source: str = value.get("aria_source", "")

        # ── Guard: evolution card with missing update_id is always an error ───────
        # When aria_source marks this as an evolution card but evolution_update_id
        # is absent, refuse the action rather than falling through to the
        # governance path which could resolve an unrelated approval.
        if aria_source == "evolution_card" and not evolution_update_id:
            await turn_context.send_activity(
                MessageFactory.text(
                    "⚠️ Evolution card action received without an update ID. "
                    "The action has been blocked to prevent accidental approval "
                    "of an unrelated task. Please retry from the pending updates list."
                )
            )
            return

        # ── Evolution approval / promote path — direct UpdateManager call ────────
        # Evolution cards carry an explicit evolution_update_id. When present,
        # bypass the governance approval_gate (evolution uses UpdateManager's own
        # approval lifecycle) and call approve/reject/promote directly.
        if evolution_update_id:
            if action == "approve":
                result = _execute_evolution_after_approval(evolution_update_id, approver=from_name)
            elif action == "promote_canary":
                result = _execute_evolution_promote_canary(evolution_update_id)
            else:
                result = _execute_evolution_rejection(
                    evolution_update_id,
                    reason=f"Rejected via Teams card by {from_name}",
                )

            if result and "error" not in result:
                status    = result.get("status", "unknown")
                component = result.get("component", evolution_update_id[:16])
                version   = result.get("version", "")
                if action == "approve":
                    verb = "approved → canary"
                elif action == "promote_canary":
                    verb = "promoted → active"
                else:
                    verb = "rejected"
                await turn_context.send_activity(
                    MessageFactory.text(
                        f"✅ Update {verb} by {from_name}.\n"
                        f"**{component}** v{version} is now **{status}**."
                    )
                )
            else:
                err = (result or {}).get("error", "Unknown error")
                await turn_context.send_activity(
                    MessageFactory.text(
                        f"⚠️ Evolution update action failed: {err}\n"
                        f"Update ID: `{evolution_update_id[:20]}`"
                    )
                )
            return

        # ── Standard governance approval_gate path (Jira, PR, KPI, etc.) ───────
        try:
            from aria.governance import approval_gate
            pending = [r for r in approval_gate.get_for_task(task_id) if r.status == "pending"]
            if not pending:
                await turn_context.send_activity(
                    MessageFactory.text(
                        f"No pending approval found for task `{task_id[:12]}`. "
                        "It may have already been resolved."
                    )
                )
                return
            resolved = 0
            jira_attempted: bool = False
            jira_created: Optional[dict] = None
            for req in pending:
                if action == "approve":
                    updated = approval_gate.approve(req.request_id, approved_by=from_name)
                    if updated:
                        resolved += 1
                        # T4 jira_create — execute the ticket creation now, since the
                        # LangGraph run has already completed and cannot be resumed.
                        if req.tool_name == "jira_create":
                            jira_attempted = True
                            jira_created = _execute_jira_after_approval(task_id)
                else:
                    updated = approval_gate.reject(req.request_id, reason="Rejected via Teams card")
                    if updated:
                        resolved += 1

            if jira_attempted:
                if jira_created:
                    ticket_id  = jira_created.get("ticket_id", "AU-ENG-???")
                    ticket_url = jira_created.get("url", "")
                    await turn_context.send_activity(
                        MessageFactory.text(
                            f"✅ Jira ticket created by {from_name}.\n"
                            f"Ticket: **{ticket_id}**\n{ticket_url}"
                        )
                    )
                else:
                    await turn_context.send_activity(
                        MessageFactory.text(
                            f"⚠️ Jira ticket creation failed for task `{task_id[:12]}`.\n"
                            "The approval was recorded but the ticket was not created. "
                            "Please create the ticket manually or retry."
                        )
                    )
            else:
                verb = "approved" if action == "approve" else "rejected"
                await turn_context.send_activity(
                    MessageFactory.text(
                        f"Task `{task_id[:12]}`: {resolved} request(s) {verb} by {from_name}."
                    )
                )
        except Exception as e:
            await turn_context.send_activity(
                MessageFactory.text(f"Approval gate error: {e}")
            )

    async def _handle_text_message(self, turn_context: TurnContext):
        """
        Process an incoming Teams message.
        Strips @mention prefix, runs through ARIA graph, replies with Adaptive Card.
        """
        raw_text = turn_context.activity.text or ""

        # Strip the @ARIA mention tag (Teams adds <at>ARIA</at> prefix)
        import re
        raw_text = re.sub(r"<at>[^<]+</at>", "", raw_text).strip()

        if not raw_text:
            await turn_context.send_activity(
                MessageFactory.text("Hi! I'm ARIA. Tell me what to work on.")
            )
            return

        # Detect audience from channel context
        channel_data = turn_context.activity.channel_data or {}
        channel_name = (
            channel_data.get("teamsChannelId", "")
            or (turn_context.activity.conversation or {}).get("name", "")
        )
        from_name = (turn_context.activity.from_property or {}).get("name", "")
        audience  = _detect_audience(channel_name, from_name)

        # Send a typing indicator while ARIA works
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        # Run ARIA graph
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._get_graph().invoke({
                    "raw_input":   raw_text,
                    "task_status": "pending",
                    "messages":    [],
                    "steps_completed": [],
                    "audience":    audience,
                }),
            )

            task_type             = result.get("task_type", "general")
            skill_output          = result.get("skill_output")
            task_id               = result.get("task_id", "unknown")
            response_text         = result.get("response", "Task complete.")
            platform_evidence_json = result.get("platform_evidence")

            # Try to build an Adaptive Card; fall back to plain text.
            # For kpi/ci_cd: card is suppressed when evidence is absent/unsafe —
            # response_text (the gated withheld message from respond.py) is used instead.
            card_schema = _build_card(task_type, skill_output, task_id,
                                      platform_evidence_json=platform_evidence_json)
            if card_schema:
                # Register a generic T2 approval request for feedback cards.
                # SKIP for jira — jira_node already registered a T4 "jira_create" request;
                # adding a second T2 "jira" request causes double-approval confusion.
                if task_type != "jira":
                    try:
                        from aria.governance.approval_gate import request_approval as _req_approval
                        _req_approval(
                            task_id=task_id,
                            tool_name=task_type,
                            proposed_action=(
                                f"{task_type} recommendation — approve to accept, "
                                "reject to flag as incorrect"
                            ),
                            action_tier="T2",
                        )
                    except Exception:
                        pass  # non-fatal; card still renders, buttons will report no pending request
                attachment = {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content":     card_schema,
                }
                reply = Activity(
                    type=ActivityTypes.message,
                    attachments=[attachment],
                )
                await turn_context.send_activity(reply)
            else:
                await turn_context.send_activity(
                    MessageFactory.text(response_text)
                )

        except Exception as e:
            await turn_context.send_activity(
                MessageFactory.text(f"ARIA encountered an error: {e}")
            )

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        """Welcome message when ARIA is added to a channel."""
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "👋 Hi, I'm **ARIA** — your AI Engineer assistant.\n\n"
                        "Mention me with a task:\n"
                        "• `@ARIA Review my PR for the recommendation engine`\n"
                        "• `@ARIA CTR dropped 18% this week, investigate`\n"
                        "• `@ARIA Build failed on the notification service pipeline`"
                    )
                )
