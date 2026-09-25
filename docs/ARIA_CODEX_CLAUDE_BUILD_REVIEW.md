# ARIA Codex / Claude Build & Review

Status: local developer workflow. It does not change ARIA product authority, connector, deployment, or publication boundaries.

## Roles

- Human: defines the work order and acceptance criteria; authorizes waivers, patch application, commits, pushes, and deployment.
- Codex: the only product-code writer.
- Claude: independent reviewer of frozen revisions. Claude receives no product edit/write tools.
- Coordinator: creates isolated clones, freezes diffs, records state, invokes workers, and enforces handoffs. It does not author product code.

The workflow is:

```text
human work order
  -> isolated Codex implementation
  -> complete diff frozen and SHA-256 hashed
  -> fresh Claude review of that exact snapshot
  -> Codex remediation when P1/P2 findings remain
  -> fresh Claude re-audit with pre-fix and current snapshots
  -> human apply decision after acceptance
```

Claude does not review a changing builder directory. Codex and Claude are never active against the same mutable source tree.

## Start

Both subscription CLIs must already be authenticated:

```powershell
codex login status
claude auth status
```

No OpenAI or Anthropic API key is required. Provider and credential environment variables are removed from worker tool environments. The authenticated CLIs still contact their model providers to perform the requested build and review.

Run the local console:

```powershell
Set-Location apps/backend
uv run uvicorn aria.braintrust.app:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/build-review
```

## Work Order

A work order contains:

- title and objective;
- mandatory acceptance criteria;
- repository-relative allowed paths;
- requested repository-native validation commands;
- maximum review rounds.

The isolated builder starts from the committed `HEAD` captured when the session is created. Existing uncommitted and untracked files in the canonical repository are not copied into the builder clone.

Codex cannot expand beyond the allowed paths. A changed path outside the allowlist stops the session before Claude review.

## Runtime State

All protocol state is under the gitignored root:

```text
.aria_build_review/<session_id>/
  control.json
  work_order.json
  work_order.md
  events.jsonl
  snapshots/
  codex/
  claude/
  verification/
  workspaces/

.aria_build_review/.human/
  <session_id>.token
```

`control.json` is atomically replaced. `events.jsonl` is append-only. Every frozen patch is named by its SHA-256 digest. Founder capability tokens are stored outside each session tree under `.aria_build_review/.human/` so worker scratch paths do not share the same subtree as the token file.

The runtime root is separate from `.aria_data/collaboration/`, which belongs to ARIA's V3 product collaboration store.

## Review Rules

- P1: security, authority, governance, secret, external-action, data-integrity, core-correctness, mandatory-criterion, or security-regression-test defect.
- P2: meaningful noncritical correctness, reliability, failure-handling, contract, test, or regression-risk defect.
- P3: advisory improvement.

Open P1 and P2 findings block automatic acceptance. P3 findings do not. A human may explicitly waive an open P2 with a written justification; P1 cannot be waived by this workflow.

Finding IDs remain stable between rounds. An open prior blocker cannot disappear from a later report. Closing a P1 requires an independently recorded pre-fix reproduction and a passing current-snapshot check linked to the same finding ID.

Claude may run tests and adversarial probes in disposable verification space. Provider web tools are disabled. If the review changes the frozen source snapshot, the coordinator discards the verdict.

## Review Size

- Up to 800 handwritten changed lines and at most 25 files: full review.
- 801 to 2,000 handwritten changed lines and at most 25 files: partitioned review.
- More than 2,000 handwritten changed lines or more than 25 files: automatic review stops for human intervention.

A shallow or oversized review cannot accept a revision.

## Human Apply Boundary

Acceptance does not modify the canonical working tree. The UI enables `Apply accepted patch` only after an accepted Claude verdict or an explicit eligible P2 waiver.

Application requires an unguessable per-session capability and checks that:

- branch and `HEAD` still match the session baseline;
- tracked changes still match the initial baseline;
- untracked path metadata still matches the initial baseline;
- the accepted patch bytes still match their recorded SHA-256.

Applying a patch does not stage or commit it. There is no endpoint for commit, push, deployment, or publication.

## Failure and Restart Behavior

Round exhaustion never means acceptance. Remaining blockers produce `failed_review` and return authority to the human.

Worker timeout, invalid structured output, hash mismatch, reviewer mutation, source drift, or orchestration failure stops safely without persisting raw provider error text.

An interrupted active session reloads as `human_intervention_required`; workers are not silently resumed after a server restart.

## Visible Evidence

The UI displays work-order state, current actor, frozen diff hash, review depth, changed-file/line counts, explicit worker outputs, tests reported, and structured findings. It does not request or display hidden chain-of-thought.
