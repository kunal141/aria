"""
Week 35 — full V2 internal-pilot demo + runtime-isolation + safety regression.

These tests prove the Week 35 acceptance claims WITHOUT new product scope:

  1. ``TestV2FullPilotDemo`` — the offline demo drives the real V2 app end to end
     (propose → approve → restart → recall-with-citation → 3 read-only pilots →
     workspace artifacts → draft-only → Work Ledger trace) in fixtures mode with
     no cloud key.
  2. ``TestRuntimeIsolation`` — the demo confines all runtime state to a temp dir,
     cleans it up, never writes into the source package, and ``.aria_data/`` is
     gitignored.
  3. ``TestSafetyBoundaries`` — credentials alone never activate live connectors;
     ``read_only_live`` fails closed; approval is a decision record only; sensitive
     memory is refused; error responses are redacted; there is no cloud fallback.

All offline + deterministic: no network, no provider key, no live connector.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from aria.demo import v2_full_pilot as demo

_REPO_BACKEND = Path(__file__).resolve().parents[1]  # apps/backend
_PROVIDER_KEYS = demo._PROVIDER_KEY_VARS


# ── 1. Full demo end-to-end ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def demo_result() -> dict:
    """Run the demo once (self-isolating + self-cleaning) and share the summary."""
    return demo.run_demo(write=lambda *_a, **_k: None)


class TestV2FullPilotDemo:
    def test_demo_succeeds_in_fixtures_mode(self, demo_result):
        assert demo_result["ok"] is True
        # Every pilot ran in fixtures mode — no live connector was used.
        assert demo_result["analytics"]["connector_mode"] == "fixtures"

    def test_memory_proposed_approved_and_persisted(self, demo_result):
        assert demo_result["memory_id"].startswith("mem-")
        # One approved memory is active after the whole run.
        assert demo_result["active_memory_count"] == 1

    def test_recall_after_restart_is_cited(self, demo_result):
        # Recall happens on a SECOND app instance (restart) over the same SQLite.
        assert demo_result["recall_cited"] is True

    def test_three_pilots_produce_reports_and_drafts(self, demo_result):
        assert demo_result["analytics"]["pilot"] == "analytics"
        assert demo_result["ci_cd"]["pilot"] == "ci_cd"
        assert demo_result["pr_review"]["pilot"] == "pr_review"
        # Pilots emit draft-only actions (never posted/sent/created).
        assert demo_result["ci_cd"]["drafts"] >= 1
        assert demo_result["pr_review"]["drafts"] >= 1

    def test_analytics_memory_explains_but_evidence_proves_counts(self, demo_result):
        # Memory explains the event_type VALUES; fixture evidence backs the COUNTS.
        # Memory never bypasses the evidence gate.
        an = demo_result["analytics"]
        assert an["memory_citations"] >= 1
        assert len(an["evidence"]) >= 1
        assert all(e.startswith("fixture:") for e in an["evidence"])

    def test_workspace_holds_artifacts_citations_and_draft_refs(self, demo_result):
        ws = demo_result["workspace"]
        assert len(ws["artifacts"]) == 3            # analytics + ci_cd + pr_review reports
        assert ws["citations"] >= 1
        assert ws["drafts"] == 7                    # 2 + 1 + 4 draft refs

    def test_work_ledger_trace_has_full_causal_chain(self, demo_result):
        types = set(demo_result["ledger_event_types"])
        # conversation → memory → approval → recall → pilots → workspace/drafts
        for expected in (
            "conversation_started", "memory_proposed", "approval_requested",
            "approved", "memory_applied", "memory_recalled",
            "read_only_connector_invoked", "pilot_report_created",
            "draft_action_created", "workspace_created", "workspace_updated",
        ):
            assert expected in types, f"missing ledger event: {expected}"

    def test_no_external_write_event_types(self, demo_result):
        # There is no such thing as a "sent/posted/created-externally" ledger event;
        # the connector is only ever invoked read-only.
        types = set(demo_result["ledger_event_types"])
        assert "read_only_connector_invoked" in types
        forbidden = {"jira_created", "teams_sent", "pr_comment_posted",
                     "external_write", "deployment", "model_trained"}
        assert forbidden.isdisjoint(types)

    def test_boundary_statement_is_explicit(self, demo_result):
        b = set(demo_result["boundaries"])
        assert "no external writes" in b
        assert "no Jira ticket created" in b
        assert "no Teams message sent" in b
        assert "no PR comment posted" in b


# ── 2. Runtime isolation + cleanup ────────────────────────────────────────────


class TestRuntimeIsolation:
    def test_demo_state_lives_under_a_temp_dir(self, demo_result):
        data_dir = Path(demo_result["data_dir"]).resolve()
        temp_root = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp").resolve()
        # The demo's data dir is under the OS temp root, never under the repo.
        assert str(data_dir).startswith(str(temp_root)) or "aria_v2_demo_" in str(data_dir)
        assert _REPO_BACKEND not in data_dir.parents

    def test_demo_cleans_up_its_temp_state(self, demo_result):
        assert demo_result["temp_cleaned"] is True
        assert not Path(demo_result["data_dir"]).exists()
        assert not Path(demo_result["ledger_path"]).exists()

    def test_demo_does_not_write_into_the_source_package(self):
        """A fresh run must not create/modify the runtime ledger checked-in path
        or an ``.aria_data`` tree inside the source package."""
        runtime_ledger = _REPO_BACKEND / "work_ledger_v2.jsonl"
        source_data = _REPO_BACKEND / ".aria_data"

        before_ledger = _digest(runtime_ledger)
        before_data_exists = source_data.exists()

        demo.run_demo(write=lambda *_a, **_k: None)

        assert _digest(runtime_ledger) == before_ledger, "demo modified the runtime ledger"
        assert source_data.exists() == before_data_exists, "demo created a source-package .aria_data"

    def test_keep_flag_retains_state_then_clean_for_next_run(self):
        """``--keep`` retains the temp dir (so it can be inspected); we then remove
        it ourselves so the test leaves nothing behind."""
        import shutil

        result = demo.run_demo(write=lambda *_a, **_k: None, keep=True)
        kept = Path(result["data_dir"])
        try:
            assert result["temp_cleaned"] is False
            assert kept.exists()
        finally:
            shutil.rmtree(kept.parent, ignore_errors=True)
        assert not kept.exists()

    def test_aria_data_dir_is_gitignored(self):
        gitignore = (_REPO_BACKEND.parent.parent / ".gitignore").read_text(encoding="utf-8")
        assert ".aria_data" in gitignore


# ── 3. Safety boundaries ──────────────────────────────────────────────────────


class TestSafetyBoundaries:
    def test_credentials_alone_do_not_activate_live_connector(self, monkeypatch):
        from aria.connectors import FixtureConnector, get_connector, resolve_connector_mode

        # Provider creds present, but CONNECTOR_MODE is NOT read_only_live.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-real")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-not-real")
        monkeypatch.delenv("CONNECTOR_MODE", raising=False)

        assert resolve_connector_mode().value == "fixtures"
        assert isinstance(get_connector(), FixtureConnector)

    def test_read_only_live_fails_closed_without_allowlist(self, monkeypatch):
        from aria.connectors import ConnectorModeError, get_connector

        monkeypatch.setenv("CONNECTOR_MODE", "read_only_live")
        monkeypatch.delenv("CONNECTOR_PROVIDER_ALLOWLIST", raising=False)

        with pytest.raises(ConnectorModeError):
            get_connector("github").read_pr()

    def test_read_only_live_even_when_allowed_does_no_network(self, monkeypatch):
        from aria.connectors import get_connector

        monkeypatch.setenv("CONNECTOR_MODE", "read_only_live")
        monkeypatch.setenv("CONNECTOR_PROVIDER_ALLOWLIST", "github")
        # Explicitly allowed — yet Week 34/35 performs NO real network read.
        with pytest.raises(NotImplementedError):
            get_connector("github").read_pr()

    def test_no_cloud_fallback_from_credentials(self, monkeypatch):
        from aria.llm import ExecutionMode, resolve_execution_mode

        # A cloud key in the env must NOT silently escalate the execution mode.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-real")
        monkeypatch.delenv("ARIA_EXECUTION_MODE", raising=False)
        assert resolve_execution_mode() is ExecutionMode.offline_mock

    def test_sensitive_memory_is_refused_and_not_persisted(self):
        from fastapi.testclient import TestClient

        from aria.api.v2 import build_v2_app

        client = TestClient(build_v2_app())
        sid = client.post("/api/v2/chat/sessions", json={"scope": "analytics.events"}).json()["session_id"]
        # Memory-SHAPED (a field/value mapping, so it reaches the propose path) but
        # the table/field names carry sensitivity markers ("api_key", "token") — the
        # store must refuse it (no authenticated identity layer in V2).
        events = demo._stream(
            client, sid,
            "In api_key_store table, token = 1 means active, token = 2 means revoked.",
        )
        completed = demo._first(events, "message.completed")
        assert completed["data"]["refused"] is True
        assert demo._first(events, "memory.proposed") is None
        # Nothing sensitive reached the store.
        assert client.get("/api/v2/memory").json()["count"] == 0

    def test_approval_is_a_decision_record_not_an_external_action(self):
        from fastapi.testclient import TestClient

        from aria.api.v2 import build_v2_app

        client = TestClient(build_v2_app())
        sid = client.post("/api/v2/chat/sessions", json={"scope": "analytics.events"}).json()["session_id"]
        ev = demo._stream(client, sid, demo.CANONICAL)
        pid = demo._first(ev, "memory.proposed")["data"]["proposal_id"]

        record = client.post(f"/api/v2/memory/proposals/{pid}/decision",
                             json={"decision": "approve", "session_id": sid}).json()
        # The decision targets internal domain memory only — never an external system.
        assert record["action_type"] == "memory"
        assert record["target_system"] == "domain_memory"
        assert record["risk_level"] == "low"

    def test_demo_pins_offline_mode_even_with_ambient_cloud_opt_in(self, monkeypatch):
        """Proof-boundary: an ambient ``ARIA_EXECUTION_MODE=cloud_opt_in`` must NOT
        leak a 'cloud' label into the isolated ledger — the demo pins offline_mock —
        and the ambient value must be restored after the run."""
        import json
        import shutil

        monkeypatch.setenv("ARIA_EXECUTION_MODE", "cloud_opt_in")
        result = demo.run_demo(write=lambda *_a, **_k: None, keep=True)
        ledger_path = Path(result["ledger_path"])
        try:
            assert result["execution_mode"] == "offline_mock"
            lines = [ln for ln in ledger_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            assert lines, "demo produced no ledger events"
            for line in lines:
                event = json.loads(line)
                mode = (event.get("metadata") or {}).get("execution_mode")
                # Either no execution_mode on the event, or exactly offline_mock —
                # never the ambient cloud_opt_in.
                assert mode in (None, "offline_mock"), f"leaked execution_mode: {mode!r}"
        finally:
            shutil.rmtree(ledger_path.parent, ignore_errors=True)
        # Ambient env restored after the run (isolation did not stick).
        assert os.environ["ARIA_EXECUTION_MODE"] == "cloud_opt_in"

    def test_error_responses_are_redacted(self):
        from fastapi.testclient import TestClient

        from aria.api.v2 import build_v2_app

        client = TestClient(build_v2_app())
        # Unknown ids return a stable typed code + sanitised detail — never raw text.
        r1 = client.post("/api/v2/memory/proposals/does-not-exist/decision",
                         json={"decision": "approve"})
        assert r1.status_code == 404
        assert r1.json() == {"error_code": "proposal_not_found", "detail": "Unknown proposal."}

        r2 = client.get("/api/v2/workspaces/nope")
        assert r2.status_code == 404
        assert r2.json()["error_code"] == "workspace_not_found"


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()
