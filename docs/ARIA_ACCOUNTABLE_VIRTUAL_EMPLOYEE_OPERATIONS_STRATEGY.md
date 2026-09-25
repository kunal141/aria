# ARIA — Accountable Virtual Employee Operations Strategy

**Version:** 2.0 · **Status:** Canonical product and build strategy, 2026-08-17. Conceptual
architecture **frozen** — future work is judged against this document rather than reopening the
strategy. Reopen only when empirical evidence forces it.

**Current product boundary:** ARIA has a governed, tenant-aware, offline/internal-mock
virtual-employee foundation, private-staging packaging, and a Codex↔Claude build-review
coordinator. It does **not** yet have durable employee identities, live execution, proof-quality
data connectors, an attribution layer, or any verified label. Public release and
commercialization remain blocked pending employer/IP review.

**v2 changelog:** moat redefined from *proof-carrying work* to **Verified Operational Learning** ·
added the Attribution layer, label economics, and the work/learning integrity taxonomies · added
the temporal invariant · authority reformulated as ceiling-vs-position · employee portfolio
re-ranked on outcome observability (Data Analyst split into Data Quality vs Data Analyst) ·
GTM criterion added · three-layer product model added · build gates restructured to A/B/C.

---

## 1. Founder Decision

ARIA builds the category of **Accountable Virtual Employee Operations (AVEO)** — used internally
as the operating thesis. Customer-facing language leads with the doctrine, not the acronym.

The product unit is an **Accountable Virtual Employee**: a persistent, supervised digital team
member that owns recurring commitments, works through bounded tools and specialists, carries
proof for material work, earns authority through verified performance, and improves from what
actually happened.

> **Doctrine — Assign outcomes. Bound authority. Prove the work. Learn from what actually happened.**

The first three are **product doctrine**. The fourth is the **moat engine**.

> **Moat — Verified Operational Learning.**
> ARIA develops a proprietary, organization-specific understanding of how work actually succeeds,
> built from attributable verified outcomes.

### Locked decisions

| Decision | Value |
|---|---|
| Company direction | Accountable virtual employees, not a generic agent builder |
| Platform scope | Cross-department by design, narrow first role |
| First role | Release Readiness Coordinator |
| Second role | QA Employee (label quality), then Data Quality |
| Cross-department proof | Vendor Onboarding — proves kernel generality, **not** a fuel source |
| Deployment | Private/deploy-per-organization first |
| Commercial posture | Managed commitments and verified outcomes; never headcount replacement |
| Safety posture | No automatic promotion, blanket autonomy, uncontrolled browsing, silent self-modification, or unapproved material action |

---

## 2. The Problem, and the Market Reality

Organizations can create agents quickly. They still cannot delegate durable responsibility,
because managers cannot efficiently answer: what outcome does this own · who supervises it ·
what may it touch right now · which claims are supported, stale, or unknown · what did it
actually do · did the downstream outcome occur · how much intervention did it need · has it
earned more authority · can we replace the model without losing history.

**Market reality — identity and governance are no longer differentiators.** Microsoft Entra Agent
ID and Agent 365 ship agent identity, lifecycle governance, Conditional Access, and an enterprise
control plane. Workday's Agent System of Record manages agent roles, lifecycle, impact and cost.
ServiceNow AI Control Tower covers AI discovery, risk/compliance, runtime monitoring,
auditability, and value measurement. Asana positions an operating system for human-agent
teams.[1][2][3][4]

Therefore ARIA must not claim novelty in identity, governance, workforce vocabulary, memory, or
agent orchestration. The falsifiable advantage is:

> **Higher accepted-outcome integrity at lower manager verification effort, with verified
> outcomes that measurably improve subsequent work — across recurring commitments and more than
> one department.**

No equivalent organization-specific, verified-outcome-driven **earned-authority** mechanism was
found in the public material of the incumbents above. That is a wedge, not a permanent exclusion —
they can build it, but doing so cuts against products sold on confident answers.

