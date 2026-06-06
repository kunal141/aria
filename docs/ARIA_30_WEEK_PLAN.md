# ARIA — Autonomous Role-based Intelligence Agent
## 30-Week Master Build Plan

**Builder**: Kunal Mahajan, Amar Ujala  
**Started**: May 2026  
**Reveal**: Week 30 — Surprise demo to manager + LinkedIn launch  
**Ambition**: "The mother of all agentic AI projects"

---

## What ARIA Is

ARIA is not a chatbot. Not a copilot. Not a workflow tool.

**ARIA is a full AI Employee** — the first one built on a platform that can create unlimited future AI Employees. She receives goals (not prompts), decomposes work into subtasks, executes using typed skills, remembers everything across sessions, reports proactively, learns from feedback, and proposes her own capability upgrades.

> "ARIA is not the product. The AI Employee Platform is the product. ARIA is the first tenant."

---

## The 7-Layer Competitive Moat

| Layer | Why It Cannot Be Replicated |
|---|---|
| 30 weeks of institutional memory | Accumulates from Day 1. Competitor starting today begins at zero. |
| Self-dogfooding corpus | ARIA reviews her own PRs, generates her own tests from Week 7. No one else has this data. |
| Human Teaching corpus | Every correction + approval = a preference signal. 6 months × daily use. |
| Evolution Intelligence history | Daily AI ecosystem monitoring from Week 18. Calibrated relevance scoring built over months. |
| 24 pillars at production depth | Any single pillar is copyable in days. All 24 simultaneously — not in 4 weeks. |
| Calibrated evaluation infrastructure | 30 weeks of rubrics + baselines + regression data on real usage. |
| Fine-tuned specialist models | Trained on approved outputs. Encodes Amar Ujala's specific risk patterns into weights. |

---

## Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Orchestration | LangGraph | Stateful graphs, durable checkpointing, human-in-the-loop |
| Foundation | LangChain LCEL | Chains, prompt templates, tool wrappers |
| Tracing | LangSmith | Mandatory from Week 3 — every node traced |
| API | FastAPI + Pydantic | Typed contracts on every skill input/output |
| Primary LLM | Claude (Anthropic) | All ARIA skills; OpenAI for benchmarking |
| Multi-agent (hands-on) | CrewAI | Real implementation Week 22 |
| Multi-agent (study) | AutoGen | Study Weeks 17–18; bounded production Weeks 27–29 |
| Prompt optimization | DSPy | Metrics-driven, not hand-tuning — Week 21 |
| Structured output | Instructor + Pydantic | Every skill returns a validated Pydantic model |
| Vector store | Chroma → pgvector | Chroma Week 9 (learn); pgvector Week 11 (production) |
| Model serving | vLLM | Self-hosted, OpenAI-compatible, privacy-preserving — Week 25 |
| Fine-tuning | Unsloth + TRL | LoRA on Qwen2.5-Coder-7B — Week 29 |

---

## The 24 Capability Pillars

| # | Pillar | Version | Build Week |
|---|---|---|---|
| 1 | Conversational Tasking | V1 | 3–4 |
| 2 | AI Engineering (PRIMARY) | V1 | 7–10 |
| 3 | Data Science & Analytics | V2 | 11, 26 |
| 4 | QA / Test Intelligence | V1 | 17–18 |
| 5 | CI/CD & Release Intelligence | V1 | 19 |
| 6 | Jira / Delivery Management | V1 | 20 |
| 7 | Reporting & Communication | V1 | 8 |
| 8 | Knowledge / RAG / Org Intelligence | V1 | 9 |
| 9 | Code Intelligence | V1 | 10 |
| 10 | Governance & Trust | V1 | 15–16 |
| 11 | Agent Runtime Harness | V1 | 21 |
| 12 | Agent Evaluation Harness | V1 | 14 |
| 13 | Agent Factory | V2 | 22 |
| 14 | AI Workforce Expansion | V2 | 17, 25 |
| 15 | Agent Control Plane | V2 | 25 |
| 16 | AI Work Ledger | V2 | 4→8→13→15→22→29 |
| 17 | Human Teaching Layer | V1 | 11–12 |
| 18 | Evolution & Capability Intelligence | V3 | 18, 27–28 |
| 19 | Workflow Mining & Automation Discovery | V2 | 22 |
| 20 | Decision Intelligence | V2 | 24 |
| 21 | Confidence, Cost & Risk Optimizer | V2 | 21 |
| 22 | AI Capability Marketplace | V3 | 28 |
| 23 | AI Employee as a Service | V3 | 29 |
| 24 | Model Intelligence & Post-Training | V2 | 16, 25, 29 |

---

## Governance Framework — Action Tiers

| Tier | Name | What ARIA Does | Approval |
|---|---|---|---|
| T1 | Read | Fetch data, read docs, observe | Automatic |
| T2 | Recommend | Propose action, post suggestion | Automatic |
| T3 | Draft | Create draft (PR note, ticket) | Automatic — human edits before send |
| T4 | Execute-with-Approval | Takes real action after explicit approval | Human must approve |
| T5 | Autonomous | Acts without asking | Pre-approved routine patterns only |

