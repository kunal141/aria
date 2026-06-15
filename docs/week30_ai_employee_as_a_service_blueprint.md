# Week 30 — AI Employee as a Service (AaS) Blueprint

Forward-looking **blueprint** for how the platform could become a multi-tenant service
(Pillar 23). This is **V3 vision / documentation only** — **nothing here is built in V1**, and
none of it is to be implemented as part of Week 30. Recorded so today's design leaves clean
attach points.

**Status:** Week 30 Launch Readiness ACCEPTED by Codex (2026-06-15). Week 30 complete. (This remains a V3 vision doc, not an implemented system.)

---

## The thesis

The product is not a model and not a single agent — it's the **harness**. Tenants can swap
models; the harness is the moat.

> ARIA is built using Harness Engineering: the model is only one component; the real
> intelligence comes from orchestration, memory, tools, governance, evaluation, workflows, Work
> Ledger, ROI measurement, and safe execution around the model.

AaS sells the **harness as a service**: each customer gets governed AI employees that learn their
context, under their approval, with their ROI measured.

## What's reusable today (the foundation AaS would build on)

| Today (V1, built) | Becomes (AaS, V3) |
|---|---|
| Skill registry + typed contracts | Per-tenant skill catalog |
| Work Ledger v2 (typed, ROI) | Per-tenant ledger + billing/usage metering |
| Governance + action tiers + evidence gate | Per-tenant policy + approval routing |
| Evolution pipeline + Model Registry | Per-tenant governed self-improvement |
| Offline deterministic demo | Per-tenant sandbox / trial |

## What AaS additionally requires (all V3 — NOT built)

1. **Multi-tenancy & isolation** — per-tenant data, memory, ledger, secrets; hard isolation
   boundaries; no cross-tenant retrieval.
2. **Identity & delegated authorization** (§28.4 #1) — typed auth envelopes; tenants and
   subagents inherit only explicitly delegated scopes.
3. **Private deployment option** — VPC/on-prem so sensitive code/data never leaves the tenant.
   Pairs with the vLLM serving roadmap for self-hosted models.
4. **Usage & billing layer** — metering off Work Ledger events (tasks, tokens, cost) → invoices.
5. **Tenant onboarding** — repo-config compatibility (§28.4 #8: read `AGENTS.md`/`CLAUDE.md`),
   knowledge-vault ingestion, skill enablement.
6. **Security gateway** (§28.4 #6) — prompt-injection detection, output-leakage scanning,
   data-exfiltration checks at the tenant boundary.
7. **Per-tenant evaluation** — episode packages (§28.4 #7) for audit, replay, and SLA grading.

## Phasing (illustrative, not committed)

- **V1 (done):** single-org, single-employee, governed, offline-provable.
- **V2:** live connectors, vLLM serving, real fine-tuning, subagent engine — still single-tenant.
- **V3:** multi-tenant isolation, billing, private deployment, security gateway → true AaS.

## Guardrails carried into AaS (non-negotiable)

- Governance before autonomy — always.
- Fail-closed evidence gate per tenant.
- Human approval for any production action; rollback always retained.
- No tenant data in training/datasets/logs without explicit, scoped consent.

## Why this is credible rather than hand-wavy

The V1 platform already carries the seams AaS needs: `correlation_id` + `actor` on every ledger
event, typed skill contracts, a file-backed registry pattern, and a governance layer that is
structural (not documentation). AaS is an **extension of these seams**, not a rewrite.

---

*Attach-point references: §22 (Marketplace), §23 (AaS), §28.1 (Subagent Engine), §28.4 (eight
future capabilities). Boundary: [week30_v1_v2_v3_boundary.md](week30_v1_v2_v3_boundary.md).*
