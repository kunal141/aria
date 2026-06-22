# ARIA V3 — Boundaries & Non-Goals (binding)

> **Status: governance boundary document.** These boundaries are enforced in code
> (with tests) across V3.1–V3.10 and remain in force. V3.10 is **visibility, control,
> proof, ROI, and acceptance — not more autonomy.**

A manager should be able to inspect ARIA like an employee: what it worked on, what it
learned, what it needs, what it risks, and what value it produced — while ARIA stays
strictly inside the boundaries below.

## What V3 IS

- A governed AI-employee **platform pilot**, local and offline-by-default.
- Goal ownership → planning → governed (dry-run) agents → skill-evolution proposals →
  work memory + fixture-only world awareness → draft-only collaboration → local
  deterministic routines → a deny-by-default controlled action gate → a read-only
  manager dashboard with estimated ROI and an offline end-to-end proof.

## What V3 is NOT (binding non-goals)

V3 must **never** (and does not):

- perform a **real production deployment** or public release;
- become **multi-tenant** SaaS;
- make **real connector writes** or real Teams / Slack / Gmail / Jira / GitHub /
  webhook writes;
- do **uncontrolled live monitoring** or open-web browsing/crawling;
- run **external runtime adapters**, Claude Managed Agents, `launch-your-agent`, MCP
  execution, or Docker/REST/CLI external agents;
- perform **live action execution** (V3.9 runs dry-run / internal-mock only; `live`
  mode is disabled and store-enforced);
- **auto-approve**, **auto-execute**, or **auto-activate** a skill;
- **self-modify** production code, or use **hidden cloud** resources;
- claim consciousness, emotional self-awareness, or unrestricted autonomy.

## Governance invariants (enforced in code)

- **Deny-by-default** for external actions; external targets are blocked from live/mock
  execution (dry-run preview only).
- **Approval is bound** to an action's id + payload hash + scope; a changed payload,
  widened scope, or expiry invalidates it (re-approval required).
- **Execution status is receipt-backed**: an action reaches `executed`/`failed` only
  through the governed path, never via a forged store call.
- **Source-cited memory & summaries**: no orphan lessons, no invented dashboard/risk
  facts; missing evidence is shown explicitly.
- **Secrets** are masked / structural-secret refs rejected at every store boundary;
  **no raw exception text** is persisted or surfaced.
- **`ARIA_USER_ID` is attribution only**, never authorization.
- Every state change is **Work-Ledger audited** through a transactional outbox.

## Publication boundary

Public GitHub / LinkedIn publication remains **BLOCKED pending employer/IP approval**.
All V3 artifacts are internal-pilot drafts only.

*Cross-references: [`V3_FINAL_ACCEPTANCE_CHECKLIST.md`](V3_FINAL_ACCEPTANCE_CHECKLIST.md),
[`V3_FINAL_PROOF_DEMO.md`](V3_FINAL_PROOF_DEMO.md),
[`V3_GOAL_DRIVEN_SELF_LEARNING_AI_EMPLOYEE_WORKFORCE.md`](V3_GOAL_DRIVEN_SELF_LEARNING_AI_EMPLOYEE_WORKFORCE.md).*
