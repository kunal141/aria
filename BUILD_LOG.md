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

---

## Week 24 — Decision Intelligence (LATS) — `396b181` (2026-06-06)

### Scope complete
- `aria/decision/` package: `models.py`, `scorer.py`, `lats.py`, `engine.py`
- `DecisionOption`, `DecisionMatrix`, `DecisionResult` — typed contracts
- `score_option()`, `rank_options()`, `predict_approval()`, `release_risk_score()`
- `LATSNode` + `LATSTree` + `run_lats()` — UCT-based Language Agent Tree Search
- `next_best_action()` — greedy / lats / mock entry point
- 53 new tests. 274 total passing.

---

## Codex review fixes + Week 25 — Agent Control Plane + SLM Classifier

### P1 fixes (critical correctness)
| Finding | Fix |
|---|---|
| Jira T4 approval never resumes execution | `teams_bot.py`: skip T2 for jira; `_execute_jira_after_approval()` called on T4 approve action |
| Runtime timeout blocks until fn completion | `harness.py`: `executor.shutdown(wait=False)` instead of context manager |
| Token budget disconnected from graph | `intake.py`: `budget_tracker.init_task()`; `respond.py`: `budget_tracker.consume()` + sets `token_budget_used` |
| Decision selection inconsistent after enrichment | `engine.py`: enrich all options with `predict_approval()` BEFORE selection |

### P2 fixes (integration gaps)
| Finding | Fix |
|---|---|
| Analytics crew unreachable | Added "analytics_qa" task type to `state.py`, keyword rules in `router.py`, conditional edge in `graph.py` |
| Decision Intelligence not integrated | `general_node` now imports and runs `next_best_action()` (Pillar 20 live in production graph) |
| SLM accepts arbitrary task types | `classifier.py`: validate SLM output against `_ALLOWED_TASK_TYPES`, fall back to keyword if invalid |
| Control plane double-counts versioned agents | `registry.list_agents()` now filters out `@`-keyed versioned aliases |

### P3 fix
- `CLAUDE.md` + `BUILD_LOG.md` status updated to reflect Week 24 + Week 25 state

### Week 25 scope complete
- `aria/control_plane/`: `models.py`, `monitor.py`, `control_plane.py` — `AgentMonitor` + `ControlPlane.report()`
- `aria/slm/`: `classifier.py` — `SLMClassifier` with keyword backend, vLLM-ready interface

### Verified clean
- `uv run pytest -q`: **338 passed**

---

## Codex review round 2 fixes — `(2026-06-07)`

### P1 fixes (critical correctness)
| Finding | Fix |
|---|---|
| Jira reports creation when governed execution fails | `teams_bot.py`: `_execute_jira_after_approval()` returns `Optional[dict]` (None on failure, not fabricated ticket); `_handle_card_action` tracks `jira_attempted` flag separately, sends honest failure message when None |
| Budget consumption is after-the-fact and boolean result ignored | `skill_nodes.py`: `_guard_budget()` helper calls `consume()` pre-execution at start of every skill node; `respond.py` reads `budget_tracker.used()` instead of retroactive consume |
| Timed-out tools continue executing side-effects | `harness.py`: `CancellationToken` class with threading.Event; set in `_thread_local` inside worker; `token.cancel()` fires on timeout before `shutdown(wait=False)`; T3/T4 tools without `idem_key` get audit warning |

### P3 fix
- `CLAUDE.md` status table updated — stale "Week 13 ⏳ NEXT" row replaced with accurate Week 3–25 summary

### Verified clean
- `uv run pytest -q`: **350 passed**
- Python compilation: passed
- Git working tree: clean

---

## Agent Factory Codex fixes — `(2026-06-07)`

### P1 fix (unsafe code generation)
| Finding | Fix |
|---|---|
| Names like `123-agent` and `bad agent` produce SyntaxError in scaffolded code | `agent_spec.py`: `@field_validator("name")` rejects any name where `name.replace("-","_")` is not a valid Python identifier |
| Triple-quote in role/goal/backstory breaks generated docstring | `scaffold.py`: `_safe_embed()` helper replaces `"""` with `\"\"\"` before embedding any string field into the scaffold |

### P2 fixes (registry correctness)
| Finding | Fix |
|---|---|
| `update_status("agent", "broken")` silently stores invalid status | `registry.py`: `update_status()` now uses `AgentSpec.model_validate(...)` instead of `model_copy(update=...)` — Pydantic enforces the AgentStatus Literal |
| Replacing a draft or sandbox agent loses its history record | `registry.py`: `register()` now archives any existing version (not only active) under `name@version` key; only active agents are also deprecated |

### Verified clean
- `uv run pytest -q`: **363 passed**

---

## Agent Factory scaffold hardening (round 2) — `(2026-06-07)`

### P1 fix (remaining unsafe interpolation)
| Finding | Fix |
|---|---|
| `version='v1"oops'` produces unterminated string literal in return dict | `scaffold.py`: string literal values in `return` dict now use `repr()` at generation time — quotes, backslashes, and all special chars are always safe |
| Capability `skill_name` with `\n` breaks comment indentation | `scaffold.py`: `_safe_comment()` helper strips newlines; applied to `primary_skill` and `_to_class(primary_skill)` in all comment lines |
| `owner='domain\user'` in docstring: `\u` processed as Unicode escape | `_safe_embed()` now doubles backslashes (step 1, must run before `"""` escaping) — `\user` → `\\user` in generated source |
| Newline in skill_name breaks `textwrap.dedent` (zero-indent line collapses common prefix) | `_safe_embed()` now also collapses `\n` and `\r` to spaces (step 3) |

### Verified clean
- `uv run pytest -q`: **367 passed**
