# V3 Roadmap: ARIA as AI Employee Meta-Harness

> **Status: DOCUMENTATION / ROADMAP ONLY — not implemented, not scheduled.**
> Nothing in this document is built in V2. It does **not** change Week 32 behavior
> and adds no code. It records a long-term V3 direction so that current V2 design
> choices leave clean attach points (see the cross-references in §"Where this
> attaches"). Do **not** begin any of this during Week 32 or V2.
>
> **Predecessor (unchanged):** V1 + V1.1 accepted; the V2 internal-pilot is in
> progress on branch `v2-complete-internal-ai-employee-pilot` (Week 31 local
> intelligence + Week 32 conversational orchestrator & domain memory committed).
> This note is additive documentation on top of that state.

---

## 1. The broadened scope

Today ARIA is framed as an **AI Employee Platform** — the infrastructure that runs
*one* governed AI employee (the AI Engineer) and can spawn role-specific siblings.
V3 broadens that scope: ARIA becomes an **AI Employee Meta-Harness / Agent Control
Plane** — the governed system that can create, run, monitor, approve, audit, and
improve **many** AI employees *and* external agents.

This is an evolution of, not a replacement for, the existing direction. It builds
directly on:

- the **seven harness layers** (CLAUDE.md §26.1) — runtime, tools, governance,
  evaluation, memory, evolution, and subagent/workflow;
- **Pillar 13 — Agent Factory** and **Pillar 15 — Agent Control Plane**;
- the **AI Work Ledger** (Pillar 16) with `correlation_id` + `actor` on every event;
- the **§28.1 Subagent Instruction Engine** and **§28.4 Agentic AI Roadmap**
  (delegated agent identity, A2A-ready envelopes, security gateway, episode
  packages, agent-config compatibility).

V3 generalizes those from *ARIA-internal subagents* to *any internal or external
agent*, governed as accountable workers.

---

## 2. Positioning

> *"ARIA is not only one AI employee. ARIA is the governed platform that can
> create, run, monitor, approve, audit, and improve many AI employees and external
> agents."*

> *"Databricks-style platforms govern agents as infrastructure. ARIA governs
> agents as employees doing accountable work."*

> *"Claude, Codex, Gemma, and future agents are workers. ARIA is the governed work
> system around them."*

The distinction is the moat: most platforms treat agents as *infrastructure
primitives* (deploy, scale, observe). ARIA treats them as *employees doing
accountable work* — with identity, delegated authorization, approval gates,
evidence-backed output, an immutable work ledger, evaluation before activation,
and governed self-improvement. The harness is the product; the models are
interchangeable workers inside it.

---

## 3. What V2 remains (unchanged)

V3 does **not** pull any of the following into V2. V2 stays focused on a practical,
local, single-user internal pilot:

- Conversational Orchestrator (above the accepted V1 graph)
- SQLite Domain Memory Authority (approval-gated, versioned, scope-isolated)
- local intelligence (Ollama/Gemma; no cloud fallback)
- terminal / web chat
- approval-gated memory/workflow decisions, with external writes still blocked or draft-only
- read-only internal pilots (PR / CI-CD / Analytics)

None of the V3 capabilities below are V2 implementation work.

---

## 4. Agents ARIA V3 can run and govern

V3's meta-harness is designed to run and govern a heterogeneous fleet under one
governance contract:

1. **ARIA-native specialist agents** (spawned by the Agent Factory)
2. **External CLI agents** (e.g. a terminal agent invoked as a subprocess)
3. **OpenAI Agents SDK agents**
4. **Claude / Codex-style agents**
5. **YAML-defined agents** (declarative agent specs)
6. **MCP tool servers**
7. **Dockerized / custom agents**
8. **REST-callable agents**
9. **Future mobile / web / terminal agent interfaces**

Every one of these is reached through the same adapter, registry, policy gateway,
sandbox, ledger, and evaluation harness — never directly.

---

## 5. Required V3 components (roadmap-only)

The eight components below are documented as V3 roadmap items. They are **not**
specified to implementation depth here and are **not** built in V2.

### 5.1 External Agent Adapter Layer

A common adapter interface so any external agent is described and called uniformly.
Each adapter declares:

- `agent_id`
- `provider`
- `runtime_type`
- `input_schema`
- `output_schema`
- `required_tools`
- `required_permissions`
- `sandbox_profile`
- `cost_profile`
- `risk_profile`
- `timeout_policy`
- `artifact_policy`

*Attaches to:* Tool Execution Harness (§26.1 L2) + §28.1 typed subagent briefs.

### 5.2 Universal Agent Registry

A single registry tracking every governed agent — ARIA-native and external. Tracks:

- ARIA-native agents
- external agents
- versions
- owners
- capabilities
- permissions
- lifecycle status
- approval status
- rollback target
- usage history
- evaluation score

*Attaches to:* Pillar 13 (Agent Factory), Pillar 15 (Control Plane), and the
Week-29 Model Lifecycle Registry pattern (file-backed, schema-validated, rollback
pointer).

### 5.3 Agent Policy Gateway

Every agent call passes through one governed gateway before execution. Checks:

- identity check
- delegated authorization
- allowed context
- forbidden context
- allowed tools
- forbidden tools
- risk classification
- cost policy
- privacy policy
- approval requirement
- audit trace

*Attaches to:* Governance Harness (§26.1 L3), §26.7 Safe Execution, §28.4 #1
(delegated authorization) and #6 (security gateway). No agent call bypasses it.

### 5.4 Agent Runtime Sandbox

Safe execution for CLI / Python / Dockerized / REST agents and MCP servers, with:

- path confinement
- environment isolation
- timeout
- resource limits
- no uncontrolled network access
- artifact capture
- logs
- rollback / recovery

*Attaches to:* §26.7 Safe Execution Environment (structural, not documented). The
V2 SQLite store's `ARIA_DATA_DIR` path-confinement + transactional audit outbox are
the same discipline at a smaller scale.

### 5.5 Cross-Agent Work Ledger

All agent activity — internal or external — is logged to one auditable ledger:

- `parent_task_id`
- `workflow_id`
- `correlation_id`
- `caller_agent_id`
- `target_agent_id`
- `human_owner`
- input summary
- output artifact
- tools used
- approvals
- cost
- latency
- failure
- rollback

*Attaches to:* AI Work Ledger (Pillar 16). `correlation_id` + `actor` already exist
on every v2 event (added in Week 29 precisely so subagent/cross-agent traces plug
in with no migration); `caller_agent_id` / `target_agent_id` / `human_owner` are
the §28.4 #1 envelope extensions.

### 5.6 Agent Evaluation Harness

Before activation, every agent must pass:

- smoke tests
- safety tests
- output schema tests
- cost tests
- latency tests
- task-quality evals
- prompt-injection tests
- regression tests

*Attaches to:* Evaluation Harness (§26.1 L4), Pillar 12, and the Week-31
model-fitness gate pattern (eval-only schemas, latency thresholds, graceful failure
handling) generalized from "is this model fit?" to "is this agent fit to activate?".

### 5.7 Multi-interface Control Plane

Expose governed agents through multiple surfaces over the **same** governance core:

- terminal UI
- web UI
- REST API
- future mobile / native app
- internal dashboard

*Attaches to:* §26.2 Declarative Generative UI + §26.8 Generative UI Canvas +
§28.4 #3 (AG-UI / agent-UI event stream). The surface varies; governance does not.

### 5.8 Agent Factory Expansion

Expand the current ARIA Agent Factory from **ARIA-native specialist agents** to
**external-agent packages**. Future support:

- YAML agent specs
- OpenAI Agents SDK-style agents
- Claude / Codex-style agents
- CLI agents
- MCP-enabled agents
- Dockerized agents
- REST agents

*Attaches to:* Pillar 13 (Agent Factory) + §28.4 #8 (agent-configuration
compatibility — repo-level `AGENTS.md` / `CLAUDE.md` / `ARIA.md` → registry entries
and briefs).

