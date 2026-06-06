# ARIA — 30-Week Implementation Plan

> **Structure**: v3's pedagogically correct ordering (Weeks 1–24) + our advanced capabilities (Weeks 25–30).
> **Principle**: Understand → Build → Context → Skills → Outputs → Knowledge → Memory → Observe → Measure → Govern → Autonomy → Domain → Harden → Expand → Future-proof → Launch

---

## Status Tracker

| Phase | Weeks | Theme | Status |
|---|---|---|---|
| 1 | 1–2 | Foundation: Understand + Architect | ✅ Done (docs complete) |
| 2 | 3–4 | LangGraph + Orchestrator | ⬜ |
| 3 | 5–6 | Context Engineering + First Skill | ⬜ |
| 4 | 7–8 | PR Review + Artifact Engine | ⬜ |
| 5 | 9–10 | Knowledge + Code Intelligence | ⬜ |
| 6 | 11–12 | Memory Fabric (2 weeks) | ⬜ |
| 7 | 13–14 | Observability + Evaluation | ⬜ |
| 8 | 15–16 | Governance + Controlled Autonomy | ⬜ |
| 9 | 17–18 | QA Intelligence (2 weeks) | ⬜ |
| 10 | 19–20 | CI/CD + Jira/Delivery | ⬜ |
| 11 | 21–22 | Runtime Harness + Agent Factory | ⬜ |
| 12 | 23–24 | Schema/Evolution + Packaging | ⬜ |
| 13 | 25–26 | Agent Control Plane + Workforce | ⬜ |
| 14 | 27–28 | Self-Evolution (Propose + Integrate) | ⬜ |
| 15 | 29–30 | AI Work Ledger + Launch | ⬜ |

---

## Weeks 1–2: Foundation (COMPLETE)

### Week 1 — Problem, Vision, Scope Freeze ✅
**Goal**: Freeze the project foundation so every later implementation decision is aligned.

**Learned**: AI Employee vs chatbot vs copilot vs agent; why enterprise AI needs orchestration, memory, governance; how this project becomes a platform, not a demo

**Built**: Problem statement, solution statement, V1 scope, project positioning, repo structure, docs

**Concepts**: AI Employee category, enterprise work operating system, scope discipline, problem-solution fit

**Self-Check**: Can you explain why this is not a chatbot? Can you explain the exact V1 scope in 2 minutes?

### Week 2 — Architecture & Capability Mapping ✅
**Goal**: Translate the project idea into a clear architecture and capability structure that can scale.

**Learned**: Workflow vs agent vs swarm; orchestrator-first architecture; why selective swarm beats swarm-first

**Built**: Architecture v1, capability map (23 pillars), action tiers, success metrics

**Concepts**: Orchestrator-first, specialist agents, action tiers, layered platform design

**Self-Check**: Can you explain why LangGraph fits? Can you explain when to use specialist agents vs direct tools?

---

## Week 3 — LangGraph Foundation

**Goal**: Set up the technical backbone and become comfortable with graph-based orchestration.

**Learn**:
- LangGraph nodes, edges, state (TypedDict)
- StateGraph → compile → invoke/stream
- Durable execution and checkpointing
- Human-in-the-loop via `interrupt_before` / `interrupt_after`
- LangSmith setup — `LANGSMITH_TRACING=true`, every run traced

**Build**:
- [ ] LangGraph starter flow — input node → LLM node → output node
- [ ] Add state: typed ARIAState flowing through nodes
- [ ] Add conditional edge: route based on task_type
- [ ] Wire LangSmith — traces visible in dashboard
- [ ] Frontend + backend shells initialized
- [ ] `.env` configured with API keys

**Output**: Core codebase initialized. LangGraph runs, traces visible.

**Risks**: Tool hopping; getting stuck on setup before understanding flow design

**Self-Check**: Can you create a minimal LangGraph flow? Can you explain durable execution simply?

**Learning Technique Added**: LangGraph StateGraph pattern becomes ARIA's orchestration backbone

---

## Week 4 — Task Intake & Orchestrator v1

**Goal**: Make the system accept work and move it through a controlled lifecycle.

**Learn**:
- Task lifecycle design (pending → in_progress → awaiting_approval → completed/failed)
- State machine thinking for multi-step workflows
- Task object design — what fields every task needs
- ReAct pattern (Reasoning + Acting) — ARIA's core thinking loop

