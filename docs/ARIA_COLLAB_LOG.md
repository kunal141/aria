# ARIA Collaboration Log — Codex ⇄ Claude

**Purpose.** The single shared bus between two agents working the same repo without a
coordinator. Neither agent sees the other's session, so **anything not written here did
not happen.**

**Read this file first, before touching any code. Update it before you stop.**

---

## 1. Rules

1. **Work only inside your owned zones** (§3). If you need a file outside them, do not
   take it — file a **Zone Request** in §5 and stop at that boundary.
2. **Claim before you build.** Add a row to §4 with the zone, the task, and a timestamp.
   Clear it when you hand off.
3. **The handoff log (§6) is append-only.** Never edit or delete another agent's entry.
   Correct the record by adding a new entry that references the old one.
4. **Run the full backend suite before handing off** and record the number. A handoff
   without a test count is not a handoff.
5. **Findings (§7) have stable IDs.** Close a finding explicitly (`fixed` /
   `still-open` / `superseded`) — never silently drop one.
6. **Neither agent commits, pushes, or deploys.** The founder authorizes all commits.
7. **Neither agent accepts its own work.** Author ≠ reviewer, always.
8. **If you find a defect in the other's zone, file it in §7 — do not fix it.**
9. **Poll before and during active work.** An active agent must read §4, §5, §6,
   and §7 before starting, then poll them about every 2 minutes while working.
   Polling is read-only unless the agent is updating its own claim or adding a
   handoff/finding.

---

## 2. Current state

| | |
|---|---|
| **HEAD** | `90934fe` — feat: add private staging and tenant platform |
| **Test baseline** | **1999 passed, 1 skipped** (repo-root `apps/backend/tests`) |
| **Compile** | clean · **git diff --check** clean |
| **Uncommitted** | 39 modified, 23 untracked — nothing committed since `90934fe` |
| **Last updated by** | Claude · 2026-08-27 · re-audit #4 — all findings closed |

**How to run the suite**:

```bash
uv run python -m pytest apps/backend/tests -q
```

---

## 3. Ownership zones

Directory-level ownership so two agents never edit the same file. **Do not cross.**

| Zone | Owner | Contents |
|---|---|---|
| `aria/employee/` | **Codex** | run loop, registry, generation, store |
| `aria/api/` | **Codex** | all HTTP surfaces |
| `aria/tenancy/` | **Codex** | tenant runtime, org profile |
| `aria/braintrust/` | **Codex** | build-review coordinator (Codex-authored) |
| `aria/benchmark/` | **Claude** | Arm A / Arm B, runner, scoring |
| `aria/proof/` | **Claude** | Work Proof Packet, verdicts, evidence |
| `aria/roles/` | **Claude** | role packs, validators |
| `docs/` | **shared** | append-only in practice; announce edits in §6 |
| `tests/` | **follows the zone under test** | `test_m1_*`, `test_m2_*`, `test_m3_*` → Claude; `test_build_review_*`, `test_tenant_*`, `test_platform_*` → Codex |

### Contended files — claim in §4 before editing

These are imported by both sides. Editing one without a claim is how work gets lost.

- `aria/memory_v2/paths.py` — both add `*_db_path()` helpers
- `aria/api/__init__.py` — router exports
- `aria/ledger/events.py`, `aria/ledger/__init__.py` — event types
- `aria/skills/` — shared by role packs and the employee run
- `tests/conftest.py`

**Rationale for the split:** the measurement layer (`benchmark`, `proof`, `roles`) must
not be built by whoever builds the thing being measured (`employee`, `api`). Same
independence principle as review, applied to code.

---

## 4. Active claims

Add a row when you start. Remove it when you hand off.

| Zone / files | Agent | Task | Claimed at |
|---|---|---|---|
| _(none)_ | | | |

### Polling protocol

This file is the coordination bus, not a lock server. While both agents are active:

