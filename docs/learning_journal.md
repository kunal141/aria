# ARIA Learning Journal

Track every concept learned, every experiment run, every insight gained. This journal is ARIA's own memory of how she was built.

---

## How to Use This Journal

After each learning session, add an entry:

```markdown
## Week X — [Topic]
**Date**: YYYY-MM-DD
**Resources**: [books, docs, courses, papers]
**Key Concepts**: bullet list of what you learned
**Experiments**: what you built or tried
**Insights**: non-obvious realizations
**Questions**: what remains unclear — revisit later
**Applied to ARIA**: where/how this learning shows up in the codebase
**Architecture Decision**: [optional — if a significant decision was made]
**Failure Log**: [optional — what didn't work and why]
**Capability Added**: [optional — which pillar got a new capability]
**Resume Bullet**: [draft a resume bullet for this week's work]
```

---

## Week 1 — Problem, Vision, Scope Freeze

**Date**: 2026-05-10
**Status**: ✅ Done

**Key Concepts**:
- AI Employee vs chatbot vs copilot: chatbots respond, copilots assist, AI Employees act
- Why enterprise AI needs orchestration + memory + governance — not just an LLM wrapper
- Workflow vs agent vs swarm: when to use each
- Orchestrator-first design: brain routes, specialists execute
- Scope freeze discipline: what's in V1, what's deferred

**Applied to ARIA**:
- Problem + solution statements written (`docs/problem_statement.md`, `docs/solution_statement.md`)
- V1 scope locked (`docs/v1_scope.md`): AI Engineer vertical is primary, Editorial AI is Vertical 2
- Architecture first sketch (`docs/architecture.md`)

**Resume Bullet**: Designed architecture for ARIA, a 23-pillar agentic AI platform — scoped V1 to AI Engineering use case with explicit deferral rationale

---

## Week 2 — Architecture & Capability Mapping

**Date**: 2026-05-10
**Status**: ✅ Done

**Key Concepts**:
- 23 capability pillars mapped from first principles + cross-referenced with industry benchmarks
- Governed self-evolution: the platform improves like an employee with 9 distinct evolution types
- Self-dogfooding: ARIA using herself to build herself creates irreplaceable operational corpus
- 7-layer moat: why this cannot be replicated in 4 weeks by a competitor
- Evolution Intelligence: ecosystem monitoring → proposal → sandbox → human approval → live

**Applied to ARIA**:
- Complete 30-week plan written (`docs/weekly_plan.md`)
- Governed self-evolution documented (`docs/evolution_intelligence.md`)
- Moat analysis written (`docs/moat_analysis.md`)
- Self-dogfooding protocol written (`docs/self_dogfooding.md`)
- 23 capability pillars mapped (`docs/capability_map.md`)
- Master plan viewer built (`apps/frontend/src/ARIAMasterPlan.jsx`)

**Resume Bullet**: Designed 7-layer competitive moat strategy for AI platform; documented governed self-evolution framework with 9 evolution types and full lifecycle

---

## Week 3 — LangGraph Foundation

**Date**: 2026-05-17
**Status**: ✅ Done

**Key Concepts**:
- LangGraph is a **state machine**, not a chatbot framework — state flows between nodes like items on an assembly line
- `TypedDict` + `Literal` = typed state contract; IDE catches `state["task_status"] = "completed"` before runtime does
- Nodes return **partial dicts** — LangGraph merges the returned keys back into the full state; you only write what you own
- `set_entry_point` + `add_edge` + END = the minimal graph wiring; `compile()` validates structure before any code runs
- `uuid.uuid4()` in intake = every task gets a unique identity — this becomes the primary key in the Work Ledger

**Experiments**:
- Built LangGraph skeleton with dummy keyword router — graph ran end-to-end on first attempt
- Built LCEL chain in isolation (`day2_lcel_test.py`) before wiring it into the graph
- Swapped keyword router for Claude LCEL chain — zero changes to any other file because state contract was fixed

**Insights**:
- Build with dummy logic first, swap in real logic second. Dummy router → Claude router was surgical because the state contract never changed. This is the whole point of typed state.
- `import aria.config` must be the **first import** in any file that uses LangChain — otherwise LangSmith env vars aren't set when the library initialises
- LCEL `|` pipe is function composition: `prompt | llm | parser` = `parser(llm(prompt(input)))`. The pipe just makes it readable and adds streaming/async for free

**Architecture Decision**: Backend lives at `apps/backend/` — renamed from the original `build/` folder (Week 13 restructure) to align with the monorepo convention (`apps/frontend` + `apps/backend`). All Weeks 3–12 code lives here.

**Failure Log**:
- LangSmith 401 errors cluttered output — `config.py` was setting `LANGCHAIN_TRACING_V2=true` unconditionally. Fixed by gating on `LANGCHAIN_API_KEY` presence.
- Windows Unicode crash — fixed with `sys.stdout.reconfigure(encoding="utf-8")` at top of `main.py`

**Capability Added**: Pillar 1 (Conversational Tasking) — task intake + routing working end-to-end

**Resume Bullet**: Built LangGraph StateGraph orchestration backbone with typed state contracts, LCEL Claude router, and graceful API key degradation — graph routes 5 task types end-to-end

---

## Week 4 — Conditional Edges + Work Ledger Seed

**Date**: 2026-05-24
**Status**: ✅ Done

