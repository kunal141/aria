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


def _build_kpi_card(data: dict, task_id: str) -> dict:
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

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
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
        ],
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


def _build_card(task_type: str, skill_output: Optional[str], task_id: str) -> Optional[dict]:
    """
    Parse skill output and build the right Adaptive Card schema.
    Returns None if output is a placeholder or unparseable.
    """
    if not skill_output or skill_output.startswith("["):
        return None
    try:
        data = json.loads(skill_output)
    except json.JSONDecodeError:
        return None

    if task_type == "pr_review":
        return _build_pr_review_card(data, task_id)
    if task_type == "kpi":
        return _build_kpi_card(data, task_id)
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
        if action not in ("approve", "reject"):
            await turn_context.send_activity(
                MessageFactory.text(f"Unknown card action: {action}")
            )
            return
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
            from_name = (turn_context.activity.from_property or {}).get("name", "teams-user")
            resolved = 0
            for req in pending:
                if action == "approve":
                    updated = approval_gate.approve(req.request_id, approved_by=from_name)
                else:
                    updated = approval_gate.reject(req.request_id, reason="Rejected via Teams card")
                if updated:
                    resolved += 1
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

            task_type    = result.get("task_type", "general")
            skill_output = result.get("skill_output")
            task_id      = result.get("task_id", "unknown")
            response_text = result.get("response", "Task complete.")

            # Try to build an Adaptive Card; fall back to plain text
            card_schema = _build_card(task_type, skill_output, task_id)
            if card_schema:
                # Register approval request only when a card with Approve/Reject buttons exists
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
