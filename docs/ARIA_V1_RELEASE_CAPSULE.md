# ARIA V1 Release Capsule

**Release status:** ARIA V1 and V1.1 accepted  
**V1 launch-readiness commit:** `abf0096`  
**V1.1 local-chat commit:** `d199a51`  
**Backend baseline:** `1048 passed, 1 skipped`  
**Public release:** Blocked pending employer/IP approval

This document is the concise source of truth for the accepted ARIA V1 release.
Where older Week 30 documents show `1027 passed, 1 skipped`, that remains the
correct historical Week 30 baseline. The current V1.1 baseline is
`1048 passed, 1 skipped`.

## 1. Executive Summary

ARIA V1 is a governed AI Employee Platform prototype built using Harness
Engineering. It demonstrates task intake, routing, typed skill execution,
evidence-gated responses, approval controls, artifacts, memory infrastructure,
a typed Work Ledger, ROI metrics, governed update lifecycle, dataset export,
and model-lifecycle readiness.

ARIA V1.1 adds a safe local terminal chat surface over the accepted graph. It
does not add production autonomy or live integrations.

The honest positioning is:

> ARIA V1 is a governed AI Employee Platform prototype and launch-ready demo,
> proving task routing, skill execution, artifacts, Work Ledger, ROI,
> governance, model lifecycle, dataset export, and fine-tuning readiness
> without claiming production autonomy.

ARIA is not a fully autonomous person, a production AI employee, or a deployed
fine-tuned model. The platform and its governance harness are the product; the
model is a replaceable component.

## 2. Final Accepted Commits

| Scope | Commit | Accepted state |
|---|---|---|
| Week 29 foundation | `9590750` | Work Ledger v2, ROI Dashboard, Dataset Export, Model Registry v1, Fine-Tuning Prototype |
| Week 30 launch readiness | `abf0096` | Golden demo, launch package, truth audit, reliability fixes |
| V1.1 usability wrapper | `d199a51` | Safe local terminal chat, offline-by-default policy, mutation guards, error redaction |

The accepted V1 release line ends at `d199a51`.

## 3. What ARIA V1 Is

ARIA V1 is:

- A LangGraph-based task orchestration runtime.
- A set of typed engineering and analytics skills.
- A governed execution harness with action tiers and approvals.
- A fail-closed evidence system for supported platform claims.
- A Work Ledger and ROI measurement foundation.
- A memory, RAG, and code-intelligence proof.
- A governed self-improvement and rollback pipeline.
- A launch-ready internal demonstration package.

Canonical positioning:

> Claude gives intelligence. ARIA gives governed work ownership.

> ARIA is built using Harness Engineering: the model is only one component;
> the real intelligence comes from orchestration, memory, tools, governance,
> evaluation, workflows, Work Ledger, ROI measurement, and safe execution
> around the model.

## 4. What V1.1 Added

V1.1 added `aria.chat`, a local natural-language terminal interface over the
existing `aria_graph`.

It provides:

- `uv run python -m aria.chat` for offline deterministic interaction.
- `--llm` as an explicit opt-in to a configured live model.
- Reuse of the accepted router, skills, evidence gate, approvals, and respond
  path without duplicating skill logic.
- A restrictive chat policy:
  `surface="local_chat"`, `execution_mode="dry_run"`,
  `allow_mutations=False`.
- Blocking of state-changing evolution scan, evaluation, promotion, and
  rollback commands.
- Offline suppression of provider calls and LangSmith tracing.
- Redaction of audited exception paths before they reach users or ledgers.

Offline chat is primarily a workflow and governance demonstration. Its default
responses are deterministic skill outputs, not evidence of human-level
conversation quality or persistent conversational understanding.

## 5. Built

The following capabilities are implemented, tested, and runnable:

- LangGraph lifecycle: intake -> router -> skill -> evidence gate -> respond.
- Keyword routing and optional LLM routing.
- PR review, KPI, CI/CD, Jira drafting, QA, and test-review skills.
- Typed Pydantic input/output contracts.
- Fail-closed KPI and CI/CD evidence gates.
- Action tiers T1-T3, with T4 actions requiring explicit approval.
- Work Ledger v2 schemas, writer, reader, metrics, and API.
- ROI Dashboard consuming ledger metrics.
- Memory models and local memory store.
- RAG strategies and AST-based code intelligence.
- Evaluation harness and deterministic regression suites.
- Governed evolution pipeline:
  monitor -> propose -> sandbox -> evaluate -> approve -> canary -> rollback.
- Model Lifecycle Registry v1.
- Privacy-safe SFT/DPO dataset export prototype.
- Local chat REPL and offline golden-path demo.

## 6. Partially Built

