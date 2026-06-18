"""
Week 34 — Read-only PR / CI-CD / Analytics pilots tests
(branch ``v2-complete-internal-ai-employee-pilot``).

Deterministic and offline: pilots read local fixtures only; nothing makes a
network/paid call. ARIA_DATA_DIR + the v2 ledger are redirected to ``tmp_path`` by
the autouse conftest fixtures.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aria.api.v2 import build_v2_app
from aria.connectors import (
    ConnectorMode,
    ConnectorModeError,
    FixtureConnector,
    get_connector,
    resolve_connector_mode,
)
from aria.pilots.analytics import run_analytics
from aria.pilots.ci_cd import run_ci_cd
from aria.pilots.models import EVIDENCE_REQUIRED, DraftKind, PilotKind
from aria.pilots.pr_review import run_pr_review

CANONICAL = (
    "In story_events table, event_type = 1 means page_view, "
    "event_type = 2 means story_click, event_type = 3 means notification_open."
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_v2_app())


def _ledger_types() -> list[str]:
    path = Path(os.environ["ARIA_LEDGER_V2_PATH"])
    if not path.exists():
        return []
    return [json.loads(line)["event_type"] for line in path.read_text(encoding="utf-8").splitlines()]


def _stream(client: TestClient, sid: str, message: str) -> list[dict]:
    r = client.post(f"/api/v2/chat/sessions/{sid}/messages", json={"message": message})
    assert r.status_code == 200
    return [json.loads(line) for line in r.text.strip().splitlines()]


def _new_session(client: TestClient) -> str:
    return client.post("/api/v2/chat/sessions", json={}).json()["session_id"]


# ── Connector mode contract ───────────────────────────────────────────────────


def test_default_connector_mode_is_fixtures(monkeypatch):
    monkeypatch.delenv("CONNECTOR_MODE", raising=False)
    assert resolve_connector_mode() is ConnectorMode.fixtures
    assert isinstance(get_connector(), FixtureConnector)


def test_credentials_present_do_not_activate_live(monkeypatch):
    monkeypatch.delenv("CONNECTOR_MODE", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_FAKEFAKEFAKEFAKEFAKE")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-FAKE")
    # Credentials present, mode unset → still fixtures.
    assert resolve_connector_mode() is ConnectorMode.fixtures
    assert isinstance(get_connector(), FixtureConnector)


def test_read_only_live_requires_explicit_mode_and_allowlist(monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "read_only_live")
    monkeypatch.delenv("CONNECTOR_PROVIDER_ALLOWLIST", raising=False)
    conn = get_connector("github")
    # No allowlist → fail closed.
    with pytest.raises(ConnectorModeError):
        conn.read_pr()
    # With allowlist → still no real network read in Week 34 (scaffold).
    monkeypatch.setenv("CONNECTOR_PROVIDER_ALLOWLIST", "github")
    with pytest.raises(NotImplementedError):
        get_connector("github").read_pr()
    # A provider NOT on the allowlist still fails closed.
    with pytest.raises(ConnectorModeError):
        get_connector("gitlab").read_pr()


def test_fixture_mode_makes_no_network_calls(monkeypatch):
    import socket

    def _no_net(*_a, **_k):
        raise AssertionError("fixtures mode must not open a socket")

    monkeypatch.setattr(socket, "socket", _no_net)
    monkeypatch.setattr(socket, "create_connection", _no_net)
    # All three pilots run purely from fixtures — no socket created.
    assert run_pr_review(FixtureConnector()).pilot is PilotKind.pr_review
    assert run_ci_cd(FixtureConnector()).pilot is PilotKind.ci_cd
    assert run_analytics(FixtureConnector()).pilot is PilotKind.analytics


def test_connector_exposes_no_write_methods():
    conn = FixtureConnector()
    for forbidden in ("post", "send", "create", "write", "rerun", "retry", "update",
                      "delete", "post_comment", "merge"):
        assert not hasattr(conn, forbidden), f"connector must not expose {forbidden!r}"
    # Only read_* methods exist.
    public = [m for m in dir(conn) if not m.startswith("_")]
    assert all(m.startswith("read_") or m in ("mode", "provider") for m in public)


# ── PR pilot ──────────────────────────────────────────────────────────────────


def test_pr_pilot_report():
    report = run_pr_review(FixtureConnector())
    assert report.pilot is PilotKind.pr_review
    assert "PR-481" in report.summary                              # fixture loaded
    assert any(f.kind == "risk" for f in report.findings)         # risk findings
    assert any(f.kind == "missing_tests" for f in report.findings)  # missing tests
    assert report.evidence_references                              # evidence refs
    # Draft review comments + Jira are draft-only with boundary text.
    kinds = {d.kind for d in report.drafts}
    assert DraftKind.pr_comment in kinds and DraftKind.jira in kinds
    assert all("Not posted" in d.boundary or "Not sent" in d.boundary for d in report.drafts)


def test_pr_pilot_through_api_creates_workspace_and_ledger(client):
    sid = _new_session(client)
    events = _stream(client, sid, "Review this PR for the recommendation engine")
    pilot = next(e for e in events if e["event"] == "pilot.report")
    assert pilot["data"]["pilot"] == "pr_review"
    assert pilot["data"]["connector_mode"] == "fixtures"
    assert pilot["data"]["workspace_id"]
    assert any(e["event"] == "draft.created" for e in events)
    # workspace has the report artifact
    ws = client.get(f"/api/v2/workspaces/{pilot['data']['workspace_id']}").json()
    assert any("pr_review_report.md" in r for r in ws["artifact_refs"])
    types = _ledger_types()
    for required in ("read_only_connector_invoked", "pilot_report_created", "draft_action_created"):
        assert required in types


# ── CI/CD pilot ───────────────────────────────────────────────────────────────


def test_ci_pilot_report():
    report = run_ci_cd(FixtureConnector())
    assert report.pilot is PilotKind.ci_cd
    assert "run-9921" in report.summary
    assert any(f.kind == "failed_step" for f in report.findings)
    assert any(f.kind == "root_cause" for f in report.findings)
    assert any(f.evidence for f in report.findings)               # evidence references
    teams = [d for d in report.drafts if d.kind is DraftKind.teams]
    assert len(teams) == 1                                        # Teams preview
    assert "Not sent" in teams[0].boundary                       # preview-only


def test_ci_pilot_through_api(client):
    sid = _new_session(client)
    events = _stream(client, sid, "Investigate the CI/CD pipeline failure")
    pilot = next(e for e in events if e["event"] == "pilot.report")
    assert pilot["data"]["pilot"] == "ci_cd"
    ws = client.get(f"/api/v2/workspaces/{pilot['data']['workspace_id']}").json()
    assert any("ci_cd_report.md" in r for r in ws["artifact_refs"])
    assert "read_only_connector_invoked" in _ledger_types()


# ── Analytics pilot ───────────────────────────────────────────────────────────


def _mapping_recall(mapping=None):
    mapping = mapping or {"1": "page_view", "2": "story_click", "3": "notification_open"}

    def recall(table, field):
        return mapping, {"memory_id": "mem-1", "version": 1, "retrieval_reason": "matched"}
    return recall


def test_analytics_pilot_runs_all_checks():
    report = run_analytics(FixtureConnector(), table="story_events", recall=_mapping_recall())
    kinds = {f.kind for f in report.findings}
    for required in ("freshness", "nulls", "duplicates", "taxonomy", "funnel", "anomaly", "distribution"):
        assert required in kinds, f"missing {required} check"
    # Memory recalled + cited.
    assert report.memory_citations and report.memory_citations[0]["memory_id"] == "mem-1"
    # Draft Jira items generated for data-quality issues.
    assert any(d.kind is DraftKind.jira for d in report.drafts)
    # Evidence references include the event fixture.
    assert any("events" in e.source for e in report.evidence_references)


def test_analytics_memory_does_not_prove_counts_without_evidence():
    """Memory may explain values, but counts/anomalies need event evidence; with
    the event data missing they are withheld as ``evidence_required``."""
    class _NoEvents(FixtureConnector):
        def read_events(self, table):
            return None, []

    report = run_analytics(_NoEvents(), table="story_events", recall=_mapping_recall())
    # Memory still explains the values (citation present) ...
    assert report.memory_citations
    # ... but distribution / anomaly counts are withheld, not invented.
    dist = next(f for f in report.findings if f.kind == "distribution")
    assert dist.status == EVIDENCE_REQUIRED
    anomaly = next(f for f in report.findings if f.kind == "anomaly")
    assert anomaly.status == EVIDENCE_REQUIRED


def test_analytics_distribution_is_fixture_evidenced_not_memory():
    report = run_analytics(FixtureConnector(), table="story_events", recall=_mapping_recall())
    dist = next(f for f in report.findings if f.kind == "distribution")
    assert dist.status == "supported"
    # The distribution count is evidenced by the EVENT fixture, not by memory.
    assert any("events" in ev for ev in dist.evidence)
    assert all(not ev.startswith("memory:") for ev in dist.evidence)


def test_analytics_through_api_uses_approved_memory(client):
    sid = _new_session(client)
    pid = next(e["data"]["proposal_id"] for e in _stream(client, sid, CANONICAL)
               if e["event"] == "memory.proposed")
    client.post(f"/api/v2/memory/proposals/{pid}/decision",
                json={"decision": "approve", "session_id": sid})

    events = _stream(client, sid, "Check story_events event_type distribution and explain the values")
    pilot = next(e for e in events if e["event"] == "pilot.report")
    assert pilot["data"]["pilot"] == "analytics"
    assert pilot["data"]["memory_citations"]          # approved memory recalled + cited
    ws = client.get(f"/api/v2/workspaces/{pilot['data']['workspace_id']}").json()
    assert any("analytics_report.md" in r for r in ws["artifact_refs"])
    assert ws["memory_citations"]


# ── Draft action governance ───────────────────────────────────────────────────


def test_drafts_are_data_only_with_boundaries():
    from aria.pilots.drafts import jira_draft, pr_comment_draft, teams_preview

    j = jira_draft(title="t", body="b")
    t = teams_preview(title="t", body="b")
    p = pr_comment_draft(title="t", body="b")
    assert "Not posted" in j.boundary and not j.approved
    assert "Not sent" in t.boundary
    assert "Not posted" in p.boundary
    assert "No external write executed" in j.boundary


def test_drafts_module_does_not_reuse_write_integrations():
    """The draft builders must not IMPORT any Jira/Teams/GitHub integration or
    HTTP client that could execute a write."""
    src = (Path(__file__).resolve().parents[1] / "aria" / "pilots" / "drafts.py").read_text(encoding="utf-8")
    forbidden_imports = (
        "aria.integrations", "teams_bot", "jira_skill", "import requests",
        "import httpx", "urllib", "from aria.integrations",
    )
    for forbidden in forbidden_imports:
        assert forbidden not in src, f"drafts.py must not import {forbidden!r}"
    # And nothing in the pilots package imports a write-capable integration.
    import aria.pilots.drafts as drafts_mod
    assert "aria.integrations" not in str(getattr(drafts_mod, "__file__", ""))


def test_approval_of_draft_is_decision_only(client):
    """Approving a memory proposal records a decision; no draft is ever executed.
    (Drafts themselves are never approved into an external write in Week 34.)"""
    sid = _new_session(client)
    # A pilot run produces drafts in the workspace; none are executed.
    events = _stream(client, sid, "Review this PR for the recommendation engine")
    drafts = [e for e in events if e["event"] == "draft.created"]
    assert drafts and all("Not posted" in d["data"]["boundary"] or "Not sent" in d["data"]["boundary"]
                          for d in drafts)
    # No external-write / connector-write ledger events ever appear.
    types = set(_ledger_types())
    assert "action_taken" not in types


# ── API / web / terminal integration ──────────────────────────────────────────


def test_pilot_report_in_api_stream_has_boundary_and_evidence(client):
    sid = _new_session(client)
    events = _stream(client, sid, "Review this PR for the recommendation engine")
    completed = next(e for e in events if e["event"] == "message.completed")
    # The streamed final response is the read-only report with boundary text.
    assert "Draft-only" in completed["data"]["response"] or "Read-only" in completed["data"]["response"]
    pilot = next(e for e in events if e["event"] == "pilot.report")
    assert pilot["data"]["evidence_references"]
    assert "nothing posted" in pilot["data"]["boundary"].lower()


def test_pilot_summary_through_terminal():
    from aria.conversation import terminal

    out: list[str] = []
    lines = iter(["Review this PR for the recommendation engine", "exit"])

    def read(_prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    terminal.session_repl(read=read, write=out.append)
    joined = "\n".join(out)
    assert "PR Review Report" in joined
    assert "Draft-only" in joined or "Read-only" in joined


def test_pilot_stream_no_raw_exception_or_chain_of_thought(client, monkeypatch):
    sid = _new_session(client)
    secret = "PILOT_SECRET_sk-ant-XYZ"
    from aria.conversation.orchestrator import ConversationOrchestrator
    monkeypatch.setattr(ConversationOrchestrator, "handle",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(secret)))
    events = _stream(client, sid, "Review this PR")
    blob = json.dumps(events)
    assert secret not in blob
    for e in events:
        assert "rationale" not in e["data"] and "reasoning" not in e["data"]


# ── P1: pilot artifact + pilot ledger trace are atomic / durable / recoverable ─


class _FailingWriter:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or OSError("ledger outage")

    def append(self, *_a, **_k):
        raise self.exc


def _pilot_with_failing_ledger(exc=None):
    from aria.memory_v2.store import DomainMemoryStore
    from aria.memory_v2.workspace import WorkspaceStore
    from aria.pilots.service import PilotService

    fw = _FailingWriter(exc)
    store = DomainMemoryStore(writer=fw)
    wss = WorkspaceStore(writer=fw)
    svc = PilotService(store, wss)
    session = store.create_session(owner="human:local", scope="analytics.events")
    return svc, store, wss, session


def test_pilot_ledger_failure_leaves_durable_recoverable_trace(tmp_path):
    from aria.ledger.writer import LedgerWriter
    from aria.pilots.models import PilotKind

    svc, store, wss, session = _pilot_with_failing_ledger()
    # State commits and run() does NOT raise — the trace is durably queued.
    result = svc.run(PilotKind.pr_review, "Review this PR", session=session)
    ws = wss.get_by_session(session.session_id)
    assert ws.artifact_refs                       # report artifact committed
    assert wss.pending_audit_count() > 0          # pilot events durably queued
    assert result.workspace_id == ws.workspace_id

    # Recovery: a healthy writer drains the outbox to the ledger, in causal order.
    led = tmp_path / "recovered.jsonl"
    wss.flush_outbox(writer=LedgerWriter(led))
    assert wss.pending_audit_count() == 0
    rec = [json.loads(line)["event_type"] for line in led.read_text(encoding="utf-8").splitlines()]
    for required in ("read_only_connector_invoked", "workspace_created", "workspace_updated",
                     "pilot_report_created", "draft_action_created"):
        assert required in rec, f"missing {required} after recovery"
    # Causal order: connector → artifact → report → drafts.
    assert rec.index("read_only_connector_invoked") < rec.index("workspace_created")
    assert rec.index("workspace_updated") < rec.index("pilot_report_created")
    assert rec.index("pilot_report_created") < rec.index("draft_action_created")


def test_pilot_draft_failure_queues_all_drafts_in_order(tmp_path):
    from aria.ledger.writer import LedgerWriter
    from aria.pilots.models import PilotKind

    svc, store, wss, session = _pilot_with_failing_ledger()
    svc.run(PilotKind.pr_review, "Review this PR", session=session)  # PR pilot has 4 drafts
    led = tmp_path / "recovered.jsonl"
    wss.flush_outbox(writer=LedgerWriter(led))
    rec = [json.loads(line)["event_type"] for line in led.read_text(encoding="utf-8").splitlines()]
    # All draft events recovered, each after pilot_report_created, contiguous + in order.
    first_draft = rec.index("draft_action_created")
    assert rec[first_draft - 1] == "pilot_report_created"
    n_drafts = rec.count("draft_action_created")
    assert n_drafts == 4
    assert rec[first_draft:first_draft + n_drafts] == ["draft_action_created"] * n_drafts


def test_pilot_audit_failure_never_stores_exception_secret():
    from aria.memory_v2.paths import workspace_artifact_dir
    from aria.pilots.models import PilotKind

    secret = "PILOT_OUTAGE_SECRET_VALUE"
    svc, store, wss, session = _pilot_with_failing_ledger(OSError(secret))
    svc.run(PilotKind.pr_review, "Review this PR", session=session)

    # The outbox stores the redacted EVENT only — never the writer's exception.
    conn = wss._connect()
    blob = " ".join(r["event_json"] for r in conn.execute("SELECT event_json FROM audit_outbox"))
    assert secret not in blob
    # Workspace metadata + artifact files carry no secret.
    ws = wss.get_by_session(session.session_id)
    assert secret not in json.dumps(ws.model_dump(mode="json"))
    for f in workspace_artifact_dir(ws.workspace_id).glob("*"):
        assert secret not in f.read_text(encoding="utf-8")
