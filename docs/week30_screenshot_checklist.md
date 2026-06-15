# Week 30 — Screenshot Checklist

Screenshots to capture for the deck, README, and LinkedIn (pending publication approval).
Each entry says **what to capture**, **how to produce it**, and **the honesty caption** to
use so an image never implies more than is true.

**Status:** Week 30 Launch Readiness ACCEPTED by Codex (2026-06-15). Week 30 complete.
Save images to `docs/demos/` as `week_30_<name>.png`.

---

| # | Screenshot | How to produce | Honest caption |
|---|---|---|---|
| 1 | **Golden path — full run** | `uv run python -m aria.demo.golden_path` (terminal) | "End-to-end loop, offline. No paid API call." |
| 2 | **Evidence gate withholding** | Same run, Stage 1 (KPI/CI-CD `[RESPONSE WITHHELD]`) | "Fail-closed governance: ARIA refuses unsupported claims." |
| 3 | **Proactive CI/CD notification** | Same run, the Teams card printed on the CI/CD input | "Proactive alert is a governed skill output (mock channel)." |
| 4 | **ROI snapshot (Work Ledger)** | Same run, Stage 3 metrics | "ROI computed from the Work Ledger — deterministic demo data." |
| 5 | **ROI Dashboard (frontend)** | Run the frontend against `/api/v1/ledger/metrics` (see reliability doc) | "Dashboard reads real ledger metrics; figures are demo data, not production." |
| 6 | **Governance / approval** | `uv run python -m aria.model_registry.demo` (approve step) | "Human approval gate — nothing activates without sign-off." |
| 7 | **Evolution / canary / rollback** | `aria.model_registry.demo` rollback step (or golden Stage 2 rollback) | "Governed rollback path always retained." |
| 8 | **Model Lifecycle Registry** | `aria.model_registry.demo` registry listing | "Registry v1: version, dataset hash, rollback pointer." |
| 9 | **Fine-Tuning Prototype dry-run** | `uv run python -m aria.fine_tuning.demo` (shows `active model: NONE`) | "Offline dry-run only — no model trained or deployed." |
| 10 | **Test suite green** | `uv run python -m pytest -q` (last line) | "1027 passed, 1 skipped." |
| 11 | **Teams/voice surface** (optional) | `ARIAVoice.jsx` UI / Teams card render | "Identity surface exists; live deployment needs credentials (V2)." |

---

## Caption rules (apply to every image)
- If the screenshot shows demo/seeded data, the caption **must** say so.
- Never caption the fine-tuning image as a trained or deployed model.
- Never caption the Jira/Teams images as live writes — they are mocks.
- Prefer captions that name the **harness layer** being shown (governance, memory, evolution…).

## Before using any screenshot publicly
- Crop out absolute file paths that contain the user's name where avoidable.
- Confirm no `.env`, key, or internal hostname is visible in the frame.
- Clear the item against [week30_public_safety_audit.md](week30_public_safety_audit.md).
