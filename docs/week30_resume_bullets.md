# Week 30 — Resume / CV Bullets

Portfolio bullets grounded in what is actually built and tested. Each is defensible against the
Truth & Claim Audit. Pick per role; do not stack claims that imply deployment.

**Status:** Awaiting Codex Launch-Readiness Audit.

---

## Headline bullet (lead with this)

- Designed and built **ARIA**, a governed AI-employee platform on **LangGraph** using
  **Harness Engineering** — seven layers (runtime, tools, governance, evaluation, memory,
  evolution, workflow) around the LLM — with **1021 automated tests passing** and a
  reproducible **offline** end-to-end demo.

## Engineering / platform bullets

- Built a **typed Work Ledger v2** (15 discriminated Pydantic event types, frozen contracts)
  that records every task/action and computes **ROI directly** — completion, approval rate,
  failure rate, cost-per-task, corrections, and model-usage breakdown.
- Implemented a **fail-closed evidence gate**: KPI and CI/CD responses are *withheld* when
  evidence is insufficient, preventing confident-but-unsupported answers.
- Implemented **governance with action tiers (T1–T3 live, T4 behind explicit approval)** and a
  **governed self-improvement pipeline** (propose → sandbox → evaluate → approve → canary →
  rollback) — never autonomous.
- Built a **Model Lifecycle Registry v1** (version, training-dataset hash, eval score, rollback
  pointer) and an offline **dataset-export + fine-tuning prototype** — proving the
  shadow-learning pipeline end-to-end **without training or deploying any model**.

## ML / LLM-engineering bullets

- Engineered the harness around model calls — **router, structured outputs (Instructor +
  Pydantic), RAG, code intelligence, memory** — so the model is swappable and every call is
  governed, evaluated, and logged.
- Built an **offline-deterministic test/demo mode** that strips all provider keys and aborts on
  any live key, guaranteeing zero paid API calls in CI and demos.

## Leadership / product bullets

- Authored a **Truth & Claim Audit** classifying every capability as Built / Partial / Prototype
  / Roadmap, and a **public-safety audit** — engineering rigor *and* honest scoping for a reveal.
- Framed the work as **Harness Engineering**: "the model is one component; the real intelligence
  comes from orchestration, memory, tools, governance, evaluation, workflows, Work Ledger, ROI
  measurement, and safe execution around the model."

---

## Quantified claims you may use (all verifiable)
- `1021 tests passing, 1 skipped`
- `15` typed Work Ledger event types
- `7` harness layers; `24` capability pillars (with honest V1/V2/V3 boundary)
- Offline demo: one command, deterministic ROI snapshot

## Claims you must NOT make
- ❌ "deployed a fine-tuned model" / "trained on production data"
- ❌ "fully autonomous AI employee"
- ❌ "live Jira/Teams automation in production"
- ❌ "all 24 pillars operational"
