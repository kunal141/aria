# ARIA Learning Curriculum — Full Framework & Technique Map

Every framework, technique, and paper gets implemented inside ARIA. Learning is not separate from building.

---

## Core Principle

> Study the technique → implement it as a real capability inside ARIA → measure quality improvement → document in learning journal.

No technique is just "read and understood." Each produces a working capability.

---

## Full Technique Map (Week by Week)

| Technique / Framework | Study Week | Implement Week | Implemented As | ARIA Pillar |
|---|---|---|---|---|
| **LangGraph** | 3 | 3 | Core orchestration backbone: StateGraph, nodes, edges, checkpointers | 1, 11 |
| **ReAct** | 3-4 | 4 | ARIA's orchestrator reasoning loop: Think → Act → Observe → Reflect | 1 |
| **Chain of Thought** | 4 | 4 | Skill execution planning: ARIA plans steps before calling a skill | 1, 20 |
| **Tree of Thoughts** | 4 | 11 | Multi-path task decomposition when outcome is uncertain | 1, 20 |
| **Context Engineering** | 5 | 5 | What to send vs store vs summarize; working memory design | All skills |
| **HyDE** (Hypothetical Document Embeddings) | 6 | 9 | Enhanced retrieval: generate hypothetical answer → embed → match real docs | 8 |
| **Self-RAG** | 6 | 9 | ARIA critiques her own retrieval: relevant? complete? retrieve again? | 8 |
| **Adaptive RAG** | 6 | 9 | Dynamic retrieval strategy: choose method based on query type | 8 |
| **AutoGen (Study + Comparison)** | 7 | 17–22 | Conversational multi-agent protocol: ConversableAgent, GroupChat, actor-model; build 2-agent demo Week 18; compare vs CrewAI at Week 22 | 14 |
| **SWE-agent / MetaGPT patterns** | 8 | 23 | AI Engineering sub-agent design reference | 2 |
| **MemGPT / Letta memory patterns** | 11 | 11 | Memory paging: hot (context) + warm (retrieval) + cold (archived) | 4 |
| **LangSmith evaluation** | 13 | 13-14 | Rubric + regression framework; LLM-as-judge; golden examples | 12 |
| **Constitutional AI** | 14 | 14, 28 | Eval harness safety checks; self-integration proposal safety gate | 10, 18 |
| **CrewAI** | 17 | 22 | HANDS-ON implementation — build real Analytics + QA crew with role-based agents, tasks, process; NOT just a reference pattern | 13 |
| **RAPTOR** | 19 | 22 | Hierarchical document summarization for long organizational docs | 8 |
| **GraphRAG** | 19 | 22 | Knowledge graph retrieval for multi-hop org intelligence questions | 8 |
| **DSPy** | 21 | 21 | Systematic prompt optimization: define metric → compile → optimized prompt | 18 |
| **Instructor** | 21 | 21 | Structured output enforcement: every skill output is a validated Pydantic model | All skills |
| **Outlines / Guidance** | 21 | 21 | Constrained generation for JSON/structured outputs | All skills |
| **MCP (Model Context Protocol)** | Throughout | 3+ | Tool standardization for all external integrations | All |
| **LATS** (Language Agent Tree Search) | 24 | 24 | Agent tree search for multi-step decision exploration + evolution evaluation | 20, 18 |
| **A2A protocol** | 23 | 23+ | Schema design + future agent interoperability | 23 |
| **LoRA / QLoRA fine-tuning** | 25 | 25 | Fine-tune Qwen2.5-Coder-7B on Work Ledger PR review outputs — institutional knowledge in weights | 16, 21 |
| **DPO (Direct Preference Optimization)** | 25 | 25+ | Preference alignment from Work Ledger approve/reject pairs — encodes what the organization values | 17, 21 |
| **Unsloth** | 25 | 25 | Memory-efficient LoRA training — 2× faster than vanilla, fits on RTX 4090 or RunPod A40 (~$0.80/run) | 16 |
| **vLLM** | 25 | 25 | Serve fine-tuned model locally — OpenAI-compatible API, zero code changes in ARIA's skill layer | 21 |
| **Synthetic Data Generation** | 25 | 29 | Generate synthetic training examples when Work Ledger approved outputs < 50 — unblocks fine-tuning; use LLM + seed examples to create diverse training data | 24 |