**Key Concepts**:
- `add_conditional_edges(node, fn, mapping)` — after a node, call `fn(state)` and use its return value to pick the next node. This is how one router fans out to many skill nodes.
- The routing function returns a **string** (node name) — LangGraph looks it up in the mapping dict
- Work Ledger starts as a simple JSONL append log — every task gets `{task_id, task_type, routing_reason, timestamp}` written immediately after respond. This is Pillar 16 seed.
- Why JSONL and not a database? Append-only, zero dependencies, human-readable, trivially parseable — the right choice for Week 4. Postgres/pgvector comes at Week 11.

**Experiments**:
- Replaced fixed `router → respond` edge with `add_conditional_edges` — graph now fans to 5 skill nodes
- Each skill node is a placeholder with a week label — `[Week 19] CI/CD skill will analyse: '...'`
- Work Ledger verified: `work_ledger.jsonl` gets a new line on every `python main.py` run

**Insights**:
- Placeholder nodes with explicit week labels are not dead code — they are honest contracts. The graph knows the skill doesn't exist yet; so does the reader.
- `routing_reason` written to the Work Ledger from Day 1 is critical. By Week 29, 25 weeks of routing decisions become a training signal for model routing optimisation.
- The respond node checks `skill_output.startswith("[Week")` to detect placeholder vs real skill — simple, works, no magic.

**Architecture Decision**: Work Ledger logs from respond node (not from skill nodes) — every task gets logged regardless of which skill ran, including placeholders

**Capability Added**: Pillar 16 (AI Work Ledger) seed — event log running from Week 4

**Resume Bullet**: Implemented conditional edge routing in LangGraph (1 router → 5 skill branches) and seeded the AI Work Ledger JSONL event log that will accumulate 25 weeks of task data

---

## Week 5 — (Context Engineering — Learning week)

**Date**: 2026-05-31
**Status**: 📖 Learning week — no new build files

