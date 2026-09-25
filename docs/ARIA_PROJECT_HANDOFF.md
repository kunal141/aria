# ARIA — Project Handoff

**Read this before CLAUDE.md.** CLAUDE.md describes the original 30-week V1–V3 plan and is
still useful history, but the project's *thesis* moved on after that plan completed. This
file is the current truth. Where the two disagree, this file wins.

Written 2026-09-03, at the point the work was moved to GitHub ahead of a laptop change.

---

## 1. Orientation in sixty seconds

ARIA started as a 30-week "AI Employee platform" and reached V3. That work is complete,
tagged, and merged. What followed is a different and much sharper question:

> **Can an AI system's work be trusted enough to act on without a human re-checking it?**

Everything built since is an attempt to answer that with evidence rather than assertion.
The current product thesis is **Verified Operational Learning**:

1. The system produces work *with a proof of what it checked* (a Work Proof Packet).
2. Verification converts those proofs into trusted labels.
3. Labels accumulate into organization-specific operating knowledge.
4. Authority is **earned** from that record, never granted by configuration.

The moat is not governance (table stakes), not the model, and not the framework. It is the
accumulated, verified record of work — which a competitor cannot copy because they did not
do the work.

**The current state of that thesis: unproven.** The harness to test it is built. The test
has not been run, because it needs two things only a human can obtain (§6).

---

## 2. What is actually built

All of this is real, tested, and cross-audited by two independent agents.

| Package | What it does |
|---|---|
| `apps/backend/aria/proof/` | **Work Proof Packet v0.** Manifest items, claim verdicts, evidence refs with content hashes, reconciliation. The artifact the whole thesis rests on. |
| `apps/backend/aria/roles/release_readiness/` | **RR-001…RR-006** deterministic release-readiness validators with explicit abstention. |
| `apps/backend/aria/benchmark/` | **Both benchmark arms.** Arm A (ARIA: deterministic, abstaining, hash-bound evidence) and Arm B (a competent LLM agent baseline). Arm configs are hashed so post-hoc tuning is detectable. |
| `apps/backend/aria/employee/registry.py` | **Persistent employee identity** plus a derived employment record. Lifecycle: probation → active → restricted/retired. |
| `apps/backend/aria/employee/generation.py` | The deterministic-vs-real-model report generation seam. |
| `apps/backend/aria/tenancy/org_profile.py` | **Tenant org profile** — organization identity is configuration, not hardcoded. |
| `apps/backend/aria/skills/prompt_context.py` | Composes tenant context into skill prompts (concatenation, never `str.format`). |
| `apps/backend/aria/braintrust/` | Build-review coordinator (Codex-authored) — the two-agent review harness. |

**Test baseline: 1999 passed, 1 skipped.** From the repo root:

```
uv run python -m pytest apps/backend/tests -q
```

Backend-native also works (`cd apps/backend && uv run python -m pytest tests -q`). Both
invocations must pass — the repo-root one was broken once and is now pinned by a test.

### The genericization property

`grep -rni "amar ujala|AU-ENG|media_tech_domain" apps/backend/aria/` returns **0**. The
product is employer-neutral; organization identity arrives at runtime via
`TenantOrgProfile`. Do not reintroduce employer-specific strings into shipped code — that
neutrality is what makes ARIA sellable to an organization that is not the original
employer.

---

## 3. Key documents, in reading order

| Document | Why you need it |
|---|---|
| **This file** | Orientation and current truth |
| `docs/ARIA_ACCOUNTABLE_VIRTUAL_EMPLOYEE_OPERATIONS_STRATEGY.md` | The canonical strategy (v2.0): nine-stage operating chain, contracts, label economics, gates, nine locked rules |
| `docs/ARIA_WORK_PROOF_BENCHMARK_SPEC.md` | The benchmark that decides whether the thesis is true (v0.3.1) |
| `docs/RELEASE_READINESS_POLICY_RULES_V0.md` | RR-001…008 as written policy, mirrored by the code |
| `docs/ARIA_COLLAB_LOG.md` | The Codex⇄Claude coordination bus — zones, findings, handoffs |
| `docs/ARIA_DEVELOPMENT_PLAN_M0_M4.md` | The plan that produced the current code |
| `CLAUDE.md` | The original 30-week plan. History and architecture, now partly superseded |

