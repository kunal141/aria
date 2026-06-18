# ARIA V2 — Codex Acceptance Package

Single-document audit surface for the V2 internal AI-employee pilot. Everything an
auditor needs to verify scope, reproduce the proof, and confirm the boundaries.

---

## 1. Branch & commits

- **Branch:** `v2-complete-internal-ai-employee-pilot`
- **Accepted, committed weeks:**

  | Week | Commit | Title |
  |---|---|---|
  | 31 | `9ddc906` | feat(v2-week31): add local intelligence foundation |
  | 32 | `f73edd7` | feat(v2-week32): add conversational orchestrator and domain memory |
  | 33 | `0ae5a77` | feat(v2-week33): add chat API, web chat, approval inbox, and workspace |
  | 34 | `546c12d` | feat(v2-week34): add read-only pilot workflows |

- **Week 35 (this package):** uncommitted on the branch — full E2E demo, runtime
  isolation + safety tests, and these five acceptance docs. **No new product scope.**
  Commit only on request.

---

## 2. Scope of V2 (what was built)

A local, internal, **read-only / draft-only** AI-employee pilot:

- Multi-turn conversation with session/turn persistence.
- Domain-memory authority: propose → human approve → versioned persist → recall with
  citation; supersede, rollback, delete (tombstone); survives process restart.
- Three read-only investigation pilots: analytics, CI/CD, PR review.
- Persistent per-session workspace (report artifacts, citations, draft references).
- FastAPI V2 (NDJSON streaming chat, memory decision, memory/version/workspace reads)
  + React web chat + approval inbox.
- Work Ledger v2 trace across the full causal chain, via a transactional outbox.

**Not built (out of V2 scope):** live external writes, multi-tenancy/AaS, vLLM
serving, real fine-tuning/model deployment, subagent architecture, external-agent
meta-harness runtime, public release automation. See §8.

---

## 3. Architecture (one screen)

```
Browser (React: ARIAChat + approval inbox)        Terminal (aria.chat / demo)
            │  /api/v2 (NDJSON)                              │
            ▼                                                ▼
   FastAPI V2  (aria/api/v2.py)  ── per-request fresh components (SQLite thread-affinity)
            │
            ▼
   ConversationOrchestrator (aria/conversation/orchestrator.py)
     ├─ decide(): converse | run_workflow | propose_memory | clarify
     ├─ DomainMemoryStore (aria/memory_v2/store.py)  ── SQLite authority + audit OUTBOX
     ├─ ApprovalService (aria/conversation/approval.py)  ── decision record only
     ├─ PilotService (aria/pilots/service.py)  ── read-only pilots, draft-only outputs
     │     └─ Connectors (aria/connectors/*)  ── fixtures (default) | read_only_live (fail-closed)
     └─ WorkspaceStore (aria/memory_v2/workspace.py)  ── artifacts/citations/drafts + audit OUTBOX
            │
            ▼
   Work Ledger v2  (aria/ledger/*, ARIA_LEDGER_V2_PATH)  ── append-only, idempotent, redacted
```

All runtime state under `ARIA_DATA_DIR` (gitignored) + the v2 ledger file (gitignored).

---

## 4. How to verify (commands)

```bash
# backend
cd apps/backend
uv sync
python -m compileall aria                       # syntax
uv run pytest -q                                # 1206 passed, 1 skipped
uv run pytest tests/test_week35_v2_demo.py -q   # 22 passed (demo E2E + isolation + safety)

# the headline demo (offline, deterministic, self-cleaning)
uv run python -m aria.demo.v2_full_pilot

# frontend
cd ../frontend
npm install
npx vitest run                                  # 33 passed
npm run build                                   # OK (dist/)

# isolation
cd ../..
git status --short                              # clean after demo/tests
```

---

## 5. Demo proof points (`aria.demo.v2_full_pilot`)