| Capability | Works today | Remaining boundary |
|---|---|---|
| Live Work Ledger emission | The live graph emits terminal `Responded` or `Failed` events | The full event taxonomy is seeded/tested but not auto-emitted at every live graph stage |
| Jira | Draft generation and T4 approval gating | Real Jira REST writes are not connected |
| Teams and voice | Bot/API/frontend components exist | No audited live hosted deployment with credentials |
| Model Router | Routes by task, risk, privacy, and model tier | Not connected to a trained self-hosted specialist |
| Memory | Typed task, outcome, decision, artifact, and institutional-memory infrastructure exists | Casual chat does not yet become approved long-term domain knowledge |
| Local chat | Reuses the governed graph and supports optional LLM mode | Default mode is deterministic and does not maintain employee-like conversational memory |

## 7. Prototype-Only

The following prove architecture and lifecycle, not production operation:

- Fine-tuning planner and runner.
- SFT/DPO dataset preparation.
- Offline model evaluation and registry lifecycle.
- Seeded lifecycle events used by the golden demo for ROI reporting.
- Mock Jira creation.
- Mock/local Teams notifications.

No model weights were trained. No model was activated. No production endpoint
was deployed.

## 8. Roadmap-Only

The following are documented V2/V3 capabilities and are not part of V1:

- Real fine-tuning and production model deployment.
- vLLM serving.
- Production Jira, Teams, GitHub, and CI/CD writes.
- Subagent Instruction Engine and governed delegation.
- Persistent agent workspaces and Generative UI Canvas.
- A2A-ready external interoperability.
- Agent identity and delegated authorization.
- Agent security gateway.
- Branching agent experiments.
- Multi-tenant AI Employee as a Service.
- Unsupervised autonomous self-modification.

## 9. Run Local Chat

From the repository:

```powershell
cd apps/backend
uv run python -m aria.chat
```

This is the default offline mode:

- No paid LLM call.
- No LangSmith network tracing.
- Keyword routing and deterministic skill outputs.
- Local runtime logs may be written.
- Production mutations remain blocked.

Live model mode is explicitly opt-in:

```powershell
uv run python -m aria.chat --llm
```

This mode may make paid provider calls when credentials are configured. It does
not enable live Jira/Teams/GitHub writes or evolution mutations.

## 10. Run the Golden Demo

```powershell
cd apps/backend
uv run python -m aria.demo.golden_path
```

The demo is offline and deterministic. It demonstrates:

1. Real graph routing and skill execution using offline skill paths.
2. Evidence-gate withholding for unsupported KPI and CI/CD claims.
3. A Jira draft behind the T4 approval boundary.
4. Real terminal Work Ledger events.
5. Seeded typed lifecycle events for richer approval/failure/rollback metrics.
6. ROI aggregation through `LedgerMetrics.summary()`.

The seeded lifecycle is demonstration data, not production history.

## 11. Run Proof Demos

Run these from `apps/backend`:

```powershell
uv run python -m aria.ledger.demo --dashboard
uv run python -m aria.model_registry.demo
uv run python -m aria.training_data.demo
uv run python -m aria.fine_tuning.demo
```

They prove typed ledger metrics, registry lifecycle, privacy-safe dataset export,
and the offline fine-tuning pipeline shape. They do not train or deploy a model.

## 12. Test Baseline

Current accepted V1.1 backend baseline:

```text
1048 passed, 1 skipped
```

Command:

```powershell
cd apps/backend
uv run --group dev python -m pytest -q
```

The historical Week 30 launch-readiness baseline was
`1027 passed, 1 skipped`. V1.1 added the local-chat boundary tests.

## 13. Architecture Summary

The primary request path is:

```text
request -> intake -> router -> skill -> evidence gate -> respond -> ledger -> ROI
```

ARIA uses seven harness layers:

| Layer | V1 status |
|---|---|
| Runtime Harness | Built: LangGraph, state, retries, budgets, failure handling |
| Tool Execution Harness | Built/partial: typed skills, dry-run, idempotency, audit; real connectors deferred |
| Governance Harness | Built: action tiers, approvals, privacy and evidence gates |
| Evaluation Harness | Built: deterministic regressions, rubrics, eval components |
| Memory Harness | Built infrastructure; employee-like domain recall remains V2 |
| Evolution Harness | Built as a human-gated pipeline with canary and rollback |
| Subagent/Workflow Harness | Roadmap-only |

## 14. Work Ledger, ROI, and Governance

Work Ledger v2 provides typed, immutable event contracts with task,
correlation, actor, workflow, model, cost, approval, risk, and outcome fields.

Metrics include:

- Tasks completed and tasks by skill.
- Approval and failure rates.
- Average resolution time.
- Estimated cost per task.
- Human intervention rate.
- Artifact and correction counts.
- Model usage breakdown.
- Legacy/v2/malformed source counts.

Governance is structural:

