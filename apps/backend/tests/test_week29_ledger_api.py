"""
Week 29 Priority 2 — Backend ROI API tests.

Covers every contract requirement from the Priority 2 brief:

- valid metrics response shape
- empty ledger
- malformed records counted via sources.malformed_count
- Decimal cost serialised as string
- source split (v2 / legacy_task / legacy_evolution / malformed)
- combined legacy + v2 data
- every supported filter (date, skill, actor_type, workflow_id)
- unavailable values represented as null
- production-path isolation (tests use tmp_path; env vars override)
- permission / filesystem failures → typed 5xx, NOT counted as malformed
- oversized-ledger behavior
- response contains no sensitive raw data (no raw events / metadata
  values / error strings / prompts / credentials in the surface)
"""
from __future__ import annotations

import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aria.ledger import (
    ActorType,
    ApprovalRequested,
    Approved,
    CostRecorded,
    Failed,
    LedgerWriter,
    Rejected,
    Responded,
    SkillInvoked,
    TaskCreated,
)
from aria.ledger.events import make_envelope


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _utc(seconds: float = 0.0) -> datetime:
    return datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Point the API at per-test tmp ledger files. Sets all three env vars
    so the route's ``_resolve_paths`` returns isolated paths, not the
    repo's runtime ledger files.
    """
    v2_path     = tmp_path / "ledger_v2.jsonl"
    legacy_task = tmp_path / "legacy_task.jsonl"
    legacy_evo  = tmp_path / "legacy_evolution.jsonl"
    monkeypatch.setenv("ARIA_LEDGER_V2_PATH",               str(v2_path))
    monkeypatch.setenv("ARIA_LEDGER_LEGACY_TASK_PATH",      str(legacy_task))
    monkeypatch.setenv("ARIA_LEDGER_LEGACY_EVOLUTION_PATH", str(legacy_evo))
    return {"v2": v2_path, "legacy_task": legacy_task, "legacy_evo": legacy_evo}


@pytest.fixture
def client() -> TestClient:
    # Import here so env-var fixtures applied above are in scope.
    from voice_api import app
    return TestClient(app)


def _env(task_id: str = "t-1", actor: str = "aria",
         actor_type: ActorType = ActorType.aria, **extra) -> dict:
    return make_envelope(task_id=task_id, actor=actor, actor_type=actor_type, **extra)


# ── Section A — Shape, empty, source split ────────────────────────────────────


def test_empty_ledger_returns_zero_safe_response(isolated_paths, client):
    response = client.get("/api/v1/ledger/metrics")
    assert response.status_code == 200
    body = response.json()
    # Top-level shape contract
    assert body["api_version"] == "v1"
    # Zero-safe defaults
    assert body["execution"]["total_tasks_completed"] == 0
    assert body["execution"]["tasks_by_skill"] == {}
    assert body["approval"]["approvals_granted"] == 0
    assert body["approval"]["approvals_rejected"] == 0
    assert body["approval"]["approval_rate"] is None
    assert body["failure"]["failure_rate"] is None
    assert body["resolution"]["avg_time_to_resolution_ms"] is None
    assert body["cost"]["estimated_cost_total"] == "0"
    assert body["cost"]["estimated_cost_per_task"] is None
    assert body["cost"]["tasks_with_cost"] == 0
    assert body["human_intervention"]["rate"] is None
    assert body["artifacts"]["count"] == 0
    assert body["corrections"]["count"] == 0
    assert body["models"]["usage_breakdown"] == {}
    assert body["sources"] == {
        "v2_event_count": 0,
        "legacy_task_count": 0,
        "legacy_evolution_count": 0,
        "malformed_count": 0,
    }


def test_valid_metrics_response_full_lifecycle(isolated_paths, client):
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    w.append(TaskCreated(**_env("t-1", timestamp=t)))
    w.append(SkillInvoked(**_env("t-1", timestamp=t), skill_name="pr_review"))
    w.append(ApprovalRequested(**_env("t-1", timestamp=t),
                                approval_id="appr-1"))
    w.append(Approved(**make_envelope(
        task_id="t-1", actor="kunal", actor_type=ActorType.human,
        timestamp=t + timedelta(seconds=3)),
        approval_id="appr-1"))
    w.append(CostRecorded(**_env("t-1", timestamp=t + timedelta(seconds=4)),
                          estimated_cost=Decimal("0.1234")))
    w.append(Responded(**_env("t-1", timestamp=t + timedelta(seconds=10))))

    r = client.get("/api/v1/ledger/metrics").json()
    assert r["execution"]["total_tasks_completed"] == 1
    assert r["execution"]["tasks_by_skill"] == {"pr_review": 1}
    assert r["approval"]["approvals_granted"] == 1
    assert r["approval"]["approval_rate"] == 1.0
    assert r["approval"]["approval_rate_by_skill"] == {"pr_review": 1.0}
    assert r["failure"]["failure_rate"] == 0.0
    assert r["failure"]["failure_rate_by_skill"] == {"pr_review": 0.0}
    assert r["resolution"]["avg_time_to_resolution_ms"] == 10_000.0
    # Decimal serialised as string — critical contract
    assert r["cost"]["estimated_cost_total"] == "0.1234"
    assert r["cost"]["estimated_cost_per_task"] == "0.1234"
    assert isinstance(r["cost"]["estimated_cost_total"], str)
    assert r["human_intervention"]["rate"] == 1.0
    assert r["sources"]["v2_event_count"] == 6


def test_malformed_records_are_counted_and_skipped(isolated_paths, client):
    # Plant a real event + a bad line.
    LedgerWriter(isolated_paths["v2"]).append(
        TaskCreated(**_env("t-1", timestamp=_utc()))
    )
    with isolated_paths["v2"].open("a", encoding="utf-8") as fh:
        fh.write("definitely not json\n")
        # Valid JSON but does not match the discriminated union.
        fh.write(json.dumps({"event_type": "nonexistent_type"}) + "\n")

    body = client.get("/api/v1/ledger/metrics").json()
    assert body["sources"]["v2_event_count"] == 1
    assert body["sources"]["malformed_count"] == 2


def test_source_split_for_all_three_ledgers(isolated_paths, client):
    LedgerWriter(isolated_paths["v2"]).append(
        TaskCreated(**_env("t-1", timestamp=_utc()))
    )
    isolated_paths["legacy_task"].write_text(json.dumps({
        "task_id": "l-1", "task_type": "kpi", "routing_reason": "r",
        "timestamp": "2026-06-04T09:10:01+00:00", "week": 4,
    }) + "\n", encoding="utf-8")
    isolated_paths["legacy_evo"].write_text(json.dumps({
        "event_type": "approval", "task_id": "upd-1",
        "update_id": "upd-1", "component_name": "c", "version": "1.0.0",
        "timestamp": "2026-06-09T09:51:58+00:00",
        "actor": "k", "outcome": "approved_canary",
    }) + "\n", encoding="utf-8")

    body = client.get("/api/v1/ledger/metrics").json()
    assert body["sources"]["v2_event_count"] == 1
    assert body["sources"]["legacy_task_count"] == 1
    assert body["sources"]["legacy_evolution_count"] == 1
    assert body["sources"]["malformed_count"] == 0


def test_combined_legacy_and_v2_data_counted_once(isolated_paths, client):
    """A task mirrored into both v2 and legacy must count exactly once."""
    w = LedgerWriter(isolated_paths["v2"])
    w.append(SkillInvoked(**_env("mirror-t", timestamp=_utc()),
                           skill_name="kpi"))
    w.append(Responded(**_env("mirror-t", timestamp=_utc(2))))
    isolated_paths["legacy_task"].write_text(json.dumps({
        "task_id": "mirror-t", "task_type": "kpi",
        "routing_reason": "r", "timestamp": "2026-06-04T09:10:01+00:00",
        "week": 4,
    }) + "\n", encoding="utf-8")
    body = client.get("/api/v1/ledger/metrics").json()
    assert body["execution"]["tasks_by_skill"] == {"kpi": 1}
    assert body["execution"]["total_tasks_completed"] == 1


# ── Section B — Filters ──────────────────────────────────────────────────────


def test_date_filter_excludes_out_of_range_events(isolated_paths, client):
    w = LedgerWriter(isolated_paths["v2"])
    inside_ts = _utc()
    outside_ts = _utc(86400 * 30)  # 30 days later
    w.append(SkillInvoked(**_env("t-in", timestamp=inside_ts),
                           skill_name="pr_review"))
    w.append(Responded(**_env("t-in", timestamp=inside_ts + timedelta(seconds=1))))
    w.append(SkillInvoked(**_env("t-out", timestamp=outside_ts),
                           skill_name="pr_review"))
    w.append(Responded(**_env("t-out", timestamp=outside_ts + timedelta(seconds=1))))

    body = client.get("/api/v1/ledger/metrics", params={
        "start_date": "2026-06-11T00:00:00+00:00",
        "end_date":   "2026-06-12T00:00:00+00:00",
    }).json()
    assert body["execution"]["total_tasks_completed"] == 1
    assert body["filters_applied"]["start_date"] == "2026-06-11T00:00:00+00:00"


def test_skill_filter_keeps_only_matching_tasks(isolated_paths, client):
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    w.append(SkillInvoked(**_env("pr-1", timestamp=t), skill_name="pr_review"))
    w.append(Responded(**_env("pr-1", timestamp=t + timedelta(seconds=1))))
    w.append(SkillInvoked(**_env("kpi-1", timestamp=t), skill_name="kpi"))
    w.append(Responded(**_env("kpi-1", timestamp=t + timedelta(seconds=1))))
    body = client.get("/api/v1/ledger/metrics", params={"skill": "pr_review"}).json()
    assert body["execution"]["tasks_by_skill"] == {"pr_review": 1}
    assert body["execution"]["total_tasks_completed"] == 1


def test_actor_type_filter(isolated_paths, client):
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    w.append(TaskCreated(**_env("t-h", actor="kunal",
                                  actor_type=ActorType.human, timestamp=t)))
    w.append(TaskCreated(**_env("t-a", actor="aria",
                                  actor_type=ActorType.aria, timestamp=t)))
    body = client.get("/api/v1/ledger/metrics",
                       params={"actor_type": "human"}).json()
    assert body["sources"]["v2_event_count"] == 1


def test_workflow_filter(isolated_paths, client):
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    w.append(SkillInvoked(**make_envelope(
        task_id="t-wf-A", actor="aria", actor_type=ActorType.aria,
        workflow_id="wf-A", timestamp=t), skill_name="pr_review"))
    w.append(SkillInvoked(**make_envelope(
        task_id="t-wf-B", actor="aria", actor_type=ActorType.aria,
        workflow_id="wf-B", timestamp=t), skill_name="kpi"))
    body = client.get("/api/v1/ledger/metrics",
                       params={"workflow_id": "wf-A"}).json()
    assert body["sources"]["v2_event_count"] == 1
    assert body["filters_applied"]["workflow_id"] == "wf-A"


def test_invalid_date_filter_returns_400(isolated_paths, client):
    body = client.get("/api/v1/ledger/metrics",
                       params={"start_date": "not a date"})
    assert body.status_code == 400
    assert body.json()["error_code"] == "invalid_filter"


def test_naive_date_filter_rejected(isolated_paths, client):
    body = client.get("/api/v1/ledger/metrics",
                       params={"start_date": "2026-06-11T00:00:00"})
    assert body.status_code == 400


def test_invalid_actor_type_returns_400(isolated_paths, client):
    body = client.get("/api/v1/ledger/metrics",
                       params={"actor_type": "robot"})
    assert body.status_code == 400


def test_start_after_end_returns_400(isolated_paths, client):
    body = client.get("/api/v1/ledger/metrics", params={
        "start_date": "2026-06-12T00:00:00+00:00",
        "end_date":   "2026-06-11T00:00:00+00:00",
    })
    assert body.status_code == 400


# ── Section C — Unavailable values are null ──────────────────────────────────


def test_unavailable_rates_and_costs_are_null(isolated_paths, client):
    # A skill that completes without any approval verdicts or costs.
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    w.append(SkillInvoked(**_env("t-a", timestamp=t), skill_name="pr_review"))
    w.append(Responded(**_env("t-a", timestamp=t + timedelta(seconds=1))))
    body = client.get("/api/v1/ledger/metrics").json()
    assert body["approval"]["approval_rate"] is None
    assert body["approval"]["approval_rate_by_skill"]["pr_review"] is None
    assert body["cost"]["estimated_cost_per_task"] is None
    # No TaskCreated was emitted in this minimal stream → resolution stays None.
    assert body["resolution"]["avg_time_to_resolution_ms"] is None


# ── Section D — Production-path isolation ────────────────────────────────────


def test_production_paths_are_isolated_by_env_vars(
    isolated_paths, client, tmp_path
):
    # Verify the request reads from tmp paths only, not from any
    # repository runtime file.
    w = LedgerWriter(isolated_paths["v2"])
    w.append(TaskCreated(**_env("iso-t", timestamp=_utc())))
    body = client.get("/api/v1/ledger/metrics").json()
    assert body["sources"]["v2_event_count"] == 1
    # Confirm the runtime path was NOT touched.
    runtime_default = Path("apps/backend/work_ledger_v2.jsonl").resolve()
    if runtime_default.exists():
        # If a developer happens to have one locally, just confirm we
        # didn't ADD anything to it during this test.
        size_before = runtime_default.stat().st_size
        client.get("/api/v1/ledger/metrics")
        assert runtime_default.stat().st_size == size_before
    else:
        assert not runtime_default.exists()


# ── Section E — Failure modes that must NOT become malformed_count ───────────


@pytest.mark.skipif(sys.platform == "win32",
                    reason="chmod permission semantics differ on Windows")
def test_permission_error_returns_503_not_malformed(
    isolated_paths, client
):
    # Make the file unreadable.
    isolated_paths["v2"].write_text("doesn't matter\n", encoding="utf-8")
    isolated_paths["v2"].chmod(0)
    try:
        body = client.get("/api/v1/ledger/metrics")
        assert body.status_code == 503
        assert body.json()["error_code"] in ("filesystem_error",)
    finally:
        # Restore so cleanup works.
        isolated_paths["v2"].chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_oversized_ledger_returns_413(isolated_paths, client, monkeypatch):
    monkeypatch.setenv("ARIA_LEDGER_API_MAX_RECORDS", "3")
    w = LedgerWriter(isolated_paths["v2"])
    for i in range(5):
        w.append(TaskCreated(**_env(f"t-{i}", timestamp=_utc(i))))
    body = client.get("/api/v1/ledger/metrics")
    assert body.status_code == 413
    assert body.json()["error_code"] == "oversized_ledger"


# ── Section F — No sensitive raw data leaks through the response ─────────────


def test_response_contains_no_sensitive_raw_fields(isolated_paths, client):
    """
    Even if a caller persisted events that contain redacted secrets, the
    API response shape must not expose:
      - raw event objects
      - event-level metadata
      - error strings, prompts, transcripts, credentials
    """
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    # Try to plant a string that, post-redaction, still might leak
    # through an over-permissive API.
    w.append(Failed(**_env("t-secret", timestamp=t),
                    error="oh no a token sk-1234567890abcdef leaked"))
    body = client.get("/api/v1/ledger/metrics").json()
    serialised = json.dumps(body)
    # No raw event-level fields are exposed.
    forbidden_keys = ("error", "raw_prompt", "metadata", "actor",
                       "task_id", "event_id", "skill_output", "routing_reason")
    for k in forbidden_keys:
        assert f'"{k}"' not in serialised, (
            f"Response leaked an internal field: {k!r}"
        )
    # And no credential pattern survived anywhere.
    assert "sk-1234567890abcdef" not in serialised


def test_filters_applied_echoes_request_query(isolated_paths, client):
    body = client.get("/api/v1/ledger/metrics", params={
        "skill": "pr_review",
        "actor_type": "human",
        "workflow_id": "wf-1",
    }).json()
    assert body["filters_applied"]["skill"] == "pr_review"
    assert body["filters_applied"]["actor_type"] == "human"
    assert body["filters_applied"]["workflow_id"] == "wf-1"


def test_extra_query_params_do_not_break_the_route(isolated_paths, client):
    # FastAPI ignores unknown params; the surface must not crash.
    body = client.get("/api/v1/ledger/metrics",
                       params={"something_we_dont_know": "x"})
    assert body.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Section G — Round 2 narrow fixes
# ═══════════════════════════════════════════════════════════════════════════════

# G.1 — Filters retain COMPLETE task lifecycles (no contradictory metrics)


def test_actor_type_filter_retains_complete_lifecycle(isolated_paths, client):
    """
    [P1] Round-2: filtering by actor_type=human must NOT drop a task's
    SkillInvoked / Responded events (which have actor_type=aria),
    otherwise the metrics show contradictions like "approval_rate=1.0
    but completed=0".
    """
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    # Task that had a human approval — by lifecycle-join semantics, the
    # whole task should survive the human filter.
    w.append(TaskCreated(**_env("t-h", actor="aria",
                                  actor_type=ActorType.aria, timestamp=t)))
    w.append(SkillInvoked(**_env("t-h", actor="aria",
                                   actor_type=ActorType.aria, timestamp=t),
                            skill_name="pr_review"))
    w.append(ApprovalRequested(**_env("t-h", actor="aria",
                                        actor_type=ActorType.aria, timestamp=t),
                                 approval_id="appr-h"))
    w.append(Approved(**make_envelope(
        task_id="t-h", actor="kunal", actor_type=ActorType.human,
        timestamp=t + timedelta(seconds=3)),
        approval_id="appr-h"))
    w.append(Responded(**_env("t-h", actor="aria",
                                actor_type=ActorType.aria,
                                timestamp=t + timedelta(seconds=5))))

    body = client.get("/api/v1/ledger/metrics",
                       params={"actor_type": "human"}).json()
    # Whole lifecycle retained: skill counted, approval counted, completion counted.
    assert body["execution"]["total_tasks_completed"] == 1
    assert body["execution"]["tasks_by_skill"] == {"pr_review": 1}
    assert body["approval"]["approvals_granted"] == 1
    assert body["approval"]["approval_rate"] == 1.0
    # Human intervention rate is well-defined and not null.
    assert body["human_intervention"]["rate"] == 1.0


def test_workflow_filter_retains_complete_lifecycle(isolated_paths, client):
    """
    workflow_id filter selects tasks whose ANY event matches; the
    entire lifecycle for those tasks is then retained.
    """
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    # Only the TaskCreated carries workflow_id=wf-X — the other events
    # don't. The whole task must still survive the filter.
    w.append(TaskCreated(**make_envelope(
        task_id="t-wf", actor="aria", actor_type=ActorType.aria,
        workflow_id="wf-X", timestamp=t)))
    w.append(SkillInvoked(**_env("t-wf", timestamp=t), skill_name="pr_review"))
    w.append(Responded(**_env("t-wf", timestamp=t + timedelta(seconds=5))))

    body = client.get("/api/v1/ledger/metrics",
                       params={"workflow_id": "wf-X"}).json()
    assert body["execution"]["total_tasks_completed"] == 1
    assert body["execution"]["tasks_by_skill"] == {"pr_review": 1}


def test_date_filter_anchors_on_task_created_not_individual_events(
    isolated_paths, client
):
    """
    [P1] Round-2: date filter anchors on the task's TaskCreated event
    (or earliest event if none) — a task that was CREATED inside the
    window survives WITH ITS LATER EVENTS, even if those events lie
    outside the window. Without this, a Cost or Responded event later
    than the window's end_date would be dropped while the task is
    still classified as completed → contradictory cost/resolution.
    """
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    # TaskCreated inside the window; cost and responded just after.
    w.append(TaskCreated(**_env("t-in", timestamp=t)))
    w.append(SkillInvoked(**_env("t-in", timestamp=t), skill_name="kpi"))
    w.append(CostRecorded(**_env("t-in", timestamp=t + timedelta(hours=1)),
                          estimated_cost=Decimal("0.10")))
    w.append(Responded(**_env("t-in", timestamp=t + timedelta(hours=2))))

    # Window ends 30 minutes after TaskCreated — cost + responded are
    # AFTER end_date, but the task's anchor is INSIDE the window.
    body = client.get("/api/v1/ledger/metrics", params={
        "start_date": t.isoformat(),
        "end_date":   (t + timedelta(minutes=30)).isoformat(),
    }).json()
    assert body["execution"]["total_tasks_completed"] == 1
    assert body["execution"]["tasks_by_skill"] == {"kpi": 1}
    # Cost is preserved because the task's lifecycle is retained whole.
    assert body["cost"]["estimated_cost_total"] == "0.10"
    assert body["cost"]["tasks_with_cost"] == 1


def test_date_filter_excludes_task_with_anchor_outside_window(isolated_paths, client):
    w = LedgerWriter(isolated_paths["v2"])
    early = _utc()
    late = _utc(86400 * 30)
    w.append(TaskCreated(**_env("t-early", timestamp=early)))
    w.append(SkillInvoked(**_env("t-early", timestamp=early), skill_name="kpi"))
    w.append(Responded(**_env("t-early", timestamp=early + timedelta(seconds=1))))
    w.append(TaskCreated(**_env("t-late", timestamp=late)))
    w.append(SkillInvoked(**_env("t-late", timestamp=late), skill_name="kpi"))
    w.append(Responded(**_env("t-late", timestamp=late + timedelta(seconds=1))))

    body = client.get("/api/v1/ledger/metrics", params={
        "start_date": "2026-06-11T00:00:00+00:00",
        "end_date":   "2026-06-12T00:00:00+00:00",
    }).json()
    # Only "t-early" — its anchor (TaskCreated) is in the window.
    assert body["execution"]["total_tasks_completed"] == 1


def test_skill_filter_keeps_lifecycle_events_including_cost(isolated_paths, client):
    """Skill filter also preserves the cost event that's not a SkillInvoked itself."""
    w = LedgerWriter(isolated_paths["v2"])
    t = _utc()
    w.append(TaskCreated(**_env("pr-1", timestamp=t)))
    w.append(SkillInvoked(**_env("pr-1", timestamp=t), skill_name="pr_review"))
    w.append(CostRecorded(**_env("pr-1", timestamp=t + timedelta(seconds=1)),
                          estimated_cost=Decimal("0.25")))
    w.append(Responded(**_env("pr-1", timestamp=t + timedelta(seconds=2))))
    # Decoy task on a different skill.
    w.append(SkillInvoked(**_env("kpi-1", timestamp=t), skill_name="kpi"))
    w.append(Responded(**_env("kpi-1", timestamp=t + timedelta(seconds=1))))

    body = client.get("/api/v1/ledger/metrics",
                       params={"skill": "pr_review"}).json()
    assert body["execution"]["tasks_by_skill"] == {"pr_review": 1}
    assert body["cost"]["estimated_cost_total"] == "0.25"


