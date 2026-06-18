# ARIA V2 — Fresh-Clone / Fresh-State Setup

How to go from a clean checkout to a running, verified V2 internal pilot.

> **Primary V2 demo requires no cloud credentials and no live connectors.**
> Everything in §1–§4 runs fully offline against deterministic fixtures. Cloud/Ollama
> are strictly opt-in (§7).

---

## 0. Prerequisites

- **Python** 3.13 + [`uv`](https://docs.astral.sh/uv/) (project/venv manager)
- **Node** 18+ and **npm** (frontend only)
- A POSIX shell or PowerShell. Commands below use forward slashes; on Windows
  PowerShell they work as-is from the repo root.

No API keys are required for the primary path.

---

## 1. Backend setup

```bash
cd apps/backend
uv sync                 # create .venv and install locked dependencies
```

That is the entire backend install. No `.env` is needed for the offline path.

---

## 2. Run the backend test suite

```bash
cd apps/backend
uv run pytest -q
```

Expected: **1205 passed, 1 skipped**. Tests are fully isolated — an autouse
fixture redirects `ARIA_LEDGER_V2_PATH`, the evolution deployment root, and
`ARIA_DATA_DIR` to per-test temp directories, so the suite never touches real
runtime files and makes no network/paid calls (even on a machine with provider
keys set).

Just the Week 35 acceptance tests:

```bash
uv run pytest tests/test_week35_v2_demo.py -q     # 21 passed
```

---

## 3. Run the full V2 demo (the headline proof)

```bash
cd apps/backend
uv run python -m aria.demo.v2_full_pilot          # cleans temp state on exit
uv run python -m aria.demo.v2_full_pilot --keep   # keep temp state to inspect it
```

- Default mode is `CONNECTOR_MODE=fixtures`; the demo also strips every provider
  key for the duration of the run, so **a paid call or a live connector is
  impossible**.
- All runtime state (SQLite domain memory + the v2 Work Ledger) is written to a
  throwaway temp directory and removed on exit (unless `--keep`).
- The demo prints a numbered 19-step trace and an explicit boundary statement
  (no external writes / no Jira / no Teams / no PR / no live connector / no vLLM /
  no training / no deployment).

---

## 4. Talk to ARIA locally (terminal, offline)

```bash
cd apps/backend
uv run python -m aria.chat            # multi-turn, session + memory aware, OFFLINE
uv run python -m aria.chat --v1       # single-turn V1.1 REPL
```

Local chat is **offline-by-default**: even if a provider key is configured in
`apps/backend/.env`, the live brain stays off unless you explicitly pass `--llm`.
See [`local_chat.md`](local_chat.md) for the full surface policy.

---

## 5. Optional — run the V2 web chat (frontend + API)

The web chat is optional; the headline proof in §3 needs no server.

Terminal A — serve the V2 API on port 8001 (the frontend dev proxy target):

```bash
cd apps/backend
uv run uvicorn aria.api.v2:build_v2_app --factory --port 8001
```

Terminal B — run the frontend dev server:

```bash
cd apps/frontend
npm install
npm run dev                 # http://localhost:5173 (proxies /api → :8001)
```

Frontend tests / build:

```bash
cd apps/frontend
npx vitest run              # 33 passed
npm run build               # production bundle into dist/
```

The web API binds to the ambient `ARIA_DATA_DIR` at request time. For a throwaway
session, set `ARIA_DATA_DIR` to a temp path before starting uvicorn (see §6).

---

## 6. Runtime state, isolation, and reset

All V2 runtime data lives under **`ARIA_DATA_DIR`** (default:
`apps/backend/.aria_data/`, which is **gitignored**) plus the v2 Work Ledger at
`ARIA_LEDGER_V2_PATH` (default: `apps/backend/work_ledger_v2.jsonl`, also
gitignored).

**Use an isolated data dir** (recommended for demos / experiments):

```bash
# bash
export ARIA_DATA_DIR=/tmp/aria_demo
export ARIA_LEDGER_V2_PATH=/tmp/aria_demo/work_ledger_v2.jsonl
```

```powershell
# PowerShell
$env:ARIA_DATA_DIR = "$env:TEMP\aria_demo"
$env:ARIA_LEDGER_V2_PATH = "$env:TEMP\aria_demo\work_ledger_v2.jsonl"
```

**Reset / wipe local runtime state** (safe — these files are not tracked):

```bash
# bash, from apps/backend
rm -rf .aria_data work_ledger_v2.jsonl
```

```powershell
# PowerShell, from apps/backend
Remove-Item -Recurse -Force .aria_data, work_ledger_v2.jsonl -ErrorAction SilentlyContinue
```

The `aria.demo.v2_full_pilot` demo manages its own temp dir and never depends on
or pollutes these paths.

---

## 7. Optional — local Ollama mode and model availability

The pilot is offline-by-default. A local model is **opt-in** and never required:

```bash
export ARIA_EXECUTION_MODE=local_ollama       # opt in to a local model
uv run python -m aria.llm.check               # verify readiness (no auto-download)
```

Behaviour contract:

- **Default mode is `offline_mock`** — deterministic local behaviour, no model, no
  network. An unset `ARIA_EXECUTION_MODE` can never escalate to cloud.
- **No cloud fallback.** Cloud is reached only via an explicit
  `ARIA_EXECUTION_MODE=cloud_opt_in`. **Credentials alone never select cloud** —
  a stray `ANTHROPIC_API_KEY` in the environment does not change the mode.
- **Model unavailable → loud failure, never silent downgrade.** If
  `local_ollama` is selected but the model/daemon is not ready, readiness raises
  rather than auto-downloading a model or silently falling back to `offline_mock`.
- An invalid `ARIA_EXECUTION_MODE` value raises `InvalidExecutionModeError` rather
  than guessing a mode.

---

## 8. Quick verification checklist

```bash
cd apps/backend
python -m compileall aria                      # syntax check
uv run pytest -q                               # 1205 passed, 1 skipped
uv run python -m aria.demo.v2_full_pilot       # OK + temp cleaned
cd ../frontend && npx vitest run && npm run build
cd ../.. && git status --short                 # clean after demo/tests
```
