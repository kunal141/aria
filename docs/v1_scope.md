# ARIA V1 Scope

V1 is ARIA's proof-of-concept to demonstrate autonomous AI work — a system that earns trust through governed action before expanding into full workforce orchestration.

## V1 Definition: "One AI Employee, One Vertical, Full Loop"

V1 proves ARIA can:
1. Receive a goal (not a prompt)
2. Break it into tasks
3. Execute those tasks using skills and sub-agents
4. Remember everything it did
5. Report outcomes proactively
6. Accept feedback and improve

---

## V1 Primary Use Case: AI Engineer

**V1 is ARIA as an AI Engineering colleague — not Editorial AI.**

This is intentional:
- Kunal (the builder) is the primary user in V1 — real usage from Day 1
- ARIA reviews her own code, generates her own tests, documents her own architecture
- Every PR Kunal opens on the `aria/` repo is reviewed by ARIA — this is self-dogfooding
- Real signal from real work on a real codebase from Week 8 onwards
- Editorial AI is **Vertical 2** — it requires integrations with Amar Ujala's CMS and KPI APIs that don't exist yet

**Why AI Engineer first:**
Every bug ARIA catches in her own codebase is proof of QA capability. Every deployment risk she flags on her own PRs is proof of code intelligence. The self-dogfooding corpus is what makes ARIA irreplaceable.

---

## V1 Primary Skills (AI Engineer Vertical)

| Skill | Description | Week Built |
|---|---|---|
| PR Review | Code quality, deployment risk, business impact, missing tests | Week 7 |
| Test Case Generation | Functional tests, edge cases, coverage gap detection | Week 17 |
| CI/CD Failure Summary | Build log analysis, root cause, rollback recommendation | Week 19 |
| Code Intelligence | Repo Q&A, AST parsing, dependency graph | Week 10 |
| Jira Ticket Creation | Ticket from PR failure, refinement, blocker tracking | Week 20 |
| KPI Investigation | Anomaly detection, root cause, statistical analysis | Week 11 |

---

## V1 Domains

| Domain | V1 Capability | Out of Scope (V2+) |
|---|---|---|
| **Orchestration** | LangGraph stateful task graph, routing, checkpointing | Self-modifying graphs |
| **Context Engineering** | Working memory design, context injection, summarization | Full context optimizer |
| **Memory** | User + Task + Decision + Outcome memory; semantic retrieval | Full 6-layer fabric |
| **Skills** | 6 core skills (PR review, test gen, CI/CD, code intel, Jira, KPI) | Full skill registry |
| **Artifact Engine** | Reports, PR notes, email drafts, technical briefs | Full template library |
| **Knowledge Retrieval** | SOP search, architecture doc retrieval, meeting recall | RAPTOR + GraphRAG |
| **Identity** | Teams bot + basic persona | Email account, calendar integration |
| **Governance** | Action tiers 1-3 (Read, Recommend, Draft), RBAC, audit log | Tiers 4-5 (Execute, Autonomous) |
| **AI Engineer** | PR review, test generation, CI/CD analysis, code intelligence | Full engineering automation |
| **Evaluation** | LangSmith tracing + 5 rubrics + regression suite | Full LLM-as-judge framework |
| **Agent Factory** | Manual agent registration | Autonomous agent design + sandbox |
| **Sub-agents** | 1-2 specialist agents (Analytics + QA) | Full governed replica set |
| **Editorial AI** | **Vertical 2 — NOT V1** | Full editorial workflow automation |

---

## V1 Success Criteria

By end of Week 13 (Phase 3 complete), ARIA V1 should be able to:

- [ ] Accept a goal via Teams @mention or API
- [ ] Decompose goal into subtasks with dependency graph
- [ ] Execute subtasks using registered skills
- [ ] Retrieve relevant context (memory + knowledge) to inform execution
- [ ] Store outcome in persistent memory
- [ ] Post result to Teams with confidence score
- [ ] Accept correction feedback and log it
- [ ] **Review a real PR on her own codebase** (self-dogfooding begins)
- [ ] **Generate test cases for a real PR change**
- [ ] **Summarize a CI/CD failure with root cause**
- [ ] All 5 rubric scores established in LangSmith (baseline set)

