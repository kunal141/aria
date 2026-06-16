# ARIA V2 — Complete Five-Week V2 Internal-Pilot Scope

*(Internal AI Employee Pilot — local intelligence & approval-gated domain memory)*

> **This plan completes the agreed *five-milestone V2 internal-pilot scope* in full — it is not an MVP of
> that scope, and none of its 20 goal items are deferred to a later V2.x; all 20 ship inside the five
> milestones.** It does **not** claim to complete the entire V2/V3 roadmap: subagents, delegated identity,
> multi-tenancy, production writes, vLLM, real fine-tuning, **live connector *writes* / production
> actions**, and AI-Employee-as-a-Service remain explicitly V3/future (see §24–§25).
> **Live connector boundary:** *optional, explicitly authorized live **read-only** sources* are **in V2
> scope** (the `CONNECTOR_MODE=read_only_live` path of §6.4, default off). Only connector **writes** and
> production actions are deferred to V3 — V2 has no external write path at all (§12, §24).
> **"Five weeks" means five implementation milestones**, not five fixed calendar weeks — Codex
> stabilization/re-audit rounds may extend elapsed calendar time, and quality + governance gates always
> override the schedule (see §3, §18, §26).
> The per-milestone load is aggressive **by design** — the answer to compression is higher per-milestone
> workload and parallel workstreams, not reduced scope.
> Planning document only. No code in this document changes runtime behavior.
> Implementation begins **only after this plan is accepted**, on branch
> `v2-complete-internal-ai-employee-pilot` (do not create until asked).

**Status:** DRAFT — awaiting Codex re-audit. Not yet an accepted or committed plan.
**Predecessor state (locked):** V1 complete at `abf0096`; V1.1 local chat REPL complete at `d199a51`;
V1 release capsule committed at `3157012`; backend baseline **1048 passed, 1 skipped**; local chat
offline-by-default; no live integrations, no production execution, no vLLM, no real training, no
deployment; public release blocked pending employer/IP approval.
**Working-tree note:** the *accepted baseline* tree was clean before any planning docs were added. The
current working tree is **not** clean — it contains this planning document (and, until committed, any
sibling planning artifacts) as the only deltas from the accepted baseline. The V2 branch (when created)
will be cut from the **latest accepted planning commit**, not from a hypothetically clean `d199a51` tree
(see §26).

---

## 1. Executive Summary

V1 proved ARIA is a *safe, governed harness*: a typed LangGraph runtime (intake → router → skill →
evidence gate → respond), the six principal offline-safe skills listed in the V1 release capsule (PR
review, KPI, CI/CD, Jira drafting, QA, and test review), a fail-closed evidence gate, Work Ledger v2 with
ROI metrics, governed evolution, and an offline-by-default local chat REPL. Everything is provable and
nothing touches production.

V2 turns that prototype into a **practical internal AI employee pilot** that a single engineer (Kunal) can
actually *use* on a laptop, end to end, with **local model intelligence and no cloud dependency**. The
five things that make V2 "real" without making it risky:

1. **Local brain** — Ollama/Gemma runs the intelligence; **no silent cloud fallback**, ever.
2. **Conversation** — multi-turn orchestration above the V1 graph, with streaming in terminal and web.
3. **Memory that earns trust** — casual statements become **approval-gated, versioned domain memory** in
   an authoritative SQLite store; unapproved memory is never retrieved; everything is cited.
4. **Surfaces** — streaming terminal chat, a FastAPI V2 streaming API, and a minimal ARIAChat web view,
   plus an approval inbox and a persistent per-task workspace.
5. **Three read-only pilots** — PR review, CI/CD investigation, Analytics/KPI investigation — all
   draft-only, fixture-backed, evidence-gated.

V2 is deliberately a **pilot**, not a product: **no production writes, no vLLM, no real fine-tuning, no
subagents, no multi-tenancy, no public release.** The V1/V1.1 governance — evidence gates, action tiers,
dry-run surface policy, secret redaction, isolated test sinks — is **preserved and extended additively, not
replaced.** The V1 graph is *not* claimed to be byte-for-byte unchanged: its **governance semantics and
entry path are preserved**, while purely **additive** typed inputs / context / evidence adapters may be
introduced where needed (see §4, P-level invariants in §22).

---

## 2. V2 North Star

> *"ARIA runs locally on Gemma with no cloud dependency, holds a real multi-turn conversation, learns the
> organisation's domain knowledge only after I approve it, remembers it across restarts, cites it when she
> uses it, and walks three real engineering investigations end-to-end — all read-only, all governed, all
> on my machine."*

The single demo that proves it (the `story_events.event_type` arc): tell ARIA a fact → she proposes
memory → you approve → it persists in SQLite → **restart** → she recalls it *with a citation* → she uses
it to run a read-only analytics investigation and produce a cited report + a Jira **draft**.

---

## 3. Why V2 Is Compressed Into 5 Weeks

The original roadmap framed V2 as a **+12-month, ~50,000-line, multi-vertical, multi-tenant SaaS** effort
(CLAUDE.md §2; `week30_v1_v2_v3_boundary.md` §"V2 — Roadmap"). That scope includes vLLM serving, real
fine-tuning + deployment, live connector **writes**, the §28.1 Subagent Engine, Model Router v3, and the
Generative UI Canvas.

This plan does **not** attempt that. It carves out exactly the slice that makes ARIA a *usable internal
pilot* and compresses it into **five implementation milestones** by:

- **Reusing the V1 harness wholesale.** The orchestrator sits *above* the accepted graph; routing,
  skills, evidence gates, and governance **semantics are preserved** and the graph entry path is
  preserved — only **additive** adapters (typed inputs / context / evidence) are introduced, never a
  rewrite or a bypass.
- **Reusing existing infrastructure.** Ollama is already wired in `config.py`; the offline/no-external-network
  discipline already exists via `offline_scope()`/`has_llm()`; the Work Ledger already carries
  `correlation_id` + `actor` on every event; V1.1's `chat.py` + surface-policy state fields are the seed
  for the terminal upgrade.
- **Choosing SQLite over a distributed store.** One file, ACID transactions, trivial restart-safety — the
  authoritative memory store needs nothing heavier for a single-user pilot.
- **Going read-only / draft-only everywhere.** No connector write code to harden means weeks go to
  conversation, memory, and proof — not to integration safety.
- **Running parallel workstreams** (backend / frontend / docs / tests) inside each week rather than
  sequentially.

**This is intentionally aggressive.** §5 states explicitly what parallelism each week assumes and where
the schedule is most likely to slip.

---

## 4. V2 Architecture