---

## 3. The Core Operating Chain

Everything in ARIA is one of these nine stages. If a feature does not serve a stage, it is not
in scope.

```text
Outcome Contract → Authority → Execution → Proof → Observed Outcome
                                                        ↓
                          Learning ← Trusted Label ← Verification ← Attribution
```

| Stage | Question it answers |
|---|---|
| **Outcome Contract** | What exactly has ARIA committed to deliver? |
| **Authority** | What is it allowed to do, to what, under which conditions? |
| **Execution** | The work itself, through bounded tools and specialists |
| **Proof** | Can ARIA demonstrate the commitment was satisfied? |
| **Observed Outcome** | What actually happened downstream? |
| **Attribution** | Was ARIA's work causally relevant? |
| **Verification** | Does this need human confirmation, and from which stream? |
| **Trusted Label** | A defensible signal, with provenance and confidence |
| **Learning** | Routing, abstention, authority, evaluation depth, workflow discovery |

---

## 4. What Makes This an Employee

Every ARIA employee requires: stable tenant-scoped identity with a human sponsor · a role charter
with explicit non-responsibilities · a commitment portfolio of recurring owned outcomes · team
membership and escalation relationships · scoped memory separating approved organizational
knowledge from episodic history and source-cited world knowledge · versioned capability licences ·
a performance record · a learning plan · and a lifecycle (hire → onboard → probation → active →
restricted → suspended → retired) with policy-governed retention.

One visible employee may coordinate many temporary specialists internally. **Those specialists are
implementation details.** The manager assigns responsibility to the employee and receives one
coherent result, exception trail, and performance record.

---

## 5. The Universal Contracts

Cross-department generality means these contracts work unchanged for Engineering, QA, Data,
Finance, Procurement, Compliance, Marketing, Sales and People Ops. **If a second department
requires changing a contract rather than adding a role pack, the platform thesis has failed.**

**5.1 Employee** — `employee_id · tenant_id · human_sponsor · manager_and_team ·
role_charter_version · objectives_and_service_levels · employment_status · capability_licences ·
memory_scopes · risk_and_budget_limits`

**5.2 Commitment** — `commitment_id · desired_outcome · owner_employee_id · cadence_or_deadline ·
success_and_acceptance_criteria · authoritative_sources · dependencies_and_handoffs ·
exception_and_escalation_policy · materiality_and_risk`

A commitment is not satisfied because an artifact was produced. It is satisfied when ARIA can
state: **outcome · evidence · missing evidence · confidence · authority exercised · next action.**

**5.3 Authority Lease** — authority is runtime-enforced, never a permanent role flag:
`employee × capability × target_system × data_scope × action × risk × budget × expiry`
Each lease records approving human, evidence basis, issue time, expiry, revocation state, and
permitted compensation/rollback.

**5.4 Work Proof Packet** — `commitment → source snapshots + content hashes → atomic claims →
authority/freshness/classification checks → validators and uncertainty → decision and approvals →
action request + lease → execution receipt → observed outcome → correction`

**5.5 Handoff** — `sender · recipient · work_item · acceptance_criteria · evidence_and_context ·
deadline · accepted_or_rejected_at · exception_owner`

**5.6 Memory** — scoped by tenant, employee, project, purpose, sensitivity, source, owner,
confidence, validity window, retention. Casual text never becomes organizational truth without
approval. World knowledge is source-cited and cannot override approved company memory.

**5.7 Performance** — accepted/rejected outcomes · integrity failure counts by class · evidence
precision and coverage · correct abstention · correction and escalation rates · human verification
minutes · SLA adherence · incidents · measured cost, latency, business effect.

**5.8 Learning and Evolution** — `signal → cited gap → proposal → specification → tests →
sandbox/shadow → evaluation → human approval → bounded activation → monitor → rollback`.
Observed failure can produce a proposal. It can never silently change production behaviour.

