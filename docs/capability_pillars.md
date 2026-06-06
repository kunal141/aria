# ARIA — 24 Capability Pillars (Full Breakdown)

Complete sub-capability inventory for all 24 pillars. Each pillar covers a full domain of work that a human employee would handle.

---

## Pillar 1 — Conversational Tasking
**Build Week**: 3-4 | **V1 Priority**: Core

The ability to receive goals (not prompts), understand intent, decompose work, route to the right specialists, and synthesize results.

**Sub-capabilities**:
- Natural language goal intake via Teams @mention, API, or scheduled trigger
- Intent classification: task vs question vs request for information
- Goal decomposition into dependent subtask graph
- Task routing: right agent/skill per task type
- Clarification before execution when goal is ambiguous
- Multi-turn conversational refinement (clarify scope, constraints, priority)
- Proactive task initiation (ARIA notices something and acts without being asked)
- Result synthesis from multiple parallel skill executions
- Confidence scoring per output
- Graceful failure handling ("I couldn't complete X because Y. Here's what I did accomplish.")

**Techniques**: ReAct, Chain of Thought, Tree of Thoughts

---

## Pillar 2 — AI Engineering
**Build Week**: 7-10 | **V1 Priority**: Primary use case

ARIA as a senior AI Engineering colleague. Reviews code, generates tests, analyzes pipelines, understands architecture.

**Sub-capabilities**:
- **PR Review** (v1+):
  - Code quality assessment (readability, patterns, anti-patterns)
  - Deployment risk estimation (what breaks if this ships?)
  - Business impact explanation (what does this change mean for users?)
  - Missing test identification (what test cases are absent?)
  - Architecture impact (does this touch core systems?)
  - Historical failure comparison (have similar changes caused incidents?)
  - **Media-tech domain awareness** (Amar Ujala–specific): ARIA understands the tech stack behind a news media org — CMS pipelines (content ingest, publish, distribution), recommendation systems (article/video ranking), notification services (push, email, in-app), personalisation engines (user cohort models, A/B variants), analytics pipelines (engagement metrics, CTR, reach). PR reviews for these systems include domain-specific risk assessment (e.g. "this change affects the recommendation ranking model — could impact 5M daily active users")
- **Code Intelligence**:
  - Repo Q&A (answer questions about any codebase)
  - AST parsing (understand code structure)
  - Dependency graph mapping (what depends on what?)
  - Semantic code retrieval (find relevant code by meaning)
  - PR metadata ingestion + indexing
- **AI Engineering Specific**:
  - LangSmith trace review (ARIA reads her own traces and proposes improvements)
  - Prompt quality review (is this prompt well-structured?)
  - Skill schema review (is this input/output typed correctly?)
  - Architecture decision documentation

**Self-dogfooding**: All AI Engineering skills are exercised on ARIA's own codebase from Week 8.

---

## Pillar 3 — Data Science & Analytics
**Build Week**: 11, 26 | **V1 Priority**: Core analytics

Investigate data, detect anomalies, explain trends, run experiments.

**Sub-capabilities**:
- KPI monitoring against historical baselines
- Statistical anomaly detection (z-score, rolling mean, standard deviation)
- Root cause investigation (structured hypothesis tree → test → conclude)
- Experiment analysis (A/B test results, feature flag impact)
- Data pipeline health monitoring
- Trend explanation (why did metric X change?)
- Correlation analysis (what correlates with this drop?)
- Dashboard data interpretation
- CSV/JSON data exploration and EDA
- Predictive trend analysis (where is this metric going?)
- **Editorial / Content-Tech KPI Investigation** (V1, Amar Ujala–specific):
  - CTR drop investigation (article-level, section-level, homepage — why did clicks fall?)
  - Personalised feed performance analysis (which cohorts are underperforming? why?)
  - Notification CTR drop investigation (push / email / in-app — open rate, click rate, opt-out spike)
  - Story recommendation performance analysis (are the right articles being surfaced to the right users?)
  - Content pipeline health monitoring (ingest latency, publish failures, CDN errors)
  - A/B test result interpretation for product and editorial experiments

