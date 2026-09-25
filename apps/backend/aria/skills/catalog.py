"""
Read-only skill catalog.

The V1 skill *registry* (``skill_registry.py``) is a runtime scaffold that is not
auto-populated — skills are invoked as modules. This module exposes a small, deterministic,
READ-ONLY catalog of the concrete domain skills that actually exist under ``aria/skills/``,
so the manager interface can list ARIA's capabilities.

It performs NO skill execution, NO model call, NO network, and NO credential access — it only
describes the typed input/output contracts and action tier of each skill.
"""
from __future__ import annotations

# Action-tier names (see CLAUDE.md §11 governance framework).
_TIER_NAMES = {
    1: "Read",
    2: "Recommend",
    3: "Draft",
    4: "Execute-with-Approval",
    5: "Autonomous",
}

# Curated from the real modules in aria/skills/ — name, typed contract, and purpose.
_CATALOG: tuple[dict, ...] = (
    {
        "name": "pr_review",
        "title": "PR Review",
        "category": "AI Engineering",
        "version": "v1",
        "action_tier": 3,
        "input_schema": "PRReviewInput",
        "output_schema": "PRReviewOutput",
        "description": ("Reviews a pull request for code quality, deployment risk, business "
                        "impact, and missing tests — including media-tech services (CMS, "
                        "recommendation, notification, personalisation pipelines)."),
    },
    {
        "name": "kpi",
        "title": "KPI Investigation",
        "category": "Data Science & Analytics",
        "version": "v1",
        "action_tier": 2,
        "input_schema": "KPIInput",
        "output_schema": "KPIOutput",
        "description": ("Investigates a KPI anomaly in a metric declared by the tenant "
                        "and proposes ranked root-cause hypotheses with evidence."),
    },
    {
        "name": "ci_cd",
        "title": "CI/CD Failure Triage",
        "category": "CI/CD & Release Intelligence",
        "version": "v1",
        "action_tier": 2,
        "input_schema": "CICDInput",
        "output_schema": "CICDOutput",
        "description": ("Summarises a CI/CD pipeline failure and triages the most likely "
                        "root-cause hypotheses for the failing build."),
    },
    {
        "name": "jira",
        "title": "Jira Delivery Management",
        "category": "Jira / Delivery Management",
        "version": "v1",
        "action_tier": 3,
        "input_schema": "JiraInput",
        "output_schema": "JiraOutput",
        "description": ("Drafts and refines Jira tickets and tracks sprint blockers. Draft-only "
                        "— a human approves before anything is created."),
    },
    {
        "name": "qa",
        "title": "QA / Test Generation",
        "category": "QA / Test Intelligence",
        "version": "v1",
        "action_tier": 3,
        "input_schema": "QAInput",
        "output_schema": "QAOutput",
        "description": ("Generates functional, edge, and negative test cases and flags coverage "
                        "gaps for a change under review."),
    },
    {
        "name": "test_review",
        "title": "Test Review & Regression Intelligence",
        "category": "QA / Test Intelligence",
        "version": "v1",
        "action_tier": 2,
        "input_schema": "TestReviewInput",
        "output_schema": "TestReviewOutput",
        "description": ("Reviews an existing test suite for quality issues and highlights "
                        "regression risk before a release."),
    },
)


def skills_catalog() -> list[dict]:
    """Return the read-only skill catalog, each entry enriched with its tier name.

    Deterministic and side-effect free — safe to call from an API handler.
    """
    out: list[dict] = []
    for entry in _CATALOG:
        item = dict(entry)
        item["tier_name"] = _TIER_NAMES.get(entry["action_tier"], "Unknown")
        out.append(item)
    return out