**V1 implements Tiers 1–3 only. Tiers 4–5 are V2.**

---

## Demo Proof Milestones

| Week | Milestone | What to Show |
|---|---|---|
| 4 ★ | Task intake working | One real task accepted, tracked, status visible in UI |
| 8 ★ | First skill + artifact | PR review on a real PR → structured artifact with risk score |
| 12 ★ | Memory + retrieval | ARIA recalls a past decision. Retrieves and cites a doc. |
| 16 ★ | Governance + controlled action | ARIA recommends → approval gate → continues after approval |
| 20 ★ | AI Engineer suite complete | Jira ticket + CI/CD summary + test gen from one task |
| 24 ★ | Flagship demo v1 | Task via Teams → orchestrated → skill → artifact → Work Ledger |
| 30 ★ | Final reveal | Full platform live demo + ROI dashboard + surprise reveal |

---

---

# PHASE 1 — Foundation (Weeks 1–2) ✅ COMPLETE

---

## Week 1 — Problem, Vision, Scope Freeze

**Status**: ✅ Done  
**Goal**: Lock the problem statement, solution, and V1 scope before writing any code.

### What Was Learned
- AI Employee vs chatbot vs copilot: chatbots respond, copilots assist, AI Employees act
- Why enterprise AI needs orchestration + memory + governance — not just an LLM wrapper
- Orchestrator-first design: central brain routes, specialists execute
- Scope freeze discipline: what's in V1, what's deferred

### What Was Built
- `docs/problem_statement.md`
- `docs/solution_statement.md`
- `docs/v1_scope.md` — AI Engineer vertical is primary
- `docs/architecture.md` — first architecture sketch

### Key Decision
V1 = AI Engineer vertical only. Editorial AI is deferred to V2. This prevents scope explosion.

---

## Week 2 — Architecture & Capability Mapping

**Status**: ✅ Done  
**Goal**: Map all 24 capability pillars, design the 7-layer moat, define the 30-week plan.

### What Was Learned
- 24 capability pillars mapped from first principles
- Governed self-evolution: 9 distinct evolution types
- Self-dogfooding: ARIA using herself to build herself creates irreplaceable corpus
- 7-layer moat: why this cannot be replicated in 4 weeks

### What Was Built
- `docs/capability_map.md` — all 24 pillars with build weeks
- `docs/capability_pillars.md` — full sub-capability breakdown
- `docs/learning_curriculum.md` — every technique with study resources
- `docs/moat_analysis.md` — 7-layer moat with irreplicability rationale
- `docs/evolution_intelligence.md` — 9 evolution types + lifecycle
- `docs/self_dogfooding.md` — protocol for ARIA reviewing her own code
- `apps/frontend/src/ARIAMasterPlan.jsx` — interactive 30-week plan viewer (localhost:5173)

### Resume Bullet
> Designed 7-layer competitive moat strategy for AI Employee platform; documented governed self-evolution framework with 9 evolution types and full lifecycle across 24 capability pillars

---

---

# PHASE 2 — Build Core (Weeks 3–5)

---

## Week 3 — LangGraph Foundation

**Goal**: Build the LangGraph + LangChain backend skeleton. First graph running end-to-end.

### What to Learn
- **LangGraph**: StateGraph, nodes, edges, conditional edges, compile(), invoke()
- **LangChain LCEL**: `|` pipe operator, ChatPromptTemplate, ChatAnthropic, StrOutputParser
- **TypedDict**: why typed state matters in a 30-week codebase
- **Durable execution**: why LangGraph beats plain Python for orchestration

### What to Build

#### Day 1 — Graph skeleton (dummy router, no Claude)
- `aria/state.py` — ARIAState TypedDict (task_id, task_type, routing_reason, steps_completed)
- `aria/nodes/intake.py` — assigns UUID task_id, opens audit trail
- `aria/nodes/router.py` v1 — keyword matching (no API key needed)
- `aria/nodes/respond.py` — placeholder response
- `aria/graph.py` — StateGraph: intake → router → respond → END
- `main.py` — runs 5 test inputs, prints state

#### Day 2 — LCEL chain (isolated, no graph)
- `day2_lcel_test.py` — standalone Claude chain: prompt | llm | parser
- Understand the `|` operator before integrating

#### Day 3 — Integration + LangSmith
- `aria/config.py` — loads .env, enables LangSmith tracing
- Replace dummy router with Claude LCEL chain
- Verify trace at smith.langchain.com → project "ARIA"

#### Days 4–6 — Full graph with Claude router
- Router auto-detects API key: Claude mode if set, keyword fallback otherwise
- `aria/work_ledger.py` — Work Ledger v0: logs task_id, task_type, routing_reason per task

#### Day 7 — Review + docs
- Read LangSmith trace — see every node, every state change
- Write Week 3 learning notes + resume bullet

