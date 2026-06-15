# Week 30 — V1 / V2 / V3 Boundary

The single source of truth for "what version is this?" Use it whenever a claim, a slide, or a
diagram could blur the line. Consistent with the Truth & Claim Audit.

**Status:** Week 30 Launch Readiness ACCEPTED by Codex (2026-06-15). Week 30 complete.

---

## V1 — Built and tested (what exists today)

- LangGraph runtime: intake → router → skill → evidence gate → respond.
- Skills: **PR review, KPI investigation, CI/CD triage, Jira drafting, QA / test review** — all
  typed (Pydantic in/out), offline-safe.
- **Fail-closed evidence gate** (KPI/CI-CD withhold unsupported claims).
- **Work Ledger v2** (15 typed events) + reader + **ROI metrics** + ROI Dashboard (frontend).
- Governance: **action tiers T1–T3 live; T4 behind explicit approval** (T5 off).
- Memory, RAG, code intelligence; CrewAI analytics/QA crew; Decision Intelligence (greedy).
- **Governed evolution pipeline** (propose → sandbox → approve → canary → rollback).
- **Model Lifecycle Registry v1**; **dataset export**.
- Proof: `1027 tests passing, 1 skipped`; offline deterministic demo.

## V1 — Prototype (built but explicitly not operational)

- **Fine-tuning pipeline** — offline dry-run only. **No model trained, no model deployed,
  active model = NONE.** Proves the shadow-learning pipeline; does not ship a model.

## V1 — Partial (exists, but not fully wired/operational)

- **Per-event ledger emission in the live graph** — today only terminal Responded/Failed events
  are auto-emitted by the production graph; the full event taxonomy is exercised by
  demos/tests/seeded data.
- **Jira/Teams** — drafting + proactive notification logic exists; **live writes are mocks**
  (need credentials → V2).
- **Model Router** — selects among API models; **not wired to a fine-tuned/self-hosted model**.

## V2 — Roadmap (designed, not built)

- **vLLM serving** (self-hosted, OpenAI-compatible) and **real fine-tuning + deployment**.
- **Live connectors:** Teams identity, Jira writes, CI/CD ingestion with real credentials.
- **§28.1 Subagent Instruction Engine** — typed delegation (attach points only today:
  `correlation_id` + `actor` already on every ledger event).
- **Model Router v3** routing stable/high-volume tasks to a fine-tuned specialist.
- **§26.8 Generative UI Canvas** (persistent workspaces).
- Parts of **§28.4**: agent identity/delegated auth, A2A-ready envelopes, AG-UI event stream,
  persistent workspaces, security gateway, episode packages, agent-config compatibility.

## V3 — Roadmap (vision)

- **Multi-tenant AI Employee as a Service** (Pillar 23) — isolation, billing, private/VPC deploy.
- **AI Capability Marketplace** (Pillar 22).
- **Agent branching / experiment paths** (§28.4 #5).
- Broad autonomous tiers (T4/T5 as routine) — **only** after trust + governance maturity.

---

## The bright lines (never blur these)

| Claim | Correct version label |
|---|---|
| "Fine-tuned model trained / deployed" | ❌ not V1 — **prototype only**, nothing trained/deployed |
| "vLLM serving live" | ❌ V2 roadmap |
| "Live Jira/Teams automation" | ❌ V1 mocks; **V2** for real writes |
| "Subagents / delegation" | ❌ V2 roadmap (attach points only) |
| "Multi-tenant / AaS" | ❌ V3 roadmap |
| "Autonomous self-modification" | ❌ never without human approval |
| "Governed evolution pipeline exists" | ✅ V1 (built) |
| "Work Ledger + ROI" | ✅ V1 (built) |
| "Evidence gate withholds unsupported claims" | ✅ V1 (built) |
| "1027 tests passing" | ✅ V1 (verified) |

---

*Cross-references: [week30_truth_and_claim_audit.md](week30_truth_and_claim_audit.md),
[week30_architecture_summary.md](week30_architecture_summary.md),
[week30_ai_employee_as_a_service_blueprint.md](week30_ai_employee_as_a_service_blueprint.md).*
