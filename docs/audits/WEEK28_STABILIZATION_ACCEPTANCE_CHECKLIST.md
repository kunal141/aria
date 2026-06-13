# Week 28 Stabilization Acceptance Checklist

This checklist is derived from `CODEX_FULL_241_QUESTION_AUDIT.md`. It is an
acceptance contract for stabilization work only. It does not authorize new
Week 29 features.

## Verification Baseline

Run commands from the repository root:

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py
uv run --group dev python -m pytest -q
uv run python -m compileall -q apps/backend/aria
npm --prefix apps/frontend test -- --run src/ARIAVoice.test.jsx
npm --prefix apps/frontend run build
```

Required result:

- `test_week28_stabilization.py`: at least 38 tests pass, with no skips or
  expected failures.
- Full backend suite: exit code `0`, no failures or collection errors, and at
  least 726 tests pass.
- Python compilation: exit code `0`.
- Voice component tests: exactly 2 tests pass.
- Frontend production build: exit code `0`.

## 1. Duplicate Release Scan Prevention

**Pass condition**

- Rescanning an identical proposal/content hash is idempotent.
- The existing release keeps its ID, version, lifecycle state, approval
  metadata, and deployment metadata.
- No second release is created for the same proposal and content hash.
- A materially changed proposal creates a new immutable semantic version and
  preserves the previous release.

**Fail condition**

- A rescan overwrites an active, canary, rejected, rolled-back, or approved
  release.
- A duplicate release ID/version is created.
- A changed proposal mutates an existing release in place.

**Required tests**

```text
test_duplicate_scan_is_idempotent_for_active_release
test_changed_proposal_creates_new_semver_without_overwrite
```

**Command**

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py -k "duplicate_scan or changed_proposal"
```

**Expected result:** `2 passed`; stored release count and original release
fields remain unchanged after the duplicate scan.

**Proof files/functions**

- `apps/backend/aria/evolution/pipeline.py::ProposalPipeline.run`
- `apps/backend/aria/evolution/monitor.py::_stable_id`
- `apps/backend/aria/evolution/update_manager/store.py`
- `apps/backend/aria/evolution/update_manager/models.py::UpdateRelease`

**Codex re-audit:** Yes. Re-run both tests and inspect store/version allocation
for overwrite paths.

## 2. Teams Pending-Update Approval IDs

**Pass condition**

- Every pending-update Approve/Reject action contains the exact non-empty
  `update_id` of the displayed release.
- Selecting one release changes only that release.
- Unknown, missing, stale, or already-resolved IDs return a clear no-op/error.
- The handler does not substitute a task ID, proposal ID, or generic governance
  approval ID.

**Fail condition**

- Cards omit `update_id`, use list position, approve all pending releases, or
  report success without a matching state transition.

**Required tests**

```text
test_pending_update_card_actions_include_exact_update_id
test_pending_update_approval_updates_only_selected_release
```

**Command**

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py -k "pending_update"
```

**Expected result:** `2 passed`; the selected release transitions and all
unselected releases remain byte-for-byte equivalent in the store.

**Proof files/functions**

- `apps/backend/aria/nodes/evolution_node.py::_handle_list_pending`
- `apps/backend/aria/integrations/teams_bot.py::_build_evolution_approval_card`
- `apps/backend/aria/integrations/teams_bot.py::_handle_card_action`
- `apps/backend/aria/integrations/teams_bot.py::_execute_evolution_after_approval`

**Codex re-audit:** Yes. Inspect rendered card payloads and execute the handler
against at least two pending releases.

## 3. Governed Canary Promotion

**Pass condition**

- Promotion is rejected before valid T4 approval.
- The approver cannot be the proposal author.
- Approval is bound to the exact release hash/version and is rejected if stale.
- Canary activation runs constitutional and health checks.
- Only a healthy approved canary may transition to active.
- A failed check leaves the previously active release and artifact unchanged.

**Fail condition**

- Direct method calls, Teams actions, or graph requests bypass approval or
  health checks.
- A failed canary is reported as active.

**Required tests**

```text
test_unapproved_promotion_is_blocked
test_approved_canary_health_pass_promotes_active
```

**Command**

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py -k "unapproved_promotion or approved_canary"
```

**Expected result:** `2 passed`; unauthorized promotion raises the documented
governance exception, while the approved healthy release follows the defined
canary-to-active transitions.

**Proof files/functions**

- `apps/backend/aria/evolution/update_manager/operations.py::approve_update`
- `apps/backend/aria/evolution/update_manager/operations.py::activate_canary`
- `apps/backend/aria/evolution/update_manager/operations.py::promote_canary`
- `apps/backend/aria/evolution/update_manager/health.py::run_health_checks`
- `apps/backend/aria/evolution/update_manager/constitutional.py`