---

## Framework Deep Dives

### LangGraph
**What it is**: A framework for building stateful, multi-step agent workflows as directed graphs.

**Key concepts to learn**:
- `StateGraph`: define a graph with typed state (`TypedDict`)
- Nodes: Python functions that read + modify state
- Edges: define flow between nodes (conditional or unconditional)
- Checkpointers: make state durable (PostgreSQL, Redis, in-memory)
- `interrupt_before` / `interrupt_after`: pause for human approval
- Fan-out / fan-in: parallel node execution and result merging
- Subgraphs: nested graphs for complex workflows

**Implemented as in ARIA**:
- Every ARIA workflow is a `StateGraph`
- Every skill call is a node
- Every routing decision is a conditional edge
- Every approval gate uses `interrupt_before`
- PostgreSQL checkpointer for production durability

**Study resources**:
- LangGraph official docs: https://langchain-ai.github.io/langgraph/
- LangGraph conceptual guide: multi-agent, human-in-the-loop
- LangGraph examples: ReAct agent, multi-agent supervisor

---

### ReAct (Reason + Act)
**What it is**: A reasoning pattern where the agent alternates: Thought → Action → Observation → Thought → ...

**Key concepts**:
- Agent reasons about what to do (Thought)
- Takes an action (call a tool, skill, or sub-agent)
- Observes the result
- Reasons again from updated state
- Repeats until task complete or max steps reached

**Implemented as in ARIA**:
- ARIA's orchestrator reasoning node: before routing, ARIA thinks about the task
- Thought: "This is a PR review task. I need the PR diff + code context + risk checklist"
- Action: call PR diff tool → call code intelligence tool → call PR review skill
- Observation: "Risk level is high. Missing tests for module X."
- Thought: "I should flag this and recommend adding tests."
- Output: structured review with risk summary

---

### Chain of Thought (CoT)
**What it is**: The model explicitly reasons through steps before giving a final answer.

**Key concepts**:
- Zero-shot CoT: "Let's think step by step"
- Few-shot CoT: provide examples of reasoning chains
- Structured CoT: constrain the reasoning format (numbered steps, markdown sections)

**Implemented as in ARIA**:
- Skill execution planning: before calling a skill, ARIA generates a plan
- PR Review planning: "Step 1: Get PR diff. Step 2: Identify changed modules. Step 3: Check test coverage. Step 4: Assess deployment risk."
- Each step is logged in LangSmith trace

---

### Tree of Thoughts (ToT)
**What it is**: The model explores multiple reasoning paths simultaneously, evaluates each, and pursues the most promising.

**Key concepts**:
- Generate N candidate thoughts at each step
- Score each thought (self-evaluation or external scorer)
- Expand the best k thoughts
- Backtrack when a path leads to dead end
- Find optimal reasoning path through search (BFS or DFS)

**Implemented as in ARIA**:
- Multi-path task decomposition: when a goal is ambiguous, ARIA generates 3 decomposition options and scores each
- Decision Intelligence: generate multiple action options → score → present best with tradeoff explanation

---

### Context Engineering
**What it is**: The discipline of deciding what information to put in the LLM's context window — not just "stuff everything in."

**Key concepts**:
- Working memory: what the model needs RIGHT NOW to complete this task
- Long-term memory: what to retrieve from store (not put in context directly)
- What to summarize: compress old context that's still relevant but bulky
- What to exclude: irrelevant history, stale data, noise
- Context budget: estimate token cost, leave room for output
- Grounding: always include the most recent + most relevant source material