**5.9 Attribution** *(new in v2)* — `observed_outcome · candidate_decision · evidence_tier ·
attribution_verdict · confidence · adjudicator · excluded_reason`

**5.10 Label** *(new in v2)* — `decision_ref · outcome_ref · attribution_ref · label_source ·
verification_stream · failure_class · confidence · decision_time · label_time`

---

## 6. The Moat: Verified Operational Learning

**Proof is not the moat. Proof is the machine that manufactures the moat.**

Evidence-backed AI is copyable. What is not copyable is an organization-specific corpus of
*attributable, verified* outcomes accumulated over months of real work.

```text
Proof  →  trustworthy evidence
Attribution + Verification  →  trustworthy labels
Trustworthy labels  →  organization-specific operating knowledge
```

### 6.1 Attribution — deny by default

> **A downstream outcome is not a label. It is only a label candidate.**

A rollback six hours after ARIA approved a release may be caused by ARIA, a vendor outage,
another engineer's config push, or a traffic spike. Converting correlation into labels poisons
the accumulator faster than having no labels at all.

Rules:

1. **Deny by default.** If the outcome cannot be confidently linked to ARIA's work, mark it
   `unattributable` and **exclude it from learning entirely.** Do not downweight it — discard it.
2. **Harvest, don't infer.** Take attribution from evidence the organization already produces —
   postmortems, RCA, CI/CD results, audit findings, reviewer corrections, incident records —
   rather than attempting causal inference from telemetry.
3. **Tier the evidence.** `directly observable > explicit RCA > human adjudication > circumstantial correlation`. RCA is not perfect ground truth and must not be treated as such.
4. **Evaluate the resolver.** Incorrect attribution corrupts every downstream label, so
   attribution precision, coverage, and false-attribution rate are themselves measured against
   human-adjudicated samples.

> **Label integrity beats label volume.**

### 6.2 Label economics — the fuel supply

Reducing manager effort also reduces label production. Left unmanaged, succeeding at the product
promise starves the moat. Three sources resolve it:

| Source | Description | Cost | Role |
|---|---|---|---|
| **Natural outcomes** | Operational systems produce the result without human review — deployment healthy after an observation window, reconciliation matched, ticket not reopened, defect escaped or not | Free | Primary fuel |
| **Active verification** | Humans review only high-information cases: uncertainty, novelty, validator disagreement, high materiality, new model/skill, domain drift | Targeted | Teaching |
| **Random verification** | Small independent stream sampled without regard to ARIA's confidence | Small, fixed | Measuring |

> **Active verification teaches. Random verification measures.**

Active selection is biased by construction, so any metric computed on it — **including calibration
error, whose entire job is detecting drift** — is distorted. A portion of the random stream is held
as a **locked holdout** that ARIA never trains on.

Verification intensity follows a curve: near-total early, then stratified sampling as confidence
accumulates. Effort falls; the measurement instrument survives.

**Label-economics metrics:** verified-label yield · automatic-label rate · verification minutes per
trustworthy label · attribution precision · attribution coverage · false-attribution rate ·
calibration error · correction yield · label coverage across task archetypes.

*An architecture producing 10,000 events and 13 trustworthy labels is not accumulating intelligence.*

### 6.3 Work-integrity failure classes

| Class | Meaning | Indicates |
|---|---|---|
| **Fabrication** | Asserted something no evidence supports | Grounding failure |
| **Contradiction** | Conclusion conflicts with available evidence | Extraction/reasoning failure |
| **Material omission** | Failed to surface something required for the outcome | Coverage failure |
| **Abstention failure** | Acted on insufficient evidence, or abstained despite sufficient evidence | Boundary miscalibration |

Silent omission of a critical item is treated as a safety failure equal to a false assertion — the
manager never sees the problem either way. Abstention failure is first-class because the
act/ask/abstain boundary is precisely what earned authority optimizes.

### 6.4 Learning-integrity failure classes