### Key Output
`python main.py` runs end-to-end. 5 tasks correctly classified. LangSmith trace visible. Work Ledger appending entries.

### Techniques Introduced
- LangGraph StateGraph
- LangChain LCEL (pipe operator)
- TypedDict state management

---

## Week 4 — Task Orchestrator v1 + Conditional Edges

**Goal**: Router branches to different skill nodes. Work Ledger logging every task.

### What to Learn
- **Conditional edges**: `add_conditional_edges` — graph branches based on state
- **ReAct pattern**: Think → Act → Observe → Reflect (foundation of orchestrator reasoning)
- **Task lifecycle design**: pending → routing → executing → done/failed

### What to Build
- `aria/nodes/skill_nodes.py` — placeholder nodes: pr_review_node, kpi_node, ci_cd_node, jira_node, general_node
- `aria/graph.py` v2 — conditional edges: router → correct skill node → respond
- `aria/work_ledger.py` — integrated into respond node

### Key Output
TRAIL shows `['intake', 'router', 'kpi_node', 'respond']` for KPI tasks — each task takes a different path. Work Ledger has unique task_id per run.

### Techniques Introduced
- Conditional edges (add_conditional_edges)
- ReAct reasoning pattern (conceptual foundation)

---

## Week 5 — Context Engineering

**Goal**: Design the context strategy before any skill is built. Prevents the #1 LLM architecture mistake.

### What to Learn
- Working memory vs long-term memory vs summarisation
- What to send vs store vs summarise in each LLM call
- Token budget per node — how to prevent context bloat
- Context window management patterns

### What to Build
- `aria/context/context_manager.py` — token budget enforcement, message trimming
- `aria/context/summariser.py` — summarise long task histories before they hit context limit
- Context injection points documented in every skill template

### Key Output
Context design v1 — every skill call has a defined token budget and context injection strategy.

### Techniques Introduced
- Context Engineering (working vs long-term vs summary memory)
- Chain of Thought (planning step before skill execution)

---

---

# PHASE 3 — First Skills (Weeks 6–8)

---

## Week 6 — Skill Registry + KPI Investigation Skill

**Goal**: First real skill live. ARIA actually investigates a KPI drop and returns structured analysis.

### What to Learn
- Reusable skill design: input schema → LLM call → output schema
- Pydantic for typed I/O contracts
- Eval-Lite: every skill ships with golden examples and a rubric
- LLM vs deterministic logic: when to use each

### What to Build
- `aria/skills/skill_registry.py` — register, get, list skills with metadata
- `aria/skills/kpi_skill.py`:
  - `KPIInput` Pydantic model
  - `KPIOutput` Pydantic model (summary, root_causes, recommended_actions, confidence_score)
  - Claude call with Amar Ujala media context
  - Eval rubric (1–5 scale) + 5 golden examples + 3 failure cases
- `kpi_node` wired to real skill

### Key Output
KPI investigation returns structured JSON: root causes ranked by likelihood, recommended actions, data needed. Eval rubric established.

### Techniques Introduced
- Skill Registry pattern
- Pydantic typed contracts (Pillar 11 foundation)
- Eval-Lite (precursor to full LangSmith harness at Week 14)

---

## Week 7 — PR Review Skill + Self-Dogfooding Begins

**Goal**: ARIA reviews code PRs. From this week, ARIA also reviews her own PRs.

### What to Learn
- PR review patterns: code quality, deployment risk, missing tests, business impact
- Media-tech PR review: CMS pipelines, recommendation systems, notification services, personalisation engines
- Teams bot architecture basics
- Self-dogfooding protocol: ARIA reviews her own codebase

### What to Build
- `aria/skills/pr_review_skill.py`:
  - `PRReviewInput`: diff, pr_title, pr_description, repo_context
  - `PRReviewOutput`: summary, risk_level, issues, suggestions, missing_tests, recommendation
  - Claude call with engineering + media-tech context
  - Eval rubric + 5 golden examples
- `pr_review_node` wired to real skill
- Self-dogfooding starts: ARIA reviews her own PRs from Week 7 onwards

### Key Output
PR review on a real PR → structured output with risk_level (low/medium/high/critical) and specific suggestions. Self-dogfooding log started.

### Techniques Introduced
- Self-dogfooding protocol (Pillar 2 + moat layer)
- Teams bot design patterns

---

## Week 8 — Artifact Generation Layer ★ MILESTONE

**Goal**: ARIA produces structured work products — not just analysis, but deliverable artifacts.

### What to Learn
- Enterprise artifact design: audience-aware outputs
- Converting findings to work products (PR notes, summaries, briefs)
- Artifact versioning and storage

### What to Build
- `aria/artifacts/artifact_engine.py` — artifact generator with templates
- Artifact types: PR Note, KPI Brief, CI/CD Summary, Jira Draft, Executive Summary
- Work Ledger v1: artifact_id linked to task_id
- Teams bot integration (send artifact as Teams message)