```
                          ┌────────────────────────────────────────────────┐
   Terminal chat ─────────┤                                                │
   (uv run -m aria.chat)  │      V2 Conversation Orchestrator (NEW)         │
                          │   decision ∈ {converse, run_workflow,           │
   Web ARIAChat ──────────┤              propose_memory, clarify}           │
   (fetch + ReadableStream)│  - short-term session history (context only)   │
                          │   - NEVER executes tools directly               │
   FastAPI V2 API ────────┤   - delegates workflows to the V1 graph         │
   (/api/v2/chat/...)     └───────────────┬───────────────┬────────────────┘
                                          │               │
                            run_workflow  │               │ propose_memory / recall
                                          ▼               ▼
                       ┌──────────────────────────┐   ┌──────────────────────────┐
                       │ V1 LangGraph (gov.        │   │  SQLite Domain Memory     │
                       │   semantics + entry path  │   │  Authority (NEW)          │
                       │   preserved; additive     │   │  proposal→approve→version │
                       │   adapters only)          │   │  →cite→update/delete/     │
                       └────────────┬──────────────┘   │  rollback                 │
                                    │                   └────────────┬─────────────┘
              read-only pilots      │                                │
              (PR / CI-CD / Analytics, fixture-backed)               │
                                    ▼                                ▼
                       ┌────────────────────────────────────────────────────────┐
                       │   Work Ledger v2 (aria/ledger/) — EXTENDED with         │
                       │   conversation + memory + approval + workspace events   │
                       │   (correlation_id + actor already present)              │
                       └────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                       Persistent per-task Workspace (SQLite-backed, restart-safe)
                       Approval Inbox / Decision Surface (memory, Jira, Teams, PR drafts)
```

**Invariants carried from V1 (non-negotiable):**

- The V1 graph is the **only** path to skill execution and governance. The orchestrator decides *whether*
  to call it; it never bypasses it. The graph is **not** claimed to be byte-for-byte unchanged — its
  governance semantics and entry path are preserved, and any new wiring is a purely **additive** adapter
  (typed input / context / evidence), never a rewrite of routing, skills, or gates.
- **Memory supplements evidence; it never replaces it.** A KPI/CI-CD claim still passes the fail-closed
  evidence gate even if a memory "explains" the data.
- **External and workflow mutations remain blocked / dry-run throughout V2.** Approval may persist
  approved domain memory or mark a draft approved; it **never** enables connector or production execution.
- Secrets are redacted; raw exception text and raw chain-of-thought are never surfaced.
- **Browser streaming uses `fetch()` + a `ReadableStream` reader over a POST** (not `EventSource`, which is
  GET-only). A future GET-based SSE endpoint is optional and out of scope for this pilot.

---

## 5. Parallel Workstreams

Each week runs four lanes. The plan assumes Kunal context-switches between lanes (or sequences them within
the week), not that four people work simultaneously — so the realistic constraint is **lane ordering**,
not headcount.

| Lane | Owns | Hard dependency |
|---|---|---|
| **Backend** | Provider contract, orchestrator, SQLite memory, ledger events, pilots, API | Memory authority must land before pilots can cite it |
| **Frontend** | ARIAChat web view, proposal/approval/citation cards, streaming | Needs the streaming event contract frozen (Week 33 start); consumes it via `fetch()` + `ReadableStream` |
| **Docs** | Contracts, ADRs, demo script, boundary updates, weekly maintenance artifacts | Tracks backend; never leads it |
| **Tests** | No-cloud-fallback, memory lifecycle, streaming event order, pilot read-only, regression | Written *with* each feature, not after (Eval-Lite discipline) |

**Where parallelism is real vs assumed:** Backend↔Tests are genuinely concurrent (TDD). Frontend is gated
on the API contract, so it lags backend by ~half a week — which is why the **streaming event contract is
frozen at the end of Week 32** (the allowed event set + ordering, consumed via `fetch()` +
`ReadableStream`), letting the web lane start on day 1 of Week 33 rather than mid-week. Docs trail
both. **The single most likely slip point** is Week 33 (streaming + API + web + approval inbox + workspace
in one week) — see §23. The response to pressure there is **more parallel hours, not a dropped
deliverable**: every Week-33 item is a required V2 item and ships in Week 33.

---

## 6. Local Intelligence Foundation

**Provider:** Ollama (local inference). Already supported in `apps/backend/aria/config.py`
(`provider == "ollama"` → `ChatOllama`). V2 makes it the **default** and adds availability + no-fallback
enforcement.

**Target configuration (`.env`):**

```env
LLM_PROVIDER=ollama
LLM_MODEL=gemma4:e4b
LOCAL_LLM_PROVIDER=ollama
```

> **Model is a verified-at-implementation configuration, not a blind assumption.** `gemma4:e4b` is the
> **target** model string. It is **not assumed to exist** — Week 31 must verify it against the local
> Ollama install before anything else is built:
>
> ```bash
> ollama list            # is the tag pulled locally?
> ollama show gemma4:e4b  # does this exact tag resolve?  (or the equivalent Ollama API check)
> ```
>
> If the model is **unavailable**, ARIA must fail clearly with a controlled error that includes
> `ollama pull <configured-model>` (which renders as `ollama pull gemma4:e4b` under the default config) —
> it must **never auto-download during startup** and **never silently fall back to cloud**. Ollama tag
> names vary by release (e.g. Gemma "e4b" effective-parameter variants), so the env value is configurable;
> the guidance string interpolates `LLM_MODEL` so a substitute model produces correct guidance. The
> **startup availability check** is what guarantees a wrong/absent tag surfaces loudly on day 1 instead of
> silently degrading.

**Requirements (all enforced at startup / call time):**

- **Verify Ollama is reachable** at startup (daemon up).
- **Verify the configured model is present** at startup — `LLM_MODEL` must appear in `ollama list`
  (equivalently `ollama show gemma4:e4b` / the Ollama API) before the app is considered healthy.
- **Never auto-download** a model during app startup.
- **Never silently fall back** to OpenAI / Anthropic / any cloud provider.
- On unavailability, return a **clear, controlled error** that tells the user exactly what to run
  (the model name is interpolated from `LLM_MODEL`, so it stays correct for a substitute model):

  ```bash
  ollama pull <configured-model>   # default config → ollama pull gemma4:e4b
  ```

