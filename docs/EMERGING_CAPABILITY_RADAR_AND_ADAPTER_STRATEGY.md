# ARIA — Emerging Capability Radar + Adapter Learning System

> **Status: DOCUMENTATION / ROADMAP ONLY — not implemented, not scheduled.**
> This document adds **no code** and changes **no runtime, tests, APIs, frontend,
> connectors, or V3.6 behavior**. It is a planning note for a future V3.7+/V4 module.
> **V3.7 has not started.** V3.6 (Work Memory Graph + World Awareness Engine) is
> committed at `c283b85` and is **fixture-only** — nothing here makes it live.
>
> **Predecessor (unchanged):** V3.6 added the Work Memory Graph + World Awareness
> Engine (source registry, fixture-only ingestion, relevance scoring, high-risk
> escalation, improvement routing to V3.5 as proposal-only). This note generalizes
> that machinery from "world updates" to "emerging external agent/AI capabilities"
> and adds the future adapter-learning loop — as vision only.

---

## 1. Why this exists

New external agent infrastructure is emerging quickly — for example Anthropic
`launch-your-agent`, Claude Managed Agents, agent memory systems (e.g. Perplexity
Brain-style), MCP servers, the OpenAI Agents SDK, Databricks/Omnigent-style
meta-harness patterns, and future hosted/managed agent runtimes.

ARIA must **not** treat every new launch as a manual roadmap discussion. It should
maintain a governed radar that detects new capabilities, understands them, compares
them against ARIA's architecture, and decides — under approval — whether each
becomes a skill, an adapter, a runtime backend, a roadmap note, a security review
item, or an ignored entry.

### Positioning (locked)

> *"ARIA should not chase every new AI launch manually. It should maintain an
> Emerging Capability Radar that detects new models, agent runtimes, memory systems,
> MCP tools, frameworks, and platform patterns, then evaluates whether they should
> become ARIA skills, adapters, runtime backends, roadmap notes, or ignored items."*

> *"Claude Managed Agents, launch-your-agent, OpenAI Agents SDK, MCP servers, and
> similar systems should be treated as possible execution backends or adapter targets
> for ARIA, not replacements for ARIA."*

> *"ARIA remains the governance, work ownership, memory, approval, Work Ledger, ROI,
> and policy layer. External runtimes are workers/backends that ARIA may govern."*

---

## 2. What ARIA should eventually be able to do

A governed, end-to-end capability-intake loop:

1. **discover** or receive news about new AI/agent capabilities;
2. **understand** what the new capability does;
3. **compare** it against ARIA's architecture;
4. **decide** whether it is one of: irrelevant · documentation-only · skill
   opportunity · adapter opportunity · runtime backend opportunity · security risk ·
   roadmap-changing opportunity;
5. **produce** an integration proposal;
6. **route** the proposal through governance and approval;
7. **learn** from the integration outcome.

This is the same shape as V3.6's existing world-awareness → improvement-proposal
flow, extended with an explicit *capability mapping* step and a future *adapter*
target. It never bypasses approval, and it never activates anything on its own.

---

## 3. Emerging Capability Radar (future module)

**Module name:** `Emerging Capability Radar`

**Purpose:** continuously monitor approved sources and identify relevant new
capabilities, then hand each to the evaluation + mapping loop.

**Sources may include:**

- official product blogs
- GitHub repositories
- release notes
- documentation pages
- research papers
- security advisories
- trusted industry / news sources
- internal team recommendations

**Important boundary (binding):**

- In current **V3.6**, ingestion is **fixture-only** — there is **no live browsing,
  no network, no crawling**. The radar concept reuses V3.6's `WorldSource` /
  `WorldUpdate` registry and deterministic relevance scoring.
- **Live monitoring comes later** (V3.8 / V4) as **scheduled routines** with
  **approved source allowlists**, cost caps, cooldowns, escalation, and a Work Ledger
  trace per run — exactly the governance V3.8 (Scheduled Routines) already requires.

The radar is a *detector and classifier*, not an actor. It produces records and
proposals; humans approve; only then does anything change.

---

## 4. Future record models (concepts only — not Pydantic code yet)

These are documented as future typed contracts. They extend, rather than replace,
the V3.6 models (`WorldSource`, `WorldUpdate`, `ImprovementProposal`) and the V3
meta-harness adapter layer (`docs/V3_ROADMAP_META_HARNESS.md` §5.1).

### 4.1 `EmergingCapability`

A detected external capability, with provenance and a governed status.

