# ARIA Capability Map

Full capability inventory across all 24 pillars. Week numbers indicate when each capability is built.

**Legend**: ✅ V1 | 🔜 V2 | 🔜 V3 | Week = build week

---

## Pillar 1 — Conversational Tasking
*Accept goals, not prompts. Decompose, route, synthesize.*

| Capability | V | Week |
|---|---|---|
| Goal intake (Teams @mention, API, scheduled) | ✅ | 4 |
| Goal decomposition into dependent subtasks | ✅ | 4 |
| Task routing to correct agent/skill | ✅ | 4 |
| Clarification before execution (when ambiguous) | ✅ | 7 |
| Multi-turn conversational task refinement | 🔜 V2 | 25 |
| Proactive task initiation (ARIA acts without being asked) | 🔜 V2 | 19 |

---

## Pillar 2 — AI Engineering
*ARIA as AI Engineer colleague. V1 primary use case.*

| Capability | V | Week |
|---|---|---|
| PR review (code quality, deployment risk, business impact) | ✅ | 7 |
| Test case generation (functional, edge, negative) | ✅ | 17 |
| CI/CD failure summary + root cause | ✅ | 19 |
| Release readiness assessment | ✅ | 19 |
| Coverage gap detection | ✅ | 18 |
| Failed test analysis | ✅ | 18 |
| Regression checklist generation | 🔜 V2 | 18 |
| Architecture decision review | 🔜 V2 | 23 |

---

## Pillar 3 — Data Science & Analytics
*Investigate data, detect anomalies, explain trends.*

| Capability | V | Week |
|---|---|---|
| KPI investigation + anomaly detection | ✅ | 11 |
| Statistical anomaly detection (z-score, rolling mean) | ✅ | 11 |
| Experiment analysis (A/B, feature flag results) | 🔜 V2 | 26 |
| Root cause investigation (structured hypothesis tree) | 🔜 V2 | 26 |
| Predictive trend analysis | 🔜 V3 | 28 |
| Dashboard generation from raw data | 🔜 V2 | 26 |

---

## Pillar 4 — QA / Test Intelligence
*Test strategy, case design, regression intelligence.*

| Capability | V | Week |
|---|---|---|
| Test case generation from PR/story | ✅ | 17 |
| Requirement-to-test mapping | ✅ | 17 |
| Negative + edge case identification | ✅ | 17 |
| Failed test summary + root cause | ✅ | 18 |
| Coverage gap detection | ✅ | 18 |
| Test regression risk scoring | 🔜 V2 | 18 |
| QA artifact generation (test plan, report) | ✅ | 17 |

---

## Pillar 5 — CI/CD & Release Intelligence
*Understand pipelines, flag risk, recommend releases.*

| Capability | V | Week |
|---|---|---|
| CI/CD failure summary (build log → root cause) | ✅ | 19 |
| Release readiness decision | ✅ | 19 |
| Deployment risk scoring | ✅ | 19 |
| Rollback recommendation | ✅ | 19 |
| Deployment summary artifact | ✅ | 19 |
| Historical failure pattern comparison | 🔜 V2 | 26 |

---

## Pillar 6 — Jira / Delivery Management
*Ticket creation, refinement, sprint intelligence.*

| Capability | V | Week |
|---|---|---|
| Jira ticket creation from PR failure | ✅ | 20 |
| Story refinement (acceptance criteria, sub-tasks) | ✅ | 20 |
| Sprint summary generation | ✅ | 20 |
| Blocker identification + escalation | ✅ | 20 |
| Issue-to-code mapping | 🔜 V2 | 20 |
| Velocity trend analysis | 🔜 V2 | 26 |

---

## Pillar 7 — Reporting & Communication
*Translate technical findings into stakeholder outputs.*

| Capability | V | Week |
|---|---|---|
| Leadership summary (business-first, non-technical) | ✅ | 21 |
| Stakeholder email drafting | ✅ | 8 |
| Teams update posting | ✅ | 7 |
| Technical-to-business translation | ✅ | 8 |
| Weekly performance summary | ✅ | 21 |
| Executive briefing artifact | ✅ | 21 |
| Audience-aware output formatting | ✅ | 8 |