### Key Output
**★ MILESTONE DEMO**: PR review on a real PR → structured artifact output with risk score → artifact stored + linked in Work Ledger.

### Techniques Introduced
- Artifact generation patterns
- Work Ledger artifact tracking (Pillar 16)

---

---

# PHASE 4 — Memory + Identity (Weeks 9–13)

---

## Week 9 — Knowledge Retrieval Layer (RAG v1)

**Goal**: ARIA can retrieve from internal documents, SOPs, and knowledge bases.

### What to Learn
- Retrieval basics: embeddings, chunking strategies, metadata filters
- Chroma vector store (zero-config, learn first)
- HyDE: generate hypothetical doc → embed → search real docs
- Self-RAG: ARIA critiques her own retrieval relevance
- Adaptive RAG: choose strategy based on query type

### What to Build
- `aria/knowledge/retrieval.py` — Chroma-based retrieval API
- `aria/knowledge/ingestion.py` — ingest docs/SOPs into vector store
- Knowledge source: Amar Ujala editorial guidelines + engineering SOPs
- Retrieval integrated into KPI and PR Review skills

### Key Output
Knowledge retrieval v1 — ARIA can cite internal documents in her analysis.

### Techniques Introduced
- HyDE (Hypothetical Document Embeddings)
- Self-RAG (retrieval self-critique)
- Adaptive RAG (query-type-based strategy)

---

## Week 10 — Code Intelligence Layer

**Goal**: ARIA understands the codebase — not just files, but structure, dependencies, and context.

### What to Learn
- Code chunking strategies (different from text chunking)
- AST (Abstract Syntax Tree) basics
- Dependency graph analysis
- Repo-aware reasoning

### What to Build
- `aria/skills/code_intelligence.py` — repo Q&A, AST parsing, dependency graph
- Code indexing pipeline: ingest repo → chunk by function/class → embed → store
- PR metadata ingestion: link PR diffs to code intelligence index

### Key Output
Code understanding v1 — ARIA can answer "what does this function do?" and "what would break if I change this?"

### Techniques Introduced
- AST parsing
- Dependency graph analysis
- Code-aware chunking

---

## Week 11 — Memory Fabric v1

**Goal**: ARIA remembers. Session memory, task memory, user preferences.

### What to Learn
- Memory schemas: session/task/user/team
- When to update memory vs when to retrieve
- MemGPT/Letta patterns: hot (context) + warm (retrieval) + cold (archived)
- Tree of Thoughts: multi-path decomposition when outcome is uncertain
- Chroma → pgvector migration

### What to Build
- `aria/memory/session_memory.py` — remembers current conversation context
- `aria/memory/task_memory.py` — remembers past task outcomes
- `aria/memory/user_memory.py` — learns user preferences and correction patterns
- pgvector migration: persistent memory with SQL filters + ACID behaviour
- Memory API: store, retrieve, update, forget

### Key Output
Memory fabric v1 — ARIA recalls past decisions. "Last time you asked about CTR, the root cause was the recommendation model update."

### Techniques Introduced
- MemGPT/Letta memory paging patterns
- Tree of Thoughts
- pgvector (replaces Chroma for production)

---

## Week 12 — Institutional & Outcome Memory ★ MILESTONE

**Goal**: ARIA remembers decisions, not just facts. Institutional knowledge accumulates.

### What to Learn
- Decision memory: why a choice was made, not just what was chosen
- Artifact memory: link every artifact to the task and context that produced it
- Outcome memory: did the recommendation help? what was the result?
- Institutional memory: org-level patterns, not user-level preferences

### What to Build
- `aria/memory/decision_memory.py` — stores decision + rationale + outcome
- `aria/memory/artifact_memory.py` — links artifacts to tasks, contexts, outcomes
- `aria/memory/institutional_memory.py` — org-level pattern library
- Memory fabric v2: all memory types integrated

### Key Output
**★ MILESTONE DEMO**: Ask ARIA about a past decision — she recalls it with context. Ask about a doc — she retrieves and cites it. ARIA's memory is visibly accumulating.

---

## Week 13 — LangSmith Tracing + Teams Identity

**Goal**: ARIA is visible in the workplace. Traces debuggable. ARIA persona in Teams.

### What to Learn
- Trace debugging: reading LangSmith traces to find failures
- Agent observability: what to log at each node
- Teams bot identity: ARIA responds to @mentions

### What to Build
- Full LangSmith trace integration — every node logged with inputs/outputs
- Skill trace logging — each skill call linked to its trace
- ARIA persona in Teams: profile picture, display name, response style
- Work Ledger v2: trace_id linked to every task entry

### Key Output
Traceability v1 + ARIA present in workplace. @mention ARIA in Teams → she responds.

---

---

# PHASE 5 — Governance (Weeks 14–16)

---

## Week 14 — Evaluation Design + Eval Harness

**Goal**: Quality becomes a measurable, tracked system — not a feeling.

