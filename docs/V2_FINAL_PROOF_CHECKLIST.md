# ARIA V2 — Final Proof Checklist (Week 35)

**Branch:** `v2-complete-internal-ai-employee-pilot`
**Status:** V2 internal AI-employee pilot — hardened, integrated, demo-ready. Awaiting Codex final acceptance audit.
**Scope of V2:** a **local, internal, read-only / draft-only** AI-employee pilot. No production deployment, no external writes, no public release.

This document is the single per-week evidence ledger for V2. Every claim below is backed by a test, a demo, or a file. Where something is *not* built, it is named explicitly in the "Must Not Claim" section.

---

## 0. One-command proof

```bash
cd apps/backend
uv run python -m aria.demo.v2_full_pilot          # offline, deterministic, self-cleaning
```

Runs the entire V2 loop with **no cloud credentials and no live connectors** (`CONNECTOR_MODE=fixtures`, all provider keys stripped): start session → teach a canonical fact → ARIA proposes memory → human approves → persist in SQLite → **restart** → recall with a `memory_id` + version citation → analytics pilot (memory explains values, fixtures prove counts) → CI/CD pilot (Teams preview only) → PR pilot (review + Jira drafts only) → workspace with artifacts/citations/drafts → Work Ledger trace → explicit boundary statement. The demo writes only to a throwaway temp dir and deletes it on exit.

---

## 1. Per-week accepted scope + evidence

| Week | Commit | Accepted scope | Primary evidence |
|---|---|---|---|
| 31 — Local intelligence foundation | `9ddc906` | Execution-mode contract (`offline_mock` default, no cred escalation), local LLM readiness (Ollama opt-in, never auto-download / auto-fallback), redaction plumbing | `tests/` Week 31 suite; `aria/llm/execution_mode.py`, `aria/llm/readiness.py` |
| 32 — Conversational orchestrator + domain memory | `f73edd7` | Multi-turn session orchestrator; SQLite domain-memory authority (propose → approve → version → recall, supersede, rollback, tombstone); sensitive-memory refusal; transactional **audit outbox** (state + ledger never diverge) | Week 32 suite; `aria/conversation/orchestrator.py`, `aria/memory_v2/store.py`, `aria/memory_v2/audit.py` |
| 33 — Chat API + web chat + approval inbox + workspace | `0ae5a77` | FastAPI V2 (NDJSON streaming chat, memory decision, memory/version/workspace reads); approval **decision record** (no external action); persistent workspace store; React web chat + approval inbox | Week 33 suite + `apps/frontend` vitest; `aria/api/v2.py`, `aria/conversation/approval.py`, `aria/memory_v2/workspace.py`, `apps/frontend/src/ARIAChat.jsx` |
| 34 — Read-only pilots | `546c12d` | Read-only connector layer (fixtures-first, live scaffold fail-closed); analytics / CI-CD / PR pilots (evidence-disciplined, draft-only); pilot events through the workspace transactional outbox in causal order | Week 34 suite; `aria/connectors/*`, `aria/pilots/*` |
| 35 — Hardening / integration / proof (this week) | *(uncommitted)* | Full E2E demo `aria.demo.v2_full_pilot`; runtime-isolation + safety regression tests; 5 acceptance docs | `tests/test_week35_v2_demo.py` (21 tests); `aria/demo/v2_full_pilot.py`; this doc set |

No new product capability was added in Week 35 — only the demo, tests, and documentation that prove the four prior weeks integrate and stay governed.

---

## 2. Test counts and baselines

| Suite | Command | Result |
|---|---|---|
| Backend (full) | `cd apps/backend && uv run pytest -q` | **1206 passed, 1 skipped** |
| — of which Week 35 | `uv run pytest tests/test_week35_v2_demo.py -q` | **22 passed** |
| Week 31–35 slice | `uv run pytest -k "week31 or week32 or week33 or week34 or week35"` | **158 passed** |
| Frontend (unit) | `cd apps/frontend && npx vitest run` | **33 passed** (3 files) |
| Frontend (build) | `cd apps/frontend && npm run build` | **OK** — 36 modules, `dist/` produced |
| V2 demo | `cd apps/backend && uv run python -m aria.demo.v2_full_pilot` | **OK** — execution mode pinned `offline_mock`, 13 ledger event types, temp state cleaned |

