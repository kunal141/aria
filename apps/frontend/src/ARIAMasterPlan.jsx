import React, { useMemo, useState } from 'react';

export default function ARIAMasterPlan() {
  const [selectedWeek, setSelectedWeek] = useState('3');
  const [activeTab, setActiveTab] = useState('plan');

  const phases = [
    {
      week: '1', phase: 1, status: 'done',
      title: 'Problem, Vision, Scope Freeze',
      learn: ['AI Employee vs chatbot vs copilot vs agent', 'Why enterprise AI needs orchestration, memory, governance', 'How this project becomes a platform, not a demo'],
      build: ['Freeze problem statement', 'Freeze final solution statement', 'Freeze V1 scope', 'Finalize project name and strategic positioning'],
      output: 'Project definition locked ✅', goal: 'Freeze the project foundation so every later implementation decision is aligned to one clear platform vision.',
      concepts: ['AI Employee category', 'enterprise work operating system', 'scope discipline', 'problem-solution fit'],
      deliverables: ['Final problem statement', 'Final solution statement', 'V1 scope note', 'Project positioning note'],
      risks: ['Trying to solve too many problems at once', 'Mixing demo ideas with platform vision'],
      checkpoints: ['Can you explain why this is not a chatbot?', 'Can you explain the exact V1 scope in 2 minutes?'],
      techniques: [], frameworks: []
    },
    {
      week: '2', phase: 1, status: 'done',
      title: 'Architecture & Capability Mapping',
      learn: ['Workflow vs agent vs swarm', 'Orchestrator-first architecture', 'Why selective swarm is better than swarm-first'],
      build: ['Create architecture v1', 'Create capability map (24 pillars)', 'Define action tiers', 'Draft success metrics'],
      output: 'Architecture v1 + capability map ✅', goal: 'Translate the project idea into a clear architecture and capability structure that can scale.',
      concepts: ['orchestrator-first', 'specialist agents', 'action tiers', 'layered platform design'],
      deliverables: ['Architecture v1 diagram', 'Capability map', 'Action-tier matrix', 'Initial KPI list'],
      risks: ['Overcomplicating architecture too early', 'Using swarm as a buzzword instead of a design choice'],
      checkpoints: ['Can you explain why LangGraph fits?', 'Can you explain when to use specialist agents vs direct tools?'],
      techniques: [], frameworks: []
    },
    {
      week: '3', phase: 2, status: 'active',
      title: 'LangGraph + LangChain Foundation',
      learn: ['LangChain fundamentals — prompts, LCEL chains, tools, LLM wrappers (the layer LangGraph builds on)', 'LangGraph nodes, edges, state (TypedDict)', 'StateGraph → compile → invoke/stream', 'Durable execution and checkpointing', 'Human-in-the-loop via interrupt_before / interrupt_after', 'LangSmith setup — every run traced automatically'],
      build: ['LangChain prompt templates + LCEL chain for first LLM call', 'LangGraph starter flow — input → LLM → output', 'Typed ARIAState flowing through nodes', 'Conditional edge: route based on task_type', 'LangSmith traces visible in dashboard', 'Frontend + backend shells initialized'],
      output: 'Core codebase initialized. LangChain + LangGraph running. Traces visible in LangSmith.',
      goal: 'Set up the technical backbone. Understand LangChain as the foundation and LangGraph as the orchestration layer on top.',
      concepts: ['LangChain LCEL', 'prompt templates', 'state graph', 'durable execution', 'LangSmith tracing'],
      deliverables: ['LangChain chain', 'LangGraph starter flow', 'ARIAState schema', 'Frontend + backend shells', 'LangSmith traces'],
      risks: ['Skipping LangChain basics and going straight to LangGraph', 'Tool hopping before understanding flow design'],
      checkpoints: ['Can you write a LangChain LCEL chain?', 'Can you create a minimal LangGraph flow?', 'Are traces visible in LangSmith?'],
      techniques: ['LangGraph StateGraph — becomes ARIA\'s orchestration backbone'],
      frameworks: ['LangChain', 'LangGraph', 'LangSmith']
    },
    {
      week: '4', phase: 2, status: 'upcoming', milestone: true, milestoneDemo: 'One real task accepted, tracked through lifecycle, status visible in UI',
      title: 'Task Intake & Orchestrator v1',
      learn: ['Task lifecycle design (pending → in_progress → awaiting_approval → completed)', 'State machine thinking for multi-step workflows', 'Task object design', 'ReAct pattern (Reasoning + Acting) — ARIA\'s thinking loop'],
      build: ['Task schema (Pydantic model)', 'Task intake interface (chat/API)', 'Orchestrator v1 — receives task, plans, routes', 'Basic routing: classify task → select skill/agent', 'ReAct loop: think → act → observe → think', 'AI Work Ledger v0 — basic event log: record every task intake, routing decision, and completion event from Day 1 (this data accumulates for 25 more weeks before Week 29 analysis)'],
      output: 'Task orchestration v1. System accepts and tracks one task end-to-end. Work Ledger event log started.',
      goal: 'Make the system accept work and move it through a controlled lifecycle. Start the Work Ledger early — ROI and self-evolution both depend on data that must accumulate from now.',
      concepts: ['task objects', 'routing', 'state transitions', 'input normalization', 'ReAct reasoning', 'event sourcing'],
      deliverables: ['Task schema', 'Task intake UI/flow', 'Basic orchestrator', 'Task state tracking', 'Work Ledger event log v0'],
      risks: ['Weak task schema', 'No clear state transitions', 'Starting Work Ledger too late — Week 29 ROI math needs 25 weeks of data'],
      checkpoints: ['Can the system accept and track one task end-to-end?', 'Can you explain each task state clearly?', 'Is the Work Ledger logging every task event?'],
      techniques: ['ReAct pattern — wired into orchestrator reasoning loop', 'Event sourcing — every action logged from Day 1'],
      frameworks: ['LangChain', 'LangGraph']
    },
    {
      week: '5', phase: 2, status: 'upcoming',
      title: 'Context Engineering',
      learn: ['What context to send vs store vs summarize', 'Working memory vs long-term memory', 'How to reduce context bloat', 'Context selection strategy — relevance scoring', 'Chain of Thought — structured multi-step reasoning'],
      build: ['Context strategy doc (codified rules)', 'Memory injection points', 'Artifact context design', 'Context size budget — tokens per node', 'Chain of Thought wrapper for complex planning'],
      output: 'Context design v1. ARIA selects what context to include — not everything.',
      goal: 'Design how the system thinks with the right context instead of blindly stuffing everything into prompts.',
      concepts: ['working memory', 'prompt context boundaries', 'summarization', 'context selection', 'Chain of Thought'],
      deliverables: ['Context strategy note', 'Memory injection map', 'Artifact context rules', 'Token budget policy'],
      risks: ['Too much context', 'No separation between memory and prompt payload'],
      checkpoints: ['Can you explain what context is included for one task?', 'Can you justify what is excluded?'],
      techniques: ['Chain of Thought for task planning', 'Context budgeting — prevents 10 common LLM mistakes'],
      frameworks: ['LangChain']
    },
    {
      week: '6', phase: 2, status: 'upcoming',
      title: 'Skill Registry + KPI Investigation Skill',
      learn: ['Reusable skill design — typed input/output schemas', 'LLM vs deterministic logic boundaries', 'Schema discipline — typed contracts not freeform text', 'Skill versioning — v1 → v2 evolution path'],
      build: ['Skill registry — register, discover, invoke', 'Skill schema (SkillDefinition model)', 'KPI investigation skill — fetch metrics, compare baseline, find anomalies — include Amar Ujala media-tech KPIs: CTR, feed performance, notification CTR, recommendation metrics', 'Skill metadata model — tags, action_tier, version', 'Eval-Lite v1 for every new skill: 5 golden examples (representative inputs + ideal outputs), 3 failure cases (known bad outputs to catch regressions), output schema validation check, human rubric (1–5 on correctness, completeness, actionability, hallucination risk)'],
      output: 'First real skill live with Eval-Lite. ARIA selects and calls KPI skill with structured I/O. Every output scored against rubric from Day 1.',
      goal: 'Move from generic orchestration to reusable enterprise capabilities with typed contracts. Every skill ships with a minimum eval set — full harness comes at Week 14 but quality is measured from Week 6.',
      concepts: ['skills as reusable units', 'schema design', 'deterministic vs agentic boundaries', 'skill versioning', 'Eval-Lite', 'golden examples'],
      deliverables: ['Skill registry v1', 'KPI investigation skill (with media-tech KPIs)', 'Skill metadata structure', 'Eval-Lite template (golden examples + rubric)'],
      risks: ['Turning every task into one-off prompt logic', 'No schema discipline', 'Shipping skills with no quality baseline — regressions invisible until Week 14'],
      checkpoints: ['Can the KPI skill run with structured input/output?', 'Can you explain why it is a reusable skill?', 'Does the KPI skill have 5 golden examples and a rubric score?'],
      techniques: ['Typed skill contracts prevent prompt spaghetti', 'Versioning enables Skill evolution moat', 'Eval-Lite — minimum viable quality gate for every skill from Week 6'],
      frameworks: ['LangChain']
    },
    {
      week: '7', phase: 3, status: 'upcoming',
      title: 'PR Review Skill + Self-Dogfooding Begins',
      learn: ['PR review patterns — useful review vs noise', 'How to review code with business context', 'Engineering risk articulation — deployment risk, breaking changes', 'Business-aware code review'],
      build: ['PR review workflow (LangGraph graph)', 'PR review skill — code quality + business impact + deployment risk', 'Media-tech PR review context: ARIA understands CMS pipelines, recommendation systems, notification services, personalisation engines, analytics pipelines at Amar Ujala — reviews are domain-aware, not just generic code review', 'Risk summary output format — structured, actionable', 'Self-dogfooding: ARIA reviews her own codebase PR #1', 'Eval-Lite for PR review skill: 5 golden PR review examples, 3 failure cases (e.g. missed deployment risk, hallucinated test suggestion), rubric'],
      output: 'PR review v1 with media-tech domain awareness. ARIA reviews her own code. Self-dogfooding begins.',
      goal: 'Give the platform one serious engineering capability with domain relevance to Amar Ujala AND start generating real institutional memory.',
      concepts: ['code review heuristics', 'business impact awareness', 'structured review outputs', 'self-dogfooding'],
      deliverables: ['PR review workflow', 'PR review skill', 'Risk summary template', 'First self-review logged'],
      risks: ['Only stylistic review without real usefulness', 'No business impact explanation'],
      checkpoints: ['Can it produce actionable PR feedback?', 'Has ARIA reviewed her own PR?'],
      techniques: ['Business-aware code review', 'Self-dogfooding loop begins — 30 weeks of real data accumulation starts now'],
      frameworks: ['LangGraph', 'LangChain']
    },
    {
      week: '8', phase: 3, status: 'upcoming', milestone: true, milestoneDemo: 'PR review on a real PR → structured artifact output with risk score and media-tech domain context',
      title: 'Artifact Generation Layer',
      learn: ['Artifact design for enterprise AI — what makes output a usable work product', 'Audience-aware communication — leadership vs engineering vs QA', 'Converting findings into work products'],
      build: ['Report generator — structured analysis report', 'PR note artifact', 'Summary artifact — configurable length + audience', 'Email/brief draft templates', 'Audience selector — same data, different format by role', 'Work Ledger v1 — artifact logging: every generated document indexed (artifact_id, task_id, type, audience, content hash)'],
      output: 'Artifact engine v1. One task creates a usable artifact. Outputs vary by audience. Every artifact indexed in Work Ledger.',
      goal: 'Make the system produce enterprise-ready work products. Index every artifact from now so Work Ledger search works at Week 29.',
      concepts: ['artifactization', 'audience-aware communication', 'structured outputs', 'artifact indexing'],
      deliverables: ['Report templates', 'PR note artifact', 'Summary artifact', 'Email draft templates', 'Work Ledger artifact log'],
      risks: ['Outputs stay too chat-like', 'No audience differentiation'],
      checkpoints: ['Can one task create a usable artifact?', 'Can outputs vary by audience?', 'Is the artifact indexed in the Work Ledger?'],
      techniques: ['Artifactization transforms raw LLM output into structured enterprise documents'],
      frameworks: ['LangChain']
    },
    {
      week: '9', phase: 3, status: 'upcoming',
      title: 'Knowledge Retrieval Layer — RAG',
      learn: ['Retrieval basics — embeddings, similarity search, vector stores', 'Chunking strategy — by function/class/section', 'Metadata filters + grounding', 'HyDE (Hypothetical Document Embeddings)', 'Self-RAG — ARIA critiques her own retrieved docs'],
      build: ['Doc/SOP retrieval layer — ingest + chunk + embed + store', 'Knowledge source ingestion pipeline', 'Retrieval API for agent usage', 'HyDE integration', 'Self-RAG — critique retrieved docs before using', 'Vector store: start with Chroma (zero-config, in-memory, LangChain-native) — do NOT set up Postgres/pgvector this week; learn RAG fundamentals first, migrate at Week 11–12 when memory needs persistence and SQL filters'],
      output: 'Knowledge retrieval v1 on Chroma. ARIA retrieves relevant docs and cites sources accurately.',
      goal: 'Give the platform grounded access to docs, SOPs, and institutional reference material. Use Chroma to learn RAG without infrastructure overhead — pgvector migration happens once the patterns are solid.',
      concepts: ['semantic retrieval', 'chunking', 'filters', 'grounding', 'HyDE', 'Self-RAG', 'Chroma local vector store'],
      deliverables: ['Doc retrieval layer (Chroma)', 'Ingestion pipeline', 'Retrieval interface', 'HyDE + Self-RAG'],
      risks: ['Poor chunking', 'Weak grounding and noisy retrieval', 'Premature pgvector setup blocking RAG learning'],
      checkpoints: ['Can the system retrieve relevant docs reliably?', 'Can it cite the right internal context?', 'Is the vector store running locally on Chroma without DB setup overhead?'],
      techniques: ['HyDE improves retrieval for sparse queries', 'Self-RAG prevents hallucination from noisy retrieval', 'Chroma → pgvector migration pattern: start simple, add persistence when needed'],
      frameworks: ['LangChain (retrievers, Chroma)', 'LangGraph']
    },
    {
      week: '10', phase: 3, status: 'upcoming',
      title: 'Code Intelligence Layer',
      learn: ['Code chunking — by function/class/module', 'AST parsing — extract code structure', 'Dependency graph — map imports, calls, which module affects which', 'Repo-aware reasoning'],
      build: ['Repo connector — GitHub/GitLab integration', 'Code indexing pipeline', 'AST parser — extract structure from Python/JS', 'Dependency graph', 'Code intelligence v1 — answer questions about the codebase'],
      output: 'Code understanding v1. ARIA can locate relevant code paths and explain module relationships.',
      goal: 'Make the platform understand the structure and relationships of the existing codebase.',
      concepts: ['repo ingestion', 'AST parsing', 'dependency mapping', 'PR context'],
      deliverables: ['Repo connector', 'Code indexing', 'PR metadata layer', 'Code intelligence v1'],
      risks: ['Only doing naive code RAG', 'No structural understanding'],
      checkpoints: ['Can it locate relevant code paths?', 'Can it explain relationships between modules?'],
      techniques: ['AST parsing gives real code structure vs naive text chunking'],
      frameworks: ['LangChain', 'LangGraph']
    },
    {
      week: '11', phase: 4, status: 'upcoming',
      title: 'Memory Fabric v1',
      learn: ['Session, user, team, task memory — four distinct types', 'Memory schemas — typed entries, not freeform logs', 'When to update memory — triggers, freshness, importance scoring', 'MemGPT/Letta patterns — OS-style memory paging'],
      build: ['Session memory', 'Task memory — task + outcome linkage', 'User preference memory', 'Memory API — read, write, search, update', 'Memory freshness — staleness scoring', 'pgvector migration: move from Chroma (Week 9) to Postgres + pgvector — set up pgvector extension, migrate existing embeddings, add SQL metadata filters, enable hybrid search (vector similarity + SQL WHERE clauses for date/source/topic filters), Redis hot cache for frequently-accessed memory entries'],
      output: 'Memory fabric v1 on pgvector. ARIA remembers task context and preferences across sessions. Production-grade vector store live.',
      goal: 'Introduce structured memory AND migrate RAG to production-grade storage. Chroma served its purpose for learning — pgvector now unlocks persistent memory, SQL filtering, and ACID guarantees needed for institutional memory.',
      concepts: ['memory types', 'memory update logic', 'context persistence', 'MemGPT paging', 'pgvector migration', 'hybrid search'],
      deliverables: ['Memory API', 'Session memory', 'Task memory', 'User preference memory', 'pgvector migration + hybrid search'],
      risks: ['Confusing chat history with memory', 'Updating memory too aggressively', 'pgvector setup blocking memory work — do migration first, memory schema second'],
      checkpoints: ['Can the system remember task context?', 'Can it use preferences properly?', 'Is pgvector running and can you do both vector similarity and SQL filter queries simultaneously?'],
      techniques: ['MemGPT/Letta memory paging — OS-style context management', 'Hybrid search: vector similarity + SQL metadata filters — best of both worlds'],
      frameworks: ['LangChain', 'LangGraph', 'pgvector']
    },
    {
      week: '12', phase: 4, status: 'upcoming', milestone: true, milestoneDemo: 'Ask ARIA about a past decision — she recalls it. Ask about an internal doc — she retrieves and cites it with metadata.',
      title: 'Institutional & Outcome Memory',
      learn: ['Decision memory — what was decided, why, alternatives', 'Artifact memory — index all generated documents', 'Outcome memory — what happened after the action', 'Institutional memory — organizational collective knowledge'],
      build: ['Outcome memory model', 'Artifact-task linkage', 'Decision memory layer', 'Memory v2 — unified API across all 6 memory types'],
      output: 'Institutional memory v2. ARIA links tasks to outcomes and remembers decisions.',
      goal: 'Evolve memory from user/task context into organizational memory and outcome learning.',
      concepts: ['institutional memory', 'decision traces', 'artifact linkage', 'outcome capture'],
      deliverables: ['Outcome memory model', 'Artifact linking', 'Decision memory layer', 'Memory v2 API'],
      risks: ['No structured outcome storage', 'Memory not tied to future usefulness'],
      checkpoints: ['Can the platform remember what happened previously?', 'Can it link tasks to outcomes?'],
      techniques: ['6-layer institutional memory fabric — the primary moat accumulation begins'],
      frameworks: ['LangChain', 'LangGraph']
    },
    {
      week: '13', phase: 4, status: 'upcoming',
      title: 'LangSmith Tracing + Teams Identity',
      learn: ['Trace anatomy — input, steps, tool calls, outputs, latency, tokens', 'Agent observability — see exactly what ARIA did and why', 'Failure trace reading', 'Teams Bot architecture — bot registration, @mention, adaptive cards'],
      build: ['LangSmith trace integration', 'Skill + orchestrator trace logging', 'Teams bot registration + @mention handler', 'ARIA persona — name, greeting, voice, tone', 'Work Ledger v2 — trace linking: every LangSmith trace_id linked to its Work Ledger task record (enables "show me exactly what ARIA did for task X")'],
      output: 'Traceability v1 + Teams identity. ARIA is observable AND present in the workplace. Every trace linked to a Work Ledger record.',
      goal: 'Make execution visible, give ARIA her workplace presence, and connect observability to the Work Ledger so traces are queryable alongside outcomes.',
      concepts: ['trace anatomy', 'agent observability', 'failure trace interpretation', 'Teams Bot framework', 'trace-to-ledger linking'],
      deliverables: ['LangSmith traces', 'Skill + orchestrator traces', 'Teams bot live', 'ARIA persona', 'Trace-to-ledger link table'],
      risks: ['Building blindly with no visibility', 'No Teams presence = no workplace identity'],
      checkpoints: ['Can you debug one failed run using traces?', 'Can ARIA respond to a Teams @mention?', 'Can you look up a Work Ledger task and see its LangSmith trace?'],
      techniques: ['LangSmith tracing — full execution visibility', 'Teams identity — ARIA becomes a real workplace colleague'],
      frameworks: ['LangSmith', 'LangGraph', 'LangChain']
    },
    {
      week: '14', phase: 4, status: 'upcoming',
      title: 'Evaluation Harness',
      learn: ['Benchmark tasks — representative test cases per skill', 'Golden examples — expected outputs to compare against', 'Human review rubrics', 'LLM-as-judge', 'Constitutional AI — ARIA checks own outputs against principles'],
      build: ['Eval harness v1', '5 benchmark datasets: PR review, KPI analysis, test gen, summary, report', 'Skill scoring rubrics', 'Regression check suite', 'LLM-as-judge integration'],
      output: 'Eval harness v1. Skills evaluated against benchmarks. Regressions caught automatically.',
      goal: 'Make quality measurable so the platform can improve systematically.',
      concepts: ['benchmark design', 'quality rubrics', 'regression checks', 'LLM-as-judge', 'Constitutional AI'],
      deliverables: ['Eval harness', 'Benchmark tasks', 'Scoring rubrics', 'Regression tests'],
      risks: ['No objective measurement', 'Only subjective demo quality'],
      checkpoints: ['Can you evaluate a skill against a benchmark?', 'Can you detect regressions?'],
      techniques: ['Constitutional AI for self-evaluation', 'LLM-as-judge for scalable quality assessment'],
      frameworks: ['LangSmith', 'LangChain']
    },
    {
      week: '15', phase: 5, status: 'upcoming',
      title: 'Governance Layer + Security & Secrets',
      learn: ['RBAC design — roles, permissions, access control', 'Approval system design', 'Auditability requirements', 'Policy engine — encode organizational rules', 'Secrets management — never hardcode API keys, use a vault or env layer', 'Token scoping — tool permissions should be minimal by default', 'Sensitive data redaction — PII, credentials, internal code must not appear in logs or traces'],
      build: ['Approval engine', 'Role-permission matrix', 'Audit log — every tool call, decision, output recorded', 'Policy engine', 'RBAC enforcement', 'Security & Secrets layer: secrets manager integration (env vars → vault → rotation), API key scoping per tool, OAuth token design, tool permission scopes (read-only vs read-write vs admin)', 'Sensitive data redaction — strip PII and credentials from all LangSmith traces and Work Ledger logs', 'Work Ledger v3 — approval logging: every approve/reject decision recorded with approver, timestamp, and reason', 'Audit-safe log policy — what is logged vs what is redacted by default'],
      output: 'Governance v1 + Security layer. Every action auditable. Approvals logged. Secrets safe. PII redacted from traces.',
      goal: 'Add enterprise trust and security boundaries simultaneously — governance without secrets management is incomplete.',
      concepts: ['RBAC', 'approval routing', 'auditability', 'policy controls', 'secrets management', 'token scoping', 'data redaction', 'audit-safe logging'],
      deliverables: ['Approval engine', 'Permission matrix', 'Audit log', 'Policy engine', 'Secrets layer', 'Redaction policy', 'Approval Work Ledger records'],
      risks: ['Allowing unsafe actions too early', 'No traceability', 'API keys hardcoded in codebase', 'PII in LangSmith traces visible to anyone with project access'],
      checkpoints: ['Can you explain who can approve what?', 'Can every action be audited?', 'Are secrets stored outside codebase?', 'Is PII redacted before hitting LangSmith traces?'],
      techniques: ['Governance before autonomy — the correct order', 'Least-privilege tool scoping — tools get only the access they need'],
      frameworks: ['LangGraph (interrupt gates)', 'LangChain']
    },
    {
      week: '16', phase: 5, status: 'upcoming', milestone: true, milestoneDemo: 'ARIA recommends an action → routes to approval → waits → continues after human approval. Model Router routes classification to SLM.',
      title: 'Controlled Autonomy + Model Router',
      learn: ['Action tiers in practice — Read, Recommend, Draft, Execute-with-Approval, Autonomous', 'Safe autonomy', 'Confidence + escalation', 'Risk scoring', 'Model routing concept — not every task needs a frontier model', 'SLMs (Phi-3-mini, Qwen-0.5B, Gemma-2B) for classification, routing, extraction'],
      build: ['Action tier enforcement', 'Draft/send/trigger action layer', 'Risk scoring logic', 'Approval-aware execution — pause → await → resume', 'Confidence threshold gating', 'Model Router v1 — route classification/extraction tasks to SLM, complex reasoning to frontier model', 'Proactive Teams notification framework — ARIA pushes updates without being asked; framework defines: trigger conditions (5 engineering-critical types), message format (what happened + why you\'re getting this + what action you can take), approval-aware delivery (T4+ actions require approval before notification sent), rate limiting (max 3 unprompted notifications per day to prevent noise)'],
      output: 'Controlled action layer live. Model Router v1 routing classification to SLM — first measurable API cost reduction.',
      goal: 'Move from recommendation-only to governed execution. Introduce model routing so not every task burns expensive frontier model tokens.',
      concepts: ['action tiers', 'escalation', 'confidence gating', 'safe autonomy', 'model routing', 'SLMs for utility tasks'],
      deliverables: ['Action layer', 'Risk scoring', 'Approval-aware execution', 'Model Router v1', 'SLM integration'],
      risks: ['Over-automation', 'SLM quality too low for task — need fallback to frontier model'],
      checkpoints: ['Can the system safely draft vs execute?', 'Can it escalate when uncertain?', 'Does the model router correctly classify and route?'],
      techniques: ['Graduated autonomy — governance before autonomy', 'Model routing — right model for right task'],
      frameworks: ['LangGraph', 'LangChain', 'vLLM']
    },
    {
      week: '17', phase: 5, status: 'upcoming',
      title: 'QA / Test Case Generation',
      learn: ['Functional test design — happy path, negative, edge cases', 'Requirement-to-test mapping', 'Test pyramid — unit, integration, e2e', 'AI/ML testing — prompt regression, schema mismatch, output drift', 'AutoGen framework architecture — ConversableAgent, GroupChat, actor-model pattern, how it differs from LangGraph\'s graph-based approach', 'When conversational multi-agent (AutoGen) beats stateful graph orchestration (LangGraph) — and vice versa'],
      build: ['Test case generation skill', 'Positive/negative/edge case generator', 'QA artifact templates', 'Requirement parsing layer', 'AI/ML test cases — model output validation', 'Study AutoGen docs + annotate ConversableAgent and GroupChat patterns (learning artifact, not production code)'],
      output: 'QA skill v1. ARIA generates meaningful, mapped test cases for real PRs. AutoGen patterns understood.',
      goal: 'Give the platform a serious QA capability tied to real engineering workflows. Begin AutoGen study for Week 22 comparison.',
      concepts: ['test case design', 'requirement mapping', 'QA artifacts', 'AI/ML testing', 'AutoGen conversational multi-agent', 'ConversableAgent', 'GroupChat'],
      deliverables: ['Test case generation skill', 'QA templates', 'Requirement parsing', 'AI/ML test cases', 'AutoGen annotated study notes'],
      risks: ['Only generic test cases', 'No mapping to real requirements'],
      checkpoints: ['Can it generate meaningful test cases?', 'Do they cover core paths?', 'Can you explain how AutoGen ConversableAgent differs from LangGraph StateGraph?'],
      techniques: ['Test pyramid methodology', 'AI/ML-specific test design', 'AutoGen patterns — study for Week 17–22 comparison'],
      frameworks: ['LangChain', 'LangGraph', 'AutoGen']
    },
    {
      week: '18', phase: 5, status: 'upcoming',
      title: 'Test Review & Regression Intelligence',
      learn: ['Coverage review — what is tested vs what matters', 'Regression risk', 'Failed test analysis', 'AutoGen GroupChat + termination conditions + code execution patterns — deepen study from Week 17'],
      build: ['Test case review skill', 'Failed test summary skill', 'Coverage gap detection', 'Regression checklist generator', 'Release QA summary', 'Small 2-agent AutoGen experiment: CodeReviewerAgent + TestGeneratorAgent — learning side project, not production code'],
      output: 'QA skill v2. ARIA reviews tests critically and identifies coverage gaps. AutoGen 2-agent demo working.',
      goal: 'Move from generating tests to evaluating coverage and identifying risk gaps. Build first AutoGen demo to understand the framework hands-on before Week 22 comparison.',
      concepts: ['coverage review', 'regression risk', 'failed test interpretation', 'AutoGen 2-agent demo', 'GroupChat termination'],
      deliverables: ['Test review skill', 'Failed test summarizer', 'Coverage gap logic', 'QA summary', 'AutoGen 2-agent learning demo'],
      risks: ['Weak coverage analysis', 'No distinction between functional and regression issues'],
      checkpoints: ['Can it review tests critically?', 'Can it identify meaningful gaps?', 'Is the AutoGen 2-agent demo running? Can you explain when AutoGen\'s conversational approach beats LangGraph\'s graph approach?'],
      techniques: ['AutoGen 2-agent demo — CodeReviewerAgent + TestGeneratorAgent'],
      frameworks: ['LangChain', 'LangGraph', 'AutoGen']
    },
    {
      week: '19', phase: 5, status: 'upcoming',
      title: 'CI/CD Intelligence',
      learn: ['CI/CD lifecycle — build, test, deploy stages', 'Release readiness', 'Failure triage patterns'],
      build: ['CI/CD failure summary skill', 'Build log analysis skill', 'Release readiness skill', 'Rollback summary skill', 'Post-deploy validation', 'Proactive CI/CD alerts: when pipeline fails, ARIA proactively sends Teams message to PR author — "Your pipeline failed. Root cause: X. Suggested fix: Y. Release blocked until resolved." No @mention needed.'],
      output: 'CI/CD capability v1. ARIA summarizes pipeline failures and assesses release readiness.',
      goal: 'Expand the platform into deployment and release workflows.',
      concepts: ['pipeline stages', 'failure triage', 'release readiness', 'rollback decisions'],
      deliverables: ['CI/CD failure skill', 'Release readiness skill', 'Deployment summary artifact'],
      risks: ['No clear distinction between advisory and execution', 'Weak release risk thinking'],
      checkpoints: ['Can it summarize pipeline failures well?', 'Can it produce release-readiness output?'],
      techniques: [],
      frameworks: ['LangChain', 'LangGraph']
    },
    {
      week: '20', phase: 5, status: 'upcoming', milestone: true, milestoneDemo: 'Full AI Engineer suite: one task triggers Jira ticket creation + CI/CD failure summary + test gen + artifact delivery',
      title: 'Jira / Delivery Intelligence + Reporting',
      learn: ['Story decomposition', 'Acceptance criteria design', 'Backlog + blocker handling', 'Audience-specific reporting'],
      build: ['Jira ticket creation skill', 'Ticket refinement skill', 'Sprint/blocker summary skill', 'Leadership summary skill', 'Stakeholder email skill', 'Technical-to-business translation', 'Proactive Jira/blocker alerts: when a sprint blocker is detected or a ticket is overdue, ARIA proactively notifies the assignee in Teams — "Blocker detected on [ticket]. Blocking [N] downstream items. Suggested escalation: [person/action]."'],
      output: 'Jira/Delivery v1 + Reporting v1. ARIA creates actionable stories and leadership summaries.',
      goal: 'Support delivery management, work tracking, and leadership communication.',
      concepts: ['delivery intelligence', 'ticket quality', 'backlog health', 'audience-specific outputs'],
      deliverables: ['Jira creation skill', 'Ticket refinement', 'Sprint/blocker summary', 'Leadership summary'],
      risks: ['Only generating vague tickets', 'No audience differentiation in reports'],
      checkpoints: ['Can it produce actionable stories?', 'Can it generate a leadership-ready summary?'],
      techniques: [],
      frameworks: ['LangChain', 'LangGraph']
    },
    {
      week: '21', phase: 6, status: 'upcoming',
      title: 'Agent Runtime Harness + Tool Execution Harness + Prompt Depth',
      learn: ['Retries + exponential backoff', 'Timeout handling', 'Idempotency', 'Resumability + checkpointing', 'Failure classification', 'DSPy — treat prompts as parameters, optimize systematically', 'Instructor — structured output enforcement', 'Outlines — constrained generation', 'Tool execution safety — why every tool call needs validation, not just the LLM output'],
      build: ['Agent Runtime Harness — wraps all agent execution with retry, timeout, checkpointing, failure classification', 'Retry logic with backoff', 'Execution guardrails', 'Failure classifier', 'Checkpointing + resumability', 'DSPy prompt optimizer', 'Instructor integration — typed, validated LLM outputs', 'Tool Execution Harness — wraps every tool call with: input schema validation (reject malformed inputs early), output schema validation, configurable timeout per tool, retry policy per tool type, permission check before execution, risk level tag (read / write / destructive), idempotency key (safe to retry), dry-run mode (simulate without side effects), approval_required flag for Tier 4 tools', 'Safety Harness — output filtering, rate limiting, cost circuit breaker (stop if spend exceeds budget)'],
      output: 'Runtime harness v1 + Tool Execution Harness + optimized prompts. Every tool call is validated, logged, and safe. Failed tasks resume.',
      goal: 'Make the runtime and tool layer both enterprise-robust. A runtime harness without a tool harness is incomplete — most failures happen at tool boundaries.',
      concepts: ['reliability engineering', 'checkpointing', 'safe failure behavior', 'DSPy', 'Instructor', 'tool input/output validation', 'idempotency', 'dry-run mode', 'cost circuit breaker'],
      deliverables: ['Runtime harness', 'Tool Execution Harness', 'Safety Harness', 'Retry logic', 'Guardrails', 'Failure classification', 'DSPy optimizer'],
      risks: ['Fragile long-running flows', 'No recovery strategy', 'Tool calls with no input validation — garbage in, expensive garbage out'],
      checkpoints: ['Can a failed task be resumed?', 'Can runtime issues be classified and handled?', 'Can every tool call be run in dry-run mode?', 'Does the permission check fire before a write tool executes?'],
      techniques: ['DSPy — systematic prompt optimization', 'Instructor — structured outputs', 'Tool Execution Harness — treats every tool as a typed, validated, permission-gated contract'],
      frameworks: ['LangGraph', 'LangChain', 'DSPy', 'Instructor']
    },
    {
      week: '22', phase: 6, status: 'upcoming',
      title: 'Agent Factory + CrewAI + Multi-Agent Patterns',
      learn: ['Skill vs agent vs workflow — when is each the right abstraction?', 'Capability lifecycle — draft → test → approve → active → deprecated', 'Sandboxing + promotion', 'CrewAI — role-based multi-agent orchestration (hands-on, not just reference)', 'CrewAI: Crew, Agent, Task, Process concepts', 'AutoGen comparison — when conversational multi-agent beats role-based crews; when to choose CrewAI vs AutoGen vs LangGraph'],
      build: ['CrewAI crew implementation — Analytics + QA crew with defined roles, tasks, and process', 'Capability request flow — propose new skill/agent/workflow', 'Agent/skill/workflow classifier', 'Scaffold generator', 'Sandbox Runner — safe execution environment for new capabilities: dry-run mode (execute with fake/mock data), staging mode (run against staging env not prod), restricted tool mode (new capability only gets read-only tools until approved), approval-only mode (every action requires human sign-off during sandbox phase), isolation boundary (sandbox agent cannot access production Work Ledger or prod memory)', 'Capability registry', 'Evaluation before promotion — must pass rubrics before activation', 'AutoGen comparison exercise — replicate a subset of the CrewAI crew in AutoGen; document architectural tradeoffs between the two approaches', 'Work Ledger v4 — delivery outcome logging: link Jira tickets, PR merges, and CI/CD results to task records for end-to-end ROI tracking'],
      output: 'Agent Factory v1 + real CrewAI crew live. AutoGen comparison exercise done. ARIA proposes new capabilities. All 3 multi-agent frameworks understood hands-on.',
      goal: 'Build the Agent Factory AND get real hands-on experience with CrewAI. Compare vs AutoGen demo from Week 18. By end of this week you can speak confidently about LangGraph vs CrewAI vs AutoGen tradeoffs in interviews.',
      concepts: ['capability creation', 'sandbox promotion', 'capability lifecycle', 'CrewAI roles + tasks + crew', 'multi-agent coordination', 'AutoGen vs CrewAI architectural tradeoffs'],
      deliverables: ['CrewAI Analytics+QA crew', 'Capability request flow', 'Classifier', 'Scaffold generator', 'Registry', 'AutoGen vs CrewAI tradeoff doc'],
      risks: ['Creating agents without governance', 'Understanding CrewAI vs LangGraph vs AutoGen tradeoffs'],
      checkpoints: ['Is the CrewAI crew running with real role-based coordination?', 'Can the Agent Factory propose a new capability?', 'Can you explain when you would choose CrewAI vs AutoGen vs LangGraph?'],
      techniques: ['CrewAI role-based multi-agent design — real implementation, not just reference', 'LangGraph vs CrewAI vs AutoGen comparison — when to use each framework'],
      frameworks: ['CrewAI', 'LangGraph', 'LangChain', 'AutoGen']
    },
    {
      week: '23', phase: 6, status: 'upcoming',
      title: 'Schema/Protocol Design + Evolution Monitoring',
      learn: ['Task, skill, artifact, approval schemas — typed contracts', 'MCP (Model Context Protocol) — tool standardization', 'A2A (Agent-to-Agent) basics', 'AI ecosystem monitoring — arxiv, GitHub, HuggingFace, LangChain blog'],
      build: ['Schema library', 'MCP tool definitions', 'A2A protocol stub', 'Evolution Intelligence: monitoring layer — daily digest', 'Relevance scoring', 'Capability proposal flow stub'],
      output: 'Protocol + evolution v1. Contracts clean. ARIA tracks AI ecosystem daily.',
      goal: 'Clean contracts, future-ready protocols, Evolution Intelligence begins monitoring.',
      concepts: ['schemas', 'tool contracts', 'MCP', 'A2A', 'evolution intelligence'],
      deliverables: ['Schema library', 'MCP tool defs', 'A2A stub', 'Evolution monitoring layer'],
      risks: ['Loose interfaces', 'No future-ready protocol discipline'],
      checkpoints: ['Are your task/skill/artifact contracts clean?', 'Does ARIA produce a daily AI digest?'],
      techniques: ['MCP — tool standardization', 'A2A — future agent interoperability'],
      frameworks: ['LangChain (MCP tools)', 'LangGraph']
    },
    {
      week: '24', phase: 6, status: 'upcoming', milestone: true, milestoneDemo: 'Full end-to-end: task received via Teams @mention → orchestrated → skill executed → artifact delivered → logged in Work Ledger. Flagship demo v1.',
      title: 'Packaging, CV Story, Demo Polish',
      learn: ['How to defend architecture choices', 'How to tell the project story in 1 min, 5 min, 30 min', 'How to position the moat and value'],
      build: ['Final documentation pass', 'Architecture defense deck', 'Resume bullets — all Week 1-24 capabilities', 'Demo script v1', 'Portfolio summary for LinkedIn + interviews'],
      output: 'Flagship project package v1. Can explain ARIA in any timeframe to any audience.',
      goal: 'Turn the built platform into a career asset. Prepare for the bigger launch ahead.',
      concepts: ['storytelling', 'portfolio packaging', 'CV framing', 'architecture defense'],
      deliverables: ['Final docs', 'Portfolio summary', 'Architecture deck', 'Resume bullets'],
      risks: ['Under-selling the project', 'No clean story for interviews'],
      checkpoints: ['Can you explain the platform in 1 minute and 5 minutes?', 'Can you explain why it is hard to copy?'],
      techniques: [],
      frameworks: []
    },
    {
      week: '25', phase: 7, status: 'upcoming',
      title: 'Agent Control Plane + Workforce Orchestration',
      learn: ['Agent 365 concept — enterprise HR for AI agents', 'Workforce orchestration — spawn, assign, monitor, coordinate, retire', 'Agent health monitoring', 'Parallel agent execution — fan-out / fan-in patterns'],
      build: ['Agent Control Plane — registry + health dashboard + lifecycle management', 'Workforce manager — spawn agents, assign tasks, collect results', 'Parallel execution — fan-out to 3+ agents simultaneously', 'Agent monitoring dashboard'],
      output: 'ARIA manages a 5-agent team. Control Plane shows all agents live.',
      goal: 'ARIA manages her own agent team. She is now an AI manager, not just an AI worker.',
      concepts: ['agent registry', 'workforce management', 'parallel execution', 'agent health'],
      deliverables: ['Agent Control Plane', 'Workforce manager', 'Health dashboard', 'Parallel execution'],
      risks: ['Agent coordination complexity', 'No clear result synthesis'],
      checkpoints: ['Can ARIA manage a 3-agent team?', 'Is the Control Plane showing agent health live?'],
      techniques: ['Fan-out / fan-in parallel agent coordination'],
      frameworks: ['LangGraph', 'CrewAI (compare workforce patterns)', 'LangChain']
    },
    {
      week: '26', phase: 7, status: 'upcoming',
      title: 'Analytics Depth + Decision Intelligence + Workflow Mining',
      learn: ['RAPTOR — recursive summarization for long docs', 'GraphRAG — knowledge graph-based retrieval', 'LATS (Language Agent Tree Search) — multi-step decision exploration', 'Workflow mining — detect recurring manual work'],
      build: ['EDA skill depth — full exploratory analysis', 'Experiment analysis skill', 'Model monitoring summary skill', 'RAPTOR integration', 'GraphRAG integration', 'Workflow mining engine', 'Decision tree builder'],
      output: 'ARIA investigates complex KPI drop with full analytics depth. Identifies 5 automation opportunities.',
      goal: 'Full Data Science capabilities + better decision reasoning + automation discovery.',
      concepts: ['RAPTOR', 'GraphRAG', 'LATS', 'workflow mining', 'decision intelligence'],
      deliverables: ['EDA skill', 'Experiment analysis', 'RAPTOR + GraphRAG', 'Workflow mining engine'],
      risks: ['RAPTOR/GraphRAG complexity', 'Workflow mining false positives'],
      checkpoints: ['Can ARIA do a full EDA?', 'Does workflow mining surface real automation candidates?'],
      techniques: ['RAPTOR for long docs', 'GraphRAG for knowledge graphs', 'LATS for decision exploration'],
      frameworks: ['LangChain (retrievers)', 'LangGraph']
    },
    {
      week: '27', phase: 8, status: 'upcoming',
      title: 'Evolution Intelligence: Evaluate & Propose',
      learn: ['How to evaluate a new framework against existing capabilities', 'LATS for capability gap analysis', 'How to write a capability proposal (effort, benefit, risk)'],
      build: ['Capability evaluator — ARIA reads paper/framework, compares to her skills', 'Gap identifier', 'Capability proposal generator', 'Proposal inbox — Kunal reviews + approves/rejects', 'Outcome tracker', 'AutoGen-powered evolution proposal review: 3-agent debate — ResearchAgent (reads the paper, extracts the technique) vs SkepticsAgent (challenges whether ARIA needs this, what the integration risk is) vs ImplementationAgent (estimates effort, drafts integration plan) — conversational debate → structured proposal document. This is the first production use of AutoGen where its conversational back-and-forth beats a fixed LangGraph graph.'],
      output: 'ARIA submits first real capability proposal from a real arxiv paper, stress-tested by a 3-agent debate.',
      goal: 'ARIA reads AI ecosystem, identifies gaps, submits integration proposals. The AutoGen debate pattern ensures proposals are challenged before reaching Kunal — reducing noise and raising quality.',
      concepts: ['capability evaluation', 'gap analysis', 'proposal design', 'evolution intelligence', 'AutoGen debate pattern'],
      deliverables: ['Capability evaluator', 'Gap identifier', 'Proposal generator', 'Proposal inbox', 'AutoGen 3-agent debate crew'],
      risks: ['Proposals too generic', 'No clear effort/benefit estimate', 'AutoGen debate loop not terminating cleanly — set max_turns and a termination keyword'],
      checkpoints: ['Has ARIA submitted a proposal from a real paper?', 'Is the proposal structured and actionable?', 'Did the 3-agent debate surface at least one genuine objection that improved the proposal?'],
      techniques: ['LATS for multi-path capability gap analysis', 'AutoGen conversational debate — bounded production use where back-and-forth critique beats a fixed graph'],
      frameworks: ['LangGraph', 'LangChain', 'AutoGen']
    },
    {
      week: '28', phase: 8, status: 'upcoming',
      title: 'Evolution Intelligence: Integrate + Marketplace',
      learn: ['Constitutional AI safety checks for self-integration', 'How to write safe, testable, sandboxed capability code', 'Marketplace design'],
      build: ['Self-integration pipeline — design → code → test → sandbox → propose → approve → deploy', 'Integration safety checker — Constitutional AI review at each stage', 'Sandbox auto-eval — capability must pass rubrics in Sandbox Runner before leaving staging', 'Sandbox isolation enforcement — new capability runs in isolated sandbox with restricted tool access, mock Work Ledger, and approval-only execution mode until promoted', 'Promotion gate — human approval required to move capability from sandbox to production; rollback plan documented before every promotion', 'AI Capability Marketplace', 'Team adoption tracking'],
      output: 'ARIA self-integrates first approved capability through the full sandbox pipeline. Marketplace live. Self-evolution loop proven end-to-end.',
      goal: 'ARIA integrates an approved capability herself — but only after passing isolation, eval, and human approval. The sandbox is what makes self-evolution safe.',
      concepts: ['self-integration', 'Constitutional AI', 'sandbox isolation', 'promotion gates', 'marketplace design', 'adoption tracking'],
      deliverables: ['Self-integration pipeline', 'Safety checker', 'Sandbox isolation layer', 'Promotion gate', 'Marketplace', 'Adoption tracking'],
      risks: ['Integration breaks existing capabilities', 'Safety check too permissive', 'Sandbox not truly isolated — new code can touch prod systems'],
      checkpoints: ['Has ARIA successfully self-integrated one capability through the full pipeline?', 'Did the sandbox isolation hold?', 'Was there a human approval gate before production promotion?', 'Is the Marketplace browsable?'],
      techniques: ['Constitutional AI for integration safety', 'Sandbox-first promotion — nothing touches production without passing isolation + eval + human approval'],
      frameworks: ['LangGraph', 'LangChain']
    },
    {
      week: '29', phase: 8, status: 'upcoming',
      title: 'AI Work Ledger Complete + ROI Dashboard + Fine-Tuning Prototype + Model Registry',
      learn: ['ROI measurement for AI systems', 'How to prove AI value to leadership with hard numbers', 'LoRA/QLoRA fine-tuning — Unsloth + TRL SFTTrainer', 'vLLM serving — PagedAttention, OpenAI-compatible API', 'DPO — preference alignment from approval/rejection pairs'],
      build: ['AI Work Ledger v5 — complete all 10 record types (builds on Weeks 4/8/13/15/22 foundations)', 'Autonomous Improvement Backlog — every rejection/failure/correction auto-queued as prioritized improvement item', 'ROI Dashboard — "ARIA completed X tasks, saved Y hours, caught Z deployment risks, improved test coverage by W%"', 'ARIA performance summary — automated weekly self-report', 'Fine-tuning prototype — prepare_dataset.py → train_lora.py (Unsloth + TRL, QLoRA rank=16) → eval_finetuned.py; first candidate: Qwen2.5-Coder-7B for PR review; benchmark against Llama-3.1-8B-Instruct before calling it final', 'Serve prototype via vLLM at localhost:8000 — intelligent model router v2: PR review tasks → local fine-tuned model, complex reasoning → Claude Opus', 'Model Lifecycle Registry v1 — version, base model, dataset used, eval score, endpoint, rollback pointer', 'AutoGen ML Research peer review: PaperReaderAgent + ExperimentDesignerAgent + RiskReviewerAgent — 3-agent debate reviews proposed fine-tuning experiment before Kunal approves', 'NOTE: Production-grade fine-tuned PR reviewer is V2 scope unless the prototype eval scores exceed baseline — if quality gap > 15%, defer to V2 and focus Week 29 on ROI + ledger completion'],
      output: 'Work Ledger complete with 25 weeks of accumulated data. ROI proven with hard numbers. Fine-tuning prototype benchmarked. Model Registry v1 live.',
      goal: 'Complete the data layer and prove business value. Fine-tuning prototype validates the approach — production deployment is V2 unless benchmark results are exceptional.',
      concepts: ['AI Work Ledger completion', 'ROI measurement', 'LoRA fine-tuning', 'vLLM inference', 'DPO preference alignment', 'model benchmarking', 'Model Lifecycle Registry'],
      deliverables: ['AI Work Ledger (all 10 record types)', 'ROI Dashboard', 'Fine-tuning prototype (Qwen2.5-Coder-7B)', 'Benchmark comparison (Qwen vs Llama)', 'vLLM server (prototype)', 'Model Lifecycle Registry v1'],
      risks: ['ROI metrics too vague — define exact formulas before building dashboard', 'Insufficient Work Ledger data — 25 weeks should be enough but use synthetic data if PR review examples < 50', 'GPU cost — use RunPod A40 at $0.40/hr; single training run ~$0.80', 'Premature production deployment — benchmark first, ship to prod only if quality > baseline'],
      checkpoints: ['Can ARIA quantify her contribution with specific numbers?', 'Has the fine-tuning prototype been benchmarked against Qwen2.5-Coder-7B AND Llama-3.1-8B-Instruct?', 'Is the Model Registry tracking version, dataset, eval score, and rollback pointer?', 'Did the AutoGen peer review surface any risks in the fine-tuning approach?'],
      techniques: ['LoRA/QLoRA fine-tuning on Work Ledger approved outputs', 'Benchmark before deploy — compare candidates on LangSmith rubric before choosing production model', 'AutoGen ML Research peer review — bounded production use for experiment quality gate'],
      frameworks: ['LangGraph', 'LangChain', 'LangSmith', 'Unsloth', 'vLLM', 'AutoGen']
    },
    {
      week: '30', phase: 9, status: 'upcoming', milestone: true, milestoneDemo: 'Live demo + ROI dashboard + Work Ledger view + Agent Control Plane + Yukti complement presentation. The world sees ARIA.',
      title: 'Launch + Productization + Career Positioning',
      learn: ['How to position a career-defining project to multiple audiences — engineers, PMs, leadership, hiring managers', 'How to write a LinkedIn post that gets shared', 'How to defend architecture choices in a 30-min interview', 'Productization: what makes an internal tool into a sellable platform'],
      build: ['Final demo polish — ARIA performing real tasks live (PR review, KPI investigation, test gen — include Amar Ujala media-tech examples)', 'Demo video with narration', 'Architecture defense deck — 10 slides: problem, solution, architecture, 24 pillars, moat, results, roadmap', 'LinkedIn post (ARIA helps draft it — meta moment)', 'Internal presentation — surprise reveal to manager + leadership with live demo', 'GitHub repo prep — clean README, architecture diagrams, demo GIFs, one-liner install', 'Resume final update — 30 weeks × 6 artifacts = 180 documented outputs, distilled to 8 bullets', 'Portfolio case study — detailed write-up: what you built, why, what you learned, what you would do differently', 'AI Employee as a Service blueprint — productization roadmap: multi-tenant architecture, private deployment (VPC/on-prem), customer workspace design, capability marketplace, billing layer, SaaS vs enterprise licensing model', 'ARIA + Yukti positioning note — complement framing, NOT competition: "Yukti defines the organisational operating model. ARIA is the execution intelligence layer that performs AI engineering, analytics, QA, CI/CD, Jira, reporting, and governed self-evolution work inside that ecosystem. Together they form a complete AI-native organisation." Present this as strengthening the manager\'s vision, not replacing it.'],
      output: 'The world sees what one person built in 30 weeks. AaS roadmap documented. Yukti differentiation written. Career moat established.',
      goal: 'Execute the launch AND document the product roadmap. The reveal should be accompanied by a clear vision for where this goes next — that\'s what separates a project from a platform.',
      concepts: ['positioning', 'narrative', 'career branding', 'launch strategy', 'productization', 'AaS blueprint', 'competitive differentiation'],
      deliverables: ['Demo video', 'Architecture deck', 'LinkedIn post', 'Internal presentation', 'Clean GitHub repo', 'Portfolio case study', 'AaS blueprint', 'Resume bullets (all 30 weeks)', 'ARIA vs Yukti positioning note'],
      risks: ['Under-selling the project', 'No live demo ready', 'AaS blueprint too vague to be useful', 'Positioning note sounds defensive rather than confident'],
      checkpoints: ['Is the demo flawless?', 'Can you explain the architecture in 5 minutes to a non-technical leader?', 'Does the AaS blueprint show a credible next step?', 'Does the positioning note make ARIA\'s advantage clear without attacking?', 'Does the LinkedIn post tell a compelling, shareable story?'],
      techniques: ['Productization thinking — features become pillars, pillars become a platform', 'Competitive positioning — differentiate on depth, not just features'],
      frameworks: []
    }
  ];

  const capabilityPillars = [
    { num: 1,  name: 'Conversational Tasking',          week: '3-4',   v: 'V1' },
    { num: 2,  name: 'AI Engineering',                  week: '7-10',  v: 'V1' },
    { num: 3,  name: 'Data Science & Analytics',        week: '26',    v: 'V2' },
    { num: 4,  name: 'QA / Test Intelligence',          week: '17-18', v: 'V1' },
    { num: 5,  name: 'CI/CD & Release',                 week: '19',    v: 'V1' },
    { num: 6,  name: 'Jira / Delivery Management',      week: '20',    v: 'V1' },
    { num: 7,  name: 'Reporting & Communication',       week: '20',    v: 'V1' },
    { num: 8,  name: 'Knowledge / RAG / Org Intel',     week: '9',     v: 'V1' },
    { num: 9,  name: 'Code Intelligence',               week: '10',    v: 'V1' },
    { num: 10, name: 'Governance & Trust',              week: '15-16', v: 'V1' },
    { num: 11, name: 'Agent Runtime Harness',           week: '21',    v: 'V1' },
    { num: 12, name: 'Agent Evaluation Harness',        week: '14',    v: 'V1' },
    { num: 13, name: 'Agent Factory',                   week: '22',    v: 'V2' },
    { num: 14, name: 'AI Workforce Expansion',          week: '25',    v: 'V2' },
    { num: 15, name: 'Agent Control Plane',             week: '25',    v: 'V2' },
    { num: 16, name: 'AI Work Ledger',                  week: '29',    v: 'V2' },
    { num: 17, name: 'Human Teaching Layer',            week: '11-12', v: 'V1' },
    { num: 18, name: 'Evolution & Capability Intel',    week: '23-28', v: 'V3' },
    { num: 19, name: 'Workflow Mining',                 week: '26',    v: 'V2' },
    { num: 20, name: 'Decision Intelligence',           week: '26',    v: 'V2' },
    { num: 21, name: 'Confidence, Cost & Risk',         week: '21',    v: 'V2' },
    { num: 22, name: 'AI Capability Marketplace',       week: '28',    v: 'V3' },
    { num: 23, name: 'AI Employee as a Service',        week: '29',    v: 'V3' },
    { num: 24, name: 'Model Intelligence & Post-Training', week: '16–29', v: 'V2' },
  ];

  const selfEvolutionTypes = [
    ['Prompt evolution',       'Better instructions, better output formats',              'Low rubric score + rejection pattern'],
    ['Skill evolution',        'Skills become more accurate and useful over versions',     'User corrections + outcome tracking'],
    ['Workflow evolution',     'Repeated tasks become structured reusable workflows',      'Workflow Mining detects repetition (10x)'],
    ['Agent evolution',        'New specialist agents proposed and created',               'Repeated capability requests to Agent Factory'],
    ['Memory evolution',       'System learns preferences and past outcomes',              'User correction + outcome linkage'],
    ['Tool evolution',         'New tools/connectors added',                              'Evolution radar identifies useful new tool/MCP server'],
    ['Policy evolution',       'Approval/risk rules improve from outcome data',            'Outcome data shows policy is miscalibrated'],
    ['Model-routing evolution','Better model chosen per task type over time',              'Cost/quality tracking shows suboptimal routing'],
    ['Evaluation evolution',   'Better benchmarks and rubrics added',                     'Current rubrics miss important quality dimensions'],
  ];

  const learningCurriculum = [
    ['LangChain (LCEL, Chains, Tools)',  '3',       'Foundation: prompt templates, chains, tool definitions — the layer LangGraph builds on', 'LangChain'],
    ['LangGraph',                        '3',       'Stateful orchestration backbone — every ARIA workflow is a LangGraph StateGraph', 'LangGraph'],
    ['ReAct',                            '4',       'Orchestrator reasoning loop: Think → Act → Observe → Reflect', 'Pattern'],
    ['Chain of Thought',                 '5',       'Complex task planning step inside skills', 'Pattern'],
    ['MemGPT/Letta patterns',            '11',      'Memory paging + consolidation — OS-style context management', 'Pattern'],
    ['HyDE',                             '9',       'Enhanced retrieval for sparse queries', 'Pattern'],
    ['Self-RAG',                         '9',       'ARIA critiques her own retrieval before using it', 'Pattern'],
    ['RAPTOR',                           '26',      'Hierarchical long document summarization', 'Pattern'],
    ['GraphRAG',                         '26',      'Org knowledge as a traversable graph', 'Pattern'],
    ['AutoGen (Study + Comparison)',      '17–22',   'Learn conversational multi-agent patterns; build 2-agent demo at Week 18; compare vs CrewAI at Week 22 — understand all 3 frameworks', 'AutoGen'],
    ['CrewAI',                           '22',      'Real hands-on: Analytics + QA crew with role-based agents', 'CrewAI'],
    ['DSPy',                             '21',      'Systematic prompt optimization — prompts as parameters', 'DSPy'],
    ['Instructor',                       '21',      'Typed, validated LLM outputs — every skill returns Pydantic model', 'Instructor'],
    ['Outlines / Guidance',              '21',      'Constrained generation — guaranteed schema compliance', 'Pattern'],
    ['Constitutional AI',                '14 + 28', 'Output safety checks + self-integration safety gate', 'Pattern'],
    ['LATS',                             '26-27',   'Decision tree search + capability gap analysis', 'Pattern'],
    ['Eval-Lite',                         '6',       'Minimum eval for every skill from Day 1: 5 golden examples, 3 failure cases, schema check, 1–5 rubric — full harness at Week 14', 'Pattern'],
    ['LangSmith evals',                  '14',      'Rubric + regression framework — quality as a system (upgrades Eval-Lite into full harness)', 'LangSmith'],
    ['MCP',                              '23+',     'Tool standardization — all ARIA tools as MCP-compatible', 'Protocol'],
    ['A2A protocol',                     '23+',     'Future agent interoperability', 'Protocol'],
    ['SLM (Small Language Models)',        '16',      'Phi-3-mini / Qwen-0.5B / Gemma-2B for cheap/fast classification, routing, extraction — NOT everything needs a 7B model', 'Pattern'],
    ['Model Router / Gateway',            '16',      'Route each task: SLM → fine-tuned local → frontier API — based on risk, complexity, cost, privacy', 'Pattern'],
    ['Model Lifecycle Registry',          '29',      'Track model version, dataset used, eval score, endpoint, rollback pointer — MLOps for ARIA', 'Pattern'],
    ['LoRA / QLoRA fine-tuning',          '29',      'Fine-tune Qwen2.5-Coder-7B on Work Ledger PR review data — institutional knowledge in weights', 'Fine-Tuning'],
    ['vLLM inference serving',            '29',      'Serve fine-tuned model locally via OpenAI-compatible API — zero skill-layer code changes', 'Serving'],
    ['DPO (Direct Preference Optimization)', '29',   'Preference alignment from Work Ledger approve/reject pairs — ARIA learns your taste', 'Fine-Tuning'],
    ['Unsloth',                           '29',      'Memory-efficient LoRA training — 2× faster, fits on RTX 4090 or RunPod A40', 'Unsloth'],
    ['Synthetic Data Generation',         '29',      'Generate training data when Work Ledger examples are sparse — unblocks fine-tuning when real examples < 50', 'Fine-Tuning'],
  ];

  const phaseColors = {
    1: 'bg-slate-100 text-slate-700 border-slate-200',
    2: 'bg-blue-50 text-blue-700 border-blue-200',
    3: 'bg-violet-50 text-violet-700 border-violet-200',
    4: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    5: 'bg-orange-50 text-orange-700 border-orange-200',
    6: 'bg-cyan-50 text-cyan-700 border-cyan-200',
    7: 'bg-pink-50 text-pink-700 border-pink-200',
    8: 'bg-amber-50 text-amber-700 border-amber-200',
    9: 'bg-rose-50 text-rose-700 border-rose-200',
  };

  const phaseNames = {
    1: 'Foundation', 2: 'Build Core', 3: 'First Capabilities',
    4: 'Memory + Identity', 5: 'Domain Skills', 6: 'Intelligence Depth',
    7: 'Workforce', 8: 'Self-Evolution', 9: 'Launch'
  };

  const frameworkColors = {
    'LangChain':  'bg-yellow-50 text-yellow-700 border-yellow-200',
    'LangGraph':  'bg-blue-50 text-blue-700 border-blue-200',
    'LangSmith':  'bg-indigo-50 text-indigo-700 border-indigo-200',
    'CrewAI':     'bg-orange-50 text-orange-700 border-orange-200',
    'DSPy':       'bg-purple-50 text-purple-700 border-purple-200',
    'Instructor': 'bg-teal-50 text-teal-700 border-teal-200',
    'Unsloth':    'bg-rose-50 text-rose-700 border-rose-200',
    'vLLM':       'bg-lime-50 text-lime-700 border-lime-200',
    'Pattern':    'bg-gray-100 text-gray-600 border-gray-200',
    'Protocol':   'bg-slate-100 text-slate-600 border-slate-200',
    'Fine-Tuning':'bg-rose-50 text-rose-700 border-rose-200',
    'Serving':    'bg-lime-50 text-lime-700 border-lime-200',
    'AutoGen':    'bg-amber-50 text-amber-700 border-amber-200',
  };

  const selectedPhase = useMemo(() => phases.find(p => p.week === selectedWeek) || phases[2], [selectedWeek]);

  const tabs = [
    { id: 'plan',       label: '30-Week Plan' },
    { id: 'pillars',    label: '24 Pillars' },
    { id: 'evolution',  label: 'Self-Evolution' },
    { id: 'curriculum', label: 'Learning Curriculum' },
    { id: 'moat',       label: 'Moat Analysis' },
  ];

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 font-sans">
      <div className="max-w-7xl mx-auto px-4 md:px-8 py-10">

        {/* ── Cover ── */}
        <div className="rounded-3xl bg-gradient-to-br from-violet-600 to-violet-800 p-8 md:p-12 mb-8 shadow-lg">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-xs font-bold uppercase tracking-[0.3em] text-violet-200 mb-3">Confidential — 30-Week Master Plan</div>
              <h1 className="text-4xl md:text-6xl font-black tracking-tight text-white">ARIA</h1>
              <div className="text-xl md:text-2xl font-semibold text-violet-100 mt-2">Autonomous Role-based Intelligence Agent</div>
              <p className="text-violet-200 mt-4 max-w-3xl text-base leading-7">
                A governed, self-evolving AI Employee Platform with 24 capability pillars — built to own enterprise work
                end-to-end, manage its own agent workforce, and continuously improve through governed self-evolution.
              </p>
              <div className="mt-4 text-sm text-violet-300">Built by Kunal Mahajan · INMA Global 30 Under 30 in AI (2025)</div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm min-w-[240px]">
              {[['Duration', '30 Weeks'], ['Core Stack', 'LangGraph + LangChain'], ['Pillars', '24 Capabilities'], ['Moat', 'Governed Self-Evolution']].map(([k, v]) => (
                <div key={k} className="rounded-2xl bg-white/15 border border-white/20 p-4 backdrop-blur-sm">
                  <div className="text-violet-200 text-xs">{k}</div>
                  <div className="font-semibold text-white mt-1">{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Positioning ── */}
        <div className="rounded-3xl bg-white border border-gray-200 p-6 mb-8 shadow-sm">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-center mb-4">
            <div className="p-4 rounded-2xl bg-red-50 border border-red-100">
              <div className="text-red-600 font-semibold mb-1">Not a chatbot.</div>
              <div className="text-gray-500 text-sm">Doesn't just answer questions.</div>
            </div>
            <div className="p-4 rounded-2xl bg-amber-50 border border-amber-100">
              <div className="text-amber-700 font-semibold mb-1">Not a copilot.</div>
              <div className="text-gray-500 text-sm">Doesn't assist. Owns work end-to-end.</div>
            </div>
            <div className="p-4 rounded-2xl bg-green-50 border border-green-100">
              <div className="text-green-700 font-semibold mb-1">An AI Employee.</div>
              <div className="text-gray-500 text-sm">Governed, role-capable, self-evolving, enterprise-native.</div>
            </div>
          </div>
          <div className="p-4 rounded-2xl bg-violet-50 border border-violet-200 text-center">
            <p className="text-gray-700 text-sm md:text-base leading-7">
              <span className="font-semibold text-violet-800">The platform is self-evolving in a governed way:</span> it learns from tasks, feedback, approvals, failures, outcomes, and AI industry changes, then proposes, tests, and integrates new skills, agents, workflows, and policies through sandboxing, evaluation, and human approval.
            </p>
          </div>
        </div>

        {/* ── Stack Banner ── */}
        <div className="rounded-2xl bg-white border border-gray-200 px-5 py-3 mb-6 flex items-center gap-3 flex-wrap shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Core Stack:</span>
          {[['LangGraph','bg-blue-100 text-blue-700'], ['LangChain','bg-yellow-100 text-yellow-700'], ['CrewAI','bg-orange-100 text-orange-700'], ['LangSmith','bg-indigo-100 text-indigo-700'], ['DSPy','bg-purple-100 text-purple-700'], ['Instructor','bg-teal-100 text-teal-700'], ['Claude API','bg-violet-100 text-violet-700'], ['FastAPI','bg-green-100 text-green-700']].map(([name, cls]) => (
            <span key={name} className={`px-2.5 py-1 rounded-full text-xs font-semibold ${cls}`}>{name}</span>
          ))}
        </div>

        {/* ── Tabs ── */}
        <div className="flex flex-wrap gap-2 mb-6">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              className={`px-4 py-2 rounded-xl text-sm font-medium border transition-all ${
                activeTab === t.id
                  ? 'bg-violet-600 text-white border-violet-600 shadow-sm'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-violet-400 hover:text-violet-600'
              }`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Tab: 30-Week Plan ── */}
        {activeTab === 'plan' && (
          <>
            {/* Week picker */}
            <div className="rounded-3xl bg-white border border-gray-200 p-6 mb-6 shadow-sm">
              <div className="text-xs font-bold uppercase tracking-[0.2em] text-gray-400 mb-2">Select a Week</div>
              <div className="text-sm text-gray-500 mb-4">Click any week to see Learn / Build / Frameworks / Checkpoints in detail</div>
              <div className="flex flex-wrap gap-2">
                {phases.map(p => (
                  <button key={p.week} onClick={() => setSelectedWeek(p.week)}
                    className={`px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                      selectedWeek === p.week ? 'bg-violet-600 text-white border-violet-600 shadow-sm' :
                      p.status === 'done'   ? 'bg-green-50 text-green-700 border-green-200' :
                      p.status === 'active' ? 'bg-blue-50 text-blue-700 border-blue-300 ring-2 ring-blue-200' :
                      p.milestone           ? 'bg-amber-50 text-amber-700 border-amber-300 hover:border-amber-400' :
                      'bg-white text-gray-500 border-gray-200 hover:border-violet-300 hover:text-violet-600'
                    }`}>
                    W{p.week} {p.status === 'done' ? '✓' : p.status === 'active' ? '▶' : p.milestone ? '★' : ''}
                  </button>
                ))}
              </div>
            </div>

            {/* Week detail */}
            <div className="rounded-3xl bg-white border border-gray-200 p-6 mb-6 shadow-sm">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between mb-6">
                <div>
                  <span className={`inline-block text-xs font-bold uppercase tracking-[0.15em] px-3 py-1 rounded-full border mb-3 ${phaseColors[selectedPhase.phase]}`}>
                    Phase {selectedPhase.phase} — {phaseNames[selectedPhase.phase]}
                  </span>
                  <h2 className="text-2xl font-bold text-gray-900">Week {selectedPhase.week} — {selectedPhase.title}</h2>
                  <p className="text-gray-500 mt-2 max-w-3xl leading-7">{selectedPhase.goal}</p>
                  {/* Framework badges */}
                  {selectedPhase.frameworks?.length > 0 && (
                    <div className="flex gap-2 mt-3 flex-wrap">
                      <span className="text-xs text-gray-400 font-medium mt-0.5">Frameworks:</span>
                      {selectedPhase.frameworks.map(fw => (
                        <span key={fw} className={`text-xs px-2 py-0.5 rounded-full border font-medium ${frameworkColors[fw] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>{fw}</span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex flex-col gap-3 min-w-[220px] shrink-0">
                  {selectedPhase.milestone && (
                    <div className="rounded-2xl bg-amber-50 border border-amber-300 p-4">
                      <div className="text-xs text-amber-600 font-bold uppercase tracking-wide mb-1">★ Milestone Demo Week</div>
                      <div className="text-xs text-amber-800 leading-5">{selectedPhase.milestoneDemo}</div>
                    </div>
                  )}
                  <div className="rounded-2xl bg-violet-50 border border-violet-200 p-4">
                    <div className="text-xs text-violet-500 font-medium mb-1">Week Output</div>
                    <div className="font-semibold text-violet-900 text-sm leading-relaxed">{selectedPhase.output}</div>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-4">
                <div className="rounded-2xl bg-blue-50 border border-blue-200 p-5">
                  <div className="font-semibold text-blue-800 mb-3">📖 What You Learn</div>
                  <ul className="space-y-2">{selectedPhase.learn.map((i, k) => (
                    <li key={k} className="flex gap-2 text-sm text-blue-900"><span className="text-blue-400 mt-0.5 shrink-0">→</span>{i}</li>
                  ))}</ul>
                </div>
                <div className="rounded-2xl bg-gray-50 border border-gray-200 p-5">
                  <div className="font-semibold text-gray-800 mb-3">🔨 What You Build</div>
                  <ul className="space-y-2">{selectedPhase.build.map((i, k) => (
                    <li key={k} className="flex gap-2 text-sm text-gray-700"><span className="text-emerald-500 mt-0.5 shrink-0">▸</span>{i}</li>
                  ))}</ul>
                </div>
                <div className="rounded-2xl bg-amber-50 border border-amber-200 p-5">
                  <div className="font-semibold text-amber-800 mb-3">⚠ Risks to Avoid</div>
                  <ul className="space-y-2">{selectedPhase.risks.map((i, k) => (
                    <li key={k} className="text-sm text-amber-700">⚠ {i}</li>
                  ))}</ul>
                </div>
                <div className="rounded-2xl bg-green-50 border border-green-200 p-5">
                  <div className="font-semibold text-green-800 mb-3">✓ Self-Check Questions</div>
                  <ul className="space-y-2">{selectedPhase.checkpoints.map((i, k) => (
                    <li key={k} className="text-sm text-green-700">✓ {i}</li>
                  ))}</ul>
                </div>
              </div>

              {selectedPhase.techniques?.length > 0 && (
                <div className="rounded-2xl bg-violet-50 border border-violet-200 p-5">
                  <div className="font-semibold text-violet-800 mb-3">◆ Techniques & Patterns Applied This Week</div>
                  <ul className="space-y-2">{selectedPhase.techniques.map((i, k) => (
                    <li key={k} className="text-sm text-violet-700">◆ {i}</li>
                  ))}</ul>
                </div>
              )}
            </div>

            {/* Full timeline table */}
            <div className="rounded-3xl bg-white border border-gray-200 p-6 shadow-sm overflow-hidden">
              <div className="font-semibold text-gray-900 text-lg mb-4">Full 30-Week Timeline</div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="text-left p-3 font-semibold text-gray-600">Wk</th>
                      <th className="text-left p-3 font-semibold text-gray-600">Theme</th>
                      <th className="text-left p-3 font-semibold text-gray-600 hidden md:table-cell">Frameworks</th>
                      <th className="text-left p-3 font-semibold text-gray-600 hidden lg:table-cell">Key Build</th>
                      <th className="text-left p-3 font-semibold text-gray-600">Output</th>
                    </tr>
                  </thead>
                  <tbody>
                    {phases.map(p => (
                      <tr key={p.week} onClick={() => setSelectedWeek(p.week)}
                        className={`border-b border-gray-100 align-top cursor-pointer hover:bg-gray-50 transition ${selectedWeek === p.week ? 'bg-violet-50' : ''}`}>
                        <td className="p-3 font-bold text-gray-900">{p.week}</td>
                        <td className="p-3">
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${phaseColors[p.phase]}`}>P{p.phase}</span>
                          <div className={`font-medium mt-1 ${selectedWeek === p.week ? 'text-violet-700' : 'text-gray-800'}`}>{p.title}</div>
                        </td>
                        <td className="p-3 hidden md:table-cell">
                          <div className="flex flex-wrap gap-1">
                            {(p.frameworks || []).slice(0,2).map(fw => (
                              <span key={fw} className={`text-xs px-1.5 py-0.5 rounded border font-medium ${frameworkColors[fw] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>{fw}</span>
                            ))}
                          </div>
                        </td>
                        <td className="p-3 text-gray-500 hidden lg:table-cell text-xs">{p.build[0]}</td>
                        <td className="p-3 text-gray-600 text-xs">{p.output.replace(' ✅', '')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {/* ── Tab: 24 Pillars ── */}
        {activeTab === 'pillars' && (
          <div className="rounded-3xl bg-white border border-gray-200 p-6 shadow-sm">
            <div className="font-semibold text-gray-900 text-xl mb-1">24 Capability Pillars</div>
            <p className="text-gray-500 text-sm mb-6">Every pillar ARIA will have. No other AI system has all 24 at production depth simultaneously.</p>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {capabilityPillars.map(p => (
                <div key={p.num} className="rounded-2xl bg-gray-50 border border-gray-200 p-4 hover:shadow-sm transition-shadow">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-gray-400">#{p.num}</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${
                      p.v === 'V1' ? 'bg-green-50 text-green-700 border-green-200' :
                      p.v === 'V2' ? 'bg-blue-50 text-blue-700 border-blue-200' :
                      'bg-violet-50 text-violet-700 border-violet-200'
                    }`}>{p.v}</span>
                  </div>
                  <div className="font-semibold text-gray-900 text-sm">{p.name}</div>
                  <div className="text-xs text-gray-400 mt-1">Week {p.week}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Tab: Self-Evolution ── */}
        {activeTab === 'evolution' && (
          <div className="space-y-6">
            <div className="rounded-3xl bg-white border border-gray-200 p-6 shadow-sm">
              <div className="font-semibold text-gray-900 text-xl mb-4">The 9 Types of Governed Self-Evolution</div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="text-left p-3 font-semibold text-gray-600">Type</th>
                      <th className="text-left p-3 font-semibold text-gray-600">What Evolves</th>
                      <th className="text-left p-3 font-semibold text-gray-600 hidden md:table-cell">Trigger</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selfEvolutionTypes.map(([type, what, trigger]) => (
                      <tr key={type} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="p-3 font-medium text-violet-700">{type}</td>
                        <td className="p-3 text-gray-700">{what}</td>
                        <td className="p-3 text-gray-400 hidden md:table-cell text-xs">{trigger}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="rounded-3xl bg-white border border-gray-200 p-6 shadow-sm">
              <div className="font-semibold text-gray-900 text-xl mb-4">The Self-Evolution Lifecycle (9 Steps)</div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {[
                  ['1. Work Happens',       'Task executed, output generated, action taken'],
                  ['2. AI Work Ledger',      'Records task + output + approval + outcome + ROI signal'],
                  ['3. Evaluation Harness',  'Scores quality via rubrics, LLM-as-judge, regression checks'],
                  ['4. Memory Fabric',       'Stores preferences learned, outcomes, patterns identified'],
                  ['5. Improvement Backlog', 'Ranks candidate improvements by impact × feasibility'],
                  ['6. Agent Factory',       'Creates skill/agent/workflow upgrade proposal with effort estimate'],
                  ['7. Sandbox Testing',     'Runs new capability in isolation, evaluates against rubrics'],
                  ['8. Human Approval',      'Kunal reviews proposal + sandbox results, approves or rejects'],
                  ['9. New Version Live',    'Registered in capability registry, outcome monitored for 2 weeks'],
                ].map(([title, desc]) => (
                  <div key={title} className="rounded-2xl bg-gray-50 border border-gray-200 p-4">
                    <div className="font-semibold text-gray-900 text-sm mb-1">{title}</div>
                    <div className="text-gray-500 text-xs leading-relaxed">{desc}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-3xl bg-red-50 border border-red-200 p-6">
              <div className="font-semibold text-red-700 text-lg mb-4">What Self-Evolution Must NOT Do</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {['Modify production behavior without human approval', 'Create agents with broad access automatically', 'Bypass governance or action tiers', 'Self-replicate without approval gates', 'Change security policies autonomously', 'Deploy capabilities without sandbox evaluation', 'Learn from unreliable sources without relevance scoring', 'Modify its own evaluation criteria to look better'].map(i => (
                  <div key={i} className="flex gap-2 text-sm text-red-700"><span className="shrink-0">✗</span>{i}</div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Tab: Learning Curriculum ── */}
        {activeTab === 'curriculum' && (
          <div className="rounded-3xl bg-white border border-gray-200 p-6 shadow-sm">
            <div className="font-semibold text-gray-900 text-xl mb-1">Full Learning Curriculum</div>
            <p className="text-gray-500 text-sm mb-2">Every technique learned gets implemented inside ARIA. The learning IS the capability accumulation.</p>
            <div className="flex gap-2 mb-6 flex-wrap">
              {Object.entries(frameworkColors).map(([fw, cls]) => (
                <span key={fw} className={`text-xs px-2.5 py-1 rounded-full border font-medium ${cls}`}>{fw}</span>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="text-left p-3 font-semibold text-gray-600">Technique / Framework</th>
                    <th className="text-left p-3 font-semibold text-gray-600">Week</th>
                    <th className="text-left p-3 font-semibold text-gray-600">Implemented As</th>
                    <th className="text-left p-3 font-semibold text-gray-600">Type</th>
                  </tr>
                </thead>
                <tbody>
                  {learningCurriculum.map(([tech, week, impl, type]) => (
                    <tr key={tech} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="p-3 font-medium text-violet-700">{tech}</td>
                      <td className="p-3 text-gray-500">{week}</td>
                      <td className="p-3 text-gray-700">{impl}</td>
                      <td className="p-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${frameworkColors[type] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>{type}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Tab: Moat Analysis ── */}
        {activeTab === 'moat' && (
          <div className="space-y-4">
            {[
              { title: 'Institutional Memory',         tag: 'Primary Moat',      color: 'border-emerald-200 bg-emerald-50', tagCls: 'bg-emerald-100 text-emerald-700', desc: 'Every task run, decision made, correction given, and outcome tracked — accumulates from Day 1 and cannot be transferred. A competitor starting fresh has zero.' },
              { title: 'Self-Dogfooding Corpus',       tag: 'Unique Moat',       color: 'border-blue-200 bg-blue-50', tagCls: 'bg-blue-100 text-blue-700', desc: 'From Week 7, ARIA reviews her own PRs, generates her own tests, documents her own architecture. After 30 weeks: hundreds of real tasks on a real codebase. No one else has this data.' },
              { title: 'Human Teaching Corpus',        tag: 'Proprietary Signal', color: 'border-violet-200 bg-violet-50', tagCls: 'bg-violet-100 text-violet-700', desc: 'Every correction, approval, and rejection by Kunal is a training signal. 6 months = thousands of preference signals. ARIA knows exactly what this organization values.' },
              { title: 'Evolution Intelligence History', tag: 'Time Moat',        color: 'border-amber-200 bg-amber-50', tagCls: 'bg-amber-100 text-amber-700', desc: 'By Week 30, ARIA has 7+ weeks of daily AI ecosystem monitoring, calibrated relevance scoring, and integrated capabilities with proven quality improvement.' },
              { title: '24 Pillars at Production Depth', tag: 'Breadth × Depth', color: 'border-pink-200 bg-pink-50', tagCls: 'bg-pink-100 text-pink-700', desc: 'Any one pillar is copyable in days. All 24 at production quality simultaneously — including rubrics, regression tests, and organizational calibration — takes 30 weeks.' },
              { title: 'Calibrated Evaluation Infrastructure', tag: 'Quality Moat', color: 'border-cyan-200 bg-cyan-50', tagCls: 'bg-cyan-100 text-cyan-700', desc: 'Rubrics, baselines, and regression tests built over 30 weeks on real usage data. A fresh system has nothing to regress against.' },
              { title: "Kunal's Operational Expertise", tag: 'Person Moat',       color: 'border-rose-200 bg-rose-50', tagCls: 'bg-rose-100 text-rose-700', desc: 'After 30 weeks, Kunal is one of the few people in the world who has built and operated a full AI Employee in a real media organization. Not from a tutorial. From production.' },
              { title: 'Fine-Tuned Specialist Models',  tag: 'ML Moat',           color: 'border-lime-200 bg-lime-50', tagCls: 'bg-lime-100 text-lime-700', desc: 'By Week 29, ARIA-PR-Reviewer-7B is fine-tuned on YOUR approved PR review outputs via LoRA/QLoRA. This model encodes your team\'s specific risk patterns and preferences — it cannot be replicated without your data.' },
            ].map(({ title, color, tag, tagCls, desc }) => (
              <div key={title} className={`rounded-2xl border p-5 ${color}`}>
                <div className="flex items-center gap-3 mb-2">
                  <div className="font-bold text-gray-900">{title}</div>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${tagCls}`}>{tag}</span>
                </div>
                <p className="text-gray-700 text-sm leading-7">{desc}</p>
              </div>
            ))}
            <div className="rounded-3xl bg-white border border-gray-200 p-6 text-center shadow-sm">
              <div className="text-lg font-bold text-gray-900 mb-2">The Bottom Line</div>
              <p className="text-gray-600 max-w-3xl mx-auto leading-7">
                ARIA's moat is not the code — it's 30 weeks of accumulated memory, calibrated intelligence, organizational trust, and the expertise of the person who built and operated it.
              </p>
            </div>
          </div>
        )}

        {/* ── Footer ── */}
        <div className="rounded-3xl bg-gradient-to-br from-violet-600 to-violet-800 p-8 mt-8 text-center shadow-lg">
          <h2 className="text-2xl font-bold text-white">The Final Strategic Line</h2>
          <p className="mt-4 text-violet-100 max-w-5xl mx-auto text-base leading-8">
            This is not a static AI implementation. It is a governed, self-evolving enterprise AI work operating system that can take ownership of engineering, analytics, QA, delivery, and reporting tasks — while continuously learning, expanding capabilities, managing its own AI workforce, and evolving with the AI ecosystem over time.
          </p>
        </div>

      </div>
    </div>
  );
}