---

## Pillar 8 — Knowledge / RAG / Org Intelligence
*ARIA knows the organization's history, SOPs, decisions.*

| Capability | V | Week |
|---|---|---|
| Document + SOP retrieval (basic RAG) | ✅ | 9 |
| HyDE (Hypothetical Document Embeddings) | ✅ | 9 |
| Self-RAG (ARIA critiques her own retrieval) | ✅ | 9 |
| Adaptive RAG (dynamic strategy) | ✅ | 9 |
| Architecture doc retrieval | ✅ | 9 |
| Past report retrieval | ✅ | 19 |
| Meeting recall | 🔜 V2 | 19 |
| RAPTOR (long document hierarchical summarization) | 🔜 V2 | 19 |
| GraphRAG (knowledge graph retrieval) | 🔜 V2 | 19 |

---

## Pillar 9 — Code Intelligence
*Deep understanding of the codebase.*

| Capability | V | Week |
|---|---|---|
| Repo Q&A (answer questions about codebase) | ✅ | 10 |
| Code indexing pipeline | ✅ | 10 |
| PR metadata ingestion | ✅ | 10 |
| AST parsing (code structure analysis) | ✅ | 10 |
| Dependency graph mapping | ✅ | 10 |
| Semantic code retrieval (find relevant code by meaning) | 🔜 V2 | 10 |
| Release risk scoring from code changes | 🔜 V2 | 19 |

---

## Pillar 10 — Governance & Trust
*Every action is authorized, auditable, and reversible.*

| Capability | V | Week |
|---|---|---|
| Tier 1 — Read | ✅ | 15 |
| Tier 2 — Recommend | ✅ | 15 |
| Tier 3 — Draft (human approves before sending) | ✅ | 16 |
| Tier 4 — Execute with Approval | 🔜 V2 | 16 |
| Tier 5 — Autonomous Low-Risk | 🔜 V3 | 29 |
| RBAC (role-based access to capabilities) | ✅ | 15 |
| Audit log (permanent record of all actions) | ✅ | 15 |
| Approval engine (route approvals to right humans) | ✅ | 15 |
| Risk scoring (confidence gating) | ✅ | 16 |
| Constitutional AI safety checks | ✅ | 14 |
| Approval prediction (from historical patterns) | 🔜 V2 | 25 |

---

## Pillar 11 — Agent Runtime Harness
*ARIA is reliable in production.*

| Capability | V | Week |
|---|---|---|
| Retry logic with exponential backoff | ✅ | 21 |
| Timeout handling | ✅ | 21 |
| Idempotency guarantees | ✅ | 21 |
| State checkpointing + resumability | ✅ | 3 |
| Failure classification | ✅ | 21 |
| Circuit breaker | 🔜 V2 | 21 |
| Dead letter queue for failed tasks | 🔜 V2 | 21 |

---

## Pillar 12 — Agent Evaluation Harness
*ARIA measures herself against rubrics.*

| Capability | V | Week |
|---|---|---|
| LangSmith tracing setup | ✅ | 13 |
| 5 skill rubrics (PR review, test gen, KPI, summary, report) | ✅ | 14 |
| Golden example datasets | ✅ | 14 |
| LLM-as-judge evaluation | ✅ | 14 |
| Regression test suite | ✅ | 14 |
| Baseline scores established | ✅ | 14 |
| Quality delta tracking (version-over-version) | 🔜 V2 | 29 |
| Automated regression alert | 🔜 V2 | 14 |

---

## Pillar 13 — Agent Factory
*ARIA can create specialist agents.*

| Capability | V | Week |
|---|---|---|
| Capability request intake | ✅ | 22 |
| Skill vs agent vs workflow classifier | ✅ | 22 |
| Agent scaffold generator | ✅ | 22 |
| Sandbox runner (isolated execution) | ✅ | 15 |
| Rubric evaluation before promotion | ✅ | 15 |
| Human approval gate for promotion | ✅ | 15 |
| Capability registry update | ✅ | 22 |
| Autonomous agent proposal | 🔜 V3 | 27 |
| Self-integration pipeline | 🔜 V3 | 27 |

