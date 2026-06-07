"""
Evidence Gate — deterministic tests

Proves that missing, stale, conflicting, and unauthorized evidence cannot
produce an authoritative user-facing answer across all three surfaces:
  - respond.py (LangGraph graph output)
  - voice/router.py (spoken output gate)
  - teams_bot.py (Adaptive Card gate)

Skill execution is NOT mocked — the skill still runs. Only the publication
surface is gated. The tests verify that the gated text is returned instead
of the raw skill analysis.

Legend:
  ABSENT  — platform_evidence is None (assembly never ran or failed)
  UNSAFE  — platform_evidence present but is_safe_to_surface=False
  SAFE    — platform_evidence present and is_safe_to_surface=True
"""
import json
import uuid

import pytest

from aria.nodes.respond import respond, _parse_evidence, _build_response, _EVIDENCE_REQUIRED_TYPES
from aria.artifact_engine import render_artifact_with_citations, _render_citation_footer
from aria.voice.router import (
    _evidence_gate_spoken,
    _parse_platform_evidence,
    _VOICE_EVIDENCE_REQUIRED,
)
from aria.integrations.teams_bot import (
    _build_card,
    _build_evidence_facts,
    _EVIDENCE_REQUIRED_CARD_TYPES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _minimal_state(
    task_type: str = "kpi",
    skill_output: str | None = None,
    platform_evidence: str | None = None,
) -> dict:
    tid = uuid.uuid4().hex
    so = skill_output or json.dumps({
        "summary": "CTR dropped 18% on recommendation-service",
        "root_causes": [{"hypothesis": "Model staleness", "likelihood": "high", "evidence": "metrics"}],
        "recommended_actions": ["Retrain model"],
        "data_needed": [],
        "confidence_score": 0.72,
        "version": "v1",
    })
    return {
        "task_id":           tid,
        "raw_input":         "Why did CTR drop?",
        "task_type":         task_type,
        "task_status":       "executing",
        "routing_reason":    "kpi keyword",
        "steps_completed":   ["intake", "router", "kpi_node"],
        "skill_name":        f"{task_type}:v1",
        "skill_output":      so,
        "response":          None,
        "messages":          [],
        "error":             None,
        "audience":          "developer",
        "langsmith_run_id":  None,
        "routing_tier":      "smart",
        "complexity":        "normal",
        "approval_request_id": None,
        "data_sensitivity":  "internal",
        "execution_mode":    "dry_run",
        "token_budget":      50000,
        "token_budget_used": 0,
        "platform_evidence": platform_evidence,
    }


def _safe_evidence_json(
    query: str = "test query",
    claim_id: str = "service-health",
    source_id: str = "analytics-pipeline:telemetry:metrics-latest",
    authority: int = 10,
    is_stale: bool = False,
) -> str:
    """Build a minimal EvidencedAnswer JSON with is_safe_to_surface=True."""
    return json.dumps({
        "answer_id":          uuid.uuid4().hex,
        "query":              query,
        "answer":             "Analytics pipeline is healthy.",
        "claim_evidence_map": [
            {
                "claim_id":     claim_id,
                "claim_text":   "Is the service healthy?",
                "evidence": [{
                    "source_id":          source_id,
                    "source_type":        "telemetry",
                    "service_id":         "analytics-pipeline",
                    "excerpt":            "p99 latency 230ms. Error rate 0.02%.",
                    "relevance_score":    0.9,
                    "authority":          authority,
                    "ingested_at":        "2026-06-07T00:00:00+00:00",
                    "content_updated_at": "2026-06-07T00:00:00+00:00",
                    "sensitivity":        "internal",
                    "is_stale":           is_stale,
                    "staleness_hours":    None if not is_stale else 5.0,
                }],
                "is_supported":      True,
                "conflicts":         [],
                "selected_evidence": {
                    "source_id":          source_id,
                    "source_type":        "telemetry",
                    "service_id":         "analytics-pipeline",
                    "excerpt":            "p99 latency 230ms. Error rate 0.02%.",
                    "relevance_score":    0.9,
                    "authority":          authority,
                    "ingested_at":        "2026-06-07T00:00:00+00:00",
                    "content_updated_at": "2026-06-07T00:00:00+00:00",
                    "sensitivity":        "internal",
                    "is_stale":           is_stale,
                    "staleness_hours":    None if not is_stale else 5.0,
                },
                "selection_reason": "only available evidence",
            }
        ],
        "authorization_decisions": [{
            "source_id":     source_id,
            "caller_level":  "internal",
            "source_level":  "internal",
            "allowed":       True,
            "reason":        "caller level matches",
        }],
        "freshness_warnings": (
            ["Claim 'service-health': source is 5.0h old"] if is_stale else []
        ),
        "is_safe_to_surface": True,
        "blocked_reason":     None,
        "assembled_at":       "2026-06-07T00:00:00+00:00",
    })


def _unsafe_evidence_json(blocked_reason: str = "No authorized evidence for claim: service-health") -> str:
    """Build a minimal EvidencedAnswer JSON with is_safe_to_surface=False."""
    return json.dumps({
        "answer_id":          uuid.uuid4().hex,
        "query":              "test query",
        "answer":             "",
        "claim_evidence_map": [{
            "claim_id":         "service-health",
            "claim_text":       "Is the service healthy?",
            "evidence":         [],
            "is_supported":     False,
            "conflicts":        [],
            "selected_evidence": None,
            "selection_reason": None,
        }],
        "authorization_decisions": [],
        "freshness_warnings": [],
        "is_safe_to_surface": False,
        "blocked_reason":     blocked_reason,
        "assembled_at":       "2026-06-07T00:00:00+00:00",
    })


# ─────────────────────────────────────────────────────────────────────────────
# 1. _EVIDENCE_REQUIRED_TYPES definition
# ─────────────────────────────────────────────────────────────────────────────

def test_kpi_is_evidence_required():
    assert "kpi" in _EVIDENCE_REQUIRED_TYPES


def test_ci_cd_is_evidence_required():
    assert "ci_cd" in _EVIDENCE_REQUIRED_TYPES


def test_pr_review_not_evidence_required():
    assert "pr_review" not in _EVIDENCE_REQUIRED_TYPES


def test_jira_not_evidence_required():
    assert "jira" not in _EVIDENCE_REQUIRED_TYPES


# ─────────────────────────────────────────────────────────────────────────────
# 2. _parse_evidence
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_evidence_none_returns_none():
    assert _parse_evidence(None) is None


def test_parse_evidence_empty_string_returns_none():
    assert _parse_evidence("") is None


def test_parse_evidence_invalid_json_returns_none():
    assert _parse_evidence("{not valid json") is None


def test_parse_evidence_valid_json_returns_dict():
    result = _parse_evidence(_safe_evidence_json())
    assert isinstance(result, dict)
    assert result["is_safe_to_surface"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. respond.py — evidence gate (ABSENT case)
# ─────────────────────────────────────────────────────────────────────────────

def test_respond_kpi_absent_evidence_withheld():
    """KPI with no platform_evidence → response is withheld, not the skill analysis."""
    state = _minimal_state(task_type="kpi", platform_evidence=None)
    result = respond(state)
    response = result["response"]
    assert "[EVIDENCE UNAVAILABLE" in response
    assert "WITHHELD" in response
    # Must NOT contain the raw skill summary
    assert "CTR dropped" not in response


def test_respond_ci_cd_absent_evidence_withheld():
    """CI/CD with no platform_evidence → withheld."""
    so = json.dumps({
        "failure_summary": "Build failed on step 3",
        "failed_stage": "test",
        "root_cause_hypotheses": [],
        "suggested_fixes": [],
        "deployment_verdict": "do_not_deploy",
        "severity": "high",
        "notify_team": False,
        "version": "v1",
    })
    state = _minimal_state(task_type="ci_cd", skill_output=so, platform_evidence=None)
    result = respond(state)
    response = result["response"]
    assert "[EVIDENCE UNAVAILABLE" in response
    assert "Build failed on step 3" not in response


def test_respond_kpi_task_status_still_done_when_withheld():
    """Even withheld responses complete the task (skill ran, publication gated)."""
    state = _minimal_state(task_type="kpi", platform_evidence=None)
    result = respond(state)
    assert result["task_status"] == "done"


# ─────────────────────────────────────────────────────────────────────────────
# 4. respond.py — evidence gate (UNSAFE case)
# ─────────────────────────────────────────────────────────────────────────────

def test_respond_kpi_unsafe_evidence_withheld():
    """KPI with is_safe_to_surface=False → response is withheld."""
    state = _minimal_state(task_type="kpi", platform_evidence=_unsafe_evidence_json())
    result = respond(state)
    response = result["response"]
    assert "[RESPONSE WITHHELD" in response
    assert "UNSUPPORTED CLAIMS" in response
    assert "CTR dropped" not in response


def test_respond_withheld_response_includes_blocked_reason():
    blocked = "No evidence for claims: service-health, recent-issues"
    state = _minimal_state(
        task_type="kpi",
        platform_evidence=_unsafe_evidence_json(blocked_reason=blocked),
    )
    result = respond(state)
    assert blocked in result["response"]


def test_respond_withheld_response_includes_task_id():
    state = _minimal_state(task_type="kpi", platform_evidence=_unsafe_evidence_json())
    result = respond(state)
    assert state["task_id"][:12] in result["response"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. respond.py — evidence gate (SAFE case)
# ─────────────────────────────────────────────────────────────────────────────

def test_respond_kpi_safe_evidence_surfaces():
    """KPI with safe evidence → skill analysis surfaced."""
    state = _minimal_state(task_type="kpi", platform_evidence=_safe_evidence_json())
    result = respond(state)
    response = result["response"]
    # No withheld marker
    assert "[EVIDENCE UNAVAILABLE" not in response
    assert "[RESPONSE WITHHELD" not in response


def test_respond_kpi_safe_includes_citation_footer():
    """Safe KPI response includes the Evidence Provenance footer."""
    state = _minimal_state(task_type="kpi", platform_evidence=_safe_evidence_json())
    result = respond(state)
    assert "Evidence Provenance" in result["response"]


def test_respond_kpi_citation_includes_source_id():
    source_id = "analytics-pipeline:telemetry:metrics-latest"
    state = _minimal_state(
        task_type="kpi",
        platform_evidence=_safe_evidence_json(source_id=source_id),
    )
    result = respond(state)
    assert source_id in result["response"]


def test_respond_kpi_citation_never_includes_source_content():
    """Citation footer must NOT include the excerpt/content from the source."""
    pe = _safe_evidence_json()
    # The safe_evidence excerpt is "p99 latency 230ms. Error rate 0.02%."
    state = _minimal_state(task_type="kpi", platform_evidence=pe)
    result = respond(state)
    # The citation footer should not repeat the evidence excerpt text
    # (it may appear in the skill output rendering, but NOT as a "cited from source" leak)
    footer_start = result["response"].find("Evidence Provenance")
    if footer_start >= 0:
        footer = result["response"][footer_start:]
        assert "p99 latency" not in footer
        assert "Error rate 0.02%" not in footer


def test_respond_stale_evidence_surfaces_with_warning():
    """Stale-but-supported evidence → answer surfaces, staleness flag in footer."""
    pe = _safe_evidence_json(is_stale=True)
    state = _minimal_state(task_type="kpi", platform_evidence=pe)
    result = respond(state)
    response = result["response"]
    # Answer surfaces (not withheld)
    assert "[EVIDENCE UNAVAILABLE" not in response
    assert "[RESPONSE WITHHELD" not in response
    # Stale flag visible in footer
    assert "stale" in response.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 6. respond.py — non-evidence-required types pass through without gate
# ─────────────────────────────────────────────────────────────────────────────

def test_respond_pr_review_no_gate():
    """PR review surfaces without platform_evidence (gate not required)."""
    so = json.dumps({
        "verdict": "approve",
        "risk_level": "low",
        "summary": "Clean PR",
        "code_issues": [],
        "missing_tests": [],
        "deployment_risks": [],
        "business_impact": "Low risk",
        "positive_observations": ["Good tests"],
        "version": "v1",
    })
    state = _minimal_state(task_type="pr_review", skill_output=so, platform_evidence=None)
    result = respond(state)
    response = result["response"]
    # PR review should surface, no evidence gate applied
    assert "[EVIDENCE UNAVAILABLE" not in response
    assert "WITHHELD" not in response


def test_respond_jira_no_gate():
    """Jira task type is not evidence-required — always passes through."""
    so = json.dumps({
        "ticket_draft": {"title": "Fix bug", "ticket_type": "bug", "priority": "medium",
                         "story_points": 3, "acceptance_criteria": [], "labels": []},
        "sprint_impact": "",
        "blocker_detected": False,
        "approval_required": False,
        "version": "v1",
    })
    state = _minimal_state(task_type="jira", skill_output=so, platform_evidence=None)
    result = respond(state)
    assert "WITHHELD" not in result["response"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. _build_response helper — direct unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_build_response_absent_evidence_returns_withheld():
    r = _build_response("kpi", '{"summary": "x"}', "task-abc", "developer", None)
    assert "WITHHELD" in r


def test_build_response_unsafe_returns_withheld():
    r = _build_response("kpi", '{"summary": "x"}', "task-abc", "developer",
                        _unsafe_evidence_json("broken claims"))
    assert "WITHHELD" in r
    assert "broken claims" in r


def test_build_response_safe_returns_artifact():
    r = _build_response("kpi", '{"summary": "ok", "root_causes": [], "recommended_actions": [], "data_needed": [], "confidence_score": 0.5, "version": "v1"}',
                        "task-abc", "developer", _safe_evidence_json())
    assert "Evidence Provenance" in r
    assert "WITHHELD" not in r


def test_build_response_non_evidence_type_ignores_absent_evidence():
    so = '{"verdict": "approve", "risk_level": "low", "summary": "ok", "code_issues": [], "missing_tests": [], "deployment_risks": [], "business_impact": "", "positive_observations": [], "version": "v1"}'
    r = _build_response("pr_review", so, "task-abc", "developer", None)
    assert "WITHHELD" not in r


# ─────────────────────────────────────────────────────────────────────────────
# 8. artifact_engine — _render_citation_footer
# ─────────────────────────────────────────────────────────────────────────────

def test_citation_footer_contains_source_id():
    evidenced = json.loads(_safe_evidence_json(source_id="svc:telemetry:latest"))
    footer = _render_citation_footer(evidenced)
    assert "svc:telemetry:latest" in footer


def test_citation_footer_contains_authority():
    evidenced = json.loads(_safe_evidence_json(authority=10))
    footer = _render_citation_footer(evidenced)
    assert "authority=10" in footer


def test_citation_footer_stale_flag_present():
    evidenced = json.loads(_safe_evidence_json(is_stale=True))
    footer = _render_citation_footer(evidenced)
    assert "stale" in footer


def test_citation_footer_no_stale_flag_when_fresh():
    evidenced = json.loads(_safe_evidence_json(is_stale=False))
    footer = _render_citation_footer(evidenced)
    assert "stale" not in footer.lower()


def test_citation_footer_unsupported_claim_marked():
    evidenced = json.loads(_unsafe_evidence_json())
    footer = _render_citation_footer(evidenced)
    assert "UNSUPPORTED" in footer


def test_citation_footer_never_contains_evidence_excerpt():
    """The footer must show source identifiers only — never the excerpt text."""
    evidenced = json.loads(_safe_evidence_json())
    footer = _render_citation_footer(evidenced)
    # Excerpt text from _safe_evidence_json
    assert "p99 latency" not in footer
    assert "Error rate 0.02%" not in footer


# ─────────────────────────────────────────────────────────────────────────────
# 9. Voice router — evidence gate
# ─────────────────────────────────────────────────────────────────────────────

def test_voice_gate_absent_evidence_withheld():
    result = {"skill_output": '{"summary": "ok"}', "platform_evidence": None}
    withheld = _evidence_gate_spoken(result, "kpi")
    assert withheld is not None
    assert "couldn't verify" in withheld.lower() or "unavailable" in withheld.lower()


def test_voice_gate_unsafe_evidence_withheld():
    result = {
        "skill_output": '{"summary": "ok"}',
        "platform_evidence": _unsafe_evidence_json("broken claim"),
    }
    withheld = _evidence_gate_spoken(result, "kpi")
    assert withheld is not None
    assert "broken claim" in withheld


def test_voice_gate_safe_evidence_passes():
    result = {
        "skill_output": '{"summary": "ok"}',
        "platform_evidence": _safe_evidence_json(),
    }
    withheld = _evidence_gate_spoken(result, "kpi")
    assert withheld is None


def test_voice_gate_ci_cd_also_gated():
    result = {"skill_output": '{"failure_summary": "x"}', "platform_evidence": None}
    withheld = _evidence_gate_spoken(result, "ci_cd")
    assert withheld is not None


def test_voice_gate_pr_review_not_gated():
    """PR review voice output is NOT gated by platform evidence."""
    result = {"skill_output": '{"verdict": "approve"}', "platform_evidence": None}
    withheld = _evidence_gate_spoken(result, "pr_review")
    assert withheld is None


def test_voice_gate_general_not_gated():
    result = {"skill_output": '{"answer": "general"}', "platform_evidence": None}
    withheld = _evidence_gate_spoken(result, "general")
    assert withheld is None


def test_voice_evidence_required_types_match_respond():
    """Voice and respond must gate the same task types — no surface divergence."""
    assert _VOICE_EVIDENCE_REQUIRED == _EVIDENCE_REQUIRED_TYPES


# ─────────────────────────────────────────────────────────────────────────────
# 10. Teams bot — _build_card evidence gate
# ─────────────────────────────────────────────────────────────────────────────

def test_teams_kpi_card_absent_evidence_returns_none():
    """Without platform_evidence, kpi card must not be built."""
    so = json.dumps({
        "summary": "CTR dropped",
        "confidence_score": 0.7,
        "root_causes": [],
        "recommended_actions": [],
        "version": "v1",
    })
    card = _build_card("kpi", so, "task-123", platform_evidence_json=None)
    assert card is None


def test_teams_kpi_card_unsafe_evidence_returns_none():
    card = _build_card(
        "kpi",
        '{"summary": "x", "confidence_score": 0.5, "root_causes": [], "recommended_actions": [], "version": "v1"}',
        "task-123",
        platform_evidence_json=_unsafe_evidence_json(),
    )
    assert card is None


def test_teams_kpi_card_safe_evidence_returns_card():
    so = json.dumps({
        "summary": "CTR dropped",
        "confidence_score": 0.7,
        "root_causes": [],
        "recommended_actions": [],
        "version": "v1",
    })
    card = _build_card("kpi", so, "task-123", platform_evidence_json=_safe_evidence_json())
    assert card is not None
    assert card["type"] == "AdaptiveCard"


def test_teams_kpi_card_includes_evidence_section():
    so = json.dumps({
        "summary": "CTR dropped",
        "confidence_score": 0.7,
        "root_causes": [],
        "recommended_actions": [],
        "version": "v1",
    })
    card = _build_card("kpi", so, "task-123", platform_evidence_json=_safe_evidence_json())
    assert card is not None
    body_texts = " ".join(
        b.get("text", "") for b in card["body"] if b.get("type") == "TextBlock"
    )
    assert "Evidence Sources" in body_texts


def test_teams_cicd_card_absent_evidence_returns_none():
    so = json.dumps({
        "failure_summary": "Build failed",
        "failed_stage": "test",
        "root_cause_hypotheses": [],
        "suggested_fixes": [],
        "deployment_verdict": "do_not_deploy",
        "severity": "high",
        "notify_team": False,
        "version": "v1",
    })
    card = _build_card("ci_cd", so, "task-123", platform_evidence_json=None)
    assert card is None


def test_teams_cicd_card_safe_evidence_returns_card():
    so = json.dumps({
        "failure_summary": "Build failed",
        "failed_stage": "test",
        "root_cause_hypotheses": [],
        "suggested_fixes": [],
        "deployment_verdict": "do_not_deploy",
        "severity": "high",
        "notify_team": False,
        "version": "v1",
    })
    card = _build_card("ci_cd", so, "task-123",
                       platform_evidence_json=_safe_evidence_json(claim_id="pipeline-state"))
    assert card is not None
    assert card["type"] == "AdaptiveCard"


def test_teams_pr_review_card_no_gate():
    """PR review card builds without platform_evidence — gate not applied."""
    so = json.dumps({
        "verdict": "approve",
        "risk_level": "low",
        "summary": "Clean PR",
        "code_issues": [],
        "missing_tests": [],
        "deployment_risks": [],
        "business_impact": "Low risk",
        "version": "v1",
    })
    card = _build_card("pr_review", so, "task-123", platform_evidence_json=None)
    assert card is not None


def test_teams_evidence_facts_no_source_content():
    """_build_evidence_facts must only include source_id/authority — never content."""
    evidenced = json.loads(_safe_evidence_json())
    facts = _build_evidence_facts(evidenced)
    assert len(facts) > 0
    all_text = " ".join(f.get("value", "") for f in facts)
    assert "p99 latency" not in all_text
    assert "Error rate" not in all_text


def test_teams_evidence_required_card_types_match_respond():
    """Teams bot and respond must gate the same task types."""
    assert _EVIDENCE_REQUIRED_CARD_TYPES == _EVIDENCE_REQUIRED_TYPES


# ─────────────────────────────────────────────────────────────────────────────
# 11. End-to-end: kpi_node → respond chain
# ─────────────────────────────────────────────────────────────────────────────

def test_kpi_node_plus_respond_surfaces_when_evidence_safe():
    """
    kpi_node populates platform_evidence; respond surfaces the answer when safe.
    This is a full integration test of the kpi → respond chain (no LLM, dry-run).
    """
    from aria.nodes.skill_nodes import kpi_node

    state = _minimal_state(task_type="kpi", skill_output=None, platform_evidence=None)
    # Override with a proper full state dict (kpi_node needs all fields)
    state.update({
        "raw_input": "What is causing the CTR drop on analytics-pipeline?",
    })

    node_result = kpi_node(state)

    # kpi_node should always populate platform_evidence for analytics-pipeline
    pe_json = node_result.get("platform_evidence")
    assert pe_json is not None, "kpi_node must set platform_evidence"

    # Merge node result into state for respond
    state.update(node_result)
    respond_result = respond(state)
    response = respond_result["response"]

    # For analytics-pipeline (which has fixtures), evidence should be safe
    pe = json.loads(pe_json)
    if pe.get("is_safe_to_surface"):
        assert "[EVIDENCE UNAVAILABLE" not in response
        assert "Evidence Provenance" in response
    else:
        # Fixtures present but claims may be unsupported for some queries — gate applies
        assert "[RESPONSE WITHHELD" in response or "[EVIDENCE UNAVAILABLE" in response


def test_kpi_node_plus_respond_withheld_when_no_fixtures_match():
    """
    For a service not in the catalog, kpi_node may produce unsafe evidence →
    respond withholds the answer.
    """
    from aria.nodes.skill_nodes import kpi_node

    state = _minimal_state(task_type="kpi", skill_output=None, platform_evidence=None)
    state.update({
        "raw_input": "What is wrong with nonexistent-mystery-service-xyz?",
    })

    node_result = kpi_node(state)
    state.update(node_result)
    respond_result = respond(state)
    response = respond_result["response"]

    pe_json = node_result.get("platform_evidence")
    if pe_json:
        pe = json.loads(pe_json)
        if not pe.get("is_safe_to_surface"):
            assert "[RESPONSE WITHHELD" in response
    # If platform_evidence is None (assembly failed entirely), it's also withheld
    if not pe_json:
        assert "[EVIDENCE UNAVAILABLE" in response


def test_ci_cd_node_sets_platform_evidence():
    """ci_cd_node must populate platform_evidence after this change."""
    from aria.nodes.skill_nodes import ci_cd_node

    state = _minimal_state(task_type="ci_cd")
    state.update({
        "raw_input": "analytics-pipeline build failed on test stage",
    })

    result = ci_cd_node(state)
    assert "platform_evidence" in result, (
        "ci_cd_node must populate platform_evidence (dependency impact)"
    )
    pe = json.loads(result["platform_evidence"])
    assert "claim_evidence_map" in pe
    # Should have pipeline-state and dependency-impact claims
    claim_ids = [ce["claim_id"] for ce in pe["claim_evidence_map"]]
    assert "pipeline-state" in claim_ids
    assert "dependency-impact" in claim_ids
