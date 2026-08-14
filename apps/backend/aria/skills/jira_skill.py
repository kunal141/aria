"""
Jira / Delivery Management Skill — Week 20

Produces a structured Jira ticket draft from natural language:
  - Title + description + acceptance criteria (Given/When/Then)
  - Type inference (bug / task / story / epic / sub-task)
  - Priority recommendation
  - Blocker detection
  - Story point estimate (tasks/stories only)

V1 read-only contract:
  This skill NEVER calls the Jira API directly.
  It always returns a draft for human review (Action Tier T3).
  Actual ticket creation (T4, Execute-with-Approval) arrives in Week 21
  when the Runtime Harness provides idempotency keys and a dry-run mode.

Domain context: Amar Ujala engineering projects
  AU-ENG  : Engineering (recommendation, notification, CMS, analytics, feed)
  AU-QA   : Quality Assurance
  AU-DATA : Data Science / Analytics
  AU-OPS  : DevOps / Infrastructure
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

import aria.config
from aria.config import get_routed_llm, has_llm
from aria.skills.json_output import parse_json_object
from aria.tracing import traceable

# ── Sub-models ────────────────────────────────────────────────────────────────

class JiraTicketDraft(BaseModel):
    title:               str
    description:         str
    ticket_type:         Literal["bug", "task", "story", "epic", "sub-task"]
    priority:            Literal["critical", "high", "medium", "low"]
    acceptance_criteria: list[str]
    labels:              list[str]
    story_points:        Optional[int] = None   # None for bugs
    suggested_assignee:  str = ""
    suggested_sprint:    str = ""
    blocker_for:         list[str] = []         # other tickets/services this blocks
    project_key:         str = "AU-ENG"


# ── Input Schema ──────────────────────────────────────────────────────────────

class JiraInput(BaseModel):
    raw_input:        str  = Field(..., description="Natural language description of the ticket or request")
    task_id:          str  = Field(..., description="Unique task identifier from ARIAState")
    project_key:      str  = Field(default="AU-ENG", description="Target Jira project key")
    read_only:        bool = Field(default=True,  description="V1: always True — never calls Jira API")
    data_sensitivity: str  = Field(default="internal",  description="Routing: public/internal/confidential/restricted")
    audience:         str  = Field(default="developer", description="Routing: developer/manager/leadership")


# ── Output Schema ─────────────────────────────────────────────────────────────

class JiraOutput(BaseModel):
    ticket_draft:      JiraTicketDraft
    action_taken:      Literal["draft_created", "would_require_approval"]
    approval_required: bool   # True only if user explicitly requests creation (T4)
    blocker_detected:  bool
    sprint_impact:     str    # one sentence: what this means for current sprint/release
    version:           str = "v1"


# ── Create-intent detection ───────────────────────────────────────────────────

# Explicit phrases that signal the user wants an actual ticket created, not just a draft.
# T4 (Execute-with-Approval) is activated only for these; everything else stays T3 (Draft).
_CREATE_KEYWORDS = frozenset([
    "create ticket", "file a ticket", "file ticket", "create a ticket",
    "submit ticket", "create now", "create it now", "please create",
    "go ahead and create", "actually create",
])


def _wants_create(raw_input: str) -> bool:
    """Return True if the input explicitly requests ticket creation (not just a draft)."""
    lower = raw_input.lower()
    return any(kw in lower for kw in _CREATE_KEYWORDS)


# ── Skill Prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """You are ARIA, a delivery management specialist for Amar Ujala — India's largest Hindi media platform.

You create structured Jira ticket drafts from engineering team requests.

Amar Ujala engineering projects:
  AU-ENG  : Engineering — recommendation engine, notification service, CMS ingestion, analytics pipeline, feed ranking
  AU-QA   : Quality Assurance
  AU-DATA : Data Science / Analytics
  AU-OPS  : DevOps / Infrastructure

Ticket type rules:
  bug      → "not working", "broken", "crash", "error", "failing", "regression"
  task     → "implement", "add", "update", "refactor", "migrate", "improve"
  story    → "as a user", "so that", "user story", "feature"
  epic     → "initiative", "quarter", "OKR", "milestone", multiple related features
  sub-task → "subtask", "part of", "depends on #"

Priority rules:
  critical → production incident, data loss, main branch blocked
  high     → sprint blocker, customer-facing regression, release blocked
  medium   → non-blocking improvement, tech debt with known impact
  low      → nice-to-have, cosmetic, future sprint

Story points (tasks/stories only; null for bugs):
  1 → < 2 hours   2 → 2–4 hours   3 → 1 day   5 → 2–3 days   8 → 1 week   13 → > 1 week

Respond with ONLY valid JSON:
{
  "ticket_draft": {
    "title": "concise action-oriented title under 60 chars",
    "description": "what the ticket involves and why it matters — 2–4 sentences",
    "ticket_type": "bug|task|story|epic|sub-task",
    "priority": "critical|high|medium|low",
    "acceptance_criteria": ["Given ... When ... Then ...", "..."],
    "labels": ["service-name", "component"],
    "story_points": null,
    "suggested_assignee": "role or team name if inferable, else empty string",
    "suggested_sprint": "current|next|empty string",
    "blocker_for": [],
    "project_key": "AU-ENG"
  },
  "action_taken": "draft_created",
  "approval_required": false,
  "blocker_detected": false,
  "sprint_impact": "one sentence on sprint/release impact, or 'No immediate sprint impact' if none"
}

