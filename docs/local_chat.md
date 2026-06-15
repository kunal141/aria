# ARIA — Local Chat (natural-language REPL)

A small V1.1 usability wrapper so you can talk to ARIA in plain English from a
terminal, instead of editing the hard-coded inputs in `apps/backend/main.py`.

## Run

```bash
cd apps/backend
uv run python -m aria.chat            # offline keyword brain (default)
uv run python -m aria.chat --llm      # opt in to the live LLM brain (paid)
```

You'll see:

```
ARIA Local Chat
Mode: offline/local unless --llm is given AND a provider key is configured
Active brain: keyword router (offline, no API calls)
Note: local chat is a governed local workflow surface — not production execution.
No live Jira/Teams/GitHub writes occur, and state-changing evolution actions are blocked (dry-run) from chat.
```

Type a request and press Enter. Type `exit` or `quit` (or press Ctrl-D) to stop.

## Example prompts

```text
Review my PR for recommendation engine
Check what is wrong in events data table
Create Jira draft for missing session_id issue
Investigate CI/CD failure
Prepare QA checklist for personalization API
```

Each is classified by the existing router and dispatched to the matching skill
(`pr_review`, `kpi`, `ci_cd`, `jira`, `qa`, `test_review`, `evolution`, or
`general`). The reply shows the routed skill in brackets followed by ARIA's
response.

## Offline vs paid LLM mode

| Mode | When | Behaviour |
|---|---|---|
| **Offline (default)** | no `--llm` flag (provider key may even be present) | Keyword router + deterministic mock skill outputs. **No paid API call, no network.** |
| **LLM (opt-in)** | `--llm` flag **and** a provider + key configured in `.env` | Same graph, but the router and skills use the live model. **Makes paid API calls.** |

Local chat is **offline-by-default**: even if `LLM_PROVIDER` + an API key are set
in `apps/backend/.env`, the live brain stays off unless you pass `--llm`. The
flag is the only thing that enables paid calls.

To use the live brain, configure a provider in `apps/backend/.env` and pass `--llm`:

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

## What local chat writes (normal usage)

In normal (non-test) usage, local chat runs the same governed graph the rest of
the platform uses, so it **writes the local runtime logs** that any graph run
produces, for example:

- `apps/backend/work_ledger.jsonl` and the v2 ledger (every completed task)
- `apps/backend/tool_audit.jsonl` (tool invocations, when a tool runs)
- `apps/backend/notifications.jsonl` (mock Teams notifications — printed/logged
  locally, **never sent** to a real Teams workspace)
- `apps/backend/memory_store.json` (memory writes)

These are **local files only**. Local chat may print/queue **mock** Teams
notifications; no message leaves your machine.

**Test mode is isolated.** `tests/test_chat_repl.py` redirects every runtime sink
(audit, ledger, notifier, memory) into a temp directory and forces offline mode,
so running the tests does **not** modify any of the real runtime files above and
makes no network/paid calls — even on a machine with real provider keys.

## Boundary (governed local workflow, NOT production execution)

Local chat reuses the same governed graph the test suite exercises. Every request
carries a restrictive **safe chat surface policy**
(`surface="local_chat"`, `execution_mode="dry_run"`, `allow_mutations=False`,
`allow_llm=False`), which downstream nodes honour. As a result, local chat does
**not** perform production execution:

- **No live Jira / Teams / GitHub writes** — those connectors are V2 and require
  approval. An explicit "create a ticket" request produces an
  **approval-required draft**, not an executed ticket.
- **State-changing evolution actions are blocked / dry-run.** "scan",
  "evaluate proposal", "promote canary", and "rollback component" through chat
  return a blocked, approval-required answer and **never** persist, activate, or
  restore a real runtime component. You can still *ask* about evolution (e.g.
  list pending proposals) — you just get the safe dry-run response. Real
  promotion or rollback only happens through the governed T4 approval path, not
  local chat.
- **No LangSmith / network calls in offline mode.** The offline scope disables
  tracing as well as the LLM, so even with ambient `LANGSMITH_API_KEY` set,
  offline chat makes no outbound connections.
- **Error text is redacted on the paths that surface or persist it.** Raw
  exception text can carry secrets, so the paths that would otherwise expose it
  show the exception *class* only: (a) an exception that escapes the graph is
  reported to the REPL by class name, never its message; (b) the evolution node
  returns a typed `internal_error` envelope for internally-caught errors; and
  (c) a router LLM-classify failure records only the exception class in
  `routing_reason` (which is returned to callers and written to the ledger).
  This is not a blanket guarantee for every conceivable skill code path — it
  covers the surfaces that return or persist error text today.
- **No vLLM serving, no model training, no deployment.**
- Governance gates (evidence gate, action tiers, approvals) are preserved exactly
  as in the normal graph path — e.g. KPI / CI-CD claims without sufficient
  evidence are withheld.

It is a convenience surface over `aria.graph.aria_graph` — the same entry point
`main.py` uses.
