# ARIA — Build Log
# Every file, every concept, every step — in order.
# Use this to rebuild ARIA from scratch at any point to reinforce learning.

---

## How to Use This Log

Each step has:
- **What**: the file created
- **Why**: the concept it teaches
- **Key insight**: the non-obvious thing to understand
- **Depends on**: files that must exist before this one

Rebuild discipline: close this file, open a blank folder, rebuild each step from memory.
Check your output matches. If it doesn't — you found a gap. That gap is worth more than getting it right.

---

## WEEK 3 — LangGraph Foundation (Graph Skeleton)

### DAY 1 — Build the graph skeleton (no AI, just structure)

**Goal**: Get a LangGraph graph running end-to-end with a dummy router.
Understand state, nodes, edges before touching any LLM.

---

#### Step 1 — `aria/state.py`
**What**: ARIAState TypedDict — the shared data contract for the entire graph.

**Why**: Every node in the graph reads from and writes to this dict.
Without a typed contract, nodes pass arbitrary dicts and bugs are invisible until runtime.

**Key insight**: TypedDict + Literal catches invalid values at write time, not at 2am when production breaks.
`task_status: Literal["pending", "routing", "done", "failed"]` means
`state["task_status"] = "completed"` is flagged by the IDE immediately.

**Key fields**:
- `task_id` — unique ID per task (assigned by intake node)
- `task_type` — which ARIA skill handles this task
- `routing_reason` — WHY ARIA chose this skill (seed of the Work Ledger)
- `steps_completed` — audit trail: which nodes ran, in order
- `response` — final text returned to the user

**Depends on**: nothing — this is the foundation everything else imports.

```python
from typing import TypedDict, Optional, Literal, List

class ARIAState(TypedDict):
    task_id: str
    raw_input: str
    task_type: Optional[Literal["pr_review", "kpi", "ci_cd", "jira", "general", "unknown"]]
    task_status: Literal["pending", "routing", "executing", "done", "failed"]
    routing_reason: Optional[str]
    steps_completed: List[str]
    skill_name: Optional[str]
    skill_output: Optional[str]
    response: Optional[str]
    messages: List[dict]
    error: Optional[str]
```

---

#### Step 2 — `aria/nodes/intake.py`
**What**: First node in the graph. Assigns task_id, opens the audit trail.

**Why**: Every task that enters ARIA needs a unique identity and a clean audit trail.
This is also where the Work Ledger will log task creation (Week 4).

**Key insight**: Nodes return PARTIAL dicts, not the full state.
LangGraph merges the returned dict back into the full ARIAState.
You only write the fields this node is responsible for.

**Key insight 2**: `uuid.uuid4()` generates a globally unique ID.
This becomes the primary key for every task in the Work Ledger.

**Depends on**: `aria/state.py`

```python
import uuid
from aria.state import ARIAState

def intake(state: ARIAState) -> dict:
    return {
        "task_id": str(uuid.uuid4()),
        "task_status": "routing",
        "steps_completed": ["intake"],
    }
```

---

#### Step 3 — `aria/nodes/router.py` (Day 1 version — keyword matching)
**What**: Second node. Classifies the task type using keyword rules.

**Why**: ARIA needs to know WHICH skill to invoke. This is the brain of the graph.
Day 1 uses keywords. Day 2 replaces keywords with Claude. Same state contract — different logic inside.

**Key insight**: The state contract (what fields are written) NEVER changes between Day 1 and Day 2.
`task_type` and `routing_reason` are always written. Only the mechanism that produces them changes.
This is the power of typed state — you can swap implementations without breaking callers.

**Key insight 2**: `steps_completed` is always APPENDED, never overwritten.
`state["steps_completed"] + ["router"]` builds the audit trail incrementally.

**Depends on**: `aria/state.py`

```python
from aria.state import ARIAState

_RULES = [
    (["pr", "pull request", "code review", "diff", "merge"], "pr_review", "Input mentions a PR"),
    (["kpi", "metric", "ctr", "drop", "spike", "feed", "recommendation"], "kpi", "Input refers to a KPI"),
    (["ci", "cd", "pipeline", "build", "deploy", "release"], "ci_cd", "Input mentions CI/CD"),
    (["jira", "ticket", "story", "sprint", "backlog", "blocker"], "jira", "Input refers to Jira"),
]

def router(state: ARIAState) -> dict:
    raw = state["raw_input"].lower()
    task_type, routing_reason = "general", "No keywords matched — routing to general"
    for keywords, skill, reason in _RULES:
        if any(kw in raw for kw in keywords):
            task_type, routing_reason = skill, reason
            break
    return {
        "task_type": task_type,
        "routing_reason": routing_reason,
        "steps_completed": state["steps_completed"] + ["router"],
    }
```

---

#### Step 4 — `aria/nodes/respond.py`
**What**: Third node. Formats a placeholder response.

**Why**: Every graph needs an output node. This is a placeholder —
from Week 6, each task_type routes to a real skill node that does actual work.

**Key insight**: Week 3's respond node is intentionally dumb.
Its only job is to show that the graph runs end-to-end.
The real value is in the routing — not the response.

**Depends on**: `aria/state.py`

```python
from aria.state import ARIAState

_LABELS = {
    "pr_review": "PR Review", "kpi": "KPI Investigation",
    "ci_cd": "CI/CD Intelligence", "jira": "Jira / Delivery Management",
    "general": "General", "unknown": "Unknown",
}

def respond(state: ARIAState) -> dict:
    label = _LABELS.get(state.get("task_type", "unknown"), "Unknown")
    return {
        "response": f"Routed to: {label}\nReason: {state.get('routing_reason','')}\n[Skill wires in at Week 6]",
        "task_status": "done",
        "steps_completed": state["steps_completed"] + ["respond"],
    }
```

---

#### Step 5 — `aria/graph.py`
**What**: Wires all nodes into a StateGraph and compiles it.

**Why**: LangGraph requires explicit registration of nodes and edges.
`compile()` validates the structure — orphaned nodes, missing edges — before any code runs.

**Key insight**: `set_entry_point("intake")` tells LangGraph where execution begins.
`add_edge("respond", END)` tells it where to stop.
Without END, the graph runs forever.

**Key insight 2**: Week 3 uses fixed edges (A → B always).
Week 4 adds `add_conditional_edges` — router checks state and branches to
`pr_review_skill` OR `kpi_skill` OR `ci_cd_skill` based on `task_type`.

**Depends on**: `aria/state.py`, all 3 node files

```python
from langgraph.graph import StateGraph, END
from aria.state import ARIAState
from aria.nodes.intake import intake
from aria.nodes.router import router
from aria.nodes.respond import respond

def build_graph():
    graph = StateGraph(ARIAState)
    graph.add_node("intake", intake)
    graph.add_node("router", router)
    graph.add_node("respond", respond)
    graph.set_entry_point("intake")
    graph.add_edge("intake", "router")
    graph.add_edge("router", "respond")
    graph.add_edge("respond", END)
    return graph.compile()

aria_graph = build_graph()
```

---

#### Step 6 — `main.py`
**What**: Entry point. Invokes the graph with 5 test inputs.

**Why**: Every run of `python main.py` is a sanity check.
If TRAIL always shows `['intake', 'router', 'respond']`, the graph ran correctly.

**Key insight**: `aria_graph.invoke(initial_state)` runs the entire graph synchronously.
LangGraph calls each node in order, merging partial state updates after each node.
The returned dict is the FINAL state after all nodes complete.

**Depends on**: `aria/graph.py`

**Run**: `uv run python main.py`

**Expected output** (Day 1):
```
INPUT  : Review my PR for the recommendation engine changes
TYPE   : pr_review
TRAIL  : ['intake', 'router', 'respond']
STATUS : done
```

---

### DAY 2 — Replace keyword router with Claude LCEL chain

**Goal**: Understand LangChain LCEL (the pipe operator).
Build the Claude chain in isolation first. Then plug it into the graph.

---

#### Step 7 — `aria/config.py`
**What**: Loads `.env` and sets LangSmith environment variables.