Rules:
- acceptance_criteria: 3–5 Given/When/Then statements
- labels: 2–4 from: bug, feature, tech-debt, recommendation, notification, cms, analytics, feed, infra, performance, security
- approval_required: true only if the user explicitly asks to CREATE the ticket immediately
- blocker_detected: true if the work blocks a sprint, release, or in-flight ticket"""


# ── Skill Function ─────────────────────────────────────────────────────────────

@traceable(
    run_type="chain",
    name="jira_skill_v1",
    tags=["skill", "jira", "aria"],
)
def run(input: JiraInput) -> JiraOutput:
    wants_create = _wants_create(input.raw_input)

    if not has_llm():
        return JiraOutput(
            ticket_draft=JiraTicketDraft(
                title="Fix Elasticsearch connection timeout in recommendation-service CI",
                description=(
                    "Integration tests for the recommendation service are failing in CI with "
                    "ConnectionRefusedError on port 9200. The Elasticsearch service container "
                    "is not started before tests run, causing all retrieval tests to fail. "
                    "This blocks the current feature branch pipeline."
                ),
                ticket_type="bug",
                priority="high",
                acceptance_criteria=[
                    "Given CI runs the recommendation-service test suite, "
                    "When tests require Elasticsearch, "
                    "Then an elasticsearch container is started via GitHub Actions services config",
                    "Given the fix is applied, "
                    "When tests run on any branch, "
                    "Then the integration suite passes without ConnectionRefusedError",
                    "Given the fix is merged, "
                    "When pipeline runs, "
                    "Then no regression is introduced in previously passing tests",
                ],
                labels=["bug", "recommendation", "infra"],
                story_points=None,
                suggested_assignee="backend-engineer",
                suggested_sprint="current",
                project_key=input.project_key,
            ),
            action_taken="would_require_approval" if wants_create else "draft_created",
            approval_required=wants_create,
            blocker_detected=True,
            sprint_impact="Blocks the recommendation-service feature pipeline until the CI fix is merged.",
        )

    from langchain_core.messages import SystemMessage
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    chain = (
        ChatPromptTemplate.from_messages([
            SystemMessage(content=_SYSTEM),
            ("human", "{raw_input}"),
        ])
        | get_routed_llm(
            task_type="jira",
            data_sensitivity=input.data_sensitivity,
            audience=input.audience,
            temperature=0,
        )
        | StrOutputParser()
    )

    raw = chain.invoke({"raw_input": f"[Project: {input.project_key}]\n\n{input.raw_input}"})

    try:
        data = parse_json_object(raw)
        draft_data = data.get("ticket_draft", {})
        draft_data.setdefault("project_key", input.project_key)
        # Keyword check overrides LLM decision — explicit create intent always triggers T4
        llm_approval = data.get("approval_required", False)
        approval_required = llm_approval or wants_create
        return JiraOutput(
            ticket_draft=JiraTicketDraft(**draft_data),
            action_taken="would_require_approval" if approval_required else "draft_created",
            approval_required=approval_required,
            blocker_detected=data.get("blocker_detected", False),
            sprint_impact=data.get("sprint_impact", ""),
        )
    except Exception as exc:
        error_type = type(exc).__name__
        return JiraOutput(
            ticket_draft=JiraTicketDraft(
                title="Jira ticket draft — parse error",
                description=f"Model output invalid ({error_type}; details redacted).",
                ticket_type="task",
                priority="low",
                acceptance_criteria=[],
                labels=["aria-parse-error"],
            ),
            action_taken="draft_created",
            approval_required=False,
            blocker_detected=False,
            sprint_impact="",
        )


# ── Eval-Lite ─────────────────────────────────────────────────────────────────

EVAL_RUBRIC = """
Jira Skill — Eval Rubric (1–5)

5 — Title is action-oriented and under 60 chars. AC uses Given/When/Then for all items.
    Priority and type are correctly inferred from context. Labels are service-specific.
    blocker_detected correctly set. sprint_impact is specific and actionable.

4 — Title good. One AC step is vague. Priority correct. Labels slightly generic.

3 — Title describes problem but not action. AC present but not Given/When/Then format.
    Priority reasonable. sprint_impact is "No immediate sprint impact" when it clearly has one.

2 — Title too long or unclear. Only one AC item. Priority miscalibrated.

1 — Generic Jira output with no Amar Ujala context. No service labels. AC absent.
"""

GOLDEN_EXAMPLES = [
    {
        "input": "The recommendation service tests are failing in CI — ConnectionRefusedError on Elasticsearch",
        "expected_type": "bug",
        "expected_priority": "high",
        "expected_blocker": True,
        "notes": "CI failure on recommendation service = high priority bug, not a task",
    },
    {
        "input": "Add rate limiting to the notification service push endpoint — getting APNS throttle errors",
        "expected_type": "task",
        "expected_priority": "high",
        "expected_blocker": False,
        "notes": "Implementation work = task; high priority due to APNS impact",
    },
    {
        "input": "Migrate CMS ingestion to async Elasticsearch client for better throughput",
        "expected_type": "task",
        "expected_priority": "medium",
        "expected_blocker": False,
        "notes": "Tech debt improvement = medium priority task",
    },
    {
        "input": "Sprint blocker: analytics pipeline ETL job crashing with OOM on large article batches",
        "expected_type": "bug",
        "expected_priority": "critical",
        "expected_blocker": True,
        "notes": "Explicit sprint blocker + OOM in prod = critical; blocker_detected must be True",
    },
    {
        "input": "Create an epic for Q3 feed personalisation improvements across recommendation and feed ranking",
        "expected_type": "epic",
        "expected_priority": "medium",
        "expected_blocker": False,
        "notes": "Quarter-scoped multi-feature initiative = epic",
    },
]
