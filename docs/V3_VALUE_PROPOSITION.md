# ARIA V3 — Value Proposition

> Business value summary. Private internal pilot. Public release blocked pending
> employer/IP approval; V4 not started.

## What ARIA V3 proves

- An AI system can **own a business goal end to end** — intake → roadmap → task board →
  specialist agents → governed execution → drafts → routines → controlled actions →
  manager dashboard + ROI — **under governance the whole way**.
- **Governed autonomy is real and testable**: deny-by-default action gate, payload-bound
  approval, proposal-only skills, draft-only communication, fixture-only world awareness,
  source-cited memory, immutable Work Ledger. 371 focused V3 tests; 1577 backend tests.
- **The runtime is swappable; the governance layer is the moat.** External agent
  runtimes can plug in later as workers without us losing control.

## What it does NOT yet do (honest boundaries)

- No **real** external writes (Teams/Slack/Gmail/Jira/GitHub/webhook) — V3.9 is dry-run /
  internal-mock only; live execution is disabled.
- No live web monitoring (world awareness is fixture-only); no cron/daemon (routines are
  local + deterministic).
- No external runtime adapters yet (Claude Managed Agents / launch-your-agent / MCP /
  Docker/REST agents are V4 roadmap, documentation-only today).
- No multi-tenant SaaS, no deployment, no public release, no fine-tuned model in the loop.
- Not conscious, not unrestricted, not self-modifying — "self-awareness" means
  operational introspection only.

## Why it is defensible

- **Institutional memory + Work Ledger** accumulate from day one and aren't transferable.
- **Governance depth** — action tiers, approval gates, payload-hash binding, receipt-
  backed execution, structural-secret rejection — is the hard part most agent demos skip.
- **Source-cited everything** — lessons, risks, ROI claims must cite evidence; the store
  itself rejects fabricated proof/ROI.
- **Breadth at production discipline** — ten governed subsystems under one audit + policy
  contract, not a single flashy capability.

## Why it is different from Claude Managed Agents / launch-your-agent

| | Managed agent runtime / launch-your-agent | ARIA V3 |
|---|---|---|
| Creates/runs agents fast | ✅ | uses them as workers |
| Goal ownership end-to-end | — | ✅ |
| Approval gate bound to action + payload | — | ✅ |
| Institutional memory + reusable lessons | — | ✅ |
| Immutable Work Ledger + ROI | — | ✅ |
| Governs *which* agents may exist + how they're evaluated | — | ✅ |

> Anthropic can provide managed agent runtime. ARIA provides governed work ownership.

## Why governance matters

Enterprises don't fail to adopt AI because models are weak — they hesitate because they
can't **trust, audit, approve, or roll back** what the AI does. ARIA makes autonomy
*adoptable*: every action is previewable, approvable, reversible, audited, and bounded.
That's what turns "interesting demo" into "thing a real org will run."

## What V4 can add later (roadmap, not started)

- External **runtime adapter layer** — Claude Managed Agents / launch-your-agent / MCP /
  REST / Docker / CLI agents as governed backends.
- **Live, allowlisted** source monitoring via scheduled routines (still governed).
- Graduated **controlled live execution** (Levels 4→6) behind written approval policies.
- An **Emerging Capability Radar** that maps new AI launches to adapter proposals.
- (All gated on governance, evaluation, and the employer/IP/publication boundary.)

## Who would use it

Internal teams that want accountable AI execution, not just AI answers — engineering,
analytics, product, and operations groups that need an auditable, approval-gated
assistant that *owns work* rather than reacting to prompts.

## Internal use cases (ARIA as a role-specialized employee)

- **AI product manager** — owns a goal, maintains the roadmap/task board, drafts updates.
- **AI analyst** — investigates a KPI/CTR drop, gathers evidence, drafts findings.
- **AI engineering assistant** — PR review prep, test-gap surfacing, CI/CD triage drafts.
- **AI newsroom operations employee** — content-pipeline / notification-CTR reviews
  (Amar Ujala media-tech), all draft-only.
- **AI personalization operations employee** — recommendation/feed health reviews.
- **AI astrology platform operations employee** — e.g. a MyJyotish-style ops assistant
  owning recurring operational reviews (draft-only, governed).
- **AI QA / release-readiness employee** — blocker digests, risk view, approval queue
  for a release.

In every case ARIA stays the governance, memory, approval, Work Ledger, and ROI layer —
the role changes, the control plane does not.

*Cross-references: [`V3_MANAGER_NARRATIVE.md`](V3_MANAGER_NARRATIVE.md),
[`V3_BOUNDARIES_AND_NON_GOALS.md`](V3_BOUNDARIES_AND_NON_GOALS.md),
[`EMERGING_CAPABILITY_RADAR_AND_ADAPTER_STRATEGY.md`](EMERGING_CAPABILITY_RADAR_AND_ADAPTER_STRATEGY.md).*