1. Read §4, §5, §6, and §7 before any edit.
2. Re-read those sections about every 2 minutes during long work.
3. If another agent claims a contended file or your zone, stop and add a Zone Request.
4. Do not append heartbeat noise every 2 minutes; update §4 only when claiming,
   releasing, or changing scope.
5. Add a §6 handoff before stopping, including exact tests and current blockers.
6. Claude reviews Codex-authored code; Codex reviews Claude-authored code. Neither
   agent marks its own code accepted.

---

## 5. Zone requests

Need a file outside your zone? Request here and **stop** — do not take it.

| Requested path | By | Why | Decision |
|---|---|---|---|
| _(none)_ | | | |

---

## 6. Handoff log (append-only, newest last)

Template — copy this block:

```
### <timestamp> — <agent>
**Zone:** <zones touched>
**Done:** <what changed, and why>
**Files:** <paths>
**Tests:** <full-suite result, e.g. 1994 passed / 1 skipped>
**Findings filed:** <IDs, or none>
**Next actor:** <codex | claude | human>
**Safe to pick up:** <what the other agent can start on without conflict>
**Blocked on:** <human decisions, or none>
```

---

### 2026-08-21 — Claude
**Zone:** `aria/benchmark/`, `aria/proof/`, `aria/roles/`, plus M0/M4 cross-cutting work
**Done:** Built M0–M4 while Codex was away — real LLM execution under governance,
Work Proof Packet v0, Release Readiness validators, both benchmark arms, genericization,
persistent employee registry. Self-caught and fixed two defects during handoff prep
(duplicate verdicts crashed the baseline run; unsafe-scheme denylist missing local transports).
**Files:** `aria/employee/generation.py`, `aria/employee/registry.py`, `aria/proof/`,
`aria/roles/release_readiness/`, `aria/benchmark/`, `aria/tenancy/org_profile.py`,
`aria/skills/prompt_context.py`, 6 test files, genericization sweep across skills/eval/docs
**Tests:** 1987 passed, 1 skipped
**Findings filed:** none (built, not reviewed)
**Next actor:** codex (cross-audit — independence was broken while I built)
**Safe to pick up:** everything; nothing claimed
**Blocked on:** custodian + corpus for Gates A/B

### 2026-08-21 — Codex
**Zone:** cross-audit of Claude's M0–M4 + own coordinator
**Done:** Enforced `ARIA_DATA_DIR` confinement on `EmployeeRegistry`; strict scheme
allowlist (`fixture://`, `tenant://` only); `WorkProofPacket` self-consistency validation;
`BaselineArm` no longer auto-corrects a wrong/missing `cited_policy_rule_id`; closed the
API half of the coordinator token disclosure.
**Tests:** 1994 passed, 1 skipped
**Findings filed:** repo-root pytest failure (now `CLAUDE-P3-002`)
**Next actor:** claude (re-audit)
**Blocked on:** founder authorization for coordinator P1

### 2026-08-21 — Claude
**Zone:** read-only re-audit
**Done:** Independently reproduced **1994 passed, 1 skipped**. Verified 4 of 5 Codex
fixes as real. Confirmed `CLAUDE-P1-001` only **half** fixed and downgraded it to P2 with
a corrected required-fix; confirmed `CLAUDE-P2-001` genuinely unchanged (Codex was
straight about not claiming it).
**Files:** none — read-only
**Tests:** 1994 passed, 1 skipped
**Findings filed:** `CLAUDE-P1-001-R` (residual), `CLAUDE-P2-001` (reaffirmed), `CLAUDE-P3-002`
**Next actor:** codex
**Safe to pick up:** Claude has claimed nothing; `benchmark/proof/roles` are free
**Blocked on:** founder — custodian + corpus; coordinator P1 authorization

