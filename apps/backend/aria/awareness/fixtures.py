"""
Deterministic world-awareness FIXTURES (V3.6).

These stand in for external sources/updates. There is NO live browsing, NO network,
and NO open-web crawling anywhere in V3.6 — ``ingest_fixtures`` reads only this
module. Each update carries a source citation and topic tags used by relevance
scoring.
"""
from __future__ import annotations

from aria.awareness.models import WorldSourceType

# Registered fixture sources (name, source_type, url, topic_tags, policy_notes).
FIXTURE_SOURCES: tuple[dict, ...] = (
    {
        "key": "databricks_docs", "name": "Databricks Engineering Docs",
        "source_type": WorldSourceType.official_doc, "url": "fixture://databricks/docs",
        "topic_tags": ["agent_harness", "governance", "tooling"],
        "policy_notes": "first-party docs — high trust; advisory only",
    },
    {
        "key": "langgraph_release", "name": "LangGraph Release Notes",
        "source_type": WorldSourceType.release_note, "url": "fixture://langgraph/releases",
        "topic_tags": ["agent_harness", "memory", "tooling"],
        "policy_notes": "release notes — high trust; advisory only",
    },
    {
        "key": "cve_advisory", "name": "Dependency Security Advisory",
        "source_type": WorldSourceType.security_advisory, "url": "fixture://advisories/cve",
        "topic_tags": ["security", "dependency"],
        "policy_notes": "security advisory — escalate to human review",
    },
    {
        "key": "random_blog", "name": "Some AI Trends Blog",
        "source_type": WorldSourceType.blog, "url": "fixture://blog/ai-trends",
        "topic_tags": ["hype", "opinion"],
        "policy_notes": "low-trust blog — cannot change roadmap",
    },
)

# Fixture updates, keyed by their source ``key``.
FIXTURE_UPDATES: tuple[dict, ...] = (
    {
        "source_key": "databricks_docs",
        "title": "Meta-harness pattern: delegated agent identity + policy gateway",
        "summary": ("A pattern for governed external-agent collaboration: delegated identity, "
                    "a policy gateway, and session sharing across agents."),
        "source_url": "fixture://databricks/docs/meta-harness",
        "citations": ["fixture://databricks/docs/meta-harness#section-2"],
        "topic_tags": ["agent_harness", "external_agent", "governance", "policy_gateway",
                       "session_sharing"],
    },
    {
        "source_key": "langgraph_release",
        "title": "Durable cross-session agent memory checkpoints",
        "summary": "New checkpointer enables durable, inspectable cross-session agent memory.",
        "source_url": "fixture://langgraph/releases/v1.2",
        "citations": ["fixture://langgraph/releases/v1.2#memory"],
        "topic_tags": ["memory", "agent_harness", "tooling"],
    },
    {
        "source_key": "cve_advisory",
        "title": "High-severity deserialization CVE in a common dependency",
        "summary": "A high-severity remote-code-execution advisory affecting a popular library.",
        "source_url": "fixture://advisories/cve-2026-0001",
        "citations": ["fixture://advisories/cve-2026-0001"],
        "topic_tags": ["security", "dependency", "rce"],
        "risk_level": "high",
    },
    {
        "source_key": "random_blog",
        "title": "Ten hot AI takes for next year",
        "summary": "Opinion piece with broad, unsourced predictions about AI.",
        "source_url": "fixture://blog/ai-trends/2026",
        "citations": ["fixture://blog/ai-trends/2026"],
        "topic_tags": ["hype", "opinion"],
    },
)