- **Cloud models are explicit opt-in only** (a deliberate flag/env, mirroring V1.1's `--llm` discipline).
- **No external network or paid-provider calls in the default local mode.** (A local Ollama call to
  `localhost` is not an external/paid call; the prohibition is on *cloud / paid provider* traffic and any
  outbound network beyond the local daemon.)
- Record **model name, latency, token count (if available), and failures** in the Work Ledger.
- **Tests must prove no-cloud-fallback even when cloud credentials are present** in the environment.

**How this extends existing code (attach points, not rewrites):**

- A small `aria/llm/local_provider.py` (or extension of `config.py`) adds `ensure_local_model_available()`
  and a `cloud_opt_in` gate. `has_llm()` / `offline_scope()` semantics are reused: "no cloud" is the same
  discipline V1.1 already enforces, now applied to the default path rather than only the chat surface.
- The router and skills are **not** rewritten — they already call the provider factory.

### 6.1 Execution modes (explicit, named)

V2 has exactly three named execution modes. The default is **offline** and nothing escalates silently:

| Mode | Brain | Network | When |
|---|---|---|---|
| `offline_mock` | deterministic keyword router + mock skill outputs (V1.1 behaviour) | none | selected **only explicitly or by tests** — never auto-selected because Ollama is absent/unhealthy; never contacts the daemon |
| `local_ollama` | local Ollama / `gemma4:e4b` | local daemon only (`localhost`), **no external/paid** | default for **interactive** V2 use once readiness passes |
| `cloud_opt_in` | a cloud provider (Anthropic/OpenAI/…) | external/paid | **only** when a deliberate flag/env is set, mirroring V1.1's `--llm`; never auto-selected, never a fallback |

The mode is **always chosen explicitly; no mode is ever auto-selected as a fallback.** Specifically:

- An **explicitly selected `local_ollama` must fail loudly** when Ollama is unreachable or the model is
  absent — it returns the controlled `ollama pull <configured-model>` error and **never** automatically
  downgrades to `offline_mock` or escalates to `cloud_opt_in`.
- `local_ollama` never silently degrades to `cloud_opt_in`, and `cloud_opt_in` is never reached except by a
  deliberate flag/env.
- `offline_mock` is entered **only** by an explicit selection or by the test harness — never because the
  daemon happens to be down. Tests run in `offline_mock` so the suite needs **no** Ollama daemon and makes
  **no** network/paid calls.

### 6.2 Readiness boundary — checks run at startup, never at import

Ollama reachability + model-presence checks run **only** when a V2 chat session or the V2 API actually
starts (or via an explicit readiness command/endpoint) — **never at module import time**. Concretely:

- Importing any `aria.*` module must **not** contact the Ollama daemon. The existing V1/V1.1 test suite
  imports the package freely; it must keep passing **with no Ollama installed**, because tests run in
  `offline_mock` and nothing on the import path probes a daemon.
- The readiness check is invoked at the entry points that need a live brain (`aria.chat` V2 startup, the
  FastAPI V2 app startup, or an explicit `aria … --check-model` / `GET /api/v2/health`).
- `offline_mock` is always available as the no-daemon path, so a developer (or CI) with no Ollama can still
  run, import, and test the whole codebase.

### 6.3 Model-fitness gate (Week 31)

`gemma4:e4b` being *present* is necessary but **not sufficient**. Week 31 also runs a small, local
**model-fitness suite** that benchmarks the configured model on the behaviours V2 depends on, before the
local-intelligence foundation is accepted.

So the fitness suite has something to validate against **without** pulling Week 32 work forward, Week 31
first **freezes two minimal, evaluation-only JSON schemas** — a routing-decision shape and a
memory-extraction shape. These are *compatibility contracts* (the field set + types the fitness suite
asserts against), **not** the full `OrchestratorDecision` / `DomainMemoryProposal` models and **not** the
orchestrator or memory store — those are designed and implemented in Week 32 and must remain
*backward-compatible* with the frozen Week-31 shapes. The fitness suite checks:

- structured routing decisions parse against the **frozen minimal routing schema**,
- domain-memory extraction parses against the **frozen minimal memory-extraction schema**,
- basic multi-turn conversational coherence,
- output **schema validity** (the minimal typed contracts parse), and
- a **latency threshold** + graceful failure handling.

If `gemma4:e4b` fails the fitness suite, the env model string is **configurable**, so substituting a
different local Ollama model is a one-line change — **not** a redesign. Acceptance of Week 31 requires the
fitness suite to pass on the configured model (or on a documented substitute).

### 6.4 Connector-mode contract (applies to all three pilots)

External connectors (PR / CI-CD / Analytics sources) are governed by a single explicit env switch,
**default-fixtures**:

| `CONNECTOR_MODE` | Behaviour |
|---|---|
| `fixtures` *(default)* | every pilot reads **deterministic local fixtures**; no outbound connector call, ever — even if real credentials happen to be present in the environment |
| `read_only_live` | a pilot **may** read real provider data, but only under **all** of: an explicit opt-in flag, a provider **allowlist**, **read-only** permission validation, employer/IP authorization, and a Codex audit acceptance |

The presence of credentials **never** flips a pilot from `fixtures` to live — only an explicit
`CONNECTOR_MODE=read_only_live` (plus the guards above) does. No pilot writes to any external system in
either mode (see §12, §14–§16, §24).

---

## 7. Conversational Orchestrator

A **V2 conversation service** that sits *above* the accepted V1 graph. It **preserves** existing
routing/governance and **does not replace** them.

**The orchestrator never executes tools directly.** It only decides one of:

```text
converse        → answer from session context / general knowledge, no workflow
run_workflow    → hand off to the V1 graph (governance + evidence gate apply)
propose_memory  → extract a reusable domain fact as an approval-gated proposal
clarify         → ask the user a question before acting
```

**Rules:**

- Session history is **short-term context**, not permanent truth.
- Reusable domain knowledge becomes a **proposal** (never auto-persisted).
- A memory proposal must be **approved before persistence**.
- Workflow requests go through **existing graph governance**.
- Memory **supplements** evidence but **never bypasses** evidence gates.
- **External and workflow mutations remain blocked / dry-run throughout V2.** Approval may persist
  approved domain memory or mark a draft approved; it never enables connector or production execution.

**Decision contract (typed):** `OrchestratorDecision { action, rationale, payload, confidence,
correlation_id }`. The `rationale` is a short surfaced reason — **never raw chain-of-thought.**

---

## 8. SQLite Domain Memory Authority

**SQLite is the authoritative V2 memory store.** Not Neo4j. (Neo4j is documented as a **V3 derived
knowledge graph only** — see §25.) SQLite is chosen because it gives approval, versioning, rollback, ACID
transactions, and auditability in a single restart-safe file with zero infrastructure.

**Location:** `${ARIA_DATA_DIR}/memory/store.sqlite`, where `ARIA_DATA_DIR` defaults to a gitignored
`.aria_data/` runtime directory (not inside the importable `aria` source package). The runtime DB is
therefore **never** committed and **never** ships in the source tree. In tests `ARIA_DATA_DIR` is
redirected to `tmp_path`, matching V1.1's sink-isolation pattern, so the suite writes no real DB. (`.aria_data/`
is added to `.gitignore` as part of the Week-31 implementation, not in this planning doc.)