**Why**: API keys must never be hardcoded. `python-dotenv` reads from `.env` file.
LangSmith env vars must be set BEFORE any LangGraph/LangChain imports execute.

**Key insight**: `import aria.config` at the top of any file that uses LangChain
ensures tracing is active. If you import LangChain before setting the env vars,
traces won't appear in LangSmith.

**Depends on**: `.env` file with `ANTHROPIC_API_KEY` and `LANGCHAIN_API_KEY`

```python
import os
from dotenv import load_dotenv

load_dotenv()
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "ARIA"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
```

---

#### Step 8 — `day2_lcel_test.py` (standalone — not part of graph)
**What**: Isolated LCEL chain that calls Claude to classify task type.
This file is a LEARNING artifact — not production code.

**Why**: Always build and test a new component in isolation before integrating.
Easier to debug, easier to understand, easier to verify.

**The LCEL pipe operator**:
```
prompt | llm | output_parser
```
Each `|` passes the output of the left side as input to the right side.
- `prompt.invoke({"raw_input": "..."})` → `ChatMessage`
- `llm.invoke(ChatMessage)` → `AIMessage`
- `StrOutputParser().invoke(AIMessage)` → plain string

**Key insight**: The pipe operator is just function composition.
`a | b | c` is equivalent to `c(b(a(input)))`.
LCEL makes it readable and adds streaming, batching, async for free.

**Key insight 2**: Claude is prompted to return ONLY valid JSON.
`temperature=0` makes it deterministic — same input always gives same output.
This is critical for a routing node — you cannot have randomness in classification.

**Key insight 3 — why Claude beats keywords**:
Input: `"Our recommendation system is surfacing old content"`
- Keyword router → `general` (no keywords matched)
- Claude → `kpi` (understands the meaning — feed performance issue)

This is the gap LCEL closes.

**Depends on**: `aria/config.py`, `.env`

**Run**: `uv run python day2_lcel_test.py`

---

#### Step 9 — `aria/nodes/router.py` (Day 2 version — Claude powered)
**What**: Same router node, same state contract, Claude inside instead of keywords.

**Why**: The graph doesn't know or care HOW the router classifies —
it only sees the state fields that come out. Swapping the implementation
is surgical: one file changes, nothing else does.

**Key insight**: This is why typed state contracts matter.
If router.py returned arbitrary keys, every other node would break on swap.
Because the contract is fixed (`task_type`, `routing_reason`, `steps_completed`),
the swap is invisible to the rest of the graph.

**Depends on**: `aria/config.py`, `aria/state.py`, LangChain installed

**Run full graph**: `uv run python main.py`

---

## COMING NEXT

### DAY 3 — LangSmith traces (needs API keys)
- Add ANTHROPIC_API_KEY + LANGCHAIN_API_KEY to `build/.env`
- Run `day2_lcel_test.py` — see Claude classify 6 inputs
- Run `main.py` — full graph now uses Claude router
- Open smith.langchain.com → project "ARIA"
- Read the trace: see every node, every state change, every Claude call
- KEY LEARNING: see routing_reason written by Claude — "Feed performance indicates KPI issue"

### WEEK 4 — Conditional edges + Task Orchestrator + Work Ledger v0
#### Step 10 — `aria/nodes/skill_nodes.py`
- Placeholder nodes for each skill: pr_review_node, kpi_node, ci_cd_node, jira_node
- Each node reads task_type from state, does placeholder work

#### Step 11 — `aria/graph.py` (Week 4 version — conditional edges)
- Replace fixed `router → respond` edge with `add_conditional_edges`
- Router checks state["task_type"] and branches to the right skill node
- Graph shape: intake → router → [pr_review | kpi | ci_cd | jira | general] → respond → END

#### Step 12 — `aria/work_ledger.py` (v0 — event log)
- On every task: append {task_id, task_type, routing_reason, timestamp} to `work_ledger.jsonl`
- This is the seed of Pillar 16 (AI Work Ledger) — 25 weeks of data feeds the ROI dashboard

### WEEK 6 — First real skill (KPI Investigation)
- `skills/kpi_skill.py`: Pydantic input schema, Pydantic output schema, Claude call
- Skill registry: register the skill, look it up by name
- Eval-Lite: 5 golden examples, 3 failure cases, 1–5 rubric
- Router → conditional edge → kpi_skill node → respond

### WEEK 7 — PR Review Skill ✅ DONE
#### Step 13 — `aria/skills/pr_review_skill.py`
**What**: Second real skill. Reviews pull requests for code quality, risk, and business impact.

**Why**: PR Review is the first skill that directly touches engineering workflow at Amar Ujala.
Covers media-tech systems: CMS pipelines, recommendation engine, notification service, analytics.

**Output schema — PRReviewOutput**:
- `verdict`: approve / request_changes / needs_discussion
- `risk_level`: high / medium / low
- `code_issues`: list of `CodeIssue` (severity + category + description + suggestion)
- `missing_tests`: specific test cases that should exist but don't
- `deployment_risks`: what could fail in production at scale
- `business_impact`: effect on CTR, feed, notifications
- `positive_observations`: what was done well

**Key insight**: PRReviewInput includes optional `diff` and `pr_title` fields.
In mock mode (no API key), these are ignored. With Claude, the diff becomes part of the prompt.
This pattern — optional context enrichment — scales to any skill.

**Eval-Lite included**: 5 golden examples covering recommendation ranking, notification trigger,
async refactor, bug fix, A/B test framework. 3 failure cases.

**Depends on**: `aria/config.py`, `aria/skills/skill_registry.py`

#### Step 14 — `aria/nodes/skill_nodes.py` (Week 7 update)
**What**: Registers pr_review skill. Replaces `pr_review_node` placeholder with real skill call.

**Pattern is identical to kpi_node**:
1. Look up skill in registry by name
2. Call `skill_meta.fn(PRReviewInput(...))`
3. Return `skill_name`, `skill_output`, `steps_completed`

**Key insight**: The skill node pattern is now established.
Every future skill (ci_cd, jira) will follow this exact same 10-line pattern.
The registry decouples skill discovery from skill execution.

---

## WEEK 28 — Governed Self-Improvement & Update Manager

**Primary objective**: Build ARIA's governed self-improvement layer — versioned updates,
approval gates, canary deployment, and verified rollback. The AI Capability Marketplace
is NOT built yet; it is deferred until this end-to-end lifecycle is proven.

**Completion bar achieved**: one versioned prompt update travels through:
  discovery → proposal → evaluation → T4 approval → canary → promotion
  → comparison → verified rollback

---

### Core data contracts — `aria/evolution/update_manager/models.py`

**What**: Immutable `UpdateRelease` Pydantic model with full 9-state lifecycle.

**Key types**:
- `UpdateStatus` (str Enum): discovered → proposed → evaluated → awaiting_approval
  → canary → active → superseded / rolled_back / rejected
- `ComponentType`: prompt, retrieval_config, evaluation_rubric, routing_rule, skill,
  voice_ux, knowledge_ingestion
- `ImpactLevel`: none / low / medium / high / critical
- `TERMINAL_STATUSES: frozenset` — {active, superseded, rolled_back, rejected}
- `compute_hash(content: str) → str` — SHA-256 hex (64 chars) of content string
- `UpdateRelease.verify_hash()` — computes hash of current content, compares to stored

**Validators**:
- `content_hash` must be exactly 64 hex chars (SHA-256)
- `semantic_version` must match x.y.z semver pattern

**Exceptions**: `UpdateNotFoundError`, `UpdateStateError`, `SelfApprovalError`,
  `ConstitutionalViolationError`, `HashMismatchError`, `ConcurrentActivationError`

**Key insight**: `is_terminal()` prevents any mutation after reaching a terminal state.
This is the append-only audit log property — terminal updates are permanent records.

---

### Thread-safe store — `aria/evolution/update_manager/store.py`

**What**: `UpdateStore` Protocol + `InMemoryUpdateStore`.

**Concurrency safety**:
- `begin_activation(update_id) → bool` — returns False if already activating (concurrent prevention)
- `end_activation(update_id)` — releases lock; always called in `finally`
- Uses `threading.Lock` protecting a `set[str]` of in-flight activation IDs

