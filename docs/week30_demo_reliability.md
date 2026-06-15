# Week 30 — Demo Reliability (Fresh-Clone Runbook)

Goal: anyone can clone the repo and reproduce the golden demo with **commands that
actually work from a clean setup** — no paid API, no hidden state.

**Status:** Week 30 Launch Readiness ACCEPTED by Codex (2026-06-15). Week 30 complete.

---

## 0. Prerequisites

- **Python 3.11+** and **[uv](https://github.com/astral-sh/uv)** (project uses `uv` + `.venv`).
- **Node 18+** (only for the ROI Dashboard frontend; the backend demo needs no frontend).
- No API keys required for the primary demo. (Keys are only needed for live LLM answers,
  which the demo deliberately does not use.)

---

## 1. Fresh-clone setup

```bash
git clone <repo-url> aria
cd aria/apps/backend
uv sync                 # creates .venv and installs locked deps
```

> If you see `warning: VIRTUAL_ENV=...anaconda3 does not match ...` — this is **benign**.
> `uv` ignores the outer env and uses the project `.venv`. The demo still runs correctly.

Optional (only for live LLM answers, NOT for the demo):
```bash
cp .env.example .env     # then add ANTHROPIC_API_KEY=... if you want online skills
```

---

## 2. Smoke test (proves the install is healthy)

```bash
cd apps/backend
uv run python -m pytest -q
```
**Expected:** `1027 passed, 1 skipped` (benign deprecation warnings only). Runtime ≈ 20s.

---

## 3. Primary demo command (offline, deterministic)

```bash
cd apps/backend
uv run python -m aria.demo.golden_path
```
**Expected:** three stages print (LIVE runs → SEEDED governed lifecycle → ROI snapshot),
ending with the boundary line *"No paid API call, no network call, no model training, and no
deployment occurred."* Exit code `0`. See [week30_golden_demo.md](week30_golden_demo.md) for
the exact expected ROI numbers.

Pass `--keep` to retain the temp ledger directory for inspection:
```bash
uv run python -m aria.demo.golden_path --keep
```

---

## 4. Environment validation (is my setup demo-ready?)

| Check | Command | Healthy result |
|---|---|---|
| uv present | `uv --version` | prints a version |
| deps installed | `uv run python -c "import langgraph, pydantic, fastapi"` | no error |
| offline guard works | run the demo with a bogus key: `ANTHROPIC_API_KEY=x uv run python -m aria.demo.golden_path` | still offline — the script strips the key; mock path taken |
| full suite | `uv run python -m pytest -q` | `1027 passed, 1 skipped` |

---

## 5. Demo state & how to reset it

The golden demo is **stateless** — it isolates every runtime sink (ledger + notification +
tool-audit logs) into a temp directory that it deletes on exit, and restores the repointed
module globals afterwards, so a run leaves the repo byte-for-byte unchanged. A regression test
(`tests/test_week30_golden_demo.py::test_demo_does_not_mutate_runtime_files`) asserts this.
There is **nothing to reset** for the primary demo.

If you ran other tools that write the real runtime ledgers, those files are **gitignored**
and safe to delete to start clean:

```bash
# from apps/backend — remove regenerable runtime data (all gitignored)
rm -f work_ledger.jsonl work_ledger_v2.jsonl evolution_events.jsonl \
      update_releases.jsonl tool_audit.jsonl notifications.jsonl ml/registry.jsonl
rm -rf deployments/
```
None of these are source; the platform regenerates them on next run.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `OFFLINE GUARD FAILED: a provider key is still visible` | An exotic provider env var the stripper doesn't cover | Unset all `*_API_KEY` vars in your shell, or run in a clean shell; the guard is doing its job (refusing to risk a paid call) |
| `ModuleNotFoundError: aria...` | Not in `apps/backend`, or deps not synced | `cd apps/backend && uv sync` |
| Unicode/emoji garbled in terminal | Non-UTF-8 console | The script calls `reconfigure(encoding="utf-8")`; on legacy consoles set `PYTHONUTF8=1` |
| `VIRTUAL_ENV does not match` warning | Conda/other env active | Benign — ignore, or `conda deactivate` before running |
| ROI numbers differ from the doc | You ran with `--keep` and re-ran into the same dir, or seeded extra data | Run fresh (no `--keep`); counts are deterministic on a clean temp ledger |

---

## 7. ROI Dashboard (optional, secondary surface)

The dashboard is a React view that reads `GET /api/v1/ledger/metrics`. It is **not required**
for the primary demo (the golden path prints the same metrics to stdout). To show it live you
need the FastAPI app serving the ledger API and the frontend dev server running; that path
depends on having ledger data on disk and is a secondary, non-blocking surface for the reveal.