### Tables / contracts

**ChatSession** — `session_id`, `owner`, `scope`, `created_at`, `updated_at`

**ChatTurn** — `turn_id`, `session_id`, `role`, `content`, `model`, `task_id`, `correlation_id`,
`timestamp`

**DomainMemoryProposal** — `proposal_id`, `operation` (create/update/delete), `structured_value`,
`source_turn_id`, `owner`, `scope`, `confidence`, `status` (pending/approved/rejected), `created_at`,
`decided_at`

**DomainMemoryVersion** — `memory_id`, `version`, `approved_value`, `source_turn_id`, `proposal_id`,
`owner`, `approver`, `scope`, `created_at`, `superseded_by`, `rollback_target`, `is_active`

**MemoryCitation** — `memory_id`, `version`, `relevant_fields`, `retrieval_reason`

### Lifecycle

```text
casual statement
  → structured proposal
  → display proposal (approval surface)
  → explicit approve / reject
  → transactional SQLite write (on approve)
  → Work Ledger event
  → available for future retrieval (cited)
```

**Worked example (the canonical V2 memory):**

```text
In story_events table, event_type = 1 means page_view, event_type = 2 means story_click,
event_type = 3 means notification_open.
```

ARIA must be able to **propose, approve, persist, cite, version, update, delete, and rollback** this
memory.

### Rules

- **Unapproved memory is never retrieved.** **Rejected memory is never retrieved.**
- **Approved memory is immutable by version.**
- **Updates create a new proposal + a new version** (the prior version is superseded, not edited).
- **Deletions create a proposal + a tombstone/supersede** (audit trail preserved).
- **Rollback restores a prior approved version.**
- **Retrieval cites memory ID and version.**
- **Memory writes and recalls are logged in the Work Ledger.**
- **Scope isolation is required** (a memory in one scope is invisible to another).
- **V2 supports only normal / non-sensitive domain memory.** There is no authenticated identity in this
  single-user pilot, so confidential / restricted memory is **out of scope**: an attempt to *persist* or
  *retrieve* memory marked sensitive/restricted is **rejected** (the proposal is refused, retrieval returns
  nothing) and the refusal is logged as a Work Ledger event. Real confidential-memory support requires a
  future authenticated identity + authorization layer (V3).
- **Caller-supplied actor metadata must never be treated as proof of authorization.** `ARIA_USER_ID`
  (§10) is a *labeling* field for attribution in the ledger — it is **not** authentication and confers no
  privilege. No memory operation may grant access on the basis of a self-declared actor string.

---

## 9. Terminal Chat Upgrade

Upgrade the V1.1 REPL (`apps/backend/aria/chat.py`, run via `uv run python -m aria.chat`) to a
session-aware, streaming, memory-aware terminal.

**V2 behavior:**

- Maintain a **session ID** across turns.
- Show the **active model** (e.g. `Active brain: ollama / gemma4:e4b (local)`).
- Support **multi-turn context**.
- **Stream output progressively** (token-by-token where the provider supports it).
- Show **memory proposals** inline.
- Allow **inline approve / reject** of proposals.
- Show **memory citations** when recalled.
- Show **workflow status** when a workflow runs.
- **Preserve the safe local chat surface policy** (`surface="local_chat"`, `execution_mode="dry_run"`,
  `allow_mutations=False`, cloud off by default).
- **External and workflow mutations stay blocked / dry-run throughout V2** — approval persists approved
  memory or marks a draft approved; it never enables connector or production execution.

The V1.1 offline-by-default and surface-policy guarantees are **kept**; V2 layers session + streaming +
memory on top, it does not loosen them.

---

## 10. FastAPI V2 Streaming Chat

Planned endpoints (localhost pilot only):

```text
POST /api/v2/chat/sessions
POST /api/v2/chat/sessions/{session_id}/messages        ← streams the event body (read via fetch + ReadableStream)
POST /api/v2/memory/proposals/{proposal_id}/decision
GET  /api/v2/memory
GET  /api/v2/memory/{memory_id}/versions
GET  /api/v2/workspaces/{workspace_id}
```

**Streaming events** (ordered; streamed in the **POST response body** and consumed on the client via
`fetch()` + a `ReadableStream` reader — **not** `EventSource`, which is GET-only):

```text
message.started → token* → workflow.started → workflow.completed → memory.proposed
→ approval.required → memory.applied → memory.recalled → artifact.created
→ workspace.updated → message.completed | error
```

(Not every turn emits every event; the contract is the **allowed set and ordering**, not a fixed
sequence.)

**Rules:**

- **Localhost pilot only.**
- **Actor is a configurable *label* only** via `ARIA_USER_ID` (e.g. `human:local`) — **no hardcoded
  personal identity, and it is NOT authentication.** It is recorded for ledger attribution and must never
  be treated as proof of authorization or used to grant access (see §8, P1.2).
- **No raw chain-of-thought** in any event.
- **No raw exception text** in any event (class-only, matching V1.1 redaction).

**Where it attaches:** extends the existing FastAPI app (`apps/backend/voice_api.py` is the current API
surface). The V2 routes are additive; V1 endpoints are untouched.

---

## 11. Minimal ARIAChat Web View

A minimal but usable React view in `apps/frontend/src/` (e.g. `ARIAChat.jsx`, wired into the existing
`App.jsx` view switcher alongside `ROIDashboard.jsx`).

**Features:** conversation history; streaming output; memory proposal cards; approve/reject memory
buttons; memory citation display; workflow status display; artifact card display; approval-required cards;
safe error display; **local-only pilot warning** banner.

**Do not over-polish.** It must be **functional and testable**, not pretty. Schema-driven cards (per the
declarative-UI principle), no raw HTML injection, errors shown redacted. The streaming response is
consumed with `fetch()` + a `ReadableStream` reader over the POST body (**not** `EventSource`).

---

## 12. Approval Inbox / Decision Surface

A single surface (terminal section + web panel + API endpoint) for all V2 approvals:

- Memory approve / reject
- Jira draft approval
- Teams preview approval
- PR comment approval (**draft-only**)
- Workflow mutation (stays blocked / dry-run throughout V2 — approval never enables execution)

