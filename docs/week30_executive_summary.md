# Week 30 — Executive Summary

One-page brief for leadership. Plain language, no exaggeration, every claim traceable to the
Truth & Claim Audit.

**Status:** Awaiting Codex Launch-Readiness Audit.

---

## What ARIA is

ARIA is a **governed AI-employee platform** for engineering work. It receives goals, does the
work (PR review, KPI investigation, CI/CD triage, Jira drafting, QA/test generation), produces
structured artifacts, and records every action — but **it never reaches production without a
human approving it**.

> Claude gives intelligence. ARIA gives governed work ownership.

The platform is the product; **ARIA is the first employee built on it.**

## Why it's different

> ARIA is built using Harness Engineering: the model is only one component; the real
> intelligence comes from orchestration, memory, tools, governance, evaluation, workflows, Work
> Ledger, ROI measurement, and safe execution around the model.

Seven layers wrap every model call: runtime, tools, governance, evaluation, memory, evolution,
and (roadmap) subagents. That harness — not the model — is the durable advantage.

## What's proven today

- **Runs end-to-end, offline, deterministically:** one command, no API key, reproducible.
- **Governance you can see:** the **evidence gate is fail-closed** — ARIA *withholds* KPI/CI-CD
  answers it can't support, rather than guessing.
- **Measures itself:** a typed **Work Ledger** computes ROI directly — completion, approval rate,
  failure rate, cost-per-task, corrections, model usage.
- **Tested:** `1021 automated tests passing` (1 skipped).
- **Governed self-improvement pipeline:** propose → sandbox → approve → canary → rollback.

## What's honestly *not* done

- Fine-tuning is an **offline prototype** — **no model was trained or deployed**.
- **No vLLM serving**, no production model-router wire-up.
- Jira/Teams writes in the demo are **mocks**; live connectors need credentials (V2).
- Subagents, multi-tenant AaS, and the eight §28.4 capabilities are **roadmap**.

## The moat (why six months matters)

Every governed, logged task compounds into **institutional memory** — approvals, corrections,
outcomes, risk patterns — that a competitor starting today cannot replicate. The Work Ledger is
that asset, accumulating from day one.

## Positioning vs Yukti

Yukti is the **organisational operating model**; ARIA is the **execution-intelligence layer**.
Complementary, not competing — ARIA strengthens the vision with memory, governance, evaluation,
and ROI proof.

## The ask

1. Approve an **internal pilot** scope and an expanded skill set.
2. Make an **employer/IP decision** before any public publication.
3. Decide the V2 priorities: live connectors, vLLM serving, real fine-tuning.

---

*Detail: [week30_truth_and_claim_audit.md](week30_truth_and_claim_audit.md) ·
[week30_architecture_summary.md](week30_architecture_summary.md) ·
[week30_final_proof_checklist.md](week30_final_proof_checklist.md)*
