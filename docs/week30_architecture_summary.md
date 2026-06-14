# Week 30 — Final Architecture Summary

A consolidated, honest view of how ARIA is built as of the Week 30 launch-readiness audit. This
summarizes; the canonical detail lives in `docs/architecture.md` and `CLAUDE.md` §26.1.

**Status:** Awaiting Codex Launch-Readiness Audit.

---

## One-sentence architecture

ARIA is a **LangGraph state machine** whose nodes call **typed, Pydantic-contracted skills**,
governed by **action tiers + a fail-closed evidence gate**, with every task and action recorded
in a **typed Work Ledger** that computes ROI — i.e. a **Harness Engineering** system where the
model is one swappable component.

## The request lifecycle (what actually runs)

```
request → intake → router → skill node → evidence gate → respond → Work Ledger → ROI
                   (kw/LLM)  (pr/kpi/      (fail-closed)            (typed events)
                              ci_cd/jira/
                              qa/...)
```

- **intake** — assigns `task_id`, seeds audit trail.
- **router** — classifies task type (keyword path needs no API key; LLM path when available).
- **skill node** — runs the typed skill; offline mode uses deterministic mocks.
- **evidence gate** — KPI/CI-CD answers are **withheld** when evidence is insufficient.
- **respond** — formats the artifact (or the withholding notice).
- **Work Ledger** — records events; ROI metrics derive from them.

## The seven harness layers (and where they live)

| # | Layer | Code home (today) |
|---|---|---|
| 1 | Runtime | `aria/graph.py`, `aria/state.py`, `aria/nodes/*` |
| 2 | Tool execution | `aria/skills/*`, tool harness |
| 3 | Governance | governance module, `aria/nodes/respond.py` (evidence gate), evolution constitutional checks |
| 4 | Evaluation | eval harness + per-skill `_eval()` |
| 5 | Memory | `aria/memory/*`, `aria/ledger/*`, `aria/work_ledger.py` |
| 6 | Evolution | `aria/evolution/*` (pipeline, registry, update_manager), model registry |
| 7 | Subagent/workflow | **roadmap** — §28.1 attach points only (not built) |

## Work Ledger v2 (the memory spine)

- 15 **discriminated, frozen Pydantic** event types; envelope carries `task_id`, `actor`,
  `actor_type`, `correlation_id`, timestamp.
- **Reader/metrics** compute: tasks completed, tasks-by-skill, approval rate, failure rate,
  cost totals/per-task, corrections, model-usage breakdown, latency.
- Isolation seams: v2 `LedgerWriter` + `configure_default_writer`; legacy via module-constant
  redirection. The demo uses a temp dir and cleans up.
- The `correlation_id` + `actor` fields are deliberate **attach points** for future subagents
  (§28.1) — no migration needed later.

## Governance & safety (structural, not documentation)

- **Action tiers:** T1–T3 live; **T4 behind explicit approval**; T5 not enabled.
- **Evidence gate:** fail-closed; refuses unsupported claims.
- **Privacy:** secrets redacted/rejected at the type boundary.
- **Governed evolution:** propose → sandbox → evaluate → approve → canary → **rollback**; never
  autonomous. Backed by the **Model Lifecycle Registry v1** (version, dataset hash, eval score,
  rollback pointer).

## Model intelligence (honest status)

- **Router** chooses models per task; structured output via **Instructor + Pydantic**.
- **Dataset export** + **fine-tuning prototype** exist as **offline dry-runs**. **No model was
  trained or deployed; active model = NONE; no vLLM serving; router not wired to a fine-tuned
  model.**

## What is explicitly NOT in the architecture yet (roadmap)

vLLM serving · real fine-tuning/deployment · live Jira/Teams connectors · §28.1 Subagent
Instruction Engine · §26.8 Generative UI Canvas · §28.4 eight future capabilities · multi-tenant
AaS · autonomous self-modification.

## Verification surface

- Tests: `1021 passed, 1 skipped`.
- Demo: `cd apps/backend && uv run python -m aria.demo.golden_path` (offline, deterministic).

---

*See [week30_truth_and_claim_audit.md](week30_truth_and_claim_audit.md) for the per-capability
Built/Partial/Prototype/Roadmap classification, and
[week30_v1_v2_v3_boundary.md](week30_v1_v2_v3_boundary.md) for the version boundary.*