**Key insight**: The `__len__` method making empty stores falsy requires callers to use
`if store is not None` rather than `store or InMemoryUpdateStore()`. Fixed in pipeline.py.

---

### Constitutional AI safety — `aria/evolution/update_manager/constitutional.py`

**What**: 22 deterministic regex rules blocking governance-weakening proposals.

**Checked surfaces**: `update.changelog`, `update.content`, each `update.evidence_refs` item.

**Rules block**:
- Governance weakening: disable/remove/weaken governance, bypass T4/T5, skip approval, auto-approve
- Evidence gate disabling: disable/remove/bypass evidence gate
- Privacy gate disabling: disable/remove/bypass privacy gate
- Audit log disabling: disable/skip/remove audit
- Risk ceiling manipulation: raise/increase own risk ceiling
- Self-modification: modify/update/override constitutional rules
- Executable code: exec(), eval(), __import__()
- Marketplace injection: import marketplace, from marketplace import

**Key insight**: Constitutional rules are checked TWICE — at `activate_canary()` and again
at `approve_update()`. Two independent checks prevent an approval race condition.

---

### Health checks — `aria/evolution/update_manager/health.py`

**What**: 4 deterministic health checks run before canary promotion and rollback.

**Checks**: content_non_empty, hash_verification, constitutional_check, version_format

**Key insight**: Health checks are the last line of defence before `active` status.
A hash that passes `verify_hash()` but was tampered since the check will fail here.

---

### Update Manager operations — `aria/evolution/update_manager/operations.py`

**What**: `UpdateManager` class with all 9 lifecycle operations.

**Operations**:
1. `list_pending_updates()` — awaiting_approval + canary + evaluated + proposed
2. `get_update(update_id)`
3. `compare_update(update_id) → UpdateComparison` — `difflib.unified_diff` on content
4. `show_changelog(component_name) → list[UpdateRelease]` — oldest first
5. `approve_update(update_id, approver)` — T4 gate: awaiting_approval → canary
   Blocks: self-approval, stale state, unauthorized approver, constitutional violations
   Idempotent: same approver on already-canary = no-op
6. `reject_update(update_id, reason)` — any non-terminal → rejected
7. `activate_canary(update_id)` — evaluated/awaiting_approval → canary with constitutional check
8. `promote_canary(update_id)` — canary → active after hash + health + concurrency checks
   Supersedes any prior active version of the same component
9. `rollback_update(component_name, target_version)` — verified hash + health → restore target to active

**Key insight**: `promote_canary` uses `try/finally` to guarantee `end_activation` is
called even if hash verification or health checks raise. This prevents a crashed promotion
from permanently blocking all future activations of the same update.

---

### Proposal Pipeline — `aria/evolution/pipeline.py`

**What**: `ProposalPipeline` connects EvolutionMonitor → DebateEngine → run_sandbox → UpdateRelease.

**Steps**:
1. Debate — if not "approve", proposal is rejected; return `PipelineResult(update=None)`
2. Sandbox — if fails, proposal sandbox_failed; return `PipelineResult(update=None)`
3. Create `UpdateRelease` in `awaiting_approval` status with SHA-256 content hash

**Bug fixed**: `update_store or InMemoryUpdateStore()` was creating a new store when an
empty store was passed (empty store is falsy via `__len__`). Changed to `is not None` check.

---

### Evolution node wiring — `aria/nodes/evolution_node.py`

**What**: `evolution_node(state: dict) → dict` — routes natural language evolution intents.

**Supported intents** (matched via keywords in `raw_input`):
- `scan / capability gap / discover` → `_handle_scan` — runs EvolutionMonitor + pipeline
- `pending / show proposal / self-improvement` → `_handle_list_pending`
- `evaluate proposal <id>` → `_handle_evaluate_proposal`
- `compare update <id>` → `_handle_compare_update`
- `rollback component <name> to <version>` → `_handle_rollback`

**Graph wiring** (`aria/graph.py`): "evolution" task_type → "evolution_node" → "respond"

---

### Teams approval card — `aria/integrations/teams_bot.py`

**What**: `_build_evolution_approval_card(data, task_id)` — Adaptive Card for T4 approval UX.

**Card sections**:
- Version diff: from/to versions, component name, security/privacy impact
- Changelog: why ARIA proposes this update
- Diff preview: first 8 lines of `difflib.unified_diff` output
- Canary plan: deployment strategy (5% traffic, 24h monitoring)
- Rollback target: what version will be restored if promotion fails
- Evidence refs: up to 3 supporting work ledger entries
- Governance notice: reminder that ARIA only proposes, activation requires T4 approval
- Actions: "✅ Approve Update" / "❌ Reject Update" / "📋 All Pending Updates" (ShowCard)

**Handles 5 action types**: compare_update, list_pending, scan, evaluate_proposal, rollback

---

### Evolution package exports — `aria/evolution/__init__.py`

**What**: Updated to export all Week 28 public API items.

**New exports**: `ProposalPipeline`, `PipelineResult`, `UpdateRelease`, `UpdateStatus`,
`ComponentType`, `ImpactLevel`, `UpdateComparison`, all exception classes, `compute_hash`,
`UpdateStore`, `InMemoryUpdateStore`, `UpdateManager`

---

### Test suite — `tests/test_week28_evolution.py`

**What**: 58 tests covering 13 adversarial scenarios + end-to-end completion bar.

**Scenarios**:
1. Version creation — fields, hash validation, invalid semver/hash rejected
2. Update comparison — diff shown, empty diff for no prior content
3. Forged approval blocked — unauthorized approver list enforced
4. Stale approval blocked — active/rejected/canary states block re-approval
5. Constitutional attack blocked — 9 malicious patterns all caught; content checked too
6. Failed sandbox blocks pipeline — mocked SandboxResult(passed=False)
7. Failed health check blocks promotion — hash tamper + health mock both raise
8. Hash mismatch blocks activation — verify_hash() fails after content tamper
9. Concurrent activation blocked — begin_activation() returns False on second call
10. Interrupted deployment recoverable — finally-block releases lock; reject still works
11. Rollback restores prior version — target→active, current→rolled_back
12. Work-ledger signal creates proposal — 10 repeated tasks detected by monitor
13. Evidence coverage gap — 5 failed tasks signal a gap

**End-to-end test**: `TestEndToEndCompletionBar.test_full_governed_lifecycle` — one prompt
update traverses the full lifecycle in a single test.

**Full suite**: 667 tests passing (58 new in Week 28, up from 609).

**Claim**: ARIA now supports governed self-improvement proposals with versioned approval,
canary deployment, and verified rollback. The marketplace is explicitly deferred.

---

## Week 29 — AI Work Ledger v2 → Fine-Tuning Prototype — COMPLETE (Accepted by Codex)

**Date**: 2026-06-14
**Status**: ✅ COMPLETE. All five priorities independently ACCEPTED by Codex. Week 30 not started.

**Priorities (built in fixed ROI order, each accepted):**
1. **AI Work Ledger v2** — schema-versioned, queryable JSONL ledger; every event carries `ledger_event_version`, `correlation_id`, `actor`, `risk_tier`, per-event token/cost/latency, `evaluation_score`, `outcome_label`. One-time v1 backfill for legacy records. Source of truth for ROI + dataset export.
2. **ROI Dashboard** — frontend view over Work Ledger v2 (tasks by skill/week, approved-vs-rejected ratio, human time saved, cost spent, failure/rollback rate, evolution-loop activity), harness-engineering copy.
3. **Dataset Export Prototype** — `(input, output)` SFT JSONL from `outcome_label=approved` events; `(prompt, chosen, rejected, correction)` DPO JSONL from rejected+corrected pairs; dedup by hash, quality filter, format validation. No training run.
4. **Model Lifecycle Registry v1** — file-backed JSONL registry (model name + base version, training-dataset hash, holdout eval score, deployment endpoint, rollback pointer, active skills). Atomic flush, schema-validated, audit-logged to the Work Ledger.
5. **Fine-Tuning Prototype** — offline deterministic **dry-run** LoRA planner/runner over the Priority-3 export. Proves the pipeline only: a candidate is registered + evaluated against a holdout; NO real training, NO model download, NO GPU, NO vLLM serving, NO model-router wire-up, NO activation. Active model stays NONE.