| Field | Meaning |
|---|---|
| `capability_id` | Stable id for the capability record |
| `name` | Human-readable name (e.g. "Claude Managed Agents") |
| `vendor` | Originating vendor/project (e.g. Anthropic, OpenAI, Databricks) |
| `source_url` | Citation for where it was discovered (fixture:// in V3.6) |
| `source_type` | The kind of source (blog / repo / release note / advisory / …) |
| `discovered_at` | Timestamp of detection |
| `summary` | Cited, neutral description of what it does |
| `category` | One of the categories below |
| `trust_level` | high / medium / low (mirrors V3.6 source trust) |
| `maturity_level` | e.g. experimental / preview / GA / deprecated |
| `relevance_score` | Deterministic relevance to ARIA's roadmap/goals |
| `risk_level` | low / medium / high (security/risk classification) |
| `status` | One of the statuses below |

**Categories:**

`model` · `agent_runtime` · `managed_agent_platform` · `memory_system` ·
`MCP_server` · `workflow_framework` · `vector_store` · `observability_tool` ·
`security_tool` · `deployment_platform` · `evaluation_framework`

**Statuses:**

`discovered` · `summarized` · `mapped` · `ignored` · `roadmap_note_created` ·
`skill_gap_created` · `adapter_proposal_created` · `security_review_required` ·
`approved_for_experiment` · `rejected`

### 4.2 `CapabilityMapping`

How a capability maps onto ARIA's architecture, with a recommended action.

| Field | Meaning |
|---|---|
| `mapping_id` | Stable id for the mapping record |
| `capability_id` | The `EmergingCapability` this maps |
| `aria_area` | The ARIA area it touches (list below) |
| `mapped_to` | The concrete ARIA component/concept it maps to |
| `rationale` | Why this mapping (cited reasoning) |
| `impact` | Expected impact if integrated |
| `integration_complexity` | low / medium / high effort estimate |
| `risk_summary` | Condensed risk assessment |
| `recommended_action` | ignore / document / skill_gap / adapter / runtime_backend / security_review / roadmap_note |

**ARIA areas:**

`goal ownership` · `work memory graph` · `agent workforce` · `skill evolution` ·
`world awareness` · `scheduled routines` · `runtime adapters` · `connector layer` ·
`approval system` · `Work Ledger` · `ROI dashboard` · `security/governance`

### 4.3 `AdapterProposal`

A governed proposal to integrate an external runtime as a **bounded adapter/backend**
(never an unmanaged replacement). It is an evolution of V3.6's proposal-only routing,
aimed at the V3 meta-harness External Agent Adapter Layer.

| Field | Meaning |
|---|---|
| `adapter_id` | Stable id for the adapter proposal |
| `capability_id` | The `EmergingCapability` it integrates |
| `adapter_type` | One of the adapter types below |
| `target_runtime` | The concrete external runtime to wrap |
| `input_contract` | Typed input schema the adapter accepts |
| `output_contract` | Typed output schema the adapter returns |
| `auth_requirements` | What authentication is needed (managed, scoped) |
| `permissions_required` | The exact, minimal permissions requested |
| `sandbox_requirements` | Required isolation/confinement profile |
| `cost_model` | Expected cost shape and caps |
| `risk_level` | low / medium / high |
| `approval_required` | Always true for any external runtime |
| `test_plan_ref` | Reference to the generated test plan |
| `status` | pending / in_review / approved_for_experiment / rejected / … |

**Adapter types:**

`Claude Managed Agent adapter` · `launch-your-agent integration wrapper` ·
`OpenAI Agents SDK adapter` · `MCP server adapter` · `CLI agent adapter` ·
`Docker agent adapter` · `REST agent adapter` · `local ARIA-native skill adapter`

---

## 5. How ARIA should evaluate new launches

A capability is only as good as the answers to these questions. The radar attaches
this checklist to every `CapabilityMapping`:

1. What problem does this new capability solve?
2. Is it a runtime, skill, model, memory layer, connector, or governance tool?
3. Does ARIA already have this capability?
4. Would it replace an ARIA component or become an execution backend?
5. What data would it access?
6. What actions could it perform?
7. Does it need authentication?
8. Does it create external writes?
9. Does it support audit / logging?
10. Does it support sandboxing?
11. Can it be made read-only / draft-only first?
12. What is the cost model?
13. What is the rollback plan?
14. What tests would prove it is safe?
15. Should it be ignored, documented, tested, or integrated?

Default answers bias toward **ignore / document / read-only-first**. "Integrate as a
live backend" is the last option, never the first, and only after Codex audit and
human approval.

---

## 6. Integration path (governed, end-to-end)

Every external capability must travel this path. No step is skippable, and no
external runtime becomes active just because it exists.

```text
discover capability
→ summarize with citation
→ classify category
→ map to ARIA architecture
→ score relevance/risk
→ create roadmap note or adapter proposal
→ generate test plan
→ run sandbox/fixture experiment
→ Codex audit
→ human approval
→ activate as adapter/backend only if safe
→ monitor and rollback if needed
```

> **No external runtime should become active just because it exists.**

This mirrors the V3.5 skill-evolution lifecycle (detect → propose → spec → test →
sandbox → evaluate → approve → activate → monitor → rollback) and the V3.6
improvement-routing discipline (proposal-only, never auto-activated).

---

## 7. Anthropic `launch-your-agent` / Claude Managed Agents (roadmap note)

Anthropic `launch-your-agent` and Claude Managed Agents should be treated as
**possible future execution backends** for ARIA. **ARIA should not be replaced by
them.**

**Potential future use (V4):**

- ARIA defines the goal, constraints, policy, approvals, and work memory.
- ARIA decides *when* a cloud-hosted managed agent is appropriate.
- ARIA generates a bounded agent brief (typed, scoped — the §28.1 Subagent
  Instruction Engine shape).
- A Claude Managed Agent executes under **scoped permissions**.
- ARIA receives artifacts / results.
- ARIA records a **Work Ledger** trace.
- ARIA evaluates output quality against the brief's rubric.
- ARIA asks for **approval before any external write**.
- ARIA learns from the outcome (Work Memory Graph + Skill Evolution).

### Positioning (locked)

> *"Anthropic can provide managed agent runtime. ARIA provides governed work
> ownership."*

> *"launch-your-agent may create agents quickly. ARIA should decide which agents
> should exist, what they are allowed to do, how they are evaluated, and how their
> work is remembered."*

The managed runtime is a **worker/backend**; ARIA is the governance, identity,
approval, memory, ledger, ROI, and policy layer around it.

---

## 8. Relationship to V3.6 and V4

**V3.6 (committed, `c283b85`):**

- fixture-only world awareness
- work memory graph
- improvement proposals (proposal-only)
- **no** live browsing
- **no** runtime adapter execution

**V3.7 / V3.8 (planned, not started):**

- team collaboration (V3.7)
- scheduled routines (V3.8)
- approved source monitoring (the radar's *live* sources, allowlisted + capped)

**V4 (vision):**

- external runtime adapter layer
- Claude Managed Agents adapter
- `launch-your-agent` compatibility
- MCP / CLI / REST / Docker agent adapters
- controlled experiments
- limited approved live execution
- **Model Router + Sovereignty Layer** and an **Evaluation Harness Hook** (V4.1 design
  requirements — contracts/policy only)

The Emerging Capability Radar is the **detection + mapping front-end**; the V3
meta-harness adapter layer (`docs/V3_ROADMAP_META_HARNESS.md` §5) is the **governed
execution back-end** it eventually feeds. Both are roadmap-only. The tight V4.1 scope —
adapter contracts, model/router + sovereignty contracts, evaluation hooks, and an
internal mock adapter only (no real external execution) — is specified in
[`V4_SCOPE_AND_DESIGN_REQUIREMENTS.md`](V4_SCOPE_AND_DESIGN_REQUIREMENTS.md).

---

## 9. Safety boundaries (explicit, binding on any future build)

The radar and adapter learning system must **never**:

- activate an external runtime automatically;
- perform live writes by default;
- use unmanaged credentials;
- browse the internet in an uncontrolled way;
- incur hidden cloud usage;
- self-modify production code;
- bypass the Work Ledger;
- bypass the approval gateway;
- update memory without source links;
- integrate any capability without sandbox tests **and** a Codex audit.

These are the same disciplines V1/V2/V3.6 already enforce — carried forward
unchanged, scaled to external capability intake.

---

## 10. Where this attaches (so current design leaves clean seams)

| Future concept | Existing attach point |
|---|---|
| `EmergingCapability` | V3.6 `WorldSource` / `WorldUpdate` registry + relevance scoring + high-risk escalation |
| Radar source monitoring | V3.6 fixture ingestion now; V3.8 Scheduled Routines for live, allowlisted sources |
| `CapabilityMapping` | V3.6 → V3.5 improvement routing; CLAUDE.md §26.1 harness layers; Pillars 18 / 24 |
| `AdapterProposal` | `V3_ROADMAP_META_HARNESS.md` §5.1 External Agent Adapter Layer + §5.3 Policy Gateway |
| Integration path | V3.5 skill-evolution lifecycle + V3.6 proposal-only discipline + Codex audit gate |
| Managed-agent execution | §28.1 Subagent Instruction Engine (bounded briefs) + Cross-Agent Work Ledger (§5.5) |
| Safety boundaries | §13 V3 governance requirements; §26.7 Safe Execution; V3.6 store-boundary guards |

No current code needs to change for these to be addable later — only the avoidance
of choices that would block them.

---

## Cross-references

- V3.6 implementation context: `apps/backend/aria/awareness/` (World Awareness +
  Work Memory Graph), committed at `c283b85`.
- V3 milestone roadmap: [`V3_GOAL_DRIVEN_SELF_LEARNING_AI_EMPLOYEE_WORKFORCE.md`](V3_GOAL_DRIVEN_SELF_LEARNING_AI_EMPLOYEE_WORKFORCE.md)
  (§7 World Awareness Engine, §10 Scheduled Routines, §11 Controlled Live Execution,
  §14 Roadmap).
- External-agent meta-harness / adapter layer: [`V3_ROADMAP_META_HARNESS.md`](V3_ROADMAP_META_HARNESS.md)
  (§4 agents ARIA can govern, §5 required components, §5.1 adapter layer, §5.3 policy
  gateway, §5.5 cross-agent ledger).
- Project plan future layers: `CLAUDE.md` §26.1 (seven harness layers), §26.7 (safe
  execution), §28.1 (Subagent Instruction Engine), §28.4 (Agentic AI Roadmap);
  Pillars 18 (Evolution & Capability Intelligence) and 24 (Model Intelligence).
