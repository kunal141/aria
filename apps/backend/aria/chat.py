"""
aria.chat — local interactive natural-language REPL for ARIA.

A small V1.1 usability wrapper. Lets you talk to ARIA in plain English from a
terminal instead of editing ``main.py``'s hard-coded test inputs.

    cd apps/backend
    uv run python -m aria.chat            # offline keyword brain (default)
    uv run python -m aria.chat --llm      # opt in to the live LLM brain (paid)

Offline-by-default
------------------
Local chat is offline-by-default. Even if ``LLM_PROVIDER`` + an API key are
configured in ``apps/backend/.env``, the live LLM brain is OFF unless you pass
``--llm``. Offline mode uses the keyword router with deterministic mock skill
outputs — no paid API call, no network. ``--llm`` is the only thing that makes
paid calls.

Safe chat surface policy (governed local workflow, NOT production execution)
----------------------------------------------------------------------------
Every request from this surface carries a restrictive execution policy:
``surface="local_chat"``, ``execution_mode="dry_run"``, ``allow_mutations=False``,
``allow_llm=False``. Downstream nodes honour it, so:
  - State-changing evolution actions (scan / evaluate proposal / promote canary /
    rollback component) are BLOCKED from chat — they return a dry-run /
    approval-required answer, never persisting, activating, or restoring real
    runtime components.
  - There are no live Jira / Teams / GitHub writes — those connectors are V2 and
    require approval. Explicit "create a ticket" requests produce an
    approval-required draft, not an executed ticket.
  - Offline mode disables LangSmith tracing too, so an offline request makes no
    outbound network calls even with ambient LangSmith credentials.
  - Error text is redacted on the paths that surface or persist it — escaping
    exceptions (REPL shows the class), the evolution node's ``internal_error``
    envelope, and the router LLM-fallback (class only in ``routing_reason``); not
    a blanket guarantee for every conceivable skill path.
  - Governance gates (evidence gate, action tiers, approvals) run exactly as in
    the normal graph path.

This module reuses ``aria.graph.aria_graph`` directly. All routing and skill
selection lives inside the graph and is reused here, not duplicated — ``ask()``
only builds the same initial-state envelope that ``main.run()`` builds, plus the
surface policy fields above.
"""
import os
import sys

from aria.config import has_llm, offline_scope
from aria.graph import aria_graph

BANNER = (
    "ARIA Local Chat\n"
    "Mode: offline/local unless --llm is given AND a provider key is configured\n"
    "Type 'exit' or 'quit' to stop"
)

SAFETY = (
    "Note: local chat is a governed local workflow surface — not production "
    "execution.\nNo live Jira/Teams/GitHub writes occur, and state-changing "
    "evolution actions are blocked (dry-run) from chat."
)

EXIT_WORDS = frozenset({"exit", "quit"})


def ask(raw_input_text: str, *, allow_llm: bool = False) -> dict:
    """Run one natural-language request through the existing ARIA graph.

    Builds the same initial-state envelope as ``main.run()`` and invokes the
    shared compiled graph; routing and skill execution are entirely the graph's.
    A restrictive surface policy is attached so this surface stays read-only /
    dry-run and offline-by-default.
    """
    envelope = {
        "task_id": "",
        "raw_input": raw_input_text,
        "task_type": None,
        "task_status": "pending",
        "routing_reason": None,
        "steps_completed": [],
        "skill_name": None,
        "skill_output": None,
        "response": None,
        "messages": [],
        "error": None,
        # ── Safe chat surface policy ──────────────────────────────────────────
        "surface": "local_chat",
        "execution_mode": "dry_run",   # no live tool execution from chat
        "allow_mutations": False,      # state-changing evolution actions blocked
        "allow_llm": allow_llm,        # offline-by-default; --llm opts in
    }
    if allow_llm:
        return aria_graph.invoke(envelope)
    # Offline-by-default: force has_llm()→False for the whole request so NO
    # component (router or skill) makes a live/paid call, even if provider
    # credentials are present in the environment. --llm is the only opt-in.
    with offline_scope():
        return aria_graph.invoke(envelope)


def _active_mode(allow_llm: bool) -> str:
    """One-line description of which brain is live, for the startup banner."""
    if allow_llm and has_llm():
        provider = os.getenv("LLM_PROVIDER", "anthropic").title()
        return f"Active brain: {provider} (LLM mode — live API calls, opted in via --llm)"
    if allow_llm and not has_llm():
        return "Active brain: keyword router (offline — --llm given but no provider key configured)"
    return "Active brain: keyword router (offline, no API calls)"


def _format(result: dict) -> str:
    """Format a graph result into a single printable block."""
    skill = result.get("skill_name") or result.get("task_type") or "-"
    response = result.get("response") or "(no response)"
    return f"[{skill}]\n{response}"


def repl(read=input, write=print, ask_fn=None, allow_llm=False) -> None:
    """Interactive loop.

    ``read``/``write``/``ask_fn`` are injectable so the loop is testable without
    touching real stdin/stdout or invoking the graph. ``allow_llm`` is forwarded
    to the default ``ask`` wrapper (ignored when a custom ``ask_fn`` is given).
    """
    if ask_fn is None:
        ask_fn = lambda text: ask(text, allow_llm=allow_llm)  # noqa: E731

    write(BANNER)
    write(_active_mode(allow_llm))
    write(SAFETY)
    write("")

    while True:
        try:
            line = read("you > ")
        except EOFError:          # Ctrl-D / Ctrl-Z / closed pipe
            write("")
            break
        if line is None:          # injected reader signalling end of input
            break

        text = line.strip()
        if not text:              # ignore empty / whitespace-only input
            continue
        if text.lower() in EXIT_WORDS:
            write("ARIA: goodbye.")
            break

        try:
            result = ask_fn(text)
            write(f"\nARIA {_format(result)}\n")
        except Exception as exc:  # never let one bad request crash the REPL
            # Never surface the raw exception text — it can carry secrets (e.g. a
            # provider error echoing an API key/password). Show only the error
            # category so nothing sensitive is ever displayed.
            write(
                f"\nARIA: sorry — that request failed "
                f"(error: {type(exc).__name__}; details redacted). "
                f"Try rephrasing.\n"
            )


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)

    # V1.1 single-turn REPL is preserved behind --v1 (and used by tests via
    # ``repl``/``ask``). By default ``python -m aria.chat`` now launches the Week
    # 32 multi-turn, session-aware, memory-aware terminal, which reuses ``ask`` as
    # the governed graph boundary for run_workflow.
    if "--v1" in argv:
        allow_llm = "--llm" in argv
        # Windows console fix for Unicode in artifact cards (mirrors main.py).
        # Guarded so importing/running under pytest's captured stdout is safe.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        repl(allow_llm=allow_llm)
        return 0

    from aria.conversation.terminal import main as session_main  # lazy: avoids import cycle

    return session_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