**Security / provenance hardening (Codex rounds, all closed):**
- Dataset provenance is ledger-backed and **content-bound**: a cited `OutcomeRecorded` / `CorrectionRecorded` event must record a `content_hash` equal to the canonical hash reconstructed from the exported row; hashless legacy events fail closed.
- Structural identifiers (`task_id`, each `source_events` entry) are validated as non-empty strings — never `str()`-coerced.
- **DPO `chosen` binding** (final finding): the planner requires `chosen == correction`, so the content-bound `correction` transitively authorises the exact preferred response DPO trains toward. Swapping only `chosen` is rejected.

**Verified baseline (2026-06-14):**
- `tests/test_week29_fine_tuning.py`: 35 passed
- Full backend suite: 1021 passed, 1 skipped
- `py_compile` (planner + tests): OK
- Priority 4 + Priority 5 demos: clean — 0 audit-emission failures, no activation, no training/deployment, "Prototype only."
- `git diff --check`: OK
- Test deployment pollution absent — conftest `_isolate_deployment_root` + `_isolate_ledger_v2` autouse fixtures redirect all writes to tmp; previously-tracked runtime `deployments/prompts/*.txt` artifacts removed from version control and gitignored.

**Codex final verdict**: no remaining findings; Week 29 Priorities 4 and 5 accepted; **Week 29 complete.**

**Roadmap note**: CLAUDE.md § 28.4 (Agentic AI Roadmap — eight V2/V3 capabilities) added as documentation-only; not implemented.

---

## Week 28 Stabilization — Round 2 Fixes (Closed by Round 3)

**Date**: 2026-06-09
**Status**: Superseded — Round 2 left two P1 findings open; Round 3 closes them.

**Round 2 findings addressed:**
1. Duplicate Release Scan Prevention — pipeline idempotency guard with content-hash comparison.
2. Teams Per-Update Action IDs — `aria_source` field + missing-ID guard.
3. Governed Canary Promotion — already passing.
4. Graph Uses Promoted Version — real approve→promote_canary flow, 3-tuple component_loader, component_version wired.
5. Rollback Restores Old Version — already passing.
6. **Path Confinement (INCOMPLETE in Round 2)** — `_write_artifact_atomic` gained `deployment_root kwarg OR DEPLOYMENT_ROOT global`, but `DEPLOYMENT_ROOT` remained `None`, so confinement was never active. Fixed in Round 3.
7. **Persistence Fail-Closed (INCOMPLETE in Round 2)** — Artifact write reordered to after `store.save()`, but `promote_canary` still called `_supersede_active()` (saves one record) then `store.save(activated)` (saves a second record) as two independent operations. A failure between them left no active release. Fixed in Round 3.
8. Voice Transcript Fix — stale closure fixed, 2 Vitest tests pass.
9. Typed Work Ledger Events — ordering verified; rollback event test added.
10. Documentation — BUILD_LOG and CLAUDE.md updated.

---

## Week 28 Stabilization — Round 3 Fixes (Closed by Round 4)

**Date**: 2026-06-09
**Status**: Round 3 fixes submitted; awaiting Codex re-audit. Week 29 blocked until accepted.

**Round 3 findings addressed (all Codex re-audit findings from round 2):**

1. **[P1] Path Confinement Active by Default** — `DEPLOYMENT_ROOT` changed from `None` to `Path(__file__).parent.parent.parent.parent / "deployments"` (resolves to `apps/backend/deployments/`). Any write without an explicit `deployment_root` will be confined to this directory by default. Added `configure_deployment_root(path)` helper for override at startup. Added `deployment_root: Optional[Path] = None` parameter to `UpdateManager.__init__` so tests can pass `tmp_path` for artifact-writing tests without modifying the module global.

2. **[P1] Atomic Multi-Save (Transactional Promote + Rollback)** — Added `save_batch(updates: list[UpdateRelease])` to both `UpdateStore` Protocol and `InMemoryUpdateStore`. Single lock, single flush, all-or-nothing rollback on `OSError`. Renamed `_supersede_active()` to `_collect_superseded()` — it now returns a list of modified records without saving. `promote_canary` collects superseded + builds activated, then calls `save_batch(superseded + [activated])` — one atomic operation. `rollback_update` builds `[rolled_back, restored]` list then calls `save_batch(batch)` — one atomic operation. Neither operation can leave a component with no active release due to a partial failure.

3. **[P2] Rollback Failure Event Test Renamed + Persistence-Error Test Added** — `test_rollback_emits_failure_event_with_rollback_outcome` renamed to `test_successful_rollback_emits_failure_typed_audit_event` with docstring clarifying this is the nominal path (rollbacks always emit a failure-typed event for audit purposes, not because of an error). New test `test_rollback_persistence_error_leaves_no_partial_state` verifies that when `save_batch` raises `PersistenceError`, the exception propagates and neither state transition is committed — store remains at pre-rollback state.

4. **[P3] Documentation Accuracy** — CLAUDE.md status line updated: removed "path confinement active by default" claim from Round 2, updated test count to 705 (18 in stabilization suite), described Round 3 items accurately.

---

## Week 28 Stabilization — Round 4 Fixes (Closed by Round 5)

**Date**: 2026-06-09
**Status**: Round 4 fixes submitted; awaiting Codex re-audit. Week 29 blocked until accepted.

**Round 4 findings addressed (all Codex re-audit findings from round 3):**

1. **[P1] False-Active State on Artifact Failure** — Root cause: both `promote_canary` and `rollback_update` committed state via `save_batch` BEFORE writing the artifact. If the artifact write failed after `save_batch`, the release was marked `active` in the store but the artifact was absent or stale. Retry was impossible because `promote_canary` requires `canary` status. Fix: artifact write and `_verify_artifact` now happen BEFORE `save_batch` in both methods. If the write fails, the release stays in `canary` (promotion) or the state stays unchanged (rollback) — both are fully retriable. If `save_batch` fails after a successful write, the artifact is ahead of state by one write; the next retry idempotently re-writes the same content and retries `save_batch`. The registry (store) remains the authoritative source of truth throughout.

2. **[P2] No Failure Ledger Event on Operational Failure** — `promote_canary` and `rollback_update` had no exception handler, so `PersistenceError` and other operational failures produced zero ledger events. Fix: added `except Exception as exc: _log("failure", ..., outcome="promotion_failed"/"rollback_failed", detail=str(exc)); raise` inside both methods. On success, only the nominal events are emitted (`promotion`, `activation` for promote; `failure` with `outcome="rollback"` for rollback). On any exception, a `failure` event with the failure outcome is emitted before re-raising.

3. **[P2 test] Persistence Failure Emits Failure Event** — New test `test_promote_canary_persistence_failure_emits_failure_event`: mocks `save_batch` to raise `PersistenceError`, calls `promote_canary`, verifies (a) `failure` event with `outcome="promotion_failed"` is captured, (b) the release stays in `canary` status (no false-active state).

4. **[P3] Checklist Counts Updated** — `WEEK28_STABILIZATION_ACCEPTANCE_CHECKLIST.md` updated: "exactly 16 tests" → "at least 19 tests", "at least 703 tests" → "at least 706 tests".

---

## Week 28 Stabilization — Round 5 Fixes (Awaiting Codex Re-Audit)

**Date**: 2026-06-10
**Status**: Round 5 fixes submitted; awaiting Codex re-audit. Week 29 blocked until accepted.

**Round 5 findings addressed (all Codex re-audit findings from round 4):**

1. **[P1] Artifact Restored on save_batch Failure** — Root cause: artifact was written to disk before `save_batch`, but if `save_batch` failed, the old artifact content was not restored — only the store was rolled back (atomically by `save_batch`). This left the filesystem inconsistent with the store. Fix: added `_backup_artifact(path_str)` helper (reads previous content; returns None if file absent) and `_restore_artifact(path_str, prev_content, deployment_root)` helper (re-writes previous content, or `unlink` if file was absent before; best-effort, never raises). In both `promote_canary` and `rollback_update`, the artifact is backed up before writing. An inner `try/except` around artifact write + `save_batch` calls `_restore_artifact` if any exception occurs after the artifact was physically written. This ensures filesystem always matches store state after any failure.

