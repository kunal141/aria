"""
Week 32 terminal: multi-turn, session-aware, memory-aware REPL.

Run (command unchanged from V1.1):

    cd apps/backend
    uv run python -m aria.chat

Week 32 behavior (terminal only — no FastAPI/web here):
  - maintains a ``session_id`` and persists every turn (SQLite)
  - uses short-term session context
  - uses Week 31 execution modes (``offline_mock`` works with NO Ollama;
    ``local_ollama`` goes only through the Week 31 provider path; no cloud
    fallback)
  - shows structured memory proposals and allows inline ``approve <id>`` /
    ``reject <id>``
  - shows memory citations on recall
  - preserves the safe local-chat surface policy for workflows (run_workflow goes
    through ``aria.chat.ask`` → ``execution_mode=dry_run``, mutations blocked)

``ARIA_USER_ID`` is a label only — it is NOT authentication and never unlocks
sensitive memory.
"""
from __future__ import annotations

import os

from aria.conversation.orchestrator import ConversationOrchestrator
from aria.llm import ExecutionMode, configured_local_model, resolve_execution_mode
from aria.memory_v2.store import DomainMemoryStore

EXIT_WORDS = frozenset({"exit", "quit"})


def _owner() -> str:
    # Label only — never treated as authorization (Week 32 §5).
    value = os.getenv("ARIA_USER_ID")
    return value if value and value.strip() else "human:local"


def _active_brain(mode: ExecutionMode) -> str:
    if mode is ExecutionMode.local_ollama:
        return f"Active brain: ollama / {configured_local_model()} (local, Week 31 provider path)"
    if mode is ExecutionMode.cloud_opt_in:
        return "Active brain: cloud (explicit cloud_opt_in)"
    return "Active brain: offline (deterministic orchestrator + keyword router; no Ollama, no cloud)"


def session_repl(read=input, write=print, *, mode=None, scope: str = "analytics.events") -> None:
    """Interactive Week 32 session loop. ``read``/``write`` are injectable for tests."""
    resolved = resolve_execution_mode(mode)
    owner = _owner()

    store = DomainMemoryStore(execution_mode=resolved.value)
    orch = ConversationOrchestrator(store, execution_mode=resolved.value)
    session = orch.start_session(owner=owner, scope=scope)

    write("ARIA Conversation (Week 32) — multi-turn, memory-aware")
    write(_active_brain(resolved))
    write(f"Session: {session.session_id}")
    write(
        "Tell me a domain fact to remember (I'll propose it for your approval), ask what a term "
        "means, or ask for a PR / CI-CD / KPI workflow. Commands: `approve <id>`, `reject <id>`, "
        "`exit`."
    )
    write("Note: workflows run read-only/dry-run; no live writes. Sensitive memory is refused.")
    write("")

    while True:
        try:
            line = read("you > ")
        except EOFError:
            write("")
            break
        if line is None:
            break
        text = line.strip()
        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            write("ARIA: goodbye.")
            break

        try:
            handled = _handle_command(orch, session, text)
            if handled is not None:
                write(f"\nARIA:\n{handled}\n")
                continue
            result = orch.handle(text, session=session)
            write(f"\nARIA [{result.decision.action.value}]:\n{result.response}\n")
        except Exception as exc:  # never leak raw exception text (may carry secrets)
            write(
                f"\nARIA: sorry — that request failed "
                f"(error: {type(exc).__name__}; details redacted). Try rephrasing.\n"
            )


def _handle_command(orch: ConversationOrchestrator, session, text: str):
    """Handle inline approve/reject commands; return rendered text, or None if not a command."""
    parts = text.split()
    if len(parts) == 2 and parts[0].lower() in ("approve", "reject"):
        proposal_id = parts[1]
        if parts[0].lower() == "approve":
            version = orch.approve_memory(proposal_id, approver=session.owner, session=session)
            return (
                f"Approved. Active memory {version.memory_id} v{version.version} "
                f"in scope {version.scope}."
            )
        proposal = orch.reject_memory(proposal_id, actor=session.owner, session=session)
        return f"Rejected proposal {proposal.proposal_id}. It will never be retrieved."
    return None


def main(argv=None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else list(argv)
    mode = None
    if "--mode" in argv:
        i = argv.index("--mode")
        if i + 1 < len(argv):
            mode = argv[i + 1]

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console: unicode-safe
    except (AttributeError, ValueError):
        pass
    session_repl(mode=mode)
    return 0
