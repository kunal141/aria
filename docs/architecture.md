# ARIA Architecture

## Guiding Principles

1. **Orchestrator-first**: ARIA's brain routes, delegates, and synthesizes. Specialists execute.
2. **State is sacred**: Every state transition is durable, checkpointed, and auditable.
3. **Memory before action**: Every task begins with memory retrieval; every outcome updates memory.
4. **Governed autonomy**: No autonomous action outside defined tiers. Every tier has a safety harness.
5. **Skills are versioned contracts**: Typed input/output schemas, semantic versioning, capability registry.
6. **Self-dogfooding from Week 8**: ARIA reviews her own PRs, generates her own tests, documents her own architecture. Her codebase is her first real client.
7. **Governed self-evolution**: ARIA proposes capability upgrades; humans approve; sandboxing precedes deployment. She improves like an employee — with audit and control.

---

## The 23 Capability Pillars

| # | Pillar | V1 Phase | Build Week |
|---|---|---|---|
| 1 | Conversational Tasking | Phase 1 | Week 4 |
| 2 | AI Engineering (V1 primary) | Phase 2 | Week 7 |
| 3 | Data Science & Analytics | Phase 3 | Week 11 |
| 4 | QA / Test Intelligence | Phase 3 | Week 17 |
| 5 | CI/CD & Release Intelligence | Phase 3 | Week 19 |
| 6 | Jira / Delivery Management | Phase 4 | Week 20 |
| 7 | Reporting & Communication | Phase 2 | Week 8 |
| 8 | Knowledge / RAG / Org Intelligence | Phase 2 | Week 9 |
| 9 | Code Intelligence | Phase 2 | Week 10 |
| 10 | Governance & Trust | Phase 4 | Week 15 |
| 11 | Agent Runtime Harness | Phase 5 | Week 21 |
| 12 | Agent Evaluation Harness | Phase 3 | Week 14 |
| 13 | Agent Factory | Phase 5 | Week 22 |
| 14 | AI Workforce Expansion | Phase 4 | Week 17 |
| 15 | Agent Control Plane | Phase 4 | Week 16 |
| 16 | AI Work Ledger | Phase 6 | Week 29 (full) |
| 17 | Human Teaching Layer | Phase 2 | Week 9 |
| 18 | Evolution & Capability Intelligence | Phase 4 | Week 18 (monitoring) |
| 19 | Workflow Mining & Automation Discovery | Phase 5 | Week 22 |
| 20 | Decision Intelligence | Phase 6 | Week 24 |
| 21 | Confidence, Cost & Risk Optimizer | Phase 6 | Week 25 |
| 22 | AI Capability Marketplace | Phase 7 | Week 28 |
| 23 | AI Employee as a Service | Phase 8 | Week 29 |

---

## The 19 Architecture Layers

