"""
ARIA Voice Router — Week 26 (Voice MVP)

POST /voice/run
  Accepts a speech transcript from the browser (Web Speech API),
  routes it through ARIA's existing skill + governance infrastructure,
  and returns a structured response suitable for text-to-speech playback.

Governance constraints (non-negotiable):
  - Only T1/T2 (read-only, recommend) tasks are executed directly.
  - T3/T4 tasks (jira creation, PR comment posting) are NEVER executed
    automatically via voice. The response includes an approval_required flag
    and an explanation the user can act on in the full UI.
  - No approval is ever bypassed. No side-effect tool is ever called.
  - Dry-run mode is always active for any harness call made here.

This enforces the same governance contract as the Teams bot — voice is a
presentation layer, not an escalated permission layer.
"""
import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from aria.nodes.skill_nodes import (
    ci_cd_node,
    general_node,
    kpi_node,
    pr_review_node,
    qa_node,
)
from aria.nodes.skill_nodes import test_review_node as _test_review_node


# ── Request / response models ─────────────────────────────────────────────────

class VoiceRunRequest(BaseModel):
    transcript: str
    audience: str = "developer"
    data_sensitivity: str = "internal"


class VoiceRunResponse(BaseModel):
    task_id: str
    task_type: str
    skill_output: str                    # text sent to SpeechSynthesis
    approval_required: bool = False
    approval_message: Optional[str] = None   # shown when approval_required=True


# ── Read-only skill types allowed to execute via voice ────────────────────────
# Jira and PR comment posting are T3/T4 — blocked; user must approve in the UI.

_VOICE_ALLOWED_TYPES = frozenset([
    "kpi",
    "pr_review",
    "ci_cd",
    "qa",
    "test_review",
    "general",
    "unknown",
])

_VOICE_BLOCKED_TYPES = frozenset(["jira", "analytics_qa"])

_VOICE_BLOCKED_MESSAGE = (
    "I can prepare a draft or ticket for you, but I need your approval before "
    "taking any real action. Please review the request in the ARIA dashboard "
    "and approve it there. Voice cannot bypass the governance gate."
)


# ── Keyword router (same logic as nodes/router.py keyword fallback) ───────────

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "kpi":         ["kpi", "metric", "ctr", "drop", "anomaly", "analytics", "dashboard", "conversion", "engagement"],
    "pr_review":   ["pr", "pull request", "code review", "diff", "review this", "merge", "branch"],
    "ci_cd":       ["ci", "cd", "pipeline", "build", "deploy", "failing", "test run", "workflow"],
    "qa":          ["test case", "test suite", "coverage", "generate test", "write test", "qa"],
    "test_review": ["flak", "flaky", "intermittent", "test review", "review test"],
    "jira":        ["jira", "ticket", "issue", "story", "epic", "sprint", "create ticket"],
    "analytics_qa": ["crew", "analytics crew", "investigation crew"],
}


def _classify(transcript: str) -> str:
    lower = transcript.lower()
    for task_type, keywords in _TYPE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return task_type
    return "general"


# ── Minimal ARIAState builder ─────────────────────────────────────────────────

def _make_state(
    task_id: str,
    transcript: str,
    task_type: str,
    audience: str,
    data_sensitivity: str,
) -> dict:
    return {
        "task_id":             task_id,
        "raw_input":           transcript,
        "task_type":           task_type,
        "task_status":         "executing",
        "routing_reason":      f"voice:{task_type}",
        "steps_completed":     ["intake", "voice_router"],
        "skill_name":          None,
        "skill_output":        None,
        "response":            None,
        "messages":            [],
        "error":               None,
        "audience":            audience,
        "langsmith_run_id":    None,
        "routing_tier":        None,
        "complexity":          None,
        "approval_request_id": None,
        "data_sensitivity":    data_sensitivity,
        "execution_mode":      "dry_run",   # voice always dry-run for harness calls
        "token_budget":        None,
        "token_budget_used":   None,
        "platform_evidence":   None,        # populated by kpi_node / ci_cd_node
    }


# ── Evidence gate (mirrors respond.py gate for voice surface) ─────────────────

# Task types that require platform_evidence before voice can speak the result.
_VOICE_EVIDENCE_REQUIRED: frozenset[str] = frozenset({"kpi", "ci_cd"})


def _parse_platform_evidence(pe_json: Optional[str]) -> Optional[dict]:
    if not pe_json:
        return None
    try:
        import json as _json
        return _json.loads(pe_json)
    except Exception:
        return None