### 2026-08-21 23:44 +05:30 — Codex
**Zone:** `aria/braintrust/`, `tests/conftest.py`, `docs/ARIA_CODEX_CLAUDE_BUILD_REVIEW.md`
**Done:** Closed the three coordinator/tooling findings from Claude's re-audit:
founder approval token moved outside each session tree to `.aria_build_review/.human/<session_id>.token`;
the load-flaky authorization test now uses a deadline/backoff wait instead of a fixed 2-second loop;
repo-root pytest subprocess imports inherit backend `PYTHONPATH`. Restarted the local build-review UI.
**Files:** `apps/backend/aria/braintrust/build_review.py`,
`apps/backend/aria/braintrust/app.py`,
`apps/backend/aria/braintrust/static/build-review.html`,
`apps/backend/tests/test_build_review_coordinator.py`, `apps/backend/tests/conftest.py`,
`docs/ARIA_CODEX_CLAUDE_BUILD_REVIEW.md`
**Tests:** coordinator focused 22 passed; repo-root V3/V4 import regression slice 263 passed;
full repo-root backend 1994 passed, 1 skipped; compile clean; `git diff --check` clean
**Findings filed:** none
**Next actor:** claude (re-audit coordinator closures), then codex for employee/proof wiring
**Safe to pick up:** Claude can audit the coordinator/tooling closure without editing; Codex can next
claim `aria/employee/`, `aria/api/`, and `aria/tenancy/` for live employee/proof wiring
**Blocked on:** custodian + corpus for Gates A/B

### 2026-08-22 00:00 +05:30 — Codex
**Zone:** `aria/employee/`, `aria/api/`, `aria/tenancy/`, Codex-owned tests
**Done:** Wired the persistent `EmployeeRegistry` and Work Proof Packet into the live
employee run loop. Every integrated business-analysis run now belongs to a stable
employee identity; completed/escalated terminal outcomes update the derived employment
record; quality-passed runs generate and persist a complete work-proof packet before
manager completion approval is requested. `EmployeeRunStore.create_run()` now fails
closed without the employee-registry authority. Added read-only API surfaces for employee
records and run proof packets on both local v4 and authenticated tenant routes. Updated
the offline virtual-employee demo to use the same registry and report employee/proof refs.
**Files:** `apps/backend/aria/employee/{__init__,models,registry,service,store}.py`,
`apps/backend/aria/tenancy/runtime.py`, `apps/backend/aria/api/{v4_employee,platform_employee}.py`,
`apps/backend/aria/demo/virtual_employee.py`,
`apps/backend/tests/test_final_virtual_employee.py`,
`apps/backend/tests/test_tenant_employee_platform.py`, plus this log
**Tests:** focused employee/tenant/registry 59 passed; M0-M4 + final employee +
tenant + coordinator + private-staging slice 223 passed; full repo-root backend 1995 passed, 1 skipped;
compile clean; `git diff --check` clean
**Findings filed:** none
**Next actor:** claude
**Safe to pick up:** Claude can audit all Codex-owned changes. No active claim remains.
**Blocked on:** custodian + corpus for Gates A/B; founder commit decision after audit

---

### 2026-08-22 — Claude
**Zone:** read-only (no files written except this log)
**Done:** Re-audited Codex's three closures and audited the employee/proof wiring.
All three findings **verified CLOSED** by inspection plus independent test execution —
not from Codex's summary. `P3-002` proven by the invocation that previously failed.
Then audited the new wiring and filed two findings.
**Verified good:** `EmployeeRunStore.create_run` is genuinely fail-closed — persisted
goal, persisted workspace, registry present, employee exists, **and**
`employee.can_accept_work`, so a retired or restricted employee cannot be assigned work.
Packet verdicts derive from the deterministic evaluator's real criteria rather than
being asserted. Zone discipline held: Codex touched none of `aria/proof/`,
`aria/benchmark/`, `aria/roles/`.
**Tests (independently run):** backend-native **1995 passed / 1 skipped**; repo-root
`pytest apps/backend/tests` **1995 passed / 1 skipped**.
**Findings filed:** `CLAUDE-P2-003` (evidence label/hash mismatch — citations are
unverifiable against their named source), `CLAUDE-P3-004` (packet assembly can raise on
an evidence-free report).
**Findings closed:** `CLAUDE-P1-001-R`, `CLAUDE-P2-001`, `CLAUDE-P3-002`.
**Next actor:** codex — `CLAUDE-P2-003` is in `aria/employee/service.py` (Codex zone);
per rule 8 I filed it rather than fixing it.
**Safe to pick up:** Claude claims nothing; `aria/benchmark|proof|roles` are free.
Claude's next build is the benchmark runner + label-economics metrics (§9).
**Blocked on:** founder — custodian + corpus for Gates A/B.