---

## 4. Core invariants — do not break these

Enforced in code, not by convention. Several were paid for with real bugs.

1. **A producer can never self-report `omitted`.** Only reconciliation assigns it, so a
   dangerous claim cannot be quietly dropped out of the denominator.
2. **`supported` requires evidence.** A verdict without a citation is not a verdict.
3. **An evidence `source` must name what its `content_hash` is a hash of.** Otherwise the
   citation is decorative — it looks verifiable and is not.
4. **An empty employment record reports `None`, not zero.** "No data" and "zero percent"
   are different claims about a new hire.
5. **The employment record is derived on read, never stored.** A stored summary drifts from
   the work behind it; that is what makes performance dashboards untrustworthy.
6. **Both benchmark arms are reconciled identically.** Neither may shrink the denominator
   by answering only the easy checks.
7. **The baseline arm must stay genuinely competent.** Its prompt is generated from the
   same manifest ARIA answers and must permit abstention. A weak Arm B produces a
   spectacular win that means nothing.
8. **Deny-by-default execution.** `offline_mock` is the default; `cloud_opt_in` is excluded
   from the authenticated tenant surface; legacy unauthenticated routers are fail-closed
   behind `ARIA_STAGING_LEGACY_API`.
9. **Stores are second authorities.** A store re-derives and re-verifies rather than
   trusting its caller — see completion approval in `employee/store.py`, which rebuilds
   evidence payloads itself so a forged packet cannot pass.
10. **Neither agent accepts its own work, and neither commits.** Author ≠ reviewer.

---

## 5. What is deliberately NOT built

This is not backlog. It is a deliberate stop, and re-reading it will save weeks.

- Attribution layer, earned-authority engine, employee factory, more role packs — **all
  blocked on evidence that does not exist yet.** Building them now means building on an
  unvalidated thesis.
- Real fine-tuning, vLLM serving, production deployment — out of scope.
- Public GitHub / LinkedIn publication — **blocked pending employer/IP approval.** The repo
  is private. Keep it private until that approval exists.

The strategy's own stop condition: **do not add breadth before the benchmark reports.**

---

## 6. The two blockers (human-only)

Neither is a coding task. Both have been open for the entire build, and no amount of
further building moves them.

1. **A custodian and a second labeller.** The benchmark needs a role-separated human who
   instantiates manifests and labels outcomes independently of whoever built the system.
2. **A corpus: one organization with ≥10 releases with observable outcomes.**

Until these exist, Gates A and B cannot run and the thesis stays unproven. If they turn out
to be hard to obtain, that is itself information about the thesis worth having early.

---

## 7. Learnings and mistakes — the expensive part

Read this section. It is the part that cannot be reconstructed from the code.

### Engineering lessons

- **An anti-strawman test caught a rigged benchmark.** M1's "supported requires evidence"
  invariant was silently discarding every `supported` verdict the baseline produced —
  because the baseline has no evidence-binding layer, which is the entire point of it.
  Arm B would have been structurally incapable of ever saying "this check passed,"
  producing a flawless ARIA win that no reader could have detected. **When you build a
  comparison, write the tests that defend the side you want to lose.**
- **Guards from earlier layers caught defects in later ones, three times.** M1's evidence
  invariant caught M2's rules citing nothing, then caught M3 crippling the baseline. Build
  the invariant before the thing it constrains.
- **Fix the code, not the test.** When a regression test failed because a new error message
  lacked a substring, the fix was to improve the message — not to edit the assertion.
- **A load-flaky test is not closed by passing.** It passed before it failed. A
  fixed-duration polling loop racing real work must become a deadline with backoff.