---

## Pillar 14 — AI Workforce Expansion
*ARIA manages a team of specialist agents.*

| Capability | V | Week |
|---|---|---|
| Specialist agent spawning | 🔜 V2 | 17 |
| Task assignment to sub-agents | 🔜 V2 | 17 |
| Parallel sub-agent execution | 🔜 V2 | 17 |
| Result synthesis from multiple agents | 🔜 V2 | 17 |
| Agent retirement | 🔜 V2 | 17 |
| Agent performance comparison | 🔜 V3 | 29 |

---

## Pillar 15 — Agent Control Plane
*Central registry and health dashboard for all agents.*

| Capability | V | Week |
|---|---|---|
| Agent registry (list all agents + metadata) | 🔜 V2 | 16 |
| Agent health monitoring | 🔜 V2 | 16 |
| Lifecycle management (enable/disable/retire) | 🔜 V2 | 16 |
| Usage tracking (tasks handled, cost, latency) | 🔜 V2 | 16 |
| Agent version history | 🔜 V3 | 29 |
| Control plane dashboard UI | 🔜 V2 | GUI |

---

## Pillar 16 — AI Work Ledger
*The permanent, searchable record of everything ARIA has done.*

| Capability | V | Week |
|---|---|---|
| Task record (goal, plan, execution) | ✅ | 4 |
| Plan record (subtasks, dependencies) | ✅ | 4 |
| Agent record (which agent ran, cost) | 🔜 V2 | 16 |
| Tool record (which tools used) | 🔜 V2 | 16 |
| Artifact record (outputs generated) | 🔜 V2 | 8 |
| Approval record (what was approved/rejected) | 🔜 V2 | 15 |
| Action record (external actions taken) | 🔜 V2 | 16 |
| Outcome record (did it work?) | 🔜 V2 | 12 |
| ROI signal (time saved, quality improved) | 🔜 V3 | 29 |
| Improvement record (what ARIA changed based on feedback) | 🔜 V3 | 29 |
| ROI Dashboard UI | 🔜 V3 | 29 |

---

## Pillar 17 — Human Teaching Layer
*Every correction is a training signal.*