**Techniques**: Statistical methods, structured hypothesis reasoning, ReAct for investigation loops

---

## Pillar 4 — QA / Test Intelligence
**Build Week**: 17-18 | **V1 Priority**: Phase 3

Design tests, find coverage gaps, analyze failures.

**Sub-capabilities**:
- Test case generation from PR/user story/acceptance criteria
- Requirement-to-test mapping (which requirement does each test cover?)
- Functional test design (happy path, normal flow)
- Negative test case identification (what should fail gracefully?)
- Edge case identification (boundary values, null inputs, race conditions)
- Failed test summary (what went wrong? Why? How to fix?)
- Test coverage gap detection (what's untested?)
- Regression checklist generation (what to re-test after this change?)
- QA artifact generation (test plan, test report, coverage report)
- Risk-based test prioritization (which tests matter most for this change?)

---

## Pillar 5 — CI/CD & Release Intelligence
**Build Week**: 19 | **V1 Priority**: Phase 3

Understand build pipelines, assess release risk, recommend rollbacks.

**Sub-capabilities**:
- Build log parsing + root cause extraction
- CI/CD failure summary (what failed, why, how to fix)
- Release readiness assessment (safe to deploy? what's the risk?)
- Deployment risk scoring (based on change scope, test coverage, historical failure rate)
- Rollback recommendation (should we roll back? which version?)
- Deployment summary artifact (what shipped, what changed, risk level)
- Historical failure pattern comparison (has this type of failure happened before?)
- Release note generation from PR list
- Multi-stage pipeline understanding (build → test → deploy → verify)

---

## Pillar 6 — Jira / Delivery Management
**Build Week**: 20 | **V1 Priority**: Phase 4

Create tickets, refine stories, track delivery.

**Sub-capabilities**:
- Jira ticket creation from PR failure, CI/CD alert, or bug report
- Story refinement (add acceptance criteria, sub-tasks, effort estimate)
- Epic-to-story decomposition
- Sprint summary generation (what shipped, what's blocked, what's at risk)
- Blocker identification + escalation recommendation
- Issue-to-code mapping (which code change caused this Jira issue?)
- Velocity trend analysis (are we on track?)
- Backlog health assessment (too much tech debt? unclear stories?)
- Dependency mapping across stories

---

## Pillar 7 — Reporting & Communication
**Build Week**: 8, 21 | **V1 Priority**: Phase 2

Translate technical work into stakeholder outputs. The right format for the right audience.

**Sub-capabilities**:
- Leadership summaries (business-first, non-technical, 1-page max)
- Stakeholder email drafting (appropriate tone, call-to-action)
- Teams update posting (timely, contextual, link-rich)
- Technical-to-business translation (what does this API change mean for revenue?)
- Weekly performance summary
- Executive briefing (situation → decision needed → recommended action → alternatives)
- Incident communication (what happened, impact, resolution, prevention)
- Meeting summary with action items
- Progress report with % complete + blockers
- Audience-aware formatting: developer view vs management view vs executive view

---

## Pillar 8 — Knowledge / RAG / Org Intelligence
**Build Week**: 9, 19, 22 | **V1 Priority**: Phase 2

ARIA knows the organization's history, SOPs, decisions, and institutional knowledge.

**Sub-capabilities**:
- Document retrieval (search SOPs, architecture docs, runbooks)
- Architecture decision recall (why was X built this way?)
- Past report retrieval (what did we say about this topic last quarter?)
- Meeting recall (what was decided in the planning meeting?)
- Semantic search over org knowledge base
- Knowledge source ingestion pipeline (new doc → chunked → embedded → indexed)
- **Advanced Retrieval**:
  - HyDE: generate hypothetical answer, embed it, find real matching docs
  - Self-RAG: ARIA critiques her own retrieval (relevant? complete? try again?)
  - Adaptive RAG: choose retrieval strategy based on query type
  - RAPTOR: hierarchical summarization of long documents
  - GraphRAG: knowledge graph traversal for multi-hop questions

---

## Pillar 9 — Code Intelligence
**Build Week**: 10 | **V1 Priority**: Phase 3

Deep understanding of codebases, not just text search.

**Sub-capabilities**:
- Repo Q&A (answer "how does X work?" using code as ground truth)
- Code indexing pipeline (chunk → embed → index by file, function, module)
- PR metadata ingestion (author, changed files, test coverage delta)
- AST parsing (understand structure: functions, classes, imports, calls)
- Dependency graph (what imports what? what does changing X break?)
- Semantic code retrieval (find code by meaning, not keyword)
- Cross-file impact analysis (changing function F affects module M, service S)
- Code pattern detection (find all places where pattern P is used)
- Release risk scoring from code change scope

---

## Pillar 10 — Governance & Trust
**Build Week**: 14-16 | **V1 Priority**: Phase 4

Every action is authorized, auditable, and reversible.

**Sub-capabilities**:
- **Action Tiers**:
  - Tier 1 — Read: safe information retrieval, no side effects
  - Tier 2 — Recommend: ARIA suggests, human decides
  - Tier 3 — Draft: ARIA prepares, human approves before sending
  - Tier 4 — Execute with Approval: critical action, human authorizes
  - Tier 5 — Autonomous Low-Risk: within pre-approved policy envelope
- RBAC (role-based access: who can request which capabilities)
- Audit log (permanent, append-only record of every action + decision)
- Approval engine (route approvals to the right human, track response)
- Risk scoring (what's the confidence? what's the blast radius?)
- Constitutional AI safety checks (is this output safe? does it violate any policy?)
- Approval prediction (will Kunal approve this? based on historical patterns)
- Policy engine (configurable rules: "never send email without human review")
- Escalation engine (when to pause and ask for human judgment)
- **Trust & Explainability Console**: for every ARIA output, users can inspect — which tools were called, which documents were retrieved, what confidence level was assigned, which approval tier applied, who approved, and why ARIA chose this approach over alternatives
- **Security & Secrets Management** (Week 15):
  - Secrets vault: no API keys or credentials in codebase; all stored in env-layer or external vault with rotation support
  - Tool permission scoping: each tool declares its minimum required permission (read-only vs read-write vs admin); enforced at Tool Execution Harness layer
  - OAuth/token design: short-lived tokens, scope-limited, refreshed automatically
  - Sensitive data redaction: PII, credentials, and internal code stripped from LangSmith traces, Work Ledger logs, and artifact text before they are stored or displayed
  - Audit-safe logging policy: what is logged vs what is always redacted — codified and enforced, not manual
  - Environment boundary: dev / staging / prod each have separate credentials; no staging credential can reach prod systems

---

## Pillar 11 — Agent Runtime Harness
**Build Week**: 21 | **V1 Priority**: Phase 5

ARIA is reliable in production. Failures are handled, not ignored.

**Sub-capabilities**:
- Retry logic with exponential backoff (transient failures → automatic recovery)
- Timeout handling (long-running tasks → graceful timeout with partial result)
- Idempotency guarantees (retry-safe: running twice = same result)
- State checkpointing + resumability (crash → resume from last checkpoint)
- Failure classification (transient vs permanent vs partial)
- Circuit breaker (repeated failures → stop trying, alert human)
- Dead letter queue (failed tasks → quarantined for human review)
- Health check endpoints (is ARIA operational?)
- Graceful degradation (if skill X fails, attempt fallback Y)
- **Tool Execution Harness** (Week 21): every tool call passes through a typed, validated, permission-gated contract:
  - Input schema validation — malformed inputs rejected before tool execution (fail fast, not expensive)
  - Output schema validation — unexpected tool outputs caught before they reach the LLM
  - Configurable timeout per tool type (search: 5s, code execution: 30s, API call: 10s)
  - Per-tool retry policy (idempotent read tools: retry 3×; destructive write tools: never auto-retry)
  - Permission check before execution — tool's required_permission checked against caller's role
  - Risk level tag (read / write / destructive) — used by Model Router and Governance layer
  - Idempotency key — every write operation has a unique key; safe to retry without double-execution
  - Dry-run mode — simulate tool execution with mock data; no side effects; used in Sandbox Runner
  - `approval_required` flag — Tier 4 tools pause execution and route to approval engine before running
  - Execution log — every tool call logged to Work Ledger with inputs, outputs, duration, cost

---

## Pillar 12 — Agent Evaluation Harness
**Build Week**: 13-14 | **V1 Priority**: Phase 3

ARIA measures herself against rubrics. What can't be measured can't be improved.

**Sub-capabilities**:
- LangSmith tracing (every run → full trace, every step visible)
- Rubric design (5+ skills have scoring criteria: PR review, test gen, KPI, summary, report)
- Golden example datasets (reference inputs + ideal outputs per skill)
- LLM-as-judge evaluation (ARIA reviews her own outputs against rubric)
- Human review scoring (Kunal scores outputs, logged as ground truth)
- Regression test suite (run benchmark after every skill update)
- Baseline scores (Week 14: first measurements, never deleted)
- Quality delta tracking (v2 rubric score vs v1 — did it improve?)
- Automated regression alert (score drops below threshold → flag for review)
- Evaluation evolution (new rubric dimensions added as gaps are discovered)

---

## Pillar 13 — Agent Factory
**Build Week**: 22, 27 | **V1 Priority**: Phase 5

ARIA can create specialist agents.

**Sub-capabilities**:
- Capability request intake (what's needed? skill, agent, or workflow?)
- Skill vs agent vs workflow classifier (is this reusable enough to register?)
- Agent scaffold generator (ARIA generates skeleton code for new agent)
- **Sandbox Runner** (safe execution environment — Week 22):
  - Dry-run mode: execute capability logic with mock/fake data; no side effects; verifies logic without touching prod
  - Staging mode: run against staging environment only; no prod systems, no prod Work Ledger, no prod memory
  - Restricted tool mode: new capability gets read-only tool access only until approved; write and destructive tools are blocked
  - Approval-only mode: every action the new capability attempts requires human sign-off during sandbox phase
  - Isolation boundary: sandbox agent runs in separate process with no access to production memory, Work Ledger records, or user data
  - Promotion gate: explicit human approval required to move from sandbox to production; rollback plan documented before every promotion
- Rubric evaluation before promotion (does the new capability meet quality bar?)
- Human approval gate (Kunal reviews sandbox results → approve/reject)
- Capability registry update (new version registered, old deprecated)
- Autonomous agent proposal (Week 27+: ARIA proposes agents without being asked)
- Self-integration pipeline (Week 27+: ARIA integrates approved capability herself)

---

## Pillar 14 — AI Workforce Expansion
**Build Week**: 17 | **V1 Priority**: Phase 4

ARIA manages a team of specialist agents.

**Sub-capabilities**:
- Specialist agent spawning (create agent instance for specific task)
- Task assignment to sub-agents (right agent gets right task)
- Parallel sub-agent execution (multiple agents run concurrently)
- Inter-agent communication (agents share context and partial results)
- Result synthesis from multiple agents (ARIA integrates outputs coherently)
- Agent performance comparison (which agent handles QA tasks better?)
- Agent retirement (decommission when no longer needed)
- Workforce health monitoring (are all agents functioning correctly?)

---

## Pillar 15 — Agent Control Plane
**Build Week**: 16 | **V1 Priority**: Phase 4

Central registry and visibility for all agents. "Internal Agent 365."

**Sub-capabilities**:
- Agent registry (every registered agent with name, version, capabilities, owner)
- Agent health monitoring (is it running? latency? error rate?)
- Lifecycle management (enable / disable / retire / upgrade)
- Usage tracking (tasks handled, tokens consumed, latency, cost per agent)
- Version history (v1 → v2 → v3 with rubric scores per version)
- Agent dependency mapping (which agents call which other agents?)
- Control plane dashboard UI (visual view of entire AI workforce)

---

## Pillar 16 — AI Work Ledger
**Build Week**: 4 (basic), 29 (complete) | **V1 Priority**: Core

Permanent, searchable record of everything ARIA has ever done. The source of truth for ROI claims.

**10 Record Types**:

| Record | What It Captures | When Created |
|---|---|---|
| Task record | Goal, plan, subtasks, status | Task intake |
| Plan record | Subtask dependency graph, routing decisions | Decomposition |
| Agent record | Which agent ran, duration, cost | Execution |
| Tool record | Which tools called, inputs, outputs | Tool use |
| Artifact record | All generated outputs indexed | Output |
| Approval record | What was approved/rejected, by whom, when | Human decision |
| Action record | External actions taken (Jira ticket created, etc.) | Action execution |
| Outcome record | Did it work? Metric change after action | 1-7 days later |
| ROI signal | Time saved, quality improved, cost reduced | Periodic |
| Improvement record | What ARIA changed based on feedback | After evolution |

**Additional capabilities**:
- Full-text search across all records
- ROI Dashboard: "I completed X tasks, saved Y hours, improved Z metric"
- Trend analysis: is ARIA being used more or less over time?
- Skill usage breakdown: which capabilities are most valuable?
- **Autonomous Improvement Backlog**: every rejected output, failed task, correction, or negative feedback signal is automatically logged as a prioritized improvement item — ARIA generates her own backlog of what to fix next, ranked by frequency and impact, reviewed by Kunal before any change is made

---

## Pillar 17 — Human Teaching Layer
**Build Week**: 9, 12 | **V1 Priority**: Phase 2

Every correction is a training signal. Every approval is a preference signal.

**Sub-capabilities**:
- Output rating (thumbs up/down on any ARIA output)
- Correction capture ("the right answer was X, not Y")
- User preference memory ("Kunal always wants business impact first")
- Approval pattern tracking (which recommendations does he always approve?)
- Rejection pattern analysis (what types of output get rejected most?)
- Correction-to-improvement pipeline (correction → Improvement Backlog → skill upgrade)
- Multi-user preference tracking (different users have different preferences)
- Preference learning (RLHF-inspired: learn from approval/rejection history)

---

## Pillar 18 — Evolution & Capability Intelligence
**Build Week**: 18 (monitoring), 27-28 (full) | **V1 Priority**: Phase 4/7

ARIA knows about new AI developments and proposes integrations.

**Sub-capabilities**:
- **Monitoring** (Week 18):
  - arxiv monitoring (filter for agent-relevant papers)
  - GitHub trending (filter for AI/agent repos)
  - HuggingFace releases (new models, evaluation frameworks)
  - LangChain/LangGraph changelogs
  - AI newsletters + blogs (distilled signals)
  - Daily digest with relevance scores
- **Evaluate & Propose** (Week 27):
  - Read papers/frameworks in depth
  - Capability gap identification (what can't ARIA do that this enables?)
  - Structured proposal writing: source, gap, expected improvement, effort, risk, sandbox plan
  - Submit to human approval inbox
- **Integrate** (Week 28):
  - Design integration (code changes, skill spec updates, prompt revisions)
  - Constitutional AI safety check on proposed code
  - Sandbox execution with rubric evaluation
  - Final approval → registry update → goes live
  - Outcome monitoring (did it improve quality?)

---

## Pillar 19 — Workflow Mining & Automation Discovery
**Build Week**: 22 | **V1 Priority**: Phase 5

Find what should be automated next.

**Sub-capabilities**:
- Repeated task detection (same request type appearing multiple times)
- Manual effort identification (ARIA notices what Kunal keeps doing manually)
- Automation candidate ranking (impact × feasibility score per candidate)
- Capability backlog generation (ranked list of automation opportunities)
- Bottleneck detection (where does work get stuck most often?)
- ROI estimate per automation opportunity
- Proposal to Agent Factory (top candidate → agent spec → sandbox)

---

## Pillar 20 — Decision Intelligence
**Build Week**: 24 | **V1 Priority**: Phase 6

ARIA recommends the best next action, not just answers to questions.

**Sub-capabilities**:
- Next-best-action recommendation (given situation X, do Y)
- Option ranking with tradeoff explanation (option A has lower risk, option B has faster ROI)
- **Risk-benefit tradeoff table**: for every recommendation, generate a structured table — option name, expected benefit, risk level, confidence score, approval tier required, historical precedent
- **Approval prediction**: based on Work Ledger approval history, predict whether Kunal will approve a proposed action before even asking — surface only borderline cases for human review
- **Release risk scoring**: predict probability of incident from a given PR or deployment based on historical failure patterns in the Work Ledger
- Escalation decision engine (when should ARIA escalate vs execute?)
- Risk/benefit articulation for each recommendation
- LATS (Language Agent Tree Search) for multi-step decision exploration
- Decision memory (past decisions + outcomes inform future recommendations)
- Confidence-gated recommendations (low confidence → escalate, don't guess)

---

## Pillar 21 — Confidence, Cost & Risk Optimizer
**Build Week**: 25 | **V1 Priority**: Phase 6

ARIA uses the right model for the right task at the right cost.

**Sub-capabilities**:
- Confidence scoring per output (how sure is ARIA?)
- Model routing by task complexity:
  - Simple summaries → fast/cheap model (GPT-4o-mini / Haiku)
  - High-risk PR review → strongest model (Claude Opus)
  - Medium analysis → balanced model (Claude Sonnet)
- Cost tracking per task + per agent + per skill
- Cost optimization recommendations (where are we spending too much?)
- Release risk predictor (ML from Work Ledger: which PRs historically cause incidents?)
- Approval predictor (based on historical patterns: will Kunal approve this?)
- Preference learning from Work Ledger history

---

## Pillar 22 — AI Capability Marketplace
**Build Week**: 28 | **V1 Priority**: Phase 7

Any team can browse, adopt, and evaluate ARIA's capabilities.

**Sub-capabilities**:
- Skill catalog (all skills: name, description, eval scores, version, owner)
- Agent catalog (all agents: capabilities, health, usage stats)
- Capability evaluation scores (rubric scores visible to teams)
- Team adoption tracking (which teams use which capabilities)
- Version history per capability (v1 → v2 → v3 with quality delta)
- Capability comparison (v2 vs v3: is the upgrade worth it?)
- Marketplace UI (browse, search, request access, rate)
- Cross-team capability sharing (one team's agent → available to others)

---

## Pillar 23 — AI Employee as a Service
**Build Week**: 29 | **V1 Priority**: Phase 8

ARIA as a platform for other organizations to deploy their own AI Employee.

**Sub-capabilities**:
- Multi-tenant architecture (each org gets isolated ARIA instance)
- Governance console per tenant (each org controls their own action tiers + RBAC)
- Usage tracking per tenant (cost, tasks, ROI per organization)
- Capability isolation (tenant A's skills/agents don't bleed into tenant B)
- Onboarding workflow (set up ARIA for a new org in < 1 day)
- Billing and cost allocation (per-task pricing model)
- White-label support (org can brand their AI Employee)
- Cross-tenant learning (aggregate signals across tenants while preserving privacy)
- **Private deployment option**: deploy ARIA entirely within a VPC or on-premises — no data leaves the organization's infrastructure; self-hosted vLLM replaces all external model API calls
- **Usage and billing layer**: per-task cost tracking, per-tenant billing, usage quotas, cost allocation reports for chargebacks across teams

---

## Pillar 24 — Model Intelligence & Post-Training
**Build Week**: 16 (router concept), 25 (SLMs + vLLM), 29 (fine-tuning + lifecycle) | **V1 Priority**: Phase 6-8

ARIA is not just a wrapper around one API model. She routes work to the right model — sometimes a tiny local model, sometimes a fine-tuned specialist, sometimes a frontier API. She also manages model versions, tracks quality, and can trigger retraining when performance drifts.

**Sub-capabilities**:
- **Model Router / Model Gateway** (v2): routes each task to the right model based on risk, complexity, cost, latency, and data privacy requirements
- **Small Language Model (SLM) Utility Layer** (v2): Phi-3-mini, Qwen-0.5B, Gemma-2B for task classification, intent routing, risk scoring, field extraction, format checking — cheap and fast for repeated internal tasks
- **vLLM Serving Layer** (v2): self-hosted open-source model inference via OpenAI-compatible API — privacy-safe for internal/sensitive data
- **LoRA / QLoRA Fine-Tuning** (v3): fine-tune specialist models (7B) on Work Ledger approved outputs — encodes organizational patterns in weights
- **DPO Preference Alignment** (v3): align model behavior using approval/rejection pairs from the Work Ledger
- **Model Lifecycle Registry** (v2): tracks model name, base model version, dataset version, eval score, deployment endpoint, rollback pointer, usage by skill
- **Model Eval Harness** (v2): compares base model vs fine-tuned model on LangSmith rubrics — quality gates before deployment
- **Model Monitoring** (v2): tracks latency, quality drift, cost per inference, failure rate post-deployment
- **ML Research & Post-Training Agent** (v3): specialist agent that automates the full ML lifecycle:
  - **Paper and research review**: reads ML papers from arxiv, extracts methods and findings relevant to ARIA's capabilities
  - **Citation traversal**: follows citation chains to discover related work and prior art
  - **Dataset discovery and quality inspection**: locates relevant public datasets, inspects for bias, coverage, format consistency
  - **Synthetic data generation**: when Work Ledger approved examples are fewer than 50, generates high-quality synthetic training examples to unblock fine-tuning
  - **Training script generation**: produces LoRA/QLoRA training scripts configured for the target model and task
  - **Experiment launch and job monitoring**: schedules training runs, monitors GPU utilization, logs metrics in real time
  - **Failure debugging and iteration**: detects training failures (loss explosion, OOM, slow convergence) and proposes fixes
  - **Model card generation**: produces structured model cards documenting base model, dataset, eval scores, intended use, limitations
  - **Approval-based promotion to deployment**: proposes trained model to Kunal for review; only deploys after explicit approval; updates Model Lifecycle Registry on promotion
- **Rollback** (v2): revert to previous model version if quality drops

**Routing Logic**:
| Condition | Route |
|---|---|
| Simple classification / extraction | SLM (Phi-3-mini, Qwen-0.5B) |
| Repeated structured generation | Fine-tuned SLM via vLLM |
| Sensitive internal code / data | Self-hosted model via vLLM (no external API) |
| Complex multi-step reasoning | Claude Opus / GPT-4 |
| Calculation-heavy | Python/SQL tool + LLM explanation |
| High-risk action tier 4-5 | Frontier model + human approval |
| Low confidence | Escalate to human |

**When NOT to fine-tune**:
- Task requires fresh knowledge (use RAG instead)
- Task depends heavily on retrieved context (use RAG + tools)
- Workflow is still changing (wait for stability)
- < 50 clean training examples
- Correctness depends on tools/data (tools beat fine-tuning here)
- RAG + prompting already meets quality bar

**Techniques**: LoRA, QLoRA, DPO, vLLM PagedAttention, model routing
**Models**: Qwen2.5-Coder-7B (fine-tuning), Phi-3-mini (SLM routing), Gemma-2B (SLM extraction), Llama-3.2-1B (SLM classification)

---

## The Exceptional Product Layer (Cross-Cutting)

These capabilities span multiple pillars and make ARIA exceptional vs basic agentic systems:

| Capability | What It Is | Pillars It Spans |
|---|---|---|
| Autonomous Improvement Backlog | ARIA generates her own list of what to fix next | 12, 17, 18 |
| Self-Dogfooding | ARIA uses herself to build herself | 2, 4, 12, 17 |
| Trust & Explainability Console | Every output shows: why, how confident, what was retrieved | 10, 12, 16 |
| ROI Dashboard | Prove the value of every task ARIA has ever run | 16 |
| Surprise Launch Narrative | 30 weeks → one person → most complete AI Employee ever | All 24 |
