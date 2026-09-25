# ARIA Development Plan — M0 → M4

**Version:** 1.0 · **Date:** 2026-08-17 · **Builder:** Claude (interim, while Codex is on leave)
**Status:** proposed — awaiting founder approval before implementation begins.

**Governing documents:** [Strategy v2](ARIA_ACCOUNTABLE_VIRTUAL_EMPLOYEE_OPERATIONS_STRATEGY.md) ·
[Benchmark Spec v0.3.1](ARIA_WORK_PROOF_BENCHMARK_SPEC.md) ·
[Policy Rules v0](RELEASE_READINESS_POLICY_RULES_V0.md)

---

## 0. Premise and role caveat

The benchmark (Gates A/B) is blocked on two **human** tasks — a custodian/second labeller, and one
organization with observable-outcome release history. Neither is a coding task.

But the benchmark measures something ARIA **cannot currently produce**: a Work Proof Packet with
claim-level verdicts. So the unblocked, highest-value work is *building the thing the benchmark
will measure*, so that the moment a corpus arrives, Gates A and B can run immediately.

**Role caveat.** Claude is normally the independent reviewer. Building removes that independence.
Mitigations, non-negotiable:

1. Adversarial tests are written **before** the implementation they test.
2. Every milestone enters Codex's review queue on its return; nothing is treated as accepted.
3. The founder authorizes all commits. No push, no deploy.
4. The build-review coordinator's own P1 stays open unless the founder explicitly assigns it (§M0.6).

---

## 1. What we are NOT building in this window

Deliberately excluded, per strategy §12 and the stop conditions:

- Attribution layer — requires observed outcomes that do not exist yet
- Earned-authority promotion engine — requires performance history that does not exist yet
- Employee Factory / role-pack SDK — premature before role #1 works
- Verified Operational Learning pipeline — no labels exist to learn from
- Any write connector, live execution, voice, telephony, marketplace
- Employee #2 through #6

**Rule for this window:** if it does not help produce or evaluate a Work Proof Packet for Release
Readiness, it is out of scope.

---

## 2. Milestones

### M0 — Make it real (3–4 days)

*Nothing downstream matters until an authenticated user gets real work from a real model.*

| # | Task | File(s) |
|---|---|---|
| 0.1 | Remove the `offline_mock` gate so authenticated tenant runs may execute for real, policy gates and ledger intact | `aria/api/platform_employee.py:38` |
| 0.2 | Route tenant employee runs through the proven local-LLM skill path | `aria/employee/service.py`, `aria/api/v2.py:163` → `chat.py:92` |
| 0.3 | Relax the `fixture://`-only `source_refs` constraint behind a tenant policy flag | `aria/employee/service.py` |
| 0.4 | Ship `ARIA_PRIVATE_AUTH_SECRET` in deployment artifacts (identity is currently unreachable → 503) | `compose.private.yml`, `deployment/private-staging/env.example` |
| 0.5 | Add langchain/ollama to the container lockfile; add a gated egress network | `deployment/private-staging/backend-requirements.lock`, `compose.private.yml` |
| 0.6 | *(founder decision)* Fix build-review P1-001 — remove `approval_token` from GET, store `sha256(token)` on disk | `aria/braintrust/app.py:85`, `build_review.py:1303` |
| 0.7 | Authenticate or unmount the unauthenticated legacy routers | `aria/api/staging.py:44-49` |

**Exit:** an authenticated tenant user POSTs a goal and receives LLM-generated, evidence-backed,
ledger-recorded work — **inside the container**, not only natively. Full suite green.

---

### M1 — Work Proof Packet v0 (1 week)

The core artifact. New package `aria/proof/`.

| # | Task | Detail |
|---|---|---|
| 1.1 | `Claim` model | tier A/B · claim text · `policy_rule_id` (required for B) · materiality · authoritative source · freshness window |
| 1.2 | `Verdict` enum + evidence | `supported / unsatisfied / abstained` (+ `omitted` assigned by reconciliation only) · evidence refs carrying **source + content hash + observed_at** |
| 1.3 | Manifest loader | consumes `WORK_PROOF_MANIFEST_TEMPLATE_V0.json`; validates tier/rule/stratum invariants |
| 1.4 | **Reconciliation** | any manifest item with no verdict → `omitted`. A required item can never leave the denominator |
| 1.5 | Evidence snapshotter | capture + hash + timestamp; detect stale/absent/conflicting/unauthorized states |
| 1.6 | Packet assembly + persistence | path-confined, ledger-emitting, tenant-scoped |
| 1.7 | Abstention engine | the universal abstain rule: never evaluate on assumed facts |

**Adversarial tests written first (1.0):** forged verdict on an omitted item · evidence ref without
a hash · Tier-B claim citing no rule · packet claiming `supported` with zero evidence · manifest
item silently dropped.

**Exit:** given a fixture release, ARIA emits a schema-valid packet exercising all four verdicts,
with hashes and timestamps on every evidence ref.

---

### M2 — Release Readiness validators (1–1.5 weeks)