---

## 6. Where this attaches (so V2 leaves clean seams)

This roadmap intentionally maps 1:1 onto existing pillars and harness layers, so
V2 work needs **no** pre-building — only the avoidance of choices that would block
these later:

| V3 component | Existing attach point |
|---|---|
| External Agent Adapter Layer | §28.1 typed subagent briefs; Tool Harness (§26.1 L2) |
| Universal Agent Registry | Pillars 13 / 15; Model Lifecycle Registry pattern |
| Agent Policy Gateway | Governance Harness (§26.1 L3); §26.7; §28.4 #1/#6 |
| Agent Runtime Sandbox | §26.7 Safe Execution; V2 `ARIA_DATA_DIR` confinement |
| Cross-Agent Work Ledger | Pillar 16; `correlation_id`/`actor`; §28.4 #1 |
| Agent Evaluation Harness | §26.1 L4; Pillar 12; Week-31 fitness-gate pattern |
| Multi-interface Control Plane | §26.2 / §26.8; §28.4 #3 |
| Agent Factory Expansion | Pillar 13; §28.4 #8 |

V2's already-shipped seams that this relies on: the Work Ledger's `correlation_id` +
`actor` fields, the path-confinement + transactional-audit-outbox discipline, the
approval-gated/versioned memory authority, and the model-fitness gate.

---

## 7. Important boundary

**This is V3 roadmap only. Do not implement during Week 32 or V2.**

V2 remains focused on:

- local intelligence
- conversation
- approved memory
- terminal / web chat
- approval-gated memory/workflow decisions, with external writes still blocked or draft-only
- read-only internal pilots

When a V2 implementation choice comes up, prefer designs that make these V3 layers
easier to add later — but do **not** pre-build them.

---

## 8. V2 / V3 distinction (locked)

> *"V2 makes ARIA a practical internal AI employee pilot. V3 turns ARIA into a
> meta-harness that can govern multiple internal and external agents as accountable
> AI workers."*

---

*Cross-references: `CLAUDE.md` §26.1 (seven harness layers), §26.7 (safe
execution), §28.1 (Subagent Instruction Engine), §28.4 (Agentic AI Roadmap),
Pillars 12 / 13 / 15 / 16 / 24; `docs/V2_LOCAL_INTELLIGENCE_AND_MEMORY_PLAN.md`
(the V2 internal-pilot scope this V3 vision sits above);
`docs/week30_v1_v2_v3_boundary.md` (the V1/V2/V3 bright lines).*
