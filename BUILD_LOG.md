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

## Week 20 — Jira / Delivery Management _(in progress)_

Started: 2026-06-06