**Implemented as in ARIA**:
- Context strategy document: defines what goes in prompt vs what gets retrieved
- Memory injection points: user preferences + task history retrieved fresh per task
- Artifact context: when generating a report, inject only the relevant data, not all ARIA's memory
- Summarization: long conversation history → compressed summary in working context

---

### HyDE (Hypothetical Document Embeddings)
**What it is**: To retrieve a document about question Q, first generate a hypothetical answer to Q, embed that hypothetical answer, then search for real documents that are similar to the hypothetical.

**Key insight**: The hypothetical answer often matches real documents better than the question itself.

**Implemented as in ARIA**:
- SOP retrieval: "How do we handle a production outage?" → generate hypothetical SOP → embed → retrieve real SOP
- Architecture doc retrieval: "How does the recommendation engine work?" → generate hypothetical explanation → retrieve real architecture doc

---

### Self-RAG
**What it is**: After retrieving documents, the model critiques its own retrieval: "Is this document relevant? Is my retrieval complete? Should I retrieve again with a different query?"

**Phases**:
1. Retrieve: get candidate documents
2. Relevance check: "Is retrieved doc D relevant to query Q?"
3. Sufficiency check: "Do I have enough to answer?"
4. If no: regenerate query, retrieve again
5. Answer: generate answer from verified-relevant documents
6. Support check: "Is my answer supported by the retrieved documents?"

**Implemented as in ARIA**:
- Knowledge retrieval layer: after retrieval, ARIA checks relevance before including in context
- If retrieval is insufficient, ARIA attempts alternative queries before answering

---

### MemGPT / Letta Memory Patterns
**What it is**: A memory architecture inspired by OS virtual memory — manages what's "in-context" (RAM) vs "on-disk" (long-term store) and pages memory in/out based on relevance.

**Key concepts**:
- Main context (in-context memory): recent conversation + active task state + current user preferences
- External storage (retrieval memory): all past conversations, decisions, outcomes
- Memory paging: move important info from storage → context when relevant
- Memory consolidation: combine related memories into summaries
- Memory forgetting: decay stale context, promote important signals

**Implemented as in ARIA**:
- User memory: preference + role → always in context
- Task memory: current task context → in context for task duration
- Decision memory: past architectural decisions → retrieved on demand
- Outcome memory: past task outcomes → retrieved when similar task starts

---

### Constitutional AI
**What it is**: A technique for training models to be helpful, harmless, and honest using a "constitution" (a set of principles). At inference time, the model critiques its own outputs against the principles.

**For inference-time use**:
1. Generate initial output
2. Critique: "Does this output violate any principle?"
3. Revise: "Generate a better version that doesn't violate principle X"
4. Use revised output

**Implemented as in ARIA**:
- Evaluation harness: every skill output checked against safety rubric
- Self-integration safety: before any capability is proposed for integration, ARIA checks: "Does this change any safety boundary? Does it bypass governance?"

---

### DSPy (Declarative Self-improving Python)
**What it is**: A framework for programming language models — instead of writing prompts by hand, you define input/output signatures and a metric, and DSPy compiles optimized prompts automatically.

**Key concepts**:
- Signatures: define input fields + output fields (like typed function signatures)
- Modules: composable LM calls (Predict, ChainOfThought, ReAct)
- Teleprompters/Optimizers: compile signatures + examples → optimized prompt
- Metrics: define what "good" means (rubric score, accuracy, format compliance)

**Implemented as in ARIA**:
- Skill prompt optimization: instead of hand-tuning PR review prompt, define input/output signature + quality metric, compile optimized prompt
- Measurable improvement: before DSPy vs after DSPy rubric scores tracked in LangSmith

---

### Instructor
**What it is**: A library that makes LLM outputs conform to Pydantic models — guaranteed structured output.

**Key concepts**:
- Define a Pydantic model for the output
- Decorate with `@instructor.patch` or use `client.chat.completions.create(..., response_model=MyModel)`
- If LLM output doesn't parse, Instructor retries with error message
- Result: always a valid Python object, never a string to parse manually

