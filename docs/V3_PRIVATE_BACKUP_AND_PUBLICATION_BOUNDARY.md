# ARIA V3 — Private Backup & Publication Boundary

> **Binding boundary.** ARIA V3 is a **private internal pilot**. Nothing here is
> published, pushed, or deployed.

## Current repository state (local only)

- The repository is **local / private** on this machine.
- **No git remote is configured** — there is nothing to push to, and nothing has been
  pushed.
- `master` contains the accepted V3 program (merge `13a33ad`); the V3 endpoint `17021ef`
  is marked by the **local** annotated tag `aria-v3-goal-driven-workforce`.
- The tag is **local only** — it has not been pushed.

## Hard rules (do not break)

- ❌ **No public release** of any kind (GitHub public repo, LinkedIn, blog, demo video to
  external audiences).
- ❌ **No `git push`** — not the branch, not `master`, not the tag — until approval.
- ❌ **No external deployment**, hosting, or productionization.
- ❌ **No public-release material** (the demo/narrative docs are for *internal* private
  demos only).
- ✅ **Private demo is allowed** — running the offline V3 proof / API locally for an
  internal audience is fine; it touches no external system.

## Approval required before any publication

Publication — pushing to any shared/public remote, or sharing externally — requires
**explicit employer / IP approval first**, because ARIA was built in the context of
employment at Amar Ujala and the IP/ownership position must be cleared before anything
leaves a private machine.

Until that approval is granted and recorded:

- treat the whole repo as **confidential internal IP**;
- keep backups **private** (e.g. a local/offline copy or a *private* remote that has been
  approved — not a public one);
- a public GitHub push must **not** happen.

## If/when approval is granted (future, not now)

Only after written employer/IP approval:

1. configure the approved remote (`git remote add origin <approved-private-or-public-url>`);
2. push `master` and then the tag;
3. apply any required public-safety scrub (secrets, internal references) per a separate
   public-safety audit.

None of these steps are authorized yet.

## Safe-for-private-demo confirmation

ARIA V3 is **safe for private internal demo**: it is offline, deterministic, performs no
external writes, makes no network calls, requires no credentials, and leaves the repo
unchanged after a demo run. Its safety for demo does **not** imply safety for
publication — those are separate decisions, and publication remains blocked.

*Cross-references: [`V3_BOUNDARIES_AND_NON_GOALS.md`](V3_BOUNDARIES_AND_NON_GOALS.md),
[`V3_FINAL_ACCEPTANCE_CHECKLIST.md`](V3_FINAL_ACCEPTANCE_CHECKLIST.md),
[`V3_DEMO_SCRIPT_5_MIN.md`](V3_DEMO_SCRIPT_5_MIN.md).*