2. **[P2] Failure Event Wraps Entire Governed Operation** — Root cause: in `promote_canary`, the outer `except Exception` (failure event handler) was an INNER try block that only started after hash/health validation. Hash failures and health-check failures raised exceptions that bypassed the failure event handler entirely. Fix: restructured `promote_canary` to use three levels — `try/finally` (outer, releases activation lock), `try/except` (middle, logs failure event for ANY exception in the governed operation including hash/health), `try/except` (inner, restores artifact on save_batch failure). Same pattern applied to `rollback_update`: the entire body from content/hash/health checks through artifact write and save_batch is now wrapped in the failure-event handler.

3. **New tests added** — `test_promote_canary_hash_failure_emits_failure_event`: verifies `HashMismatchError` from corrupted hash emits `failure` event with `outcome="promotion_failed"`. `test_promote_canary_artifact_restored_on_save_batch_failure`: verifies that when `save_batch` raises `PersistenceError` after artifact write, the artifact is restored to old content and the store stays in `canary` state.

---

## Week 28 Stabilization — Round 12 Narrow Fixes (Awaiting Codex Re-Audit)

**Date**: 2026-06-11
**Status**: Round 11 component-identity work was NOT accepted by Codex —
two P1 gaps surfaced (monitor produced zero proposals; pr_review_skill
silently swallowed `ComponentArtifactError`). Round 12 closes those two
gaps with no architecture redesign. Week 29 BLOCKED until Codex
independently verifies. Do NOT mark complete prior to Codex acceptance.

**Verified baseline (2026-06-11):**
- `test_week28_stabilization.py`: 38 passed
- Full backend suite: 726 passed, 0 failures
- `compileall apps/backend/aria`: exit 0
- `ARIAVoice.test.jsx`: 2 passed
- Frontend build: exit 0
- Path selector (`-k "deployment_path or outside_deployment_root or traversal"`
  against `test_week28_stabilization.py`): 5 passed
- `git diff --check`: exit 0

**Round 12 findings addressed (Codex Round 11 re-audit):**

1. **[P1] Monitor cannot create any proposal**
   - Root cause: Round 11 left two incompatible mappings in
     `aria/evolution/monitor.py`. `_SIGNAL_TO_EVOLUTION` produced only
     `skill | rag | workflow`, and `_TASK_TYPE_TO_TARGET` only registered
     `(pr_review, EvolutionType.prompt) → "pr_review_prompt"`. The product
     of these two tables for any observed signal was always None, so
     `_signal_to_proposal` returned None for every real signal — the
     monitor detected gaps but queued zero updates.
   - Fix:
     - Removed `_SIGNAL_TO_EVOLUTION` and `_TASK_TYPE_TO_TARGET`.
     - Added one mapping `_TASK_TYPE_SIGNAL_TO_TARGET: dict[(str, str),
       (str, EvolutionType)]` keyed by `(task_type, signal_type)`
       returning `(target_component, evolution_type)`. Both ends agree by
       construction — the value's target_component IS what the pipeline
       will rewrite; the value's evolution_type matches the taxonomy
       bucket. Registered three entries for V1's pr_review_prompt
       component (high_error_rate, low_support_rate, repeated_pattern),
       all → `("pr_review_prompt", EvolutionType.prompt)`.
     - Added separate `_SIGNAL_BASE_RISK: dict[str, float]` for per-signal
       base risk modulation.
     - `_signal_to_proposal` now does one lookup. Abstains only when no
       entry exists; for V1's registered components, supported signals
       always produce a proposal.
   - Test: `test_monitor_scan_produces_proposal_and_pipeline_queues_update`
     in `tests/test_week28_stabilization.py` asserts the full
     monitor→pipeline path:
     ```
     work_ledger.jsonl with 4 pr_review errors + 1 success
       → EvolutionMonitor.scan() → proposals_found == 1
       → proposal.target_component == "pr_review_prompt"
       → ProposalPipeline.run(proposal) → updates_queued == 1
       → queued.component_name == "pr_review_prompt"
       → queued.status == UpdateStatus.awaiting_approval
     ```

2. **[P1] Production consumer bypasses fail-closed artifact validation**
   - Root cause: `apps/backend/aria/skills/pr_review_skill.py::run`
     wrapped the `component_loader.load("pr_review_prompt", default=_SYSTEM)`
     call in `try: ... except Exception: system_prompt = _SYSTEM`. A
     `ComponentArtifactError` raised by the loader for a missing,
     unreadable, outside-root, or hash-mismatched on-disk artifact was
     silently swallowed; the skill ran on the hardcoded `_SYSTEM` prompt
     and the graph completed normally — defeating the runtime
     artifact-authority contract.
   - Fix: removed the broad `try/except` from `pr_review_skill.run`.
     `component_loader.load()` already handles the legitimate "no active
     release" case via its `default` argument (returns
     `(_SYSTEM, None, None)`); the only failures that now propagate are
     genuine fail-closed signals. An invalid runtime artifact surfaces
     through `aria_graph.invoke()` as `ComponentArtifactError`, failing
     the task.
   - Tests:
     - `test_graph_fails_when_active_artifact_is_missing` — creates an
       active release, deletes the on-disk versioned artifact, asserts
       `pytest.raises(ComponentArtifactError)` around
       `aria_graph.invoke(state)` for a pr_review task.
     - `test_graph_fails_when_active_artifact_is_corrupted` — same setup
       but writes tampered content over the artifact (hash no longer
       matches), asserts the same fail-closed propagation.

**No other architectural changes** — transaction architecture (single
component lock, save_batch invariant, immutable versioned artifact),
Round 10 boundary fixes (update_id validation, derived-path reconfinement,
UnicodeError catching), and Round 11's component registry +
`EvolutionProposal.target_component` field all unchanged. The two fixes
above are surgical: 6 lines in `monitor.py`, 8 lines in `pr_review_skill.py`,
3 new test functions.

---

## Week 28 Stabilization — Round 11 Component-Identity Gap (Closed by Round 12)

**Date**: 2026-06-11
**Status**: Round 10 boundary fixes were accepted by Codex. Round 11 closes
the final end-to-end component-identity gap. Week 29 BLOCKED until Codex
independently verifies. Do NOT mark complete prior to Codex acceptance.

**Verified baseline (2026-06-11):**
- `test_week28_stabilization.py`: 35 passed
- Full backend suite: 723 passed, 0 failures
- `compileall apps/backend/aria`: exit 0
- `ARIAVoice.test.jsx`: 2 passed
- Frontend build: exit 0
- Path selector (`-k "deployment_path or outside_deployment_root or traversal"`
  against `test_week28_stabilization.py`): 5 passed
- `git diff --check`: exit 0

**Round 11 changes — end-to-end component identity, no transaction-architecture changes:**

1. **Evolvable-component registry — new module**
   - File: `apps/backend/aria/evolution/component_registry.py`
   - `@dataclass(frozen=True) ComponentRegistration` with five fields:
     `name`, `component_type`, `artifact_subdir`, `artifact_extension`,
     `production_consumer`.
   - `_REGISTRY: dict[str, ComponentRegistration]` lists the V1 evolvable
     component:
     ```
     "pr_review_prompt" → (prompt, "prompts", ".txt", "aria.skills.pr_review_skill")
     ```
   - Helpers: `get_registration(name)`, `is_evolvable(name)`,
     `list_evolvable_components()`, `artifact_path_for(name, deployment_root)`.
   - `UnknownComponentError(ValueError)` raised for unknown targets.

2. **`EvolutionProposal.target_component: str` (new validated field)**
   - File: `apps/backend/aria/evolution/models.py`
   - Field declared between `evolution_type` and `status`.
   - `@field_validator("target_component")` calls
     `component_registry.is_evolvable(v)` at construction; rejects with
     `UnknownComponentError` if the target is not registered. A proposal
     with an unknown target therefore cannot exist as a constructed model.