**Build**:
- [ ] Task schema (Pydantic model: id, goal, context, status, action_tier, result)
- [ ] Task intake interface (chat/form/API)
- [ ] Orchestrator v1 — receives task, plans steps, routes
- [ ] Basic routing: classify task type → select skill/agent
- [ ] ReAct loop: think → act → observe → think

**Output**: Task orchestration v1. System accepts and tracks one task end-to-end.

**Risks**: Weak task schema; no clear state transitions

**Self-Check**: Can the system accept and track one task end-to-end? Can you explain each task state clearly?

**Learning Technique Added**: ReAct pattern wired into orchestrator reasoning loop

---

## Week 5 — Context Engineering

**Goal**: Design how the system thinks with the right context — not blindly stuffing everything into prompts.

**Learn**:
- Working memory (what's in the current prompt) vs long-term memory (stored, retrieved)
- What to send vs store vs summarize
- How to reduce context bloat — why 200K context ≠ unlimited thinking
- Context selection strategy — relevance scoring for injection
- Chain of Thought — structured multi-step reasoning

**Build**:
- [ ] Context strategy document (codified rules)
- [ ] Memory injection points — where in the graph context gets retrieved
- [ ] Artifact context design — how generated outputs get referenced in future tasks
- [ ] Context size budget — max tokens per node, summarization trigger
- [ ] Chain of Thought wrapper for complex task planning

**Output**: Context design v1. ARIA selects what context to include, not everything.

**Risks**: Too much context; no separation between memory and prompt payload

**Self-Check**: Can you explain what context is included for one task? Can you justify what is excluded?

**Learning Technique Added**: Chain of Thought for planning; context budgeting prevents 10 common LLM mistakes

---

## Week 6 — Skill Registry + KPI Investigation Skill

**Goal**: Move from generic orchestration to reusable enterprise capabilities with typed contracts.

**Learn**:
- Reusable skill design — name, description, input schema, output schema, action tier
- LLM vs deterministic logic — when to use each
- Schema discipline — typed inputs/outputs, not freeform text
- Skill versioning — v1 → v2 evolution path

**Build**:
- [ ] Skill registry — register, discover, invoke skills
- [ ] Skill schema (SkillDefinition model)
- [ ] KPI Investigation skill — fetch metrics, compare baseline, identify anomalies
- [ ] Skill metadata model — tags, action_tier, version, author

**Output**: First real skill live. ARIA selects and calls KPI skill with structured I/O.

**Risks**: Turning every task into one-off prompt logic; no schema discipline

**Self-Check**: Can the KPI skill run with structured input/output? Can you explain why it is a reusable skill?

**Learning Technique Added**: Typed skill contracts prevent prompt spaghetti; versioning enables Skill evolution

---

## Week 7 — PR Review Skill

**Goal**: Give the platform one serious engineering capability tied to real developer workflows.

**Learn**:
- PR review patterns — what makes a useful review vs noise
- How to review code with business context (not just style)
- Engineering risk articulation — deployment risk, breaking changes, missing tests
- Business-aware code review — how does this change affect KPIs, users, systems?

**Build**:
- [ ] PR review workflow (LangGraph graph)
- [ ] PR review skill — code quality + business impact + deployment risk
- [ ] Risk summary output format — structured, actionable
- [ ] Self-dogfooding: ARIA reviews her own codebase PR #1

**Output**: PR review v1. ARIA produces actionable PR feedback with business impact.

**Risks**: Only stylistic review without real usefulness; no business impact explanation

**Self-Check**: Can it produce actionable PR feedback? Can it explain why a change may matter?

**Learning Technique Added**: Business-aware code review; first self-dogfooding run

---

## Week 8 — Artifact Generation Layer

**Goal**: Make the system produce enterprise-ready work products, not just chat text.

**Learn**:
- Artifact design for enterprise AI — what makes an output a usable work product
- Audience-aware communication — leadership vs engineering vs QA outputs
- Converting findings into work products — reports, briefs, emails, tickets

**Build**:
- [ ] Report generator — structured analysis report
- [ ] PR note artifact — formatted PR review output
- [ ] Summary artifact — configurable length + audience
- [ ] Email/brief draft templates — stakeholder-ready
- [ ] Audience selector — same data, different format by role

**Output**: Artifact engine v1. One task creates a usable artifact. Outputs vary by audience.

**Risks**: Outputs stay too chat-like; no audience differentiation

**Self-Check**: Can one task create a usable artifact? Can outputs vary by audience?

**Learning Technique Added**: Artifactization — transforms raw LLM output into structured enterprise documents

---

## Week 9 — Knowledge Retrieval Layer

**Goal**: Give the platform grounded access to docs, SOPs, and institutional reference material.

**Learn**:
- Retrieval basics — embeddings, similarity search, vector stores
- Chunking strategy — by function/class/section, not random character splits
- Metadata filters — filter by doc type, team, date, source before ranking
- Grounding — cite sources, don't hallucinate
- Advanced RAG: HyDE (Hypothetical Document Embeddings), Self-RAG

**Build**:
- [ ] Doc/SOP retrieval layer — ingest + chunk + embed + store
- [ ] Knowledge source ingestion pipeline
- [ ] Retrieval API for agent usage (query → ranked docs)
- [ ] HyDE: generate hypothetical answer, use it to retrieve
- [ ] Self-RAG: ARIA critiques her own retrieved docs before using

**Output**: Knowledge retrieval v1. ARIA retrieves relevant docs and cites sources accurately.

**Risks**: Poor chunking; weak grounding and noisy retrieval

**Self-Check**: Can the system retrieve relevant docs reliably? Can it cite/use the right internal context?

**Learning Technique Added**: HyDE + Self-RAG wired into retrieval layer

---

## Week 10 — Code Intelligence Layer

**Goal**: Make the platform understand the structure and relationships of the existing codebase.

**Learn**:
- Code chunking — by function/class/module, not naive text splits
- AST basics — parse code structure, extract function signatures, find call sites
- Dependency graph — map imports, calls, which module affects which
- Repo-aware reasoning — knowing where to look, not just what to search

**Build**:
- [ ] Repo connector — GitHub/GitLab integration
- [ ] Code indexing pipeline — index files, functions, classes, modules
- [ ] AST parser — extract structure from Python/JS files
- [ ] Dependency graph — map inter-module dependencies
- [ ] Code intelligence v1 — answer questions about the codebase

**Output**: Code understanding v1. ARIA can locate relevant code paths and explain module relationships.

**Risks**: Only doing naive code RAG; no structural understanding

**Self-Check**: Can it locate relevant code paths? Can it explain relationships between modules?

---

## Week 11 — Memory Fabric v1

**Goal**: Introduce structured memory so the system becomes context-aware across interactions.

**Learn**:
- Session memory (current conversation), User memory (preferences, role), Team memory (org structure), Task memory (past task context)
- Memory schemas — typed entries, not freeform logs
- When to update memory — triggers, freshness, importance scoring
- MemGPT/Letta patterns — OS-style memory paging

**Build**:
- [ ] Session memory — within-conversation context
- [ ] Task memory — store task + outcome linkage
- [ ] User preference memory — learns tone, format, detail level
- [ ] Memory API — read, write, search, update
- [ ] Memory freshness — staleness scoring, decay

**Output**: Memory fabric v1. ARIA remembers task context and user preferences across sessions.

**Risks**: Confusing chat history with memory; updating memory too aggressively

**Self-Check**: Can the system remember task context? Can it use preferences properly?

**Learning Technique Added**: MemGPT/Letta memory paging patterns

---

## Week 12 — Institutional & Outcome Memory

**Goal**: Evolve memory from user/task context into organizational memory and outcome learning.

**Learn**:
- Decision memory — what was decided, why, alternatives considered
- Artifact memory — index all generated documents/reports
- Outcome memory — what happened after the action was taken
- Institutional memory concepts — the organization's collective knowledge

**Build**:
- [ ] Outcome memory model — task → action → result → lesson
- [ ] Artifact-task linkage — every artifact linked to the task that created it
- [ ] Decision memory layer — log decisions with rationale
- [ ] Memory v2 — unified API across all 6 memory types

**Output**: Institutional memory v2. ARIA links tasks to outcomes and remembers organizational decisions.

**Risks**: No structured outcome storage; memory not tied to future usefulness

**Self-Check**: Can the platform remember what happened previously? Can it link tasks to outcomes?

---

## Week 13 — LangSmith Tracing + Teams Identity

**Goal**: Make execution visible AND give ARIA her workplace presence.

**Learn**:
- Trace anatomy — input, steps, tool calls, outputs, latency, tokens
- Agent observability — see exactly what ARIA did and why
- Failure trace reading — diagnose issues from traces
- Teams Bot architecture — bot registration, @mention handling, adaptive cards

**Build**:
- [ ] LangSmith trace integration — every run traced
- [ ] Skill trace logging — per-skill trace with inputs/outputs
- [ ] Orchestrator trace logging — full graph execution visible
- [ ] Teams bot registration + @mention handler
- [ ] ARIA persona — name, greeting, voice, tone
- [ ] First Teams demo: @mention ARIA, she responds with a task result

**Output**: Traceability v1 + Teams identity. ARIA is observable AND present in the workplace.

**Risks**: Building blindly with no visibility; no reusable trace review habit

**Self-Check**: Can you debug one failed run using traces? Can ARIA respond to a Teams @mention?

---

## Week 14 — Evaluation Harness

**Goal**: Make quality measurable so the platform can improve systematically.

**Learn**:
- Benchmark tasks — representative test cases for each skill
- Golden examples — expected outputs to compare against
- Human review rubrics — structured scoring criteria
- LLM-as-judge — use a judge model to evaluate outputs
- Constitutional AI — ARIA checks her own outputs against principles
- Regression testing — detect if new version got worse

**Build**:
- [ ] Eval harness v1 — run benchmark tasks, score results
- [ ] 5 benchmark datasets: PR review, KPI analysis, test gen, summary, report
- [ ] Skill scoring rubrics — structured criteria per skill
- [ ] Regression check suite — run on every code change
- [ ] LLM-as-judge integration for automated scoring

**Output**: Eval harness v1. Can evaluate any skill against benchmarks. Regressions detected automatically.

**Risks**: No objective measurement; only subjective demo quality

**Self-Check**: Can you evaluate a skill against a benchmark? Can you detect regressions?

**Learning Technique Added**: Constitutional AI for self-evaluation

---

## Week 15 — Governance Layer

**Goal**: Add enterprise trust and controlled action boundaries to the platform.

**Learn**:
- RBAC design — roles, permissions, what each role can do
- Approval system design — who approves what, escalation paths
- Auditability requirements — what must be logged for compliance
- Policy engine — encode organizational rules

**Build**:
- [ ] Approval engine — route approval requests to right human
- [ ] Role-permission matrix — who can do what
- [ ] Audit log — every tool call, decision, approval, output recorded
- [ ] Policy engine — configurable rules (e.g., "always approve before sending email")
- [ ] RBAC enforcement — check permissions before every action

**Output**: Governance v1. Every action auditable. Approvals routed correctly. RBAC enforced.

**Risks**: Allowing unsafe actions too early; no traceability

**Self-Check**: Can you explain who can approve what? Can every action be audited?

---

## Week 16 — Controlled Autonomy

**Goal**: Move from recommendation-only behavior to governed execution.

**Learn**:
- Action tiers in practice — Read, Recommend, Draft, Execute-with-Approval, Autonomous
- Safe autonomy — what "safe" means for each tier
- Confidence + escalation — when to act vs ask for help
- Risk scoring — how to estimate action risk

**Build**:
- [ ] Action tier enforcement — every action checked against tier policy
- [ ] Draft/send/trigger action layer — ARIA can draft and execute permitted actions
- [ ] Risk scoring logic — score each action before executing
- [ ] Approval-aware execution flow — pause → await approval → resume
- [ ] Confidence threshold — escalate when confidence < threshold

**Output**: Controlled action layer. ARIA safely drafts vs executes. Escalates when uncertain.

**Risks**: Over-automation; weak escalation logic

**Self-Check**: Can the system safely draft vs execute? Can it escalate when uncertain?

---

## Week 17 — QA / Test Case Generation

**Goal**: Give the platform a serious QA capability tied to real engineering workflows.

**Learn**:
- Functional test design — happy path, negative cases, edge cases
- Requirement-to-test mapping — acceptance criteria → test cases
- Test pyramid — unit, integration, e2e in correct proportions
- AI/ML testing — prompt regression, schema mismatch, output drift

**Build**:
- [ ] Test case generation skill — from PR / Jira / requirement / user story
- [ ] Positive/negative/edge case generator
- [ ] QA artifact templates — structured test case documents
- [ ] Requirement parsing layer — extract testable criteria
- [ ] AI/ML test cases — model output validation, prompt regression

**Output**: QA skill v1. ARIA generates meaningful, mapped test cases for real PRs.

**Risks**: Only generic test cases; no mapping to real requirements

**Self-Check**: Can it generate meaningful test cases? Do they cover core paths?

---

## Week 18 — Test Review & Regression Intelligence

**Goal**: Move from generating tests to evaluating coverage and identifying risk gaps.

**Learn**:
- Coverage review — what's tested vs what matters
- Regression risk — which changes require regression testing
- Failed test analysis — what does a failure actually mean?

**Build**:
- [ ] Test case review skill — review existing tests for gaps
- [ ] Failed test summary skill — summarize failures + probable causes
- [ ] Coverage gap detection — identify missing coverage areas
- [ ] Regression checklist generator — pre-release regression scope
- [ ] Release QA summary — overall readiness assessment

**Output**: QA skill v2. ARIA reviews tests critically and identifies meaningful gaps.

**Risks**: Weak coverage analysis; no distinction between functional and regression issues

**Self-Check**: Can it review tests critically? Can it identify meaningful gaps?

---

## Week 19 — CI/CD Intelligence

**Goal**: Expand the platform into deployment and release workflows.

**Learn**:
- CI/CD lifecycle — build, test, deploy stages
- Release readiness — what "ready to ship" means
- Failure triage patterns — classify failures by type and severity
- Rollback decision logic

**Build**:
- [ ] CI/CD failure summary skill — root cause from logs
- [ ] Build log analysis — identify failed stage, missing dep, config issue
- [ ] Release readiness skill — validate deployment checklist
- [ ] Rollback summary skill — prepare rollback recommendation
- [ ] Post-deploy validation — smoke test summary

**Output**: CI/CD capability v1. ARIA summarizes pipeline failures and assesses release readiness.

**Risks**: No clear distinction between advisory and execution; weak release risk thinking

**Self-Check**: Can it summarize pipeline failures well? Can it produce release-readiness output?

---

## Week 20 — Jira / Delivery Intelligence + Reporting

**Goal**: Support delivery management, structured work tracking, and leadership communication.

**Learn**:
- Story decomposition — big features → clear subtasks
- Acceptance criteria design — what does "done" mean
- Backlog + blocker handling — what's stuck and why
- Audience-specific reporting — different formats for leadership vs engineering

**Build**:
- [ ] Jira ticket creation skill — from chat, PR, logs, test failures
- [ ] Ticket refinement skill — improve title, description, acceptance criteria
- [ ] Sprint/blocker summary skill
- [ ] Leadership summary skill — executive-ready, business impact first
- [ ] Stakeholder email skill — clear, action-oriented
- [ ] Technical-to-business translation

**Output**: Jira/Delivery v1 + Reporting v1. ARIA creates actionable stories and leadership summaries.

**Risks**: Vague tickets; no audience differentiation in reports

**Self-Check**: Can it produce actionable stories? Can it generate a leadership-ready summary?

---

## Week 21 — Agent Runtime Harness + Prompt Engineering Depth

**Goal**: Make the runtime robust enough for real enterprise operation. Optimize how prompts work.

**Learn**:
- Retries + exponential backoff — safe retry policies
- Timeout handling — prevent stuck agent loops
- Idempotency — prevent duplicate emails, tickets, actions
- Resumability + checkpointing — recover interrupted tasks
- Failure classification — tool failure vs model failure vs permission failure vs data failure
- DSPy — treat prompts as parameters, not strings; optimize systematically
- Instructor — structured output enforcement with validation
- Outlines / Guidance — constrained generation, guaranteed schema compliance

**Build**:
- [ ] Runtime harness — wraps all agent execution
- [ ] Retry logic with exponential backoff
- [ ] Execution guardrails — validate before tool calls
- [ ] Failure classifier — categorize and route failures
- [ ] Checkpointing — save progress at key stages
- [ ] DSPy prompt optimizer — systematic prompt improvement
- [ ] Instructor integration — typed, validated LLM outputs

**Output**: Runtime harness v1 + optimized prompts. Failed tasks resume. Prompts improve systematically.

**Risks**: Fragile long-running flows; no recovery strategy

**Self-Check**: Can a failed task be resumed? Can runtime issues be classified and handled?

**Learning Technique Added**: DSPy, Instructor, Outlines — the prompt engineering engineering layer

---

## Week 22 — Agent Factory

**Goal**: Enable governed self-expansion — ARIA can create new capabilities.

**Learn**:
- Skill vs agent vs workflow — when is each the right abstraction?
- Capability lifecycle — draft → test → approve → active → deprecated → retired
- Sandboxing + promotion — safe evaluation before production
- CrewAI patterns — learn role-playing multi-agent design for Factory reference
- AutoGen patterns — conversational agent protocol as Factory reference

**Build**:
- [ ] Capability request flow — propose new skill/agent/workflow
- [ ] Agent/skill/workflow classifier — what type is this capability?
- [ ] Scaffold generator — auto-generate boilerplate from spec
- [ ] Sandbox runner — isolated test environment
- [ ] Capability registry — store all approved capabilities
- [ ] Evaluation before promotion — must pass rubrics before activation

**Output**: Agent Factory v1. ARIA proposes, scaffolds, tests, and registers new capabilities.

**Risks**: Creating agents without governance; no lifecycle discipline

**Self-Check**: Can the platform propose a new capability cleanly? Can it distinguish skill vs agent?

**Learning Technique Added**: CrewAI + AutoGen patterns inform Factory design

---

## Week 23 — Schema/Protocol Design + Evolution Monitoring

**Goal**: Clean contracts, future-ready protocols, Evolution Intelligence begins monitoring.

**Learn**:
- Task, skill, artifact, approval schemas — typed contracts, not freeform dicts
- MCP (Model Context Protocol) — tool standardization
- A2A (Agent-to-Agent) basics — future interoperability
- AI ecosystem monitoring — arxiv, GitHub, HuggingFace, LangChain blog

**Build**:
- [ ] Schema library — all shared types in one place
- [ ] MCP tool definitions — ARIA's tools as MCP-compatible
- [ ] A2A protocol stub — ready for future agent interop
- [ ] Evolution Intelligence: monitoring layer — daily digest from arxiv/GitHub/HuggingFace
- [ ] Relevance scoring — filter what's worth reading
- [ ] Capability proposal flow stub — ready for Week 27

**Output**: Protocol + evolution v1. Contracts clean. ARIA starts tracking the AI ecosystem daily.

**Risks**: Loose interfaces; no future-ready protocol discipline

**Self-Check**: Are your task/skill/artifact contracts clean? Does ARIA produce a daily AI digest?

---

## Week 24 — Packaging, CV Story, Demo Polish

**Goal**: Turn the built platform into a career asset. Prepare for the bigger launch ahead.

**Learn**:
- How to defend architecture choices in interviews
- How to tell the project story in 1 min, 5 min, 30 min
- How to position the moat and value

**Build**:
- [ ] Final documentation pass — all docs current
- [ ] Architecture defense deck
- [ ] Resume bullets — updated with all Week 1-24 capabilities
- [ ] Demo script v1 — show the 5 most impressive capabilities
- [ ] Portfolio summary — for LinkedIn, interviews, visibility

**Output**: Flagship project package v1. Can explain ARIA in any timeframe to any audience.

**Risks**: Under-selling the project; no clean story for interviews

**Self-Check**: Can you explain the platform in 1 minute and 5 minutes? Can you explain why it is hard to copy?

---

## Week 25 — Agent Control Plane + Workforce Orchestration

**Goal**: ARIA manages her own agent team. She is now an AI manager, not just an AI worker.

**Learn**:
- Agent 365 concept — enterprise HR for AI agents
- Workforce orchestration — spawn, assign, monitor, coordinate, retire
- Agent health monitoring — latency, failure rate, quality score, cost
- Parallel agent execution — fan-out / fan-in patterns

**Build**:
- [ ] Agent Control Plane — registry + health dashboard + lifecycle management
- [ ] Workforce manager — spawn agents, assign tasks, collect results
- [ ] Parallel execution — fan-out to 3+ agents simultaneously
- [ ] Agent monitoring — health, usage, quality score per agent
- [ ] Workforce scaling — dynamic team size based on task complexity

**Output**: ARIA manages a 5-agent team on a complex goal. Control Plane shows all agents live.

---

## Week 26 — Analytics Depth + Decision Intelligence + Workflow Mining

**Goal**: Full Data Science capabilities + ARIA makes better decisions + discovers automation gaps.

**Learn**:
- RAPTOR (recursive summarization for long docs)
- GraphRAG (knowledge graph-based retrieval)
- Decision Intelligence — LATS (Language Agent Tree Search) for multi-step decisions
- Workflow mining — detect recurring manual work, rank automation candidates

**Build**:
- [ ] EDA skill depth — full exploratory analysis with recommendations
- [ ] Experiment analysis skill — A/B test interpretation
- [ ] Model monitoring summary — drift, performance, threshold review
- [ ] RAPTOR integration — summarize long strategy/architecture docs
- [ ] GraphRAG integration — org knowledge as a graph
- [ ] Workflow mining engine — detect + rank automation candidates
- [ ] Decision tree builder — ARIA explores multiple decision paths

**Output**: ARIA investigates a complex KPI drop with full analytics depth. Identifies 5 automation opportunities.

---

## Week 27 — Evolution Intelligence: Evaluate & Propose

**Goal**: ARIA reads AI ecosystem, identifies gaps, submits integration proposals.

**Learn**:
- How to evaluate a new framework against existing capabilities
- LATS for evaluation — tree search through capability gap analysis
- How to write a capability proposal (effort, benefit, risk estimate)

**Build**:
- [ ] Capability evaluator — ARIA reads paper/framework, compares to her skills
- [ ] Gap identifier — what she can't do that this enables
- [ ] Capability proposal generator — structured proposal with effort/benefit/risk
- [ ] Proposal inbox — Kunal reviews + approves/rejects proposals
- [ ] Outcome tracker — did approved integrations improve quality?

**Output**: ARIA submits first real capability proposal from a real arxiv paper. Kunal reviews it.

---

## Week 28 — Evolution Intelligence: Integrate

**Goal**: ARIA self-integrates an approved capability. The self-evolution loop is closed.

**Learn**:
- Constitutional AI safety checks for self-integration
- How to write safe, testable, sandboxed capability code
- How to evaluate a self-integrated capability before promotion

**Build**:
- [ ] Self-integration pipeline — design → code → test → sandbox → propose → approve → deploy
- [ ] Integration safety checker — Constitutional AI review of new code
- [ ] Sandbox auto-eval — run rubrics on new capability in isolation
- [ ] AI Capability Marketplace — catalog all skills, agents, workflows with eval scores
- [ ] Team adoption tracking — which teams use which capabilities

**Output**: ARIA self-integrates first approved capability. Marketplace live. End-to-end evolution loop proven.

---

## Week 29 — AI Work Ledger + ROI Dashboard + AaS

**Goal**: The business case is bulletproof. Leadership can see ARIA's value quantitatively.

**Build**:
- [ ] AI Work Ledger complete — all 10 record types: task, plan, agent, tool, artifact, approval, action, outcome, ROI signal, improvement
- [ ] ROI Dashboard — tasks completed, hours saved, quality improvement, adoption rate
- [ ] AaS foundations — multi-tenant isolation, governance console, usage tracking
- [ ] ARIA performance summary — automated weekly report on her own performance

**Output**: ARIA proves "I completed X tasks, saved Y hours, improved Z metric." ROI is visible.

---

## Week 30 — Launch

**Goal**: The surprise reveal. The LinkedIn post. The career-defining moment.

**Build**:
- [ ] Final polish pass — all capabilities working, all docs current
- [ ] Demo video recording — ARIA performing real tasks live
- [ ] LinkedIn post (ARIA helps write it) — announce the project publicly
- [ ] Internal presentation — surprise reveal to manager + leadership
- [ ] GitHub repo preparation — clean README, architecture docs, demo GIFs
- [ ] Resume final update — all 30 weeks of capability documented

**Outcome**: The world sees what one person built in 30 weeks. The career moat is established.

---

## Weekly Maintenance Discipline (Every Week)

| Artifact | What to capture |
|---|---|
| Learning notes | What you learned, what remains unclear |
| Architecture decisions | Choices made, alternatives considered, tradeoffs |
| Failure log | What broke and how you fixed it |
| Capability log | Every new skill/module added |
| Demo snapshots | Proof of working outputs |
| Resume bullet drafts | Update continuously, not at the end |
