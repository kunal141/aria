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

---

## Agent Factory Lifecycle + E2E Scenarios + Voice MVP — `(2026-06-07)`

### Scope complete
- `aria/factory/lifecycle.py`: 5-stage factory lifecycle — validate → security scan → T4 approval → activate → rollback; `LifecycleResult`, `ValidationResult`, `SecurityCheckResult`, `ActivationResult` models
- `tests/test_factory_lifecycle.py`: 44 deterministic lifecycle tests covering every stage, failure paths, rollback, and the full round-trip
- `tests/test_e2e_scenarios.py`: 24 deterministic E2E scenario tests across 6 scenarios: KPI investigation, flaky-test analysis, Jira T4 creation path, privacy gate, idem key deduplication, malicious metadata injection blocked
- `aria/voice/router.py` + `voice_api.py`: FastAPI voice API — POST /voice/run; governance gate enforced (T1/T2 execute; T3/T4 refused with explanation); `aria/voice/__init__.py`
- `apps/frontend/src/ARIAVoice.jsx`: Browser voice MVP — Web Speech API (no SDK); hold-to-speak mic; SpeechSynthesis response; history with approval cards; governance notice banner
- `App.jsx`: Voice view wired into view switcher alongside Dashboard and Master Plan
- `pyproject.toml`: `fastapi>=0.111.0`, `uvicorn>=0.29.0` added to dependencies

### Verified clean
- `uv run pytest -q`: **435 passed**
- Frontend production build (`npm run build`): **passed**
- Git working tree: **clean**

---

## Platform Intelligence V1 — `(2026-06-07)`

### Scope complete
- `aria/platform/models.py`: Full domain type library — `ServiceEntry`, `KnowledgeSource`, `Evidence`, `ConflictRecord`, `AuthorizationDecision`, `ClaimSpec`, `ClaimEvidence`, `EvidencedAnswer`; `caller_can_access()`, `SOURCE_AUTHORITY`, `STALENESS_HOURS`
- `aria/platform/catalog.py`: `ServiceCatalog` + `CatalogStore` Protocol + `InMemoryCatalogStore`; BFS impact analysis over reverse-dependency graph
- `aria/platform/sources.py`: `SourceRepository` + `SourceStore` Protocol + `InMemorySourceStore`; Phase-1 authorization at retrieval — restricted sources never returned to under-cleared callers
- `aria/platform/evaluator.py`: `check_staleness()`, `check_authorization()` (Phase-2), `detect_conflicts()`, `_resolve_conflict()` (authority → recency → unresolved), `build_evidence()`
- `aria/platform/evidence.py`: `EvidenceAssembler.assemble()` — two-phase auth, per-claim mapping, fail-closed on missing evidence, no LLM decides claim support
- `aria/platform/fixtures.py`: `build_service_fixtures()` + `build_source_fixtures()` + `load_fixtures_into()` — factory functions (not singletons); 5 canonical services + recognizable restricted-content test fixtures (`SECRET_API_KEY=abc123`)
- `aria/platform/__init__.py`: Public API exports
- `aria/state.py`: Added `platform_evidence: Optional[str]` field
- `aria/nodes/skill_nodes.py`: `kpi_node` now calls `_assemble_kpi_evidence()` post-skill; `platform_evidence` JSON added to return dict
- `tests/test_platform_intelligence.py`: 44 deterministic tests — sensitivity ordering, staleness thresholds, conflict detection/resolution, Phase-1/Phase-2 auth, **critical leak tests proving `SECRET_API_KEY` never appears in EvidencedAnswer JSON**, dependency impact BFS, fail-closed missing evidence, unresolved-conflict exclusion, kpi_node integration, fixture isolation

### Key invariants enforced and tested
- Restricted content (`SECRET_API_KEY=abc123`) verified absent from all EvidencedAnswer fields: answer, excerpts, authorization decision reasons, blocked_reason, freshness_warnings
- `AuthorizationDecision.reason` contains only source_id + sensitivity strings when `allowed=False` — no title, no content
- `EvidencedAnswer.answer == ""` whenever any claim is unsupported
- Unresolved conflicts (same authority + timestamp) exclude BOTH sources
- LLM output verified against deterministic evidence assembly — LLM never decides claim support

### Verified clean
- `uv run pytest -q`: **479 passed**
- Git working tree: clean

---