```
┌─────────────────────────────────────────────────────────┐
│  19. Evolution Intelligence Layer                        │
│      Ecosystem monitoring, capability proposals,         │
│      sandboxed self-integration, governed improvement    │
├─────────────────────────────────────────────────────────┤
│  18. Human Teaching Layer                                │
│      Feedback capture, correction logging, preference    │
│      memory, approval/rejection pattern analysis         │
├─────────────────────────────────────────────────────────┤
│  17. AI Work Ledger                                      │
│      Permanent audit trail: 10 record types              │
│      Task / Plan / Agent / Tool / Artifact / Approval /  │
│      Action / Outcome / ROI Signal / Improvement         │
├─────────────────────────────────────────────────────────┤
│  16. Agent Factory + Control Plane                       │
│      Design → Scaffold → Sandbox → Evaluate → Register   │
│      Registry / Health / Lifecycle / Usage Tracking      │
├─────────────────────────────────────────────────────────┤
│  15. Workforce Orchestration                             │
│      Spawn, assign, monitor, retire sub-agents           │
│      Parallel execution + result synthesis               │
├─────────────────────────────────────────────────────────┤
│  14. Proactive Intelligence                              │
│      Anomaly detection, workflow mining, initiative      │
│      ARIA acts without being asked when patterns found   │
├─────────────────────────────────────────────────────────┤
│  13. Web Research + Knowledge Synthesis                  │
│      Browsing, document extraction, fact verification    │
│      SOP retrieval, past decision recall                 │
├─────────────────────────────────────────────────────────┤
│  12. Communication Intelligence                          │
│      Email drafting, Teams messaging, executive briefs   │
│      Audience-aware output: technical vs leadership      │
├─────────────────────────────────────────────────────────┤
│  11. ARIA Identity + Teams Presence                      │
│      Teams bot, @mentions, persona, proactive posting    │
├─────────────────────────────────────────────────────────┤
│  10. Code Intelligence                                   │
│      AST parsing, dependency graph, semantic code search │
│      PR review, test generation, CI/CD analysis          │
├─────────────────────────────────────────────────────────┤
│   9. Governance + Compliance                             │
│      RBAC, approval engine, audit log, policy engine     │
│      Action tier enforcement, Constitutional AI checks   │
├─────────────────────────────────────────────────────────┤
│   8. Safety Harness                                      │
│      Action tier enforcement, sandbox, promotion gates   │
│      Confidence gating, escalation decision engine       │
├─────────────────────────────────────────────────────────┤
│   7. Evaluation Harness                                  │
│      LangSmith benchmarks, rubrics, regression testing   │
│      LLM-as-judge, golden examples, quality delta        │
├─────────────────────────────────────────────────────────┤
│   6. Runtime Harness                                     │
│      Retries, checkpointing, idempotency, circuit break  │
│      Failure classification, dead letter queue           │
├─────────────────────────────────────────────────────────┤
│   5. Skill Registry                                      │
│      Versioned capabilities, typed schemas, discovery    │
│      Input/output contracts, semantic versioning         │
├─────────────────────────────────────────────────────────┤
│   4. Institutional Memory Fabric                         │
│      User/Team/Task/Decision/Artifact/Outcome memory     │
│      MemGPT/Letta patterns, memory paging + consolidation│
├─────────────────────────────────────────────────────────┤
│   3. Context Engineering Layer                           │
│      Working memory, long-term retrieval, injection      │
│      HyDE, Self-RAG, Adaptive RAG, context boundaries    │
├─────────────────────────────────────────────────────────┤
│   2. Orchestration Layer (LangGraph)                     │
│      Stateful graphs, routing, multi-agent coordination  │
│      ReAct, Chain of Thought, Tree of Thoughts           │
├─────────────────────────────────────────────────────────┤
│   1. LLM Brain                                           │
│      Claude (primary) / Gemini / GPT-4o                  │
│      Model routing: strong model for risk; fast for simple│
└─────────────────────────────────────────────────────────┘
```

---

## Governed Self-Evolution — Architecture View

ARIA improves herself through a governed, human-approved lifecycle:

```
Work Happens (task executed, output generated, action taken)
   ↓
AI Work Ledger
   Records: task, plan, agents, tools, artifacts, approvals, actions, outcomes
   ↓
Evaluation Harness
   Scores: quality rubrics, LLM-as-judge, human review, regression check
   ↓
Memory Fabric
   Stores: preferences learned, outcomes remembered, patterns identified
   ↓
Improvement Backlog
   Generates: candidate improvements ranked by impact × feasibility
   Sources: low rubric scores, user corrections, rejection analysis,
            workflow mining, Evolution Intelligence radar
   ↓
Agent Factory
   Creates: skill upgrade proposal / new workflow / new agent spec
   Includes: effort estimate, expected quality delta, risk level
   ↓
Sandbox Testing
   Runs: new capability in isolated environment
   Evaluates: against rubrics, regression tests, golden examples
   ↓
Human Approval (Kunal reviews proposal + sandbox results)
   Decision: approve / reject / request modification
   ↓
Capability Registry Update
   Action: new version registered, old version deprecated
   ↓
New Version Goes Live
   Monitoring: track adoption, quality delta, outcome improvement
```

### The 9 Types of Self-Evolution

| Type | What Evolves | Trigger |
|---|---|---|
| Prompt evolution | Better instructions, better output formats | Low rubric score + rejection pattern |
| Skill evolution | Skills become more accurate over versions | Quality rubric drops or user corrections |
| Workflow evolution | Repeated tasks become structured workflows | Workflow Mining detects repetition |
| Agent evolution | New specialist agents proposed + created | Agent Factory receives repeated capability requests |
| Memory evolution | System learns preferences + past outcomes | User correction + outcome tracking |
| Tool evolution | New tools/connectors added | Evolution radar identifies useful new tool |
| Policy evolution | Approval/risk rules improve | Outcome data shows policy is miscalibrated |
| Model-routing evolution | Better model chosen per task type | Cost/quality tracking shows routing suboptimal |
| Evaluation evolution | Better benchmarks + rubrics added | Current rubrics miss important quality dimensions |

