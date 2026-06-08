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