**Codex re-audit:** Yes. Test both public operations and the Teams-triggered
path.

## 4. Graph Uses Promoted Version

**Pass condition**

- A production graph invocation reads the promoted component through the same
  loader used at runtime.
- Before promotion, the graph exhibits/reports the old version.
- After valid promotion, a new graph invocation exhibits/reports the exact new
  version and content hash.
- Restarting the process preserves the promoted selection.

**Fail condition**

- Only the update store says the release is active while the graph continues
  using static source code, old configuration, or a test-only loader.

**Required test**

```text
test_graph_uses_promoted_component_version
```

**Command**

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py -k "graph_uses_promoted"
```

**Expected result:** `1 passed`; assertions prove old-before/new-after behavior
through `aria_graph.invoke()`, including the promoted version/hash.

**Proof files/functions**

- `apps/backend/aria/graph.py::aria_graph`
- `apps/backend/aria/update_manager/operations.py::promote_canary`
- The production component loader called by the graph
- The graph node that consumes the promoted component

**Codex re-audit:** Yes. A store-only or mocked-consumer assertion does not
pass this item.

## 5. Rollback Restores Old Version

**Pass condition**

- Rollback restores the previous artifact bytes and verified SHA-256 hash.
- The previous release becomes the selected active version.
- The failed/new release becomes rolled back and cannot remain active.
- A subsequent graph invocation uses the restored old version.
- Rollback is idempotent or returns a clear no-op when already complete.

**Fail condition**

- Only lifecycle metadata changes while disk content or graph behavior remains
  on the new version.

**Required test**

```text
test_rollback_restores_artifact_and_graph_version
```

**Command**

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py -k "rollback_restores"
```

**Expected result:** `1 passed`; old bytes, hash, selected release, and graph
behavior are all restored.

**Proof files/functions**

- `apps/backend/aria/evolution/update_manager/operations.py::rollback_update`
- `apps/backend/aria/evolution/update_manager/operations.py::_write_artifact_atomic`
- `apps/backend/aria/evolution/update_manager/store.py`
- The production component loader used by `aria_graph`

**Codex re-audit:** Yes. Inspect both filesystem restoration and runtime use.

## 6. Path Confinement

**Pass condition**

- All deployment and rollback targets resolve beneath one configured
  deployment root.
- Validation uses resolved paths and a structural containment check such as
  `Path.relative_to()`.
- Absolute outside-root paths, `..` traversal, mixed Windows separators, and
  link/junction escapes are rejected before any read, write, or directory
  creation.
- A valid in-root path still deploys successfully.

**Fail condition**

- Validation relies on string prefixes, filename suffixes, or normalization
  without containment verification.

**Required tests**

```text
test_allowed_deployment_path_succeeds
test_absolute_outside_deployment_root_rejected
test_parent_traversal_rejected
```

**Command**

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py -k "deployment_path or outside_deployment_root or traversal"
```

**Expected result:** `5 passed` (3 original path-confinement tests plus the
2 Round-10 update_id traversal-rejection tests); rejected cases create or
modify no file outside the temporary deployment root.

**Proof files/functions**

- `apps/backend/aria/evolution/update_manager/operations.py::_write_artifact_atomic`
- The deployment-root configuration and path-validation function
- `apps/backend/aria/evolution/update_manager/models.py`

**Codex re-audit:** Yes. Codex should add an independent Windows traversal
probe in addition to the automated tests.

## 7. Persistence Fail-Closed Behavior

**Pass condition**

- Store flush/write failure raises a typed error to the caller.
- Approval, promotion, and rollback do not report success.
- In-memory and on-disk state remain at the last durable lifecycle state.
- Active artifacts are not changed, or are restored before the operation
  returns failure.
- Teams receives a failure/retry message rather than a success message.

**Fail condition**

- An exception is swallowed, memory advances ahead of disk, or the user is
  told that an undurable operation succeeded.

**Required tests**

```text
test_persistence_failure_blocks_approval_without_state_change
test_persistence_failure_blocks_promotion_without_state_change
test_persistence_failure_blocks_rollback_without_state_change
```

**Command**

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py -k "persistence_failure"
```

**Expected result:** `4 passed`; each injected persistence failure leaves the
last durable record and artifact unchanged and returns/raises failure.

**Proof files/functions**

- `apps/backend/aria/evolution/update_manager/store.py::_flush`
- `apps/backend/aria/evolution/update_manager/store.py::save`
- `apps/backend/aria/evolution/update_manager/operations.py`
- `apps/backend/aria/integrations/teams_bot.py::_execute_evolution_after_approval`