3. **`ProposalPipeline` end-to-end uses `target_component`**
   - File: `apps/backend/aria/evolution/pipeline.py`
   - Removed: `_ETYPE_TO_COMPONENT` mapping, `_COMPONENT_LAYOUT` layout map,
     `_default_artifact_path()` helper, and the dead `ImpactLevel`/`EvolutionType`
     imports they used.
   - Added: explicit `component_registry.get_registration(proposal.target_component)`
     lookup inside `run()` BEFORE building the release (defence in depth on top
     of the model validator). If the target is somehow unknown by the time the
     pipeline runs, `run()` returns `PipelineResult(succeeded=False,
     blocked_reason=...)` instead of silently producing a bogus release.
   - `component_name = proposal.target_component` (was
     `f"{proposal.evolution_type.value}_component"`).
   - `component_type = registration.component_type` (was a table lookup off
     `evolution_type`).
   - `artifact_path = component_registry.artifact_path_for(target,
     deployment_root)` using the LIVE `ops.DEPLOYMENT_ROOT` so test fixtures
     that monkeypatch the root see the override.
   - All ledger events updated: `component_name=proposal.target_component`
     replaces every `f"{proposal.evolution_type.value}_component"` site.

4. **All `EvolutionProposal` constructor sites updated**
   - `aria/evolution/monitor.py`: new `_TASK_TYPE_TO_TARGET` mapping
     `(task_type, evolution_type) → target_component`. `_signal_to_proposal`
     looks up the target; if absent, the monitor **abstains** (returns
     `None`) — silence is safer than emitting a proposal whose target the
     pipeline would reject.
   - `tests/test_evolution.py::_proposal()`: added `target_component`
     kwarg defaulting to `"pr_review_prompt"`.
   - `tests/test_week28_evolution.py::_make_proposal()`: added
     `target_component` kwarg defaulting to `"pr_review_prompt"`.
   - `tests/test_week28_stabilization.py::_make_proposal()`: added
     `target_component="pr_review_prompt"` to the defaults dict.
   - `tests/test_week28_stabilization.py::test_pipeline_assigns_confined_artifact_path_to_release`:
     proposal constructor updated.

5. **`test_graph_uses_promoted_component_version` fully rewritten**
   - File: `apps/backend/tests/test_week28_stabilization.py`
   - The manual `_make_release` shortcut is removed from this acceptance
     test. Every state mutation now flows through the real production code
     path:
     ```
     EvolutionProposal(target_component="pr_review_prompt")
         → ProposalPipeline.run()           # produces awaiting_approval release
         → UpdateManager.approve_update()   # awaiting_approval → canary
         → UpdateManager.promote_canary()   # canary → active + writes versioned artifact
         → Path(active.artifact_path).exists()
         → compute_hash(read_text(...)) == release.content_hash
         → aria_graph.invoke()              # reports promoted hash/version
         → InMemoryUpdateStore(persist_path=...)  # fresh instance, same JSONL
         → aria_graph.invoke()              # STILL reports promoted hash/version
     ```
   - Assertions cover all four properties listed in the user's brief:
     (a) `release.component_name == "pr_review_prompt"`,
     (b) versioned artifact_path exists on disk and bytes hash to
         `release.content_hash`,
     (c) graph reports promoted version + hash,
     (d) a newly loaded store (fresh `InMemoryUpdateStore` reading the same
         persist_path JSONL) still serves the promoted version/hash to the
         graph — restart-survival via the persistence layer.

**No other architectural changes** — the transaction architecture from
Round 9 (single component-level lock, save_batch invariant, immutable
versioned artifact as runtime authority) and the Round 10 boundary fixes
(filename-safe update_id, derived-path reconfinement, UnicodeError catching)
are unchanged.

---

## Week 28 Stabilization — Round 10 Narrow Fixes (Accepted by Codex)

**Date**: 2026-06-11
**Status**: Round 10 fixes submitted; Week 29 BLOCKED until Codex independently
verifies the boundary fixes. Do NOT mark this round complete prior to Codex
acceptance.

**Verified baseline (2026-06-11):**
- `test_week28_stabilization.py`: 35 passed
- Full backend suite: 723 passed, 0 failures
- `compileall apps/backend/aria`: exit 0
- `ARIAVoice.test.jsx`: 2 passed
- Frontend build: exit 0
- Path selector (`-k "deployment_path or outside_deployment_root or traversal"` against `test_week28_stabilization.py`): 5 passed (3 original path-confinement + 2 new update_id traversal)
- `git diff --check`: exit 0

**Round 10 findings addressed (Codex Round 9 re-audit):**

1. **[P1] update_id can escape deployment root**
   - Root cause: `_versioned_artifact_path` confined the declared `artifact_path`
     but appended `update_id` afterward; the derived path was checked with
     `exists()` before any reconfinement. A hostile `update_id="../escape"`
     would activate an existing outside-root artifact.
   - Fix (defence-in-depth):
     - Added `_VALID_UPDATE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")` and
       `_validate_update_id()` rejecting empty strings, non-filename-safe
       characters, and any "`..`" segment.
     - `_versioned_artifact_path()` calls `_validate_update_id(update_id)`
       FIRST.
     - Re-runs `_confined_path()` on the FINAL derived path (after the
       `update_id + suffix` append) before returning. Even if a separator
       slipped past step 1, the final path is guaranteed to resolve under
       the deployment root before any `exists()`/read/write.
   - Tests:
     `test_update_id_with_traversal_segment_rejected_before_filesystem_touch`
     and `test_promote_canary_rejects_traversal_update_id_before_artifact_touch`
     prove both layers.

2. **[P1] Production pipeline bypasses artifact authority**
   - Root cause: `ProposalPipeline.run()` constructed `UpdateRelease` with no
     `artifact_path`, so in production `promote_canary` skipped the artifact
     write path entirely and `component_loader.load()` returned in-memory
     `content`, defeating the entire artifact-is-runtime-authority contract.
   - Fix: introduced a small **component registry** in
     `apps/backend/aria/evolution/pipeline.py` — `_COMPONENT_LAYOUT` maps
     each `ComponentType` to a `(subdirectory, extension)` pair under the
     module-level `DEPLOYMENT_ROOT`. `_default_artifact_path(component_name,
     component_type)` builds the deterministic deployment path; the helper
     reads the **live** `operations.DEPLOYMENT_ROOT` attribute (not a stale
     import) so test fixtures that monkeypatch the root see the override.
     `ProposalPipeline.run()` now sets `artifact_path=...` on every
     `UpdateRelease` it creates.
   - Test: `test_pipeline_assigns_confined_artifact_path_to_release` verifies
     a real pipeline → release produces a release with a populated
     `artifact_path` that resolves inside the configured deployment root.

3. **[P2] Decode failures escape the loader contract**
   - Root cause: `component_loader.load()` caught only `OSError` around the
     `read_text(encoding="utf-8")` call. Binary corruption raised a raw
     `UnicodeDecodeError` (subclass of `UnicodeError`, not `OSError`),
     breaking the documented typed-exception contract.
   - Fix: changed the except clause to `except (OSError, UnicodeError)` —
     binary corruption now surfaces as `ComponentArtifactError`, identical
     to missing/permission/hash-mismatch failures. Updated error message to
     mention "corrupted" alongside "missing or unreadable".
   - Test: `test_corrupted_binary_artifact_raises_typed_error_not_unicode_decode`
     writes a non-UTF-8 byte sequence (`\xff\xfe\xfd\x00...`) to the
     committed artifact and asserts the loader raises `ComponentArtifactError`,
     never `UnicodeDecodeError`.