**In V2, an approval is a *decision record* — it is NOT an execution trigger for any external system.**
Approving a draft only marks that draft `approved` in the ledger and the workspace; it **never** posts a
PR comment, **never** creates a Jira ticket, **never** sends a Teams message, and **never** writes to any
external system or production database. Jira is draft-only, Teams is preview-only, PR comments are
draft-only — full stop, in both `CONNECTOR_MODE` values (§6.4). External *execution* of an approved draft
is a separate, post-V2 capability that requires its own authorization, connector-write code, and audit —
explicitly out of scope here (§24).

**Every approval record includes:** action type, target system, risk level, evidence, rollback/reversal
note, approver, timestamp, decision, and a **Work Ledger event**.

The **approval UX must exist** now (so a future V2.x can add a separate, audited execution step on top of
an already-governed decision trail rather than retrofitting governance) — but building that UX does **not**
create any external write path in V2.

---

## 13. Persistent Task / Session Workspace

Every serious task creates a **restart-safe** workspace. Storage is split deliberately, with no ambiguity:

- **Workspace metadata lives in SQLite** (the authoritative record): `workspace_id`, task brief, session
  ID, plan, workflow decision, evidence references, memory citations, approvals, ledger references, final
  outcome, and **paths** to any artifact files.
- **Artifact bytes live in a confined runtime directory** under `${ARIA_DATA_DIR}/workspaces/<workspace_id>/`
  (the same gitignored, test-isolated `ARIA_DATA_DIR` as the memory store, §8). Paths are **confined** to
  that directory — the SQLite record references artifact paths; it never stores or resolves arbitrary
  filesystem locations.

This is the V1-attach-point realisation of §26.8 (Generative UI Canvas) / §28.4 #4 (Persistent Workspace)
— minimal, local, single-user. It must survive a process restart (reopen by `workspace_id`), and in tests
the whole `ARIA_DATA_DIR` tree is redirected to `tmp_path` so no real workspace files are written.

---

## 14. Read-only PR Review Pilot

**Read-only. Draft-only. Fixtures by default (`CONNECTOR_MODE=fixtures`, §6.4).**

- Read PR metadata from a **local fixture** by default; read real PR metadata **only** under
  `CONNECTOR_MODE=read_only_live` with all §6.4 guards. Credential presence alone never enables live reads.
- Summarize changes; identify risk; **draft** review comments; **draft** a Jira ticket.
- **No posting comments. No write actions.** Work Ledger trace for the whole run.

Reuses the existing `pr_review` skill through the V1 graph; the pilot adds the read-only reader + fixture
fallback + draft surfacing, not a new review engine.

---

## 15. Read-only CI/CD Investigation Pilot

**Read-only. Draft-only. Fixtures by default (`CONNECTOR_MODE=fixtures`, §6.4).**

- Read a workflow run / log **fixture** by default; read real read-only provider data **only** under
  `CONNECTOR_MODE=read_only_live` with all §6.4 guards.
- Diagnose the failure; summarize impact; suggest a fix; create a **Teams message preview**.
- **No sending. No rerun.** Work Ledger trace.

Reuses the existing `ci_cd` skill; the evidence gate still governs claims.

---

## 16. Read-only Analytics/KPI/Events Pilot

**Read-only. Draft-only. Fixtures by default (`CONNECTOR_MODE=fixtures`, §6.4).** This is the pilot that
exercises domain memory.

- Read an **approved schema / query fixture** by default; read a real read-only data source **only** under
  `CONNECTOR_MODE=read_only_live` with all §6.4 guards.
- **Use approved domain memory automatically** (e.g. the `story_events.event_type` mapping) — cited.
- Run checks: **schema, freshness, nulls, duplicates, taxonomy, funnel consistency, anomalies.**
- Produce a **cited action report** + a **Jira draft.**
- **No database mutation.**

Critically: memory is used to *interpret* the data (what `event_type=2` means) but the **evidence gate
still governs the claims** — memory is not an evidence substitute.

> **Fixture guarantee (all three pilots):** by default (`CONNECTOR_MODE=fixtures`) each pilot runs against
> **deterministic local fixtures**, regardless of whether credentials are present. A pilot reads real data
> **only** when `CONNECTOR_MODE=read_only_live` is explicitly set with all §6.4 guards. No pilot fails
> *only* because credentials are absent, and no pilot goes live *merely* because credentials are present.

---

## 17. Work Ledger Events

V2 **reuses the existing ledger taxonomy wherever an event already exists**, and adds new `event_type`
values **only** for genuinely new concepts (conversation, memory lifecycle, workspace, read-only
connector). The existing taxonomy in `apps/backend/aria/ledger/events.py` already includes
`task_created`, `routed`, `skill_invoked`, `artifact_created`, `approval_requested`, `approved`,
`rejected`, `action_taken`, `failed`, `responded`, `outcome_recorded`, `correction_recorded`,
`model_used`, `cost_recorded`, and `model_lifecycle`.

**Reused events — add V2 metadata, do NOT duplicate** (no new `event_type` for these):

| Concept | Reused event | V2 metadata added |
|---|---|---|
| A memory proposal **or** a draft is queued for a human decision | `approval_requested` | `proposal_id` / `memory_id`, `kind` (`memory` / `jira_draft` / `teams_preview` / `pr_draft`) |
| The human **decision** on any approval (memory, Jira, Teams, PR) | `approved` / `rejected` | same subject metadata — **no** new `approval_decided` / `memory_approved` / `memory_rejected` event |
| A generated draft / report / preview artifact | `artifact_created` | `workspace_id`, `kind` |
| Model name / latency / token usage / cost of a turn | `model_used` / `cost_recorded` | `session_id`, `correlation_id` |
| Final response of a turn | `responded` | `session_id` |

**New V2 events — genuinely new concepts only:**

```text
conversation_started   message_received          workflow_invoked
memory_proposed        memory_applied            memory_recalled
memory_superseded      memory_deleted            memory_rolled_back
workspace_created      workspace_updated         read_only_connector_invoked
```

(`workflow_invoked` is the **orchestrator-level** hand-off to the V1 graph — distinct from the graph's own
`routed` / `skill_invoked`. The memory-lifecycle events record **memory-store state transitions**, which
are *not* approvals; the approval decision itself reuses `approval_requested` + `approved` / `rejected`
above.)

**Fields** (superset; not every event sets every field): `task_id`, `session_id`, `correlation_id`,
`workflow_id`, `actor`, `model`, `duration`, `token_count`, `cost`, `risk`, `memory_id`, `memory_version`,
`proposal_id`, `kind`, `connector`, `workspace_id`, `scope`, `outcome`.