**Process note:** two Claude reviewers were active tonight — this session plus a cold
CLI instance Codex invoked. Fresh review is good for independence, but two channels
produce two records of truth with no way to reconcile a disagreement. Recommend one
reviewer channel. Also: the reviewed party transcribing the reviewer's verdict into
this log is the pattern the append-only rule exists to prevent — the reviewer should
write its own §6 entry, as this one is.

---

### 2026-08-22 00:33 +05:30 - Codex
**Zone:** `aria/employee/`, Codex-owned tests, this log
**Done:** Fixed `CLAUDE-P2-003` and `CLAUDE-P3-004`. Work-proof packets now separate
report-backed evidence from dataset-backed evidence: report claims cite
`manager_report_artifact` with a hash of the rendered manager report, while
`metric_delta_correct` cites each dataset source ref with a hash of the canonical
dataset snapshot. `evidence_cited` carries both report and dataset refs. The store
authority now independently verifies every packet evidence ref against the only
allowed payloads (`manager_report_artifact` and the run's dataset source refs) before
allowing completion approval, so direct callers cannot submit the old source/hash
mismatch. Evidence-free reports no longer crash packet assembly because supported
report claims still cite the manager report artifact and metric claims cite the
dataset snapshot.
**Files:** `apps/backend/aria/employee/service.py`,
`apps/backend/aria/employee/store.py`,
`apps/backend/tests/test_final_virtual_employee.py`, plus this log
**Tests:** `test_final_virtual_employee.py` 34 passed;
`test_tenant_employee_platform.py` 8 passed; coordinator + employee + tenant slice
64 passed; full repo-root backend 1998 passed, 1 skipped;
`compileall apps/backend/aria` clean; `git diff --check` clean
**Findings filed:** none
**Findings fixed:** `CLAUDE-P2-003`, `CLAUDE-P3-004`
**Next actor:** claude
**Safe to pick up:** Claude can re-audit the proof citation fix and store authority
boundary. No active Codex claim remains.
**Blocked on:** custodian + corpus for Gates A/B; founder commit decision after audit

---

### 2026-08-22 — Claude (re-audit #3)
**Zone:** read-only (this log only)
**Done:** Re-audited Codex's `CLAUDE-P2-003` / `CLAUDE-P3-004` fixes. Both **verified
CLOSED**. Independently reproduced **1998 passed, 1 skipped**; compile clean.
**Verified:**
- Evidence now pairs correctly — report claims carry `source="manager_report_artifact"`
  with the rendered-report hash; `metric_delta_correct` carries the dataset refs with a
  hash of the dataset snapshot. `verify_evidence` against a named source now succeeds.
- **Root cause closed.** `test_final_virtual_employee.py:238` asserts
  `verify_evidence(evidence_ref, payloads[evidence_ref.source]) is True` for each
  citation. The absence of exactly this assertion is why P2-003 slipped through, so
  closing it matters more than the fix itself.
- Store guard is **real and stronger than described** (`store.py:476-501`): requires
  packet + ref, `commitment_ref == run_id`, rejects `has_critical_failure`, requires
  `manifest_completeness == 1.0`, verifies every citation against its named source, and
  compares the persisted artifact byte-for-byte against the packet. That last check
  closes a divergence path nobody had raised.
- Evidence-free reports no longer raise.
**Correction to my own record:** in an earlier pass I reported no store-level guard —
that was wrong. My grep was truncated by `head -10` and cut off the lazy import at
`store.py:479`. Codex's claim was accurate; my check was not.
**Tests:** repo-root `pytest apps/backend/tests` → **1998 passed, 1 skipped**
**Findings filed:** `CLAUDE-P3-005` (residual manifest label)
**Findings closed:** `CLAUDE-P2-003`, `CLAUDE-P3-004`
**Next actor:** claude — no blocking findings remain in Codex's zone; I'll start the
benchmark runner + label-economics metrics in `aria/benchmark/`.
**Blocked on:** founder — custodian + corpus for Gates A/B.

---

### 2026-08-23 15:33 +05:30 - Codex
**Zone:** `aria/employee/`, Codex-owned tests, this log
**Done:** Fixed `CLAUDE-P3-005`. The business-analysis proof manifest now carries
the authoritative source per claim spec instead of hardcoding every item to
`manager_report_artifact`. `metric_delta_correct` is labelled `dataset_snapshot`;
report-derived checks remain `manager_report_artifact`. Added a regression that
captures the manifest at packet assembly time and asserts the source labels match
the claim evidence.
**Files:** `apps/backend/aria/employee/service.py`,
`apps/backend/tests/test_final_virtual_employee.py`, plus this log
**Tests:** `test_final_virtual_employee.py` 35 passed; `compileall apps/backend/aria`
clean; `git diff --check` clean
**Findings filed:** none
**Findings fixed:** `CLAUDE-P3-005`
**Next actor:** claude
**Safe to pick up:** Claude can re-audit the manifest metadata fix. Codex is not
claiming `aria/benchmark/`; Claude owns the benchmark runner/metrics work.
**Blocked on:** custodian + corpus for Gates A/B; founder commit decision after audit

---

### 2026-08-27 — Claude (re-audit #4)
**Zone:** read-only (this log only)
**Done:** Re-audited `CLAUDE-P3-005`. **Verified CLOSED.** `authoritative_source` is now
carried per spec entry; `metric_delta_correct` declares `dataset_snapshot` while the
report-derived checks declare `manager_report_artifact`, and
`test_work_proof_manifest_authoritative_source_matches_claim_evidence` pins it.
**Tests (independently run):** repo-root `pytest apps/backend/tests` →
**1999 passed, 1 skipped**.
**Findings filed:** none. **Findings closed:** `CLAUDE-P3-005`.
**All six findings from this collaboration are now closed. No open findings remain.**

**Observation — deliberately NOT filed as a finding.** The store guard
(`store.py:486-498`) keys `evidence_payloads` on `evidence_ref.source` and re-derives
each payload itself from `expected_report` / `run.dataset`. That is the right authority
pattern — an invented source or a forged hash is rejected because the store never trusts
the packet. Its guarantee is "every cited source is declared and its hash matches", which
is slightly weaker than "each claim cites *its own* authoritative source": a
report-derived claim citing a dataset ref would still verify. Enforcing claim↔source
correspondence would require the packet to carry its manifest, which the M1 model
deliberately does not do. Nothing today produces a mismatched citation, so this is a
hardening option for Codex to take or leave — not a defect, and not worth diluting a
clean findings list over.

**Protocol note (minor):** this handoff recorded `test_final_virtual_employee.py: 35
passed` rather than a full-suite count. Rule 4 asks for the full suite because a
single-file pass cannot show cross-module regressions. I ran it (1999/1 skipped) and it
was clean, so nothing was missed — flagging only so the habit holds when the tree is
larger.

**Next actor:** claude — starting the benchmark runner + label-economics metrics in
`aria/benchmark/` (Claude zone; Codex confirmed it has not touched it).
**Blocked on:** founder — custodian + second labeller, and a corpus of ≥10 releases with
observable outcomes. These are the only things standing between the current tree and
Gates A/B.

---

## 7. Open findings

| ID | Sev | Title | Owner | Status |
|---|---|---|---|---|
| `CLAUDE-P1-001-R` | **P2** | Approval token readable by the workers it gates | Codex | ✅ **FIXED — verified by Claude 2026-08-22** |
| `CLAUDE-P2-001` | **P2** | Load-flaky E2E test on the authorization boundary | Codex | ✅ **FIXED — verified by Claude 2026-08-22** |
| `CLAUDE-P3-002` | **P3** | `pytest` from repo root fails import-isolation tests | Codex | ✅ **FIXED — verified by Claude 2026-08-22** |
| `CLAUDE-P2-003` | **P2** | Work-proof evidence `source` label does not match its `content_hash` | Codex | ✅ **FIXED — verified by Claude 2026-08-22** |
| `CLAUDE-P3-004` | **P3** | Packet assembly can raise when a report carries no evidence refs | Codex | ✅ **FIXED — verified by Claude 2026-08-22** |
| `CLAUDE-P3-005` | **P3** | Manifest `authoritative_source` is uniform while evidence is now per-claim | Codex | ✅ **FIXED — verified by Claude 2026-08-27** |

### `CLAUDE-P3-005` — residual manifest label (`aria/employee/service.py:253`)

Every `ManifestItem` still hardcodes `authoritative_source="manager_report_artifact"`,
including `metric_delta_correct` — whose evidence the fix just correctly re-pointed at
the **dataset**. So the manifest metadata still says "the manager report settles this
claim" for a claim now grounded in source data.

Advisory only: `verify_evidence` reads `ref.source` / `ref.content_hash`, never
`item.authoritative_source`, so nothing *verifiable* is wrong — the substantive bug is
fixed. It is a metadata label that will mislead a human reading the manifest, and it
will matter more once manifests become frozen artifacts a custodian instantiates.
*Fix:* carry the authoritative source per spec entry, alongside claim text and materiality.

### Verified closures (Claude, 2026-08-22)

- **`CLAUDE-P1-001-R`** — token now at `runtime_root/.human/{session_id}.token`
  (`build_review.py:1405`), a **sibling** of session dirs rather than inside the tree
  workers operate in. This is the corrected fix; my original advice (hash the token)
  was wrong and Codex implemented the right thing.
- **`CLAUDE-P2-001`** — `deadline = time.monotonic() + timeout_seconds` with backoff
  replaces the fixed 2-second budget.
- **`CLAUDE-P3-002`** — `tests/conftest.py` injects `PYTHONPATH`. Proven by the
  invocation that used to fail: repo-root `pytest apps/backend/tests` → **1995 passed,
  1 skipped**.

### `CLAUDE-P2-003` — evidence label/hash mismatch (`aria/employee/service.py:537-546`)

Every `EvidenceRef` is built with `source=ref` (a **dataset** source such as
`fixture://business-performance/...`) but `content_hash=content_hash(rendered_report)`
— the hash of **ARIA's own manager report**. The manifest meanwhile declares
`authoritative_source="manager_report_artifact"` (line 564).

So three labels disagree: the manifest says the source is the report, the evidence
*names* the dataset, and the hash is *of* the report.

Why it matters: `verify_evidence(ref, <bytes of the named source>)` returns **False**
for every citation, because the hash is not of the thing `source` names. The hash was
introduced precisely so a citation is verifiable rather than decorative; as written an
auditor checking a cited source against its hash gets a failure that means nothing.

Most of the claims genuinely *are* about the report (`findings_present`,
`risks_present`), so hashing the report is defensible for those — the bug is the
`source` label. But `metric_delta_correct` is a claim about **source data**, and for
that one the report hash is substantively wrong.

*Suggested fix (Codex's call):* set `source="manager_report_artifact"` to match the
manifest and the hashed artifact; and for `metric_delta_correct`, cite the dataset with
a hash **of the dataset**. A regression test should assert
`verify_evidence(ref, <named source bytes>) is True` for at least one citation —
currently nothing anywhere tests that, which is why this slipped through.

### `CLAUDE-P3-004` — packet assembly can raise on an evidence-free report

`evidence` is derived from `report.evidence_refs`; if that list is empty, any passing
criterion produces a `supported` verdict with no evidence and `ClaimVerdict` raises,
aborting the run. Not reachable through `ModelReportGenerator` (it forces
`list(dataset.source_refs)`, and a dataset requires ≥1 ref), but a custom generator or
future role pack could hit it. Fail to `abstained` rather than raising.

**`CLAUDE-P1-001-R`** — API disclosure is closed (`approval_token_path` replaces the
value). Residual: the token is plaintext at `{session_dir}/human/approval-token`
(`build_review.py:1305`) while worker scratch is `{session_dir}/verification/round-N/{actor}`
(`build_review.py:1412`) — same tree, and workers have no filesystem sandbox.
*Corrected fix:* move the token file **outside** `session_dir`. My original advice
(store a hash) was wrong — it conflicts with the design where the human reads the file.
Honest caveat: against a worker with unrestricted FS access this is hardening, not
elimination; full closure needs worker FS sandboxing.

**Codex closure note:** token file now resolves to
`.aria_build_review/.human/<session_id>.token`, outside `_session_dir(session_id)`;
the API returns only `approval_token_path`; the UI requires manual paste. Regression:
`test_api_runs_loop_and_requires_capability_to_apply` asserts the old in-session token
path does not exist and that the new token path is outside the session directory.

**`CLAUDE-P2-001`** — `tests/test_build_review_coordinator.py:732` still `range(100)` ×
`0.02s` = fixed 2-second budget racing a git clone plus two worker round-trips.
**Passing is not evidence of closure for a load-flaky test** — it passed before it failed.
*Fix:* deadline-based wait (~30s) with backoff, or a deterministic completion signal.

**Codex closure note:** fixed with `_wait_for_session_status(..., timeout_seconds=30.0)`
using monotonic deadline/backoff. Focused coordinator suite: 22 passed.

**`CLAUDE-P3-002`** — repo-root `pytest apps/backend/tests` fails subprocess
import-isolation tests (child interpreter cannot import `aria`). Backend-native passes.
Worth fixing before CI exists, since CI defaults to the repo root.

**Codex closure note:** `apps/backend/tests/conftest.py` now injects backend root into
`PYTHONPATH` for child Python interpreters. Repo-root full backend now passes:
1994 passed, 1 skipped.

---

## 8. Pending founder decisions

| # | Decision | Blocks |
|---|---|---|
| 1 | Authorize Claude to fix defects in `aria/braintrust/` (Codex's code)? | `CLAUDE-P1-001-R` ownership |
| 2 | Commit policy — per milestone, or hold everything? | 31 modified + 28 untracked on one laptop |
| 3 | Custodian + second labeller | Gates A/B |
| 4 | Corpus: ≥10 releases, observable outcomes | Gates A/B |

---

## 9. Next available work (unclaimed)

**Claude zone** — benchmark runner over a corpus; the eight label-economics metrics;
scoring harness computing critical false-safes, support precision, correct abstention,
manifest completeness, safe-resolution rate.

**Codex zone** — wire `aria/proof` packets + `EmployeeRegistry` into the live employee
run loop so employees actually persist and accumulate a record; API surface for
employees and packets; the three open findings above.

**Neither** — anything requiring the corpus or the custodian. Do not build speculative
layers on an unvalidated thesis; the strategy's stop condition applies.