### What to Learn
- Benchmark task design: golden examples, rubrics, regression sets
- LLM-as-judge: using Claude to evaluate Claude's outputs
- Constitutional AI: output safety checks
- Regression testing: catching skill quality regressions

### What to Build
- `aria/eval/eval_harness.py` — rubric-based evaluation framework
- Benchmark datasets for 5 skills (KPI, PR Review, CI/CD, Jira, Code Intel)
- LLM-as-judge integration: Claude rates skill outputs on 1–5 rubric
- Regression checks: run eval suite after every skill update
- Constitutional AI output safety layer

### Key Output
Eval harness v1 — baseline scores established for all 5 skills. Regression runs automatically.

### Techniques Introduced
- LangSmith evaluation framework
- Constitutional AI (output safety)
- LLM-as-judge pattern

---

## Week 15 — Governance Layer + Security & Secrets

**Goal**: ARIA can be trusted. Action tiers enforced. No secrets in code ever.

### What to Learn
- RBAC: role-based access control concepts
- Approval systems: who can approve what
- Audit logging: every action leaves a traceable record
- Secrets management: vault patterns, PII redaction

### What to Build
- `aria/governance/approval_engine.py` — routes Tier 3+ actions to approval queue
- `aria/governance/rbac.py` — role-permission matrix
- `aria/governance/audit_log.py` — tamper-evident action log
- Secrets vault integration (no API keys in codebase, ever)
- PII redaction from LangSmith traces
- Work Ledger v3: approval_id logged per governed action

### Key Output
Governance v1 — ARIA cannot take a Tier 3+ action without an approval record.

---

## Week 16 — Controlled Autonomy + Model Router v1 ★ MILESTONE

**Goal**: ARIA acts at the right tier. Right model for each task.

### What to Learn
- Action tiers in practice: when to draft vs when to recommend
- Confidence + escalation: ARIA knows when to ask
- SLMs (Phi-3-mini, Qwen-0.5B) for cheap classification tasks
- Model routing: cost/quality/privacy tradeoffs

### What to Build
- `aria/models/model_router.py` — routes by task type, risk level, cost, privacy
- SLM integration for classification/routing tasks
- Proactive Teams notifications: 5 engineering-critical trigger conditions
- Trust & Explainability Console: users can inspect ARIA's reasoning

### Key Output
**★ MILESTONE DEMO**: ARIA recommends an action → approval gate → waits → continues after approval. Model router active — SLM for classification, Sonnet for complex reasoning.

### Techniques Introduced
- SLMs (Phi-3-mini, Qwen-0.5B)
- Model Router v1 (Pillar 24 begins)

---

---

# PHASE 6 — Domain Skills (Weeks 17–20)

---

## Week 17 — QA / Test Case Generation + AutoGen Study

**Goal**: ARIA generates test cases. AutoGen framework studied.

### What to Learn
- Functional test design: positive + negative + edge cases
- Requirement-to-test mapping
- **AutoGen**: ConversableAgent, GroupChat, actor-model pattern, when to use vs LangGraph
- Sub-agent spawning patterns

### What to Build
- `aria/skills/qa_skill.py` — test case generation for given code/requirement
- QA artifact templates: test plan, test case table, coverage map
- AutoGen study: annotated demo notebook (learning artifact, not production)

### Key Output
QA skill v1 — ARIA generates functional test cases from code or requirements. AutoGen patterns understood.

### Techniques Introduced
- AutoGen (study — Weeks 17–18)
- Sub-agent spawning

---

## Week 18 — Test Review + Evolution Monitoring

**Goal**: ARIA reviews test coverage. Daily AI ecosystem monitoring begins.

### What to Learn
- Coverage gap detection: what isn't tested?
- Regression risk analysis: which changes are risky?
- Evolution Intelligence setup: monitoring arxiv, AI blogs, model releases

### What to Build
- `aria/skills/test_review_skill.py` — coverage gap analysis, regression risk
- Evolution Intelligence monitor: daily digest of AI papers + model releases
- AutoGen 2-agent demo: CodeReviewerAgent + TestGeneratorAgent (learning side project)
- Work Ledger v4: evolution monitoring events logged

### Key Output
QA skill v2 + daily AI digest starting. AutoGen conversational pattern understood hands-on.

---

## Week 19 — CI/CD Intelligence

**Goal**: ARIA understands build failures and release readiness.

### What to Learn
- CI/CD lifecycle: build → test → deploy → release
- Failure triage: reading build logs, identifying root causes
- Release readiness criteria

### What to Build
- `aria/skills/ci_cd_skill.py` — build failure triage, root cause, fix suggestion
- Release readiness skill: go/no-go checklist generation
- Deployment artifact: CI/CD summary report
- Proactive CI/CD failure alerts via Teams

### Key Output
CI/CD capability v1 — ARIA reads a failing build log and identifies the root cause.

---

## Week 20 — Jira / Delivery Intelligence ★ MILESTONE

**Goal**: ARIA manages delivery — tickets, sprints, blockers.

