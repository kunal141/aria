# ARIA V2 — Manager Summary

*One page. Plain language. No hype.*

---

## The headline

**V1 proved governed local AI work execution. V2 proves a practical internal AI
employee pilot: ARIA can converse, remember approved domain knowledge, run
read-only investigations, create artifacts, and draft actions without production
writes.**

---

## What V2 adds over V1 / V1.1

| | V1 / V1.1 | V2 |
|---|---|---|
| Interaction | Single-task runs, one-shot terminal | Multi-turn conversation with memory across turns and **across restarts** |
| Knowledge | No durable domain memory | ARIA learns approved facts (e.g. what a data field's values mean) and cites them later |
| Work products | Skill outputs | Persistent per-task **workspace**: reports, evidence, citations, and draft actions in one place |
| Investigations | — | Three read-only pilots: analytics, CI/CD, and PR review |
| Governance surface | Action tiers, evidence gate | All of V1 **plus** an explicit approval inbox and a full audit trail of every step |

Nothing in V1's governance was loosened. V2 is V1's discipline applied to a richer,
conversational, memory-backed workflow.

---

## Approved memory (the key idea)

ARIA does not invent domain knowledge. You **teach** it a fact in plain English; ARIA
**proposes** it; you **approve** it; only then is it stored. After that, ARIA recalls
it on demand and always **cites which memory and version** it used. You can supersede
or roll back any fact. Sensitive content (passwords, keys, anything confidential) is
**refused** — V2 has no identity layer to hold secrets safely, by design.

---

## The three pilots — and their value

1. **Analytics pilot** — investigates an events table. Memory explains what the
   values mean; the actual counts are backed by real evidence, never guessed. Output:
   a report plus a draft Jira ticket for any data-quality issue found.
2. **CI/CD pilot** — diagnoses a failing pipeline and prepares a Teams update. Output:
   a diagnosis plus a **Teams message preview** — not sent.
3. **PR review pilot** — reviews a pull request for the recommendation engine. Output:
   review comments plus draft Jira follow-ups — **not posted.**

Every pilot is **read-only** and **draft-only**: ARIA does the investigation and
prepares the action, a human decides whether to send it.

---

## What it does *not* do (so there are no surprises)

- It does **not** write to any production system — no Jira ticket created, no Teams
  message sent, no PR comment posted, no pipeline rerun, no database change.
- It does **not** call any external/cloud service by default — the pilot runs fully
  offline on local fixtures.
- It is **not** deployed, **not** multi-tenant, and uses **no** fine-tuned or
  self-hosted model.
- It is **not** public — no GitHub or LinkedIn publication until employer/IP review
  is complete.

---

## Why this matters

This is the difference between a demo and an employee. ARIA already behaves like a
careful junior teammate: it asks before it remembers, shows its evidence, keeps a
clean record of everything it did, and never takes an irreversible action on its own.
That is exactly the foundation you want before granting any system the ability to act.

---

## See it in one command

```
cd apps/backend
uv run python -m aria.demo.v2_full_pilot
```

Watch ARIA learn a fact, get your approval, restart, recall it with a citation, run
all three pilots, assemble a workspace, and print a clean record — with an explicit
note that nothing left the machine.

---

## Next step

Pick one real, low-risk internal workflow (e.g. a recurring analytics check or PR
review) and run V2 alongside it for a short period — **read-only and draft-only** — to
measure how much triage and drafting it removes from the team, before any decision
about granting write access (a separate, governed V3 step).
