# Week 30 — Architecture Diagram Notes

Notes for drawing the diagrams used in the reveal deck and README. These describe **what to
draw**; they are not a new architecture. Source of truth: `docs/architecture.md` and §26.1 of
`CLAUDE.md` (seven harness layers).

**Status:** Awaiting Codex Launch-Readiness Audit.

---

## Diagram 1 — The request loop (the golden path)

Draw left-to-right, single lane, with the ledger as a sink under every node:

```
  Request
     │
     ▼
 ┌────────┐   ┌────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────┐
 │ intake │──▶│ router │──▶│  skill node  │──▶│ evidence gate│──▶│ respond  │
 └────────┘   └────────┘   │ pr/kpi/ci/jira│   │ (fail-closed)│   └────┬─────┘
                           └──────────────┘   └──────┬───────┘        │
                                                     │ withhold        │ artifact
                                                     ▼                 ▼
                                        [RESPONSE WITHHELD]    Work Ledger v2 (typed events)
                                                                       │
                                                                       ▼
                                                            ROI metrics / Dashboard
```

Call-outs to label:
- router = **keyword or LLM** (keyword path needs no API key)
- evidence gate = **fail-closed**; KPI/CI-CD withhold when evidence is insufficient
- every node emits to the **Work Ledger** (today: terminal event live; full taxonomy via demo)

## Diagram 2 — The seven harness layers (concentric or stacked)

Stack the model in the middle, harness around it:

```
            ┌─────────────────────────────────────────────┐
            │ 7  Subagent / Workflow      (roadmap)        │
            │ 6  Evolution  (propose→sandbox→approve→roll) │
            │ 5  Memory / Work Ledger / ROI                │
            │ 4  Evaluation (rubrics, regression)          │
            │ 3  Governance (action tiers, approval, gate) │
            │ 2  Tool execution (MCP, dry-run, idempotency)│
            │ 1  Runtime (LangGraph: durable, resumable)   │
            │            ┌───────────────────┐             │
            │            │   the MODEL (LLM)  │  ← smallest │
            │            └───────────────────┘    part     │
            └─────────────────────────────────────────────┘
```
Caption: *the model is one component; the harness is the product.*

## Diagram 3 — Governed self-improvement loop

```
 monitor ─▶ propose ─▶ sandbox ─▶ evaluate ─▶ approve(human) ─▶ canary ─▶ promote
                                                   │                         │
                                                   └──────── rollback ◀──────┘
```
Label: **human approval is mandatory**; rollback path always retained; never autonomous.

## Diagram 4 — V1 / V2 / V3 boundary (simple bands)

Three horizontal bands; place each capability in its band. Pull contents from
[week30_v1_v2_v3_boundary.md](week30_v1_v2_v3_boundary.md). Keep "fine-tuning = prototype"
and "vLLM/deploy/subagents/multi-tenant = roadmap" visually unmistakable.

---

## Drawing rules (so diagrams don't overclaim)
- Mark roadmap layers/boxes with a dashed border and a "(roadmap)" tag.
- Mark the fine-tuning box "(prototype — offline)".
- Do not draw a vLLM server, a deployed model, or live Jira/Teams writes as solid/active.
- Keep the ledger present in every operational diagram — it's the through-line.