Turn `RELEASE_READINESS_POLICY_RULES_V0.md` into executable validators. New `aria/roles/release_readiness/`.

| # | Task |
|---|---|
| 2.1 | Tier-A fact extractors: approvals, check runs, rollback doc, release ticket, incidents, dependency diff, timestamps |
| 2.2 | Tier-B rule engine: RR-001…RR-008, each citing its `rule_id`, each with its own `abstain_when` |
| 2.3 | Disposition function: `not-ready > insufficient-evidence > ready` ordering exactly as specified |
| 2.4 | Freshness + authorization checks (RR-007) |
| 2.5 | **All 12 adversarial cases** from benchmark §10 as tests — stale, conflicting, missing, unauthorized, near-miss, ambiguous, **prompt injection**, corrupt log, duplicate ids, freshness boundary, missing policy, retracted approval |

**Prompt injection is mandatory and non-negotiable:** ARIA reads PR bodies and ticket text. A
`supported` verdict induced by attacker-controlled source text is a critical false-safe with a
security root cause. It must be ignored *and flagged*.

**Exit:** validators produce correct verdicts on constructed cases including all 12 adversarial
cases; zero critical false-safes on the constructed set.

---

### M3 — Baseline arm (3–4 days)

The comparator, built fairly or the benchmark is worthless.

| # | Task |
|---|---|
| 3.1 | Mainstream LLM agent, same model, same read access, good-faith prompt, tool-call audit log |
| 3.2 | Answers the **same manifest**, same verdict vocabulary |
| 3.3 | Config frozen and recorded: prompt, framework, model, temperature, tools, build hours |
| 3.4 | Written for independent fairness review; **never tuned after seeing ARIA's results** |

**Exit:** both arms answer an identical manifest on the same fixture releases; configs frozen and hashed.

---

### M4 — Genericize + persistent employee (1 week)

| # | Task | File(s) |
|---|---|---|
| 4.1 | `TenantOrgProfile` — org name, industry, services, metrics, project keys | `aria/tenancy/runtime.py` |
| 4.2 | Extend `_REGISTRY` 1 → 6 prompts; convert the five remaining `_SYSTEM` literals to templates (mechanism already proven at `pr_review_skill.py:126`) | `aria/evolution/component_registry.py`, `aria/skills/*.py` |
| 4.3 | De-bias the evaluator and rubric | `aria/evaluation/evaluator.py:48`, `rubrics.py:91` |
| 4.4 | Per-vertical fixture/runbook packs; drop `ARIAMasterPlan.jsx` and the AU footer from the product build | `aria/connectors/fixtures/`, `aria/knowledge/seed_docs/`, frontend |
| 4.5 | Stable `employee_id` + employee table; hire/onboard/retire lifecycle | `aria/employee/` |
| 4.6 | `get_employee_record()` deriving completion, quality-pass, correction, escalation, evidence-block rates from the ledger | `aria/employee/`, `aria/ledger/metrics.py` |

**Exit:** `grep -ri "amar ujala"` clean in the product build; a 90-day employment record renders
from real ledger data.

---

## 3. Schedule

| Milestone | Duration | Cumulative |
|---|---|---|
| M0 Make it real | 3–4 days | week 1 |
| M1 Work Proof Packet | 1 week | week 2 |
| M2 Release Readiness validators | 1–1.5 weeks | week 3–4 |
| M3 Baseline arm | 3–4 days | week 4 |
| M4 Genericize + persistent employee | 1 week | week 5 |

**~5 weeks.** At the end, ARIA can produce and evaluate Work Proof Packets for Release Readiness,
and Gates A/B can run the day a corpus and custodian exist.

---

## 4. Working discipline

Carried over from the accepted build-review protocol:

- **Adversarial tests before implementation** for every security or integrity boundary
- **Deny-by-default** everywhere: missing evidence never becomes an assumption
- **No fabricated numbers** in any output, ROI, or report
- **Path confinement + transactional audit outbox** for every new store
- **Secrets masked**, structural ids rejected, safe typed errors only
- Full backend suite green at every milestone exit
- **No commit, push, or deploy without founder authorization**
- Everything enters Codex's review queue on its return

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| **Claude builds and reviews its own work** | Adversarial-tests-first; mandatory Codex re-audit; founder approves |
| Tier-B rules prove unscoreable on real data | M2 surfaces this early; if most checks are Tier C judgment, benchmark design changes **before** freeze |
| Building the wrong thing while benchmark is unproven | Scope hard-limited to what the benchmark measures |
| Corpus never arrives | M0–M4 still deliver a real, generic, authenticated product regardless |
| Conflict with Codex's uncommitted coordinator work | Do not touch `aria/braintrust/` except §0.6 if explicitly authorized |

---

## 6. Founder decisions needed before M0

1. **Confirm the role change** — Claude builds during Codex's absence.
2. **§0.6** — should Claude fix the build-review P1 in Codex's code, or leave it for Codex?
3. **Commit policy** — commit at each milestone exit, or hold everything until Codex reviews?
4. **The five untracked docs** — commit now? They are additive and currently exist only on one laptop.