**Hard constraint**: ARIA never modifies production behavior without human approval. Every evolution goes through: propose → sandbox → human review → approve → deploy.

---

## Self-Dogfooding Architecture

From Week 8, ARIA's own codebase (`aria/`) is her first production client:

```
Kunal opens PR on aria/ repo
   ↓
GitHub webhook → ARIA review endpoint
   ↓
PR Review Skill v1+
   Checks: code quality, deployment risk, missing tests, business impact
   ↓
ARIA posts review as GitHub comment (within 2 minutes)
   ↓
Kunal approves/rejects ARIA's review comments
   ↓
All signals logged in AI Work Ledger
   ↓
Human Teaching Layer captures correction patterns
   ↓
Improvement Backlog updated: "PR Review misses X — high impact fix"
   ↓
PR Review v2 proposed, sandboxed, approved, deployed
```

**What accumulates**: After 30 weeks, ARIA has reviewed hundreds of real PRs on a real codebase. This corpus cannot be manufactured or transferred — it is the irreplaceable operational proof.

---

## Data Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Storage Layer                         │
│  PostgreSQL          Vector Store       Object Store     │
│  (structured state)  (embeddings/RAG)   (artifacts)      │
└─────────────────────────────────────────────────────────┘
```

- **PostgreSQL**: Agent state, task records, approvals, audit log, RBAC, AI Work Ledger
- **Vector Store** (pgvector / Pinecone): Memory embeddings, skill retrieval, code search, org knowledge base
- **Object Store** (S3 / MinIO): Artifacts — reports, drafts, test cases, documents

---

## Request Flow

```
Input (Teams / Email / API / Scheduled / Proactive trigger)
        │
        ▼
Context Engineering ──► Memory Retrieval ──► Knowledge Retrieval
        │
        ▼
ARIA Orchestrator (LangGraph StateGraph)
   ReAct reasoning loop: Think → Act → Observe → Reflect
        │
   ┌────┴────┐
   │         │
Single    Multi-agent
task      routing
   │         │
   ▼         ▼
Skills   Specialist Agents (spawned by Workforce Manager)
   │         │
   └────┬────┘
        │
        ▼
Safety Harness (action tier check + confidence gate)
        │
   ┌────┴────┐
   │         │
Auto     Approval
execute   gate → Human decision
        │
        ▼
Memory Update + AI Work Ledger entry
        │
        ▼
Evaluation Harness (rubric score if applicable)
        │
        ▼
Output (Teams message / email / artifact / API response)
        │
        ▼
