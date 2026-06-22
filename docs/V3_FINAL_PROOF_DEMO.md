# ARIA V3 — Final Proof Demo

> **Status: deterministic, offline proof.** No network, no external write, no
> deployment. Runs inside a throwaway `ARIA_DATA_DIR` and leaves the repo unchanged.

## What it proves

One business goal travels the **entire V3 stack**, end to end, offline:

```text
business goal
 → problem statement / roadmap / task board        (V3.1 / V3.2)
 → dynamic specialist agents (dry-run)              (V3.3)
 → supervised + governed                            (V3.4)
 → skill gap proposed (proposal-only, not activated)(V3.5)
 → work-memory lesson + fixture-only world updates  (V3.6)
 → team update draft (draft-only, never sent)       (V3.7)
 → daily routine run + summary                      (V3.8)
 → action intent previewed + dry-run/mock,
   external target BLOCKED by the deny-by-default gate (V3.9)
 → manager dashboard + estimated ROI                (V3.10)
```

## How to run

```bash
cd apps/backend
uv run python -m aria.demo.v3_proof
```

or via the API (local pilot):

```text
POST /api/v3/demo/v3-proof
```

or programmatically:

```python
from aria.demo.v3_proof import run_v3_proof
proof = run_v3_proof()      # returns a dict: title, summary, steps[], snapshot, source_refs, boundary
```

## Guarantees (tested)

- **Deterministic** — the same milestone sequence and summary every run.
- **Offline** — no network, no live connector, no external write, no real credentials.
- **No pollution** — runs in an isolated temp `ARIA_DATA_DIR`; the environment is
  restored and the temp dir removed on exit; the source package is never written to.
- **Governed** — the action step shows an internal dry-run succeeding while an external
  target is **blocked** by the deny-by-default policy; nothing is sent.
- **Audited** — every step writes typed Work-Ledger events (in the isolated ledger).
- **ROI is estimated** — the dashboard's ROI is clearly marked estimated with a visible
  calculation method.

## Output shape

`run_v3_proof()` returns:

- `title`, `summary`, `boundary` — human-readable framing;
- `steps` — one entry per V3 milestone (`milestone`, `detail`);
- `snapshot` — the V3.10 manager dashboard snapshot (goal/agent/memory/collaboration/
  routine/action summaries + approval queue + risks + estimated ROI);
- `source_refs` — provenance ids from the run.

The dashboard service persists a **proof record** (summary + source refs) and emits
`v3_proof_demo_generated` + `v3_acceptance_package_created` to the Work Ledger — no
external action occurs.

*Cross-references: [`V3_FINAL_ACCEPTANCE_CHECKLIST.md`](V3_FINAL_ACCEPTANCE_CHECKLIST.md),
[`V3_BOUNDARIES_AND_NON_GOALS.md`](V3_BOUNDARIES_AND_NON_GOALS.md).*
