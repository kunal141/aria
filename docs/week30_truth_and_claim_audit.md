# Week 30 — Truth & Claim Audit

**Purpose.** Before ARIA is demonstrated to anyone, every capability claim is classified
against what the code and the accepted tests actually prove. This document is the
honesty gate for the launch package. If a claim is not here, or is softer here than
elsewhere, **this document wins.**

**Status:** Awaiting Codex Launch-Readiness Audit.

**Baseline of record (verified 2026-06-14):**
- Backend test suite: **1021 passed, 1 skipped** (`cd apps/backend && uv run python -m pytest`).
- HEAD `6d279b1` (docs) ← `9590750` (Week 29 feature work, Codex-accepted).
- Golden demo runs fully offline with no paid API call: `cd apps/backend && uv run python -m aria.demo.golden_path`.

---

## Classification legend

| Label | Meaning |
|---|---|
| **Built** | Implemented, covered by accepted tests, and runs. Demonstrable today. |
| **Partial** | Core is built and tested, but a named part is mock/stub/not wired into the live path. |
| **Prototype** | Exists to prove a pipeline end-to-end; explicitly NOT production (offline dry-run, no real effect). |
| **Roadmap** | Documented design only (V2/V3). No implementation. |

A capability being **Built** says nothing about LLM answer *quality* — quality is governed
by the evaluation harness and was not independently benchmarked for this audit. Offline,
skills return deterministic mock outputs; the online path requires an API key that the demo
deliberately withholds.

---

## 1. Capability classification

### Built (implemented, tested, runs)

| Capability | Evidence | Notes |
|---|---|---|
| LangGraph runtime (intake → router → skill → respond) | Runs in golden demo; full graph invoked offline | Keyword router needs no API key |
| Keyword/LLM router | `aria/nodes/router.py` (`has_llm()` keyword fallback) | Offline path classifies all 5 demo inputs correctly |
| PR Review skill | Golden demo: artifact **surfaced**; `pr_review_skill.py` mock + real paths | Online quality not benchmarked here |
| KPI skill + evidence gate | Golden demo: **withheld** (`[RESPONSE WITHHELD — UNSUPPORTED CLAIMS]`) | Fail-closed governance proven live |
| CI/CD skill + proactive notification | Golden demo: Teams card emitted; evidence gate fired | Notification is a governed skill output |
| Jira **drafting** skill + T4 approval gate | Golden demo: artifact surfaced; `request_approval`/`is_approved` gate | Live Jira write is **Partial** (see below) |
| QA / test-review skills | Registered in `skill_nodes.py`; offline mocks; suite green | Not in golden demo, covered by tests |
| Typed skill contracts (Pydantic in/out) | All skills return validated models | Platform invariant |
| Work Ledger v2 (schema, writer, reader, metrics, API) | 125 ledger tests pass; golden demo aggregates real metrics | Per-event *emission* is **Partial** (below) |
| ROI metrics (`LedgerMetrics.summary()`) | Golden demo prints real snapshot | Decimal money, documented denominators |
| ROI Dashboard (frontend) | `ROIDashboard.jsx` consumes `/api/v1/ledger/metrics`, full schema validation | Reads real ledger data |
| Governance Action Tiers T1–T3 | Skills tagged `action_tier`; approval gate for T4 draft→execute | T4 bounded; T5 not in V1 |
| Evidence/Platform-Intelligence layer (fail-closed) | Golden demo withholds unsupported KPI/CI-CD claims | Real demonstration, not documentation |
| Memory fabric (6 typed memory models, file store) | `aria/memory/*`; tests | Operational + institutional memory |
| RAG strategies (HyDE, Self-RAG, Adaptive) + code intel (AST) | `aria/knowledge/*`; learning artifacts + tests | Vector store is Chroma (pgvector = V2) |
| CrewAI Analytics+QA crew | `analytics_qa_crew_node`, graceful offline fallback | Hands-on multi-agent |
| Decision Intelligence (greedy ranking) | `general_node` runs offline deterministically | LATS tree-search variant exists |
| Governed evolution pipeline (Week 27–28) | monitor→propose→sandbox→evaluate→approve→canary→promote→rollback; real artifact write/restore (`ddcb192`); tests | Pipeline is built; **continuous autonomous operation is NOT claimed** |
| Model Lifecycle Registry v1 | `model_registry` demo runs; file-backed JSONL; Week 29 P4 accepted | Records prototype entries + rollback pointer |
| Dataset Export (SFT/DPO from ledger) | `training_data` demo runs offline | Produces small/possibly-empty sets at current data scale |

### Partial (core built; a named part is mock or not wired live)