Misattribution · mislabelling · sampling bias · **temporal leakage** · drift contamination.

### 6.5 The temporal invariant *(hard architectural rule)*

> **No outcome, RCA, future state, or post-decision information may influence the reconstruction,
> evaluation, or learned policy for a decision — except as that decision's subsequent label.**
> Future information can label a past decision. It can never retroactively become part of the
> information that decision had.

```text
T0  decision moment — inputs available at T0, decision, proof packet, authority state
T1  outcome occurs
T2  RCA / attribution → trusted label
        ↓
    may improve decisions made AFTER T2 — never backwards
```

Violating this produces a system that "proves" it improved by evaluating against knowledge that
did not exist when it decided. That is backtest overfitting, and it is the failure most likely to
make ARIA look successful while delivering nothing.

### 6.6 What the accumulator compounds into

Learned model/tool/skill routing · better abstention boundaries · earned authority · evaluation-depth
selection · workflow discovery · and eventually controlled skill evolution.

Self-evolution is the **payoff, not the pitch**. It requires accumulated evidence that does not yet
exist, and leading with it invites the objection that kills enterprise deals.

---

## 7. Earned Authority

> **Policy defines the ceiling. Evidence determines how close ARIA is allowed to operate to it.**

An administrator defines what ARIA could ever be permitted to do. Verified performance determines
how much of that ceiling it currently receives. **ARIA can never earn permission the organization
never granted.**

| Stage | Behaviour | Human control |
|---|---|---|
| T1 Shadow | Reads, observes, produces private analysis | Reviews observations |
| T2 Recommend | Recommends with proof | Human decides and acts |
| T3 Draft | Creates reports, tickets, messages, change drafts | Human sends or applies |
| T4 Execute with approval | Performs a named reversible action | Fresh approval + valid lease per action |
| T5 Bounded autonomous | Executes a narrow reversible routine | Human-issued lease, monitoring, revocation |

Promotion requires minimum sample size, severity-weighted incident history, confidence bounds,
drift windows, anti-gaming checks, and human approval. Critical violations automatically contract
authority; restoration requires review. No organization-wide T5, no automatic promotion.

The employment record is durable, tenant-owned, policy-retained and **exportable**. It is not a
lock-in trap.

---

## 8. Product Model

```text
AI WORKFORCE      Release · QA · Data Quality · Incident · Delivery · Data Analyst · …
      ↓
EMPLOYEE FACTORY  role packs · skills · tools · evaluation templates · policy templates
      ↓
ARIA OS           Outcome Contracts · Authority · Proof · Memory · Work Ledger ·
                  Attribution · Verification · Verified Operational Learning
```

Three distinct things, deliberately not conflated:

- **Tools** — Jira, GitHub, SQL, CI/CD, email
- **Specialist agents/skills** — SQL agent, test agent, code-analysis agent
- **Virtual employees** — persistent business roles that own an outcome and coordinate the above

The **Employee Factory is not a prompt-to-agent builder.** A role pack must declare: outcome
schema · input/output schema · tool manifest · authority policy · proof requirements · evaluation
suite · escalation policy · failure taxonomy · **expected label sources** · audit/sampling policy ·
KPIs. Asked to "create a Data Quality Employee for Finance", ARIA must first establish what
outcomes it owns, what data it may access, what constitutes a critical anomaly, what requires
approval, what proof is mandatory, when it must abstain, how success will be observed, and which
downstream outcomes can become labels — *then* instantiate.

Agent builders are commodity. **The Employee Factory is the distribution layer for the moat** —
every additional employee gives Verified Operational Learning another domain to accumulate in.

---

## 9. Employee Portfolio

Ranked by **outcome observability and attribution quality**, not by demo appeal.

