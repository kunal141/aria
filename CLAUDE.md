# ARIA — AI Employee Platform
# Claude Code Context File — READ THIS FULLY BEFORE EVERY SESSION

This file is auto-injected into every Claude Code session. It captures every major decision,
architectural choice, discussion, and direction from all prior sessions with Kunal Mahajan.
Do not skip any section. This is the single source of truth.

---

## 0. GLOBAL CLAUDE.MD OVERRIDES (read before applying Karpathy's global rules)

A global `~/.claude/CLAUDE.md` (Karpathy's behavioral guidelines) is also loaded. Where it conflicts with ARIA's rules, **ARIA's project rules win**. Explicit overrides:

| Karpathy Global Rule | ARIA Override | Why |
|---|---|---|
| "No abstractions for single-use code" | **Typed Pydantic contracts, skill registries, and versioned schemas are REQUIRED from Day 1** — even for the first skill | These are the moat. Consistency across 24 pillars, 30 weeks, and future fine-tuning training data requires typed contracts from the start, not retrofitted later |
| "Minimum code that solves the problem" | **Every skill has: input schema, output schema, metadata model, version, action_tier, eval rubric** | ARIA is a platform, not a script. The "minimum" for a platform skill includes its contract. A skill without a schema is not a skill. |
| "No flexibility that wasn't requested" | **Skill versioning (v1 → v2 → v3) is built in from Week 6** | Versioning is not flexibility-for-flexibility's-sake. It is the mechanism by which skills evolve without breaking callers — the evolution moat depends on it |

All other Karpathy rules apply fully and complement this project:
- "Think before coding" → reinforces ARIA's learning-first approach
- "Surgical changes" → reinforces no V2 scope creep into V1
- "Goal-driven execution" → maps directly to weekly checkpoints

---

## 1. WHO IS BUILDING THIS

**Kunal Mahajan**
- Works at **Amar Ujala** (one of India's largest Hindi media organisations — AU AOP directory)
- His manager built a competing AI vision called **"Yukti"** — an agentic organisation platform
- ARIA is being built as a **surprise** — the manager does NOT know this project exists
- **Launch plan**: Reveal ARIA to manager at Week 30 as a surprise, then post on LinkedIn
- Strategic positioning: Yukti is organisation-first infrastructure. ARIA is intelligence-first AI Employee. ARIA wins on memory, self-evolution, identity, evaluation harness, Agent Factory, self-dogfooding corpus.

**Kunal's profile:**
- Ambitious, strategic thinker — thinks in complete systems, not demos (referenced Chitti from Robot/Enthiran)
- Prefers Python for all backend development
- Has **Claude API (primary)** + **OpenAI API** + ChatGPT subscription. Claude is the default for all ARIA skills; OpenAI models used for benchmarking and as fallback routing option in Model Router.
- Wants to LEARN every concept deeply — **do NOT suggest skipping any learning section**
- Goal is both to BUILD and to deeply UNDERSTAND
- Keep all 30 weeks with full learn + build structure intact — never compress or skip weeks

---

## 2. WHAT ARIA IS

**ARIA = Autonomous Role-based Intelligence Agent**

Not a chatbot. Not a copilot. Not a workflow tool.

**ARIA is a Harness Engineering project.** The model is the smallest part. The product is everything around it: the runtime, memory, tools, governance, evaluation harness, action control, delegation logic, and Work Ledger. Anyone can call an LLM. ARIA's moat is the harness — the infrastructure that makes LLM calls reliable, governed, auditable, and improvable over time.

**ARIA is a full AI Employee** that:
- Receives **GOALS** (not prompts)
- Decomposes work into dependent subtasks
- Executes using typed skills and specialist agents
- Remembers everything across sessions (institutional memory)
- Reports outcomes proactively
- Accepts feedback and improves from it
- Proposes her own capability upgrades (with human approval)
- Reviews her own code, generates her own tests (self-dogfooding from Week 7/8)
- Learns from the AI ecosystem daily (Evolution Intelligence from Week 18)

**The ambition**: "The mother of all agentic AI projects." 30 weeks. 24 capability pillars. ~24,000 lines of code at V1. Full V3 product: ~95,000 lines.

**Size estimates by version:**
- V1 (30 weeks): ~24,000 lines — AI Engineer vertical, 1 org
- V2 (+12 months): ~50,000 lines — 2 verticals, real SaaS, multi-tenant
- V3 (+24 months): ~95,000 lines — full AI Employee as a Service platform

---

## 3. CURRENT STATUS

| What | Status |
|---|---|
| Week 1 — Problem, Vision, Scope Freeze | ✅ DONE |
| Week 2 — Architecture & Capability Mapping | ✅ DONE |
| All docs in `aria/docs/` | ✅ DONE |
| Frontend (ARIAMasterPlan.jsx + ARIADashboard.jsx) | ✅ DONE — light theme, 24 pillars |
| Vite + React + Tailwind scaffolding | ✅ DONE — runs at localhost:5173 |
| Weeks 3–25 backend (`apps/backend/`) | ✅ DONE — LangGraph, skills, RAG, code intel, memory, LangSmith, Teams bot, governance, eval harness, model router, QA/CI-CD/Jira skills, CrewAI crew, DSPy, Decision Intelligence, Agent Control Plane, SLM Classifier |

**CURRENT STATE: Weeks 3–29 implementation complete. **Week 29 is COMPLETE — all five priorities (AI Work Ledger v2 → ROI Dashboard → Dataset Export Prototype → Model Lifecycle Registry v1 → Fine-Tuning Prototype) independently ACCEPTED by Codex.** 1021 backend pytest tests passing (1 skipped). No real model training, fine-tuning, or deployment occurred — the fine-tuning runner is an offline deterministic dry-run, no model was activated, and the production graph / model router were not modified. Section 28 carries documentation-only future layers — 28.1 Agent Instruction Engine / Subagent Prompting Layer, 28.2 Human-like Work Intelligence, 28.3 Harness Engineering Positioning, and 28.4 Agentic AI Roadmap (eight V2/V3 capabilities: delegated agent identity, A2A-ready envelopes, AG-UI event stream, persistent workspaces, branching experiments, security gateway, episode packages, agent-config compatibility) — vision only, NOT implemented. **Week 30 (Launch Readiness — final integration + surprise reveal + LinkedIn) is COMPLETE — ACCEPTED by Codex (2026-06-15).** The launch-readiness package is built (offline golden-path demo `aria.demo.golden_path` + ~17 deliverable docs under `docs/week30_*`); Codex round-1 ("Partially Accepted") and round-2 findings were all closed (golden-demo no-pollution fix + regression tests, terminal-vs-seeded ledger wording corrected, demo-test temp-dir leak fixed, status docs refreshed) and Codex returned a final **Accepted** verdict. Previous full baseline: 1027 backend tests passing (1 skipped); focused demo suite 6 passed; golden demo reliability verified. **Public GitHub / LinkedIn publication remains BLOCKED pending employer/IP approval — the public-safe artifacts are drafts only.** No new core capability, pillar, vLLM serving, real fine-tuning, or production deployment was added; keep the Section 28 future layers as clean attach points.**

---

## 4. DIRECTORY STRUCTURE

```
C:\Users\Kunal Mahajan\Documents\aria\          ← ALWAYS open this as VS Code root
├── CLAUDE.md                                    ← this file (auto-loaded every session)
├── .gitignore
├── apps/
│   ├── frontend/                                ← React + Vite (DONE)
│   │   ├── src/
│   │   │   ├── ARIAMasterPlan.jsx               ← 30-week interactive plan viewer
│   │   │   ├── ARIADashboard.jsx                ← 6-panel operational dashboard (mock data)
│   │   │   └── App.jsx                          ← view switcher
│   │   ├── package.json
│   │   ├── vite.config.js
│   │   └── tailwind.config.js
│   └── backend/                                 ← Python LangGraph (Weeks 3–12 DONE)
│       ├── pyproject.toml                       ← uv project config
│       ├── main.py                              ← entry point (uv run python main.py)
│       ├── aria/
│       │   ├── config.py                        ← LangSmith setup, env vars
│       │   ├── state.py                         ← ARIAState TypedDict
│       │   ├── graph.py                         ← StateGraph: intake→router→skill→respond
│       │   ├── artifact_engine.py               ← formats skill output into terminal cards
│       │   ├── work_ledger.py                   ← appends every task to work_ledger.jsonl
│       │   ├── nodes/
│       │   │   ├── intake.py                    ← assigns task_id, audit trail
│       │   │   ├── router.py                    ← LCEL chain → Claude → task_type
│       │   │   ├── respond.py                   ← calls artifact_engine, logs to ledger
│       │   │   └── skill_nodes.py               ← kpi_node + pr_review_node (real skills)
│       │   ├── skills/
│       │   │   ├── skill_registry.py            ← register/get/list skills + SkillMetadata
│       │   │   ├── kpi_skill.py                 ← KPIInput → KPIOutput (Eval-Lite included)
│       │   │   └── pr_review_skill.py           ← PRReviewInput → PRReviewOutput
│       │   ├── knowledge/
│       │   │   ├── ingestion.py                 ← chunk + embed + upsert to Chroma
│       │   │   ├── retriever.py                 ← Basic RAG, HyDE, Self-RAG, Adaptive RAG
│       │   │   ├── code_intel.py                ← AST parse, dep graph, ingest_repo()
│       │   │   └── seed_docs/                   ← kpi_runbook.md + pr_guidelines.md
│       │   └── memory/
│       │       ├── models.py                    ← 6 memory types (Pydantic)
│       │       ├── store.py                     ← file-backed JSON warm store
│       │       └── manager.py                   ← MemoryManager singleton (memory = ...)
│       ├── week9_rag_test.py                    ← learning artifact: RAG strategies
│       ├── week10_code_intel_test.py            ← learning artifact: code Q&A
│       ├── week11_memory_test.py                ← learning artifact: memory lifecycle
│       └── week12_institutional_memory_test.py  ← learning artifact: institutional memory
├── docs/
│   ├── problem_statement.md
│   ├── solution_statement.md
│   ├── v1_scope.md                              ← V1 = AI Engineer only (not Editorial AI)
│   ├── architecture.md                          ← 19-layer architecture + 24 pillars
│   ├── capability_map.md                        ← 24 pillars with week numbers
│   ├── capability_pillars.md                    ← full sub-capability breakdown per pillar
│   ├── learning_curriculum.md                   ← every technique with deep-dives + study resources
│   ├── learning_journal.md                      ← 30-week curriculum table + maintenance discipline
│   ├── moat_analysis.md                         ← 7-layer moat analysis
│   ├── evolution_intelligence.md                ← governed self-evolution: 9 types + lifecycle
│   └── self_dogfooding.md                       ← protocol for ARIA reviewing her own code
└── ml/                                          ← fine-tuning pipeline (Week 29)
    ├── finetune/
    │   ├── prepare_dataset.py
    │   ├── train_lora.py
    │   └── eval_finetuned.py
    └── serve/
        └── start_vllm.sh
```

---

## 5. TECHNOLOGY STACK — EVERY DECISION AND WHY

| Layer | Technology | Why This, Not Alternatives |
|---|---|---|
| **Orchestration** | LangGraph | Stateful directed graphs, durable checkpointing, `interrupt_before/after` for human-in-the-loop. LangChain alone is stateless. AutoGen is conversational not graph-based. |
| **Foundation** | LangChain (LCEL) | LangGraph builds ON LangChain. Provides prompt templates, LCEL chains, tool wrappers, retrievers, LLM wrappers. Both are hands-on — Week 3. |
| **Tracing + Eval** | LangSmith | First-party LangGraph integration. Rubric-based evaluation. Regression testing. LLM-as-judge. Not optional — every node must be traced. |
| **API Layer** | FastAPI | Python-native, async, Pydantic models align perfectly with skill output schemas. |
| **Frontend** | React + Vite + Tailwind CSS | Already built. Light theme. Pure Tailwind — no shadcn/ui for now. |
| **Multi-agent (hands-on)** | CrewAI | Real implementation at Week 22 — Analytics + QA crew with role-based agents, tasks, process. NOT just a reference pattern. |
| **Prompt optimization** | DSPy | Systematic: define metric → compile → optimised prompt. Not hand-tuning. Week 21. |
| **Structured output** | Instructor + Pydantic | Every skill returns a typed Pydantic model. Zero ad-hoc string parsing anywhere in the codebase. |
| **Model serving** | vLLM | OpenAI-compatible API endpoint. Self-hosted models. Zero code changes in skill layer — just swap `base_url`. Week 25+. |
| **SLMs (small models)** | Phi-3-mini, Qwen-0.5B, Gemma-2B | Cheap/fast for classification, routing, extraction. NOT fine-tuning — a completely separate concept. Week 16+. |
| **Fine-tuning** | Unsloth + TRL (SFTTrainer + DPO) | 2× faster LoRA, fits RTX 4090, ~$0.80/run on RunPod A40. Week 29. |
| **Fine-tune base model** | Qwen2.5-Coder-7B-Instruct (first candidate) | Code-aware, strong for PR review and code reasoning. **Benchmark against Llama-3.1-8B-Instruct before finalising** — Llama-3.1-8B may outperform on communication/Jira/summary tasks. Production-grade fine-tuned model is V2 unless Week 29 has time. |
| **Model routing** | Custom ModelRouter class | Routes by: task type, risk level, complexity, cost, data privacy. Built Week 16. |
| **Vector store (RAG)** | Chroma (Week 9) → Postgres + pgvector (Week 11–12) | Week 9: Chroma for local RAG learning — zero config, in-memory, LangChain-native. Week 11–12: migrate to pgvector when persistent memory + SQL filters + ACID behavior become critical. Redis for hot cache. |
| **Tool protocol** | MCP (Model Context Protocol) | Standard for tool integration. Every ARIA tool is MCP-compatible. |
| **Future interop** | A2A protocol | Agent-to-agent schema for marketplace interoperability. Week 23+. |
| **Declarative Generative UI** | JSON schema → React renderer | ARIA emits structured UI schemas (KPI cards, PR risk panels, approval cards, Work Ledger views, trace timelines, Agent Control Plane dashboards). React frontend renders them into safe components. No raw HTML in production — schema-driven rendering only. Generative UI Canvas (persistent workspaces, editable artifacts) is a V2 evolution of this. |
| **Audience-Aware Communication** | Tone adapter in respond node | ARIA adapts output tone and depth based on role (developer vs. manager vs. leadership) and context (urgent incident vs. normal update vs. frustrated user). Same underlying skill output — different surface presentation. Implemented as a rendering layer in respond node + artifact engine. |

**Multi-agent learning stack:**
- **CrewAI** — HANDS-ON implementation at Week 22 (Analytics + QA crew). Role-based agents, tasks, process.
- **AutoGen** — STUDY at Weeks 17–18, BOUNDED PRODUCTION USE at Weeks 27+. Learn sub-agent conversational protocol, actor-model, GroupChat. Build 2-agent demo. Then use it in production for specific debate/review workflows where conversational back-and-forth beats a predefined graph: (1) Evolution proposal review: Research Agent vs Skeptic Agent vs Implementation Agent (Week 27); (2) ML Research Agent peer review: Paper Reader vs Experiment Designer vs Risk Reviewer (Week 29). LangGraph remains the orchestrator for all stateful enterprise flows.
- By Week 22 you have hands-on experience with LangGraph + CrewAI + AutoGen and can speak intelligently about all three tradeoffs in interviews.

**What we are NOT using:**
- OpenAI as primary backbone — Claude is the default. OpenAI available for benchmarking and model router fallback. Use `langchain-anthropic` for all ARIA skills unless benchmarking requires `langchain-openai`.
- LangChain agents — use LangGraph StateGraph for full control
- AutoGen as production backbone — LangGraph is the orchestrator; AutoGen is for bounded debate/review sub-workflows only
- MLflow — custom model registry first, MLflow only if needed later
- shadcn/ui — pure Tailwind for now

---

## 6. THE 24 CAPABILITY PILLARS

| # | Pillar | V | Build Week |
|---|---|---|---|
| 1 | Conversational Tasking | V1 | 3–4 |
| 2 | **AI Engineering (V1 PRIMARY)** | V1 | 7–10 |
| 3 | Data Science & Analytics | V2 | 11, 26 |
| 4 | QA / Test Intelligence | V1 | 17–18 |
| 5 | CI/CD & Release Intelligence | V1 | 19 |
| 6 | Jira / Delivery Management | V1 | 20 |
| 7 | Reporting & Communication (+ Audience-Aware UI) | V1 | 8 |
| 8 | Knowledge Vault / RAG / Org Intelligence | V1 | 9 |
| 9 | Code Intelligence | V1 | 10 |
| 10 | Governance & Trust | V1 | 15–16 |
| 11 | Agent Runtime Harness | V1 | 21 |
| 12 | Agent Evaluation Harness | V1 | 14 |
| 13 | Agent Factory | V2 | 22 |
| 14 | AI Workforce Expansion | V2 | 17, 25 |
| 15 | Agent Control Plane | V2 | 25 |
| 16 | AI Work Ledger | V2 | 4 (event log) → 8 (artifacts) → 13 (traces) → 15 (approvals) → 22 (outcomes) → 29 (full + ROI) |
| 17 | Human Teaching Layer | V1 | 11–12 |
| 18 | Evolution & Capability Intelligence | V3 | 18 (monitor), 27–28 (integrate) |
| 19 | Workflow Mining & Automation Discovery | V2 | 22 |
| 20 | Decision Intelligence | V2 | 24 |
| 21 | Confidence, Cost & Risk Optimizer | V2 | 21 |
| 22 | AI Capability Marketplace | V3 | 28 |
| 23 | AI Employee as a Service | V3 | 29 |
| 24 | **Model Intelligence & Post-Training** | V2 | 16 (router), 25 (SLMs+vLLM), 29 (FT+lifecycle) |

Pillar 24 was added after GPT analysis — model routing + SLMs + vLLM + fine-tuning + model lifecycle is a full capability pillar, not scattered notes.

---

## 7. V1 SCOPE — WHAT IS IN, WHAT IS DEFERRED

**V1 = AI Engineer vertical. One vertical. One organisation. Full loop.**

**IN V1 (build in 30 weeks):**
- PR Review (code quality, deployment risk, business impact, missing tests) — **including media-tech PR review: CMS pipelines, recommendation systems, notification services, personalisation engines, analytics pipelines**
- **Editorial / Content-Tech KPI Investigation** (Amar Ujala–specific): CTR drop, feed performance, notification CTR, story recommendation analysis, content pipeline health — makes ARIA feel built for the org, not generic
- Test Case Generation (functional, edge, negative)
- CI/CD Failure Summary + root cause analysis
- Code Intelligence (repo Q&A, AST parsing, dependency graph)
- Jira Ticket Creation + refinement + blocker tracking
- KPI Investigation + anomaly detection + root cause
- Teams bot identity (@mention ARIA, she responds)
- LangSmith tracing + 5 evaluation rubrics
- Memory: user + task + decision + outcome
- Governance: Action Tiers 1–3 (Read, Recommend, Draft)
- Model Router v1 (SLM for classification, frontier model for complex tasks)
- Basic Agent Factory (manual skill/agent registration)
- Evolution Intelligence monitoring (Week 18 onwards — daily AI digest)

**DEFERRED TO V2:**
- Full Editorial AI vertical (CMS authoring, editorial workflow, content generation) — distinct from content-tech KPI investigation which IS in V1
- Action Tiers 4–5 (Execute-with-Approval, Autonomous) — needs trust built first
- Full RAPTOR + GraphRAG (RAG basics come first)
- Multi-tenant AaS architecture
- Workflow Mining (needs enough real tasks accumulated first)
- Full self-evolution loop (needs 13+ weeks of Work Ledger data)
- Fine-tuning (needs Work Ledger data — Week 29 earliest)

---

## 8. THE 30-WEEK PLAN — PHASE SUMMARY

| Phase | Weeks | Goal | Key Output |
|---|---|---|---|
| 1 — Foundation | 1–2 | Architecture, scope, planning | ✅ DONE |
| 2 — Build Core | 3–5 | LangGraph + LangChain + context engineering | First graph running |
| 3 — First Skills | 6–8 | Skill registry, KPI skill, PR review, artifact engine | First real skill live |
| 4 — Memory + Identity | 9–13 | RAG, code intel, memory fabric, LangSmith, Teams bot | ARIA in Teams |
| 5 — Domain Skills | 14–16 | Eval harness, governance, autonomy + model router | ARIA governs herself |
| 6 — Domain Skills II | 17–20 | QA, CI/CD, Jira + CrewAI crew | Full AI Engineer suite |
| 7 — Intelligence Depth | 21–24 | Runtime harness, Agent Factory, DSPy, Decision Intel | ARIA optimises herself |
| 8 — Workforce | 25–26 | Agent Control Plane, SLMs, vLLM, analytics depth | ARIA manages her team |
| 9 — Self-Evolution | 27–28 | Evolution Intelligence — propose + integrate | Self-evolution loop proven |
| 10 — Work Ledger + ML | 29 | AI Work Ledger v2 → ROI Dashboard → Dataset Export → Model Lifecycle Registry v1 → Fine-Tune Prototype (prototype only — see § 29) | ROI dashboard live + fine-tune pipeline proven end-to-end |
| 11 — Launch | 30 | Demo, LinkedIn, surprise reveal, AaS blueprint, Yukti positioning, career assets | The world sees ARIA |

---

## 9. TECHNIQUES — WHAT, WHEN, WHY

| Technique | Week Built | Implemented As | Why |
|---|---|---|---|
| LangChain LCEL | 3 | Chains, prompt templates, tool definitions | Foundation LangGraph builds on |
| LangGraph StateGraph | 3 | Core orchestration backbone | Stateful, durable, HITL |
| ReAct | 4 | Orchestrator reasoning loop: Think→Act→Observe→Reflect | Core agent reasoning pattern |
| Chain of Thought | 5 | Task planning step before skill execution | Structured multi-step reasoning |
| Context Engineering | 5 | Working memory design, token budget, summarisation | Prevents #1 LLM mistake |
| HyDE | 9 | Enhanced retrieval for sparse queries | Hypothetical doc → embed → match real |
| Self-RAG | 9 | ARIA critiques her own retrieval | Relevance check before using |
| Adaptive RAG | 9 | Dynamic retrieval strategy | Query-type-based method selection |
| MemGPT/Letta patterns | 11 | Memory paging: hot+warm+cold | OS-style context management |
| Tree of Thoughts | 11 | Multi-path decomposition for uncertain outcomes | Explore multiple task approaches |
| LangSmith evals | 14 | Rubric + regression framework, LLM-as-judge | Quality as a measurable system |
| Constitutional AI | 14, 28 | Output safety checks + self-integration safety | Governance at model level |
| CrewAI (HANDS-ON) | 22 | Real implementation: Analytics + QA crew | Hands-on multi-agent experience |
| **AutoGen (STUDY + BOUNDED PRODUCTION)** | **17–22 (study), 27–29 (production debate flows)** | **Study conversational patterns; build 2-agent demo; use in production for Evolution proposal review (Week 27) and ML Research peer review (Week 29) — both are debate/critique patterns where conversational multi-agent beats a fixed graph** | **All 3 frameworks hands-on; AutoGen used where it genuinely fits** |
| RAPTOR | 26 | Hierarchical long doc summarisation | Preserves doc structure + detail |
| GraphRAG | 26 | Org knowledge graph retrieval | Multi-hop reasoning across entities |
| DSPy | 21 | Systematic prompt optimisation | Metrics-driven, not hand-tuned |
| Instructor | 21 | Structured output on all skills | Guaranteed typed Pydantic output |
| LATS | 24 | Agent tree search for decision exploration | MCTS for agent decisions |
| SLMs | 16 | Phi-3-mini/Qwen-0.5B for classification/routing | Cheap utility, not fine-tuning |
| Model Router | 16 | Right model per task: cost/quality/privacy | Pillar 24 starts here |
| vLLM | 25 | Self-hosted model serving, OpenAI-compatible API | Privacy + cost control |
| LoRA/QLoRA (Unsloth+TRL) | 29 | Fine-tune Qwen2.5-Coder-7B on Work Ledger data | Institutional knowledge in weights |
| DPO | 29 | Preference alignment from approve/reject pairs | Encodes what the organisation values |
| Model Lifecycle Registry | 29 | Version, dataset, eval score, endpoint, rollback | MLOps for ARIA |
| **Synthetic Data Generation** | **29** | **Generate training data when real examples < 50; used in ML Research Agent** | **Unblocks fine-tuning when Work Ledger data is sparse** |

---

## 10. ARCHITECTURAL DECISIONS — THE NON-NEGOTIABLES

### Orchestrator-First (NOT Swarm-First)
Central brain routes to specialists. Not a swarm where agents decide independently.
Reason: governance, debuggability, traceability at enterprise scale.

### Self-Dogfooding Starts Week 7/8
ARIA reviews her own PRs, generates her own tests, documents her own architecture.
This corpus is irreplaceable — no one else has real tasks on a real codebase from Day 1.
Every bug caught = proof of QA capability. Every risk flagged = proof of code intelligence.

### Governed Self-Evolution (NEVER Autonomous Self-Modification)
Cycle: ARIA proposes → Kunal approves → sandbox tests → integrates.
ARIA NEVER modifies production behaviour without human approval. Ever.

### Context Engineering is a Full Week (Week 5)
Dedicated week BEFORE any skill is built.
Working memory vs long-term memory vs summarisation. Token budget per node.
This prevents the single most common LLM architecture mistake.

### Memory is Two Weeks (Weeks 11–12)
Week 11: session/task/user memory schemas.
Week 12: institutional/outcome/decision/artifact memory.
NOT compressed. The distinction between operational and institutional memory matters.

### Governance BEFORE Autonomy — Always
Evaluation harness (Week 14) → Governance layer (Week 15) → Controlled autonomy (Week 16).
You cannot safely grant autonomy before you can govern it.

### Every Skill is a Typed Contract
Input: typed Pydantic model.
Output: typed Pydantic model (enforced by Instructor).
Skills are semantically versioned (v1 → v2 → v3).
No ad-hoc string parsing anywhere. This is the difference between a demo and a platform.

---

## 11. ACTION TIERS (GOVERNANCE FRAMEWORK)

| Tier | Name | What ARIA Does | Approval Required |
|---|---|---|---|
| T1 | Read | Fetches data, reads docs, observes | Automatic |
| T2 | Recommend | Proposes action, posts suggestion | Automatic |
| T3 | Draft | Creates draft (PR note, ticket, email) | Automatic — human edits/approves before send |
| T4 | Execute-with-Approval | Takes real action after explicit approval | Human must approve first |
| T5 | Autonomous | Acts without asking | Only pre-approved routine patterns |

**V1 implements Tiers 1–3 only. Tiers 4–5 are V2.**

---

## 12. MODEL ROUTING STRATEGY (PILLAR 24)

Route EACH task to the right model. Never use one model for everything.

| Task Type | Model | Why |
|---|---|---|
| Task classification, risk scoring | Phi-3-mini or Qwen-0.5B (SLM via vLLM) | ~$0 cost, fast, simple labels |
| Structured extraction (Jira fields, PR metadata) | SLM or fine-tuned 7B | Cheap, repetitive pattern |
| Sensitive internal code / data | Self-hosted model via vLLM | No data leaves infrastructure |
| PR review, test gen (routine, stable pattern) | Fine-tuned Qwen2.5-Coder-7B via vLLM | Cheap specialist after Week 29 |
| Complex multi-step reasoning | Claude Haiku | Good cost/quality balance |
| High-risk actions, leadership summaries | Claude Opus | Best quality for high-stakes |
| Calculation-heavy tasks | Python/SQL tool + LLM explanation | Tools beat prompting for deterministic work |
| Low confidence / Tier 4–5 boundary | Human escalation | Governance |

**Model Router builds in phases:**
- Week 16: v1 — SLMs for classification, frontier for complex
- Week 25: v2 — add vLLM serving layer for self-hosted models
- Week 29: v3 — add fine-tuned specialist model routing

---

## 13. WHEN NOT TO FINE-TUNE (CRITICAL DISCIPLINE)

Fine-tuning is NOT the default answer. Exhaust this stack first:
1. Prompt engineering (system prompt, few-shot examples)
2. RAG (retrieve relevant context)
3. Tools (Python, SQL, APIs for deterministic steps)
4. Structured outputs (Instructor + Pydantic)
5. DSPy (systematic prompt optimisation)
6. SLMs for cheap classification/routing

**Fine-tune ONLY when ALL of these are true:**
- Output format/style is stable and repeated
- You have > 50 clean, high-quality examples
- RAG + prompting are inconsistent despite good retrieval
- Latency or API cost is a real constraint
- The task pattern won't change significantly for months

**Never fine-tune when:**
- Task requires fresh/current knowledge → use RAG
- Task depends on retrieved context → RAG + tools
- Workflow is still evolving → wait for stability
- < 50 clean examples → prompt engineering first
- Correctness depends on real data/calculations → tools
- Policy/governance rules need updating → policy engine, not weights

---

## 14. GOVERNED SELF-EVOLUTION

The 9 types of evolution ARIA can undergo (all require human approval):

| Type | What Evolves |
|---|---|
| Prompt evolution | Better instructions, better output formats |
| Skill evolution | Skills become more accurate over versions |
| Workflow evolution | Repeated tasks → structured reusable workflows |
| Agent evolution | New specialist agents proposed and created |
| Memory evolution | Learns preferences and past outcomes |
| Tool evolution | New tools/connectors added |
| Policy evolution | Approval/risk rules improve from outcome data |
| Model-routing evolution | Better model chosen per task type over time |
| Evaluation evolution | Better benchmarks and rubrics added |

**What ARIA must NEVER do autonomously:**
- Modify production behaviour without human approval
- Create agents with broad access automatically
- Bypass governance or action tiers
- Self-replicate without approval gates
- Change security policies
- Deploy capabilities without sandbox evaluation
- Modify her own evaluation criteria to look better

---

## 15. KEY INSIGHTS FROM GPT DISCUSSIONS

Throughout this project, multiple ChatGPT analysis sessions provided insights incorporated into the plan:

### GPT Insight 1 — SLMs are NOT fine-tuning
Small models (0.5B–4B params) for cheap utility tasks are a separate concept from fine-tuning a 7B model.
Phi-3-mini for classification. Qwen-0.5B for routing/labelling.
Use SLMs from Week 16. Fine-tuning only from Week 29.

### GPT Insight 2 — Model Lifecycle Registry is mandatory MLOps
Track: model name, base model version, dataset version, eval score, deployment endpoint, rollback pointer, usage by skill.
Without this, you can't rollback a bad fine-tuned model. Added to Week 29.

### GPT Insight 3 — ML Research & Post-Training Agent
A specialist agent (created by Agent Factory) that automates:
dataset collection → dataset prep → LoRA experiment → eval comparison → package model → deploy via vLLM → update registry → recommend rollout/rollback.
Added to Week 29 build list.

### GPT Insight 4 — "When NOT to Fine-Tune" framework
RAG + tools + evals beats fine-tuning in most cases.
Fine-tune only stable, high-volume patterns with clean examples. See Section 13.

### GPT Insight 5 — vLLM is the serving layer for privacy
Sensitive internal code (PR diffs, financial data) should never go to external APIs.
Self-hosted vLLM solves this. Privacy routing is now part of Model Router logic.

### GPT Insight 6 — Pillar 24: Model Intelligence & Post-Training
All of model routing + SLMs + vLLM + fine-tuning + model lifecycle = a 24th capability pillar.
Not scattered notes — a full domain of work.

### GPT Insight 7 — Pedagogically correct week ordering (v3 JSX analysis)
Context engineering BEFORE first skill (Week 5 before Week 6).
Memory in 2 full weeks (Weeks 11–12), not 1 compressed week.
Governance BEFORE autonomy (Week 15 before Week 16).
These prevent the 10 most common LLM architecture mistakes.

### GPT Insight 8 — AgilePoint validates the market
AgilePoint sells "Enterprise-Scale Safe Agentic AI Orchestration" — AI Control Tower with 1200+ business activities and 120+ enterprise integrations. A company is selling exactly what ARIA builds.
ARIA's advantages: self-evolving, institutional memory, self-dogfooding corpus, open standards (MCP/LangGraph) vs proprietary SDK, fine-tuned specialist models trained on internal data.

---

## 16. COMPETITIVE LANDSCAPE — HOW ARIA DIFFERENTIATES

Key AI agent frameworks/products in the wild. Useful for interview positioning.

| Platform | What it is | ARIA's advantage |
|---|---|---|
| **AgilePoint** | Enterprise AI Control Tower — 1200+ pre-built activities, 120+ system integrations, proprietary SDK | ARIA: open standards (LangGraph/MCP), self-evolving memory, self-dogfooding corpus, fine-tuned models on internal data |
| **AutoGPT / OpenAgents** | General autonomous agents, open-source | ARIA: enterprise governance, action tiers, institutional memory, self-dogfooding, evaluation harness |
| **Hermes Agent** | Personal self-improving agent: persistent memory, multi-channel (Telegram/Discord/Email), subagents, automations | ARIA: enterprise-native (Teams/Jira/CI/CD), RBAC + audit + approval gates, AI Work Ledger, role-capable across engineering workflows |
| **AutoGen** | Conversational multi-agent framework, actor-model, GroupChat | ARIA uses it as a LEARNING tool (Weeks 17–22). LangGraph's graph model beats AutoGen for complex stateful enterprise flows. |
| **CrewAI** | Role-based agent crews for structured workflows | ARIA implements it HANDS-ON at Week 22. Good for structured team-of-agents patterns. |
| **Yukti (internal)** | Manager's org-coordination platform — agents + digital employees + governance | ARIA: intelligence-first (not org-first), self-evolution, institutional memory, Work Ledger ROI proof, self-dogfooding corpus |

**ARIA's interview line**: "I didn't pick one framework and call it done. I studied AutoGen, built hands-on with CrewAI, and use LangGraph as the production backbone — because I understand the architectural tradeoffs between all three."

---

## 17. THE 7-LAYER MOAT

| Moat Layer | Why It Cannot Be Replicated |
|---|---|
| 30 weeks of institutional memory | Accumulates from Day 1. Not transferable. Competitor starts at zero. |
| Self-dogfooding corpus | Hundreds of real tasks on a real codebase. No one else has this data. |
| Human Teaching corpus | Kunal's corrections + approvals = thousands of preference signals across 6 months |
| Evolution Intelligence history | 7+ weeks of daily AI ecosystem monitoring, calibrated relevance scoring by Week 30 |
| 24 pillars at production depth | Any single pillar is copyable in days. All 24 simultaneously — not in 4 weeks. |
| Calibrated evaluation infrastructure | Rubrics + baselines + regression history built over 30 weeks on real usage data |
| Fine-tuned specialist models | Trained on YOUR approved outputs. Encodes your organisation's specific risk patterns. |

---

## 18. WEEK 3 — WHAT TO BUILD RIGHT NOW + DAILY PLAN

**Location**: `C:\Users\Kunal Mahajan\Documents\aria\apps\backend\`

### Install dependencies
```bash
uv add langgraph langchain langchain-anthropic langsmith python-dotenv pydantic instructor fastapi uvicorn
```

### Build order
1. `aria/config.py` — LangSmith env var setup:
```python
import os
from dotenv import load_dotenv
load_dotenv()
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "ARIA"
```

2. `aria/state.py` — ARIAState TypedDict:
```python
from typing import TypedDict, Optional, Literal, List
class ARIAState(TypedDict):
    task_id: str
    raw_input: str
    task_type: Optional[Literal['pr_review', 'kpi', 'ci_cd', 'jira', 'general', 'unknown']]
    task_status: Literal['pending', 'routing', 'executing', 'done', 'failed']
    routing_reason: Optional[str]      # why ARIA chose this skill — feeds Work Ledger
    steps_completed: List[str]         # audit trail: ['intake', 'router', 'respond']
    skill_name: Optional[str]
    skill_output: Optional[str]
    response: Optional[str]            # final response text sent back to user
    messages: list[dict]
    error: Optional[str]
```

3. `aria/nodes/intake.py` — assigns task_id, status = 'routing'
4. `aria/nodes/router.py` — LangChain LCEL chain to classify task_type
5. `aria/nodes/respond.py` — placeholder response (real skills Week 6+)
6. `aria/graph.py` — StateGraph: intake → router → respond → END
7. `main.py` — invoke the compiled graph, print result

### Week 3 checkpoint
- `python main.py` runs end-to-end without error
- Task type classified correctly from raw natural language input
- LangSmith trace visible at smith.langchain.com → project "ARIA"
- ARIAState typed and flowing correctly through all nodes

### Week 3 — Daily Plan

| Day | Focus | Tasks |
|---|---|---|
| Day 1 | LangGraph mental model + graph skeleton | Read LangGraph docs: StateGraph, nodes, edges, conditional edges. Draw ARIA's graph on paper. Build the graph with a **dummy router** (hardcoded task_type, no Claude yet) — get it RUNNING first. |
| Day 2 | LangChain LCEL — isolated chain | Study LCEL: `|` pipe, `ChatPromptTemplate`, `ChatAnthropic`, `StrOutputParser`. Build the Claude router chain **in isolation** (standalone script, no graph). Call Claude, classify task_type, print result. |
| Day 3 | Repo + env setup + plug Claude in | `uv init`, install deps, create `.env`, set up `config.py` with LangSmith env vars. Replace dummy router with the Claude LCEL chain. Verify LangSmith trace at smith.langchain.com → project "ARIA". |
| Day 4 | ARIAState + intake node | Write final `state.py` TypedDict (with routing_reason, steps_completed). Write `intake.py` — assigns task_id, appends 'intake' to steps_completed, sets status='routing'. Run isolated. |
| Day 5 | Router node + respond node | Write `router.py` — full LCEL chain, populates task_type + routing_reason + steps_completed. Write `respond.py` placeholder. Test with 5 different inputs. |
| Day 6 | Graph assembly + end-to-end run | Wire `graph.py` StateGraph: intake → router → respond → END. Run `main.py` end-to-end. Print final state dict. |
| Day 7 | LangSmith review + docs | Read the trace in LangSmith — see every node, every state change. Write Week 3 learning notes. Draft resume bullet. Update capability log. |

---

## 19. VS CODE SETUP

**Always open**: `C:\Users\Kunal Mahajan\Documents\aria` as the root folder.
Never open `apps/frontend` or `apps/backend` separately.

**Essential extensions**: Claude Code (Anthropic), Python (Microsoft), Pylance, ESLint, Prettier, Tailwind CSS IntelliSense
**Recommended extensions**: Python Debugger, Thunder Client (API testing), GitLens, Error Lens, Even Better TOML

**Python interpreter**: `.venv/Scripts/python.exe` (set via Ctrl+Shift+P → Python: Select Interpreter)

**Terminal layout (split)**:
- Terminal 1: `cd apps/frontend && npm run dev` → localhost:5173
- Terminal 2: `cd apps/backend && python main.py`
- Browser: smith.langchain.com for LangSmith traces

**Every new Claude Code session in VS Code — first message**:
> "Read CLAUDE.md. What's the current status and what do we build next?"

---

## 20. KEY RULES — APPLY EVERY SESSION

1. **Always trace in LangSmith** — if a node isn't traced, it doesn't exist
2. **Every skill output is a Pydantic model** — use Instructor. Zero raw string returns
3. **Never break the action tier hierarchy** — no T4/T5 actions in V1
4. **Self-dogfooding starts Week 7/8** — ARIA reviews her own PRs from that point
5. **Never skip or compress learning sections** — Kunal learns every concept fully
6. **Every technique gets implemented** — study → implement → measure (LangSmith rubric) → document
7. **Model routing from Week 16** — no single-model approach after that
8. **Fine-tuning only from Week 29** — need Work Ledger data first
9. **Governance before autonomy** — always in that order
10. **LangChain + CrewAI are HANDS-ON** — LangChain at Week 3, CrewAI real implementation at Week 22. **AutoGen = study (Weeks 17–18) + bounded production use for debate/review workflows** — Evolution proposal review (Week 27), ML Research peer review (Week 29). LangGraph remains the production backbone for all stateful orchestration.
11. **All skills are typed contracts** — versioned, Pydantic in/out, registered in skill registry
12. **No V2 scope creep into V1** — Editorial AI, Tiers 4–5, full self-evolution are V2+
13. **Work Ledger starts Week 4, not Week 29** — basic event log from Day 1; ROI at Week 29 requires 25 weeks of accumulated data
14. **Safe Execution Environment at Week 21** — every tool call gets: dry-run mode, sandbox DB, staging tool variants, token/cost budget enforcement, loop detection, tool permission scopes, approval gates, idempotency keys, audit logging. Runtime harness alone is not enough; safety properties must be structural, not just documented.
15. **Security & Secrets layer at Week 15** — no API keys in codebase ever; PII redacted from LangSmith traces; tool permissions scoped to minimum required
16. **Sandbox before production** — every new capability (Agent Factory, self-integration) runs in isolated sandbox with restricted tools + approval-only mode before promotion to prod
17. **Eval-Lite from Week 6** — every skill ships with 5 golden examples, 3 failure cases, output schema check, and a 1–5 rubric. Full LangSmith harness at Week 14.
18. **Chroma first, pgvector second** — Week 9 RAG uses Chroma (zero config). Migrate to pgvector at Week 11–12 when persistent memory needs SQL + ACID.
19. **Yukti framing = complement, not competition** — ARIA is the execution intelligence layer; Yukti is the organisational coordination layer. Present as strengthening, not replacing.
20. **Proactive Notification Intelligence** — V1 trigger conditions (Week 16–20): CI/CD failure, PR risk flag, approval pending, Jira blocker detected, test coverage regression. V2 adds KPI anomaly alerts. All notifications governed: cooldown windows, escalation levels, mute controls, delivery via Teams only (not email in V1). Notification = a skill output, not a side-effect.

---

## 21. WEEKLY MAINTENANCE DISCIPLINE — MANDATORY

Every week produces 6 artifacts. Do not skip any. These build your portfolio, CV, and institutional memory simultaneously.

| Artifact | What to write | Where |
|---|---|---|
| **Learning notes** | What you learned, what's still unclear, key "aha" moments | `docs/learning_journal.md` — Week X entry |
| **Architecture decision** | Choice made, alternatives considered, tradeoff rationale | `docs/learning_journal.md` — Architecture Decision field |
| **Failure log** | What broke, how you diagnosed it, how you fixed it, what you'd do differently | `docs/learning_journal.md` — Failure Log field |
| **Capability log** | Which pillar advanced, what was added to ARIA's codebase | `docs/learning_journal.md` — Capability Added field |
| **Demo snapshot** | Screenshot or terminal output proving the week's deliverable works | Save to `docs/demos/week_XX.png` or paste output inline |
| **Resume bullet** | One crisp line for your LinkedIn/CV, written in past tense, with a quantifiable claim | `docs/learning_journal.md` — Resume Bullet field |

**Why this matters**: By Week 30, you will have 30 weeks × 6 artifacts = 180 documented outputs. This is the portfolio that makes ARIA irreplicable — not just the code.

---

## 22. ARIA IDENTITY — PLATFORM VS EMPLOYEE

**The platform and the first employee are distinct things.**

| Term | What it is |
|---|---|
| **AI Employee Platform** | The infrastructure: LangGraph orchestration, skill registry, memory fabric, evaluation harness, governance layer, Agent Factory, Work Ledger, model routing, evolution intelligence |
| **ARIA** | The first AI Employee built on the platform — AI Engineer role, Amar Ujala context |
| **Future employees** | QA-ARIA, CI/CD-ARIA, Analytics-ARIA, Editorial-ARIA — each a role-specific agent spawned from the same platform |

**Why this matters**: ARIA is not the product. The AI Employee Platform is the product. ARIA is the proof-of-concept and the first tenant. This framing makes the AaS story coherent and makes the reveal to the manager more powerful — you're not showing "a tool," you're showing "a platform that creates AI employees."

---

## 23. DEMO PROOF MILESTONES — EVERY 4 WEEKS

A visible, demonstrable output every 4 weeks. Non-negotiable. If you can't demo it, it doesn't count.

| Week | Demo Proof | What to Show |
|---|---|---|
| **4** | Task intake working | One real task accepted, tracked through lifecycle, status visible in UI |
| **8** | First skill + artifact | PR review on a real PR → structured artifact output with risk score |
| **12** | Memory + retrieval | Ask ARIA about a past decision — she recalls it. Ask about a doc — she retrieves and cites it. |
| **16** | Governance + controlled action | ARIA recommends an action → routes to approval → waits → continues after approval |
| **20** | AI Engineer suite complete | Show Jira ticket creation + CI/CD failure summary + test gen all from one task |
| **24** | Flagship demo v1 | Full end-to-end: task received via Teams → orchestrated → skill executed → artifact delivered → logged in Work Ledger |
| **30** | Final reveal | Full platform: live demo + ROI dashboard + Work Ledger + Agent Control Plane + Yukti complement note |

---

## 24. RISK REGISTER

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Scope explosion — adding more pillars instead of building | High | High | Freeze at 24 pillars; no new pillar without removing one |
| Framework fatigue — too many tools at once | Medium | High | LangGraph first, everything else gates on a working LangGraph foundation |
| No real company use case in demos | Medium | High | Every demo uses Amar Ujala media-tech examples (CTR, recommendation, CMS pipelines) |
| Weak evals — shipping skills with no quality baseline | High | Medium | Eval-Lite mandatory from Week 6; every skill has rubric before merging |
| No visible demo at milestone weeks | Medium | High | Demo Proof table above — if Week 4 milestone can't be shown, Week 5 work pauses until it can |
| Overdependence on one model | Low | Medium | Model Router from Week 16; fine-tuning prototype at Week 29 — never locked to one API |
| Political risk with Yukti reveal | Medium | High | Complement framing locked — "ARIA strengthens Yukti's vision"; practice the one-liner before the reveal |
| Week 29 overload creep | High | Medium | Production fine-tuned model is V2 unless benchmark results are exceptional; ROI + prototype is enough for reveal |

---

## 25. REFERENCE DOCS (read these for deeper context)

| File | Contains |
|---|---|
| `docs/learning_curriculum.md` | Every technique with deep-dives, SLMs section, "when NOT to fine-tune" framework, study resource links |
| `docs/capability_pillars.md` | Full sub-capability breakdown for all 24 pillars including Pillar 24 routing table |
| `docs/architecture.md` | 19-layer architecture stack, governed self-evolution lifecycle diagram |
| `docs/v1_scope.md` | Precise V1 in-scope vs deferred, why AI Engineer not Editorial AI (note: media-specific V1 use cases now included — see Section 7) |
| `docs/learning_journal.md` | 30-week curriculum table with techniques per week, weekly maintenance discipline template |
| `docs/moat_analysis.md` | 7-layer moat with why each layer is irreplicable |
| `docs/evolution_intelligence.md` | 9 evolution types, lifecycle, concrete examples, what ARIA must never do autonomously |
| `docs/self_dogfooding.md` | Protocol for ARIA reviewing her own codebase from Week 7/8 |
| `apps/frontend/src/ARIAMasterPlan.jsx` | Interactive 30-week plan viewer — browse all 30 weeks, 24 pillars, curriculum, moat |
| `apps/frontend/src/ARIADashboard.jsx` | 6-panel operational dashboard — Task Queue, Approvals, Agent Control Plane, Work Ledger, Evolution Radar, Marketplace |

---

## 26. HARNESS ENGINEERING PRINCIPLES & EXPANDED CAPABILITIES

This section captures architectural principles derived from reviewing current AI engineering trends. These are not new pillars — they are clarifications of how ARIA's existing 24 pillars should be built.

---

### 26.1 — ARIA is a Harness Engineering Project

The model is the smallest part. The product is the harness around it. ARIA's harness is composed of seven distinct layers — every line of code in `apps/backend/aria/` belongs to one of them.

| # | Harness Layer | What it is | Where it lives today |
|---|---|---|---|
| 1 | **Runtime Harness** | LangGraph StateGraph — durable, resumable, auditable execution. Retries, timeouts, idempotency, loop detection, budget control, failure handling. | `aria/graph.py`, `aria/state.py`, `aria/nodes/*` |
| 2 | **Tool Execution Harness** | MCP-compatible tools with permission scoping, typed I/O validation, dry-run mode, idempotency keys, audit logging, risk tiers. | `aria/tools/*` (Week 21 onwards), `aria/skills/*` |
| 3 | **Governance Harness** | Action Tiers 1–5, approval gates, privacy/PII redaction, evidence gates, constitutional checks, sandbox-before-production. | `aria/governance/*`, `aria/evolution/update_manager/constitutional.py` |
| 4 | **Evaluation Harness** | Golden examples + failure cases + rubrics + regression tests + LangSmith traces. Eval-Lite from Week 6, full LangSmith from Week 14. | `aria/evals/*`, skill-level `_eval()` methods |
| 5 | **Memory Harness** | Task / user / outcome / institutional memory. Three-tier hot/warm/cold, 6 typed Pydantic memory models. | `aria/memory/*`, `aria/work_ledger.py` |
| 6 | **Evolution Harness** | Monitor → propose → sandbox → evaluate → approve → canary → promote → rollback. Governed self-improvement with immutable versioned artifacts as runtime authority. | `aria/evolution/*` (registry, pipeline, update_manager) |
| 7 | **Subagent / Workflow Harness** *(future, see § 28.1)* | Structured task-brief generation for specialist subagents — typed instruction objects with allowed/forbidden context, allowed/forbidden tools, expected output schema, risk level, budget, deadline, approval requirement, evaluation criteria, ledger correlation ID. | V2 — designed to slot on top of Pillar 13 (Agent Factory) and Pillar 15 (Control Plane) |

The same seven layers also frame how Pillar 24 routes between models, how Pillar 16 (Work Ledger) records outcomes, and how Pillar 18 (Evolution) gates self-improvement. They are not separate "things" — they are the orthogonal axes along which every ARIA capability is built.

**Interview positioning**: *"I'm not building a prompt-engineering project. I'm building the harness that makes LLM calls reliable, governed, and improvable at enterprise scale. Seven layers — runtime, tools, governance, evaluation, memory, evolution, and subagent workflow — wrap every model call. Anyone can call an API. I'm building what makes it production-grade."*

---

### 26.2 — Declarative Generative UI

ARIA emits structured UI **schemas**, not raw text. The React frontend renders them into safe, typed components.

**V1 schema types (Week 13+):**
- `KPICard` — metric, delta, confidence, root causes
- `PRRiskPanel` — verdict badge, risk level, code issues list, missing tests
- `ApprovalCard` — task summary, proposed action, approve/reject buttons, risk score
- `WorkLedgerRow` — task_id, skill, artifact type, timestamp, approval status
- `TraceTimeline` — steps_completed, node durations, routing reason
- `AgentControlPanel` — active agents, task queue depth, approval queue

**Why schema-driven:**
- Safe: no XSS risk from raw HTML injection
- Composable: new skill → new schema type, no frontend rewrite
- Auditable: the schema is the artifact, not a rendered string
- Localizable: tone/language layer applies on top without touching data

**Generative UI Canvas (V2):** ARIA creates persistent workspaces — dashboards Kunal builds with ARIA's help, editable artifacts, multi-skill views. Not just output cards but interactive work surfaces. Think Notion page + LLM-generated structure + approval widgets.

---

### 26.3 — Audience-Aware Communication

Same underlying skill output. Different surface presentation based on role and context.

| Audience | Tone | Depth | Format |
|---|---|---|---|
| Developer | Direct, technical | Full code issues, exact line refs, specific fix suggestions | Terminal card or PR comment |
| Manager | Confident, concise | Risk level, business impact, recommended action | Slack summary or Teams card |
| Leadership | Executive, measured | 2-line summary, risk/opportunity, cost implication | Email-ready brief |
| Urgent incident | Alert, action-first | What's broken, who's affected, immediate next step | Priority notification |
| Normal update | Informational, low-urgency | Status, no action needed | Work Ledger entry |
| Frustrated user | Empathetic, solution-first | Acknowledge issue, concrete next step | Direct response |

**Implementation**: Tone adapter lives in `respond node` and `artifact_engine`. It reads `audience_hint` from ARIAState (set at intake from Teams channel, role tag, or urgency signal) and selects the render template. Skill output is unchanged — only the presentation layer varies.

---

### 26.4 — Agent-to-Agent Collaboration (Governed)

LangGraph remains the orchestrator. Within that, two controlled A2A patterns are supported:

**Pattern 1 — Specialist handoff**: Router dispatches to a primary skill agent. That agent can request a specialist (e.g., PR review agent spawns a security-specialist sub-agent for high-risk diffs). Handoff is logged, audited, bounded by the same action tiers.

**Pattern 2 — Bounded debate** (via AutoGen at Weeks 27–29): Two agents with opposing perspectives review the same output (Proposer vs. Skeptic). Used for: Evolution proposal review, ML Research peer review, high-stakes PR review on sensitive changes. The debate produces a structured verdict — both positions logged in Work Ledger.

**What stays governed:**
- Every handoff logs: from_agent, to_agent, reason, task_id, timestamp
- Sub-agents inherit parent task's action tier — cannot escalate autonomously
- Debate patterns have a moderator node that terminates after N rounds and produces a verdict
- No agent-to-agent communication bypasses the LangGraph state

---

### 26.5 — Knowledge Vault / Second Brain Mode (Pillar 8 extension)

ARIA's knowledge layer is not just a RAG index. It is a **Second Brain** that organises all project knowledge:

**What gets ingested:**
- PR reviews (past verdicts, risk patterns, common issues per service)
- Incidents and post-mortems (root causes, remediation steps, recurring patterns)
- Jira exports (sprint history, blocker patterns, team velocity)
- CI/CD logs (build failure signatures, flaky test patterns)
- Architecture notes and ADRs (decision history, rationale, alternatives)
- Eval results (skill performance over time, regression history)
- Learning notes (techniques studied, mental models built — yes, ARIA learns from Kunal's learning)
- Terminal outputs and test runs (code intelligence context)

**Organisation strategy:**
- Document type tags: `incident`, `pr_review`, `architecture`, `eval`, `learning`, `jira`, `ci_cd`
- Source attribution on every chunk (for citations and provenance)
- Recency weighting — recent incidents surface before old ones
- Cross-doc linking: PR review → references incident → references architecture decision

**Why it matters**: At Week 30, ARIA can answer "What's the most common risk pattern in our recommendation service PRs over the last 6 months?" — from real indexed data, not a hallucinated answer.

---

### 26.6 — Shadow Learning → Fine-Tuning Pipeline

The pipeline from frontier model usage to self-hosted specialist:

```
Step 1 — Shadow Phase (Weeks 3–28)
  Frontier model (Claude) handles all tasks
  Every output logged to Work Ledger with: input, output, task_type, skill_version

Step 2 — Human Teaching (Weeks 11–28)
  Kunal approves or rejects each output
  Corrections captured as DPO pairs: (input, rejected_output, corrected_output)
  Approved outputs = SFT positive examples

Step 3 — Dataset Curation (Week 29)
  Filter Work Ledger: skill_name=pr_review, approved=True → SFT dataset
  Filter: approved=False, correction exists → DPO dataset
  Dedup, clean, validate format consistency
  Synthetic data generation if < 50 examples for any skill

Step 4 — Fine-Tuning (Week 29)
  Base model: Qwen2.5-Coder-7B-Instruct (benchmark Llama-3.1-8B-Instruct)
  Method: LoRA via Unsloth + TRL SFTTrainer → then DPO pass
  Hardware: RunPod A40, ~$0.80/run
  Output: fine-tuned .gguf checkpoint

Step 5 — Serve + Route (Week 29+)
  Deploy via vLLM (OpenAI-compatible endpoint)
  Model Router v3: stable, high-volume tasks → fine-tuned model
  Frontier model retained for novel/high-stakes tasks

Step 6 — Evaluate + Iterate
  Compare fine-tuned vs. Claude on same inputs
  LangSmith rubric scores both → if FT wins on ≥3/5 rubric dimensions, promote
  Work Ledger tracks fine-tune version per skill output
```

---

### 26.7 — Safe Execution Environment (Structural, Not Just Documented)

Safety properties must be built into the system architecture, not just listed as rules.

| Safety Property | Mechanism | Where Built |
|---|---|---|
| **Dry-run mode** | `execution_mode: Literal["dry_run", "live"]` in ARIAState; tools check before acting | Week 21 (Runtime Harness) |
| **Sandbox DB** | Separate DB connection string for test/staging environments | Week 15 (Security layer) |
| **Staging tool variants** | `GitHubToolStaging` mirrors `GitHubTool` but writes to a fork/test repo | Week 21 |
| **Token/cost budget** | Per-task token ceiling in ARIAState; LLM calls check budget before invoking | Week 21 |
| **Loop detection** | `steps_completed` length check; circular state detection in graph compiler | Week 21 |
| **Tool permission scopes** | Each tool registered with `min_permission_tier`; checked at invocation | Week 15 |
| **Approval gates** | T4+ actions pause graph, emit `approval_required` event, wait for human resume | Week 16 |
| **Idempotency keys** | Every tool call gets `idem_key = hash(task_id + tool_name + input_hash)` | Week 21 |
| **Audit logging** | Every tool invocation writes to `tool_audit.jsonl` regardless of outcome | Week 15 |

---

### 26.8 — Generative UI Canvas (V2 Frontend Vision)

Beyond output cards, ARIA should create **persistent workspaces**:

- A PR review doesn't just return a card — it creates a workspace: risk panel + comment drafts + approval history + linked test coverage, all editable
- A KPI investigation creates a persistent dashboard: anomaly timeline + root cause tree + action tracking
- An incident creates a war room view: timeline, affected services, assigned tasks, resolution log

**V1 foundation (Weeks 13+)**: Schema-driven output cards (Section 26.2)
**V2 evolution**: Workspace persistence, multi-skill views, ARIA-generated dashboard layouts, user-editable artifacts
**V3 vision**: ARIA proposes new dashboard layouts from Work Ledger patterns — "You always check these 3 things after a deploy. Want me to build you a deploy-readiness view?"

---

### 26.9 — Proactive Notification Intelligence

Notifications are governed skill outputs, not fire-and-forget alerts.

**V1 trigger conditions (Weeks 16–20):**

| Trigger | Skill | Channel | Cooldown |
|---|---|---|---|
| CI/CD pipeline failure | `ci_cd_skill` | Teams → #engineering | 30 min |
| PR risk score ≥ high | `pr_review_skill` | Teams DM to PR author | per-PR |
| Approval pending > 2h | `approval_tracker` | Teams DM to approver | 2h |
| Jira blocker detected | `jira_skill` | Teams → #sprint-standup | daily |
| Test coverage regression > 5% | `qa_skill` | Teams → #ci-alerts | per-build |

**V2 additions:** KPI anomaly (CTR drop > threshold), SLA breach prediction, model performance degradation.

**Governance rules:**
- Mute controls per channel and trigger type
- Escalation path: DM → channel → manager DM (after N hours unresolved)
- Every notification logged in Work Ledger as a task of type `notification`
- No notification without a skill output behind it — the notification IS the artifact

---

## 27. PERSONAL SKILL STACK & CAREER POSITIONING

**What ARIA builds in Kunal's profile (by Week 30):**

| Domain | What gets built | Why it's rare |
|---|---|---|
| **AI Leadership** | Full 30-week AI Employee platform from zero, production-grade architecture decisions, governed evolution | Most AI leads have used tools — few have designed one from first principles |
| **Media-Tech Domain** | Deep KPI investigation, CTR analysis, recommendation systems, CMS pipelines, notification services at Amar Ujala scale | Domain expertise + AI depth in the same person is extremely rare |
| **Agentic AI Architecture** | LangGraph StateGraph, multi-agent patterns (LangGraph + CrewAI + AutoGen), Agent Factory, Agent Control Plane | Production agentic systems are still rare in India at this depth |
| **Governance & Trust** | Action tiers, approval gates, audit logging, Constitutional AI, Safe Execution Environment | Most AI engineers skip governance — it's the differentiator for enterprise sales |
| **ML/LLM Engineering** | RAG (HyDE, Self-RAG, Adaptive), Code Intelligence (AST), Memory (MemGPT), Fine-tuning (LoRA/DPO), vLLM serving | Full stack: not just inference, but retrieval + memory + post-training |
| **Platform Product Thinking** | 24-pillar product with moat analysis, AaS framing, AI Work Ledger with ROI proof, surprise reveal strategy | AI + product strategy thinking is a rare combination |

**The one-liner for LinkedIn/interviews:**
> "I built ARIA — a 30-week AI Employee platform with 24 capability pillars, institutional memory, governed self-evolution, and a fine-tuned specialist model trained on real approved outputs. It's been working inside Amar Ujala for 6 months before anyone knew it existed."

**Why Harness Engineering is the career differentiator:**
Prompt engineers are a commodity. Model trainers are specialists. But engineers who can design the full harness — runtime, memory, tools, governance, evals, model routing, UI layer, work ledger — are genuinely scarce. ARIA is a 30-week proof of exactly that capability.

---

## 28. FUTURE ARCHITECTURE VISION (V2 / V3 — DOCUMENTATION ONLY)

This section captures three architectural directions that ARIA should evolve toward, recorded as **vision and roadmap only** — none of the items below are implemented in V1. They are documented now so that V1 design decisions (especially Week 29–30 work) leave clean attach points for these layers later.

When Week 29+ implementation choices come up, prefer designs that make these future layers easier to add later. Do NOT pre-build them.

---

### 28.1 — Agent Instruction Engine / Subagent Prompting Layer (V2)

**The vision**: ARIA should not only invoke fixed graph nodes. The main ARIA orchestrator should be able to **generate structured task briefs** for specialist subagents and workflows, then delegate to them under governance.

For complex tasks, ARIA generates one or more **typed Subagent Instruction Objects**. Each instruction is a Pydantic model with these fields:

| Field | Purpose |
|---|---|
| `subagent_name` | The specialist role (e.g. `pr_review_agent`, `recommendation_impact_agent`) |
| `task_objective` | What this subagent must produce |
| `parent_task_id` | Correlation ID linking back to the originating ARIA task |
| `workflow_id` | The workflow this brief is one step of |
| `allowed_context` | What memory / docs / artifacts the subagent may read |
| `forbidden_context` | Explicit exclusions (e.g. PII, other teams' projects) |
| `tools_allowed` | Subset of the tool catalog this subagent may call |
| `tools_forbidden` | Tools it must NOT touch (high-risk or out-of-scope) |
| `expected_output_schema` | Pydantic schema the subagent's output must validate against |
| `risk_level` | Maps to Action Tier (T1–T5) for permission boundary |
| `token_budget` / `cost_budget` | Hard ceilings enforced by the runtime harness |
| `deadline` / `priority` | Scheduling hint for Control Plane |
| `approval_requirement` | Whether outputs need human sign-off before merge |
| `evaluation_criteria` | Rubric the orchestrator uses to grade the subagent's output |
| `ledger_correlation_id` | ID under which all subagent events are logged in the Work Ledger |

**Worked example** — for *"Review this PR and check if it impacts recommendation CTR"*, ARIA generates briefs for:
1. **PR Review Agent** — code-level review, risk scoring (T3 draft, no execute)
2. **Recommendation Impact Agent** — analyzes whether the diff touches ranking/retrieval signals (read-only)
3. **QA / Test Agent** — generates test cases and identifies coverage gaps
4. **Business Summary Agent** — translates technical findings to manager-readable language

Each subagent returns a typed output. ARIA merges, verifies, evaluates against the per-subagent rubric, and produces the final artifact.

**Governance rules (non-negotiable)**:
- Subagents cannot self-expand permissions or tool access
- Subagents cannot directly execute T4 / T5 (Execute / Autonomous) tools
- Every subagent prompt AND output is logged in the Work Ledger under `ledger_correlation_id`
- Subagent instruction templates are versioned (`SubagentBrief.template_version`) so DSPy-style optimization is possible
- Subagent outputs are evaluated by the orchestrator BEFORE being merged into ARIA's final artifact
- Any subagent output that proposes a risky action escalates to human approval

**Where this slots in the existing architecture**:
- Built on top of **Pillar 13** (Agent Factory) — the factory scaffolds the subagent
- Run by **Pillar 15** (Agent Control Plane) — schedules, monitors, kills runaway subagents
- Enforced by the **Governance Harness** (§ 26.1 layer 3) — permission scopes, approval gates
- Evaluated by the **Evaluation Harness** (§ 26.1 layer 4) — per-subagent rubrics
- Logged by the **Memory / Work Ledger** (§ 26.1 layer 5)

**V1 alignment**: do NOT add a SubagentBrief model in Week 29. But when designing Work Ledger v2 schemas (Week 29 priority #1), include a `correlation_id` field on every event so that subagent traces can plug in later without a migration.

---

### 28.2 — Human-like Work Intelligence Layer (V2 framing)

**The vision**: ARIA should feel **human-like in work capability** — inspired by the Chitti-from-Enthiran ambition but implemented as a governed enterprise AI employee, never as uncontrolled autonomy.

"Human-like" decomposes into ten observable behaviours, each of which already maps to a specific pillar or harness layer:

| # | Human-like behaviour | Where it lives |
|---|---|---|
| 1 | Understands vague business/engineering requests | Conversational Tasking (Pillar 1) |
| 2 | Converts requests → structured goals, plans, workflows, subtasks | Task decomposition (Pillar 1) + Workflow Mining (Pillar 19) |
| 3 | Asks clarifying questions when needed | Pillar 1 + Pillar 17 (Human Teaching) |
| 4 | Prompts and manages specialist subagents | **§ 28.1 Subagent Instruction Engine** + Pillar 13 + Pillar 15 |
| 5 | Uses tools and enterprise systems safely | Tool Execution Harness (§ 26.1 layer 2) + Action Tiers |
| 6 | Remembers prior tasks, decisions, incidents, outcomes, preferences | Memory Harness (§ 26.1 layer 5) + Pillar 8 (Knowledge Vault) + Pillar 17 (Human Teaching) |
| 7 | Communicates differently for dev / manager / leadership / QA / product | Audience-Aware Communication (§ 26.3) + Pillar 7 |
| 8 | Takes ownership — produces artifacts, recommendations, next actions | Artifact Engine (Pillar 7) + Decision Intelligence (Pillar 20) |
| 9 | Learns from feedback and corrections | Pillar 17 (Human Teaching) + Shadow Learning pipeline (§ 26.6) |
| 10 | Proposes self-improvements through monitor → propose → sandbox → evaluate → approve → deploy → rollback | Evolution Harness (§ 26.1 layer 6) + Pillar 18 |

**Critical guardrail — what "human-like" does NOT mean**:
- Does NOT mean ARIA bypasses governance
- Does NOT mean ARIA bypasses approval / permission / audit logging / evidence checks / rollback rules
- Does NOT mean ARIA self-modifies production behavior without human sign-off
- "Human-like" is a description of *work capability*, not autonomy ceiling

**Positioning line (locked)**:
> *"ARIA is designed to behave like a capable AI employee: understanding goals, planning work, delegating to subagents, using tools, remembering decisions, communicating by audience, learning from feedback, and improving safely under governance."*

**V1 alignment**: V1 already implements behaviours 1, 2, 3, 5, 6, 8, 9, 10. Behaviour 4 (subagent management) is § 28.1's V2 work. Behaviour 7 (audience-aware) is in § 26.3 — partial in V1 via the respond node, full elaboration in V2.

---

### 28.3 — Harness Engineering Platform Positioning (canonical)

**The vision**: ARIA is explicitly positioned as a **Harness Engineering platform**, not a prompt wrapper or a single-agent toy. This is the framing for LinkedIn, the manager demo, the AaS pitch, and every interview.

The model is one component. The product is the system around the model — and that system is the seven harness layers in § 26.1 (which now explicitly includes Subagent / Workflow as layer 7).

**Positioning line (locked)**:
> *"ARIA is built using Harness Engineering: the model is only one component; the real intelligence comes from orchestration, memory, tools, governance, evaluation, workflows, subagents, and safe execution around the model."*

**How this affects Week 29–30 decisions**:
- ROI Dashboard copy must use harness language ("evaluation harness saved N hours of regression triage"), not generic AI marketing
- LinkedIn launch post (Week 30) leads with "Harness Engineering" and the seven layers — model choice is a footnote
- AaS blueprint (Week 30) sells the harness, not the model. Different tenants can swap models; the harness is the moat.

**Cross-references**:
- § 26.1 — the seven harness layers (now including Subagent / Workflow as layer 7)
- § 22 — Platform vs Employee distinction (the platform IS the harness; ARIA is the first employee on it)
- § 27 — career positioning (Harness Engineering is the differentiator)
- § 17 (moat analysis) — six of the seven moat layers are harness investments

---

### 28.4 — Agentic AI Roadmap: Future Capability Tracking (V2 / V3 — DOCUMENTATION ONLY)

**The vision**: eight capabilities drawn from the latest agentic-AI direction (delegated agent identity, A2A envelopes, agent-UI event streams, persistent workspaces, branching experiments, a security gateway, episode packages, and agent-config compatibility). These are **roadmap notes only** — none are implemented in V1, and **none are to be built during Week 29**. They are recorded so that current design choices (Work Ledger v2, Model Lifecycle Registry, Fine-Tuning Prototype) leave clean attach points. Each maps onto an existing pillar or harness layer — they are clarifications of where ARIA evolves, not new pillars.

| # | Future capability | Slots onto |
|---|---|---|
| 1 | Agent Identity & Delegated Authorization | § 28.1 Subagent Instruction Engine + Governance Harness (§ 26.1 L3) + Work Ledger (Pillar 16) |
| 2 | A2A-Ready Agent Message Envelope | Pillar 22 (Marketplace) + A2A interop (tech stack) — MCP-first / A2A-ready |
| 3 | AG-UI / Agent-UI Event Stream | § 26.2 Declarative Generative UI + § 26.8 Generative UI Canvas + Pillar 7 |
| 4 | Persistent Agent Workspace | § 26.8 Generative UI Canvas + Memory Harness (§ 26.1 L5) |
| 5 | Agent Branching / Experiment Paths | Evolution Harness (§ 26.1 L6) + Pillar 18 |
| 6 | Agent Security Gateway | Governance Harness (§ 26.1 L3) + § 26.7 Safe Execution + Pillar 10 |
| 7 | Episode Package / Trace-Based Evaluation | Evaluation Harness (§ 26.1 L4) + Work Ledger (Pillar 16) + Pillar 12 |
| 8 | Agent Configuration Compatibility | Pillar 8 (Knowledge Vault) + Skill Registry + § 28.1 |

**1 — Agent Identity & Delegated Authorization (V2)**
- Every subagent call carries a typed identity/authorization envelope: `caller_agent_id`, `target_agent_id`, `human_owner`, `parent_task_id`, `workflow_id`, `correlation_id`, `allowed_context`, `forbidden_context`, `allowed_tools`, `forbidden_tools`, `risk_level`, `expiry_time`, `approval_requirement`, `audit_trace_id`.
- Subagents inherit **only explicitly delegated** permissions — never the parent's full scope, never self-expanding (reinforces the § 28.1 governance rules).
- Every agent-to-agent call is logged in the Work Ledger.
- *Extends § 28.1's `SubagentBrief` with `caller_agent_id` / `target_agent_id` / `human_owner` / `expiry_time` / `audit_trace_id`. Work Ledger v2 already carries `correlation_id` + `actor`, so the ledger half of this needs no migration.*

**2 — A2A-Ready Agent Message Envelope (V2)**
- V1 stays **LangGraph-controlled internal orchestration** — no change.
- V2 supports A2A-compatible envelopes **without becoming dependent on external A2A infrastructure** (interop optional, not a runtime dependency).
- Locked stance: **ARIA is MCP-first for tools and A2A-ready for agent collaboration.**

**3 — AG-UI / Agent-UI Event Stream (V2)**
- The frontend consumes a structured event stream: `task_started`, `plan_created`, `approval_required`, `subagent_started`, `tool_called`, `artifact_created`, `progress_update`, `cost_update`, `error`, `completed`, `rollback_available`.
- Enables live timelines, approval cards, workspaces, and rollback controls — the runtime surface of § 26.2 / § 26.8.

**4 — Persistent Agent Workspace (V2/V3)**
- Every major task eventually owns a workspace folder: task brief, plan, logs, artifacts, terminal outputs, approvals, evals, and rollback snapshots.
- Useful for long-running projects (e.g. an AI Astrologer build for MyJyotish) where context must persist across many sessions.

**5 — Agent Branching / Experiment Paths (V3)**
- The Evolution Harness supports branching plans, prompts, models, and workflows.
- Branches compared by **quality, cost, latency, safety, approval need, and silent-deviation risk**.
- Promote the best branch; **always keep a rollback path** (consistent with the governed monitor → propose → sandbox → approve → canary → promote → rollback loop).

**6 — Agent Security Gateway (V2)**
- A centralized guardrail layer for: prompt-injection detection, tool-call risk scoring, output-leakage scanning, data-exfiltration checks, untrusted-context quarantine, and delegated-authorization enforcement.
- Sits in front of the Tool Execution + Governance harnesses; complements § 26.7 Safe Execution (structural safety) with input/output threat screening.

**7 — Episode Package / Trace-Based Evaluation (V2)**
- Each serious ARIA run emits an auditable **episode package**: task brief, context used, tools used, model used, subagents used, artifacts, approvals, errors, verification, rollback proof, final outcome.
- This is the unit of trace-based evaluation and audit — a superset of the Work Ledger correlation trail, packaged for replay/grading.

**8 — Agent Configuration Compatibility (V2)**
- Future ARIA understands repo-level config files (`AGENTS.md` / `CLAUDE.md` / `ARIA.md`) and converts them into context rules, skill-registry entries, subagent briefs, workflow rules, and evaluation constraints.
- Makes ARIA portable across repos without bespoke wiring per project.

**V1 / Week 29 alignment (non-negotiable)**:
- **Do NOT implement any of the above now.** Current implementation remains **Week 29 Priority 4 — Model Lifecycle Registry v1**, then **Priority 5 — Fine-Tuning Prototype**.
- When Week 29 choices come up, prefer designs that leave clean attach points (e.g. keep `correlation_id` / `actor` on every ledger event for items 1, 2, 7) — but do not pre-build the layers.

**Cross-references**: § 28.1 (Subagent Instruction Engine), § 26.1 (seven harness layers), § 26.2 / § 26.8 (UI), § 26.7 (Safe Execution), § 14 (governed self-evolution), Pillars 8 / 10 / 12 / 16 / 18 / 22.

---

## 29. WEEK 29 PLAN — AI WORK LEDGER + FINE-TUNING PROTOTYPE

**Status**: ✅ **COMPLETE — all five priorities independently ACCEPTED by Codex.** 1021 backend tests passing (1 skipped) at Week 29 acceptance; no real training or deployment occurred; production graph / model router unchanged. **Week 30 (Launch Readiness) is COMPLETE — ACCEPTED by Codex (2026-06-15); see § 3 for the canonical current status.**

### Week 29 — Final Status (Accepted by Codex)

| Priority | Deliverable | Status |
|---|---|---|
| 1 | AI Work Ledger v2 | ✅ Accepted |
| 2 | ROI Dashboard | ✅ Accepted |
| 3 | Dataset Export Prototype | ✅ Accepted |
| 4 | Model Lifecycle Registry v1 | ✅ Accepted |
| 5 | Fine-Tuning Prototype (offline dry-run — no real training/deploy) | ✅ Accepted |

Codex final verdict: no remaining findings; fine-tuning tests 35 passed; full backend 1021 passed / 1 skipped; py-compile passed; registry + fine-tuning demos passed; no real training or deployment; `git diff --check` passed; test-deployment pollution absent; the DPO `chosen`-binding guard in `planner.py` accepted. **Week 29: COMPLETE.**

**Implementation order is fixed** by ROI-of-effort. Each item must reach the listed checkpoint before the next one starts — do NOT parallelize the first three. *(Historical plan retained below for the record; all five priorities are now accepted per the Final Status table above.)*

### Priority 1 — AI Work Ledger v2 *(must complete first)*

Extend the existing `apps/backend/aria/work_ledger.py` JSONL log to a queryable, schema-versioned ledger that is the source of truth for the ROI Dashboard, the Dataset Export, and the eventual fine-tuning training set.

Required schema additions (Pydantic-validated, versioned):
- `ledger_event_version` — schema version field on every event (for forward-compat migrations)
- `correlation_id` — top-level ID grouping all events for one logical task (parent task + all subagent events). **Add this even though subagents don't exist yet** — § 28.1 will plug in cleanly.
- `actor` — `"aria" | "human:<name>" | "subagent:<role>"` (future-proof for § 28.1)
- `risk_tier` — T1–T5 of the action recorded
- `cost_tokens_in` / `cost_tokens_out` / `cost_usd` — per-event costs (needed for ROI math)
- `evaluation_score` — optional rubric score when an event ran through the eval harness
- `outcome_label` — `approved | rejected | rolled_back | superseded | active | failed | abstained`
- `latency_ms` — wall-clock for the event

Existing event types must be migrated to v2 with a one-time backfill of `ledger_event_version=1` for older records.

**Checkpoint**: 100 % of `aria/work_ledger.py` writes go through the v2 schema; reading code (notifier, evolution, governance) updated; existing tests pass; new tests cover the schema migration and the `correlation_id` propagation.

### Priority 2 — ROI Dashboard

Frontend view (in `apps/frontend/src/`) that reads from the Work Ledger v2 and surfaces:
- Tasks completed by skill / week
- Approved vs rejected ratio
- Human time saved (estimated from `outcome_label=approved` × baseline-effort table)
- Cost spent (sum of `cost_usd`)
- Failure rate and rollback rate
- Evolution loop activity — proposals → canary → active → rolled_back

Copy uses **Harness Engineering language** per § 28.3 — every metric tied to one of the seven harness layers.

**Checkpoint**: dashboard renders from real Work Ledger v2 data; screenshot saved to `docs/demos/week_29_roi_dashboard.png`.

### Priority 3 — Dataset Export Prototype

`apps/backend/aria/ml/export_dataset.py` script that materializes training data from the Work Ledger:

- **SFT set**: events where `outcome_label = approved`, exported as `(input, output)` JSONL
- **DPO set**: pairs where a rejected output and a corrected output exist for the same task, exported as `(prompt, chosen, rejected)` JSONL
- Deduplication by hash; quality filter (`evaluation_score >= threshold`); format validation
- Synthetic data generation hook left as a TODO stub (§ 26.6 Step 3 — implemented later when real-example count < 50)

**Checkpoint**: a `pr_review` SFT export and a (possibly empty) DPO export are produced from the Work Ledger v2. NO training is run yet.

### Priority 4 — Model Lifecycle Registry v1

Minimal MLOps registry (`apps/backend/aria/ml/registry.py`) tracking, for each candidate model:
- Model name + base model version
- Training dataset version (hash of the export from Priority 3)
- LangSmith eval score on a fixed holdout
- Deployment endpoint URL (filled when served, blank for prototypes)
- Rollback pointer (the previous model version this would replace)
- Active skills using the model

Persisted as JSONL under `apps/backend/ml/registry.jsonl` for V1; matches the InMemoryUpdateStore pattern (file-backed, atomic flush, schema-validated).

**Checkpoint**: registry can record at least one prototype entry; reading and writing tested; the structure makes the Week 29 fine-tune (Priority 5) registerable.

### Priority 5 — Fine-Tuning Prototype *(prototype only — NO production deployment)*

A single end-to-end LoRA training run on the Priority 3 export to **prove the pipeline**, not to ship a model.

- Base model: Qwen2.5-Coder-7B-Instruct (Llama-3.1-8B-Instruct benchmark comparison is V2)
- Library: Unsloth + TRL `SFTTrainer`
- Hardware: RunPod A40, ~$0.80/run
- Output: a `.gguf` or LoRA-adapter checkpoint, an LangSmith eval score on the holdout, and a registry entry from Priority 4
- **EXPLICITLY NOT in scope**: vLLM serving, model router wire-up, production traffic, A/B test

**Checkpoint**: registry shows one Week-29 prototype entry; eval score is recorded; nothing is deployed. The decision *"would this fine-tune outperform Claude on stable PR-review patterns?"* is answered by data, not by guesswork.

### Out of scope for Week 29 (deferred to V2 or post-Week-30)

- Subagent Instruction Engine (§ 28.1) — V2
- Generative UI Canvas (§ 26.8) — V2
- Full vLLM serving layer — Week 30 if there's time, else V2
- Production fine-tuned model in the Model Router — V2
- Multi-tenant AaS (Pillar 23) — V3

### Week 29 alignment with § 28 future vision

- Work Ledger v2's `correlation_id` + `actor` fields make § 28.1 subagent integration a no-migration add
- ROI Dashboard's harness-language copy reinforces § 28.3 positioning ahead of the Week 30 reveal
- Model Lifecycle Registry v1 anchors § 28.2 behaviour #10 (governed self-improvement loop) with a concrete artifact
- Fine-tuning prototype proves Shadow Learning pipeline (§ 26.6) is real, not aspirational