**Codex re-audit:** Yes. Inject failures before and after temporary-file writes.

## 8. Voice Transcript Fix

**Pass condition**

- The API request uses the finalized transcript from the current recognition
  event.
- Two consecutive utterances submit their own transcripts exactly once each.
- The second request cannot reuse the first transcript.
- Empty, stale React state is not submitted because of asynchronous state
  updates.

**Fail condition**

- The first request is blank, a later request sends the previous utterance, or
  one recognition result causes duplicate submissions.

**Required frontend tests**

```text
submits the current finalized transcript
submits consecutive transcripts without stale state
```

**Command**

```powershell
npm --prefix apps/frontend test -- --run src/ARIAVoice.test.jsx
```

**Expected result:** `2 passed`; mocked fetch payloads contain the exact first
and second recognized transcripts in order.

**Proof files/functions**

- `apps/frontend/src/ARIAVoice.jsx::startListening`
- Speech recognition `onresult`/`onend` handlers
- `apps/frontend/src/ARIAVoice.test.jsx`

**Codex re-audit:** Yes. Run component tests and one browser smoke test against
the local voice API.

## 9. Typed Work Ledger Lifecycle Events

**Pass condition**

- Evolution lifecycle events are validated typed records, not free-form
  dictionaries.
- The successful path emits ordered events for proposal, generation, sandbox,
  approval request, approval, canary, verification, promotion, and activation.
- Failure/rejection/rollback paths emit their corresponding typed terminal
  event.
- Every event carries stable correlation fields: `task_id`, `proposal_id`,
  `update_id`, component, version, timestamp, actor where applicable, and
  outcome.
- Invalid event types or missing required fields are rejected.

**Fail condition**

- Lifecycle transitions occur without ledger events, event names are arbitrary
  strings, or events cannot be correlated to one release.

**Required tests**

```text
test_evolution_lifecycle_emits_ordered_typed_ledger_events
test_failed_lifecycle_operation_emits_failed_event
```

**Command**

```powershell
uv run --group dev python -m pytest -q apps/backend/tests/test_week28_stabilization.py -k "typed_ledger or failed_lifecycle"
```

**Expected result:** `2 passed`; all emitted records validate against the ledger
model and appear in the required order with matching correlation IDs.

**Proof files/functions**

- `apps/backend/aria/work_ledger.py`
- `apps/backend/aria/evolution/pipeline.py::ProposalPipeline.run`
- `apps/backend/aria/update_manager/operations.py`
- `apps/backend/aria/nodes/evolution_node.py`
- `apps/backend/aria/integrations/teams_bot.py`

**Codex re-audit:** Yes. Compare emitted events with actual store transitions,
including one failed promotion and one rollback.

## 10. Documentation Corrected to Verified State

**Pass condition**

- Current-state documentation says Week 28 is stabilized only after Items 1-9
  pass.
- It records the exact verified backend test count, frontend test/build result,
  verification date, and commands used.
- `CLAUDE.md`, root `BUILD_LOG.md`, and `apps/backend/BUILD_LOG.md` do not
  contradict each other.
- Historical entries remain historical; they are not rewritten as current
  claims.
- Documentation does not claim operational self-evolution unless graph use,
  promotion, persistence, and rollback acceptance tests pass.

**Fail condition**

- Counts are copied without running tests, stale "next week" rows remain in the
  current-status section, or documentation claims capabilities not proven by
  this checklist.

**Commands**

```powershell
Select-String -Path CLAUDE.md -Pattern "Weeks 3.25 complete|350 deterministic|Next: Week 26"
Get-Content CLAUDE.md -Tail 100
Get-Content BUILD_LOG.md -Tail 100
Get-Content apps/backend/BUILD_LOG.md -Tail 120
git diff --check
```

**Expected result**

- The stale-current-state search returns no matches.
- The current status and latest build-log entries contain the same verified
  test count and Week 28 stabilization result.
- `git diff --check` exits `0`.

**Proof files**

- `CLAUDE.md`
- `BUILD_LOG.md`
- `apps/backend/BUILD_LOG.md`
- `docs/audits/CODEX_FULL_241_QUESTION_AUDIT.md`
- This checklist

**Codex re-audit:** Yes. Documentation is accepted only after Codex independently
runs the commands and compares the claims with their output.

## Final Acceptance Rule

Week 28 stabilization is accepted only when all ten items pass, the five
baseline commands succeed, no acceptance test is skipped or marked expected
failure, and Codex completes the specified re-audit. A partial pass must be
reported as partial stabilization; it must not be described as Week 28
complete.