**Implemented as in ARIA**:
- Every skill returns a typed Pydantic model — no ad-hoc string parsing anywhere
- PR Review output: `PRReviewResult(risk_level: str, missing_tests: list[str], deployment_risk: str, business_impact: str)`
- All outputs are validated, serializable, storable in Work Ledger

---

### RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)
**What it is**: Build a hierarchical tree of summaries over a document corpus. At query time, retrieve from both the leaf level (detailed) and summary level (abstract), combining for better coverage.

**Key insight**: Traditional chunking loses document structure and big-picture context. RAPTOR preserves both.

**Implemented as in ARIA**:
- Long organizational docs: architecture docs, annual reports, long SOPs
- RAPTOR tree: paragraph-level chunks (leaves) → section summaries → document summary (root)
- Retrieval: search across all levels, combine detailed + abstract context

---

### GraphRAG
**What it is**: Build a knowledge graph from a document corpus (entities + relationships). At query time, traverse the graph to answer questions that require multi-hop reasoning across entities.

**Key insight**: "How does our recommendation engine affect editorial KPIs?" requires connecting: recommendation engine → article performance → editorial team → KPIs. Graph traversal finds this; keyword search does not.

**Implemented as in ARIA**:
- Org knowledge graph: systems → teams → metrics → decisions → outcomes
- Query: "What decisions did we make about the recommendation engine?" → graph traverse → find all related decisions

---

### LATS (Language Agent Tree Search)
**What it is**: Apply Monte Carlo Tree Search (MCTS) principles to agent decision-making. Explore multiple action sequences, evaluate outcomes, backtrack from dead ends, find optimal path.

**Key concepts**:
- Selection: choose promising node based on UCB (exploration vs exploitation)
- Expansion: generate candidate next actions
- Simulation: run the action sequence, observe outcomes
- Backpropagation: update node scores based on outcome

**Implemented as in ARIA**:
- Decision Intelligence: when ARIA must recommend an action, she tree-searches: "If I do A, what happens? If I do B? Which path leads to best outcome?"
- Evolution Intelligence evaluation: "If I integrate capability X, what's the quality impact? Tree search over integration scenarios."

---

### Small Language Models (SLMs) + Model Router
**What they are**: SLMs are lightweight models (0.5B–4B parameters) designed for cheap, fast, repeated tasks that don't need a frontier model's reasoning depth. The Model Router decides which model to use for each task based on risk, complexity, cost, latency, and data privacy requirements.

**Key SLMs for enterprise AI**:
- `Phi-3-mini-4k-instruct` (3.8B) — excellent at classification and structured extraction, Microsoft
- `Qwen2.5-0.5B-Instruct` (0.5B) — extremely cheap, good for routing/labeling
- `Gemma-2-2B-it` (2B) — Google, good all-around small model
- `Llama-3.2-1B-Instruct` (1B) — Meta's efficient small model

**When SLMs are enough**:
| Task | Why SLM works |
|---|---|
| Task type classification | Limited label set, repetitive pattern |
| Intent routing | Small decision space |
| Risk level scoring (Low/Medium/High) | Controlled vocabulary |
| Jira field extraction | Structured extraction from text |
| Output format compliance check | Pattern matching |
| Email / report first draft | Low creativity requirement |
| Approval prediction | Binary classification |

**Model routing logic**:
```
Task arrives
   ↓ Is it a classification/extraction task with < 5 output classes?
     → SLM (Phi-3-mini via vLLM, ~$0 cost)
   ↓ Is it a structured generation task (PR note, ticket, summary) with stable format?
     → Fine-tuned 7B via vLLM (~$0 cost)
   ↓ Is it sensitive internal data (code, financials)?
     → Self-hosted model via vLLM (no external API call)
   ↓ Does it require complex multi-step reasoning?
     → Claude Haiku (cheap) or Claude Opus (complex)
   ↓ Is it a high-risk Tier 4-5 action?
     → Claude Opus + human approval
```

