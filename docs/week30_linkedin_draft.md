# Week 30 — LinkedIn Draft (Hold for Approval)

DRAFT ONLY. **Do not post** until employer/IP approval is confirmed and the Public-Safety Audit
pre-publication checklist is fully ✅. Genericize employer/KPI names unless naming is approved.

**Status:** Awaiting Codex Launch-Readiness Audit.

---

## Version A — the "harness" post (recommended)

> For the last few months I've been building something quietly: **ARIA** — a governed
> AI-employee platform.
>
> The lesson that shaped it: **Claude gives intelligence. ARIA gives governed work ownership.**
>
> Anyone can call an LLM. The hard part — and the real product — is everything *around* the
> model. I call it Harness Engineering:
>
> 🔹 Runtime — durable, resumable execution (LangGraph)
> 🔹 Tools — typed, dry-runnable, idempotent, audited
> 🔹 Governance — action tiers + approval gates + a fail-closed evidence gate (it *refuses* to
>    answer when it can't cite evidence)
> 🔹 Evaluation — rubrics + regression
> 🔹 Memory — a typed Work Ledger that computes ROI directly
> 🔹 Evolution — propose → sandbox → approve → canary → rollback (never autonomous)
>
> It runs end-to-end **offline and deterministically**, with **1021 automated tests passing**.
>
> What it is *not*: not autonomous, not a deployed fine-tuned model, not a magic box. Fine-tuning
> is an offline prototype. Every production action waits for a human.
>
> **ARIA is built using Harness Engineering: the model is only one component; the real
> intelligence comes from orchestration, memory, tools, governance, evaluation, workflows, Work
> Ledger, ROI measurement, and safe execution around the model.**
>
> More soon. 👇

## Version B — the short hook

> Built a governed AI employee, not a chatbot.
>
> **Claude gives intelligence. ARIA gives governed work ownership.**
>
> Seven harness layers around the model. Runs offline, 1021 tests green, and it *withholds*
> answers it can't back with evidence. Not autonomous — every production action waits for a human.
>
> The model is the smallest part. The harness is the product.

---

## Pre-post checklist (all must be ✅)
- [ ] Employer/IP approval to publish obtained
- [ ] Employer name + real KPI figures genericized (or naming explicitly approved)
- [ ] No internal hostnames, secrets, or screenshots with paths/keys
- [ ] "Yukti" framing removed from public copy
- [ ] Claims cross-checked against [week30_truth_and_claim_audit.md](week30_truth_and_claim_audit.md)
- [ ] Note added (if screenshots used): test fixtures contain intentional fake secrets

## Comment-section answers (pre-written, honest)
- *"Is it autonomous?"* → "No, by design. It proposes; a human approves; then it acts."
- *"Did you fine-tune a model?"* → "Prototype only — offline dry-run. Nothing trained or deployed."
- *"Stack?"* → "LangGraph + LangChain, Pydantic-typed skills, a typed Work Ledger, governed
  evolution. Claude as the default model."
