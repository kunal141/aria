# ARIA V3 — Goal-Driven Self-Learning AI Employee Workforce

**Status:** Planning / vision document only. **No V3 code exists.** Nothing in this
document is implemented. It defines direction so that future work has clean attach
points and a governed shape.

**Provenance:**
- V2 (Internal AI Employee Pilot) is **complete** and merged into `master` at merge
  commit `5632260`; the V2 final endpoint is `a6f579d`, tagged `aria-v2-internal-pilot`.
- V2 proves: governed chat, approved domain memory, cited recall, read-only PR/CI/
  analytics pilots, workspace artifacts, draft-only actions, Work Ledger tracing,
  offline-by-default execution, and fixture-first connectors.
- **V3 has not started.** This is the plan, not the build.

---

## 0. Framing and guardrails (read first)

ARIA is **not** conscious and **not** emotionally self-aware. Any "self" language in
this document means exactly one thing:

> **ARIA has operational self-awareness: it can inspect its goals, memory, skills,
> permissions, work history, failures, gaps, and improvement opportunities.**

That is introspection over its own operating state — not sentience, not feelings,
not independent will.

Non-negotiable principles carried forward from V1/V2 and binding on all of V3:

- **Self-learning is governed.** ARIA may *learn* continuously, but what it learns
  only becomes authoritative through approval.
- **Self-evolution is approval-gated.** ARIA may *propose* new skills, prompts,
  routines, and agents; a human approves before anything activates.
- **World awareness is source-cited and policy-controlled.** External knowledge is
  always attributed and is never treated as company truth without approval.
- **Sensitive information requires real authorization.** V3 must add an actual
  identity + authorization layer before any sensitive scope is unlocked. Until then,
  sensitive content is refused, exactly as in V2.
- **Live writes require future explicit approval policies.** No external write,
  ticket, message, deploy, or DB mutation happens without a written, approved policy
  and a human/role authorization at execution time.
- **No uncontrolled autonomy.** Every level of execution is bounded by permission,
  cost, time, evidence, and audit.
- **No public release without employer/IP approval.** Publication remains blocked.

---

## 1. V3 North Star

> **ARIA should become a governed AI employee that can understand a business goal,
> create a roadmap, coordinate people and agents, execute approved work, produce
> complete deliverables, learn from feedback, evolve skills safely, and report
> outcomes with evidence and ROI.**

The shift from V2 to V3 is the shift from *"answers a request, read-only, draft-only"*
to *"owns a goal end-to-end under governance."* The model is still the smallest part;
the harness — runtime, memory, tools, governance, evaluation, evolution, and now a
workforce of specialist agents — is the product.

---

## 2. Difference between V2 and V3

| Dimension | V2 (complete) | V3 (planned) |
|---|---|---|
| Unit of work | A request / a turn | A **goal** owned end-to-end |
| Planning | None (single turn) | Problem statement → roadmap → task board |
| Cadence | Interactive only | **Scheduled routines** + interactive |
| Agents | None (single orchestrator) | **Dynamic specialist workforce** (created on demand) |
| Collaboration | Human approves a proposal | Human **and** agent collaboration with clarifying questions and handoffs |
| Capability change | Fixed skill set | **Skill evolution** (propose → sandbox → approve → activate → monitor → rollback) |
| External knowledge | None | **World awareness** (source-cited, relevance-scored) |
| Connectors | Fixtures-first, read-only | Fixtures-first **plus** controlled live execution **only after** approval policies |
| Outputs | Draft-only, no external writes | Graduated execution levels (read → draft → approval-record → limited approved writes → scheduled approved routines → delegated-with-limits) |
| Execution mode | Offline-by-default | Offline-by-default; cloud/live strictly opt-in and policy-gated |

Everything V2 enforces (evidence gate, draft-only default, approval-as-decision,
sensitive refusal, redaction, audit outbox, offline default) **remains in force**.
V3 only *adds* capability behind *stronger* governance — never by loosening V2.

