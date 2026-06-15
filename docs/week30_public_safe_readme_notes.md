# Week 30 — Public-Safe README Notes

Guidance for a **public** README, should employer/IP approval be granted. This is **notes**,
not the published README. Until approval, ARIA stays internal (see the Public-Safety Audit).

**Status:** Week 30 Launch Readiness ACCEPTED by Codex (2026-06-15). Week 30 complete.

---

## What a public README may safely say

- ARIA is a **governed AI-employee platform** built with **Harness Engineering**.
- Tagline: *Claude gives intelligence. ARIA gives governed work ownership.*
- Thesis (verbatim, safe to publish): *ARIA is built using Harness Engineering: the model is
  only one component; the real intelligence comes from orchestration, memory, tools,
  governance, evaluation, workflows, Work Ledger, ROI measurement, and safe execution around
  the model.*
- It runs an offline, reproducible demo: `cd apps/backend && uv run python -m aria.demo.golden_path`.
- Test suite: `1027 passed, 1 skipped`.

## What a public README must NOT say
- ❌ "All 24 pillars functional" · ❌ "fully autonomous" · ❌ "operational self-evolution"
- ❌ "production fine-tuned model" / "trained on our data" · ❌ "vLLM serving" / "deployed"
- ❌ live Jira/Teams writes · ❌ named internal systems or real KPI figures
- Use the ✅/❌ table in [week30_truth_and_claim_audit.md](week30_truth_and_claim_audit.md).

## Required genericization before publishing
1. Replace `jira.amar-ujala.internal` → `jira.example.internal` (mock URLs only).
2. Replace the employer name and specific KPI examples with neutral equivalents
   (e.g. "a large media organization", "content CTR") **unless** approval to name them is given.
3. Drop the "Yukti" competitive framing from public copy.
4. Add a one-line note that test files include **intentional fake secrets** to exercise the
   redaction layer (so scanners' flags are expected).

## Suggested public README skeleton

```
# ARIA — a governed AI-employee platform (Harness Engineering)
> Claude gives intelligence. ARIA gives governed work ownership.

## What it is
A LangGraph-based harness around an LLM: runtime, tools, governance, evaluation,
memory/Work Ledger, evolution, and (roadmap) subagents. The model is one component.

## Run the offline demo (no API key)
cd apps/backend && uv sync && uv run python -m aria.demo.golden_path

## What's built vs roadmap
See docs/week30_truth_and_claim_audit.md and docs/week30_v1_v2_v3_boundary.md.

## Status
V1 platform with a built skill set + Work Ledger + ROI + governed evolution pipeline.
Fine-tuning is an offline prototype. No deployment, no vLLM, no autonomous self-modification.

## License / use
<employer-approved terms>
```

## Publication gate
Do **not** publish until every box in the Public-Safety Audit pre-publication checklist is ✅,
including explicit employer/IP approval.