**Rules (ledger-enforced invariants):**

- Memory **cannot** authorize a production mutation.
- Memory **cannot** bypass evidence gates.
- Retrieved memory **must** be cited.
- Approvals **must** be auditable.
- Secrets redacted; raw exception text never surfaced.

**Attach-point reuse:** `correlation_id` + `actor` already exist on every ledger event (built in Week 29
specifically so conversation/memory/subagent traces plug in with **no migration**). V2 adds new
`event_type` values and the few new optional fields; the writer/reader schema-version bump handles
forward-compat exactly as the v1→v2 ledger migration did.

---

## 18. Five-Milestone Implementation Plan

```text
Week 31 — Local-Intelligence Foundation (six narrowed items; no conversation/memory/API/UI/connector yet)
Week 32 — Conversational Orchestrator + SQLite Domain Memory (finalize memory schema here)
Week 33 — Streaming Terminal/Web Chat + Approval Inbox + Workspace (finalize approval policy + workspace here)
Week 34 — Read-only PR + CI/CD + Analytics Pilots
Week 35 — Hardening + Full E2E Demo + Codex V2 Acceptance
```

These are **five implementation milestones**, not fixed calendar weeks; Codex acceptance gates each one
before the next lane opens (§26).

### Week 31 — Local-Intelligence Foundation (narrowed scope)

**Week 31 is deliberately narrow.** Its only goal is a Codex-auditable local-intelligence foundation. It
covers **exactly these six items** — no conversation, memory, API, frontend, or connector implementation
begins until Codex accepts Week 31:

1. **Explicit execution-mode contract** — implement the three named modes (`offline_mock`, `local_ollama`,
   `cloud_opt_in`, §6.1); default is offline; escalation to cloud is explicit-only, never a fallback.
2. **Ollama readiness boundary** — readiness checks run at chat/API startup or an explicit
   command/endpoint, **never at import** (§6.2); importing `aria.*` contacts no daemon.
3. **`gemma4:e4b` installation + fitness verification (incl. frozen eval-only schemas)** — verify the tag
   resolves locally (`ollama list` / `ollama show gemma4:e4b` or the API equivalent); **freeze the two
   minimal, evaluation-only JSON schemas** (routing-decision + memory-extraction shapes) that the fitness
   suite asserts against — these are *compatibility contracts* for Week 32, **not** the full
   `OrchestratorDecision` / `DomainMemoryProposal` models and **not** the orchestrator or memory store;
   then **pass the §6.3 model-fitness suite** against them (routing JSON, memory extraction, multi-turn
   coherence, schema validity, latency/failure) — or configure a documented substitute model.
4. **Structural no-cloud-fallback enforcement** — a failed/absent local model surfaces a controlled error
   including `ollama pull <configured-model>` (default → `ollama pull gemma4:e4b`); it never auto-downloads and never falls back to a cloud provider.
5. **Model telemetry events** — record model name, latency, token count (where available), and failures in
   the Work Ledger (reusing `model_used` / `cost_recorded`, §17).
6. **V1/V1.1 regression + adversarial network tests** — V1 (`abf0096`) and V1.1 (`d199a51`) suites stay
   green with no Ollama installed (tests run `offline_mock`); adversarial tests set fake cloud credentials
   and assert zero cloud calls occur (sockets/cloud clients blocked).

The V2 branch is created (only after plan acceptance, and only when explicitly asked) as a precondition,
not a deliverable. **Deliverable:** local-intelligence foundation accepted by Codex.

> Scope boundary on schemas: Week 31 freezes **only** the two *minimal, evaluation-only* JSON shapes
> (routing-decision + memory-extraction) needed to validate model fitness — these are compatibility
> contracts, not implementations. **Full** schema/contract finalization is **not** a Week 31 item: the full
> SQLite memory schema + `DomainMemoryProposal` / `OrchestratorDecision` models are finalized and
> implemented in Week 32 (and must stay backward-compatible with the frozen Week-31 shapes); the approval
> policy + workspace design are finalized in Week 33. Ledger `event_type` additions land in the week that
> first emits them.

### Week 32 — Conversational Orchestrator + Domain Memory

- **Backend:** conversation service; typed decision engine; session persistence; SQLite memory authority;
  memory proposal extraction; approve/reject lifecycle; immutable versions; rollback/delete/update. The
  full `OrchestratorDecision` / `DomainMemoryProposal` models must stay **backward-compatible with the
  minimal eval-only schemas frozen in Week 31** (§6.3).
- **Terminal:** session-aware terminal chat; multi-turn context; memory proposal display; inline
  approve/reject.
- **Tests:** session turns; `propose_memory`; approval-required; rejection excludes retrieval;
  approved-retrieval-with-citation; restart survival; rollback.
- **Deliverable:** approved domain memory works end-to-end in the terminal.

### Week 33 — Streaming + API + Web + Approval Inbox + Workspace

- **Backend:** FastAPI V2 chat/session endpoints; streaming events (POST body, read via fetch + ReadableStream); memory proposal decision
  endpoint; memory list/version endpoints; workspace creation/update; approval decision service.
- **Frontend:** minimal ARIAChat view; streaming output; memory proposal cards; approval buttons; memory
  citations; workflow/artifact cards.
- **Tests:** streaming event order; disconnect handling; safe errors; terminal/web parity; approval decision
  logging; workspace restart safety.
- **Deliverable:** terminal + web chat both support conversation, memory proposal, approval, citation.

### Week 34 — Read-only PR + CI/CD + Analytics Pilots

- **PR:** read-only PR/local-fixture reader; PR summary; risk findings; draft review comments; Jira draft.
- **CI/CD:** read-only log/local-fixture reader; failure diagnosis; impact summary; fix suggestion; Teams
  preview.
- **Analytics:** schema/query fixture reader; event data-quality checks; approved-memory recall; cited
  action report; Jira draft.
- **Governance:** no write actions; approval required for drafts; evidence gates preserved; Work Ledger
  traces.
- **Tests:** no external writes; fixture fallback; evidence citations; memory-used-but-not-as-evidence;
  Jira/Teams/PR outputs draft-only.
- **Deliverable:** three read-only pilot workflows work through chat/web.

### Week 35 — Hardening + Full Internal-Pilot Demo + Codex Acceptance

- **Hardening:** full backend regression; frontend tests/build; prompt-injection tests; secret redaction;
  memory scope isolation; connector read-only enforcement; runtime-pollution check; public-safety check.
- **Demo:** V2 full demo script; V2 proof checklist; fresh-clone setup; end-to-end demo notes;
  manager-ready summary.
