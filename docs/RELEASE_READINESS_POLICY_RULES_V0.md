# Release Readiness Policy Rules — v0 (reference set)

**Version:** 0 · **Status:** draft for development trial (§18 of the benchmark spec). Not frozen.

**What this is.** The versioned Tier-B rule set the benchmark depends on. Tier-B claims are
*deterministic policy conclusions* — booleans derived from labelled Tier-A facts by an
explicit written rule. Without this file, Tier B is unscoreable and the §9 ground-truth
disposition cannot be computed.

**What this is not.** Not an opinion about how software *should* be released. This is a
**reference set to be replaced by each organization's actual policy.** Rules marked
`org-specific` almost certainly differ per customer; the benchmark uses whatever the customer
declares, not this file.

**Companion:** [Work Proof Benchmark Spec](ARIA_WORK_PROOF_BENCHMARK_SPEC.md)

---

## 1. Rule schema

Every rule is expressed in this shape. Ambiguity here becomes an unscoreable claim later.

```yaml
rule_id:            RR-###
version:            0
title:              short name
statement:          the policy in prose, as a manager would state it
tier_a_inputs:      [ facts this rule consumes ]
evaluation:         deterministic predicate over those facts
materiality:        critical | major | minor
abstain_when:       conditions under which no verdict may be given
freshness_window:   max age of supporting evidence at decision time
authoritative_source: the system of record that may settle this
org_specific:       true | false
```

**Verdict vocabulary** (identical to the manifest): `supported` · `unsatisfied` ·
`abstained` · `omitted`.

**Universal abstention condition.** Every rule inherits this in addition to its own
`abstain_when`: abstain if any required Tier-A input is **absent, stale beyond
`freshness_window`, conflicting across authoritative sources, unauthorized for the current
data scope, or itself labelled indeterminate.** A rule may never be evaluated on assumed
facts.

---

## 2. Reference rules

### RR-001 — Change approval
```yaml
rule_id: RR-001
title: Change approval threshold met
statement: >
  Every code change in the release carries at least two distinct approvals, at least one
  from a CODEOWNER of each modified path. Self-approval does not count. Approvals retracted
  before the merge commit do not count.
tier_a_inputs: [pr_ids, approval_records{approver, timestamp, state}, codeowners_map, author_id, merge_commit_sha]
evaluation: >
  For each PR: |{a in approvals : a.state == APPROVED and a.approver != author and not retracted}| >= 2
  AND at least one such approver is a CODEOWNER for every modified path.
materiality: critical
abstain_when: CODEOWNERS file unavailable; approval history incomplete; approver identity unresolvable
freshness_window: approvals must postdate the final content commit
authoritative_source: source control platform
org_specific: true   # threshold and CODEOWNER requirement vary
```

### RR-002 — Required checks passed
```yaml
rule_id: RR-002
title: All required CI checks passed on the release commit
statement: >
  Every check marked required for the target branch reports success on the exact commit
  being released. Skipped, cancelled, neutral, or stale-commit results are not success.
tier_a_inputs: [merge_commit_sha, required_check_names, check_runs{name, commit_sha, conclusion, completed_at}]
evaluation: >
  For every name in required_check_names, there exists a check_run with that name,
  commit_sha == merge_commit_sha, and conclusion == success.
materiality: critical
abstain_when: required-check list unavailable; check run references a different commit; logs truncated or corrupt
freshness_window: 24h
authoritative_source: CI system
org_specific: true   # the required-check list is per-repo
```

### RR-003 — Rollback plan present and reversible
```yaml
rule_id: RR-003
title: Documented rollback path
statement: >
  The release record links a rollback plan naming the target version and the procedure. If
  the release contains an irreversible migration, the plan states the forward-fix procedure
  instead and is explicitly acknowledged as irreversible.
tier_a_inputs: [release_record, linked_rollback_doc, migration_manifest{reversible: bool}]
evaluation: >
  rollback_doc exists AND names a target version AND (no irreversible migration
  OR forward-fix procedure documented and acknowledged).
materiality: critical
abstain_when: linked document unreachable; migration reversibility undeclared
freshness_window: must reference the current release version
authoritative_source: release tracker
org_specific: false
```

### RR-004 — Change record exists and is linked
```yaml
rule_id: RR-004
title: Traceable change record
statement: >
  A release ticket exists, is in an approved state, and links to the exact changeset being
  deployed.
tier_a_inputs: [release_ticket{id, state}, linked_commit_range, merge_commit_sha]
evaluation: ticket exists AND state in APPROVED_STATES AND merge_commit_sha within linked_commit_range
materiality: major
abstain_when: ticket state vocabulary unmapped; commit range malformed
freshness_window: 72h
authoritative_source: issue tracker
org_specific: true   # approved-state vocabulary varies
```