## Evidence Gate + CI/CD Integration + Cross-Channel Citations — `(2026-06-07)`

### Problem addressed
`kpi_node` set `platform_evidence` but `respond.py` published skill output unconditionally.
`teams_bot._build_card()` and `voice/router.py` also read `skill_output` directly,
bypassing any gate. `ci_cd_node` had no evidence assembly at all.

### Changes
- `aria/nodes/respond.py`: `_EVIDENCE_REQUIRED_TYPES = {"kpi","ci_cd"}`. `_build_response()` checks `platform_evidence` before rendering: absent → `[EVIDENCE UNAVAILABLE … WITHHELD]`; `is_safe_to_surface=False` → `[RESPONSE WITHHELD — UNSUPPORTED CLAIMS]`; safe → `render_artifact_with_citations()`. Non-evidence types (pr_review, jira, qa) pass through unchanged.
- `aria/artifact_engine.py`: `render_artifact_with_citations()` + `_render_citation_footer()` — appends claim-level provenance block (source_id + authority + staleness flag) after any evidence-backed artifact. Footer never includes source.content or source.title.
- `aria/nodes/skill_nodes.py`: `_assemble_cicd_evidence()` added; `ci_cd_node` now populates `platform_evidence` with pipeline-state + dependency-impact claims (BFS impact analysis baked in). Matches kpi_node's evidence pattern.
- `aria/integrations/teams_bot.py`: `_build_card()` now accepts `platform_evidence_json`; returns None (fallback to gated text) for kpi/ci_cd when evidence absent or unsafe. `_build_kpi_card()` gains evidence provenance FactSet. New `_build_cicd_card()` with dependency-impact block. `_build_evidence_facts()` helper shows only source_id/authority — never source content. `_handle_text_message()` extracts and threads `platform_evidence` from graph result.
- `aria/voice/router.py`: `_make_state()` includes `platform_evidence: None`. `_evidence_gate_spoken()` + `_parse_platform_evidence()` added. `voice_run()` checks gate before calling `_extract_spoken()` for kpi/ci_cd.
- `tests/test_evidence_gate.py`: 50 deterministic tests across all 4 surfaces — respond, artifact engine, voice, Teams — proving absent/unsafe/safe evidence behaviour and that `_VOICE_EVIDENCE_REQUIRED == _EVIDENCE_REQUIRED_TYPES == _EVIDENCE_REQUIRED_CARD_TYPES` (no surface divergence).

### Invariants now enforced across all surfaces
- KPI and CI/CD responses are withheld at respond, Teams card, and voice when evidence absent
- Citation footer shows source identifiers only — no source content in any rendered output
- `ci_cd_node` BFS impact analysis: analytics-pipeline failure → recommendation + feed-ranking + notification in dependency-impact claim
- `_VOICE_EVIDENCE_REQUIRED`, `_EVIDENCE_REQUIRED_TYPES`, `_EVIDENCE_REQUIRED_CARD_TYPES` must match — enforced by tests

### Verified clean
- `uv run pytest -q`: **529 passed**
- Git working tree: clean

---

## Week 27 — Evolution Intelligence + RAPTOR — `(2026-06-07)`