- **Deliverable:** Codex V2 acceptance audit.

---

## 19. End-to-End Proof

The acceptance demo (must run on a fresh clone, locally, no cloud):

1. Start ARIA local chat.
2. Tell ARIA the `story_events.event_type` mapping.
3. ARIA **proposes** memory.
4. User **approves.**
5. Memory is **persisted in SQLite.**
6. **Restart** ARIA.
7. Ask what `event_type` means.
8. ARIA **recalls** with a **memory citation.**
9. Ask for a `story_events` investigation.
10. ARIA uses approved memory, runs the **read-only analytics fixture**, creates a **cited report** + a
    **Jira draft.**
11. Ask for a CI/CD failure investigation → ARIA reads fixture/logs, creates a diagnosis + **Teams
    preview.**
12. Ask for a PR review → ARIA reads the PR fixture/repo data, creates a **review draft.**
13. Work Ledger and workspace show the **full trace.**

---

## 20. Test Plan

**Local model:** Ollama unavailable; model unavailable; strict no-cloud-fallback; credentials-present-but-
no-cloud-call; explicit cloud opt-in boundary; latency/token/failure logging.

**Conversation:** session creation; multi-turn context; `clarify`/`converse`/`run_workflow`/
`propose_memory` decisions; graph governance preserved.

**Memory:** proposal extraction; approval-required; rejection-prevents-retrieval; unapproved-prevents-
retrieval; approved-retrieval-with-citation; update/delete/rollback; restart survival; concurrent SQLite
transactions; scope isolation.

**Streaming / API:** streaming event order; disconnect; timeout; safe errors; memory-approval endpoint;
terminal/web parity.

**Web:** conversation renders; token stream renders; memory proposal approval/rejection; citations render;
errors redacted.

**Workspace:** created per serious task; persisted; contains artifacts/evidence/approvals/ledger refs;
restart-safe.

**Pilots:** PR read-only; CI/CD read-only; Analytics read-only; fixture fallback when credentials absent;
no writes; draft-only Jira/Teams/PR actions.

**Governance / security:** prompt injection cannot approve memory; prompt injection cannot bypass evidence
gate; memory cannot authorize mutation; secret redaction; no raw exception text; runtime logs isolated in
tests.

**Regression:** V1 green; V1.1 green; full backend green; frontend green.

---

## 21. Acceptance Checklist

V2 is complete **only** when **all** hold:

- [ ] Local Gemma/Ollama works
- [ ] `gemma4:e4b` availability is verified at startup, or fails clearly with `ollama pull <configured-model>` (default → `gemma4:e4b`)
- [ ] `gemma4:e4b` passes the §6.3 model-fitness suite (or a documented substitute model is configured)
- [ ] Execution modes are explicit (`offline_mock` / `local_ollama` / `cloud_opt_in`); cloud is opt-in only
- [ ] Readiness checks never run at import; V1/V1.1 suite passes with no Ollama installed
- [ ] No-cloud-fallback is proven (even with cloud creds present)
- [ ] Multi-turn terminal chat works
- [ ] Streaming works
- [ ] FastAPI V2 chat works
- [ ] Minimal web chat works
- [ ] Memory proposals work
- [ ] Memory approval/rejection works
- [ ] SQLite memory persists after restart
- [ ] Update/delete/rollback works
- [ ] Memory citations appear in answers
- [ ] Work Ledger traces conversation + memory + workflows
- [ ] Task workspace persists artifacts/evidence/approvals
- [ ] `CONNECTOR_MODE` defaults to `fixtures`; credential presence alone never enables a live read
- [ ] Approval is a decision record only — approving never posts/creates/sends to any external system
- [ ] Sensitive/restricted memory is rejected on persist and retrieve (no authenticated identity in V2)
- [ ] `ARIA_USER_ID` is a label only — never treated as authentication/authorization
- [ ] Runtime data (memory DB, workspaces) lives under gitignored `ARIA_DATA_DIR`; tests redirect to `tmp_path`
- [ ] PR read-only pilot works
- [ ] CI/CD read-only pilot works
- [ ] Analytics read-only pilot works
- [ ] Jira/Teams/PR actions are draft-only
- [ ] No production writes occur
- [ ] Evidence gates remain intact
- [ ] V1/V1.1 tests remain green
- [ ] Full backend and frontend tests pass
- [ ] Codex accepts V2

---

## 22. Codex Audit Checklist

What an independent auditor should be able to verify without trusting our word:

- **No-cloud-fallback is structural, not documented:** a test sets fake `OPENAI_API_KEY` /
  `ANTHROPIC_API_KEY` and asserts zero cloud calls occur in default local mode; sockets/cloud clients are
  blocked and the run still succeeds (or fails loudly with the `ollama pull` message).
- **Readiness is not import-coupled:** importing `aria.*` contacts no Ollama daemon; the V1/V1.1 suite
  passes with no Ollama installed (it runs in `offline_mock`).
- **Model-fitness is gated:** Week 31 acceptance shows the configured model passing the §6.3 fitness suite
  (or a documented substitute) — presence of the tag alone is not sufficient.
- **Connector mode is fixtures-by-default:** with real credentials present but `CONNECTOR_MODE` unset (or
  `fixtures`), pilots make **zero** outbound connector calls — proven by test, not by inspection.
- **Approval is a decision record, not execution:** approving a draft emits `approved` and updates the
  workspace/ledger but triggers **no** external write — a test asserts no Jira/Teams/PR/network call occurs
  on approval.
- **`ARIA_USER_ID` is not authorization:** a self-declared actor string grants no access; sensitive/
  restricted memory persist + retrieve are rejected because V2 has no authenticated identity.
- **Runtime data is isolated and uncommitted:** the memory DB and workspaces live under gitignored
  `ARIA_DATA_DIR` (not in the `aria` source package); the test suite redirects `ARIA_DATA_DIR` to
  `tmp_path` and writes nothing real.
- **Unapproved/rejected memory is never retrievable:** retrieval queries return nothing for
  pending/rejected proposals — proven by test, not by inspection.
- **Memory is immutable by version; rollback restores a prior version** — proven by a version-history
  assertion across update → rollback.
- **Memory cannot authorize mutation and cannot bypass the evidence gate** — a memory that "explains" a
  KPI does not let an unsupported KPI claim through.
- **Restart-safety:** kill the process, reopen, recall the memory + reopen the workspace by ID.
- **Surface policy preserved:** every V2 chat request still carries `execution_mode=dry_run` /
  `allow_mutations=False`; mutations are blocked/dry-run.