---

## V1 Non-Goals

- No autonomous execution of write/delete actions in external systems
- No self-spawning of agents (manual registration only in V1)
- No email account (Teams bot only)
- No predictive ML models (rule-based anomaly detection only)
- No A2A protocol (MCP only in V1)
- No public API or multi-tenant support
- No Editorial AI (deferred to Vertical 2)

---

## Vertical 2: Editorial AI Employee

**Deferred from V1 — planned for after Week 22**

**Why deferred:**
- Requires Amar Ujala CMS API integration (not yet available)
- Requires article KPI API connector
- No self-dogfooding possible on editorial tasks before V1 proves the platform

**When it ships:**
- After Agent Factory exists (Week 22)
- Editorial Agent is the first agent created by the Agent Factory
- CMS + KPI integrations are built as MCP tools
- Editorial Agent reviews articles, tracks performance, recommends improvements

**Use Case (when ready)**:
Monitor article performance in real time. Identify underperformers. Recommend editorial action.

| Input | Processing | Output |
|---|---|---|
| Article KPI API (pageviews, time-on-page, bounce rate) | Fetch KPIs every N hours → compare against baselines → flag anomalies → generate recommendation | Teams channel message to editorial team + memory entry |

**Action Tier**: Tier 2 (Recommend) — ARIA recommends, human editor decides

---

## Repo Structure (v3 Aligned)

```
aria/
├── apps/
│   ├── api/                    # FastAPI backend
│   └── frontend/               # React dashboard
│       └── src/
│           ├── ARIAMasterPlan.jsx    # 30-week plan viewer
│           └── ARIADashboard.jsx     # Operational dashboard
├── orchestration/
│   ├── graphs/                 # LangGraph state graphs
│   ├── nodes/                  # Individual graph nodes
│   ├── state/                  # State type definitions
│   ├── router/                 # Task routing logic
│   └── runtime_harness/        # Retries, checkpointing, idempotency
├── skills/
│   ├── registry.py             # Skill registration + discovery
│   ├── pr_review/              # PR review skill (v1+)
│   ├── kpi_investigation/      # KPI anomaly detection
│   ├── reporting/              # Artifact generation
│   ├── jira_support/           # Jira ticket management
│   ├── test_case_support/      # Test generation + coverage
│   ├── code_review/            # Code intelligence skills
│   └── artifact_generation/    # Reports, briefs, emails
├── agents/
│   ├── aria/                   # Core ARIA orchestrator
│   ├── analytics/              # Analytics sub-agent
│   └── editorial/              # Editorial AI Employee (V2)
├── memory/
│   ├── store.py                # Memory store interface
│   ├── embeddings.py           # Embedding + retrieval
│   └── schemas.py              # Memory type schemas
├── integrations/
│   ├── teams/                  # Microsoft Teams bot
│   ├── mcp/                    # MCP tool definitions
│   └── data_sources/           # API connectors
├── code_intelligence/          # AST, dependency graph, repo indexing
├── governance/
│   ├── action_tiers.py         # Tier enforcement
│   ├── rbac.py                 # Role-based access
│   └── audit_log.py            # Audit trail
├── evaluation/
│   ├── langsmith_setup.py
│   ├── rubrics/                # Scoring rubrics per skill
│   └── benchmarks/             # Golden examples + regression tests
├── evolution/
│   ├── tracker.py              # AI ecosystem monitoring
│   ├── proposals/              # Capability proposal templates
│   └── sandbox/                # Safe integration testing
├── schemas/
│   └── types.py                # Shared Pydantic type definitions
├── docs/                       # This directory
├── tests/
├── scripts/
├── .env.example
├── pyproject.toml
└── README.md
```