- **The root cause of a bad citation was a missing assertion.** Nothing anywhere tested
  `verify_evidence` against a *real* citation, only in isolation. Closing that gap mattered
  more than the fix itself.
- **Untracked files are the worst thing to lose** — no reflog, no stash, no recovery. This
  handoff exists because ~141 tests and five packages sat untracked on a single laptop.

### Strategy corrections (claims made, then falsified)

- *"No AI platform does earned autonomy"* — **false.** Four named incumbents do. Never
  claim novelty without checking.
- *"Governance is the moat"* — **wrong.** Governance is table stakes; every enterprise
  vendor has it. The moat is the accumulated verified record.
- *"Unexportable" / lock-in framing* — rejected twice. Do not sell lock-in.
- *"Optimize for abstention"* — a degenerate optimum. A system that abstains on everything
  scores perfectly and is worthless.
- *"Release-ready → rollback → free label"* — a downstream outcome is only a label
  *candidate*, not a label.
- **The temporal invariant**: future information may label a past decision, but can never
  become information that decision had. Violating this silently inflates results.
- **Omission gaming**: a system that generates its own claims can simply omit the hard
  ones. Solved by a frozen mandatory claim manifest plus reconciliation — which is why
  invariant 1 exists.

### Review-process lessons

- **Both sides must record their own errors.** Claude advised hashing an approval token —
  wrong; it conflicted with the design where a human reads the file, and the right fix was
  moving the file outside the worker tree. Claude also reported "no store guard exists"
  when its own grep had been truncated by `head -10`. Codex stated plainly that a finding
  was *not* closed rather than claiming it. A review loop where neither party admits
  mistakes is decoration.
- **Do not file trivia.** After six real findings, filing "the guard could be stricter"
  would only dilute the signal of the list.
- **Two reviewers with no shared context produce two records of truth.** Use one reviewer
  channel.

---

## 8. Working agreement (two agents, one repo)

Codex and Claude work the same tree via `docs/ARIA_COLLAB_LOG.md`. Neither sees the other's
session, so **anything not written in that log did not happen.**

Ownership is by directory so two agents never open the same file:

| Codex | Claude |
|---|---|
| `aria/employee/` · `aria/api/` · `aria/tenancy/` · `aria/braintrust/` | `aria/benchmark/` · `aria/proof/` · `aria/roles/` |

Rationale: **the measurement layer must not be built by whoever builds the thing being
measured.** Contended files (`memory_v2/paths.py`, `api/__init__.py`, `ledger/events.py`,
`skills/`, `tests/conftest.py`) require a claim in §4 of the log before editing.

Findings get stable IDs and must be closed explicitly. Six were filed and all six closed;
§7 of the collab log holds the record.

---

## 9. Picking this up on a new machine

```
git clone https://github.com/kunal141/aria.git
cd aria
uv sync
uv run python -m pytest apps/backend/tests -q
```

Expect **1999 passed, 1 skipped**. If that number differs, find out why before doing
anything else.

Then read, in order: this file → the strategy doc → the benchmark spec → the collab log.

**A good first message to a fresh agent session:**

> Read `docs/ARIA_PROJECT_HANDOFF.md`, then `docs/ARIA_COLLAB_LOG.md`. Confirm the test
> baseline still passes, tell me the current state, and tell me what the two human
> blockers are before proposing any work.

### Immediate next steps, in priority order

1. **Obtain the custodian and the corpus** (§6). Everything else is downstream of this.
2. **Build the benchmark runner** in `aria/benchmark/` — executes both arms over a corpus
   and computes the label-economics metrics: critical false-safes over opportunities,
   support precision, correct abstention, manifest completeness, safe-resolution rate,
   evidence coverage, cost, latency. Include a **synthetic corpus generator with known
   ground truth**, so the instrument can be validated before a partner's real data is on
   the line.
3. **Then stop building** until the benchmark reports. If it falsifies the thesis, that is
   the most valuable result available — it should change the plan, not be explained away.