- **Redaction:** secrets and raw exception text never appear in API events, ledger, web, or terminal.
- **Test isolation:** running the V2 suite writes nothing to real runtime sinks (ledger/memory/audit/
  notifier/SQLite all redirected to `tmp_path`).
- **Regression:** V1 (`abf0096`) + V1.1 (`d199a51`) suites remain green; full backend + frontend green.
- **No forbidden scope present:** no vLLM, no real training/deployment, no subagent engine, no
  multi-tenancy, no production writes, no cloud fallback, no Neo4j-as-authority (grep/structure check).

---

## 23. Risks and Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Wrong Ollama tag** (`gemma4:e4b` not a real/pulled tag) | Med | Med | Treated as a **verified-at-implementation configuration**, not an assumption: Week 31 runs `ollama list` / `ollama show gemma4:e4b` on day 1; startup availability check fails loudly with the exact `ollama pull <configured-model>` command (default → `ollama pull gemma4:e4b`); env string is configurable, so a corrected tag is a one-line change, not a redesign. |
| 2 | **Week 33 overload** (streaming + API + web + inbox + workspace in one week) | High | High | This is the aggressive-by-design week. Mitigate by **front-loading, not deferring**: freeze the streaming event contract at end of Week 32 so the frontend lane starts on Week 33 day 1; build API + terminal parity first so the web view consumes a proven contract; absorb pressure with extra parallel hours. **No Week-33 deliverable is dropped or pushed to V2.x** — all are required V2 items. |
| 3 | **Silent cloud fallback creeps back** via a library default | Med | High | No-cloud-fallback test with cloud creds present is a **merge gate**; reuse `offline_scope()` discipline; block sockets in tests. |
| 4 | **Local model quality** too weak for multi-turn / extraction on Gemma | Med | Med | Memory extraction is **proposal-only + human-approved**, so model weakness degrades convenience, not safety; keep prompts structured; cloud opt-in exists as an explicit escape hatch (never silent). |
| 5 | **SQLite concurrency** under streaming + approvals | Low | Med | Single-user pilot; use transactions + WAL; explicit concurrent-transaction test in the plan. |
| 6 | **Memory used as evidence** by accident | Med | High | Hard rule + dedicated test: a memory-explained KPI claim still must pass the evidence gate. |
| 7 | **Streaming leaks chain-of-thought / exception text** | Med | High | Event schema forbids raw CoT/exception text; redaction tests on every streaming event. |
| 8 | **Scope creep into V2.x** (someone enables a real write "just to try") | Med | High | §24 "must not" list is a merge gate. V2 has **no external write path at all**: approval is a decision record, not an execution trigger (§12); `CONNECTOR_MODE` defaults to `fixtures` and credential presence never flips to live (§6.4); a test asserts no external call occurs on approval. |
| 9 | **Regression in V1/V1.1** from the orchestrator layer | Low | High | Orchestrator sits *above* the unchanged graph; V1/V1.1 suites are merge gates every week. |

---

## 24. What V2 Must Not Claim (and Must Not Build)

Even in this complete five-milestone V2 internal-pilot scope, **do not implement**: production writes;
automatic Jira creation; automatic Teams sending; automatic PR posting; production database mutation;
vLLM; real fine-tuning; subagent architecture; multi-tenancy; Agent-as-a-Service commercialization; public
release; production deployment; **cloud fallback**; **Neo4j as authoritative memory.**

**Also explicitly forbidden (governance, not just features):**

- **Approval-triggered external execution** — an approval must never post/create/send to an external
  system. Approval is a *decision record* only (§12).
- **Treating `ARIA_USER_ID` (or any caller-supplied actor string) as authentication or authorization** —
  it is a ledger label only (§8, §10).
- **Credentials auto-activating live connectors** — only an explicit `CONNECTOR_MODE=read_only_live` (with
  all §6.4 guards) reads real data; presence of credentials must never flip a pilot to live (§6.4).
- **Confidential / restricted (sensitive) memory** — out of scope without an authenticated identity;
  sensitive persist/retrieve must be rejected (§8).
- **Import-time daemon probing or auto-download** — readiness runs at startup only; never auto-pull a
  model (§6.2).

**V2 must not claim** to be: a deployed product, a live integration, a fine-tuned/served model, a
multi-tenant platform, or anything publicly released. V2 is a **local, single-user, read-only/draft-only
internal pilot.**

---

## 25. What Remains V3

- **Neo4j as a derived knowledge graph** — built *from* approved SQLite memory versions (SQLite stays the
  authority; Neo4j is a downstream projection for multi-hop reasoning). **Documentation-only in V2.**
- vLLM serving + real fine-tuning + deployment; Model Router v3 to a self-hosted specialist.
- §28.1 Subagent Instruction Engine; live connectors (real Jira/Teams/GitHub writes); agent identity /
  delegated authorization; A2A envelopes; security gateway; episode packages.
- Multi-tenant AI Employee as a Service (Pillar 23); AI Capability Marketplace (Pillar 22); agent
  branching/experiments; routine T4/T5 autonomy.

**Neo4j note (locked):** SQLite remains authoritative for V2 memory because it handles approval,
versioning, rollback, transactions, and auditability. Neo4j is a V3 *derived* graph only.

---

## 26. Implementation Branch Plan

- **Branch name:** `v2-complete-internal-ai-employee-pilot`
- **Created from:** the **latest accepted planning commit on `master`** — i.e. the commit that sits on top
  of V1.1 (`d199a51`), the V1 release capsule (`3157012`), and **this V2 plan once it is committed** — not
  from a hypothetically clean `d199a51` tree. The exact base is whatever `master` HEAD is at the moment the
  branch is cut. **Create it only after this plan is accepted, and only when explicitly asked.** Do not
  create it now.
- **First milestone:** the narrowed **Week 31 Local-Intelligence Foundation** (§18) — execution-mode
  contract + readiness boundary + `gemma4:e4b` install/fitness + no-cloud-fallback enforcement + model
  telemetry + V1/V1.1 regression and adversarial network tests, all green. This is the smallest slice that
  is independently Codex-auditable and de-risks the single most important V2 claim ("local, no cloud")
  before any conversation/memory code is written.
- **Cadence:** one Codex acceptance gate per week (Weeks 31–35); do not start the next week's lane until
  the prior week's deliverable is green. Commit only when explicitly asked.

---

*Cross-references: `CLAUDE.md` (§2 versions, §10–14 governance, §26 harness layers, §28 future vision);
`docs/week30_v1_v2_v3_boundary.md` (the V1/V2/V3 bright lines this plan must not blur);
`docs/local_chat.md` (V1.1 surface policy this plan preserves and extends).*
