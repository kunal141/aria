# ARIA Integrated Virtual Employee Audit and Proof

Status: **Independent audit complete; awaiting commit approval.**

This document records the repository-backed product boundary after integrating the
V3 goal/work/governance stack with the uncommitted V4.1 runtime-adapter and V4.2
model-routing foundations. It does not declare production readiness, deployment,
public release, live external execution, or employer/IP approval.

## Direct answer

Before this integration, only the individual V1-V4.2 capabilities existed. ARIA did
not have one authority-checked flow joining goal intake to a corrected manager
deliverable. The new `aria.employee` layer composes those authorities and proves the
full local workflow. ARIA is functionally complete for the repository's
**deterministic, offline, governed virtual-employee proof scope**. It remains
intentionally incomplete for production/live use.

## Capability matrix

| Capability | Expected behaviour | Existing implementation / evidence | Tests | Maturity | Missing gap / required action |
|---|---|---|---|---|---|
| Manager interaction/API | Start, explicitly approve completion, and inspect employee work | `aria/api/v4_employee.py`; POST/approval/list/detail | `test_final_virtual_employee.py` | Complete | Production authentication/authorization remains out of scope |
| Goal ownership | Persist and own a business goal | `aria/goals/service.py`, `aria/goals/store.py` | V3.1 + integrated flow | Complete | None for local scope |
| Clarification | Identify missing context and record answers | Goal intake questions; integrated service records answers derived only from manager-supplied structured data | Integrated clarification assertions | Complete | Interactive multi-turn clarification remains a V2 chat capability, not this synchronous endpoint |
| Success criteria | Generate measurable criteria | `aria/goals/intake.py`; exposed in manager view | V3.1 + integrated flow | Complete | None for proof scope |
| Planning/decomposition | Roadmap and task board | `aria/goals/intake.py`, `service.py`, `store.py` | V3.1/V3.2 | Complete | None |
| Task dependencies | Govern dependency order | `aria/goals/supervisor.py` dependency plan | V3.4 + integrated supervision | Complete | Domain templates remain deterministic fixtures |
| Workforce assignment | One bounded analysis worker requires the exact persisted fixture evidence; every model attempt cites its completed assignment | `aria/goals/agents.py`, `aria/employee/store.py` | V3.3/V3.4 + integrated worker-authority tests | Complete | Dry-run workers only |
| Supervisor/governance | Budget, risk, evidence and approval blocks | `aria/goals/supervisor.py` | V3.4 regressions | Complete | No autonomous live worker processes |
| Model routing | Select provider/model by policy | `aria/model_routing/`; persisted decision linked to run, goal, and evidence | V4.2 + integrated authority tests | Complete | V4.2 remains uncommitted pending approval |
| Sovereignty/fallback | Hard exclusions and deterministic fallback | `aria/model_routing/policy.py`, `router.py` | V4.2 suite | Complete | Mock provider profiles only |
| Runtime adapters | Govern replaceable worker runtime | `aria/runtime_adapters/`; internal mock only | V4.1 + integrated receipt tests | Complete for mock scope | Future/external adapters remain blocked stubs |
| Skills/tools | Reuse bounded skills and worker contracts | V1 skills, V3.3 briefs, V3.5 skill evolution proposals | Existing V1/V3 suites | Complete for proof | No generated production skill activation |
| Approvals | Require an explicit local manager decision before final completion | Approval task + employee authority + documented decision-only endpoint | Integrated approval and direct-store tests | Complete | Attribution is not production authorization; sensitive/live actions stay blocked |
| Controlled execution | Preview then permitted local mock | V4.1 preview + internal mock receipts | V4.1 + integrated flow | Complete for mock scope | Live execution is blocked by design |
| Memory | Approved scoped persistent memory | `aria/memory_v2/`, V3.6 work memory | V2/V3 suites | Complete | Sensitive memory requires future authenticated identity |
| Retrieval/knowledge | Cited memory and fixture evidence | Domain memory citations, fixture dataset refs | V2/V3.6 + integrated evidence assertions | Complete | No live browsing or uncontrolled world ingestion |
| Evaluation | Source-checkable business quality criteria | `aria/employee/evaluation.py` | Concrete missing-risk and authority tests | Complete | Deterministic evaluator, not an external judge |
| Bounded correction | Preserve failure, plan repair, retry | `aria/employee/service.py`, `store.py` | Failed then passed two-attempt proof | Complete | Max five attempts, intentionally no recursion |
| Escalation | Stop after retry exhaustion | Store-enforced exhausted-attempt transition | Exhaustion test | Complete | Human review is recorded, not externally messaged |
| Work Ledger | Durable hierarchical audit trail; goal planning uses the goal ID and route/adapter/employee events use the employee run ID | Employee outbox plus existing V3/V4 events | Correlation, ordering, retry, report, and outbox-recovery tests | Complete | No distributed trace service |
| Receipts/evidence | Persist real request/preview/mock receipt refs | V4.1 store corroborated by employee authority | Foreign-receipt rejection test | Complete | No external receipt exists by design |
| Observability | Manager-visible status and history | `ManagerRunView`, run list/detail API | API and restart tests | Complete for local scope | No production telemetry backend |
| Cost/latency | Report declared policy-profile estimates | Route cost profile and declared latency summed per attempt | Manager view test | Complete for proof | Not measured provider billing/latency |
| ROI | Transparent conservative estimate derived from persisted completed work tasks plus the manager report | Employee authority stores the formula and cited task/artifact refs | Manager authority test | Complete for proof | Production ROI needs real approved operational data |
| Manager dashboard | Inspect goal, plan, tasks, workers, route, adapters, blockers, evaluations and outputs | V4 employee detail response | API test | Complete for API-first scope | No new large frontend was added |
| Security/privacy | Fail closed, sanitize secrets, confine paths | Store authority corroboration; `ARIA_DATA_DIR`; safe API errors | Secret/path/direct-store tests | Complete for proof | Production identity and authorization remain future work |
| Deterministic demo | One command, first failure, repair, final report | `python -m aria.demo.virtual_employee` | Demo isolation test | Complete | No live data/model/runtime |
| Product documentation | State real proof and non-goals | This document plus V1-V4 roadmap/boundary docs | `git diff --check` | Complete but needs hardening | Update official status only after acceptance |
| Production deployment | Real authenticated multi-user service | Not implemented | N/A | Out of scope | Requires employer/IP approval and a separate production program |
| Live integrations/writes | Jira/Teams/GitHub/provider execution | Explicitly absent/blocked | Negative route tests | Blocked by approval | Do not add without identity, authorization, sandbox and independent audit |

