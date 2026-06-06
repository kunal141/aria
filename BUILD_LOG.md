# ARIA Build Log

Tracks major milestones, stabilization rounds, and baseline tags.
Each entry records what was verified clean and what the git ref is.

---

## week-19-stable — `142a1e4` (2026-06-06)

**Baseline tag**: `week-19-stable`

### Scope complete
- Weeks 3–12: LangGraph backbone, 5 real skills (KPI, PR review, QA, test review, CI/CD),
  RAG (HyDE / Self-RAG / Adaptive), code intelligence (AST + dep graph), memory fabric (6 types)
- Week 13: LangSmith deep tracing, Teams bot identity
- Weeks 14–16: Evaluation harness (rubrics, LLM-as-judge, baselines), governance layer
  (action tiers, approval gate), model router (fast / smart / frontier / privacy gate)
- Weeks 17–18: QA skill (test-case generation), test-review skill (flakiness diagnosis)
- Week 19: CI/CD skill (pipeline failure analysis), proactive notifier with cooldown store

### Codex review findings closed (4 rounds)
| Round | Finding | Fix commit |
|---|---|---|
| 1 | Teams bot ImportError on `aria_graph` | 5ca8019 |
| 1 | Skills bypassed `get_routed_llm()` | 5ca8019 |
| 1 | Keyword router misclassified short tokens | 5ca8019 |
| 2 | Routing context not passed into skill inputs | 613f946 |
| 2 | "flakiness" not matched by test_review rules | 613f946 |
| 3 | Privacy gate inside broad `except` (silent external fallback) | 613f946 |
| 3 | Teams card buttons called `approve(task_id)` not `approve(request_id)` | 613f946 |
| 4 | Privacy still leaks when no local provider configured | 01c4702 |
| 4 | Cards sent with no approval request registered | 01c4702 |
| 4 | `uv.lock` had uncommitted dev-dep lines | 01c4702 |
| 5 | Approval requests created for no-card task types | 29b0324 |
| 5 | `pytest` exited with code 1, zero tests collected | 29b0324 |
| 5 | Root `testpaths` scanned production modules | 142a1e4 |

### Verified clean at tag
- `uv run pytest -q` from repo root: **41 passed, 0 warnings**
- `python -m py_compile` on all `aria/` modules: **passed**
- Frontend production build (`npm run build`): **passed**
- Git working tree: **clean**

---

## week-21 — `9b37ad3` (2026-06-06)

### Scope complete
- Week 20: Jira skill — JiraInput/JiraOutput/JiraTicketDraft, draft-only T3 path,
  Adaptive Card, 29 tests
- Week 21: Agent Runtime Harness — `execute()` with 5 safety properties,
  `BudgetTracker`, `guard_loop()`, T4 Jira create path via harness, 60 new tests

### Verified clean
- `uv run pytest -q`: **130 passed**
- Python compilation: passed
- Git working tree: clean

---

## Week 22 — Agent Factory + CrewAI — `7958dcd` (2026-06-06)

### Scope complete
- Agent Factory: `AgentSpec`, `AgentRegistry` (versioned deprecation), `scaffold_agent()` → valid Python
- CrewAI Analytics+QA crew: `AnalyticsQACrew` with mock fallback, dry-run, `analytics_qa_crew_node`
- Builtin "aria-core" agent seeded at import
- 46 new tests (agent_factory + analytics_qa_crew)

### Verified clean
- `uv run pytest -q`: **175 passed**

---

## Week 23 — DSPy + Instructor — `06e9fb8` (2026-06-06)

### Scope complete
- `aria/optimization/` package: `signatures.py`, `metrics.py`, `optimizer.py`
- `RouterSignature`, `PRReviewSignature`, `KPISignature` — DSPy Signature subclasses
- `TaskTypeOutput` — Instructor-validated Pydantic model for router output
- `routing_accuracy`, `pr_review_quality`, `kpi_quality` — deterministic DSPy metrics
- `optimize_skill()` + `SkillOptimizationResult` — BootstrapFewShot wrapper, graceful no-LM fallback
- 46 new tests (all deterministic, no LLM required)

### Verified clean
- `uv run pytest -q`: **221 passed**