Baseline before Week 35: backend 1184 passed / 1 skipped, frontend 33 passed. Week 35 adds 22 backend tests → 1206, with no regressions.

---

## 3. What is built vs draft-only vs read-only vs blocked

**Built and working (local, internal):**
- Multi-turn conversation with session + turn persistence (SQLite under `ARIA_DATA_DIR`)
- Domain-memory authority: propose → approve → versioned persist → recall-with-citation, supersede, rollback, delete (tombstone)
- Memory survives process restart (proved by the demo's restart step)
- Three read-only investigation pilots: analytics, CI/CD, PR review
- Persistent per-session workspace accumulating report artifacts, citations, draft references
- Work Ledger v2 trace covering the full causal chain
- FastAPI V2 + React web chat + approval inbox

**Read-only:**
- All connectors. `fixtures` mode is the only fully-implemented mode (no network). The `read_only_live` mode is a fail-closed scaffold with no write methods anywhere, in any mode.

**Draft-only (never executed):**
- Jira tickets → drafts only ("Draft only. Not posted.")
- Teams messages → previews only (not sent)
- PR comments → review drafts only (not posted)

**Approval is decision-only:**
- Approving a memory proposal records an auditable **decision record** targeting internal `domain_memory`. It does not trigger any external action.

**Fixture-default:**
- `CONNECTOR_MODE` resolves to `fixtures` when unset/blank/unknown. Credentials never change the mode.

**Blocked / not in V2:**
- Public GitHub / LinkedIn publication — **BLOCKED pending employer/IP approval.** All public-safe artifacts are drafts only.

**V3-only (documented vision, not implemented):**
- Live external writes, multi-tenancy / AaS, vLLM serving, real fine-tuning / model deployment, subagent architecture, external-agent meta-harness runtime.

---

## 4. Public release warning

⚠️ **Nothing in this branch is approved for public release.** ARIA is built inside an employment context (Amar Ujala) and is subject to employer/IP review. The manager reveal, any LinkedIn post, and any public GitHub push are **blocked until that review completes**. The "public-safe" framing in earlier launch docs describes *drafts*, not published material.

---

## 5. Must Not Claim (hard boundary list)

The following are **false** for V2 and must never be claimed in a demo, doc, summary, or post:

- ❌ "ARIA is deployed to production" — it is a local internal pilot only.
- ❌ "ARIA executes actions autonomously in production" — every action is read-only or a draft awaiting human decision.
- ❌ "ARIA created a Jira ticket / sent a Teams message / posted a PR comment" — these are drafts/previews only; nothing is sent.
- ❌ "ARIA reran a pipeline / mutated a production database" — no write methods exist in any connector mode.
- ❌ "ARIA was fine-tuned / a model was trained" — no real training occurred (V2 has none; the Week 29 prototype was an offline dry-run).
- ❌ "ARIA serves a self-hosted model via vLLM" — no vLLM serving exists.
- ❌ "ARIA is multi-tenant / sold as a service" — single local instance only.
- ❌ "ARIA runs an external-agent meta-harness at runtime" — that is V3 documentation only.
- ❌ "Approval triggered an external action" — approval records a decision only.
- ❌ "ARIA is public / open-sourced / posted on LinkedIn" — publication is blocked pending employer/IP approval.

---

## 6. Cross-references

- Setup & reproduction: [`V2_FRESH_CLONE_SETUP.md`](V2_FRESH_CLONE_SETUP.md)
- Safety & boundary audit: [`V2_SAFETY_AND_BOUNDARY_AUDIT.md`](V2_SAFETY_AND_BOUNDARY_AUDIT.md)
- Manager-facing summary: [`V2_MANAGER_SUMMARY.md`](V2_MANAGER_SUMMARY.md)
- Codex acceptance package: [`V2_CODEX_ACCEPTANCE_PACKAGE.md`](V2_CODEX_ACCEPTANCE_PACKAGE.md)