| Capability | What IS built | What is NOT (yet) |
|---|---|---|
| Work Ledger v2 **per-event emission in the live graph** | Schema + writer + reader + metrics + 15 typed events, all accepted | The **live** production graph mirrors only the **terminal** `Responded`/`Failed` event. The richer taxonomy (`Routed`, `SkillInvoked`, `ApprovalRequested`, `Approved`, `ActionTaken`, `CostRecorded`, `ModelUsed`) is exercised by tests, the ledger demo, and the golden demo's seeded lifecycle — it is **not auto-emitted** end-to-end by the production graph. |
| Jira capability | Ticket **drafting** + T4 approval gate | The actual Jira REST write is `_mock_jira_create` ("real Jira API integration arrives in V2"). No live ticket is created. |
| Teams identity / voice surface | `teams_bot.py`, `voice_api.py`, `ARIAVoice.jsx` exist | Live Teams/voice deployment needs credentials + hosting; not exercised in the offline demo and not audited here. |
| Model Router | Routing logic by task/risk/privacy | Routing to a **fine-tuned self-hosted** model is V2 (no such model exists). |

### Prototype (proves a pipeline; explicitly not production)

| Capability | Reality |
|---|---|
| Fine-Tuning Prototype (Week 29 P5) | **Offline deterministic dry-run.** No real training ran, no GPU, no paid/external compute, **no model was activated** (the demo asserts `active model: NONE`). It proves the pipeline shape only. |
| Dataset → registry → (would-be) train loop | The chain is wired and runnable offline; it does not produce a usable model. |

### Roadmap (documentation only — V2/V3)

vLLM serving · real fine-tuning / production model · production deployment · multi-tenant AaS ·
Subagent Instruction Engine (§28.1) · Generative UI Canvas (§26.8) · the eight Section 28.4
capabilities (delegated agent identity, A2A envelopes, AG-UI event stream, persistent
workspaces, branching experiments, security gateway, episode packages, agent-config
compatibility) · live enterprise connectors with real writes · autonomous self-modification.

---

## 2. Overclaims to remove or soften (everywhere)

These phrasings are **not supported** and must not appear in any demo, slide, README, or post:

| ❌ Do not say | ✅ Say instead |
|---|---|
| "All 24 pillars are functional" | "24 pillars are designed; a V1 subset is built and tested — see classification above." |
| "Fully autonomous AI employee" | "Governed AI employee: it proposes; a human approves; nothing reaches production without sign-off." |
| "Operational self-evolution" | "A governed self-improvement **pipeline** (propose→sandbox→approve→canary→rollback) with accepted tests. Not running autonomously in production." |
| "Production fine-tuned model" / "trained on our data" | "A fine-tuning **prototype** — an offline dry-run that proves the pipeline. No model was trained or deployed." |
| "Real deployment" / "vLLM serving live" | "No deployment. No vLLM serving. The model router is not wired to any self-hosted model." |
| "Live in Teams / creating real Jira tickets" | "Teams/voice surfaces and Jira drafting exist; live writes need credentials and are V2." |
| "Every task is fully logged in v2" | "Every task logs a terminal v2 event today; full per-event emission is in progress (Partial)." |
| "ROI proven over 6 months of production use" | "ROI **measurement** is built and computes from the Work Ledger; figures shown are from seeded/accumulated local data, not a production rollout." |

---

## 3. Explicit negative statements (state these plainly)

- **No vLLM serving.** Not started.
- **No real fine-tuning.** The only fine-tuning artifact is an offline deterministic dry-run; no weights were trained.
- **No paid or external training/compute.** The demo and prototypes make no network call and require no GPU.
- **No production deployment.** Nothing is hosted; the production graph and model router were not modified for launch readiness.
- **No autonomous self-modification.** Evolution is human-gated end to end.
- **No live enterprise connectors with real writes.** Jira write is a mock; Teams/voice need credentials.
- **Section 28.4 (and §28.1/§26.8) are roadmap only.** No implementation exists.

---

## 4. What a viewer can verify themselves

1. `cd apps/backend && uv run python -m pytest` → **1021 passed, 1 skipped**.
2. `cd apps/backend && uv run python -m aria.demo.golden_path` → end-to-end offline flow, ending in the printed line: *"No paid API call, no network call, no model training, and no deployment occurred."*
3. `uv run python -m aria.model_registry.demo` / `aria.fine_tuning.demo` / `aria.training_data.demo` → each ends with a "Prototype only…" boundary line; the fine-tuning demo shows `active model: NONE`.

Anything not reproducible by these commands should be treated as **not proven** for launch.

---

_Cross-references: see `week30_v1_v2_v3_boundary.md` for the version line, `week30_final_proof_checklist.md` for hashes/counts, and `week30_golden_demo.md` for the demonstrated flow._