- Unsupported evidence-sensitive claims are withheld.
- High-risk actions require approval.
- Local chat is dry-run and mutation-blocked.
- Restricted model routing fails closed where configured.
- Update activation is versioned, confined, verified, and rollback-capable.

The live graph currently auto-emits terminal events only. The richer lifecycle
taxonomy is implemented and tested but is not yet emitted automatically at every
live graph stage.

## 15. Model Registry and Fine-Tuning Prototype Boundary

The Model Lifecycle Registry v1 tracks model identity, dataset provenance,
evaluation results, status, production consumer, activation history, and
rollback targets.

The fine-tuning prototype:

- Reads governed, content-bound exported datasets.
- Plans an offline candidate run.
- Registers and evaluates a prototype candidate.
- Verifies that the active production model remains unchanged.

It does not:

- Train weights.
- Download a training base model.
- Use a GPU.
- Serve through vLLM.
- Update production model routing.
- Activate a model.
- Deploy an endpoint.

The accepted demonstration state is `active model: NONE`.

## 16. Public Release Warning

The repository is cleared for internal demonstration, not public publication.

Public GitHub, LinkedIn, or external sharing remains blocked until:

- Employer/IP approval is obtained, or a separately reviewed generic version is
  produced.
- Employer-specific names and internal hostnames are removed.
- Intentional fake-secret test fixtures are documented or allowlisted.
- Runtime files, datasets, model artifacts, and credentials are rescanned.
- Public claims pass the Truth & Claim Audit.

The current release capsule does not authorize public release.

## 17. What Must Not Be Claimed

Do not claim:

- ARIA is fully autonomous or a human replacement.
- All 24 capability pillars are operational.
- ARIA is running in production.
- ARIA creates real Jira tickets or sends real Teams messages.
- A fine-tuned model was trained, activated, or deployed.
- vLLM is serving a model.
- Self-evolution is continuously autonomous.
- Demo ROI figures are production ROI.
- Local chat has persistent employee-like memory.
- Local chat's deterministic offline responses prove model intelligence.

Use these truthful alternatives:

- "Governed AI Employee Platform prototype."
- "Human-approved self-improvement pipeline."
- "Fine-tuning readiness prototype."
- "ROI measurement built on typed local ledger data."
- "Local chat wrapper over the governed graph."

## 18. V2 Next Priorities

V2 should begin with a small number of real, measurable workflows:

1. PR review -> approved review comments or governed Jira action.
2. CI/CD failure investigation -> evidence-backed Teams summary.
3. Analytics/events/KPI investigation -> cited action report.

Foundational V2 work should include:

- Domain Memory / Data Dictionary Memory.
- Full live Work Ledger lifecycle emission.
- Durable connector execution with idempotency and approval resumption.
- Real evidence-source ingestion and authorization.
- Production-grade identity, permissions, and secret handling.
- Evaluation against real workflow outcomes before broader autonomy.

V2 should not start by adding many new skills. It should make a few workflows
reliable, stateful, measurable, and genuinely useful.

## 19. V2 Required Capability: Domain Memory / Data Dictionary Memory

V1/V1.1 contains memory infrastructure and memory lifecycle proof. It does not
yet provide employee-like long-term business memory learned safely from casual
conversation.

Example user statement:

> In story_events table, event_type = 1 means page_view, event_type = 2 means
> story_click, event_type = 3 means notification_open.

V2 should treat this as a proposed domain-memory update, not immediate truth.
The required lifecycle is:

1. Detect that the message contains reusable domain knowledge.
2. Extract a structured proposed mapping.
3. Show the proposed memory record and ask for approval.
4. Save only after approval as scoped persistent project memory.
5. Record metadata:
   - table: `story_events`
   - field: `event_type`
   - mapping: `1 -> page_view`, `2 -> story_click`,
     `3 -> notification_open`
   - source
   - owner
   - timestamp
   - confidence
   - project/environment scope
   - version
6. Retrieve the mapping automatically during future analytics or event
   investigations.
7. Support correction, replacement, deletion, version history, and rollback.
8. Log the proposal, approval, write, update, and deletion in the Work Ledger.
9. Preserve authorization and confidentiality boundaries during retrieval.

Non-negotiable rule:

> ARIA must never treat unapproved casual text as permanent organizational
> truth.

This is a V2 requirement. It is documented here only and is not implemented by
this release.

---

## Final Current-State Description

ARIA V1/V1.1 is an accepted, launch-ready internal prototype of a governed AI
Employee Platform. It demonstrates the harness required to route work, run typed
skills, withhold unsupported claims, require approvals, record outcomes, compute
ROI, prepare governed training data, manage model lifecycle records, and propose
versioned improvements with rollback.

It remains intentionally bounded: no production deployment, no live connector
writes, no trained specialist model, no vLLM serving, no autonomous
self-modification, and no approved conversational domain-memory learning yet.
