"""
Week 29 Priority 1 — AI Work Ledger v2 tests.

Covers every Definition-of-Done scenario plus the adversarial cases
required by constraint #11. No LLM, network, LangSmith, Teams, Jira, or
paid API calls are made.

Layout
------
  Section A — typed event validation
  Section B — writer / reader roundtrip
  Section C — legacy compatibility (work_ledger.jsonl + evolution_events.jsonl)
  Section D — ROI metrics math (with documented semantics)
  Section E — privacy / redaction
  Section F — adversarial: duplicates / concurrency / malformed /
              unknown legacy schema / missing fields / retries /
              persistence-failure
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from aria.ledger import (
    ActionTaken,
    ActorType,
    ApprovalRequested,
    Approved,
    ArtifactCreated,
    CorrectionRecorded,
    CostRecorded,
    Failed,
    LedgerEventType,
    LedgerMetrics,
    LedgerPersistenceError,
    LedgerReader,
    LedgerSource,
    LedgerWriter,
    LegacyEvolutionRecord,
    LegacyTaskRecord,
    MalformedLedgerRecord,
    ModelUsed,
    OutcomeRecorded,
    REDACTED,
    Rejected,
    Responded,
    Routed,
    SkillInvoked,
    TaskCreated,
    sanitize_metadata,
)
from aria.ledger.events import ActionTier, RiskLevel, make_envelope
from aria.ledger.exceptions import RedactionViolation


# ── Shared helpers ────────────────────────────────────────────────────────────


def _env(task_id: str = "task-1", actor: str = "aria",
         actor_type: ActorType = ActorType.aria, **extra) -> dict:
    """Build a base envelope kwarg dict for concrete event constructors."""
    return make_envelope(task_id=task_id, actor=actor, actor_type=actor_type, **extra)


def _utc(seconds: float = 0.0) -> datetime:
    return datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


# ═══════════════════════════════════════════════════════════════════════════════
# Section A — Typed event validation
# ═══════════════════════════════════════════════════════════════════════════════


def test_task_created_minimal_validates():
    ev = TaskCreated(**_env(timestamp=_utc()))
    assert ev.event_type == LedgerEventType.task_created
    assert ev.event_version == 2
    assert ev.correlation_id == "task-1"  # defaults to task_id


def test_routed_requires_routing_reason():
    with pytest.raises(ValidationError):
        Routed(**_env(timestamp=_utc()))  # missing routing_reason
    with pytest.raises(ValidationError):
        Routed(**_env(timestamp=_utc()), routing_reason="   ")  # whitespace only


def test_skill_invoked_requires_skill_name():
    with pytest.raises(ValidationError):
        SkillInvoked(**_env(timestamp=_utc()))  # no skill_name
    ev = SkillInvoked(**_env(timestamp=_utc()), skill_name="pr_review")
    assert ev.skill_name == "pr_review"


def test_artifact_created_requires_artifact_id():
    with pytest.raises(ValidationError):
        ArtifactCreated(**_env(timestamp=_utc()))
    ArtifactCreated(**_env(timestamp=_utc()), artifact_id="art-1")


def test_approval_requested_requires_approval_id():
    with pytest.raises(ValidationError):
        ApprovalRequested(**_env(timestamp=_utc()))
    ApprovalRequested(**_env(timestamp=_utc()), approval_id="appr-1")


def test_approved_requires_human_actor_type():
    # actor_type=aria → reject (only humans can grant T4/T5 approval)
    with pytest.raises(ValidationError):
        Approved(**_env(timestamp=_utc()), approval_id="appr-1")
    Approved(**_env(actor="kunal", actor_type=ActorType.human,
                    timestamp=_utc()), approval_id="appr-1")


def test_rejected_requires_human_actor_type():
    with pytest.raises(ValidationError):
        Rejected(**_env(timestamp=_utc()), approval_id="appr-1")
    Rejected(**_env(actor="kunal", actor_type=ActorType.human,
                    timestamp=_utc()), approval_id="appr-1")


def test_action_taken_requires_action_tier():
    with pytest.raises(ValidationError):
        ActionTaken(**_env(timestamp=_utc()))
    ActionTaken(**_env(timestamp=_utc()), action_tier=ActionTier.T3)


def test_failed_requires_error_text():
    with pytest.raises(ValidationError):
        Failed(**_env(timestamp=_utc()))
    Failed(**_env(timestamp=_utc()), error="upstream timeout")


def test_outcome_recorded_requires_outcome():
    with pytest.raises(ValidationError):
        OutcomeRecorded(**_env(timestamp=_utc()))
    OutcomeRecorded(**_env(timestamp=_utc()), outcome="approved")


def test_correction_recorded_requires_human_or_subagent():
    with pytest.raises(ValidationError):
        CorrectionRecorded(**_env(timestamp=_utc()))  # actor_type=aria
    CorrectionRecorded(**_env(actor="kunal", actor_type=ActorType.human,
                              timestamp=_utc()))
    CorrectionRecorded(**_env(actor="subagent:test", actor_type=ActorType.subagent,
                              timestamp=_utc()))


def test_model_used_requires_model_name():
    with pytest.raises(ValidationError):
        ModelUsed(**_env(timestamp=_utc()))
    ModelUsed(**_env(timestamp=_utc()), model_name="claude-opus-4-7")


def test_cost_recorded_requires_estimated_cost():
    with pytest.raises(ValidationError):
        CostRecorded(**_env(timestamp=_utc()))
    CostRecorded(**_env(timestamp=_utc()), estimated_cost=Decimal("0.0612"))


def test_timestamp_must_be_timezone_aware():
    naive = datetime(2026, 6, 11, 12, 0, 0)
    with pytest.raises(ValidationError):
        TaskCreated(**_env(timestamp=naive))


def test_negative_tokens_rejected():
    with pytest.raises(ValidationError):
        ModelUsed(**_env(timestamp=_utc()),
                  model_name="x", token_input=-1)


def test_negative_cost_rejected():
    with pytest.raises(ValidationError):
        CostRecorded(**_env(timestamp=_utc()),
                     estimated_cost=Decimal("-0.01"))


def test_correlation_id_defaults_to_task_id():
    ev = TaskCreated(**_env(task_id="t-xyz", timestamp=_utc()))
    assert ev.correlation_id == "t-xyz"


def test_correlation_id_explicit_preserved():
    ev = TaskCreated(**_env(task_id="t-1", timestamp=_utc(),
                            correlation_id="corr-99"))
    assert ev.correlation_id == "corr-99"


# ═══════════════════════════════════════════════════════════════════════════════
# Section B — Writer / reader roundtrip
# ═══════════════════════════════════════════════════════════════════════════════


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "ledger.jsonl"
    writer = LedgerWriter(path)

    ev1 = TaskCreated(**_env(task_id="t-1", timestamp=_utc()))
    ev2 = Responded(**_env(task_id="t-1", timestamp=_utc(5)))
    assert writer.append(ev1) is True
    assert writer.append(ev2) is True
    assert len(writer) == 2

    reader = LedgerReader(v2_path=path)
    records = reader.v2_events()
    assert len(records) == 2
    assert records[0].event_id == ev1.event_id
    assert records[1].event_id == ev2.event_id


def test_decimal_cost_serialises_without_float_drift(tmp_path):
    path = tmp_path / "ledger.jsonl"
    writer = LedgerWriter(path)
    odd = Decimal("0.123456789012345678")
    writer.append(CostRecorded(**_env(timestamp=_utc()), estimated_cost=odd))

    reader = LedgerReader(v2_path=path)
    [ev] = reader.v2_events()
    assert ev.estimated_cost == odd


def test_subagent_correlation_actor_supported(tmp_path):
    path = tmp_path / "ledger.jsonl"
    writer = LedgerWriter(path)

    # § 28.1 forward-compatibility: subagent actor_type, parent_task_id,
    # workflow_id, agent_role, ledger correlation_id all preserved.
    ev = SkillInvoked(**make_envelope(
        task_id="sub-1", actor="subagent:pr_review_agent",
        actor_type=ActorType.subagent,
        correlation_id="parent-corr-1",
        parent_task_id="parent-1",
        workflow_id="wf-1",
        agent_role="pr_review_agent",
        timestamp=_utc(),
    ), skill_name="pr_review")
    writer.append(ev)

    reader = LedgerReader(v2_path=path)
    [back] = reader.v2_events()
    assert back.actor_type == ActorType.subagent
    assert back.parent_task_id == "parent-1"
    assert back.workflow_id == "wf-1"
    assert back.correlation_id == "parent-corr-1"
    assert back.agent_role == "pr_review_agent"


# ═══════════════════════════════════════════════════════════════════════════════
# Section C — Legacy compatibility
# ═══════════════════════════════════════════════════════════════════════════════


def test_legacy_task_records_read_as_typed_records(tmp_path):
    legacy = tmp_path / "work_ledger.jsonl"
    with legacy.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "task_id": "legacy-1",
            "task_type": "pr_review",
            "routing_reason": "kw",
            "timestamp": "2026-06-04T09:10:01.912418+00:00",
            "week": 4,
        }) + "\n")
        fh.write(json.dumps({
            "task_id": "legacy-2",
            "task_type": "kpi",
            "routing_reason": "kw",
            "timestamp": "2026-06-04T09:10:01.917211+00:00",
            "error": "timeout",
            "week": 4,
        }) + "\n")

    reader = LedgerReader(legacy_task_path=legacy)
    records = reader.read_all()
    assert len(records) == 2
    assert all(isinstance(r, LegacyTaskRecord) for r in records)
    assert records[0].task_type == "pr_review"
    assert records[1].error == "timeout"


def test_legacy_evolution_records_read_as_typed_records(tmp_path):
    legacy = tmp_path / "evolution_events.jsonl"
    with legacy.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "event_type":"approval","task_id":"upd-1","update_id":"upd-1",
            "component_name":"pr_review_prompt","version":"1.0.0",
            "timestamp":"2026-06-09T09:51:58.844250+00:00",
            "actor":"kunal","outcome":"approved_canary",
        }) + "\n")
    reader = LedgerReader(legacy_evolution_path=legacy)
    [rec] = reader.read_all()
    assert isinstance(rec, LegacyEvolutionRecord)
    assert rec.original_type == "approval"
    assert rec.task_id == "upd-1"


def test_unified_reader_serves_all_three_sources(tmp_path):
    v2 = tmp_path / "ledger.jsonl"
    legacy_t = tmp_path / "work_ledger.jsonl"
    legacy_e = tmp_path / "evolution_events.jsonl"

    LedgerWriter(v2).append(TaskCreated(**_env(timestamp=_utc())))
    legacy_t.write_text(json.dumps({
        "task_id":"l-1","task_type":"x","routing_reason":"r",
        "timestamp":"2026-06-04T09:10:01+00:00","week":4,
    }) + "\n", encoding="utf-8")
    legacy_e.write_text(json.dumps({
        "event_type":"approval","task_id":"upd-1","update_id":"upd-1",
        "component_name":"c","version":"1.0.0",
        "timestamp":"2026-06-09T09:51:58+00:00","actor":"k","outcome":"approved_canary",
    }) + "\n", encoding="utf-8")

    reader = LedgerReader(v2_path=v2, legacy_task_path=legacy_t,
                          legacy_evolution_path=legacy_e)
    records = reader.read_all()
    assert len(records) == 3
    by_source_v2 = reader.read_by_source(LedgerSource.v2)
    by_source_lt = reader.read_by_source(LedgerSource.legacy_task)
    by_source_le = reader.read_by_source(LedgerSource.legacy_evolution)
    assert len(by_source_v2) == 1
    assert len(by_source_lt) == 1
    assert len(by_source_le) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Section D — ROI metrics
# ═══════════════════════════════════════════════════════════════════════════════


def _seed_metric_stream(writer: LedgerWriter) -> None:
    """One canonical stream used by the metric tests."""
    t = _utc()
    # task-1: completed with cost + approval (1 human approval)
    writer.append(TaskCreated(**_env("task-1", timestamp=t)))
    writer.append(SkillInvoked(**_env("task-1", timestamp=t + timedelta(milliseconds=50)),
                               skill_name="pr_review"))
    writer.append(ApprovalRequested(**_env("task-1", timestamp=t + timedelta(milliseconds=80)),
                                    approval_id="a-1"))
    writer.append(Approved(**make_envelope(task_id="task-1", actor="kunal",
                                           actor_type=ActorType.human,
                                           timestamp=t + timedelta(seconds=3)),
                            approval_id="a-1"))
    writer.append(ModelUsed(**_env("task-1", timestamp=t + timedelta(seconds=4)),
                            model_name="claude-opus-4-7", model_version="2026-05",
                            token_input=1000, token_output=200))
    writer.append(CostRecorded(**_env("task-1", timestamp=t + timedelta(seconds=5)),
                               estimated_cost=Decimal("0.10")))
    writer.append(Responded(**_env("task-1", timestamp=t + timedelta(seconds=10))))

    # task-2: failed terminally (no responded)
    writer.append(TaskCreated(**_env("task-2", timestamp=t)))
    writer.append(SkillInvoked(**_env("task-2", timestamp=t + timedelta(seconds=1)),
                               skill_name="kpi"))
    writer.append(Failed(**_env("task-2", timestamp=t + timedelta(seconds=2)),
                         error="upstream timeout"))

    # task-3: completed, rejected approval (counts in approval denominator)
    writer.append(TaskCreated(**_env("task-3", timestamp=t)))
    writer.append(ApprovalRequested(**_env("task-3", timestamp=t + timedelta(seconds=1)),
                                     approval_id="a-2"))
    writer.append(Rejected(**make_envelope(task_id="task-3", actor="kunal",
                                            actor_type=ActorType.human,
                                            timestamp=t + timedelta(seconds=3)),
                            approval_id="a-2"))
    writer.append(Responded(**_env("task-3", timestamp=t + timedelta(seconds=4))))


def test_metric_total_tasks_completed(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    _seed_metric_stream(writer)
    reader = LedgerReader(v2_path=writer.path)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=False).summary()
    assert s.total_tasks_completed == 2   # task-1 and task-3


def test_metric_tasks_by_skill(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    _seed_metric_stream(writer)
    reader = LedgerReader(v2_path=writer.path)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=False).summary()
    assert s.tasks_by_skill == {"pr_review": 1, "kpi": 1}


def test_metric_approval_rate_denominator_is_verdicts_only(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    _seed_metric_stream(writer)
    reader = LedgerReader(v2_path=writer.path)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=False).summary()
    # 1 approved + 1 rejected → rate = 0.5
    assert s.approvals_granted == 1
    assert s.approvals_rejected == 1
    assert s.approval_rate == 0.5


def test_metric_failure_rate(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    _seed_metric_stream(writer)
    reader = LedgerReader(v2_path=writer.path)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=False).summary()
    # 1 failed + 2 completed → terminal=3, failure_rate = 1/3
    assert s.failed_tasks == 1
    assert s.terminal_tasks == 3
    assert s.failure_rate == pytest.approx(1 / 3)


def test_metric_avg_time_to_resolution(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    _seed_metric_stream(writer)
    reader = LedgerReader(v2_path=writer.path)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=False).summary()
    # task-1 took 10s, task-3 took 4s → avg = 7000ms
    assert s.avg_time_to_resolution_ms == pytest.approx(7000.0)


def test_metric_cost_uses_decimal(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    _seed_metric_stream(writer)
    reader = LedgerReader(v2_path=writer.path)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=False).summary()
    assert s.estimated_cost_total == Decimal("0.10")
    assert s.tasks_with_cost == 1
    assert s.estimated_cost_per_task == Decimal("0.1000")
    # Critical correctness check: no binary-float ambiguity.
    assert isinstance(s.estimated_cost_total, Decimal)


def test_metric_human_intervention_rate(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    _seed_metric_stream(writer)
    reader = LedgerReader(v2_path=writer.path)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=False).summary()
    # completed = {task-1, task-3}. Both had human actor events.
    assert s.human_intervention_rate == 1.0


def test_metric_artifact_and_correction_counts(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    writer.append(ArtifactCreated(**_env(timestamp=_utc()), artifact_id="art-1"))
    writer.append(ArtifactCreated(**_env(timestamp=_utc(1)), artifact_id="art-2"))
    writer.append(CorrectionRecorded(**make_envelope(
        task_id="t-c", actor="kunal", actor_type=ActorType.human,
        timestamp=_utc(2))))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.artifact_count == 2
    assert s.correction_count == 1


def test_metric_model_usage_breakdown(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    writer.append(ModelUsed(**_env(timestamp=_utc()),
                            model_name="claude-opus-4-7", model_version="2026-05"))
    writer.append(ModelUsed(**_env(timestamp=_utc(1)),
                            model_name="claude-opus-4-7", model_version="2026-05"))
    writer.append(ModelUsed(**_env(timestamp=_utc(2)),
                            model_name="phi-3-mini"))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.model_usage_breakdown == {
        "claude-opus-4-7@2026-05": 2,
        "phi-3-mini": 1,
    }


def test_metrics_with_legacy_task_records_included(tmp_path):
    """Legacy work_ledger.jsonl records contribute to completion/failure counts."""
    legacy = tmp_path / "work_ledger.jsonl"
    legacy.write_text(
        json.dumps({
            "task_id":"l-ok","task_type":"pr_review","routing_reason":"r",
            "timestamp":"2026-06-04T09:10:01+00:00","week":4,
        }) + "\n" + json.dumps({
            "task_id":"l-fail","task_type":"kpi","routing_reason":"r",
            "timestamp":"2026-06-04T09:10:02+00:00","week":4,"error":"x",
        }) + "\n", encoding="utf-8")
    reader = LedgerReader(legacy_task_path=legacy)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=True).summary()
    assert s.total_tasks_completed == 1   # legacy ok
    assert s.failed_tasks == 1
    assert s.terminal_tasks == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Section E — Privacy / redaction
# ═══════════════════════════════════════════════════════════════════════════════


def test_sanitize_metadata_redacts_credential_keys():
    meta = {
        "ok_field": "fine",
        "api_key":  "sk-xyz-1234567890abcdef",
        "nested":   {"password": "p", "token": "abc"},
        "list":     [{"secret": "shh"}, "ok"],
    }
    out = sanitize_metadata(meta)
    assert out["ok_field"] == "fine"
    assert out["api_key"] == REDACTED
    assert out["nested"]["password"] == REDACTED
    assert out["nested"]["token"] == REDACTED
    assert out["list"][0]["secret"] == REDACTED
    assert out["list"][1] == "ok"


def test_sanitize_metadata_redacts_reserved_keys():
    meta = {"raw_prompt": "long prompt", "raw_tool_input": "credentials",
            "confidential": "x", "audience": "developer"}
    out = sanitize_metadata(meta)
    assert out["raw_prompt"] == REDACTED
    assert out["raw_tool_input"] == REDACTED
    assert out["confidential"] == REDACTED
    assert out["audience"] == "developer"


def test_sanitize_metadata_credential_value_patterns():
    meta = {"note": "sk-ant-1234567890abcdef", "header": "Bearer abc"}
    out = sanitize_metadata(meta)
    assert out["note"] == REDACTED
    assert out["header"] == REDACTED


def test_strict_mode_raises_on_secret_key():
    with pytest.raises(RedactionViolation):
        sanitize_metadata({"password": "x"}, strict=True)


def test_event_metadata_is_redacted_automatically():
    ev = TaskCreated(**_env(timestamp=_utc(),
                            metadata={"api_key": "sk-xyz-1234567890abcdef",
                                      "audience": "dev"}))
    assert ev.metadata["api_key"] == REDACTED
    assert ev.metadata["audience"] == "dev"


# ═══════════════════════════════════════════════════════════════════════════════
# Section F — Adversarial
# ═══════════════════════════════════════════════════════════════════════════════


def test_duplicate_event_id_is_idempotent_noop(tmp_path):
    path = tmp_path / "ledger.jsonl"
    writer = LedgerWriter(path)
    ev = TaskCreated(**_env(timestamp=_utc(), event_id="evt-fixed"))
    assert writer.append(ev) is True
    assert writer.append(ev) is False     # idempotent noop
    assert writer.append(ev) is False     # still noop
    # File has only one line
    assert sum(1 for _ in path.open()) == 1


def test_writer_idempotency_survives_restart(tmp_path):
    path = tmp_path / "ledger.jsonl"
    LedgerWriter(path).append(TaskCreated(**_env(event_id="evt-restart",
                                                  timestamp=_utc())))
    # New writer instance: must re-load the seen-set on init.
    w2 = LedgerWriter(path)
    assert w2.append(TaskCreated(**_env(event_id="evt-restart",
                                         timestamp=_utc()))) is False
    assert sum(1 for _ in path.open()) == 1


def test_concurrent_append_is_safe(tmp_path):
    path = tmp_path / "ledger.jsonl"
    writer = LedgerWriter(path)

    n_threads = 8
    per_thread = 25

    def worker(start: int) -> None:
        for i in range(per_thread):
            writer.append(TaskCreated(**_env(
                task_id=f"t-{start}-{i}",
                event_id=f"evt-{start}-{i}",
                timestamp=_utc(),
            )))

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(n_threads)]
    for t in threads: t.start()
    for t in threads: t.join()

    reader = LedgerReader(v2_path=path)
    events = reader.v2_events()
    assert len(events) == n_threads * per_thread
    # IDs are unique → no double-count
    assert len({e.event_id for e in events}) == n_threads * per_thread


def test_malformed_jsonl_surfaces_as_typed_record_not_silent_skip(tmp_path):
    path = tmp_path / "ledger.jsonl"
    LedgerWriter(path).append(TaskCreated(**_env(timestamp=_utc())))
    # Append a broken line directly.
    with path.open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")

    reader = LedgerReader(v2_path=path)
    records = reader.read_all()
    assert len(records) == 2
    assert any(isinstance(r, MalformedLedgerRecord) for r in records)
    bad = next(r for r in records if isinstance(r, MalformedLedgerRecord))
    assert "JSONDecodeError" in bad.parse_error
    assert bad.raw == "this is not json"


def test_unknown_legacy_evolution_schema_surfaces_as_malformed(tmp_path):
    legacy = tmp_path / "evolution_events.jsonl"
    legacy.write_text(json.dumps({
        "event_type": "extremely_new_event_type_unknown_to_v1",
        "task_id": "x",
        "timestamp": "2026-06-09T09:51:58+00:00",
    }) + "\n", encoding="utf-8")
    reader = LedgerReader(legacy_evolution_path=legacy)
    [rec] = reader.read_all()
    assert isinstance(rec, MalformedLedgerRecord)
    assert "unknown legacy evolution event_type" in rec.parse_error


def test_legacy_task_record_missing_task_id_is_malformed(tmp_path):
    legacy = tmp_path / "work_ledger.jsonl"
    legacy.write_text(json.dumps({
        "task_type": "kpi",
        "timestamp": "2026-06-04T09:10:01+00:00",
        "week": 4,
    }) + "\n", encoding="utf-8")
    reader = LedgerReader(legacy_task_path=legacy)
    [rec] = reader.read_all()
    assert isinstance(rec, MalformedLedgerRecord)
    assert "missing task_id" in rec.parse_error


def test_missing_event_specific_required_field_rejected_at_writer(tmp_path):
    """Writer validates the discriminated union — bad payloads never reach disk."""
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    # Bypass the typed constructor and feed a raw dict missing
    # ``routing_reason`` to validate() — must raise.
    bad = {
        "event_type": "routed",
        "event_id":   "evt-bad",
        "event_version": 2,
        "timestamp":  _utc().isoformat(),
        "task_id":    "t-1",
        "correlation_id": "t-1",
        "actor":      "aria",
        "actor_type": "aria",
        "metadata":   {},
    }
    with pytest.raises(ValidationError):
        writer.append(bad)
    # File must NOT have been written.
    assert not (tmp_path / "ledger.jsonl").exists() or \
        (tmp_path / "ledger.jsonl").read_text(encoding="utf-8") == ""


def test_retry_event_does_not_inflate_metrics(tmp_path):
    """If the same event_id is appended twice the metrics must be unaffected."""
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    t = _utc()
    writer.append(TaskCreated(**_env("task-1", event_id="evt-tc", timestamp=t)))
    writer.append(Responded(**_env("task-1", event_id="evt-resp", timestamp=t + timedelta(seconds=5))))

    # Retry both events — idempotent.
    writer.append(TaskCreated(**_env("task-1", event_id="evt-tc", timestamp=t)))
    writer.append(Responded(**_env("task-1", event_id="evt-resp", timestamp=t + timedelta(seconds=5))))

    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.total_tasks_completed == 1   # NOT 2
    assert s.v2_event_count == 2          # exactly two events on disk


def test_persistence_failure_does_not_fabricate_success(tmp_path, monkeypatch):
    """A flush failure raises LedgerPersistenceError; seen-set is NOT updated."""
    path = tmp_path / "ledger.jsonl"
    writer = LedgerWriter(path)

    class _BoomFile:
        def __init__(self, *a, **k): raise OSError("disk full simulation")

    # Patch Path.open in the writer module so the write step blows up.
    import aria.ledger.writer as wmod
    real_open = Path.open
    def _faulty_open(self, mode="r", *args, **kwargs):
        if "a" in mode and str(self).endswith("ledger.jsonl"):
            raise OSError("disk full simulation")
        return real_open(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", _faulty_open, raising=False)

    ev = TaskCreated(**_env(event_id="evt-boom", timestamp=_utc()))
    with pytest.raises(LedgerPersistenceError):
        writer.append(ev)

    # Seen-set must NOT have been updated; a retry after recovery succeeds.
    monkeypatch.setattr(Path, "open", real_open, raising=False)
    assert writer.has_event_id("evt-boom") is False
    assert writer.append(ev) is True


def test_outcome_and_correction_events_supported_end_to_end(tmp_path):
    """Combined: outcome + correction events flow through writer→reader→metrics."""
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    writer.append(TaskCreated(**_env("t-1", timestamp=_utc())))
    writer.append(Responded(**_env("t-1", timestamp=_utc(5))))
    writer.append(OutcomeRecorded(**_env("t-1", timestamp=_utc(10)), outcome="approved"))
    writer.append(CorrectionRecorded(**make_envelope(
        task_id="t-1", actor="kunal", actor_type=ActorType.human,
        timestamp=_utc(20))))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.correction_count == 1
    assert s.total_tasks_completed == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Section G — Round 2 narrow fixes
# ═══════════════════════════════════════════════════════════════════════════════

# G.1 — Universal redaction


def test_credential_in_error_field_is_redacted():
    """[P1] Round-2: error/status/outcome/actor must pass through redaction too."""
    ev = Failed(**_env(timestamp=_utc()),
                 error="auth blew up: sk-1234567890abcdef leaked into the trace")
    assert "sk-1234567890abcdef" not in ev.error
    assert REDACTED in ev.error


def test_credential_in_actor_field_is_redacted():
    ev = TaskCreated(**make_envelope(
        task_id="t-1", actor="user-with-ghp_aaaaaaaaaaaaaaaaaaaa-token",
        actor_type=ActorType.human, timestamp=_utc(),
    ))
    assert "ghp_" not in ev.actor


def test_credential_in_outcome_status_field_is_redacted():
    ev = OutcomeRecorded(**_env(timestamp=_utc()),
                          status="ok Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
                          outcome="approved with sk-ant-1234567890abcdef leaking")
    assert "Bearer" not in ev.status or REDACTED in ev.status
    assert "eyJ" not in ev.status
    assert "sk-ant-" not in ev.outcome


def test_embedded_credential_in_metadata_string_is_redacted():
    """[P1] Round-2: anchored regexes used to miss embedded patterns."""
    ev = TaskCreated(**_env(timestamp=_utc(),
        metadata={"note": "found sk-1234567890abcdef in the logs",
                  "header": "Authorization: Bearer eyJfoo.bar.baz"}))
    assert "sk-1234567890abcdef" not in ev.metadata["note"]
    assert "eyJfoo.bar.baz" not in ev.metadata["header"]


def test_jwt_token_redacted_anywhere_in_string():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4f"
    ev = Failed(**_env(timestamp=_utc()),
                 error=f"upstream: {jwt} rejected")
    assert "eyJhbGciOiJIUzI1NiJ9" not in ev.error
    assert REDACTED in ev.error


def test_aws_access_key_redacted():
    ev = Failed(**_env(timestamp=_utc()),
                 error="boto3 error using AKIAIOSFODNN7EXAMPLE")
    assert "AKIA" not in ev.error or REDACTED in ev.error


# G.2 — Test isolation via env var + autouse fixture


def test_autouse_fixture_redirects_default_writer_to_tmp_path(_isolate_ledger_v2):
    """
    The autouse fixture must point the singleton writer at a per-test
    tmp file so calls into ``aria.ledger.get_default_writer()`` never
    touch the runtime ``work_ledger_v2.jsonl``.
    """
    from aria.ledger.writer import get_default_writer
    w = get_default_writer()
    assert Path(w.path) == _isolate_ledger_v2
    # The default file under apps/backend/ MUST not be touched by a test.
    runtime_default = Path("apps/backend/work_ledger_v2.jsonl").resolve()
    assert Path(w.path).resolve() != runtime_default


def test_respond_node_writes_to_isolated_path_not_runtime_file(_isolate_ledger_v2):
    """Calling respond() inside a test goes to the isolated path."""
    import aria.nodes.respond as respond_node
    runtime_default = Path("apps/backend/work_ledger_v2.jsonl").resolve()
    if runtime_default.exists():
        baseline_lines = sum(1 for _ in runtime_default.open(encoding="utf-8"))
    else:
        baseline_lines = 0
    respond_node._emit_v2_responded(
        task_id="iso-test",
        task_type="pr_review",
        routing_reason="r",
        error=None,
    )
    # Isolated file has the event
    assert _isolate_ledger_v2.exists()
    assert sum(1 for _ in _isolate_ledger_v2.open(encoding="utf-8")) == 1
    # Runtime file is unchanged
    if runtime_default.exists():
        assert sum(1 for _ in runtime_default.open(encoding="utf-8")) == baseline_lines


def test_ledger_disabled_env_var_returns_null_writer(monkeypatch):
    from aria.ledger import writer as ledger_writer
    monkeypatch.setenv("ARIA_LEDGER_V2_DISABLED", "1")
    ledger_writer.reset_default_writer()
    w = ledger_writer.get_default_writer()
    # NullWriter — append is a no-op; nothing on disk anywhere.
    assert w.append(TaskCreated(**_env(timestamp=_utc()))) is False
    ledger_writer.reset_default_writer()


# G.3 — Validate-before-reserve in _load_seen_ids


def test_malformed_record_does_not_reserve_event_id(tmp_path):
    """
    [P1] Round-2: a malformed line containing ``event_id`` must NOT
    cause a later valid event with the same ID to be dropped as a no-op.
    """
    path = tmp_path / "ledger.jsonl"
    # Pre-seed the file with a line that has event_id but cannot validate
    # against the discriminated union (missing required fields).
    path.write_text(
        json.dumps({"event_id": "evt-reserved",
                    "event_type": "task_created"}) + "\n",
        encoding="utf-8",
    )

    writer = LedgerWriter(path)
    # The malformed entry must NOT have reserved evt-reserved.
    valid = TaskCreated(**_env(event_id="evt-reserved", timestamp=_utc()))
    assert writer.append(valid) is True
    # And the reader still surfaces the malformed line as such.
    reader = LedgerReader(v2_path=path)
    records = reader.read_all()
    assert any(isinstance(r, MalformedLedgerRecord) for r in records)
    assert sum(1 for r in records if not isinstance(r, MalformedLedgerRecord)) == 1


def test_conflicting_payload_for_same_event_id_is_rejected(tmp_path):
    """A second append with same event_id but different content raises ValueError."""
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    ev1 = TaskCreated(**_env(event_id="evt-dup", actor="aria",
                              actor_type=ActorType.aria, timestamp=_utc()))
    assert writer.append(ev1) is True
    # Identical retry — still idempotent no-op.
    assert writer.append(ev1) is False
    # Different payload, same id → reject.
    ev2 = TaskCreated(**_env(event_id="evt-dup", actor="someone-else",
                              actor_type=ActorType.human, timestamp=_utc(5)))
    with pytest.raises(ValueError):
        writer.append(ev2)


# G.4 — Lifecycle-safe metrics


def test_tasks_by_skill_counts_distinct_task_skill_pairs(tmp_path):
    """
    [P1] Round-2: retrying SkillInvoked for the same (task_id, skill) must
    NOT inflate tasks_by_skill.
    """
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    writer.append(SkillInvoked(**_env("task-1", event_id="evt-si-1",
                                       timestamp=_utc()), skill_name="kpi"))
    # Retry: same task, same skill, different event_id (a real retry)
    writer.append(SkillInvoked(**_env("task-1", event_id="evt-si-2",
                                       timestamp=_utc(1)), skill_name="kpi"))
    # Second task on the same skill — that SHOULD count
    writer.append(SkillInvoked(**_env("task-2", event_id="evt-si-3",
                                       timestamp=_utc(2)), skill_name="kpi"))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.tasks_by_skill == {"kpi": 2}


def test_approvals_count_distinct_approval_ids(tmp_path):
    """Two Approved events for the same approval_id count once."""
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    writer.append(Approved(**make_envelope(
        task_id="t-1", actor="kunal", actor_type=ActorType.human,
        event_id="evt-a1", timestamp=_utc()), approval_id="appr-1"))
    # Retry — same approval_id, different event_id
    writer.append(Approved(**make_envelope(
        task_id="t-1", actor="kunal", actor_type=ActorType.human,
        event_id="evt-a2", timestamp=_utc(1)), approval_id="appr-1"))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.approvals_granted == 1


def test_time_to_resolution_uses_first_responded_not_latest_event(tmp_path):
    """
    [P1] Round-2: corrections / outcomes recorded AFTER Responded must
    not stretch the time-to-resolution metric.
    """
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    writer.append(TaskCreated(**_env("t-1", event_id="e1", timestamp=_utc())))
    writer.append(Responded(**_env("t-1", event_id="e2", timestamp=_utc(20))))
    # Out-of-band activity AFTER the response — must NOT extend the metric.
    writer.append(OutcomeRecorded(**_env("t-1", event_id="e3",
                                          timestamp=_utc(600)),
                                   outcome="approved"))
    writer.append(CorrectionRecorded(**make_envelope(
        task_id="t-1", actor="kunal", actor_type=ActorType.human,
        event_id="e4", timestamp=_utc(900))))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.avg_time_to_resolution_ms == 20_000.0


# ═══════════════════════════════════════════════════════════════════════════════
# Section H — Round 3 narrow fixes
# ═══════════════════════════════════════════════════════════════════════════════

# H.1 — Writer is the final sanitization boundary


def test_model_copy_secret_leak_is_resanitized_by_writer(tmp_path):
    """
    [P1] Round-3: ``model_copy(update=...)`` skips validators. The writer
    must dump-and-revalidate so the redacted-freetext validator runs
    again and the secret is masked before disk.
    """
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    clean = Failed(**_env(timestamp=_utc()), error="legitimate failure")
    leaked = clean.model_copy(update={"error": "leaked sk-1234567890abcdef key"})
    # The in-memory copy still contains the secret because model_copy
    # bypasses validators — that's a Pydantic property, not a bug we can
    # fix at the model layer. The writer is the safety net.
    assert "sk-1234567890abcdef" in leaked.error
    writer.append(leaked)
    reader = LedgerReader(v2_path=writer.path)
    [persisted] = reader.v2_events()
    assert "sk-1234567890abcdef" not in persisted.error
    assert REDACTED in persisted.error


def test_routing_reason_is_redacted_when_secret_present(tmp_path):
    """
    [P1] Round-3: ``Routed.routing_reason`` lives outside the original
    free-text set. It must also pass through credential masking.
    """
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    ev = Routed(**_env(timestamp=_utc()),
                 routing_reason="matched keys ghp_aaaaaaaaaaaaaaaaaaaa in input")
    writer.append(ev)
    reader = LedgerReader(v2_path=writer.path)
    [persisted] = reader.v2_events()
    assert "ghp_" not in persisted.routing_reason


def test_writer_revalidates_raw_dict_input(tmp_path):
    """
    A caller that bypasses the typed constructors and hands the writer a
    raw dict with an unredacted error must still get sanitised output on
    disk.
    """
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    raw = {
        "event_type":  "failed",
        "event_id":    "evt-raw",
        "event_version": 2,
        "timestamp":   _utc().isoformat(),
        "task_id":     "t-1",
        "correlation_id": "t-1",
        "actor":       "aria",
        "actor_type":  "aria",
        "error":       "boom sk-1234567890abcdef",
        "metadata":    {},
    }
    writer.append(raw)
    reader = LedgerReader(v2_path=writer.path)
    [persisted] = reader.v2_events()
    assert "sk-1234567890abcdef" not in persisted.error


# H.2 — Per-skill rates


def test_approval_rate_by_skill_present_in_summary(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    t = _utc()
    # Two pr_review tasks, both approved
    for i, tid in enumerate(["pr-1", "pr-2"]):
        writer.append(TaskCreated(**_env(tid, timestamp=t + timedelta(seconds=i))))
        writer.append(SkillInvoked(**_env(tid, timestamp=t + timedelta(seconds=i + 0.1)),
                                    skill_name="pr_review"))
        writer.append(ApprovalRequested(**_env(tid, timestamp=t + timedelta(seconds=i + 0.2)),
                                         approval_id=f"appr-pr-{i}"))
        writer.append(Approved(**make_envelope(
            task_id=tid, actor="kunal", actor_type=ActorType.human,
            timestamp=t + timedelta(seconds=i + 0.3)),
            approval_id=f"appr-pr-{i}"))
        writer.append(Responded(**_env(tid, timestamp=t + timedelta(seconds=i + 0.4))))
    # One kpi task, rejected
    writer.append(TaskCreated(**_env("kpi-1", timestamp=t)))
    writer.append(SkillInvoked(**_env("kpi-1", timestamp=t + timedelta(seconds=0.1)),
                                skill_name="kpi"))
    writer.append(ApprovalRequested(**_env("kpi-1", timestamp=t + timedelta(seconds=0.2)),
                                     approval_id="appr-kpi-1"))
    writer.append(Rejected(**make_envelope(
        task_id="kpi-1", actor="kunal", actor_type=ActorType.human,
        timestamp=t + timedelta(seconds=0.3)),
        approval_id="appr-kpi-1"))
    writer.append(Responded(**_env("kpi-1", timestamp=t + timedelta(seconds=0.4))))

    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.approval_rate_by_skill == {"pr_review": 1.0, "kpi": 0.0}


def test_failure_rate_by_skill_present_in_summary(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    t = _utc()
    # pr_review: 1 completed, 1 failed → 0.5
    writer.append(TaskCreated(**_env("pr-ok", timestamp=t)))
    writer.append(SkillInvoked(**_env("pr-ok", timestamp=t),
                                skill_name="pr_review"))
    writer.append(Responded(**_env("pr-ok", timestamp=t + timedelta(seconds=2))))
    writer.append(TaskCreated(**_env("pr-fail", timestamp=t)))
    writer.append(SkillInvoked(**_env("pr-fail", timestamp=t),
                                skill_name="pr_review"))
    writer.append(Failed(**_env("pr-fail", timestamp=t + timedelta(seconds=1)),
                          error="crash"))
    # kpi: 1 failed → 1.0
    writer.append(TaskCreated(**_env("kpi-fail", timestamp=t)))
    writer.append(SkillInvoked(**_env("kpi-fail", timestamp=t),
                                skill_name="kpi"))
    writer.append(Failed(**_env("kpi-fail", timestamp=t + timedelta(seconds=1)),
                          error="timeout"))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.failure_rate_by_skill == {"pr_review": 0.5, "kpi": 1.0}


# H.3 — Cross-source dedup


def test_mirrored_task_not_double_counted_in_tasks_by_skill(tmp_path):
    """
    [P1] Round-3: production mirrors a completed task into BOTH ledgers
    (v2 ``Responded`` from respond.py AND the legacy work_ledger.jsonl
    line via ``log_task``). Unified metrics MUST count the task once.
    """
    v2 = tmp_path / "ledger.jsonl"
    legacy = tmp_path / "work_ledger.jsonl"
    writer = LedgerWriter(v2)
    writer.append(SkillInvoked(**_env("mirror-t", timestamp=_utc()),
                                skill_name="kpi"))
    writer.append(Responded(**_env("mirror-t", timestamp=_utc(2))))
    # Same task_id, written to legacy by log_task
    legacy.write_text(json.dumps({
        "task_id": "mirror-t",
        "task_type": "kpi",
        "routing_reason": "kw",
        "timestamp": "2026-06-04T09:10:01+00:00",
        "week": 4,
    }) + "\n", encoding="utf-8")

    reader = LedgerReader(v2_path=v2, legacy_task_path=legacy)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=True).summary()
    assert s.tasks_by_skill == {"kpi": 1}
    assert s.total_tasks_completed == 1


def test_legacy_only_task_still_appears_in_tasks_by_skill(tmp_path):
    """A task that exists ONLY in the legacy ledger contributes to the skill count."""
    legacy = tmp_path / "work_ledger.jsonl"
    legacy.write_text(json.dumps({
        "task_id": "legacy-only",
        "task_type": "kpi",
        "routing_reason": "kw",
        "timestamp": "2026-06-04T09:10:01+00:00",
        "week": 4,
    }) + "\n", encoding="utf-8")
    reader = LedgerReader(legacy_task_path=legacy)
    s = LedgerMetrics(reader.read_all(), include_legacy_tasks=True).summary()
    assert s.tasks_by_skill == {"kpi": 1}


# H.4 — Idempotent response emission


def test_respond_emission_is_idempotent_on_retry(_isolate_ledger_v2):
    """[P2] Round-3: respond() retries do not write multiple ledger lines."""
    import aria.nodes.respond as respond_node
    respond_node._emit_v2_responded(
        task_id="retry-task", task_type="pr_review",
        routing_reason="r", error=None,
    )
    respond_node._emit_v2_responded(
        task_id="retry-task", task_type="pr_review",
        routing_reason="r", error=None,
    )
    respond_node._emit_v2_responded(
        task_id="retry-task", task_type="pr_review",
        routing_reason="r", error=None,
    )
    assert sum(1 for _ in _isolate_ledger_v2.open(encoding="utf-8")) == 1


def test_respond_responded_then_failed_for_same_task_raises_terminal_conflict(_isolate_ledger_v2):
    """
    Round-5 invariant: a task has AT MOST ONE terminal outcome. After
    Responded is logged for task X, an attempt to log Failed for the same
    task surfaces ``TerminalOutcomeConflict`` (subclass of ``ValueError``).
    respond.py's narrow except does NOT swallow this — it's a logic bug.
    """
    import aria.nodes.respond as respond_node
    from aria.ledger import TerminalOutcomeConflict

    respond_node._emit_v2_responded(
        task_id="lifecycle-t", task_type="pr_review",
        routing_reason="r", error=None,
    )
    with pytest.raises(TerminalOutcomeConflict):
        respond_node._emit_v2_responded(
            task_id="lifecycle-t", task_type="pr_review",
            routing_reason="r", error="upstream timeout",
        )
    # Exactly one line — the Responded — durably persisted.
    assert sum(1 for _ in _isolate_ledger_v2.open(encoding="utf-8")) == 1


# H.5 — Tightened typed contract


def test_empty_event_id_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**_env(event_id="", timestamp=_utc()))


def test_empty_task_id_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**make_envelope(task_id="", actor="aria",
                                     actor_type=ActorType.aria,
                                     timestamp=_utc()))


def test_empty_actor_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**make_envelope(task_id="t-1", actor="",
                                     actor_type=ActorType.aria,
                                     timestamp=_utc()))


def test_unknown_event_version_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**_env(timestamp=_utc()), event_version=99)


def test_mkdir_failure_is_wrapped_into_persistence_error(tmp_path):
    """A blocking file at the parent path → LedgerPersistenceError, not raw OSError."""
    # Plant a regular FILE where the writer will try to create a parent dir.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    target = blocker / "subdir" / "ledger.jsonl"  # parent (blocker/subdir) cannot be created
    writer = LedgerWriter(target)
    with pytest.raises(LedgerPersistenceError):
        writer.append(TaskCreated(**_env(timestamp=_utc())))


# ═══════════════════════════════════════════════════════════════════════════════
# Section I — Round 4 narrow fixes
# ═══════════════════════════════════════════════════════════════════════════════

# I.1 — Multi-skill counting + attribution


def test_multi_skill_task_counts_in_each_skill(tmp_path):
    """[P1] Round-4: a task invoking pr_review AND qa contributes to BOTH skills."""
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    t = _utc()
    writer.append(TaskCreated(**_env("multi-1", timestamp=t)))
    writer.append(SkillInvoked(**_env("multi-1", timestamp=t),
                                skill_name="pr_review"))
    writer.append(SkillInvoked(**_env("multi-1", timestamp=t + timedelta(seconds=1)),
                                skill_name="qa"))
    writer.append(Responded(**_env("multi-1", timestamp=t + timedelta(seconds=2))))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.tasks_by_skill == {"pr_review": 1, "qa": 1}


def test_multi_skill_task_attributes_outcome_to_first_skill_only(tmp_path):
    """
    Task-level outcomes (failure/approval) are attributed to ONE skill —
    the earliest SkillInvoked. A failure on a multi-skill task counts
    in the first skill's failure rate, not both.
    """
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    t = _utc()
    writer.append(SkillInvoked(**_env("multi-fail", timestamp=t),
                                skill_name="pr_review"))
    writer.append(SkillInvoked(**_env("multi-fail", timestamp=t + timedelta(seconds=1)),
                                skill_name="qa"))
    writer.append(Failed(**_env("multi-fail", timestamp=t + timedelta(seconds=2)),
                         error="crash"))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    # pr_review (earlier) gets the failure; qa stays at 0.0 (denominator 0 → None)
    assert s.failure_rate_by_skill["pr_review"] == 1.0
    assert s.failure_rate_by_skill["qa"] is None


# I.2 — Structural identifiers reject credentials + whitespace-only


def test_credential_in_task_id_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**make_envelope(
            task_id="task-sk-1234567890abcdef", actor="aria",
            actor_type=ActorType.aria, timestamp=_utc(),
        ))


def test_credential_in_event_id_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**_env(event_id="evt-ghp_aaaaaaaaaaaaaaaaaaaa",
                            timestamp=_utc()))


def test_credential_in_correlation_id_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**make_envelope(
            task_id="t-1", actor="aria", actor_type=ActorType.aria,
            correlation_id="corr-sk-ant-aaaaaaaaaaaaaaaaaa",
            timestamp=_utc(),
        ))


def test_credential_in_parent_task_id_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**make_envelope(
            task_id="t-1", actor="aria", actor_type=ActorType.aria,
            parent_task_id="parent-AKIAIOSFODNN7EXAMPLE",
            timestamp=_utc(),
        ))


def test_credential_in_workflow_id_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**make_envelope(
            task_id="t-1", actor="aria", actor_type=ActorType.aria,
            workflow_id="wf-Bearer eyJ.foo.bar",
            timestamp=_utc(),
        ))


def test_whitespace_only_event_id_rejected():
    """min_length=1 accepts ' ' — the custom validator catches it."""
    with pytest.raises(ValidationError):
        TaskCreated(**_env(event_id="   ", timestamp=_utc()))


def test_whitespace_only_task_id_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**make_envelope(
            task_id="\t  \n", actor="aria", actor_type=ActorType.aria,
            timestamp=_utc(),
        ))


def test_whitespace_only_actor_rejected():
    with pytest.raises(ValidationError):
        TaskCreated(**make_envelope(
            task_id="t-1", actor="   ", actor_type=ActorType.aria,
            timestamp=_utc(),
        ))


def test_actor_with_credential_still_redacted_not_rejected():
    """actor is free-text, not a correlation key — it gets redacted, not rejected."""
    ev = TaskCreated(**make_envelope(
        task_id="t-1", actor="agent-with-ghp_aaaaaaaaaaaaaaaaaaaa-token",
        actor_type=ActorType.human, timestamp=_utc(),
    ))
    assert "ghp_" not in ev.actor


# I.3 — Per-skill rate dicts include zero-denominator skills as None


def test_per_skill_rates_include_all_known_skills_with_none(tmp_path):
    """
    A skill that has activity (SkillInvoked) but no verdicts must appear
    in approval_rate_by_skill with value None. Same for failure_rate_by_skill
    on skills with no terminal tasks.
    """
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    t = _utc()
    # pr_review: one task, completed, NO approval verdicts at all
    writer.append(SkillInvoked(**_env("pr-1", timestamp=t),
                                skill_name="pr_review"))
    writer.append(Responded(**_env("pr-1", timestamp=t + timedelta(seconds=1))))
    # kpi: one task with an approval verdict (approved)
    writer.append(SkillInvoked(**_env("kpi-1", timestamp=t),
                                skill_name="kpi"))
    writer.append(ApprovalRequested(**_env("kpi-1", timestamp=t),
                                     approval_id="appr-kpi-1"))
    writer.append(Approved(**make_envelope(
        task_id="kpi-1", actor="kunal", actor_type=ActorType.human,
        timestamp=t + timedelta(seconds=1)), approval_id="appr-kpi-1"))
    writer.append(Responded(**_env("kpi-1", timestamp=t + timedelta(seconds=2))))
    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    # Both skills present; pr_review has None (no verdicts).
    assert s.approval_rate_by_skill["pr_review"] is None
    assert s.approval_rate_by_skill["kpi"] == 1.0
    # And both present in failure_rate_by_skill (both completed, neither failed → 0.0).
    assert s.failure_rate_by_skill["pr_review"] == 0.0
    assert s.failure_rate_by_skill["kpi"] == 0.0


# I.4 — Respond truly idempotent (no swallowed ValueError)


def test_respond_retry_takes_short_circuit_not_conflict_path(_isolate_ledger_v2):
    """
    [P2] Round-4: respond.py must use has_event_id() to short-circuit
    retries so the writer's fingerprint-conflict path is NEVER reached
    via the broad except. The result is a clean idempotent return.
    """
    import aria.nodes.respond as respond_node

    # Two retries with a real time gap (different timestamps each time)
    respond_node._emit_v2_responded(
        task_id="iretry-task", task_type="pr_review",
        routing_reason="r", error=None,
    )
    import time
    time.sleep(0.01)  # ensure timestamp differs
    respond_node._emit_v2_responded(
        task_id="iretry-task", task_type="pr_review",
        routing_reason="r", error=None,
    )
    time.sleep(0.01)
    respond_node._emit_v2_responded(
        task_id="iretry-task", task_type="pr_review",
        routing_reason="r", error=None,
    )
    # ONE durable line. If respond.py had not short-circuited, the writer
    # would have raised ValueError on the second/third attempts due to
    # the timestamp fingerprint diff — the broad except would have
    # swallowed it. The has_event_id short-circuit prevents that path.
    assert sum(1 for _ in _isolate_ledger_v2.open(encoding="utf-8")) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Section J — Round 5 narrow fixes
# ═══════════════════════════════════════════════════════════════════════════════

# J.1 — Atomic check-and-append under concurrent retry


def test_writer_idempotent_on_collision_returns_false_for_diff_payload(tmp_path):
    """The flag silently no-ops on fingerprint mismatch (deterministic-id path)."""
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    ev1 = TaskCreated(**_env(event_id="evt-detr", timestamp=_utc()))
    assert writer.append(ev1, idempotent_on_collision=True) is True
    # Same id, DIFFERENT timestamp → with the flag this is a no-op,
    # WITHOUT the flag this raises (existing strict path).
    ev2 = TaskCreated(**_env(event_id="evt-detr", timestamp=_utc(5)))
    assert writer.append(ev2, idempotent_on_collision=True) is False
    with pytest.raises(ValueError):
        writer.append(ev2, idempotent_on_collision=False)
    assert sum(1 for _ in (tmp_path / "ledger.jsonl").open()) == 1


def test_concurrent_respond_retries_atomic_no_swallowed_conflict(_isolate_ledger_v2):
    """
    [P1] Round-5: two threads call _emit_v2_responded for the same task
    simultaneously. The atomic check-and-append inside the writer lock
    guarantees:
      - exactly ONE durable line on disk
      - neither thread raises (no swallowed ValueError)
    Uses a threading.Barrier so both threads attempt the append at the
    same moment — that's the race window the previous design failed in.
    """
    import threading
    import aria.nodes.respond as respond_node

    n = 16
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def worker():
        try:
            barrier.wait()
            respond_node._emit_v2_responded(
                task_id="race-task", task_type="pr_review",
                routing_reason="r", error=None,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert errors == [], f"No worker should have raised; got {errors}"
    assert sum(1 for _ in _isolate_ledger_v2.open(encoding="utf-8")) == 1


# J.2 — Single terminal outcome per task


def test_writer_rejects_failed_after_responded_for_same_task(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    from aria.ledger import TerminalOutcomeConflict
    writer.append(Responded(**_env("term-1", timestamp=_utc())))
    with pytest.raises(TerminalOutcomeConflict):
        writer.append(Failed(**_env("term-1", timestamp=_utc(5)), error="boom"))
    # The Failed must NOT have been written, even though it had a unique event_id.
    assert sum(1 for _ in (tmp_path / "ledger.jsonl").open()) == 1


def test_writer_rejects_responded_after_failed_for_same_task(tmp_path):
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    from aria.ledger import TerminalOutcomeConflict
    writer.append(Failed(**_env("term-2", timestamp=_utc()), error="early fail"))
    with pytest.raises(TerminalOutcomeConflict):
        writer.append(Responded(**_env("term-2", timestamp=_utc(5))))
    assert sum(1 for _ in (tmp_path / "ledger.jsonl").open()) == 1


def test_terminal_outcome_invariant_survives_writer_restart(tmp_path):
    """A new writer instance scans the file and re-loads the terminal map."""
    path = tmp_path / "ledger.jsonl"
    LedgerWriter(path).append(Responded(**_env("term-restart", timestamp=_utc())))
    # Fresh writer instance — must re-load terminal-task set on init.
    from aria.ledger import TerminalOutcomeConflict
    w2 = LedgerWriter(path)
    with pytest.raises(TerminalOutcomeConflict):
        w2.append(Failed(**_env("term-restart", timestamp=_utc(5)),
                          error="late fail"))


def test_load_seen_ids_detects_preexisting_conflicting_terminals(tmp_path):
    """
    [P2] Round-6: a JSONL file already containing BOTH Responded and
    Failed for the same task is an inconsistent ledger. The writer must
    refuse to open such a file — otherwise startup silently picks one
    outcome, hides the conflict, and metrics under-report failures.

    Builds the file by manually writing the two records' JSON (the
    writer's normal append path would have rejected the second).
    """
    from aria.ledger import TerminalOutcomeConflict

    path = tmp_path / "ledger.jsonl"
    conflicted_task = "conflicted-task"
    resp = Responded(**_env(conflicted_task, event_id="evt-resp",
                              timestamp=_utc()))
    fail = Failed(**_env(conflicted_task, event_id="evt-fail",
                          timestamp=_utc(5)),
                   error="contradictory record")
    # Write BOTH lines straight to disk, bypassing the writer's
    # in-process invariant — this simulates a tampered or legacy file.
    with path.open("w", encoding="utf-8") as fh:
        fh.write(resp.model_dump_json() + "\n")
        fh.write(fail.model_dump_json() + "\n")

    # Opening a writer over this file must REFUSE rather than silently
    # accept the inconsistency.
    with pytest.raises(TerminalOutcomeConflict):
        LedgerWriter(path)


def test_metrics_after_terminal_conflict_only_count_durable_outcome(tmp_path):
    """
    Even if a caller tried to log both outcomes, only the first reaches
    disk. Metrics agree.
    """
    writer = LedgerWriter(tmp_path / "ledger.jsonl")
    from aria.ledger import TerminalOutcomeConflict
    writer.append(TaskCreated(**_env("t-m", timestamp=_utc())))
    writer.append(SkillInvoked(**_env("t-m", timestamp=_utc()), skill_name="kpi"))
    writer.append(Responded(**_env("t-m", timestamp=_utc(5))))
    with pytest.raises(TerminalOutcomeConflict):
        writer.append(Failed(**_env("t-m", timestamp=_utc(6)), error="x"))

    s = LedgerMetrics(LedgerReader(v2_path=writer.path).read_all(),
                       include_legacy_tasks=False).summary()
    assert s.total_tasks_completed == 1
    assert s.failed_tasks == 0
    assert s.terminal_tasks == 1


def test_respond_does_not_swallow_validation_errors(_isolate_ledger_v2):
    """
    A bug that causes a ValidationError in event construction (e.g. an
    illegal actor) must propagate, NOT get silently swallowed by the
    narrow handler. Confirm by patching to force a ValidationError.
    """
    import aria.nodes.respond as respond_node
    from unittest.mock import patch
    from aria.ledger.events import Responded

    def _boom(*args, **kwargs):
        from pydantic import ValidationError
        from pydantic_core import PydanticCustomError
        raise ValidationError.from_exception_data(
            "Responded",
            [{"type": "value_error", "loc": (), "input": kwargs,
              "ctx": {"error": PydanticCustomError("e", "synthetic")}}],
        )

    with patch.object(Responded, "__init__", _boom):
        with pytest.raises(Exception):  # ValidationError is the real type
            respond_node._emit_v2_responded(
                task_id="surface-bug", task_type="pr_review",
                routing_reason="r", error=None,
            )
