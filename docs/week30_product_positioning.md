# Week 30 — Product Positioning

How to describe ARIA — to leadership, in interviews, and (after approval) publicly. Every line
here is consistent with the Truth & Claim Audit. No exaggeration.

**Status:** Awaiting Codex Launch-Readiness Audit.

---

## The two locked lines

> **Claude gives intelligence. ARIA gives governed work ownership.**

> **ARIA is built using Harness Engineering: the model is only one component; the real
> intelligence comes from orchestration, memory, tools, governance, evaluation, workflows,
> Work Ledger, ROI measurement, and safe execution around the model.**

These appear verbatim in the deck, the demo script, the README notes, and the LinkedIn draft.
Do not paraphrase them.

---

## The category

ARIA is a **governed AI-employee platform**, built with **Harness Engineering**. It is:

- **not a chatbot** — it receives goals, does engineering work, and produces artifacts;
- **not a copilot** — it owns a task end-to-end through a governed loop, not inline autocomplete;
- **not autonomous** — it proposes, a human approves, then it acts (T1–T3 in V1; T4 gated; T5 off).

The platform is the product. **ARIA is the first employee built on it** — an AI Engineer in a
media-tech context.

---

## Why "Harness Engineering" is the right frame

The model is the smallest, most replaceable part. Anyone can call an LLM. The durable value is
the system around it — and that system is seven layers:

| Layer | What it buys you | Proof in this repo |
|---|---|---|
| 1 Runtime | durable, resumable, auditable execution | LangGraph graph + state |
| 2 Tool execution | typed I/O, dry-run, idempotency, audit | skills + tool harness |
| 3 Governance | action tiers, approval gates, **fail-closed evidence gate** | governance + respond node |
| 4 Evaluation | rubrics, regression, LLM-as-judge | eval harness + skill evals |
| 5 Memory | task/outcome/institutional memory + **Work Ledger** | ledger v2 + memory |
| 6 Evolution | propose → sandbox → approve → canary → **rollback** | evolution pipeline + registry |
| 7 Subagent/workflow | typed delegation *(roadmap)* | §28.1 attach points only |

This frame is honest: it foregrounds what is actually built and well-tested, and it makes the
roadmap legible instead of hidden.

---

## What makes it credible (not just claimed)

- **It runs offline, deterministically:** `uv run python -m aria.demo.golden_path` — no API key.
- **It refuses to guess:** the evidence gate withholds unsupported KPI/CI-CD answers, live.
- **It measures itself:** ROI (completion, approval rate, failure rate, cost/task, corrections)
  computed directly from the Work Ledger.
- **It is tested:** `1021 passed, 1 skipped`.
- **It is honest about limits:** fine-tuning is an offline prototype; nothing is deployed.

---

## Positioning against alternatives (interview-ready)

| Asked about | One-line answer |
|---|---|
| "Isn't this just a Claude wrapper?" | "Claude gives intelligence. ARIA gives governed work ownership — seven harness layers wrap the call." |
| "Is it autonomous / risky?" | "Deliberately not. It proposes; a human approves; then it acts. Rollback is always retained." |
| vs AgilePoint | "Open standards (LangGraph/MCP), institutional memory, self-dogfooding corpus — not a proprietary SDK." |
| vs AutoGPT-style agents | "Enterprise governance, action tiers, evidence gate, evaluation harness, Work Ledger." |
| vs Yukti (internal) | "Yukti is the organisational operating model; ARIA is the execution-intelligence layer. Complementary." |

---

## Words to use / avoid

**Use:** governed, harness, evidence-gated, fail-closed, Work Ledger, ROI, prototype, roadmap,
institutional memory, human-approved.

**Avoid:** autonomous, fully automated, self-modifying, production fine-tuned, deployed model,
"all 24 pillars working," "operational self-evolution," any live-write claim for Jira/Teams.

---

## Cross-references
- Truth basis: [week30_truth_and_claim_audit.md](week30_truth_and_claim_audit.md)
- Boundaries: [week30_v1_v2_v3_boundary.md](week30_v1_v2_v3_boundary.md)
- Demo: [week30_golden_demo.md](week30_golden_demo.md)