### Scope complete
- `aria/evolution/models.py`: Full typed contract library — `EvolutionType` (9 types), `RISK_CEILING` per type, `ProposalStatus` (10 states: draft→integrated/rolled_back), `DebateArgument`, `DebateVerdict`, `SandboxResult`, `IntegrationResult`, `EvolutionProposal` (full lifecycle model with `exceeds_risk_ceiling()` + `is_ready_for_integration()`)
- `aria/evolution/store.py`: `ProposalStore` Protocol + `InMemoryProposalStore` — save/get/list/delete with status filtering
- `aria/evolution/monitor.py`: `EvolutionMonitor` — scans work ledger JSONL; detects high_error_rate, low_support_rate, repeated_pattern signals; emits ranked draft `EvolutionProposal` candidates with deterministic stable IDs; all proposals remain DRAFT (no auto-submission)
- `aria/evolution/debate.py`: `DebateEngine` — AutoGen-inspired three-agent debate (ResearchAgent + ScepticAgent + ModeratorAgent); LLM-backed path (langchain-anthropic) + deterministic heuristic fallback (no API key needed); auto-rejects proposals exceeding RISK_CEILING; full transcript recorded in `DebateVerdict`
- `aria/evolution/sandbox.py`: `run_sandbox()` — 4 deterministic checks: compile_check (ast.parse), schema_check (prose fields non-empty), risk_ceiling_check, golden_test (evidence quality heuristic); `passed=False` blocks integration with no bypass
- `aria/evolution/raptor.py`: `RaptorBuilder` + `RaptorTree` + `RaptorChunk` — 3-level RAPTOR hierarchy (Level 0 raw leaves → Level 1 group summaries → Level 2 root summary); extractive summarisation in V1 (deterministic); `query_tree()` keyword overlap retrieval across all levels; parent/child links maintained for path-to-root traversal
- `aria/evolution/integration.py`: `IntegrationEngine` — governed integration through T4 gate; requires `is_ready_for_integration()` (all 3 gates: debate approved + sandbox passed + human T4 approval); archive-before-integrate; rollback sets `rolled_back` status; dry_run mode for testing
- `aria/evolution/__init__.py`: Public API exports for all evolution components
- `tests/test_evolution.py`: 62 deterministic tests — models (risk ceiling, lifecycle validators), store CRUD, monitor (signal detection, proposal generation, stable IDs), debate (heuristic approve/defer/reject, auto-reject ceiling, transcript completeness), sandbox (all 4 checks, compile pass/fail, golden test), RAPTOR (tree structure, parent/child consistency, query retrieval, level correctness), integration (dry-run, status transitions, filesystem writes, rollback), full lifecycle round-trip

### Key invariants enforced and tested
- `is_ready_for_integration()` requires ALL three gates: debate `recommendation == "approve"` + `sandbox_result.passed == True` + `approved_by is not None` + `status == ProposalStatus.approved`
- Risk ceiling auto-reject: proposals exceeding type ceiling rejected before debate starts (confidence=1.0)
- Monitor proposals always DRAFT — no autonomous submission
- Sandbox `passed=False` → integration blocked regardless of approval state
- RAPTOR parent/child consistency enforced in test suite
- Heuristic debate produces deterministic results without LLM (test-safe)

### Verified clean
- `uv run pytest -q`: **591 passed**, 2 warnings
- Python compilation: passed
- Git working tree: clean

---

## Week 28 — Governed Self-Improvement + Update Manager — `ddcb192` (2026-06-09) — ACCEPTED

### Scope complete
- `aria/evolution/update_manager/`: governed update lifecycle — propose → canary → promote → rollback; `UpdateRelease` typed contracts; `InMemoryUpdateStore` (atomic `save_batch`, schema-validated, file-backed flush); constitutional checks
- Component identity: `component_loader.py` + `component_registry.py` — runtime authority is the immutable, versioned artifact; monitor detects capability gaps and queues proposals (pr_review_prompt component)
- Real artifact write + verify, with backup/restore on failure; path confinement under `apps/backend/deployments/` (gitignored runtime tree)
- Pipeline wiring (`evolution/pipeline.py`, `nodes/evolution_node.py`) + Work Ledger correlation

### Codex review
- Multiple stabilization rounds (3 → 12); **every finding closed**. Final round-3 commit closed all 7 findings with real artifact write/restore.
- **Status: ACCEPTED by Codex.** Stale per-round "Awaiting Codex Re-Audit" / "Week 29 blocked" notes in `apps/backend/BUILD_LOG.md` are historical context only.

### Verified clean (at Week 28 acceptance)
- backend suite: **687 passed**
- Python compilation: passed
- Git working tree: clean

---

## Week 29 — AI Work Ledger v2 → Fine-Tuning Prototype — `9590750` (2026-06-14) — COMPLETE

### Scope complete — all five priorities ACCEPTED by Codex
1. **AI Work Ledger v2** — schema-versioned, queryable JSONL ledger (`correlation_id`, `actor`, `risk_tier`, per-event cost/latency, `outcome_label`)
2. **ROI Dashboard** — frontend view over Work Ledger v2, harness-engineering copy
3. **Dataset Export Prototype** — SFT (input/output) + DPO (prompt/chosen/rejected) JSONL from approved/corrected ledger events; ledger-backed + content-bound provenance, DPO `chosen == correction` enforced
4. **Model Lifecycle Registry v1** — file-backed JSONL registry (base version, dataset hash, holdout eval, rollback pointer, active skills)
5. **Fine-Tuning Prototype** — offline deterministic dry-run LoRA planner/runner (dependency-injected real-trainer seam); proves the pipeline only