## Integrated proof

Run from `apps/backend`:

```powershell
uv run python -m aria.demo.virtual_employee
```

The proof performs:

```text
goal intake
-> clarification from supplied structured context
-> success criteria + roadmap + tasks
-> bounded workforce + supervisor
-> governed V4.2 route decision
-> V4.1 internal-mock preview and receipt
-> intentionally incomplete first manager report
-> concrete missing_risks evaluation
-> persisted repair plan
-> second preview/mock attempt
-> passed evaluation
-> manager report awaiting explicit local manager approval
-> approved completion + task-backed cost/latency/ROI view
-> correlated Work Ledger events
```

Expected proof output includes:

```text
status: completed
attempts: quality_failed, passed
repair: missing_risks
quality: 1.00
adapter: rta-internal-mock (internal mock only)
receipts: 4
```

## Store authority

`EmployeeRunStore` is not a passive database. It requires:

* a persisted goal and workspace before run creation;
* a completed evidence-backed worker assignment for every attempt;
* a real, allowed, unexecuted V4.2 decision correlated to the employee run, goal, and fixture;
* the persisted internal-mock adapter definition;
* a V4.1 request bound to the run, goal, workspace, worker, route, and evidence;
* matching persisted preview and mock-completed receipts;
* no replay of a request or receipt across attempts;
* an artifact confined to the run workspace;
* a quality evaluation recomputed from the persisted dataset and report;
* a persisted repair plan before any retry;
* a passed authoritative evaluation and byte-identical manager artifact before approval;
* completed work tasks, a completed approval task, and a completed goal before finalization;
* ROI recomputed from those persisted task and artifact records;
* exhausted failed attempts before escalation.

State and employee audit events commit through one SQLite transaction and a durable
outbox. Ledger failure leaves state committed with ordered audit records queued for
recovery; exception text is never persisted.

## Binding boundaries

* Offline deterministic fixture only.
* No API key or `.env` is read.
* No network, provider API, local model, external service, SDK, MCP, subprocess or Docker.
* No real Jira, Teams, GitHub, email, webhook or connector write.
* No automatic approval, skill activation, live runtime activation or deployment.
* No uncontrolled recursive self-learning or production self-modification.
* `ARIA_USER_ID` remains attribution only, never authorization.
* Public release remains blocked pending employer/IP approval.
* Unrelated personal, presentation and exported-data files remain excluded.

## Independent validation

The final audit used two repair loops. It closed premature completion, incorrect
clarification attribution, unsupported fixed ROI, decorative blocked workers,
uncorrelated adapter events, missing retry/report events, replay/cross-run binding
gaps, and unnecessary demo access to ambient credential variables.

Validated baseline:

```text
Integrated employee suite: 30 passed
V3.9/V3.10/V4.1/V4.2/final slice: 242 passed
Full backend: 1725 passed, 1 skipped
Frontend: 33 passed
Frontend build: passed
Compile check: passed
Ruff: passed except the established UP042 enum convention
git diff --check: passed
Proof demo: identical business output across two runs; quality_failed -> repair -> passed
```

V4.2 and the integrated layer are ready for separate, intentionally scoped commits
after owner approval. No push, deployment, publication, or live activation is
authorized.