Human Teaching Layer (feedback capture if rating given)
```

---

## Sub-Agent Taxonomy

| Agent | Role | Trigger | Build Week |
|---|---|---|---|
| QA Agent | Test generation, coverage, regression | PR opened | Week 17 |
| Analytics Agent | KPI retrieval, anomaly detection | Scheduled / ad hoc | Week 4 (stub) |
| Editorial Agent | Content performance, SEO recommendations | Scheduled (Vertical 2) | Week 22+ |
| CI/CD Agent | Pipeline monitoring, release risk scoring | Build events | Week 19 |
| Research Agent | Web search, document synthesis | Ad hoc request | Week 13 |
| Communication Agent | Email drafting, meeting summaries | Explicit request | Week 8 |

**V2 evolution — Subagent Instruction Engine** (see `CLAUDE.md` § 28.1): the V1 sub-agents above are reached through fixed graph nodes. In V2 the main ARIA orchestrator will generate **typed Subagent Instruction Objects** (subagent_name, task_objective, parent_task_id, allowed/forbidden context, allowed/forbidden tools, expected_output_schema, risk_level, token/cost budget, deadline, approval requirement, evaluation_criteria, ledger correlation_id) and delegate dynamically. Subagents cannot self-expand permissions, cannot directly execute T4/T5 tools, and every prompt + output is recorded in the Work Ledger.

---

## Evolution Intelligence Timeline

| Phase | Week | Capability |
|---|---|---|
| Monitor | 18 | Daily AI ecosystem digest (arxiv, GitHub, HuggingFace, LangChain changelog) |
| Evaluate & Propose | 27 | Read promising signals in depth; write structured capability proposals |
| Integrate | 27-28 | Self-integrate approved capability through sandbox pipeline |

By Week 30: **12+ weeks of calibrated AI ecosystem monitoring** — a corpus of relevance-scored signals specific to ARIA's domain. A competitor starting fresh has none of this.

---

## Technology Decisions

| Concern | Choice | Reason |
|---|---|---|
| Orchestration | LangGraph | Stateful graphs, durable execution, human-in-loop |
| Tracing | LangSmith | Native LangGraph integration, eval framework, rubrics |
| LLM | Claude (primary) | Best reasoning + tool use; Gemini for multimodal |
| Backend | FastAPI | Async, typed, fast |
| Frontend | React + Tailwind + shadcn/ui | Component model, dark theme, rapid prototyping |
| DB | PostgreSQL + pgvector | One DB for state + embeddings |
| Identity | Microsoft Teams Bot | Enterprise presence, @mentions, real workplace |
| Agent protocol | MCP (V1) → A2A (V3+) | Tool standardization → future interoperability |
| Prompt engineering | DSPy + Instructor | Systematic optimization, structured outputs |
| Memory patterns | MemGPT/Letta architecture | Memory paging, consolidation, prioritization |
| Safety | Constitutional AI | Output safety checks on self-integration proposals |

---

## Harness Engineering — The Seven Layers

ARIA is built as a **Harness Engineering platform**, not a prompt wrapper. The model is one component; the product is the system around the model. Every line of code in `apps/backend/aria/` belongs to exactly one of these seven layers (the canonical reference is `CLAUDE.md` § 26.1):

1. **Runtime Harness** — LangGraph StateGraph, retries, timeouts, idempotency, loop detection, budget control.
2. **Tool Execution Harness** — MCP tools, permission scoping, typed I/O, dry-run, audit logging, risk tiers.
3. **Governance Harness** — Action Tiers 1–5, approval gates, privacy/PII redaction, evidence gates, constitutional checks.
4. **Evaluation Harness** — golden examples + failure cases + rubrics + regression tests + LangSmith traces.
5. **Memory Harness** — task / user / outcome / institutional memory (three-tier hot/warm/cold).
6. **Evolution Harness** — monitor → propose → sandbox → evaluate → approve → canary → promote → rollback with immutable versioned artifacts as runtime authority.
7. **Subagent / Workflow Harness** *(V2 — § 28.1 in CLAUDE.md)* — structured task briefs for specialist subagents.

The seven layers are the framing for the AaS pitch and the Week 30 reveal: tenants can swap models; the harness is the moat.

---

## Future Architecture Vision (V2 / V3 — documentation only)

The full vision for ARIA's V2/V3 evolution is documented in `CLAUDE.md` § 28. Summary:

- **§ 28.1 Agent Instruction Engine** — typed Subagent Instruction Objects with allowed/forbidden context, allowed/forbidden tools, expected output schema, risk level, budget, deadline, approval requirement, evaluation criteria, and a `ledger_correlation_id`. Slots on top of Pillar 13 (Agent Factory) and Pillar 15 (Control Plane). Governed: subagents cannot self-expand permissions, cannot execute T4/T5 tools, every prompt+output logged.
- **§ 28.2 Human-like Work Intelligence Layer** — ARIA decomposed into ten observable work behaviours (understand vague requests → ask clarifications → plan → delegate to subagents → use tools safely → remember → audience-adapt → produce artifacts → learn from feedback → propose governed self-improvements). Each behaviour already maps to a specific pillar or harness layer. "Human-like" describes *work capability*, never autonomy ceiling.
- **§ 28.3 Harness Engineering Platform Positioning** — explicit positioning for LinkedIn, the manager demo, AaS pitch, and interviews. The seven harness layers are the canonical framing; model choice is a footnote.

V1 (Weeks 3–30) implementation choices — especially Week 29 (see `CLAUDE.md` § 29) — must leave clean attach points for the V2 layers (e.g. Work Ledger v2's `correlation_id` and `actor` fields make the Subagent Instruction Engine a no-migration add).