### Final accepted state
- Week 28 Stabilization **accepted**
- Week 29 all five priorities **accepted**
- backend: **1021 passed, 1 skipped**
- **no real training** (offline deterministic dry-run; no GPU, no model download)
- **no deployment** (active model stays NONE; production graph / model router unchanged)
- **no vLLM** serving
- **Week 30 — Launch Readiness ACCEPTED by Codex** (2026-06-15; see entry below)

### Notes
- `CLAUDE.md` Section 28.4 (Agentic AI Roadmap — eight V2/V3 capabilities) added as documentation-only future roadmap; not implemented.
- Runtime `deployments/prompts/*.txt` artifacts removed from version control and gitignored; conftest autouse fixtures isolate ledger + deployment writes to tmp.

### Verified clean
- `git diff --check`: clean (only benign LF→CRLF warnings)
- Git working tree: clean at commit `9590750`

---

## Week 30 — Launch Readiness — COMPLETE (Accepted by Codex)

**Date**: 2026-06-14 (work) · **Accepted**: 2026-06-15

**Status**: ✅ **COMPLETE — Week 30 Launch Readiness ACCEPTED by Codex (2026-06-15).** Previous full baseline: 1027 backend tests passing (1 skipped); focused demo suite 6 passed; golden demo reliability verified.

**Scope (no new core capability, pillar, vLLM, real fine-tuning, or deployment):**
- Offline, deterministic golden-path demo `aria.demo.golden_path` (no paid API, no network).
- Launch-readiness package: ~17 deliverable docs under `docs/week30_*` (Truth & Claim Audit,
  Golden Demo, Demo Reliability, launch assets, Public-Safety Audit, positioning, career
  artifacts, architecture summary, final proof checklist, V1/V2/V3 boundary).

**Codex round-1 verdict: Partially Accepted — findings addressed:**
- [P1] Golden demo mutated real runtime logs (`notifications.jsonl`, `tool_audit.jsonl`) — now
  redirected into the temp dir alongside the ledger files; repointed module globals restored on
  exit; a live run leaves the repo byte-for-byte unchanged.
- [P1] Seeded Stage-2 events were presented as live lifecycle proof — corrected in 4 docs to
  state the live graph emits the **terminal** event per task today and Stage 2 is **seeded**
  demonstration data using the real typed v2 event classes.
- [P2] No demo tests — added `tests/test_week30_golden_demo.py` (no-pollution regression +
  routing/evidence/deterministic-metrics/offline/cleanup/global-restore coverage).
- [P2] Stale status docs — at round-1, CLAUDE.md, both BUILD_LOGs, and the final proof checklist
  were moved to the then-current "in progress" wording (since superseded by the round-3 Accepted
  closeout below).

**Codex round-2 verdict: Partially Accepted — three doc/test-hygiene findings closed:**
- [P2] Demo tests leaked temp dirs (`--keep` retained `aria_golden_*` dirs) — removed `--keep`
  from the three affected tests so each self-cleans; deleted the 21 retained dirs; verified 0
  remain after a fresh focused-test run.
- [P2] Two summaries retained the "every action recorded" ledger overclaim — softened in
  `week30_architecture_summary.md` + `week30_executive_summary.md` (live graph emits the
  terminal event per task; full taxonomy is seeded/tested); demo script "rollback you just saw"
  reworded to seeded + pointed to `aria.model_registry.demo` for executed rollback proof.
- [P2] Stale canonical status — `CLAUDE.md` §29 refreshed.

**Codex round-3 verdict: ACCEPTED (2026-06-15).** No remaining Week 30 launch-readiness
findings; focused demo suite 6 passed; `%TEMP%\aria_golden_*` 0 before / 0 after; runtime-file
isolation fixed; seeded-lifecycle wording explicit; executed-rollback proof points to
`aria.model_registry.demo`; canonical status current; `git diff --check` passed; previous full
baseline 1027 passed / 1 skipped. **Week 30 Launch Readiness is ACCEPTED.**

**Closeout boundaries (unchanged):** no vLLM serving, no real fine-tuning, no production
deployment, no production graph / model-router change. **Public GitHub / LinkedIn publication
remains BLOCKED** pending employer/IP approval — the public-safe artifacts are **drafts only**.
