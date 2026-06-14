# Week 30 — 3-Minute Demo Script

A tight, honest walkthrough for the reveal. Every claim here is backed by the Truth & Claim
Audit. Nothing is exaggerated. Total spoken time ≈ 3 minutes.

**Status:** Awaiting Codex Launch-Readiness Audit.

---

### 0:00–0:25 — The one line

> "This is ARIA. **Claude gives intelligence. ARIA gives governed work ownership.**
> It's not a chatbot and it's not autonomous — it's an AI employee that does engineering
> work, but never touches production without a human approving it. Let me show you, running
> live and fully offline — no API calls."

Open a terminal in `apps/backend`.

### 0:25–1:30 — One command, the whole loop

```bash
uv run python -m aria.demo.golden_path
```

As it runs, narrate the three stages:

- **"Real requests, real routing, real skills."** Point at Stage 1: a PR review produces an
  artifact; a Jira request produces a draft behind a T4 approval gate.
- **"Watch governance refuse to guess."** Point at the **KPI** and **CI/CD** lines:
  `[RESPONSE WITHHELD — UNSUPPORTED CLAIMS]`. "The evidence gate is fail-closed. When ARIA
  can't cite evidence, it refuses to answer — and it still files a proactive CI/CD alert."
- **"Every action is recorded."** Point at Stage 2: approval granted, approval rejected, a
  failure, and a **rollback** — all typed, governed events.

### 1:30–2:20 — The ROI it produces

Point at Stage 3 (the numbers are deterministic):

> "From those events, the Work Ledger computes ROI directly: 6 tasks completed, a 50%
> approval rate, a 14% failure rate it tracks honestly, one human correction captured as a
> learning signal, cost per task, and a model-usage breakdown. **This is the harness
> measuring itself.**"

### 2:20–2:50 — What it is (and isn't)

> "Under the hood that's seven harness layers — runtime, tools, governance, evaluation,
> memory, evolution, and workflow. **ARIA is built using Harness Engineering: the model is
> only one component; the real intelligence comes from orchestration, memory, tools,
> governance, evaluation, workflows, Work Ledger, ROI measurement, and safe execution around
> the model.**"

Be explicit about boundaries (builds trust):

> "To be clear: no model was fine-tuned for this, nothing is deployed, there's no vLLM
> serving, and the Jira/Teams writes are mocks. What you saw is real and reproducible —
> `1021 tests pass` and you can run that exact command yourself."

### 2:50–3:00 — Close

> "Six months of this, governed and logged, is institutional memory a competitor can't clone.
> That's ARIA."

---

## If asked "is it autonomous?"

> "No — deliberately. It proposes, a human approves, then it acts. The rejected-approval and
> rollback you just saw are the product working as designed."

## If asked "did it just call an API?"

> "No. The script strips every provider key and aborts if one is visible. It printed
> 'No paid API call, no network call' at the end. The skills ran on deterministic offline
> mocks."

## Backup commands (if asked for a specific slice)

```bash
uv run python -m aria.model_registry.demo   # governed register → approve → activate → rollback
uv run python -m aria.fine_tuning.demo       # offline dry-run; active model: NONE
```