---

## 3. Work Ownership Engine

The core V3 loop. ARIA takes a vague request and carries it to an evidenced,
approved, ROI-reported outcome:

```text
vague request
→ problem statement
→ goal
→ success criteria
→ roadmap
→ tasks
→ evidence needed
→ skills/agents needed
→ execution plan
→ deliverables
→ approval
→ final outcome
→ memory update
→ ROI report
```

Each arrow is a governed transition with a Work Ledger trace and a `correlation_id`
that ties the whole goal together (the V2 ledger already carries `correlation_id` and
`actor`, so this attaches with no schema migration). No transition that produces an
external effect proceeds without the approval gate.

---

## 4. Goal Intake Engine

ARIA converts vague requests into structured, governed goals before any work starts.

**Worked example.** User says:

> "Our notification CTR is dropping. Own this."

ARIA produces a structured goal brief:

- **Problem statement** — Notification CTR has declined over a defined window;
  scope, surfaces, and segments affected are to be confirmed.
- **Goal** — Diagnose the CTR decline and propose evidenced remediation.
- **Success metrics** — e.g. CTR recovery target, confidence threshold, and a
  measurable check (defined with the stakeholder, not assumed).
- **Constraints** — read-only by default; no production writes without approval;
  data-privacy scope.
- **Stakeholders** — Analytics lead, Product owner, Notifications/Eng owner.
- **Data needed** — notification events, delivery logs, taxonomy of event types,
  segment dimensions.
- **Timeline** — first findings vs. full diagnosis milestones.
- **First questions** — which surfaces/segments, which date window, what counts as
  "recovered," any recent releases to consider.
- **Roadmap** — investigation → hypothesis → evidence → recommendation → draft
  actions → approval.

The goal brief is itself an artifact: typed, versioned, stored in a workspace, and
approvable. Ambiguity is surfaced as clarifying questions, never silently resolved.

---

## 5. Dynamic Agent Army / Workforce

When a goal needs specialist work, ARIA may **create specialist agents on demand**
under governance (built on the documented Subagent Instruction Engine, §28.1 of the
project plan, and run by an Agent Control Plane).

**Example specialists:**

- Data Freshness Agent
- Event Taxonomy Agent
- PR Review Agent
- CI/CD Investigator Agent
- Recommendation Analyst Agent
- Jira Drafting Agent
- Manager Summary Agent
- World Research Agent
- Skill Builder Agent

**Every agent is a typed, bounded brief** with these required fields:

