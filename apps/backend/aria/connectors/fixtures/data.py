"""
Deterministic local fixtures for the Week 34 read-only pilots.

These are the ONLY data source the pilots read in fixtures mode. They contain no
secrets, no credentials, and no real customer data — they are synthetic Amar
Ujala-style media-tech examples (recommendation service PR, CI failure, and a
``story_events`` analytics table that pairs with the canonical domain memory).

Kept here (a clear ``connectors/fixtures/`` boundary) rather than scattered in
pilot/API/UI code.
"""
from __future__ import annotations

# ── PR review fixture ─────────────────────────────────────────────────────────

PR_FIXTURES: dict[str, dict] = {
    "default": {
        "pr_id": "PR-481",
        "title": "Add story recommendation re-ranking with freshness boost",
        "author": "dev:asha",
        "description": (
            "Re-ranks story recommendations using a freshness boost signal and a "
            "new ranking feature column. Touches the recommendation ranker and a "
            "DB migration."
        ),
        "files": [
            {"path": "services/recommendation/ranker.py", "additions": 120, "deletions": 18,
             "risk": "high", "reason": "changes ranking/retrieval signals"},
            {"path": "services/recommendation/config.py", "additions": 8, "deletions": 2,
             "risk": "low", "reason": "config defaults"},
            {"path": "db/migrations/0042_add_rank_features.sql", "additions": 30, "deletions": 0,
             "risk": "high", "reason": "schema migration"},
            {"path": "services/notification/sender.py", "additions": 12, "deletions": 4,
             "risk": "medium", "reason": "notification payload change"},
        ],
        "existing_tests": ["tests/recommendation/test_config.py"],
    },
}

# ── CI/CD investigation fixture ───────────────────────────────────────────────

CICD_FIXTURES: dict[str, dict] = {
    "default": {
        "run_id": "run-9921",
        "workflow": "ci-recommendation",
        "status": "failed",
        "jobs": [
            {"name": "build", "status": "success", "steps": [
                {"name": "checkout", "status": "success", "log_excerpt": "Checked out 3157012"},
                {"name": "install", "status": "success", "log_excerpt": "Resolved 142 packages"},
            ]},
            {"name": "test", "status": "failed", "steps": [
                {"name": "lint", "status": "success", "log_excerpt": "All checks passed"},
                {"name": "unit-tests", "status": "failed", "log_excerpt": (
                    "FAILED tests/recommendation/test_ranker.py::test_rerank - "
                    "KeyError: 'freshness_boost'"
                )},
            ]},
        ],
    },
}

# ── Analytics / events fixtures (pairs with the story_events.event_type memory) ─

ANALYTICS_SCHEMA: dict[str, dict] = {
    "story_events": {
        "table": "story_events",
        "columns": [
            {"name": "event_type", "type": "int", "nullable": False},
            {"name": "user_id", "type": "string", "nullable": False},
            {"name": "story_id", "type": "string", "nullable": False},
            {"name": "session_id", "type": "string", "nullable": True},
            {"name": "ts", "type": "timestamp", "nullable": False},
        ],
        "freshness_hours": 2.0,
        "freshness_threshold_hours": 24.0,
    },
}

# One row has a null session_id; row 0 and row 3 are duplicates; event_type=9 is
# outside the known taxonomy {1,2,3} (anomaly + taxonomy issue).
ANALYTICS_EVENTS: dict[str, list[dict]] = {
    "story_events": [
        {"event_type": 1, "user_id": "u1", "story_id": "s1", "session_id": "sess-a", "ts": "2026-06-17T09:00:00+00:00"},
        {"event_type": 2, "user_id": "u2", "story_id": "s2", "session_id": None,      "ts": "2026-06-17T09:01:00+00:00"},
        {"event_type": 2, "user_id": "u2", "story_id": "s2", "session_id": "sess-b", "ts": "2026-06-17T09:02:00+00:00"},
        {"event_type": 1, "user_id": "u1", "story_id": "s1", "session_id": "sess-a", "ts": "2026-06-17T09:00:00+00:00"},
        {"event_type": 3, "user_id": "u3", "story_id": "s3", "session_id": "sess-c", "ts": "2026-06-17T09:03:00+00:00"},
        {"event_type": 9, "user_id": "u4", "story_id": "s4", "session_id": "sess-d", "ts": "2026-06-17T09:04:00+00:00"},
    ],
}