### What to Learn
- Story decomposition: breaking epics into stories
- Acceptance criteria writing
- Backlog + blocker management

### What to Build
- `aria/skills/jira_skill.py` — ticket creation, story refinement, sprint summary
- Blocker detection: ARIA flags blockers from standup notes
- Jira proactive alerts via Teams
- Work Ledger v5: Jira ticket IDs linked to ARIA-created tickets

### Key Output
**★ MILESTONE DEMO**: Show Jira ticket creation + CI/CD failure summary + test case generation — all from one task input.

---

---

# PHASE 7 — Intelligence Depth (Weeks 21–24)

---

## Week 21 — Agent Runtime Harness + DSPy + Instructor

**Goal**: Every tool call is safe, retryable, and typed. Prompts are optimised systematically.

### What to Learn
- Retry + backoff patterns for LLM calls
- Timeout handling + idempotency
- **DSPy**: systematic prompt optimisation — define metric → compile → optimised prompt
- **Instructor**: enforce Pydantic output schemas on every skill

### What to Build
- `aria/runtime/tool_harness.py` — wraps every tool: input validation, timeout, retry, permission check, idempotency key, dry-run mode
- `aria/runtime/safety_harness.py` — Constitutional AI checks before Tier 3+ actions
- DSPy integration: optimise KPI + PR Review prompts with metrics
- Instructor applied to all skills: guaranteed typed Pydantic output

### Key Output
Runtime harness v1 — no tool call can fail silently. Every skill output is validated.

### Techniques Introduced
- DSPy (systematic prompt optimisation)
- Instructor + Pydantic (structured output enforcement)

---

## Week 22 — Agent Factory + CrewAI + Multi-Agent Patterns

**Goal**: ARIA can scaffold new agents. CrewAI implemented hands-on.

### What to Learn
- Skill vs agent vs workflow: when to use each
- Capability lifecycle: from proposal to production
- **CrewAI**: role-based agents, tasks, process — hands-on implementation
- AutoGen comparison: side-by-side with CrewAI on the same problem

### What to Build
- `aria/factory/agent_factory.py` — scaffolds new agent/skill from template
- `aria/factory/sandbox_runner.py` — 5 modes: dry-run, staging, restricted, approval-only, isolation
- CrewAI crew: Analytics + QA crew with role-based agents
- AutoGen comparison exercise: same crew in AutoGen → document tradeoffs
- Workflow mining: detect repeated task patterns → propose automation

### Key Output
Agent Factory v1 + CrewAI Analytics crew running. By this week: hands-on experience with LangGraph + CrewAI + AutoGen.

### Techniques Introduced
- CrewAI (hands-on)
- AutoGen comparison
- Workflow Mining (Pillar 19)
- Sandbox Runner patterns

---

## Week 23 — Schema/Protocol + Evolution Layer Design

**Goal**: Standardise ARIA's communication protocols. Evolution layer architecture designed.

### What to Learn
- Task schema design for interoperability
- MCP (Model Context Protocol) deeper
- A2A (Agent-to-Agent) protocol basics
- Evolution layer architecture

### What to Build
- Schema library: task, skill, artifact, event schemas
- Evolution layer draft: proposal → review → sandbox → approve → integrate
- Capability proposal flow: ARIA proposes, human reviews

### Key Output
Protocol + evolution v1 — ARIA's internal schemas are standardised and documented.

---

## Week 24 — Decision Intelligence ★ MILESTONE

**Goal**: ARIA recommends the best next action, not just any action.

### What to Learn
- Option ranking: how to compare and score alternatives
- **LATS** (Language Agent Tree Search): MCTS for agent decision exploration
- Approval prediction: can ARIA predict if an action will get approved?
- Escalation decision engine

### What to Build
- `aria/skills/decision_skill.py` — next-best-action recommendation
- Option ranker: scores alternatives by risk, cost, confidence, precedent
- Escalation engine: ARIA knows when she's out of her depth
- Approval predictor: estimates likelihood of human approval

### Key Output
**★ MILESTONE DEMO**: Full end-to-end — task via Teams → orchestrated → skill executed → artifact delivered → logged in Work Ledger. Decision intelligence layer active.

### Techniques Introduced
- LATS (Language Agent Tree Search)
- Decision Intelligence (Pillar 20)

---

---

# PHASE 8 — Workforce (Weeks 25–26)

---

## Week 25 — Agent Control Plane + SLMs + vLLM

**Goal**: ARIA manages multiple agents. Self-hosted models serving locally.

### What to Learn
- Agent lifecycle management: spawn, monitor, pause, terminate
- **vLLM**: self-hosted model serving with OpenAI-compatible API
- SLMs in production: Phi-3-mini, Qwen-0.5B for classification
- Privacy routing: sensitive data never leaves infrastructure

### What to Build
- `aria/control_plane/agent_monitor.py` — tracks all spawned agents
- vLLM setup: serve a local model via OpenAI-compatible API
- Intelligent model router v2: adds vLLM self-hosted option
- QA-ARIA spawn: first specialist agent created by Agent Factory

