# Week 30 — Golden End-to-End Demo

**One command. Fully offline. No paid API. Deterministic.**

```bash
cd apps/backend
uv run python -m aria.demo.golden_path
```

This is the canonical demo for the reveal. **Stage 1 runs the live loop** —
**request → routing → skill → evidence gate → artifact → terminal Work Ledger event** — with
no network call and no API key. The live graph emits only the **terminal** event per task
today, so **Stage 2 seeds** a representative governed lifecycle (the **approval path**, the
**failure path**, and a **rollback/evolution proof**) using the real typed v2 event classes,
and **Stage 3** aggregates live + seeded events into the ROI snapshot. It ends by printing,
verbatim:

> *Prototype / demonstration only. No paid API call, no network call, no model training, and no deployment occurred during this run.*

**Status:** Week 30 Launch Readiness ACCEPTED by Codex (2026-06-15). Week 30 complete.

---

## Why it is safe (no paid call is possible)

The script forces a key-gated provider (`anthropic`), imports config so `.env` loads,
then **strips every provider key** from the environment. `has_llm()` reads the environment
live, returns `False`, and every skill takes its deterministic **mock** path. A guard
**aborts the run** if any provider key is still visible. **Every runtime side-effect sink the
graph can write** — the Work Ledger (v2 + legacy), the notification log, and the tool-audit
log — is redirected into a temporary directory that is deleted on exit, and the repointed
module globals are restored afterwards, so a live run leaves the repo **byte-for-byte
unchanged** (a regression test asserts this). See
[golden_path.py](../apps/backend/aria/demo/golden_path.py).

---

## What it demonstrates, stage by stage

### Stage 1 — LIVE graph runs (real routing + real skill, offline mock)

Four representative requests are invoked through the **real** `aria_graph`. Routing is by
keyword (no LLM). Each run writes one real terminal `Responded` event to the isolated ledger.

| Request (abridged) | Routed type | Evidence gate | Result |
|---|---|---|---|
| "Review my PR for the recommendation-service ranking change" | `pr_review` | n/a | artifact **surfaced** (PR review card) |
| "Our notification-service CTR dropped 18%…" | `kpi` | **fires** | `[RESPONSE WITHHELD — UNSUPPORTED CLAIMS]` |
| "The CI/CD pipeline is failing on deploy…" | `ci_cd` | **fires** | withheld **+** proactive Teams card emitted |
| "Create a Jira ticket for the push bug" | `jira` | n/a | draft artifact **surfaced** (T4 approval gate) |

The KPI/CI-CD **withholding is the point**: the Platform-Intelligence evidence gate is
**fail-closed** — when it cannot cite sufficient evidence it refuses to surface claims. This
is governance you can *see*, not a slide.

### Stage 2 — SEEDED governed lifecycle (real typed v2 events)

Because the live graph mirrors only the **terminal** event today (see the Truth Audit —
this is a Partial), the demo seeds a representative governed lifecycle using the **real**
15 typed v2 event classes (deterministic ids + UTC timestamps). 29 events across 4 tasks:

| Task | Path demonstrated |
|---|---|
| `gold-approval` | T4 approval **GRANTED** → action taken → completed (with cost + model events) |
| `gold-rejected` | T4 approval **REJECTED** → action withheld (non-terminal, awaiting revision) |
| `gold-failure` | terminal **FAILURE** (no response) |
| `gold-rollback` | human **correction** + `rolled_back` outcome + model **rollback** lifecycle event |

These are ordinary domain events the metrics layer counts — **not invented ROI numbers**.

### Stage 3 — ROI snapshot (real `LedgerReader → LedgerMetrics.summary()`)

The same aggregation the ROI Dashboard consumes. **Expected output (deterministic):**

```
tasks completed         : 6
tasks by skill          : {'jira': 3, 'ci_cd': 2, 'evolution': 1, 'pr_review': 1, 'kpi': 1}
approvals granted/reject : 1 / 1
approval_rate           : 0.5
failed / terminal tasks : 1 / 7
failure_rate            : 0.14285714285714285
artifacts created       : 3
corrections (DPO signal): 1
cost total / per task   : 0.0117 / 0.0117
human intervention rate : 0.3333333333333333
model usage             : {'claude-haiku-4-5': 1}
v2 events / legacy / bad : 33 / 4 / 0
avg_time_to_resolution_ms: 8000.0
```

> **Determinism note.** The seeded lifecycle and all ROI **counts/rates above are
> deterministic** across runs. The four live tasks get fresh UUID `task_id`s each run, so
> individual IDs differ — but they always contribute the same 4 completions, so the summary
> is stable. The full `MetricsSummary` JSON printed at the end is the exact shape served by
> `GET /api/v1/ledger/metrics`.

---

## The seven-layer story this demo tells

| Harness layer | Seen in the demo |
|---|---|
| Runtime | the LangGraph invoke chain (intake→router→skill→respond) |
| Tool execution | skill mock outputs + the Jira T4 approval gate |
| Governance | evidence-gate withholding; approval granted vs rejected; action tiers |
| Evaluation | (referenced) eval harness scores live behind `evaluation_score` |
| Memory | Work Ledger v2 — typed, queryable events (terminal event live per task; full taxonomy seeded/tested) |
| Evolution | the rollback task + model-lifecycle rollback event |
| Subagent/workflow | roadmap — `correlation_id`/`actor` already on every event for clean attach |

---

## Pairing demos (also offline, already Codex-accepted)

For the slices the golden path references rather than fully runs:

```bash
uv run python -m aria.ledger.demo --dashboard   # full MetricsResponse payload for the UI
uv run python -m aria.model_registry.demo        # register → approve → activate → rollback
uv run python -m aria.training_data.demo         # SFT/DPO dataset export from the ledger
uv run python -m aria.fine_tuning.demo           # offline dry-run; asserts active model: NONE
```

Each ends with a "Prototype only…" boundary line. None trains or deploys anything.