4. **[Critique] Concurrency tests overstated their proof**
   - Round 9's `promotion-vs-rollback` and `rollback-vs-rollback` tests
     pre-acquired the lock, attempted BOTH operations under contention (both
     failed), then ran BOTH operations after release (both succeeded). This
     was 4 attempts × 2 successes × 2 failures — it tested the lock semantics
     but did not assert "exactly one of two competing operations succeeds".
   - Fix: each of the three concurrency tests now models **exactly two
     attempts** — one contender (under lock-held, must raise
     `ConcurrentActivationError`) and one winner (after release, must
     succeed). Helper functions `_run_contender`, `_run_winner`, and
     `_assert_two_attempts_one_succeeded_one_blocked` make the assertion
     explicit: across the two attempts, exactly one succeeded and exactly
     one raised `ConcurrentActivationError`. Each test then asserts on the
     resulting single active release: artifact exists on disk, bytes match
     `content_hash`, and `component_loader.load()` returns the winner's
     content + hash + version.

**Architectural design (unchanged from Round 9):**
- Single component-level lock in the store; same lock for promotion and rollback.
- Store invariant: at most one active release per component, enforced atomically
  in `save_batch`.
- Immutable versioned artifact path is the runtime authority; in-memory
  `UpdateRelease.content` is proposal data, never silently substituted.
- All transitions atomic via `save_batch`; staged artifacts cleaned up on any
  pre-commit failure.

---

## Week 28 Stabilization — Round 9 Architectural Pass (Closed by Round 10)

**Date**: 2026-06-10
**Status**: Round 9 fixes submitted; Week 29 BLOCKED until Codex independently
verifies the adversarial cases. Do NOT mark this round complete prior to
Codex acceptance.

**Verified baseline (2026-06-10):**
- `test_week28_stabilization.py`: 31 passed
- Full backend suite: 719 passed, 0 failures
- `compileall apps/backend/aria`: exit 0
- `ARIAVoice.test.jsx`: 2 passed
- Frontend build: exit 0
- Path selector (`-k "deployment_path or outside_deployment_root or traversal"` against `test_week28_stabilization.py`): 3 passed
- `git diff --check`: exit 0

**Round 9 changes — single source of truth + single concurrency boundary:**

1. **One component-level lock, used by every lifecycle mutation**
   - `InMemoryUpdateStore` now exposes a single concurrency primitive:
     `acquire_component(component_name)` / `release_component(component_name)`.
   - The update_id-keyed lock (`begin_activation`/`end_activation`) is
     **removed** — it was incidental, not the right correctness boundary.
   - Both `promote_canary` and `rollback_update` acquire the component lock
     BEFORE reading active releases, rollback targets, or artifact state.
     The initial `_require()` lookup in `promote_canary` only identifies the
     component for lock acquisition; all governed reads (status, active set,
     `_find_active`, `_collect_superseded`) happen UNDER the lock.
   - Both release the lock in a `finally` block on every path.
   - Result: promotion-vs-promotion, promotion-vs-rollback, and rollback-vs-
     rollback on the same component serialize on the same lock. Different
     components run in parallel.

2. **Store invariant — at most one active release per component**
   - `_check_active_invariant()` runs inside `save` and `save_batch` AFTER
     applying records in-memory and BEFORE the disk flush.
   - If any component would have > 1 active record in the resulting state,
     the entire batch is restored to its prior durable values atomically
     and `MultipleActiveReleasesError` is raised. No record from the batch
     is visible in memory or on disk.
   - This is the final defensive guarantee — even if a caller bypassed the
     component lock, the store cannot install two simultaneously-active
     releases for one component.

3. **Immutable versioned artifact is the runtime authority**
   - `component_loader.load()` now reads from the active release's
     `artifact_path` and re-runs:
     - **Path confinement** — `_confined_path(artifact_path)` against the
       module-level `DEPLOYMENT_ROOT`. Outside-root → `ComponentArtifactError`.
     - **File presence** — missing/unreadable → `ComponentArtifactError`.
     - **Hash verification** — on-disk SHA-256 vs. `content_hash`. Mismatch
       → `ComponentArtifactError`.
   - All three failure modes are **fail-closed**. The in-memory
     `UpdateRelease.content` field is NEVER silently substituted for an
     invalid disk artifact.
   - `UpdateRelease.content` is now documented as **proposal data** —
     retained for diff display, rollback target verification, and tests
     that operate in a content-only mode (no `artifact_path` set).
   - When the active release has no `artifact_path`, `content` is the
     runtime data (proposal-only mode; existing behavior preserved).

4. **Rollback parity with promotion**
   - Same component lock acquisition pattern.
   - Same immutable versioned artifact path keyed by `target.update_id`
     (never reused across updates).
   - **Immutability protection**: if the versioned artifact already exists
     on disk, its bytes are hash-verified before reuse. A mismatching
     existing file raises `HashMismatchError` — the rollback NEVER
     overwrites an immutable artifact with different bytes.
   - Same atomic `save_batch` invariant check.

5. **Deterministic adversarial test suite (9 new tests in
   `test_week28_stabilization.py`)**
   - `test_promotion_vs_promotion_same_component_lock_blocks_second`
   - `test_promotion_vs_rollback_same_component_lock_blocks_second`
   - `test_rollback_vs_rollback_same_component_lock_blocks_second`
   - `test_store_rejects_two_active_releases_in_one_batch`
   - `test_runtime_reads_committed_artifact_path`
   - `test_missing_active_artifact_fails_closed`
   - `test_corrupted_active_artifact_fails_closed`
   - `test_persistence_failure_removes_uncommitted_artifact`
   - `test_different_components_run_concurrently`
   - Each concurrency test asserts: exactly one operation succeeds, the
     other raises `ConcurrentActivationError`, exactly one active release
     remains, the artifact exists on disk, its bytes match `content_hash`,
     and `component_loader.load()` returns that exact version.
   - All concurrency tests use **deterministic synchronization** —
     pre-acquired component locks, NOT thread-timing races.

6. **Existing test migration**
   - `TestConcurrentActivationBlocked` tests updated to use
     `acquire_component`/`release_component` (the lock API changed from
     update_id-keyed to component_name-keyed).
   - `test_rollback_target_hash_mismatch_blocked` test setup updated:
     the prior version is now in `superseded` (not `active`) status —
     the old setup violated the new at-most-one-active invariant.
   - `test_rollback_restores_artifact_and_graph_version` now
     monkeypatches `operations.DEPLOYMENT_ROOT` to `tmp_path` so the
     loader's confinement check passes.

7. **Documentation discipline**
   - Path selector claim corrected — the checklist runs against
     `test_week28_stabilization.py` only, returning **3 passed** (not 5;
     the previous round's report incorrectly counted 2 unrelated path
     tests from the evolution test file).
   - This Round 9 entry is marked "Awaiting Codex Re-Audit" — Week 29 stays
     blocked until Codex independently verifies the adversarial cases.

---

## Week 28 Stabilization — Round 8 Fixes (Closed by Round 9)

**Date**: 2026-06-10
**Status**: Round 8 fixes submitted; awaiting Codex re-audit. Week 29 blocked until accepted.

**Verified baseline (2026-06-10):**
- `test_week28_stabilization.py`: 22 passed
- Full backend suite: 710 passed, 0 failures
- `compileall apps/backend/aria`: exit 0
- `ARIAVoice.test.jsx`: 2 passed
- Frontend build: exit 0
- Path selector (`-k "deployment_path or outside_deployment_root or traversal"`): 5 passed

**Round 8 findings addressed (all Codex re-audit findings from round 7):**

1. **[P1] Final replace occurs after durable activation** — Root cause: `save_batch()` committed the release as `active` with `artifact_path` pointing at `confined_final`, then `os.replace(staged_path, confined_final)` ran after. If the rename failed, the store said "active" but the old artifact was still on disk. Fix: **immutable versioned artifact paths** — instead of staging to `.next` and replacing, the new content is written directly to `confined_final.parent / (update_id + confined_final.suffix)` — a path unique per update, never reused. The activated/restored record's `artifact_path` is updated to point at this versioned path before `save_batch` is called. `save_batch` is the LAST operation. No `os.replace` needed after commit. The versioned file IS the live artifact. Applied to both `promote_canary` and `rollback_update`.

