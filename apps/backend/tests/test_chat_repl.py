"""
Tests for the local interactive chat REPL (``aria.chat``).

Two layers:
  1. Behavioural tests inject ``read``/``write``/``ask_fn`` so the loop is
     exercised without real stdin/stdout or invoking the graph.
  2. Boundary tests run the real graph through ``chat.ask`` to prove the
     advertised safety boundaries actually hold from the chat surface:
       - KPI / CI-CD evidence withholding still fires
       - explicit Jira "create" stays an approval-required draft (no execution)
       - evolution state-changing actions (scan / evaluate / promote / rollback)
         are blocked / dry-run and never reach the persisting pipeline
       - credentials present still do NOT trigger paid calls by default
       - ambient LangSmith credentials do NOT trigger tracing network calls
       - exception secrets are never displayed — including internally-caught
         errors that never escape the graph, and router LLM-fallback errors
         whose text is persisted via routing_reason
       - runtime logs are test-isolated (no real-file pollution)

An autouse fixture forces offline mode and redirects every runtime sink into
``tmp_path`` so the suite passes even on a machine with real provider keys and
never touches the repo's runtime files or the network.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from aria import chat

# apps/backend — the runtime files that MUST stay untouched by these tests.
_BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _chat_offline_isolation(tmp_path, monkeypatch):
    """Force offline mode, block the network, and redirect every runtime sink.

    - Null the router's LLM chain and clear provider creds → keyword routing
      regardless of ambient credentials (no paid call possible).
    - Block outbound socket connections → no test can reach the network.
    - Repoint audit / legacy-ledger / notifier / memory sinks into tmp_path.
      (The v2 ledger + deployment root are already isolated by conftest.py.)
    """
    # 1) Offline brain — even if real keys exist in the dev environment.
    import aria.nodes.router as router
    monkeypatch.setattr(router, "_llm_chain", None)
    for var in (
        "LLM_PROVIDER", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY",
        "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "KIMI_API_KEY", "QWEN_API_KEY",
        "FAST_LLM_PROVIDER", "SMART_LLM_PROVIDER", "FRONTIER_LLM_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)

    # 2) No network — any outbound connection attempt fails loudly.
    import socket

    def _no_network(*_a, **_k):
        raise RuntimeError("network access is disabled in chat tests")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)

    # 3) Redirect runtime sinks into tmp_path (so real repo files stay clean).
    import aria.security.audit_log as audit_log
    import aria.work_ledger as work_ledger
    import aria.notifications.notifier as notifier
    import aria.memory.store as mem_store

    monkeypatch.setattr(audit_log, "_AUDIT_FILE", str(tmp_path / "tool_audit.jsonl"))
    monkeypatch.setattr(work_ledger, "LEDGER_FILE", tmp_path / "work_ledger.jsonl")
    monkeypatch.setattr(
        work_ledger, "EVOLUTION_EVENTS_FILE", tmp_path / "evolution_events.jsonl"
    )
    monkeypatch.setattr(notifier, "_LOG_PATH", tmp_path / "notifications.jsonl")
    monkeypatch.setattr(mem_store, "_STORE_FILE", tmp_path / "memory_store.json")
    yield


# ── Test helpers ────────────────────────────────────────────────────────────

def _reader(lines):
    """Return a read(prompt) callable that yields the given lines, then EOF."""
    it = iter(lines)

    def read(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError  # simulate Ctrl-D when input is exhausted

    return read


def _writer():
    """Return (write_callable, captured_lines_list)."""
    captured = []
    return (lambda *args: captured.append(args[0] if args else "")), captured


# ── Behavioural tests (loop mechanics, no graph) ────────────────────────────

def test_repl_exits_on_exit_word():
    ask_fn = Mock()
    write, out = _writer()
    chat.repl(read=_reader(["exit"]), write=write, ask_fn=ask_fn)

    ask_fn.assert_not_called()
    assert any("goodbye" in line for line in out)


def test_repl_exits_on_quit_word():
    ask_fn = Mock()
    write, out = _writer()
    chat.repl(read=_reader(["quit"]), write=write, ask_fn=ask_fn)

    ask_fn.assert_not_called()


def test_repl_ignores_empty_input():
    ask_fn = Mock(return_value={"response": "x", "skill_name": "general"})
    write, _ = _writer()
    # blank line, whitespace-only line, then exit — ask_fn must never fire
    chat.repl(read=_reader(["", "   ", "exit"]), write=write, ask_fn=ask_fn)

    ask_fn.assert_not_called()


def test_repl_passes_user_text_to_ask():
    ask_fn = Mock(return_value={"response": "done", "skill_name": "pr_review"})
    write, out = _writer()
    chat.repl(read=_reader(["Review my PR for recommendation engine", "exit"]),
              write=write, ask_fn=ask_fn)

    ask_fn.assert_called_once_with("Review my PR for recommendation engine")
    assert any("done" in line for line in out)
    assert any("pr_review" in line for line in out)


def test_repl_handles_errors_without_crashing():
    ask_fn = Mock(side_effect=RuntimeError("boom"))
    write, out = _writer()
    # Must NOT raise; the loop reports the failure (redacted) and reaches exit.
    chat.repl(read=_reader(["trigger failure", "exit"]), write=write, ask_fn=ask_fn)

    joined = "\n".join(out)
    assert "failed" in joined
    assert "boom" not in joined            # raw exception text is NOT shown
    assert "details redacted" in joined


def test_repl_exits_on_eof():
    ask_fn = Mock()
    write, _ = _writer()
    # No 'exit' line — reader raises EOFError immediately; loop must end cleanly.
    chat.repl(read=_reader([]), write=write, ask_fn=ask_fn)

    ask_fn.assert_not_called()


# ── Integration: wrapper reuses the real graph, offline ─────────────────────

def test_ask_runs_real_graph_offline():
    """The wrapper reuses the real graph and routes, offline."""
    result = chat.ask("Review my PR for the recommendation engine")

    assert result["task_type"] == "pr_review"
    assert result["response"]            # non-empty response produced
    assert "router" in result["steps_completed"]


def test_ask_attaches_safe_surface_policy():
    """Every chat request carries the read-only / dry-run surface policy."""
    result = chat.ask("Review my PR for the recommendation engine")

    assert result["surface"] == "local_chat"
    assert result["execution_mode"] == "dry_run"
    assert result["allow_mutations"] is False
    assert result["allow_llm"] is False


# ── Boundary tests (advertised safety actually holds from chat) ─────────────

def test_kpi_evidence_withheld_through_chat(monkeypatch):
    """(1) The evidence gate still withholds an unsupported KPI claim from chat.

    Drive the evidence layer to its realistic 'claims unsupported' condition
    (``is_safe_to_surface=False``) and prove the chat surface fails closed —
    it must route through ``respond()``'s gate, not bypass it and leak the
    skill output. If ``chat.ask`` ever short-circuited the gate, this fails.
    """
    import aria.nodes.skill_nodes as skill_nodes

    def _unsupported(_state):
        return json.dumps({
            "is_safe_to_surface": False,
            "blocked_reason": "Claims could not be supported by catalog evidence.",
        })

    monkeypatch.setattr(skill_nodes, "_assemble_kpi_evidence", _unsupported)

    result = chat.ask("Investigate the CTR anomaly on the personalization feed")

    assert result["task_type"] == "kpi"
    response = (result["response"] or "").upper()
    assert "WITHHELD" in response
    assert "UNSUPPORTED CLAIMS" in response


def test_cicd_evidence_withheld_through_chat(monkeypatch):
    """(1) The evidence gate still withholds a CI/CD answer from chat.

    Drive the evidence layer to its 'assembly could not complete' condition
    (absent evidence) and prove the chat surface fails closed with the
    evidence-unavailable notice rather than surfacing an unverified answer.
    """
    import aria.nodes.skill_nodes as skill_nodes

    monkeypatch.setattr(skill_nodes, "_assemble_cicd_evidence", lambda _state: None)

    result = chat.ask(
        "The build pipeline for recommendation-service failed on the test stage"
    )

    assert result["task_type"] == "ci_cd"
    response = (result["response"] or "").upper()
    assert "WITHHELD" in response
    assert "EVIDENCE UNAVAILABLE" in response


def test_jira_create_requires_approval_and_does_not_execute():
    """(2) Explicit Jira create is an approval-required draft, not executed."""
    # "create a ticket" is the explicit-create phrase the skill recognises (T4).
    result = chat.ask("Create a ticket for the missing session_id bug")

    assert result["task_type"] == "jira"
    data = json.loads(result["skill_output"])
    assert data["approval_required"] is True       # gated on human approval
    assert "created_ticket_id" not in data         # nothing was actually created
    # routed to the approval-pending path, not executed
    assert result.get("approval_request_id")


def test_evolution_promote_blocked_through_chat(monkeypatch):
    """(3) 'promote canary' is blocked/dry-run — the manager is never reached."""
    import aria.nodes.evolution_node as ev

    def _must_not_run():
        raise AssertionError("UpdateManager must not be reached for a blocked mutation")

    monkeypatch.setattr(ev, "_get_update_manager", _must_not_run)

    result = chat.ask("promote canary upd-abc123-v1.0.0")

    assert result["task_type"] == "evolution"
    data = json.loads(result["skill_output"])
    assert data["action"] == "promote_canary"
    assert data.get("blocked") is True
    assert data.get("dry_run") is True
    assert "blocked" in data["message"].lower()


def test_evolution_rollback_blocked_through_chat(monkeypatch):
    """(3) 'rollback component' is blocked/dry-run — nothing is restored."""
    import aria.nodes.evolution_node as ev

    def _must_not_run():
        raise AssertionError("UpdateManager must not be reached for a blocked mutation")

    monkeypatch.setattr(ev, "_get_update_manager", _must_not_run)

    result = chat.ask("rollback component pr_review_prompt to 1.0.0")

    assert result["task_type"] == "evolution"
    data = json.loads(result["skill_output"])
    assert data["action"] == "rollback"
    assert data.get("blocked") is True
    assert data.get("dry_run") is True


def test_evolution_scan_blocked_through_chat(monkeypatch):
    """(P1) 'scan' is blocked/dry-run from chat — the persisting pipeline never runs.

    ``_handle_scan`` reaches ``ProposalPipeline.run()`` which persists an
    UpdateRelease. Monkeypatch it to explode if reached; a correctly blocked
    mutation must never call it, so nothing is persisted.
    """
    import aria.nodes.evolution_node as ev

    def _must_not_run(*_a, **_k):
        raise AssertionError("scan pipeline must not run for a blocked mutation")

    monkeypatch.setattr(ev, "_handle_scan", _must_not_run)

    result = chat.ask("scan for capability gaps")

    assert result["task_type"] == "evolution"
    data = json.loads(result["skill_output"])
    assert data["action"] == "scan"
    assert data.get("blocked") is True
    assert data.get("dry_run") is True


def test_evolution_evaluate_blocked_through_chat(monkeypatch):
    """(P1) 'evaluate proposal' is blocked/dry-run from chat — no release persisted.

    ``_handle_evaluate_proposal`` also reaches ``ProposalPipeline.run()``; same
    proof — it must never be called when the surface is read-only/dry-run.
    """
    import aria.nodes.evolution_node as ev

    def _must_not_run(*_a, **_k):
        raise AssertionError("evaluate pipeline must not run for a blocked mutation")

    monkeypatch.setattr(ev, "_handle_evaluate_proposal", _must_not_run)

    result = chat.ask("evaluate proposal prop-abc12345")

    assert result["task_type"] == "evolution"
    data = json.loads(result["skill_output"])
    assert data["action"] == "evaluate_proposal"
    assert data.get("blocked") is True
    assert data.get("dry_run") is True


def test_offline_scope_disables_langsmith_tracing(monkeypatch):
    """(P1) Ambient LangSmith creds do NOT cause tracing network calls offline.

    Mirrors the audit probe: a ``@traceable`` function executed inside
    ``offline_scope()`` must not attempt any connection to the LangSmith
    ingestion host. Asserts both the structural state (tracing disabled
    in-scope) and that no smith socket connection is attempted.
    """
    import socket
    from aria.config import offline_scope
    from langsmith import traceable
    from langsmith.run_helpers import get_tracing_context

    # Ambient LangSmith credentials + tracing enabled (as on a dev box).
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-FAKEKEYFAKEKEYFAKEKEY")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "ls-FAKEKEYFAKEKEYFAKEKEY")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    # Record every outbound connection attempt (then block it).
    attempts = []

    def _record_and_block(address, *_a, **_k):
        attempts.append(address)
        raise RuntimeError("network blocked in test")

    monkeypatch.setattr(
        socket.socket, "connect",
        lambda self, address, *a, **k: _record_and_block(address),
    )
    monkeypatch.setattr(socket, "create_connection", _record_and_block)

    @traceable
    def _traced(x):
        return x + 1

    with offline_scope():
        assert get_tracing_context().get("enabled") is False  # structurally off
        assert _traced(1) == 2

    smith = [a for a in attempts
             if "smith" in str(a).lower() or "langchain.com" in str(a).lower()]
    assert smith == [], f"offline scope must not call LangSmith: {smith}"


def test_internal_evolution_error_secret_is_redacted_through_chat(monkeypatch):
    """(P1) A secret in an internally-caught evolution error never leaks.

    The evolution node catches the exception internally (it does NOT escape the
    graph), so the REPL's escaping-exception handler never sees it. The node
    itself must redact — the secret must not appear in skill_output, response,
    or error.
    """
    import aria.nodes.evolution_node as ev

    secret = "password=TOP_SECRET_TOKEN"

    def _boom():
        raise RuntimeError(secret)

    # A non-mutating action that reaches the manager, forced to raise internally.
    monkeypatch.setattr(ev, "_get_update_manager", _boom)

    result = chat.ask("show pending proposals")

    assert result["task_type"] == "evolution"
    assert "TOP_SECRET_TOKEN" not in json.dumps(result)   # nothing the caller sees
    data = json.loads(result["skill_output"])
    assert data["error"] == "internal_error"
    assert data["error_type"] == "RuntimeError"           # safe class name only
    assert "TOP_SECRET_TOKEN" not in (result["response"] or "")
    assert "TOP_SECRET_TOKEN" not in (result.get("error") or "")


def test_router_llm_fallback_secret_is_redacted_through_chat(monkeypatch, tmp_path):
    """(P1) A secret in a router LLM-chain failure never leaks via routing_reason.

    With ``--llm`` opted in, the router runs LLM mode. If the chain raises an
    exception whose text carries a secret, the fallback must surface only the
    exception *class* — never the raw message — because ``routing_reason`` is
    returned to the caller AND persisted to the Work Ledger by ``respond()``.
    """
    import aria.nodes.router as router

    secret = "password=ROUTER_SECRET"

    class _FailingChain:
        def invoke(self, *_a, **_k):
            raise RuntimeError(secret)

    # Wire a chain that fails mid-classify; allow_llm=True forces LLM mode.
    # (Skills stay offline: provider keys are cleared, so has_llm()→False.)
    monkeypatch.setattr(router, "_llm_chain", _FailingChain())

    result = chat.ask("Review my PR for the recommendation engine", allow_llm=True)

    # Router fell back to keywords; the reason carries the redacted marker only.
    reason = result.get("routing_reason") or ""
    assert "details redacted" in reason
    assert "RuntimeError" in reason
    assert "ROUTER_SECRET" not in reason

    # The secret is absent from the entire result the caller receives ...
    assert "ROUTER_SECRET" not in json.dumps(result)

    # ... and from every isolated ledger / runtime file written for this task
    # (both the legacy ledger and the v2 ledger live under this test's tmp_path).
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert "ROUTER_SECRET" not in path.read_text(encoding="utf-8"), \
                f"secret leaked into {path.name}"


def test_credentials_present_do_not_trigger_paid_calls(monkeypatch):
    """(4) Even with creds AND a wired chain, default chat stays offline."""
    import aria.nodes.router as router

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-FAKEKEYFAKEKEYFAKEKEY")

    class _Spy:
        def invoke(self, *_a, **_k):
            raise AssertionError("LLM chain must not be invoked from local chat by default")

    monkeypatch.setattr(router, "_llm_chain", _Spy())

    result = chat.ask("Review my PR for the recommendation engine")  # allow_llm=False

    assert result["task_type"] == "pr_review"
    assert "[Keywords]" in (result["routing_reason"] or "")   # keyword path was used


def test_exception_secret_is_not_displayed():
    """(5) A secret inside an exception is never shown to the user."""
    secret = "password=TOP_SECRET_TOKEN"
    ask_fn = Mock(side_effect=RuntimeError(secret))
    write, out = _writer()

    chat.repl(read=_reader(["do something", "exit"]), write=write, ask_fn=ask_fn)

    joined = "\n".join(out)
    assert "TOP_SECRET_TOKEN" not in joined
    assert "RuntimeError" in joined          # safe error category is shown
    assert "details redacted" in joined


def test_runtime_logs_are_test_isolated():
    """(6) Running real graph requests through chat leaves repo runtime files untouched."""
    runtime_files = [
        _BACKEND / "tool_audit.jsonl",
        _BACKEND / "work_ledger.jsonl",
        _BACKEND / "work_ledger_v2.jsonl",
        _BACKEND / "evolution_events.jsonl",
        _BACKEND / "notifications.jsonl",
        _BACKEND / "memory_store.json",
    ]
    before = {f: (f.stat().st_size if f.exists() else None) for f in runtime_files}

    # Exercise several skill paths that would otherwise write to these sinks.
    chat.ask("Review my PR for the recommendation engine")
    chat.ask("Our CTR dropped 18% this week, investigate the anomaly")
    chat.ask("The deploy pipeline is failing on the build step")

    after = {f: (f.stat().st_size if f.exists() else None) for f in runtime_files}
    assert before == after, "chat tests must not modify real runtime log files"