### Key Output
Agent Control Plane v1 + vLLM serving a local model. ARIA manages her own sub-agents.

### Techniques Introduced
- vLLM model serving
- SLMs in production (Pillar 24)

---

## Week 26 — Analytics Depth + RAPTOR + GraphRAG

**Goal**: ARIA handles complex analytics. Long documents summarised hierarchically.

### What to Learn
- Experiment analysis: A/B test interpretation
- Advanced anomaly detection patterns
- **RAPTOR**: hierarchical document summarisation — preserves structure + detail
- **GraphRAG**: knowledge graph retrieval for multi-hop reasoning

### What to Build
- EDA skill v2: experiment analysis, advanced anomaly detection
- RAPTOR integration: long org document summarisation
- GraphRAG: knowledge graph over org entities (people, teams, projects)
- Data pipeline intelligence skill

### Key Output
Analytics depth v2 — ARIA handles 100-page documents and multi-hop org queries.

### Techniques Introduced
- RAPTOR (hierarchical summarisation)
- GraphRAG (knowledge graph retrieval)

---

---

# PHASE 9 — Self-Evolution (Weeks 27–28)

---

## Week 27 — Evolution Intelligence — Evaluate & Propose

**Goal**: ARIA reads papers and proposes her own capability upgrades.

### What to Learn
- Reading ML papers in depth: extracting methods, not just abstracts
- Capability gap analysis: what can ARIA not do that she should?
- Structured proposal writing: evidence → proposed change → expected impact

### What to Build
- `aria/evolution/paper_reader.py` — reads arxiv papers, extracts methods
- `aria/evolution/capability_proposer.py` — generates structured upgrade proposals
- AutoGen 3-agent debate: ResearchAgent vs SkepticsAgent vs ImplementationAgent
- First real capability proposal from arxiv

### Key Output
First real capability proposal generated from an ML paper. AutoGen debate flow proven in production.

### Techniques Introduced
- LATS in evolution evaluation (tree search over capability options)
- AutoGen production use (bounded debate flows)

---

## Week 28 — Evolution Intelligence — Integrate + Marketplace

**Goal**: ARIA integrates an approved capability. Marketplace v1.

### What to Learn
- Approved self-integration: taking a proposal through sandbox to production
- Constitutional AI safety check on proposed code
- Marketplace design: capability discovery + adoption tracking

### What to Build
- Self-integration pipeline: design → code → test → sandbox → propose → approve → integrate
- Constitutional AI safety gate on all proposed code
- AI Capability Marketplace UI
- Skill catalog: browse, discover, adopt capabilities

### Key Output
End-to-end self-evolution loop proven — ARIA proposed, Kunal approved, ARIA integrated. Marketplace live.

---

---

# PHASE 10 — Work Ledger + ML (Week 29)

---

## Week 29 — AI Work Ledger Complete + Fine-Tuning + AaS Foundations

**Goal**: ARIA proves her ROI. Fine-tuning prototype. AaS foundations.

### What to Learn
- ROI measurement methodology: tasks completed, time saved, quality improved
- LoRA/QLoRA fine-tuning: Unsloth + TRL SFTTrainer + DPO
- Multi-tenant patterns for AaS architecture
- Business case construction

### What to Build
- AI Work Ledger v10: all 10 record types complete
- ROI dashboard: "I completed X tasks, saved Y hours, improved Z metric"
- Fine-tuning pipeline:
  - `prepare_dataset.py` — pull approved outputs from Work Ledger
  - `train_lora.py` — LoRA on Qwen2.5-Coder-7B (benchmark vs Llama-3.1-8B)
  - `eval_finetuned.py` — compare fine-tuned vs base model on eval harness
  - `serve/start_vllm.sh` — serve fine-tuned model locally
- ML Research Agent: paper review, citation traversal, synthetic data generation, model card generation
- AutoGen ML Research peer review: Paper Reader + Experiment Designer + Risk Reviewer
- AaS foundations: multi-tenant scaffold, governance console, usage tracking
- Autonomous Improvement Backlog: every rejection/failure auto-queued as improvement item
- Model Lifecycle Registry: version, dataset, eval score, endpoint, rollback pointer

### Key Output
ARIA can prove: "I completed X tasks, saved Y hours, improved Z metric." Fine-tuning prototype complete. Production model deferred to V2.

### Techniques Introduced
- LoRA/QLoRA (Unsloth + TRL)
- DPO (preference alignment)
- vLLM (model serving)
- Synthetic Data Generation
- Model Lifecycle Registry

---

---

# PHASE 11 — Launch (Week 30) ★ THE REVEAL

---

## Week 30 — Final Integration + Surprise Reveal + LinkedIn Launch

**Goal**: The world sees ARIA. The manager sees what was built in secret.