| # | Employee | Label quality | Note |
|---|---|---|---|
| 1 | **Release Readiness** | High — rollback/incident within hours, CI evidence, postmortems | Primary design-partner and benchmark role |
| 2 | **QA** | Highest — an escaped defect is unambiguous and attribution is trivial | Strongest natural feedback loop |
| 3 | **Data Quality** | High — reconciliation, schema, duplicate, freshness and balance checks self-verify | Strong accumulator |
| 4 | **Incident Response** | Excellent — RCA is its own deliverable | **Deferred for authority/action risk, despite excellent outcome observability and attribution quality** |
| 5 | **Delivery Operations** | Moderate — slippage observable | Useful, low action risk |
| 6 | **Data Analyst** | Low — insight correctness is subjective or slow, attribution poor | **Showcase/adoption role, not moat fuel** |

**Vendor Onboarding** remains the cross-department generality proof. Its ultimate outcomes are slow,
so it contributes intermediate labels only (document completeness, reviewer acceptance, missing
controls discovered, compliance exceptions, approval/rejection) and is **not** treated as an
accumulator.

The reasons above are recorded so future prioritization is not made on a false premise.

---

## 10. Commercial Wedge and GTM

**Selection criterion — pain alone is not enough:**

```text
volume × repetition × outcome observability × attribution quality × acceptable action risk
```

**Screening questions:** How often does this work happen? · Is essentially the same decision
repeated? · How quickly do you know whether it was right? · Is success objectively observable? ·
**Do you run RCA when it goes wrong?** · Can ARIA's contribution be isolated from other actors?

A less glamorous, high-volume workflow with measurable outcomes is strategically worth more than
an impressive executive-research agent whose correctness is unknowable.

**Moat maturity is not measured in months.** It is
`label density × task repetition × task diversity × outcome observability × attribution quality`.
A customer processing 500 repeatable reviews a day with clean downstream outcomes accumulates
faster than one running 15 strategic assignments a month.

**Buyers:** VP Engineering, CIO/CTO, COO, Procurement, Risk, Transformation.
**Pricing:** managed recurring commitments and verified operational volume — never tokens,
prompts, or named-headcount replacement.

---

## 11. Build Program and Gates

**Gate A — Proof works.** Does the proof system improve detection of fabrication, contradiction,
material omission, unsafe execution, and inappropriate non-abstention, versus a competent
agent-plus-audit-log baseline? *If no, stop.*

**Gate B — Proof reduces human work.** Can a manager validate a proof packet materially faster than
redoing the task, without loss of decision correctness? If review effort rises permanently, the
thesis is broken.

**Gate C — Learning compounds.** On unseen work, does learned routing outperform declared routing
on outcome quality, severe-failure rate, cost, latency, and abstention calibration? *If not, the
accumulator is not a moat however elegant the ledger.*

Gate C arrives later and is gated on label supply; **label-economics metrics are its leading
indicator.** Until Gate A and B report, no platform expansion.

Sequencing: benchmark (Gates A/B) → real execution + persistent employee → earned authority →
second department → attribution + label pipeline → Gate C → controlled evolution.

---

## 12. Deliberately Not Building Now

Generic drag-and-drop agent builder · feature-for-feature copies of any agent platform · a
marketplace before one role produces repeatable paid outcomes · voice/telephony/campaigns as the
wedge · blanket autonomy or a universal T5 switch · uncontrolled internet learning or source-less
memory · silent self-modification or automatic skill activation · live writes before identity,
authorization, leases, idempotency, receipts, compensation, revocation and independent audit are
complete · proprietary-data traps or non-exportable customer records · claims of consciousness,
personhood, or complete human replacement.

---

## 13. Current Repository Truth

**Provides:** tenant identity, membership, authorization, private-staging packaging · governed goal
intake, planning, bounded specialists, supervision, correction · approved scoped memory and
work-memory structures · typed Work Ledger events with durable audit outboxes · model-routing and
runtime-adapter contracts · evidence, approval, action, receipt and evaluation structures · an
integrated deterministic virtual-employee proof · a Codex↔Claude build-review coordinator (one P1
open) · local/private modes with explicit safety boundaries.

