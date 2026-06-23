# ARIA V3 — Governed AI Employee Workforce

> **Audience: manager / leadership.** Business explanation of what ARIA V3 is and why
> it matters. Documentation only — private internal pilot. **Public release is blocked
> pending employer/IP approval; V4 has not started.**

## The one-line framing

**ARIA is a governed AI employee control plane** — not a chatbot, and not just an agent
launcher.

- An **AI assistant** answers a question.
- An **agent launcher** spins up an agent and hopes it behaves.
- **ARIA owns a goal end to end under governance**: it plans the work, coordinates
  specialist agents, learns from what happened, drafts the team communication, runs
  recurring routines, previews any real-world action behind an approval gate, and
  reports the value it produced — with a complete audit trail.

## What ARIA actually does (all proven in V3.1–V3.10)

| ARIA capability | Milestone |
|---|---|
| Turns a vague business goal into a problem statement, roadmap, and task board | V3.1 / V3.2 |
| Plans a **dynamic specialist agent workforce** (dry-run, bounded briefs) | V3.3 |
| **Supervises and governs** those agents (dependency, budget, quality, escalation) | V3.4 |
| Detects capability gaps and **proposes new skills** (proposal-only, never auto-activated) | V3.5 |
| Builds a **Work Memory Graph** of reusable lessons, watches approved sources (fixture-only) | V3.6 |
| Prepares **draft-only** manager updates, stakeholder questions, handoffs, approval requests | V3.7 |
| Runs **scheduled routines** (daily reviews, blocker digests) locally and deterministically | V3.8 |
| Previews and runs **controlled actions** behind a deny-by-default approval gate (dry-run / mock) | V3.9 |
| Produces a **manager dashboard + estimated ROI** and a deterministic end-to-end proof | V3.10 |

## The crucial distinction: governed autonomy

ARIA is not interesting because it is autonomous. It is interesting because it is
**autonomous under governance**:

- every external action is **deny-by-default** and runs only as dry-run / internal-mock
  (live execution is disabled and store-enforced);
- approval is bound to the exact action + payload + scope — a changed payload requires
  re-approval;
- nothing is sent, posted, emailed, or written to an external system;
- skills are **proposed**, never auto-activated; world knowledge is **advisory**, never
  treated as company truth;
- every step is recorded in an immutable **Work Ledger**, and memory/claims must cite
  their sources.

## Where Anthropic / OpenAI / MCP fit (workers, not replacements)

External agent runtimes — **Claude Managed Agents, `launch-your-agent`, the OpenAI
Agents SDK, MCP servers, REST/Docker agents** — can *later* become **workers/backends
under ARIA** (V4 roadmap). They do **not** replace ARIA. ARIA remains the layer that
provides **governance, memory, approval, the Work Ledger, policy, and ROI**.

> *Anthropic can provide managed agent runtime.*
> *ARIA provides governed work ownership.*

> *launch-your-agent may create agents quickly.*
> *ARIA decides which agents should exist, what they are allowed to do, how they are
> evaluated, and how their work is remembered.*

## What this means for the business

ARIA is the difference between *renting AI capability* and *employing it accountably*.
It lets us adopt any future agent runtime **without giving up control**: the runtime is
swappable; the governance, memory, audit, and ROI layer — the part that makes it safe
to trust — is ours.

*Cross-references: [`V3_VALUE_PROPOSITION.md`](V3_VALUE_PROPOSITION.md),
[`V3_DEMO_SCRIPT_5_MIN.md`](V3_DEMO_SCRIPT_5_MIN.md),
[`V3_FINAL_ACCEPTANCE_CHECKLIST.md`](V3_FINAL_ACCEPTANCE_CHECKLIST.md),
[`V3_BOUNDARIES_AND_NON_GOALS.md`](V3_BOUNDARIES_AND_NON_GOALS.md).*
