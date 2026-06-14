# Week 30 — Public-Release Safety Audit

Scan of the repository for anything that must not be published without review. This audit
reflects **actual scan results** (run 2026-06-14 against the tracked tree), not assertions.

**Status:** Awaiting Codex Launch-Readiness Audit.
**Headline:** No live secrets found in tracked files. Two awareness items below require a
decision before any **public** push. **Do not publish publicly until employer/IP approval is
confirmed** (company context is pervasive — see item C).

---

## A. Secrets / API keys / tokens — **PASS (with scanner caveat)**

- **`.env` is gitignored** (`.env`, `.env.local`, `*.env`). Only **template** files are tracked:
  `.env.example`, `apps/backend/.env.example`. No real keys tracked.
- **No live credential** matched in tracked source (`sk-ant-…`, `sk-…`, `AKIA…`, `ghp_…`).
- **Caveat — test fixtures use fake credentials.** Files under `apps/backend/tests/`
  (`test_week29_ledger_v2.py`, `…_training_data.py`, `…_model_registry.py`,
  `…_fine_tuning.py`, `…_ledger_api.py`) contain **deliberately fake** secrets such as
  `AKIAIOSFODNN7EXAMPLE` (AWS's own documented example key) and `sk-ant-api03-ABCDEF…1234`.
  These exist to **prove the redaction/privacy layer works** and are not live.
  - **Risk:** automated scanners (GitHub secret scanning, truffleHog) may flag them on a
    public push and create noise.
  - **Action:** none required for safety; optionally add a scanner allowlist / note in the
    public README that these are intentional test fixtures.

## B. Internal URLs / hostnames — **1 item to genericize**

- `https://jira.amar-ujala.internal/browse/AU-ENG-MOCK` appears in:
  - [apps/backend/aria/nodes/skill_nodes.py](../apps/backend/aria/nodes/skill_nodes.py) (`_mock_jira_create`)
  - [apps/backend/aria/integrations/teams_bot.py](../apps/backend/aria/integrations/teams_bot.py)
  - It is a **mock**, non-reachable URL, but it embeds the employer's internal naming.
  - **Action (for public release only):** replace with a neutral placeholder, e.g.
    `https://jira.example.internal/browse/ENG-MOCK`. Not required for an internal reveal.

## C. Company-sensitive context — **review gate before public push**

- "Amar Ujala", media-tech KPI examples (CTR, recommendation/notification services), and the
  competitive framing vs "Yukti" appear throughout `CLAUDE.md` and `docs/`.
- These are appropriate for an **internal** reveal but constitute employer context.
- **Action:** for any **public** GitHub/LinkedIn artifact, either (a) get explicit
  employer/IP approval, or (b) publish a **genericized** variant (see
  [week30_public_safe_readme_notes.md](week30_public_safe_readme_notes.md)). This audit does
  **not** authorize public publication.

## D. Real logs / runtime data / model artifacts — **PASS**

- Runtime ledgers are gitignored and **not tracked**: `work_ledger.jsonl`,
  `work_ledger_v2.jsonl`, `evolution_events.jsonl`, `update_releases.jsonl`,
  `tool_audit.jsonl`, `notifications.jsonl`, `ml/registry.jsonl`.
- `apps/backend/deployments/` (DEPLOYMENT_ROOT) is gitignored — regenerated, not source.
- **No model weights / checkpoints / training outputs** exist in the repo (no real training
  ran). The fine-tuning prototype is an offline dry-run that activates nothing.

## E. Confidential data in datasets/plans — **PASS**

- Dataset export and registry demos run on **temp-isolated** synthetic/seeded data.
- The ledger privacy layer **redacts** credential-shaped free text and **rejects**
  credential-shaped structural identifiers at the type boundary (verified by the fixtures in A).

---

## Pre-publication checklist (must all be ✅ before a PUBLIC push)

- [ ] Employer/IP approval obtained for publishing ARIA and naming Amar Ujala — **or** a
      genericized public variant is used.
- [ ] `jira.amar-ujala.internal` replaced with a neutral placeholder in the public variant.
- [ ] Decision recorded on the test-fixture fake secrets (allowlist or note).
- [ ] `git ls-files` re-checked for `.env`, `*.jsonl` runtime data, `deployments/` — none tracked.
- [ ] LinkedIn/README copy passes the Truth & Claim Audit (no overclaims).

Until every box is checked, the launch package status remains **internal-only**.