**Implemented as in ARIA** (Week 16):
- Model Router v1 integrated into orchestrator — classifies tasks and routes to correct model endpoint
- SLMs served via vLLM (OpenAI-compatible) — zero code change in skill layer
- Cost tracking per routing decision — quantify savings in Work Ledger

---

### Fine-Tuning (LoRA / QLoRA) + vLLM
**What it is**: Training a pre-trained model on domain-specific data so it specializes. Instead of retraining all weights (expensive), LoRA attaches small adapter matrices and trains only those. QLoRA adds 4-bit quantization to make it fit on a single consumer GPU.

**Key concepts**:
- LoRA: Low-Rank Adaptation — freeze base model, add small A×B weight matrices, train only those
- QLoRA: LoRA + 4-bit NF4 quantization — reduces GPU memory by 4×, minimal quality loss
- SFTTrainer (TRL): supervised fine-tuning on instruction-formatted examples
- DPO: Direct Preference Optimization — train on (chosen, rejected) pairs to align to human preferences
- Dataset format: instruction → input → output (alpaca format) — maps directly to Work Ledger records
- vLLM: high-performance inference engine — PagedAttention for memory efficiency, continuous batching for throughput

**The moat connection**:
- By Week 25, ARIA's Work Ledger holds approved PR reviews, test cases, summaries, anomaly analyses
- Each approved record = ground truth: input + approved output
- Fine-tuning Qwen2.5-Coder-7B on these creates a specialist model that reflects YOUR organization's patterns
- No one else has this training data — it's locked to 25 weeks of real work

**Implemented as in ARIA**:
- `aria/ml/finetune/prepare_dataset.py` — pulls Work Ledger approved records → alpaca format
- `aria/ml/finetune/train_lora.py` — Unsloth + TRL SFTTrainer, QLoRA rank=16, alpha=32
- `aria/ml/finetune/eval_finetuned.py` — LangSmith rubric comparison: base vs fine-tuned
- `aria/ml/serve/start_vllm.sh` — vLLM serving at `localhost:8000/v1/chat/completions`
- Model router: PR review tasks → `localhost:8000` (local model), complex reasoning → Claude Opus

**Practical details**:
- Base model: `Qwen/Qwen2.5-Coder-7B-Instruct` (code-aware, fast, fits in 24GB with QLoRA)
- Training time: ~1-2 hours for 200 examples, 3 epochs
- Hardware: RTX 4090 locally OR RunPod A40 (~$0.40/hr) = ~$0.80 per fine-tuning run
- If Work Ledger has < 50 real examples: use **Synthetic Data Generation** (see below) to generate training examples, then retrain with real data when available

**Synthetic Data Generation for Fine-Tuning**:
When your Work Ledger has fewer than 50 approved outputs for a given skill, you don't have to wait or skip fine-tuning. Instead:
1. Take 5–10 seed examples (your best approved outputs)
2. Use Claude to generate variations: "Generate 10 diverse PR review examples in the same format and quality as these seeds, covering different code patterns and risk levels"
3. Manually verify each synthetic example — only include ones you'd genuinely approve
4. Use synthetic examples as training data with lower weight than real examples (if your trainer supports it)
5. Retrain with real data when Work Ledger grows to 50+ examples; compare eval scores
6. Track which examples are synthetic vs real in your dataset metadata

**Why this works**: LLMs are excellent at generating diverse instances of a well-defined pattern. The key is the seed examples define the pattern; the LLM generates variation. The human verify step ensures quality. This is standard practice — not a shortcut.

**Synthetic data tools**: LangChain's `FewShotPromptTemplate` for structured generation, or a simple Claude API call with few-shot examples in the prompt.

---

### When NOT to Fine-Tune (Critical Discipline)

This is as important as knowing when TO fine-tune.

**Use fine-tuning when:**
- The output format/style is stable and repeated (PR review comment format, ticket structure)
- You have > 50 clean, high-quality examples
- RAG + prompting is inconsistent despite good retrieval
- Latency or API cost is a real constraint
- The task pattern won't change significantly over the next few months

