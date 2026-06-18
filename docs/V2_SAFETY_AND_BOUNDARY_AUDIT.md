# ARIA V2 — Safety & Boundary Audit

**Branch:** `v2-complete-internal-ai-employee-pilot`
**Posture:** local, internal, read-only / draft-only pilot. No production writes anywhere.

Every control below is enforced **structurally** (in code, with a test), not just
documented. The right-hand column points to the mechanism and the proving test.

---

## 1. Control matrix

| # | Boundary | Guarantee | Enforced by / proof |
|---|---|---|---|
| 1 | **No production writes** | No connector exposes any write/post/send/rerun method in any mode. | `aria/connectors/connector.py` (read-only methods only); pilots import no integration clients. |
| 2 | **Connector defaults to fixtures** | `CONNECTOR_MODE` resolves to `fixtures` when unset, blank, or unknown (fail-safe). | `aria/connectors/mode.py::resolve_connector_mode`; `test_week35_v2_demo.py::test_credentials_alone_do_not_activate_live_connector` |
| 3 | **Credentials never activate live** | Mode resolution reads only `CONNECTOR_MODE`, never API-key presence. | same as #2; provider keys set in the test do not flip the mode. |
| 4 | **`read_only_live` requires explicit mode + allowlist + is still inert** | Live mode needs `CONNECTOR_MODE=read_only_live` **and** the provider on `CONNECTOR_PROVIDER_ALLOWLIST`; even then it raises `NotImplementedError` (no real network read in V2). | `aria/connectors/mode.py::ensure_live_allowed`, `connector.py::LiveConnector`; `test_read_only_live_fails_closed_without_allowlist`, `test_read_only_live_even_when_allowed_does_no_network` |
| 5 | **Approval is decision-only** | Approving a memory proposal records an auditable decision targeting internal `domain_memory`; it triggers no external action. | `aria/conversation/approval.py`; `test_approval_is_a_decision_record_not_an_external_action` |
| 6 | **Sensitive memory refused without auth** | V2 has no authenticated identity layer, so confidential/secret/credential/token/PII memory is refused on persist and returns nothing on recall. Classification is conservative (false-positives just refuse). | `aria/memory_v2/sensitivity.py`, `store.py::propose_memory`; `test_sensitive_memory_is_refused_and_not_persisted` |
| 7 | **`ARIA_USER_ID` is attribution-only** | The actor label is metadata for the ledger; it is never treated as proof of authorization and cannot unlock sensitive memory. | `aria/api/v2.py::actor`, `aria/memory_v2/sensitivity.py` (docstring + classify ignores actor) |
| 8 | **No cloud fallback** | Default execution mode is `offline_mock`; cloud is reached only via explicit `cloud_opt_in`. An invalid mode raises rather than guessing. The demo additionally **pins** `offline_mock` so an ambient `cloud_opt_in` cannot leak a "cloud" label into the ledger. | `aria/llm/execution_mode.py`, `aria/demo/v2_full_pilot.py`; `test_no_cloud_fallback_from_credentials`, `test_demo_pins_offline_mode_even_with_ambient_cloud_opt_in` |
| 9 | **Memory does not bypass the evidence gate** | Approved memory may *explain* values (e.g. what `event_type=2` means) but counts/claims still require fixture evidence; without evidence the pilot returns `evidence_required`/`evidence_missing`. | `aria/pilots/analytics.py`; demo summary asserts analytics carries BOTH a memory citation AND `fixture:` evidence (`test_analytics_memory_explains_but_evidence_proves_counts`) |
| 10 | **Raw exceptions / secrets redacted** | Error responses carry a stable code + sanitised detail (never raw exception text); the stream error path emits the exception **class** only, in body and logs; secret-shaped artifact filenames are rejected. | `aria/api/v2.py::_safe_error` + stream error handler; `aria/memory_v2/workspace.py::_safe_artifact_name`; `test_error_responses_are_redacted` |
| 11 | **State and audit cannot diverge** | Memory and pilot ledger events ride a transactional **outbox**: each event is enqueued in the same SQLite transaction as the state change and flushed to the Work Ledger; on a ledger outage the events stay queued + recoverable. | `aria/memory_v2/store.py`, `aria/memory_v2/workspace.py` (outbox), `aria/pilots/service.py` |
| 12 | **Public release blocked** | No public GitHub push / LinkedIn post is authorized; publication waits on employer/IP review. | policy — see §3 and `V2_FINAL_PROOF_CHECKLIST.md` §4 |

---

## 2. Threat-style walkthrough

- **"Can a prompt make ARIA approve its own memory?"** No. A decision happens only
  through the explicit `/api/v2/memory/proposals/{id}/decision` endpoint with a real
  `proposal_id`; conversational text never approves anything.
- **"Can a leaked API key turn on live connectors or cloud models?"** No. Connector
  mode and execution mode both ignore key presence; only explicit env modes flip
  behaviour, and `read_only_live` is inert anyway.
- **"Can I store a password 'as a fact' and read it back?"** No. The persist path
  refuses sensitive content (and the chat history stores a redacted placeholder, not
  the raw secret), so it never reaches SQLite and never becomes retrievable.
- **"Can memory fabricate a metric?"** No. Memory explains *meanings*; the evidence
  gate still demands fixture-backed data for any count/claim.
- **"Can a draft escape and become a real Jira ticket / Teams message / PR comment?"**
  No. Drafts are inert data artifacts labelled "Draft only. Not posted." There is no
  code path from a draft to an external write.
- **"Does running the demo or tests leave anything behind / call out?"** No. Runtime
  state is confined to `ARIA_DATA_DIR`; the demo uses a self-deleting temp dir; tests
  redirect every sink to tmp; offline + fixtures means no network.

---

## 3. Residual limitations (honest)

- `read_only_live` is a **scaffold**: there is no real live-read implementation in
  V2. When live reads are built (V3), they must keep the fail-closed gate and add
  authentication before any sensitive scope is unlocked.
- Redaction covers the surfaces that **return or persist** error text today (API
  responses, stream errors, ledger routing reasons, artifact names). It is not a
  blanket guarantee for every conceivable third-party library log line.
- `ARIA_USER_ID` provides attribution, not authentication. Multi-user trust requires
  a real identity layer (V3).
- The in-process ledger writer uses a thread lock; cross-process write locking is a
  documented follow-up (single-process pilot today).

---

## 4. Bottom line

V2 is safe to run as an **internal pilot**: it reads fixtures, remembers approved
non-sensitive facts, investigates read-only, and produces drafts a human must act
on. It performs **no production writes, no external sends, no cloud calls by default,
no training, and no deployment** — and it is **not approved for public release**.