### RR-005 — No blocking incident open
```yaml
rule_id: RR-005
title: No open blocking incident on affected services
statement: >
  No Sev-1 or Sev-2 incident is open against any service touched by this release.
tier_a_inputs: [affected_services, open_incidents{severity, affected_service, state}]
evaluation: not exists incident where severity in {SEV1, SEV2} and affected_service in affected_services and state == OPEN
materiality: critical
abstain_when: affected-service mapping unavailable; incident feed unreachable or stale beyond window
freshness_window: 1h
authoritative_source: incident management system
org_specific: true   # severity scale varies
```

### RR-006 — No known-critical vulnerable dependency introduced
```yaml
rule_id: RR-006
title: Dependency vulnerability gate
statement: >
  The release introduces no dependency version carrying a known CRITICAL advisory without a
  recorded, unexpired exception approved by the security owner.
tier_a_inputs: [dependency_diff, advisory_records{package, version_range, severity}, exceptions{id, expiry, approver}]
evaluation: >
  For every added/upgraded dependency: no matching CRITICAL advisory,
  OR an unexpired exception approved by a security owner exists.
materiality: critical
abstain_when: advisory database older than freshness_window; dependency diff incomplete; exception approver unresolvable
freshness_window: 24h for the advisory database
authoritative_source: dependency scanner + security exception register
org_specific: false
```

### RR-007 — Evidence freshness
```yaml
rule_id: RR-007
title: All supporting evidence fresh at decision time
statement: >
  Every artifact used to satisfy RR-001..RR-006 was observed within its own freshness window
  measured from the go/no-go decision timestamp.
tier_a_inputs: [decision_timestamp, evidence_snapshots{rule_id, observed_at, content_hash}]
evaluation: for each cited snapshot, decision_timestamp - observed_at <= freshness_window(rule_id)
materiality: critical
abstain_when: snapshot lacks an observation timestamp or content hash
freshness_window: per referenced rule
authoritative_source: ARIA evidence snapshots
org_specific: false
```

### RR-008 — Deployment window
```yaml
rule_id: RR-008
title: Within approved deployment window
statement: The deployment is scheduled inside an approved window, or carries an approved exception.
tier_a_inputs: [scheduled_deploy_time, approved_windows, window_exception{approver, expiry}]
evaluation: scheduled_deploy_time within approved_windows OR valid unexpired exception
materiality: major
abstain_when: window calendar unavailable; timezone of the window undeclared
freshness_window: 24h
authoritative_source: change calendar
org_specific: true   # many orgs have no window at all — then this rule is omitted, not auto-passed
```

---

## 3. Disposition function (§9 ground truth)

Applying the rule set to labelled Tier-A facts yields a deterministic disposition. This is
**policy conformance**, not a prediction about production outcomes.

```text
if any rule with materiality=critical evaluates UNSATISFIED   -> not-ready
elif any rule with materiality=critical must ABSTAIN          -> insufficient-evidence
elif any rule with materiality=major evaluates UNSATISFIED    -> not-ready
elif any rule with materiality=major must ABSTAIN             -> insufficient-evidence
else                                                          -> ready
```

**Ordering matters and is deliberate.** A known-failed critical rule outranks a
cannot-determine, because "we know it's broken" and "we cannot tell" are different manager
actions. `insufficient-evidence` is never silently treated as `ready`.

Computed by the **custodian** from labels alone, independently of either arm (spec §9, §13.1).

---

## 4. Rules deliberately excluded from v0

These are real release concerns that are **not** Tier A/B and must not be smuggled in:

| Excluded | Why | Where it belongs |
|---|---|---|
| "Change is low-risk" | Subjective weighting | Tier C advisory |
| "Adequate test coverage" | Threshold is a judgment; coverage % is a proxy, not a fact about safety | Tier C, or an org-specific Tier-B rule with a declared numeric threshold |
| "Customer impact unlikely" | Requires counterfactual | Tier C advisory |
| "Team has capacity to support" | Not machine-observable | Out of scope |
| "Code quality acceptable" | Subjective | Out of scope |

**If the development trial (spec §18) shows most real go/no-go checks land here rather than
in §2, the benchmark's scoreable surface is too thin and the design must change before
freeze.** That is precisely what the trial is for.

---

## 5. Open items before freeze

1. Replace this reference set with a **real organization's declared policy** (or confirm a
   public-repo proxy policy for the development corpus).
2. Resolve every `org_specific: true` rule against that organization.
3. Confirm the approved-state vocabularies (RR-004), severity scale (RR-005), and
   required-check lists (RR-002) — these are the most common sources of ambiguity.
4. Trial on 2–3 development releases and record which rules proved unscoreable in practice.
5. Version-lock and hash alongside the benchmark spec (spec §16).