**Does not yet prove the thesis:** `EmployeeRun` is run-scoped, not a durable employment identity ·
specialists are generated per goal, not retained as employees · the authenticated employee API is
restricted to `offline_mock` · the main dashboard still contains mock data · material evidence
validation is not yet strong enough for the benchmark · **no attribution layer exists** · **zero
verified labels exist** · live execution is not generally enabled · the universal contracts and
cross-department role-pack test do not exist.

> **ARIA demonstrates a governed virtual-employee execution foundation. The AVEO thesis begins when
> persistent employees own recurring real commitments, reduce verification effort with
> proof-carrying work, and convert attributable outcomes into trusted labels.**

---

## 14. Falsifiers and Stop Conditions

The strategy is wrong or needs material revision if: proof adds paperwork without reducing
verification effort · the benchmark permits any critical false-safe · a normal agent plus an audit
log matches ARIA on integrity and decision correctness · **attribution precision is too low to
produce trustworthy labels** · **natural label yield is too sparse to feed the accumulator** ·
**learned policy does not outperform declared policy on unseen work** · employee history does not
alter supervision or authority eligibility · managers keep buying isolated automations rather than
recurring commitments · the second department requires rewriting the kernel · customers will not pay
after the shadow pilot · live action safety cannot reach complete authority/receipt correlation ·
legal/IP review does not support independent commercialization.

If Gate A or B misses, **pause platform expansion and fix evidence quality.** Do not compensate with
more agents, models, connectors, or UI breadth.

---

## 15. Success Definition

ARIA earns the category only when all hold: a stable employee owns recurring commitments for
months · managers spend materially less time verifying · material claims carry source- and
validator-backed proof · unsupported work abstains or escalates · authority is capability-specific,
leased, revocable and runtime-enforced · actions produce correlated receipts and observed outcomes ·
**outcomes are attributable at usable precision** · **verified labels measurably improve subsequent
routing, abstention and authority decisions** · the same kernel supports two departments through
role packs · customers pay for recurring commitments · customers retain ownership and export rights.

---

## 16. Locked Concepts

| Rule | Statement |
|---|---|
| **Doctrine** | Assign outcomes. Bound authority. Prove the work. Learn from what actually happened. |
| **Moat** | Verified Operational Learning |
| **Authority** | Policy defines the ceiling. Evidence determines how close ARIA operates to it. |
| **Verification** | Active verification teaches. Random verification measures. |
| **Attribution** | Unattributable outcomes do not become learning labels. |
| **Learning** | Label integrity beats label volume. |
| **Temporal** | Future information can label a past decision; it cannot retroactively become information that decision had. |
| **Omission** | A silently omitted critical check is a safety failure, not a gap. |
| **Factory** | The Employee Factory is the distribution layer for the moat, not the moat. |

---

## 17. Immediate Next Experiment

Unchanged and still blocking: freeze Work Proof Packet v0 and the benchmark spec · secure a
custodian and second labeller · select a corpus of ≥10 distinct releases with observable outcomes ·
label ≥150 atomic claims · measure against an agent-plus-audit-log baseline on the four
work-integrity classes and verification effort.

Everything in this document beyond §13 is hypothesis until Gates A and B report.

---

## References

1. [Microsoft Entra Agent ID](https://learn.microsoft.com/en-us/entra/agent-id/what-is-microsoft-entra-agent-id) · [Agent ID governance](https://learn.microsoft.com/en-us/entra/id-governance/agent-id-governance-overview) · [Agent 365](https://www.microsoft.com/en-us/microsoft-agent-365)
2. [Workday Agent System of Record](https://www.workday.com/en-gb/artificial-intelligence/agent-system-of-record.html)
3. [ServiceNow AI Control Tower](https://www.servicenow.com/products/ai-control-tower.html)
4. [Asana operating system for human-agent teams](https://investors.asana.com/news-releases/news-release-details/asana-unveils-operating-system-human-agent-teams)