| Capability | V | Week |
|---|---|---|
| Feedback capture (thumbs up/down on outputs) | ✅ | 9 |
| Correction logging (what was wrong, what's right) | ✅ | 9 |
| User preference memory (learned from corrections) | ✅ | 9 |
| Approval pattern tracking | 🔜 V2 | 12 |
| Rejection pattern analysis | 🔜 V2 | 14 |
| Preference learning (RLHF-style from Work Ledger) | 🔜 V3 | 25 |

---

## Pillar 18 — Evolution & Capability Intelligence
*ARIA knows about new AI developments and proposes integrations.*

| Capability | V | Week |
|---|---|---|
| AI ecosystem monitoring (arxiv, GitHub, HuggingFace) | 🔜 V2 | 18 |
| Daily digest with relevance scoring | 🔜 V2 | 18 |
| Capability gap identification | 🔜 V3 | 27 |
| Structured capability proposal (gap + effort + risk) | 🔜 V3 | 27 |
| Sandbox self-integration | 🔜 V3 | 27 |
| Improvement backlog management | 🔜 V3 | 27 |
| Prompt evolution (systematic prompt optimization) | 🔜 V3 | 23 |
| Model-routing evolution (route tasks to cheaper model) | 🔜 V3 | 25 |

---

## Pillar 19 — Workflow Mining & Automation Discovery
*Find what to automate next.*

| Capability | V | Week |
|---|---|---|
| Repeated task detection | 🔜 V2 | 22 |
| Manual effort identification | 🔜 V2 | 22 |
| Automation candidate ranking | 🔜 V2 | 22 |
| Capability backlog generation | 🔜 V2 | 22 |
| Bottleneck visualization | 🔜 V3 | 26 |

---

## Pillar 20 — Decision Intelligence
*ARIA recommends the best next action, explains tradeoffs.*

| Capability | V | Week |
|---|---|---|
| Next-best-action recommendation | 🔜 V2 | 24 |
| Option ranking with tradeoff explanation | 🔜 V2 | 24 |
| Escalation decision engine | 🔜 V2 | 24 |
| LATS (Language Agent Tree Search) for multi-step decisions | 🔜 V3 | 24 |
| Risk/benefit articulation | 🔜 V2 | 24 |

---

## Pillar 21 — Confidence, Cost & Risk Optimizer
*ARIA uses the right model for the right task at the right cost.*

| Capability | V | Week |
|---|---|---|
| Confidence scoring per output | 🔜 V2 | 16 |
| Model routing by task complexity | 🔜 V3 | 25 |
| Cost tracking per task + per agent | 🔜 V2 | 16 |
| Cost optimization recommendations | 🔜 V3 | 25 |
| Release risk predictor (ML from Work Ledger) | 🔜 V3 | 25 |
| Approval predictor (from historical patterns) | 🔜 V3 | 25 |

---

## Pillar 22 — AI Capability Marketplace
*Any team can browse, adopt, and rate ARIA's capabilities.*

| Capability | V | Week |
|---|---|---|
| Skill catalog (all skills with metadata + eval scores) | 🔜 V3 | 28 |
| Agent catalog (all agents with health + usage) | 🔜 V3 | 28 |
| Team adoption tracking | 🔜 V3 | 28 |
| Version history per capability | 🔜 V3 | 28 |
| Quality score visibility (rubric scores) | 🔜 V3 | 28 |
| Marketplace UI | 🔜 V3 | 28 |

---

## Pillar 23 — AI Employee as a Service
*ARIA as a multi-tenant platform for other organizations.*

| Capability | V | Week |
|---|---|---|
| Multi-tenant architecture | 🔜 V3 | 29 |
| Governance console per tenant | 🔜 V3 | 29 |
| Usage tracking per tenant | 🔜 V3 | 29 |
| Capability isolation per tenant | 🔜 V3 | 29 |
| Onboarding workflow | 🔜 V3 | 29 |
| Billing/cost allocation | 🔜 V3 | 29 |

---

## Pillar 24 — Model Intelligence & Post-Training
*Route tasks to the right model. Serve, fine-tune, monitor, rollback.*

| Capability | V | Week |
|---|---|---|
| Model router — routes on risk, complexity, cost, latency, privacy | 🔜 V2 | 16 |
| SLM utility layer — Phi-3-mini / Qwen-0.5B for classification, routing, extraction | 🔜 V2 | 25 |
| vLLM serving — self-hosted OpenAI-compatible inference | 🔜 V2 | 25 |
| LoRA / QLoRA fine-tuning on Work Ledger outputs | 🔜 V3 | 29 |
| DPO preference alignment from approve/reject pairs | 🔜 V3 | 29 |
| Model lifecycle registry (version, dataset, eval score, endpoint) | 🔜 V2 | 29 |
| Model eval harness — base vs fine-tuned rubric comparison | 🔜 V2 | 29 |
| Model monitoring — quality drift, latency, cost per inference | 🔜 V2 | 29 |
| ML Research & Post-Training Agent | 🔜 V3 | 29 |
| Model rollback | 🔜 V2 | 29 |

---

## Summary by Phase

| Phase | Weeks | Pillars Active |
|---|---|---|
| Phase 1 — Foundations | 1-4 | 1, 10 (partial), 11, 16 (basic) |
| Phase 2 — AI Engineer Core | 5-9 | 2, 7, 8, 9, 10, 17 |
| Phase 3 — Intelligence + Analytics | 10-13 | 3, 4, 5, 12 |
| Phase 4 — Agent Factory | 14-18 | 6, 13, 14, 15, 18 (monitoring) |
| Phase 5 — Knowledge + Workflow | 19-22 | 8 (advanced), 13, 19 |
| Phase 6 — Intelligence Depth | 23-25 | 20, 21 |
| Phase 7 — Self-Evolution | 26-28 | 18 (full), 22 |
| Phase 8 — Work Ledger + AaS | 29 | 16 (full), 23 |
| Phase 9 — Launch | 30 | All 23 demonstrable |
