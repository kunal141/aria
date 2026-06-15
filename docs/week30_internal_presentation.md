# Week 30 — Internal Presentation (Reveal Deck Outline)

Audience: engineering leadership + the manager (Yukti context). Tone: confident, measured,
zero exaggeration. ~10 slides. Every slide maps to evidence in the Truth & Claim Audit.

**Status:** Week 30 Launch Readiness ACCEPTED by Codex (2026-06-15). Week 30 complete.

---

### Slide 1 — Title
**ARIA — a governed AI employee for engineering.**
Subtitle: *Claude gives intelligence. ARIA gives governed work ownership.*

### Slide 2 — The distinction
- Not a chatbot. Not a copilot. Not uncontrolled autonomy.
- An AI **employee**: receives goals, does engineering work, reports outcomes, and
  **never reaches production without human approval.**
- The platform is the product; ARIA is the **first employee** built on it.

### Slide 3 — Harness Engineering (the thesis)
> *ARIA is built using Harness Engineering: the model is only one component; the real
> intelligence comes from orchestration, memory, tools, governance, evaluation, workflows,
> Work Ledger, ROI measurement, and safe execution around the model.*

Seven layers: runtime · tools · governance · evaluation · memory · evolution · subagent/workflow.

### Slide 4 — Live demo (the centerpiece)
Run `uv run python -m aria.demo.golden_path`. Narrate per
[week30_demo_script_3min.md](week30_demo_script_3min.md). Key beats:
- real routing → real skills → artifacts
- **evidence gate withholds** unsupported KPI/CI-CD claims (governance you can see)
- approval granted / rejected / failure / **rollback** — **seeded** typed events (say so):
  the live graph emits only the terminal event today, so Stage 2 *seeds* the governed
  lifecycle with the real v2 event classes to show what the ledger records and the metrics count

### Slide 5 — The Work Ledger & ROI
- The ledger is 15 typed, queryable event classes; ROI is computed directly off them.
- **Honest scope:** the production graph auto-emits the terminal event per task today; the full
  per-event taxonomy is exercised by the demo's seeded lifecycle, tests, and the ledger API
  (per-event live emission is a documented V2 Partial).
- ROI computed directly: completion, approval rate, failure rate, cost/task, corrections,
  model usage. Deterministic numbers from the demo (live + seeded events).
- This is the moat: 6 months of governed, logged work = institutional memory.

### Slide 6 — Governance & safety (why leadership can trust it)
- Action Tiers T1–T3 in V1; T4 behind explicit approval; T5 not enabled.
- Evidence gate is **fail-closed**. Privacy layer redacts/reject secrets at the type boundary.
- Governed self-improvement: propose → sandbox → approve → canary → **rollback**. Never autonomous.

### Slide 7 — What's built vs what's next (radical honesty)
- **Built:** runtime, skills (PR/KPI/CI-CD/Jira/QA), Work Ledger v2, ROI, governance,
  evidence gate, memory, RAG, evolution pipeline, model registry. `1027 tests pass`.
- **Prototype:** fine-tuning pipeline (offline dry-run; **no model trained or deployed**).
- **Roadmap (V2/V3):** vLLM serving, real fine-tuning, live connectors, subagents, multi-tenant AaS.
- Pull this straight from [week30_truth_and_claim_audit.md](week30_truth_and_claim_audit.md).

### Slide 8 — Yukti positioning (complement, not competition)
- "Yukti is the organisational operating model. ARIA is the execution-intelligence layer.
  Together they're stronger."
- ARIA strengthens the vision with memory, governance, evaluation, and ROI proof.

### Slide 9 — The career/skill story
- One engineer designed a full harness from first principles: orchestration, memory, tools,
  governance, evals, model routing, work ledger, ROI. (See `week30_resume_bullets.md`.)

### Slide 10 — Ask / next steps
- Internal pilot scope, approval to expand the skill set, and an employer/IP decision before
  any public publication (per the Public-Safety Audit).

---

## Presenter guardrails (read before presenting)
- Say "prototype" for fine-tuning. Say "governed pipeline," not "operational self-evolution."
- If the demo terminal misbehaves, fall back to the captured expected output in
  [week30_golden_demo.md](week30_golden_demo.md) — the numbers are deterministic.
- Never claim live Jira/Teams writes, vLLM, or a trained model.
