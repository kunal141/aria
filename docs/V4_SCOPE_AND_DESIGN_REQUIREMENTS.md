# ARIA V4.1 — Scope & Design Requirements

> **Status: DOCUMENTATION / SCOPE ONLY — V4 not started.** This records the V4.1 scope
> and design requirements. It adds **no code** and changes no runtime, tests, APIs,
> frontend, connectors, or V3 behavior. V3 is COMPLETE, frozen, tagged
> (`aria-v3-goal-driven-workforce` → `17021ef`), and locally merged into `master`
> (`13a33ad`). **Public release remains blocked pending employer/IP approval.**

## Positioning (locked)

> *ARIA V4 is not just external adapter support. It is the foundation for governed
> model/runtime orchestration with evaluation and sovereignty.*

> *External runtimes are workers. Models are replaceable engines. ARIA remains the
> governance, memory, approval, Work Ledger, evaluation, action gate, and ROI control
> plane.*

## The V4.1 finish line (kept deliberately tight)

V4.1 is **contracts + hooks + one internal mock adapter** — nothing more. It delivers:

1. **External runtime adapter contracts** — the typed shape any future agent runtime
   must satisfy (already sketched in `V3_ROADMAP_META_HARNESS.md` §5.1).
2. **Model/router contracts** — the model provider registry + routing/sovereignty
   policy contracts (Requirement 1 below).
3. **Evaluation hooks** — the interface that lets adapters/model-routes later emit
   evaluation records (Requirement 2 below).
4. **Internal mock adapter only** — a deterministic, offline mock that exercises the
   contracts in tests. **No real external execution.**

**V4.1 must NOT become** Claude Managed Agents integration, `launch-your-agent`
integration, OpenAI Agents SDK integration, MCP integration, or local model serving.
Those are later V4.x increments, each gated on governance + approval. Do **not** expand
V4.1 into a long integration project.

---

## Requirement 1 — Model Router + Sovereignty Layer

**Why:** AI architecture is moving from "pick the one best model" to **governed
model/runtime orchestration**. ARIA must not hard-depend on a single cloud provider or
a single model — for cost, resilience, privacy, and export-control/sovereignty reasons.

**V4.1 deliverable:** contract / registry / policy definitions only (and, if a test
needs it, a single deterministic **mock** model). It is documentation + typed contracts,
not execution.

### Model categories
```text
frontier_cloud_model
open_cloud_model
local_open_model
coding_model
reasoning_model
embedding_model
reranker_model
fallback_model
```

### Routing examples (intent → category)
```text
hard reasoning / high-risk planning   → frontier model
repetitive coding / summarization     → cheaper open model
private / offline / fallback path     → local / open model
embedding / retrieval                 → specialized embedding model
```

### Contracts to define (no execution)
- **Model provider registry** — known providers/models as *data* (id, vendor, category,
  status), never live SDK clients.
- **Model capability profile** — what a model is good at (categories it serves,
  context window, modalities) as declared metadata.
- **Model cost/latency profile** — declared cost-per-token / typical latency bands (for
  routing decisions and ROI/eval, not billing).
- **Model risk profile** — risk classification (e.g. data-egress, privacy, output-risk)
  used by the governance harness.
- **Model fallback policy** — ordered fallback chain per category (e.g. frontier →
  open_cloud → local_open).
- **Sovereignty policy** — rules for when data may NOT leave a boundary (privacy /
  residency / export-control), forcing a local/open route.
- **Local/open model fallback plan** — the offline-capable route when no cloud is
  permitted or available.
- **Provider outage / export-control fallback plan** — deterministic degradation path
  when a provider is unavailable or disallowed.

### Rules (binding for V4.1)
- ❌ No real model API calls. ❌ No new provider SDKs. ❌ No network calls.
- ❌ No secrets / credentials. ❌ No live model execution.
- ✅ Contract / registry / policy only — plus at most a **deterministic mock model** for
  tests (offline, no network).
- ✅ The router is a **decision/policy layer**; actual model invocation stays a later,
  approval-gated V4.x increment.

---

## Requirement 2 — Evaluation Harness Hook

**Why:** Evaluation is a **first-class product layer**, not an afterthought. Every
runtime adapter and every model route should eventually be **evaluable** — for quality,
regression, safety-boundary compliance, and cost/latency.

**V4.1 deliverable:** only the **interface / contract / hook** so adapters and model
routes can *later* emit evaluation records. Not a full eval product.

### Evaluation record concept (typed contract)
```text
eval_id
goal_id
task_id
adapter_id
model_id
prompt_version
skill_version
input_ref
output_ref
expected_behavior
actual_behavior
score
pass_fail
failure_reason
human_label
cost_estimate
latency_ms
created_at
```

### What the evaluation contract must cover
- adapter output quality
- model output quality
- prompt/model regression
- safety-boundary compliance
- cost / latency tracking
- human review labels
- pass/fail reason
- version history (prompt_version / skill_version / model_id over time)

### Rules (binding for V4.1)
- ❌ No external eval API. ❌ No cloud service. ❌ No hidden telemetry.
- ✅ The hook is an **emit interface** adapters/routes can call later; V4.1 wires the
  contract, not a scoring engine.
- ✅ If evaluation data is persisted, it must be **path-confined** under
  `${ARIA_DATA_DIR}` (same discipline as every V3 store) and **source-linked**
  (`input_ref` / `output_ref` cite real records) — no orphan eval claims.
- ✅ Secrets masked / structural-secret refs rejected; no raw exception text — same
  store-authority posture as V3.5/V3.9/V3.10.

---

## How V4.1 attaches to existing work (no pre-building)

| V4.1 piece | Attaches to |
|---|---|
| External runtime adapter contracts | `V3_ROADMAP_META_HARNESS.md` §5.1 (Adapter Layer), §5.3 (Policy Gateway) |
| Model Router + Sovereignty | CLAUDE.md Pillar 24 (Model Intelligence); §12 Model Routing Strategy |
| Evaluation Harness Hook | CLAUDE.md §26.1 L4 (Evaluation Harness), Pillar 12 |
| Internal mock adapter | The V3 store/audit-outbox/path-confinement pattern (reused verbatim) |
| Governance posture | Deny-by-default action gate (V3.9), source-cited stores (V3.6/V3.10) |

These mappings exist so V4.1 design choices stay clean attach points — **do not
pre-build** the real adapters, SDKs, or serving layers.

## Non-goals (carried forward, binding)

V4.1 does **not** include: real external models, real external runtimes, live model/
agent APIs, MCP execution, Claude Managed Agents integration, `launch-your-agent`
integration, OpenAI Agents SDK integration, local model serving, deployment, public
release, or multi-tenancy. World/action/collaboration boundaries from V3 remain in force.

*Cross-references: [`V3_ROADMAP_META_HARNESS.md`](V3_ROADMAP_META_HARNESS.md),
[`EMERGING_CAPABILITY_RADAR_AND_ADAPTER_STRATEGY.md`](EMERGING_CAPABILITY_RADAR_AND_ADAPTER_STRATEGY.md),
[`V3_BOUNDARIES_AND_NON_GOALS.md`](V3_BOUNDARIES_AND_NON_GOALS.md),
[`V3_VALUE_PROPOSITION.md`](V3_VALUE_PROPOSITION.md); CLAUDE.md Pillar 24, §12, §26.1.*