1. Start a session.
2–3. Teach a canonical fact (`event_type = 1 → page_view`, …); ARIA proposes memory.
4–5. Human approves; memory persists in SQLite (versioned).
6. **Restart** (fresh app + fresh DB connections, same `ARIA_DATA_DIR`).
7–8. Recall after restart with a `memory_id` + version **citation**.
9–12. Analytics pilot: memory explains values, **fixture evidence** proves counts,
draft Jira created (draft-only).
13–14. CI/CD pilot: diagnosis + **Teams preview** (not sent).
15–16. PR pilot: review comments + Jira drafts (**not posted**).
17. Workspace holds 3 report artifacts + citations + 7 draft references.
18. Work Ledger trace covering: `conversation_started, message_received,
memory_proposed, approval_requested, approved, memory_applied, memory_recalled,
workflow_invoked, read_only_connector_invoked, pilot_report_created,
draft_action_created, workspace_created, workspace_updated`.
19. Explicit boundary statement (no external writes / Jira / Teams / PR / live
connector / vLLM / training / deployment).

---

## 6. Boundaries & safety controls (summary)

Full matrix in [`V2_SAFETY_AND_BOUNDARY_AUDIT.md`](V2_SAFETY_AND_BOUNDARY_AUDIT.md).
Key controls, each test-backed:

- No production writes (no write methods in any connector mode).
- `CONNECTOR_MODE` defaults to `fixtures`; **credentials never activate live**.
- `read_only_live` fails closed (explicit mode + allowlist) and is still inert
  (`NotImplementedError`).
- Approval is a **decision record** (`target_system=domain_memory`), not an action.
- Sensitive memory **refused** (no identity layer); `ARIA_USER_ID` is attribution-only.
- **No cloud fallback**: default `offline_mock`; cloud only via explicit `cloud_opt_in`.
- Memory **does not bypass the evidence gate** (counts need fixture evidence).
- Errors **redacted** (code + sanitised detail; class-only on the stream path).
- State + audit cannot diverge (transactional outbox).

---

## 7. Artifact / workspace behaviour

- Workspaces are per session; each serious turn (memory citation, pilot run) records
  references into the same workspace.
- Workspace responses expose **references and safe metadata only** — relative artifact
  refs, citation envelopes, draft refs — never raw filesystem paths.
- Artifact names carrying sensitivity markers are rejected (`_safe_artifact_name`).
- Pilot report + draft events are enqueued atomically with the artifact reference
  (`update_workspace(extra_events=...)`) in causal order.

---

## 8. Known limitations / do-not-claim

**Known limitations:** `read_only_live` is a scaffold (no real live read); redaction
covers surfaces that return/persist error text today; `ARIA_USER_ID` is attribution,
not authentication; single-process ledger locking.

**Do NOT claim (false for V2):**
- ❌ production deployment / autonomous production execution
- ❌ a real Jira ticket / Teams message / PR comment was created/sent/posted
- ❌ a pipeline rerun or production DB mutation
- ❌ real fine-tuning / model training / vLLM serving / model deployment
- ❌ multi-tenancy / AI-as-a-Service
- ❌ external-agent meta-harness runtime
- ❌ approval triggered an external action
- ❌ public release / open-source / LinkedIn post (blocked pending employer/IP approval)

---

## 9. Companion documents

- [`V2_FINAL_PROOF_CHECKLIST.md`](V2_FINAL_PROOF_CHECKLIST.md) — per-week scope + evidence, test counts, must-not-claim.
- [`V2_FRESH_CLONE_SETUP.md`](V2_FRESH_CLONE_SETUP.md) — clean-checkout setup, reset, fixtures/Ollama modes.
- [`V2_SAFETY_AND_BOUNDARY_AUDIT.md`](V2_SAFETY_AND_BOUNDARY_AUDIT.md) — full control matrix + threat walkthrough.
- [`V2_MANAGER_SUMMARY.md`](V2_MANAGER_SUMMARY.md) — business-friendly one-pager.

---

## 10. Requested verdict

Confirm that V2 (Weeks 31–35) is an **internally complete, governed, read-only /
draft-only AI-employee pilot** with no hidden production writes, reproducible offline,
and correctly bounded — and that it remains **not approved for public release**.