**Do NOT use fine-tuning when:**
| Situation | Better approach |
|---|---|
| Task requires fresh/current knowledge | RAG — retrieve latest docs/context |
| Task depends heavily on retrieved context | RAG + tools — retrieval IS the answer |
| Workflow is still changing | Wait — fine-tune stable patterns only |
| < 50 clean training examples | Prompt engineering first |
| Correctness depends on real data / calculations | Tools (SQL, Python) + LLM explanation |
| Policy or governance rules need updating | Policy engine — not model weights |
| Task involves rare edge cases | Prompting + guardrails |

**The default stack (exhaust these before fine-tuning)**:
```
1. Prompt engineering (system prompt, few-shot examples)
2. RAG (retrieve relevant context)
3. Tools (Python, SQL, APIs for deterministic steps)
4. Structured outputs (Instructor + Pydantic models)
5. DSPy (systematic prompt optimization)
6. SLM for cheap classification/routing

→ Only after all above: consider fine-tuning
```

**The honest truth**: For most ARIA tasks, RAG + tools + Instructor + DSPy will achieve the quality bar without a single fine-tuning run. Fine-tuning is most powerful for tasks with: stable format, high volume, and strong quality feedback from the Work Ledger.

---

## Study Resources by Category

### Orchestration & Reasoning
- LangGraph docs: https://langchain-ai.github.io/langgraph/
- ReAct paper: "ReAct: Synergizing Reasoning and Acting in Language Models"
- Tree of Thoughts paper: "Tree of Thoughts: Deliberate Problem Solving with Large Language Models"
- LATS paper: "Language Agent Tree Search Unifies Reasoning, Acting, and Planning"

### Memory
- MemGPT paper: "MemGPT: Towards LLMs as Operating Systems"
- Letta docs: https://docs.letta.com/

### Retrieval
- HyDE paper: "Precise Zero-Shot Dense Retrieval without Relevance Labels"
- Self-RAG paper: "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection"
- RAPTOR paper: "RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval"
- GraphRAG paper: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization"

### Prompt Engineering
- DSPy docs: https://dspy.ai/
- DSPy paper: "DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines"
- Instructor docs: https://python.useinstructor.com/
- Constitutional AI paper: "Constitutional AI: Harmlessness from AI Feedback"

### Evaluation
- LangSmith docs: https://docs.smith.langchain.com/
- LLM-as-judge: "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena"

### Multi-Agent

#### AutoGen (Study + Comparison — Weeks 17–22)
**What it is**: A conversational multi-agent framework where agents communicate via natural language messages. Agents can be LLMs, tools, or humans. Coordination happens through conversation, not a predefined graph.

**Key concepts to understand**:
- `ConversableAgent`: the base class — wraps an LLM, defines a system prompt, knows how to send/receive messages
- `AssistantAgent` / `UserProxyAgent`: built-in roles — the assistant proposes, the proxy executes code and returns results
- `GroupChat`: multiple agents in a shared conversation, with a `GroupChatManager` that routes turns
- `initiate_chat()`: starts a conversation between two agents with a task message
- Termination conditions: when to stop the conversation (keyword, max turns, human input)
- Code execution: UserProxyAgent can execute Python in a sandbox and return output to the conversation
- Human-in-the-loop: `human_input_mode='ALWAYS'` | `'TERMINATE'` | `'NEVER'`

**AutoGen vs LangGraph vs CrewAI — the key distinctions**:
| Dimension | AutoGen | CrewAI | LangGraph |
|---|---|---|---|
| Coordination model | Conversational — agents talk to each other | Role-based — defined crew with tasks and process | Graph-based — explicit state machine |
| Best fit | Research assistants, debate/critique, code exec loops | Structured workflows with clear role assignments | Complex stateful enterprise orchestration |
| Debugging | Conversation transcript | Task log per agent | LangSmith trace per node |
| Governance | Conversation-level | Task-level | Node-level with interrupt gates |
| ARIA usage | Study + comparison (Weeks 17–22) | Hands-on production (Week 22) | Production backbone (all 30 weeks) |
| Interview value | "I studied and benchmarked it" | "I built a real crew" | "ARIA's entire orchestration layer" |