**Key Concepts**:
- Context window = working memory. What goes in the window determines what the LLM can reason about.
- Three layers: **working memory** (this task's state), **retrieved memory** (RAG), **compressed memory** (summarised history)
- Token budget discipline: every node should have a budget. A node that doesn't control its input size will eventually fail silently or hallucinate from overflow.
- What to send vs what to store: send the minimum context needed for THIS step, not everything ARIA knows
- Summarisation before passing: long skill outputs get summarised before entering the next node's context

**Applied to ARIA**:
- KPI skill prompt is scoped to Amar Ujala domain context only — not generic analytics advice
- PR review prompt is scoped to Amar Ujala's media-tech systems — CMS, recommendation, notification, analytics
- State fields are typed and bounded — `raw_input` is the only open-ended field; everything else is controlled

**Resume Bullet**: Applied context engineering principles to all ARIA skill prompts — domain-scoped system prompts, bounded state fields, and output schemas that prevent context bloat

---

## Week 6 — Skill Registry + KPI Investigation Skill

**Date**: 2026-06-04
**Status**: ✅ Done

**Key Concepts**:
- **Skill Registry** = named lookup table: `register(name, fn, version, tier)` → `get(name).fn(input)`. Decouples skill discovery from skill execution — the node doesn't import the skill file directly.
- **Pydantic input/output schemas** = the contract. `KPIInput`, `KPIOutput`, `RootCauseHypothesis`. If a field is wrong, Pydantic raises before Claude is ever called.
- **Action tiers**: Tier 2 = Recommend — ARIA can propose but not act. Every skill is registered with its tier.
- **Eval-Lite** is mandatory from Week 6: 5 golden examples + 3 failure cases + 1–5 rubric per skill. Ships with the skill, not after.
- **Mock mode pattern**: if no API key, return a plausible mock output. Lets the graph run in any environment.
- `model_dump_json(indent=2)` serialises the Pydantic output to a formatted JSON string — this is what `skill_output` carries through state

**Experiments**:
- `kpi_skill.py` runs in mock mode (no key) and produces full `KPIOutput` JSON
- Registered in skill registry under name `"kpi"`, version `"v1"`, `action_tier=2`
- `kpi_node` in `skill_nodes.py` calls registry → calls skill → returns serialised output to state

**Insights**:
- The skill registry is not over-engineering — it's what makes Week 29 fine-tuning possible. You can't swap a skill for a fine-tuned version if the skill is hardcoded into the node.
- `confidence_score=0.0` in mock mode is honest — ARIA doesn't pretend to be confident when she has no data.
- Eval-Lite at ship time forces you to think about failure modes before writing the skill, not after.

**Architecture Decision**: Every skill output is `result.model_dump_json(indent=2)` stored in `skill_output` state field — consistent serialisation across all skills, easy to parse or log

**Capability Added**: Pillar 3 (Data Science & Analytics) seed — KPI investigation skill live with media-specific context

**Resume Bullet**: Built ARIA's first real skill — KPI Investigation with typed Pydantic contracts, Skill Registry with version + action tier metadata, and Eval-Lite rubric (5 golden examples, 3 failure cases)

---

## Week 7 — PR Review Skill

**Date**: 2026-06-04
**Status**: ✅ Done

**Key Concepts**:
- **PRReviewOutput** is richer than KPIOutput — it has nested `CodeIssue` models, each with `severity` + `category` + `description` + `suggestion`. Nested Pydantic models work exactly like flat ones.
- **verdict** + **risk_level** together determine the action: `approve + low` = merge. `request_changes + high` = block. `needs_discussion + medium` = async review.
- **business_impact** field links the code change to a metric (CTR, notification open rate) — this is what makes the review valuable to a media org, not just a generic code linter.
- Optional fields on input (`diff`, `pr_title`) — Claude uses them if present, ignores them if not. Same skill, richer output when more context is provided.
- **Positive observations** — every review surfaces what was done well, not just issues. This is important for team morale and for training data quality (approvals are as signal-rich as rejections).

**Experiments**:
- `pr_review_skill.py` mock output has 2 `CodeIssue` objects, 3 `missing_tests`, 2 `deployment_risks`, and a quantified `business_impact`
- Skill registered as `"pr_review"`, version `"v1"`, `action_tier=2`
- `pr_review_node` follows identical pattern to `kpi_node` — 10 lines, registry lookup + skill call

**Insights**:
- The node pattern is now a template: `get(name).fn(InputModel(...))` → `model_dump_json(indent=2)`. Every future skill (ci_cd, jira) will follow this exactly. The pattern is locked.
- Missing tests field is the most actionable part of a PR review — not "add more tests" but specific: "Unit test: recommendation returns empty list when no candidates pass threshold"
- Deployment risks tied to the org's actual systems (recommendation ranking → CTR) make the review feel like it was written by someone who knows the platform

**Architecture Decision**: `pr_review_node` follows the same 10-line pattern as `kpi_node` — no custom logic, just registry lookup + typed call. This pattern is now the canonical skill node template.


**Capability Added**: Pillar 2 (AI Engineering) — PR Review skill live with verdict, risk, code issues, missing tests, deployment risks, business impact

**Resume Bullet**: Built PR Review skill for media-tech codebase — typed Pydantic contracts with nested CodeIssue models, deployment risk scoring, and business impact assessment linked to CTR/notification metrics

---

## Week 8 — Artifact Engine

**Date**: 2026-06-04
**Status**: ✅ Done

**Key Concepts**:
- An **artifact** is a formatted, shareable output — not a raw JSON blob. The difference is intent: JSON is for machines, artifacts are for humans (developers, managers, Jira, Slack).
- The artifact engine is a pure function: `render_artifact(task_type, skill_output, task_id) → str`. It takes the serialised Pydantic JSON and outputs a formatted card.
- **Separation of concerns**: skills produce typed data, the engine formats it. Skills don't know how they'll be displayed. The engine doesn't know how skills work. Clean boundary.
- `json.loads(skill_output)` inside the engine — the engine deserialises what the skill serialised. The `str` round-trip (skill → state → engine) is intentional: state fields are always strings, never live Pydantic objects.
- **Graceful degradation**: if `skill_output` starts with `[Week`, it's a placeholder — render plain. If JSON parse fails — render plain. Engine never crashes.
- Box-drawing characters (`┌─┐│└`) make terminal output scannable at a glance — verdict at the top, issues in the middle, positive observations at the bottom. Same information hierarchy a human code reviewer would use.

**Experiments**:
- `artifact_engine.py` — `_render_pr_review()` and `_render_kpi()` render full box-card artifacts
- `respond.py` now calls `render_artifact()` when a real skill ran — formatted card replaces raw JSON
- Confidence score rendered as a filled bar: `[████░░░░░░] 40%` — visual, glanceable
- Severity icons: 🔴 critical / 🟠 high / 🟡 medium / 🟢 low — instant colour-coded triage

**Insights**:
- The artifact engine is where **Pillar 7 (Reporting & Communication)** starts. Raw JSON is not a report. A report has a hierarchy, an audience, and a clear recommended action at the top.
- Future artifact types can be added without touching respond.py — just add a new `elif task_type == "ci_cd"` renderer. Open for extension, closed for modification.
- The `positive_observations` section in PR review artifacts is not cosmetic — it's signal for the fine-tuning data pipeline. Approved outputs (with positives) are as valuable as flagged outputs (with issues).

**Architecture Decision**: Artifact engine is a module (`aria/artifact_engine.py`), not a method on the skill class — because formatting is a concern of the *presentation layer*, not the *skill layer*. This keeps skills testable independently of their rendered output.

**Capability Added**: Pillar 7 (Reporting & Communication) — artifact engine v1 live; PR Review and KPI skills now produce formatted, shareable output cards

**Resume Bullet**: Built ARIA's artifact engine converting typed Pydantic skill output into formatted terminal cards — verdict badges, severity-coded issue lists, confidence bars, and business impact sections

---

## Week 9 — Knowledge Retrieval Layer (RAG)

**Date**: 2026-06-05
**Status**: ✅ Done

**Key Concepts**:
- **Embeddings** = turning text into a vector (list of numbers) that captures meaning. Similar sentences → nearby vectors. Chroma stores these vectors and finds the nearest ones at query time.
- **Chunking** = splitting long docs into overlapping pieces so the retriever returns focused passages, not entire files. Overlap (80 words) ensures a thought split across a chunk boundary is still findable.
- **Cosine distance** = how different two vectors are. 0.0 = identical meaning, 1.0 = opposite. A distance of <0.45 is "relevant" for our corpus.
- **HyDE (Hypothetical Document Embeddings)**: instead of embedding the query, ask an LLM to write a hypothetical answer and embed THAT. The hypothetical answer looks more like real documents in the corpus → better retrieval. In the strategy comparison, HyDE got `dist=0.381` vs Basic RAG's `dist=0.432` — measurably better.
- **Self-RAG**: retrieve → check if chunks are actually relevant → if not, retry with a refined strategy. Acts as a quality gate on retrieval output.
- **Adaptive RAG**: heuristic strategy selector — specific queries → Basic RAG, vague/open queries → HyDE, high-stakes (contains "risk", "recommend", "best") → Self-RAG. Every query gets the right tool.
- `all-MiniLM-L6-v2` — 80MB sentence-transformers model, runs entirely locally, no API key, 384-dim embeddings. This is the standard learning-phase embedding model.

**Experiments**:
- Ingested 2 Amar Ujala seed docs → 4 chunks stored in Chroma
- All 4 test queries retrieved correct source (KPI queries → kpi_runbook, PR queries → pr_guidelines)
- HyDE mock mode: even without Claude key, hypothetical doc prefix improved retrieval distance from 0.432 → 0.381
- `format_context()` bug found and fixed: was skipping chunks larger than budget instead of truncating them
- chromadb/numpy compatibility bug patched: `np.float_` → `np.float64` in chromadb's `types.py`

**Insights**:
- The retrieval is semantically correct without any fine-tuning — "CTR drop" → kpi_runbook, "PR review" → pr_guidelines. This is the power of pre-trained embeddings on generic text.
- Chroma is in-memory for Week 9 (resets on restart). This is intentional — the learning goal is retrieval mechanics. Persistence comes at Week 11 when we migrate to pgvector + Postgres.
- `format_context()` is the context engineering step for RAG: it decides how much retrieved text to inject, respects the token budget, and formats it as a labelled block. Without this, you'd dump raw chunks into the prompt.
- The `ingest_text()` function uses `upsert` not `insert` — idempotent. Running the script twice doesn't duplicate chunks. The doc ID is an MD5 hash of `source::chunk_index`.

**Architecture Decision**: Knowledge module lives in `aria/knowledge/` (not in `aria/nodes/`) — retrieval is a capability, not a graph node. Skills call it as a library, not as a step in the pipeline. This keeps the graph clean and makes retrieval testable in isolation.

**Failure Log**: chromadb 0.4.21 (the version uv installed) uses `np.float_` which was removed in NumPy 2.0. Fixed by patching the chromadb source file in the venv directly — one line change. Note: this patch will be lost if chromadb is reinstalled.

**Capability Added**: Pillar 8 (Knowledge / RAG / Org Intelligence) — retrieval layer v1 live with Basic RAG + HyDE + Self-RAG + Adaptive RAG, seeded with Amar Ujala domain documents

**Resume Bullet**: Built RAG knowledge retrieval layer with three strategies (Basic RAG, HyDE, Self-RAG) and adaptive selection — Chroma in-memory vector store, sentence-transformers embeddings, Amar Ujala-specific seed corpus

---

## Week 10 — Code Intelligence Layer

**Date**: 2026-06-05
**Status**: ✅ Done

**Key Concepts**:
- **AST (Abstract Syntax Tree)**: Python's stdlib `ast` module parses source code into a tree of nodes — `FunctionDef`, `ClassDef`, `Import`, etc. — without executing the code. This lets ARIA understand code structure without running it.
- **Code chunking vs text chunking**: text splits by word count; code splits by function/class boundary. Each function is a natural semantic unit. The chunk for `kpi_node` is: file path + function signature + docstring + source body — everything you need to understand that symbol.
- **Dependency graph**: parse every `import` statement across all files → `{module: [modules_it_imports]}`. This shows which files depend on which — critical for impact analysis ("if I change `state.py`, which files are affected?").
- **Code Q&A via embeddings**: function source code embeds semantically. "where is the kpi skill run function defined?" → retrieves `kpi_node` from `skill_nodes.py` and `KPIInput` from `kpi_skill.py`. The embeddings understand that "kpi skill" maps to `kpi_skill.py`.
- **Self-dogfooding**: ARIA indexed her own 20 source files, 46 functions, and 12 classes. She can now answer questions about herself. This is the corpus that no competitor can replicate.

**Experiments**:
- Parsed `kpi_skill.py`: found 1 function (`run`), 3 classes (`KPIInput`, `RootCauseHypothesis`, `KPIOutput`), 6 imports
- Dependency graph: `graph.py` imports `aria.nodes.intake`, `aria.nodes.respond`, `aria.nodes.router`, `aria.nodes.skill_nodes`, `aria.state` — exactly correct
- Ingested 20 files → 58 total chunks in Chroma (4 seed docs + 54 code chunks)
- "how does the skill registry register a skill?" → retrieved `register()` from `skill_registry.py` with dist=0.536, strategy=HyDE — semantically correct

**Insights**:
- The dependency graph is free — pure stdlib `ast`, no external packages. It produces the same information a senior engineer would sketch on a whiteboard in 10 minutes.
- Code Q&A accuracy is already good for exact function lookups but weaker for semantic questions ("what does the respond node do?"). This is expected — the embedding model (`all-MiniLM-L6-v2`) is general-purpose, not code-specialised. Week 25 vLLM + code model will improve this significantly.
- `ingest_repo()` uses `upsert` — so running it twice on the same codebase is idempotent. When ARIA's code changes, the next ingest updates the changed chunks only.
- The module name extraction from file path is an approximation — works well within the `aria/` package, less clean for absolute paths. Good enough for Week 10.

**Architecture Decision**: Code intelligence shares the same Chroma collection as document knowledge — chunks are tagged with `doc_type="code"` vs `"runbook"` / `"guidelines"`. This allows mixed retrieval (pull both docs and code for a query) and avoids managing two separate vector stores at this stage.

**Capability Added**: Pillar 9 (Code Intelligence) — AST parsing, dependency graph, code ingestion, repo Q&A all live. Self-dogfooding corpus starts accumulating.

**Resume Bullet**: Built code intelligence layer using Python AST — function/class extraction, dependency graph across 20 modules, code-aware chunking ingested into Chroma vector store enabling natural-language repo Q&A

---

## Week 11 — Memory Fabric v1

**Date**: 2026-06-05
**Status**: ✅ Done

**Key Concepts**:
- **MemGPT/Letta three-tier pattern**: Hot memory = ARIAState in context right now. Warm memory = JSON-backed store, fast lookup. Cold memory = Chroma, needs semantic search to retrieve. Most AI systems only have one tier — ARIA has all three.
- **Memory types and when to use each**:
  - `SessionMemory` — ephemeral, cleared at session end (or promoted to cold). Tracks what happened in this conversation.
  - `TaskMemory` — permanent, linked to `task_id`. What did the skill produce? What was the verdict?
  - `UserMemory` — never cleared, confidence score increases as pattern repeats. This is the Human Teaching Layer seed (Pillar 17).
  - `OutcomeMemory` — approved/rejected + correction. Every rejection is a DPO training pair for Week 29.
- **Context injection**: `memory.recall_for_skill("pr_review")` returns relevant user preferences and past outcomes, formatted as a `--- USER CONTEXT ---` block that gets prepended to the skill's system prompt. The next PR review call will know Kunal's team always uses feature flags.
- **Session lifecycle**: `end_session(promote_to_cold=True)` ingests session events into Chroma before clearing warm store. Session memories are short-lived in warm tier but permanent in cold — no information is lost.
- **Idempotency**: `store.write()` uses `memory_id` as the upsert key — writing the same record twice is safe.

**Experiments**:
- Wrote 10 memory records (3 session, 2 task, 3 user, 2 outcome) — all verified in `memory_store.json`
- `recall_for_skill("pr_review")` returned 2 user preferences + 1 outcome → formatted context block
- Session end: cleared 3 session memories from warm, promoted to Chroma cold store — 7 records remain (task + user + outcome)
- The first `memory_store.json` record has correct ISO 8601 timestamp, UUID, typed fields

**Insights**:
- The rejected KPI outcome has a `correction` field: "Root causes should mention A/B test holdout group drift". This is exactly the training signal for fine-tuning — ARIA's output vs Kunal's correction = a preference pair.
- User preference confidence scores are designed to increase on repetition — if Kunal corrects the same thing 3 times, confidence reaches 0.95+ and it becomes a near-certain rule.
- File-backed JSON is the right choice for Week 11. SQLite or Postgres adds friction during the learning phase. The migration path is explicit: swap `store.py` for a DB-backed version at Week 12 when we need SQL filters and ACID writes.
- `format_for_prompt()` respects a character budget (600 chars). If user has 50 preferences, it won't dump all 50 into the prompt — it takes the most relevant ones that fit the budget.

**Architecture Decision**: Memory manager is a singleton (`memory = MemoryManager()`) imported at the module level — same instance used by all skills in a process. For multi-process or async deployment, this becomes a shared Redis/Postgres-backed store. The interface doesn't change.

**Capability Added**: Pillar 17 (Human Teaching Layer) seed — UserMemory with correction tracking. Pillar 16 (AI Work Ledger) extended — OutcomeMemory is the approve/reject log. Memory fabric v1 live.

**Resume Bullet**: Built three-tier memory fabric (MemGPT pattern) — session/task/user/outcome memory types, JSON warm store, session-to-Chroma cold promotion, context injection pipeline for skill enrichment

---

## Week 12 — Institutional & Outcome Memory

**Date**: 2026-06-05
**Status**: ✅ Done

**Key Concepts**:
- **Decision memory**: every architectural choice gets logged with decision, rationale, alternatives considered, and outcome. This is ARIA's institutional knowledge — "why did we choose Chroma over FAISS?" is answerable from memory, not from reading code.
- **Artifact memory**: every skill output is stored permanently linked to its `task_id`. `get_artifact(task_id)` retrieves any output ARIA ever produced — the foundation for the Work Ledger ROI dashboard at Week 29.
- **Outcome querying as fine-tuning pipeline**: `query_outcomes(approved=True)` returns positive training examples. `query_outcomes(approved=False)` returns DPO pairs (ARIA's output + Kunal's correction). By Week 29, this is a ready-made dataset for LoRA fine-tuning.
- **Semantic memory search**: session memories promoted to Chroma cold store are searchable by meaning. "which vector store did we choose?" retrieves the archived session event about choosing Chroma over FAISS — even though the exact words don't match.
- **ROI snapshot**: `roi_snapshot()` returns `{total_artifacts, approved, rejected, approval_rate, by_skill}`. This is the seed of the Work Ledger dashboard — at Week 29, 25 weeks of data will make this a full ROI report.

**Experiments**:
- 3 decision records written — Week 6 (skill registry), Week 9 (Chroma choice), Week 11 (JSON store)
- `get_artifact("task-pr-001")` correctly retrieved the PR review artifact
- Outcome query: 2 approved, 1 rejected (with correction about A/B holdout group)
- Semantic search found the archived session event about Chroma with `dist=0.731` — cold tier search working
- ROI snapshot: 2 artifacts, 3 outcomes, 67% approval rate, split by skill

**Insights**:
- The `correction` field on rejected outcomes is the most valuable piece of data ARIA collects. "Should have flagged A/B holdout group drift" — this is a specific improvement signal that goes directly into fine-tuning. Generic rejections ("this is wrong") are worth little; specific corrections ("the root cause was X, not Y") are gold.
- Decision memory accumulates silently. By Week 30, every non-obvious architectural choice will be logged with its rationale. When a new engineer joins and asks "why did we do this?", ARIA can answer from memory.
- `roi_snapshot()` at Week 12 shows 2 artifacts and 67% approval. At Week 29, it will show hundreds of artifacts across 6 months — the number that convinces a manager this is real work, not a demo.
- Semantic memory search across cold store (Chroma) completes the three-tier loop: Hot (state) → Warm (JSON) → Cold (Chroma). Any memory written to warm can be found semantically from cold after session promotion.

**Architecture Decision**: `store_artifact()` stores the full artifact content in `artifact_content` field — not a file path. This keeps the warm store self-contained and avoids file management complexity. For large artifacts (Week 14+ eval reports), we'll truncate to first 2000 chars and store the full content to disk with a pointer.

**Capability Added**: Pillar 16 (AI Work Ledger) — artifact memory + ROI snapshot live. Pillar 17 (Human Teaching Layer) — outcome querying pipeline ready. Decision memory is the institutional memory moat layer.

**Resume Bullet**: Built institutional memory layer — decision records with alternatives + rationale, artifact-task linkage, outcome querying pipeline (approved/rejected filtering for DPO fine-tuning), and Work Ledger ROI snapshot

---

## Upcoming Topics (Full 30-Week Curriculum)

### Phase 1 — Foundations (Weeks 3–4)

| Week | Topic | Learn | Build | Key Output |
|---|---|---|---|---|
| 3 | LangGraph Foundation | Nodes, edges, TypedDict state, durable execution, human-in-the-loop, checkpointers | Repo structure, frontend + backend shell, LangGraph skeleton | Core codebase initialized, first graph runs |
| 4 | Task Intake & Orchestrator v1 | Task lifecycle design, state machine thinking, task object schema, ReAct reasoning loop | Task intake flow, task schema, orchestrator v1, routing + state transitions | Task orchestration v1 live |

**Techniques to implement**:
- **ReAct** (Week 4) → Built into orchestrator reasoning loop: Think → Act → Observe → Reflect
- **Chain of Thought** (Week 4) → Skill execution planning: before calling a skill, ARIA plans steps

---

### Phase 2 — AI Engineer Core (Weeks 5–9)

| Week | Topic | Learn | Build | Key Output |
|---|---|---|---|---|
| 5 | Context Engineering | What to send vs store vs summarize; working vs long-term memory; reduce context bloat | Context strategy, memory injection points, artifact context design | Context design v1 — prevents 10 common LLM mistakes |
| 6 | Skill Registry + KPI Skill | Reusable skill design, typed input/output schemas, LLM vs deterministic logic | Skill registry v1, KPI investigation skill, skill metadata model | First real skill live |
| 7 | PR Review Skill + Teams Bot | PR review patterns, business context awareness, risk articulation, Teams bot architecture | PR review skill + workflow, Teams bot live | PR review v1, @mention ARIA works |
| 8 | Artifact Generation Layer | Enterprise artifact design, audience-aware outputs, converting findings to work products | Report generator, PR note, summary artifact, email/brief templates | Artifact engine v1 |
| 9 | Knowledge Retrieval Layer | Retrieval basics, embeddings + chunking, metadata filters, grounding | Doc/SOP retrieval, knowledge source ingestion, retrieval API | Knowledge retrieval v1 |

**Techniques to implement**:
- **HyDE** (Week 9) → Enhanced retrieval: generate hypothetical document, embed it, search against real docs
- **Self-RAG** (Week 9) → ARIA critiques her own retrieval: "Is this relevant? Retrieve again if not"
- **Adaptive RAG** (Week 9) → Dynamically choose retrieval strategy based on query type

---

### Phase 3 — Intelligence + Analytics (Weeks 10–13)

| Week | Topic | Learn | Build | Key Output |
|---|---|---|---|---|
| 10 | Code Intelligence Layer | Code chunking, AST basics, dependency graph, repo-aware reasoning | Repo connector, code indexing pipeline, PR metadata ingestion | Code understanding v1 |
| 11 | Memory Fabric v1 | Session/user/team/task memory schemas, when to update memory | Session memory, task memory, user preference memory, memory API | Memory fabric v1 |
| 12 | Institutional & Outcome Memory | Decision memory, artifact memory, outcome memory, institutional memory | Outcome memory model, artifact-task linkage, decision memory layer | Institutional memory v2 |
| 13 | LangSmith Tracing + Teams Identity | Trace debugging, agent observability, Teams bot identity | Trace integration, skill trace logging, orchestrator trace, ARIA persona in Teams | Traceability v1 + ARIA present in workplace |

**Techniques to implement**:
- **MemGPT/Letta patterns** (Week 11) → Memory paging: hot memory (context) + warm (retrieval) + cold (archived)
- **Tree of Thoughts** (Week 11) → Multi-path task decomposition when outcome is uncertain

---

### Phase 4 — Agent Factory + Control Plane (Weeks 14–18)

| Week | Topic | Learn | Build | Key Output |
|---|---|---|---|---|
| 14 | Evaluation Design + Eval Harness | Benchmark tasks, golden examples, human review rubrics, regression testing, Constitutional AI | Eval harness v1, benchmark datasets, 5 skill rubrics, regression checks | Eval harness v1 — baseline scores established |
| 15 | Governance Layer | RBAC concepts, approval systems, auditability | Approval engine, role-permission matrix, audit log | Governance v1 |
| 16 | Controlled Autonomy | Action tiers in practice, confidence + escalation, safe autonomy | Draft/send/trigger action layer, risk scoring, approval-aware execution | Controlled action layer |
| 17 | QA / Test Case Generation | Functional test design, negative + edge cases, requirement-to-test mapping, workforce orchestration | Test case generation skill, QA artifact templates, sub-agent spawning | QA skill v1 + workforce orchestration |
| 18 | Test Review & Evolution Monitoring | Coverage review, regression risk, failed test analysis, AI ecosystem monitoring setup | Test review skill, failed test summary, coverage gap detection, Evolution Intelligence monitoring | QA skill v2 + daily AI digest |

**Techniques to implement**:
- **Constitutional AI** (Week 14) → Output safety checks in eval harness; later used in self-integration safety checks
- **CrewAI patterns** (Week 17) → Multi-agent coordination design reference for workforce orchestration
- **AutoGen patterns** (Week 17) → Conversational agent protocol for sub-agent communication

---

### Phase 5 — Knowledge + Workflow + Jira (Weeks 19–22)

| Week | Topic | Learn | Build | Key Output |
|---|---|---|---|---|
| 19 | CI/CD Intelligence | CI/CD lifecycle, release readiness, failure triage | CI/CD failure skill, release readiness skill, deployment artifact | CI/CD capability v1 |
| 20 | Jira / Delivery Intelligence | Story decomposition, acceptance criteria, backlog + blocker handling | Jira creation + refinement skill, blocker/sprint summary | Jira/Delivery v1 |
| 21 | Agent Runtime Harness + DSPy | Retries + backoff, timeout handling, idempotency, resumability, DSPy prompt optimization, Instructor, Outlines | Runtime harness, execution guardrails, retry policies, prompt optimizer, structured output enforcement | Runtime harness v1 + prompt engineering depth |
| 22 | Agent Factory + Workflow Mining | Skill vs agent vs workflow, capability lifecycle, sandboxing, repeated task detection | Capability request flow, agent/skill classifier, scaffold generator, capability registry, workflow mining | Agent Factory v1 + automation backlog |

**Techniques to implement**:
- **DSPy** (Week 21) → Systematic prompt optimization: define metric, compile to optimized prompts
- **Instructor** (Week 21) → Structured output enforcement: every skill output is validated Pydantic model
- **Outlines / Guidance** (Week 21) → Constrained generation for structured outputs
- **RAPTOR** (Week 22) → Hierarchical document summarization for long organizational docs
- **GraphRAG** (Week 22) → Knowledge graph retrieval for org intelligence

---

### Phase 6 — Intelligence Depth + Decision Layer (Weeks 23–25)

| Week | Topic | Learn | Build | Key Output |
|---|---|---|---|---|
| 23 | Schema/Protocol + Evolution Layer Design | Task schema design, skill + artifact schemas, MCP deeper, A2A basics, evolution layer architecture | Schema library, evolution layer draft, capability proposal flow | Protocol + evolution v1 |
| 24 | Decision Intelligence | Option ranking, LATS (Language Agent Tree Search), escalation decision engine, next-best-action | Next-best-action recommendation, option ranker, escalation engine | Decision intelligence v1 |
| 25 | Fine-Tuning + vLLM + Intelligent Model Routing | LoRA/QLoRA fine-tuning, Unsloth, TRL SFTTrainer, DPO preference alignment, vLLM inference serving, model cost routing | Fine-tuning pipeline (prepare_dataset → train_lora → eval → serve), vLLM local server, intelligent model router | ARIA-PR-Reviewer-7B live; PR tasks route to local model; measurable API cost savings |

**Techniques to implement**:
- **LATS** (Week 24) → Agent tree search for multi-step decision exploration
- **LoRA/QLoRA** (Week 25) → Fine-tune Qwen2.5-Coder-7B on Work Ledger PR review data
- **DPO** (Week 25) → Preference alignment from Work Ledger approval/rejection pairs
- **Unsloth** (Week 25) → Memory-efficient LoRA training — fits on RTX 4090 or RunPod A40
- **vLLM** (Week 25) → Serve fine-tuned model locally with OpenAI-compatible API
- **MetaGPT / SWE-agent patterns** (Week 23) → AI Engineering sub-agent design reference

---

### Phase 7 — Self-Evolution + Marketplace (Weeks 26–28)

| Week | Topic | Learn | Build | Key Output |
|---|---|---|---|---|
| 26 | Analytics Depth + Data Science | Experiment analysis, A/B test interpretation, advanced anomaly detection, workflow bottleneck analysis | EDA skill v2, experiment analysis, data pipeline intelligence | Analytics depth v2 |
| 27 | Evolution Intelligence — Evaluate & Propose | Reading papers in depth, capability gap analysis, structured proposal writing, sandboxed self-integration | Capability proposal engine, self-integration pipeline (design → code → test → sandbox → propose) | First real capability proposal from arxiv |
| 28 | Evolution Intelligence — Integrate + Marketplace | Approved self-integration, Constitutional AI safety check on proposed code, marketplace design, adoption tracking | Self-integration of approved capability, marketplace UI, skill catalog, team adoption tracking | End-to-end self-evolution loop proven |

**Techniques to implement**:
- **LATS** used in Evolution Intelligence evaluation: tree search over capability options
- All RAG variants (HyDE, Self-RAG, RAPTOR, GraphRAG) combined in unified knowledge retrieval

---

### Phase 8 — Work Ledger + AaS (Week 29)

| Week | Topic | Learn | Build | Key Output |
|---|---|---|---|---|
| 29 | AI Work Ledger Complete + ROI Dashboard + AaS Foundations | ROI measurement methodology, multi-tenant patterns, SaaS architecture, business case construction | AI Work Ledger all 10 record types, ROI dashboard, AaS foundations (multi-tenant, governance console, usage tracking) | ARIA can prove: "I completed X tasks, saved Y hours, improved Z metric" |

---

### Phase 9 — Launch (Week 30)

| Week | Build | Output |
|---|---|---|
| 30 | Final polish, demo video, LinkedIn post (ARIA helps draft it), internal presentation, GitHub repo preparation | Public launch: surprise reveal to manager. LinkedIn post live. The world sees what one person built in 30 weeks. |

---

## Full Learning Curriculum Reference

Every technique gets implemented inside ARIA — not just studied:

| Technique | Week | Implemented As | Pillar |
|---|---|---|---|
| ReAct | 4 | Core orchestrator reasoning loop | 1, 11 |
| Chain of Thought | 4 | Skill execution planning step | 1 |
| Tree of Thoughts | 11 | Multi-path task decomposition | 1, 20 |
| MemGPT/Letta patterns | 11 | Memory paging + consolidation architecture | 4 (memory) |
| HyDE | 9 | Enhanced retrieval for org docs | 8 |
| Self-RAG | 9 | ARIA critiques her own retrieval | 8 |
| Adaptive RAG | 9 | Dynamic retrieval strategy | 8 |
| RAPTOR | 22 | Long document hierarchical summarization | 8 |
| GraphRAG | 22 | Knowledge graph retrieval | 8 |
| CrewAI patterns | 17 | Multi-agent coordination design reference | 14 |
| AutoGen patterns | 17 | Sub-agent conversational protocol | 14 |
| MetaGPT / SWE-agent | 23 | AI Engineering sub-agent design | 2 |
| Constitutional AI | 14 + 28 | Eval harness safety + self-integration safety | 10, 18 |
| DSPy | 21 | Systematic prompt optimization | 18 |
| Instructor | 21 | Structured output enforcement on all skills | 1–23 |
| Outlines / Guidance | 21 | Constrained generation | 1–23 |
| LATS | 24 | Agent tree search for decisions + evolution | 20 |
| LangSmith evals | 13 | Rubric + regression framework | 12 |
| LoRA / QLoRA fine-tuning | 25 | Fine-tune Qwen2.5-Coder-7B on Work Ledger outputs | 16, 21 |
| DPO | 25 | Preference alignment from approve/reject Work Ledger pairs | 17, 21 |
| Unsloth | 25 | Memory-efficient LoRA training | 16 |
| vLLM | 25 | Serve fine-tuned model via OpenAI-compatible API | 21 |
| A2A protocol | 23+ | Evolution tracking + future agent interoperability | 23 |
| MCP | Throughout | Tool standardization for all external integrations | All |

---

## Weekly Maintenance Discipline

Every week produces 6 mandatory artifacts. Complete these before moving to the next week. They are your career moat — not a checkbox exercise.

```markdown
## Week X — Maintenance Log

### Artifact 1 — Learning Notes
- What I learned this week (concepts, techniques, mental models):
  - 
- What's still unclear (questions to revisit):
  - 

### Artifact 2 — Architecture Decision Log
For each significant design choice made this week:
| Decision | Alternatives Considered | Tradeoff | Why This Choice |
|---|---|---|---|
|  |  |  |  |

### Artifact 3 — Failure Log
| What Broke | Root Cause | How Fixed | What I'd Do Differently |
|---|---|---|---|
|  |  |  |  |

### Artifact 4 — Capability Log
- Which pillar(s) advanced this week:
- What ARIA can do now that she couldn't last week:
- Skill version delta (e.g., PR Review v1 → v1.1):

### Artifact 5 — Demo Snapshot
- [ ] Screenshot or terminal output captured
- What the output proves (one sentence):
- Link to output file / screenshot:

### Artifact 6 — Resume Bullet Draft
Write one polished bullet for CV/LinkedIn — write it NOW, while the work is fresh:
> [Action verb] [what you built] using [technologies], enabling [outcome/capability] — [quantify if possible]

---

### Self-Dogfooding Log (Week 8+)
- PRs reviewed by ARIA: [N]
- Comments accepted: [N] ([%] acceptance rate)
- Real bugs or risks caught: [N]
- Most common rejection reason: [reason]
- Learning applied next week: [what changes]
```

**Why 6 artifacts, not just code commits**:
- Learning notes prevent the illusion of progress — understanding != building
- Architecture decisions become interview gold ("I chose X over Y because...")
- Failure log is your most honest portfolio signal — interviewers respect it
- Demo snapshots prove capability, not just intent
- Resume bullets written weekly stay fresh; bullets written at Week 30 are half-remembered
- The compound effect: 30 weeks × 6 artifacts = a complete, auditable learning record