### What to Build
- Final polish: all 24 pillars functional, all 7 milestones demoed
- Demo video: 3-minute showcase of ARIA's full capabilities
- LinkedIn post (ARIA helps draft it — self-dogfooding the reveal)
- Internal presentation: live demo to manager
- GitHub repo preparation: public-ready codebase
- AaS blueprint: how ARIA becomes a commercial product

### The Reveal Script
1. Manager presents Yukti vision (org operating model)
2. Kunal reveals ARIA — "I've been building something too"
3. Live demo: task via Teams → orchestrated → artifact → Work Ledger → ROI dashboard
4. Positioning: **"Yukti is the organisational operating model. ARIA is the execution intelligence layer. Together they are stronger."**

### The LinkedIn Post
- "30 weeks. 24 capability pillars. One AI Employee."
- Built solo, in secret, at Amar Ujala
- The world sees what one person built in 30 weeks

### Key Output
**★ FINAL MILESTONE**: Public launch — surprise reveal + LinkedIn post live. ARIA's institutional memory, self-dogfooding corpus, and governed evolution loop are the irreplicable proof.

---

---

# Appendix A — Full Technique Map (27 Techniques)

| Technique | Week | Implemented As |
|---|---|---|
| LangGraph StateGraph | 3 | Core orchestration backbone |
| LangChain LCEL | 3 | Chains, prompt templates, tool wrappers |
| ReAct | 4 | Orchestrator reasoning: Think→Act→Observe→Reflect |
| Chain of Thought | 5 | Task planning step before skill execution |
| Context Engineering | 5 | Token budget, working vs long-term memory |
| HyDE | 9 | Enhanced retrieval for sparse queries |
| Self-RAG | 9 | ARIA critiques her own retrieval |
| Adaptive RAG | 9 | Dynamic retrieval strategy by query type |
| AST + Dependency Graph | 10 | Code intelligence, repo-aware reasoning |
| MemGPT/Letta patterns | 11 | Memory paging: hot + warm + cold |
| Tree of Thoughts | 11 | Multi-path task decomposition |
| LangSmith Evaluation | 13–14 | Rubric + regression + LLM-as-judge |
| Constitutional AI | 14, 28 | Output safety + self-integration safety |
| SLMs (Phi-3-mini, Qwen-0.5B) | 16 | Cheap classification and routing |
| Model Router | 16 | Right model per task: cost/quality/privacy |
| AutoGen (study + bounded production) | 17–22, 27–29 | Study Weeks 17–18; production debate flows Weeks 27, 29 |
| CrewAI (hands-on) | 22 | Analytics + QA crew implementation |
| DSPy | 21 | Systematic prompt optimisation |
| Instructor + Pydantic | 21 | Structured output enforcement on all skills |
| LATS | 24 | Agent tree search for decisions + evolution |
| vLLM | 25 | Self-hosted model serving |
| RAPTOR | 26 | Hierarchical long document summarisation |
| GraphRAG | 26 | Org knowledge graph retrieval |
| LoRA/QLoRA (Unsloth + TRL) | 29 | Fine-tune Qwen2.5-Coder-7B on Work Ledger data |
| DPO | 29 | Preference alignment from approve/reject pairs |
| Model Lifecycle Registry | 29 | MLOps for ARIA — version, eval, rollback |
| Synthetic Data Generation | 29 | Training data when real examples < 50 |

---

# Appendix B — Weekly Maintenance Discipline

Every week produces 6 mandatory artifacts. Complete before moving to next week.

| Artifact | What to Write | Where |
|---|---|---|
| Learning notes | What you learned, what's still unclear | `docs/learning_journal.md` |
| Architecture decision | Choice made, alternatives, tradeoff rationale | `docs/learning_journal.md` |
| Failure log | What broke, root cause, how fixed | `docs/learning_journal.md` |
| Capability log | Which pillar advanced, what ARIA can do now | `docs/learning_journal.md` |
| Demo snapshot | Screenshot or terminal output proving the week works | `docs/demos/week_XX.png` |
| Resume bullet | One crisp line for LinkedIn/CV | `docs/learning_journal.md` |

---

# Appendix C — Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Scope explosion — adding pillars instead of building | High | High | Freeze at 24 pillars; no new pillar without removing one |
| Framework fatigue — too many tools at once | Medium | High | LangGraph first; everything else gates on a working LangGraph foundation |
| No real company use case in demos | Medium | High | Every demo uses Amar Ujala examples (CTR, recommendation, CMS pipelines) |
| Weak evals — shipping skills with no quality baseline | High | Medium | Eval-Lite mandatory from Week 6; every skill has rubric before merging |
| No visible demo at milestone weeks | Medium | High | If Week 4 milestone can't be shown, Week 5 work pauses |
| Overdependence on one model | Low | Medium | Model Router from Week 16; fine-tuning at Week 29 |
| Political risk with Yukti reveal | Medium | High | Complement framing: "ARIA strengthens Yukti's vision" |
| Week 29 overload | High | Medium | Production fine-tuned model is V2; ROI + prototype is enough for reveal |

---

*Document version: 2026-06-04 | Updated with every session*