def _evidence_gate_spoken(
    result: dict,
    task_type: str,
) -> Optional[str]:
    """
    Returns a withheld message string if the evidence gate blocks publication,
    or None if the result may proceed to _extract_spoken().

    Same contract as respond.py: absent → withheld, is_safe_to_surface=False → withheld.
    """
    if task_type not in _VOICE_EVIDENCE_REQUIRED:
        return None  # gate not required for this type

    evidenced = _parse_platform_evidence(result.get("platform_evidence"))

    if evidenced is None:
        return (
            "I couldn't verify this answer with platform data. "
            "Platform evidence was unavailable. "
            "Please check the ARIA dashboard for details."
        )

    if not evidenced.get("is_safe_to_surface", False):
        blocked = evidenced.get("blocked_reason") or "Unsupported claims detected."
        return (
            f"I found an issue with this answer. {blocked} "
            "Please check the ARIA dashboard for the full evidence trail."
        )

    return None  # safe to surface


# ── Friendly spoken output from skill_output JSON ────────────────────────────

def _extract_spoken(skill_output: str, task_type: str) -> str:
    """
    Convert structured JSON skill output to a concise spoken summary.
    Falls back to a generic sentence if the JSON structure is unexpected.
    """
    import json
    try:
        data = json.loads(skill_output)
    except Exception:
        return skill_output[:300]

    if task_type == "kpi":
        summary = data.get("summary") or data.get("root_cause_hypothesis") or ""
        return f"KPI analysis: {summary}" if summary else "KPI investigation complete. Check the dashboard for details."

    if task_type == "pr_review":
        verdict = data.get("verdict") or data.get("risk_level") or ""
        return f"PR review: {verdict}" if verdict else "PR review complete. Check the dashboard for the full report."

    if task_type in ("ci_cd",):
        summary = data.get("failure_summary") or ""
        return f"CI/CD analysis: {summary}" if summary else "Pipeline analysis complete."

    if task_type in ("qa",):
        count = len(data.get("test_cases") or [])
        return f"Generated {count} test cases. See the dashboard for the full suite."

    if task_type in ("test_review",):
        findings = data.get("flakiness_verdict") or data.get("overall_health") or ""
        return f"Test review: {findings}" if findings else "Test review complete."

    return "Task completed. Check the ARIA dashboard for the full output."


# ── FastAPI router ────────────────────────────────────────────────────────────

router = APIRouter(prefix="/voice", tags=["voice"])

_SKILL_NODE_MAP = {
    "kpi":         kpi_node,
    "pr_review":   pr_review_node,
    "ci_cd":       ci_cd_node,
    "qa":          qa_node,
    "test_review": _test_review_node,
    "general":     general_node,
    "unknown":     general_node,
}


@router.post("/run", response_model=VoiceRunResponse)
def voice_run(req: VoiceRunRequest) -> VoiceRunResponse:
    """
    Accept a voice transcript, route to the appropriate read-only skill,
    and return a spoken summary.

    Governance contract:
      - T1/T2 tasks execute immediately (kpi, pr_review, ci_cd, qa, test_review, general).
      - T3/T4 tasks (jira, analytics crew) are refused with an approval_required flag.
        The voice layer never bypasses the governance gate.
    """
    task_id   = str(uuid.uuid4())
    task_type = _classify(req.transcript)

    # ── Governance gate: block T3/T4 task types ───────────────────────────────
    if task_type in _VOICE_BLOCKED_TYPES:
        return VoiceRunResponse(
            task_id=task_id,
            task_type=task_type,
            skill_output=_VOICE_BLOCKED_MESSAGE,
            approval_required=True,
            approval_message=(
                f"Voice cannot execute '{task_type}' tasks directly. "
                "Open the ARIA dashboard to review the draft and approve."
            ),
        )

    # ── Execute read-only skill ───────────────────────────────────────────────
    node_fn = _SKILL_NODE_MAP.get(task_type, general_node)
    state   = _make_state(
        task_id=task_id,
        transcript=req.transcript,
        task_type=task_type,
        audience=req.audience,
        data_sensitivity=req.data_sensitivity,
    )

    try:
        result = node_fn(state)

        # Evidence gate — kpi and ci_cd must have safe platform_evidence
        withheld = _evidence_gate_spoken(result, task_type)
        if withheld:
            return VoiceRunResponse(
                task_id=task_id,
                task_type=task_type,
                skill_output=withheld,
            )

        spoken = _extract_spoken(result.get("skill_output") or "", task_type)
        return VoiceRunResponse(
            task_id=task_id,
            task_type=task_type,
            skill_output=spoken,
        )
    except Exception as exc:
        return VoiceRunResponse(
            task_id=task_id,
            task_type=task_type,
            skill_output=f"I encountered an issue: {exc}. Please try again.",
        )