**When AutoGen beats LangGraph**:
- You want a back-and-forth critique loop (Writer → Critic → Revision) without predefining the graph
- Code generation + execution where the number of iterations is unknown upfront
- Research tasks where agents debate options before converging on a conclusion
- Rapid prototyping where you don't want to define state schemas first

**When LangGraph beats AutoGen**:
- Enterprise workflows that need deterministic state, audit trails, and interrupt gates
- Multi-step tasks where you need durable checkpointing and resumability
- Production systems where you need node-level tracing in LangSmith
- Governance-heavy contexts where every decision must be traceable and approvable

**Weeks 17–22 learning plan**:
- Week 17: Read AutoGen docs — study ConversableAgent, AssistantAgent, UserProxyAgent, GroupChat concepts. Take notes on how it differs from LangGraph.
- Week 17: Annotate the AutoGen GitHub examples — mark what you understand and what's new
- Week 18: Build the 2-agent demo: `CodeReviewerAgent` + `TestGeneratorAgent`. Set a task: "Review this function and generate tests for it." Run it, observe the conversation.
- Week 22: After building the CrewAI crew, replicate a subset of it in AutoGen. Write a one-page comparison: what was easier in each, what was harder, which would you choose for ARIA's production workflows and why.

**Study resources**:
- AutoGen paper: "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation"
- AutoGen GitHub: https://github.com/microsoft/autogen
- AutoGen docs: https://microsoft.github.io/autogen/
- AutoGen examples: Two-agent coding assistant, GroupChat debate

#### CrewAI (Hands-On — Week 22)
Real implementation at Week 22. Build Analytics + QA crew with role-based agents, tasks, and process.

- CrewAI docs: https://docs.crewai.com/
- SWE-agent paper: "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering"

### Small Language Models & Model Routing
- Phi-3-mini model card: https://huggingface.co/microsoft/Phi-3-mini-4k-instruct
- Qwen2.5-0.5B: https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct
- HuggingFace SLM blog: "Small Language Models: A Comprehensive Overview"
- LiteLLM docs (unified model gateway): https://docs.litellm.ai/

### Fine-Tuning & Model Serving
- Unsloth docs: https://docs.unsloth.ai/
- TRL docs: https://huggingface.co/docs/trl/ (SFTTrainer, DPOTrainer)
- QLoRA paper: "QLoRA: Efficient Finetuning of Quantized LLMs"
- DPO paper: "Direct Preference Optimization: Your Language Model is Secretly a Reward Model"
- vLLM docs: https://docs.vllm.ai/
- vLLM blog: "vLLM: Easy, Fast, and Cheap LLM Serving with PagedAttention"
- Qwen2.5-Coder: https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct

---

## The Learning → Building → Measuring Loop

Every technique follows this loop:

```
1. STUDY (1-2 days)
   Read the paper/docs. Understand the core insight.
   Write 3 bullet points: what it is, when to use it, key constraint.

2. IMPLEMENT (2-3 days)
   Build it as a real capability inside ARIA.
   Wire it to the orchestrator or the relevant skill.
   Add LangSmith traces so you can see it working.

3. MEASURE (1 day)
   Run the before/after rubric comparison in LangSmith.
   Document the quality delta.
   If it doesn't improve quality, understand why and note it.

4. DOCUMENT (30 min)
   Add entry to learning_journal.md.
   Write one resume bullet for the week.
   Update capability_map.md if a new capability was added.
```

The measure step is non-negotiable. "I implemented Self-RAG" is meaningless without "and retrieval relevance improved from 6.2 to 7.8 on our benchmark."