# G.2 — Error responses are sanitised


def test_503_response_does_not_leak_exception_details(
    isolated_paths, client, monkeypatch
):
    """
    [P2] Round-2: when the underlying reader raises, the HTTP body must
    surface a stable generic message — never the raw exception (which
    can contain filesystem paths, usernames, or embedded credentials).
    """
    # Force the reader to raise an OSError whose string contains a
    # secret-bearing path component.
    secret_path = r"C:\Users\Kunal Mahajan\app-with-ghp_1234567890abcdef\ledger.jsonl"
    def _boom(*a, **k):
        raise OSError(f"Permission denied: {secret_path}")
    monkeypatch.setattr(
        "aria.ledger.api.LedgerReader.iter_all",
        lambda self: (_ for _ in ()).throw(
            OSError(f"Permission denied: {secret_path}")
        ),
    )

    res = client.get("/api/v1/ledger/metrics")
    assert res.status_code == 503
    body_text = res.text
    assert "ghp_" not in body_text
    assert "Kunal Mahajan" not in body_text
    assert "Permission denied" not in body_text
    # The typed envelope is intact.
    body = res.json()
    assert body["error_code"] == "filesystem_error"
    assert body["detail"] == "Ledger could not be read."


def test_500_unexpected_response_is_generic(
    isolated_paths, client, monkeypatch
):
    secret = "Bearer eyJ.suspicious.payload"
    monkeypatch.setattr(
        "aria.ledger.api.LedgerReader.iter_all",
        lambda self: (_ for _ in ()).throw(
            RuntimeError(f"Boom carrying {secret}")
        ),
    )
    res = client.get("/api/v1/ledger/metrics")
    assert res.status_code == 503
    assert "eyJ" not in res.text
    assert "Boom" not in res.text


def test_400_invalid_filter_keeps_descriptive_message(isolated_paths, client):
    """
    Filter-validation messages ARE allowed to surface to the client
    because they only describe what the CLIENT sent — not server state.
    """
    res = client.get("/api/v1/ledger/metrics",
                      params={"actor_type": "robot"})
    assert res.status_code == 400
    assert "actor_type" in res.json()["detail"]
    assert "robot" in res.json()["detail"]