| Field | Purpose |
|---|---|
| `role` | The specialist function |
| `objective` | What it must produce |
| `allowed_context` | Memory / docs / artifacts it may read |
| `forbidden_context` | Explicit exclusions (PII, other teams' data) |
| `allowed_tools` | The exact tool subset it may call |
| `forbidden_tools` | Tools it must never touch |
| `time_limit` | Hard wall-clock ceiling |
| `cost_limit` | Hard token/cost ceiling |
| `approval_requirement` | Whether its output needs human sign-off before use |
| `output_schema` | The typed schema its output must validate against |
| `work_ledger_trace` | Correlation ID under which all its events are logged |
| `kill_switch` | A control to terminate a runaway/over-budget agent |

**Governance rules (binding):** agents inherit **only explicitly delegated**
permissions — never the parent's full scope, never self-expanding; agents cannot
execute live/high-risk tools directly; every agent prompt and output is logged; any
risky proposed action escalates to human approval; outputs are evaluated against the
brief's rubric before being merged.

---

## 6. Skill Evolution Engine

How ARIA safely grows new capability:

```text
detect repeated gap
→ propose new skill
→ generate skill spec
→ generate tests
→ sandbox implementation
→ evaluate before/after
→ human approval
→ activate
→ monitor
→ rollback if bad
```

**Hard rules:**

- ARIA **cannot silently modify production behavior.** Activation is a human,
  approval-gated step.
- **New skills require tests** (golden examples + failure cases + a rubric) and an
  evaluation that compares before/after.
- **Unsafe skills are blocked** (constitutional checks, permission scope, evidence
  discipline) and never reach activation.
- **All evolution is logged** — proposal, spec, tests, sandbox result, approval,
  activation, monitoring, and any rollback — under the Work Ledger.
- Skills remain **typed, versioned contracts** (Pydantic in/out), consistent with the
  platform rule that a skill without a schema is not a skill.

---

## 7. World Awareness Engine

ARIA monitors a **selected, policy-controlled** set of external sources and turns
changes into governed proposals — never into silent truth.

**Sources (allowlisted):**

- AI model releases
- OpenAI / Anthropic / Databricks / MLflow / LangGraph updates
- research papers
- security advisories
- engineering best practices
- relevant industry trends

**For each signal, ARIA must:**

- **summarize what changed**
- **cite sources** (provenance on every claim)
- **score relevance** to ARIA's and the company's work
- **propose** roadmap / skill updates (proposals only)
- **never treat world knowledge as company truth without approval**

World knowledge lives in a clearly separated, source-attributed store. It can inform
proposals and questions; it cannot override approved company/domain memory and cannot
satisfy the evidence gate for a company metric on its own.

---

## 8. Team Interaction Layer

Other teams interact with ARIA like a virtual teammate, each within a scoped,
permissioned surface.

**Teams may include:** Editorial, Product, Engineering, Analytics, SEO, Growth,
Astrology / MyJyotish, Management.

**Per-team support:**

- team-specific workspaces
- scoped memory (a team sees only what it is authorized to see)
- role-based permissions
- team-facing progress updates
- approval requests
- draft reports
- clarification questions
- handoff summaries

Scoping is enforced by the authorization layer (§13), not by convention. A team's
memory and artifacts are isolated by scope and role.

---

## 9. Human and Agent Collaboration Layer

ARIA can request missing context from **humans or agents**, and treats both as
first-class, logged collaborators.

**Examples:**

- ask the **Analytics lead** to confirm event taxonomy
- ask the **Product owner** for success criteria
- ask the **CI Agent** to inspect failing logs
- ask the **PR Agent** to review code
- ask the **Research Agent** to summarize an external trend
- ask the **Manager** for approval before any external write

**Rule:** every collaboration request and response is logged (who/what was asked, why,
the correlation ID, and the outcome). A human's answer is attribution-checked; an
agent's answer is evaluated against its brief before it is used.

---

## 10. Scheduled Routines / Work Loops

V3 adds **governed recurring work** in addition to interactive work.

**Planned routines:**

- daily KPI anomaly scan
- hourly CI health check
- new PR review scan
- daily AI / news / research watch
- weekly manager progress report
- nightly backlog review
- product feedback summarization

**Rules:**

- scheduled work is **governed** (same gates as interactive work)
- **costs are capped** per routine and per period
- **failures escalate** (with cooldowns and escalation levels)
- **external writes are blocked** unless an approved policy authorizes them
- **every routine has a Work Ledger trace** and a clear owner

---

## 11. Controlled Live Execution

V3 must reach live action **gradually**, never by jumping to uncontrolled writes.

| Level | Capability |
|---|---|
| **Level 1** | Read-only investigation |
| **Level 2** | Draft-only actions |
| **Level 3** | Approval records only |
| **Level 4** | Limited approved writes |
| **Level 5** | Scheduled approved routines |
| **Level 6** | Delegated execution with policy limits |

V2 today operates at **Levels 1–3**. Each step up requires: a written policy, an
authorization model, evidence discipline, cost/time caps, a kill switch, rollback,
and audit. **V3 must not jump directly to uncontrolled live writes.** Levels 4–6 are
unlocked one at a time, each behind its own approval policy.

---

## 12. The Seven Brains of ARIA

A conceptual decomposition of the V3 harness (each "brain" maps to existing harness
layers and pillars — this is architecture framing, not new mysticism):

1. **Goal Brain** — understands goals and problem statements; runs Goal Intake (§4)
   and the Work Ownership loop (§3).
2. **Memory Brain** — stores approved institutional / domain knowledge; versioned,
   cited, scoped (extends V2 domain memory).
3. **World Brain** — monitors external changes; source-cited and relevance-scored
   (§7).
4. **Skill Brain** — detects capability gaps and proposes new skills under the
   evolution gate (§6).
5. **Agent Brain** — creates and supervises specialist agents within typed, bounded
   briefs (§5).
6. **Governance Brain** — controls identity, permissions, approvals, risk, cost,
   audit, and rollback (§13); it sits in front of everything.
7. **Execution Brain** — gets approved work done through tools and workflows at the
   permitted live-execution level (§11).

The Governance Brain is supreme: no other brain can bypass it.

---

## 13. Governance Requirements

V3 is only acceptable if **all** of the following are present and enforced
structurally (in code, with tests), not merely documented:

- **identity and authorization** (a real layer — the prerequisite for sensitive
  scopes and live writes)
- **scoped memory** (team/role isolation)
- **sensitive memory controls** (refused without proven authorization)
- **approval gateway** (every external effect passes through it)
- **cost / time limits** (per task, per agent, per routine)
- **kill switch** (terminate any agent/routine)
- **audit trail** (immutable, complete)
- **Work Ledger** (every event, every correlation)
- **evidence gate** (claims/counts require evidence; memory explains, it does not
  fabricate)
- **rollback** (every change is reversible)
- **no raw secrets** (never stored, never logged, never returned)
- **no raw exception leakage** (class/code only on surfaces that return or persist
  errors)

These are the same disciplines V2 enforces, scaled up to a workforce, scheduled work,
and graduated live execution.

---

## 14. Roadmap

Staged milestones, each independently shippable and independently governed. Do them
in order; each gates the next.

| Milestone | Scope |
|---|---|
| **V3.1** | Goal Intake + Problem Statement Engine |
| **V3.2** | Roadmap Planner + Task Board |
| **V3.3** | Work Ownership Loop |
| **V3.4** | Dynamic Agent Workforce |
| **V3.5** | Skill Evolution Engine |
| **V3.6** | World Awareness Engine |
| **V3.7** | Team Collaboration Layer |
| **V3.8** | Scheduled Routines |
| **V3.9** | Controlled Live Execution (Levels 4→6, one at a time) |
| **V3.10** | Manager Dashboard + ROI |

Identity/authorization (§13) is a **prerequisite woven across V3.1–V3.4** and is hard
required before V3.9.

---

## 15. Must Not Claim

This document, and any future V3 work, must **never** claim:

- ❌ consciousness
- ❌ emotional self-awareness
- ❌ unrestricted autonomy
- ❌ uncontrolled self-modification
- ❌ live writes without approval
- ❌ production deployment
- ❌ public release
- ❌ multi-tenant SaaS readiness
- ❌ external-agent runtime already implemented

"Self-awareness" here means **operational introspection only** (§0). Everything in
this document is **planning**; **no V3 capability is built**, and V3 implementation
**has not started**.

---

## Cross-references

- V2 acceptance + boundaries: [`V2_CODEX_ACCEPTANCE_PACKAGE.md`](V2_CODEX_ACCEPTANCE_PACKAGE.md), [`V2_SAFETY_AND_BOUNDARY_AUDIT.md`](V2_SAFETY_AND_BOUNDARY_AUDIT.md)
- Earlier future-architecture vision: [`V3_ROADMAP_META_HARNESS.md`](V3_ROADMAP_META_HARNESS.md)
- Project plan future layers: `CLAUDE.md` §28 (Subagent Instruction Engine, Agentic AI Roadmap), §26 (seven harness layers), §14 (governed self-evolution)