2. **[P1] Concurrent updates can both become active** — Root cause: the activation lock was keyed only by `update_id`. Two different updates for the same component had different IDs, so both could acquire their locks simultaneously and both write `active` status, leaving two active releases in the store. Fix: **component-level activation lock** — `InMemoryUpdateStore` now maintains a second set `_activating_components: set[str]` alongside `_activating: set[str]`. `begin_activation(update_id, component_name)` atomically checks and acquires BOTH locks; returns `False` if either is already held. `end_activation` releases both. Both `promote_canary` and `rollback_update` pass `component_name=update.component_name` to the lock calls. New test `test_concurrent_different_updates_same_component_only_one_wins` added to `TestConcurrentActivationBlocked`.

3. **[P3] Dead code removal** — `_ArtifactSnapshot`, `_snapshot_artifact()`, and `_restore_from_snapshot()` were introduced in Round 6 and superseded by the staging approach in Round 7. They remained as dead code. All three removed from `operations.py`.

4. **[Fix] Missing Path import** — `test_week28_evolution.py` tests updated in Round 8 used `Path(active.artifact_path)` but `pathlib.Path` was not imported. Added `from pathlib import Path` to the test module.

---

## Week 28 Stabilization — Round 7 Fixes (Closed by Round 8)

**Date**: 2026-06-10
**Status**: Round 7 fixes submitted; awaiting Codex re-audit. Week 29 blocked until accepted.

**Verified baseline (2026-06-10):**
- `test_week28_stabilization.py`: 22 passed
- Full backend suite: 709 passed, 0 failures
- `compileall apps/backend/aria`: exit 0
- `ARIAVoice.test.jsx`: 2 passed
- Frontend build: exit 0

**Round 7 findings addressed (all Codex re-audit findings from round 6):**

1. **[P1] Outside-root artifact read before rejection** — Root cause: `_snapshot_artifact(update.artifact_path)` ran before `_write_artifact_atomic()`, so an outside-root path's bytes were read before `ValueError` was raised. Fix: path confinement check (`_confined_path`) is now the very first filesystem operation in the inner block. It computes `confined_final` before any read or write. If the path escapes the root, `ValueError` is raised immediately and no file is ever read.

2. **[P1] Restoration failure leaves filesystem ahead of store** — Root cause: if `save_batch()` failed and `_restore_from_snapshot()` also failed, the newly written artifact remained on disk while the store stayed at `canary`. Fix: replaced snapshot/restore with a **staging path design**. New content is written to `confined_final.parent / (confined_final.name + ".next")` — a staging path in the same confined directory. The active artifact is never overwritten until `save_batch` succeeds. On any pre-commit failure, the staging file is deleted (best-effort) and the active artifact is untouched. No restoration step is needed; the inconsistency scenario is eliminated. After `save_batch` succeeds, `os.replace(staged_path, confined_final)` atomically promotes the staging file to the live path. Applied to both `promote_canary` and `rollback_update`.

3. **[P3] Checklist section 6 filter** — `-k "deployment_path or traversal"` selected only 2 of 3 path-confinement tests (`test_absolute_outside_deployment_root_rejected` was not matched). Fixed: filter updated to `-k "deployment_path or outside_deployment_root or traversal"` — now selects all 3 tests.

4. **[P3] Test module header** — Line 4 still said "Exactly 16 tests"; there are 22. Updated to "22 tests" with accurate item breakdown (16 core + 6 supplementary regression tests).

---

## Week 28 Stabilization — Round 6 Fixes (Closed by Round 7)

**Date**: 2026-06-10
**Status**: Round 6 fixes submitted; awaiting Codex re-audit. Week 29 blocked until accepted.

**Verified baseline (2026-06-10):**
- `test_week28_stabilization.py`: 22 passed
- Full backend suite: 709 passed, 0 failures
- `compileall apps/backend/aria`: exit 0
- `ARIAVoice.test.jsx`: 2 passed
- Frontend build: exit 0

**Round 6 findings addressed (all Codex re-audit findings from round 5):**

1. **[P1] Non-UTF-8 Artifact Deleted on save_batch Failure** — Root cause: `_backup_artifact` used `read_text(encoding="utf-8")` and returned `None` on BOTH conditions: file absent AND any decode/read failure. `_restore_artifact` interpreted `None` as "file was absent before write" and called `unlink()`. For non-UTF-8 binary files (e.g., UTF-16 content), this silently deleted the pre-existing file instead of restoring it. Fix: replaced `_backup_artifact`/`_restore_artifact` with a fail-closed `_ArtifactSnapshot` dataclass (frozen, fields: `path_str: str`, `existed: bool`, `data: Optional[bytes]`). `_snapshot_artifact(path_str)` reads raw bytes via `read_bytes()` (never `read_text`), raises immediately on any read failure (fail-closed — prevents the write from starting), returns `existed=True, data=<bytes>` for present files and `existed=False, data=None` for absent files. `_restore_from_snapshot` writes back `snapshot.data` as raw bytes via atomic tmp+replace, or calls `unlink(missing_ok=True)` if `existed=False`; raises on any failure (fail-closed, never swallows). Both `promote_canary` and `rollback_update` inner try blocks updated to use the new snapshot API.

2. **[P1 test] Non-UTF-8 Artifact Preserved** — New test `test_promote_canary_nonutf8_artifact_restored_on_save_batch_failure`: writes UTF-16 LE binary content (`b"\xff\xfe" + "Legacy binary artifact".encode("utf-16-le")`) to a temp file, mocks `save_batch` to raise `PersistenceError`, calls `promote_canary` (which writes new content then triggers the failure), verifies that the original non-UTF-8 bytes are restored exactly (not deleted, not corrupted).

3. **[P3] Checklist and documentation updated** — `WEEK28_STABILIZATION_ACCEPTANCE_CHECKLIST.md`: baseline updated to "at least 22 tests" / "at least 709 tests"; section 7 expected result updated from `3 passed` to `4 passed`; proof paths in sections 1, 3, 5, 6, 7 corrected from `aria/update_manager/` to `aria/evolution/update_manager/`. `CLAUDE.md` status line updated: 708 → 709 tests, 21 → 22 stabilization suite, Round 5 → Round 6 description.

---

## REBUILD CHECKLIST

To rebuild ARIA from scratch (learning exercise):

- [ ] Create blank folder
- [ ] Step 1: Write `aria/state.py` from memory — all fields, correct types
- [ ] Step 2: Write `aria/nodes/intake.py` — partial dict return, uuid, steps_completed
- [ ] Step 3: Write `aria/nodes/router.py` — keyword rules, append to steps_completed
- [ ] Step 4: Write `aria/nodes/respond.py` — label map, task_status=done
- [ ] Step 5: Write `aria/graph.py` — StateGraph, add_node, set_entry_point, add_edge, compile
- [ ] Step 6: Write `main.py` — initial state dict, invoke, print fields
- [ ] Run: `uv run python main.py` — verify TRAIL shows all 3 nodes
- [ ] Step 7: Write `aria/config.py` — dotenv, LangSmith env vars
- [ ] Step 8: Write `day2_lcel_test.py` — prompt | llm | parser, test 6 inputs
- [ ] Step 9: Update `aria/nodes/router.py` — Claude chain replaces keywords
- [ ] Run: `uv run python main.py` — verify Claude is now classifying
- [ ] Step 10: Write `aria/work_ledger.py` — JSONL append, log_task() called from respond
- [ ] Step 11: Write `aria/skills/skill_registry.py` — register(), get(), SkillMetadata dataclass
- [ ] Step 12: Write `aria/skills/kpi_skill.py` — KPIInput, KPIOutput, RootCauseHypothesis, run(), Eval-Lite
- [ ] Update `aria/nodes/skill_nodes.py` — register kpi skill, kpi_node calls real skill
- [ ] Run: `uv run python main.py` — verify kpi input shows full JSON output (not placeholder)
- [ ] Step 13: Write `aria/skills/pr_review_skill.py` — PRReviewInput, CodeIssue, PRReviewOutput, run(), Eval-Lite
- [ ] Step 14: Update `aria/nodes/skill_nodes.py` — register pr_review skill, pr_review_node calls real skill
- [ ] Run: `uv run python main.py` — verify pr_review input shows verdict + code_issues + deployment_risks
