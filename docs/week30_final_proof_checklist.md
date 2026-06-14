# Week 30 — Final Proof Checklist

The single page a reviewer (or auditor) reads to confirm what is real. Every row is verifiable
from this repo. No claim here exceeds the Truth & Claim Audit.

**Status:** Awaiting Codex Launch-Readiness Audit.

---

## 1. Accepted weeks (independently reviewed)

| Week | Scope | Status | Anchor commits |
|---|---|---|---|
| 27 | Evolution Intelligence + RAPTOR (governed self-evolution loop) | Accepted | `3812387`, `8a6e7af` |
| 28 | Governed Self-Improvement & Update Manager | Accepted | `143d30e`, `136e8c0`, `ddcb192` |
| 29 | Work Ledger v2 → ROI → Dataset Export → Model Registry v1 → Fine-Tune Prototype | Accepted | `9691c79`, `9590750`, `6d279b1` |
| 30 | Launch Readiness (this package) | **Awaiting Codex audit** | `253e3a7` (+ this docs batch, pending commit) |

## 2. Test + build proof

| Check | Result |
|---|---|
| Backend pytest | `1021 passed, 1 skipped` |
| Run command | `cd apps/backend && uv run python -m pytest` |
| py-compile (Week 29 modules) | passed (per Week 29 acceptance) |
| `git diff --check` | clean (no whitespace/conflict errors) |

## 3. Demo commands (all offline, no API key, no network)

| Demo | Command | What it proves |
|---|---|---|
| **Golden path (primary)** | `uv run python -m aria.demo.golden_path` | request → skill → evidence gate → ledger → ROI, end-to-end |
| Model registry | `uv run python -m aria.model_registry.demo` | register → approve → activate → **rollback** |
| Fine-tuning prototype | `uv run python -m aria.fine_tuning.demo` | offline dry-run; **active model = NONE** |
| Ledger | `uv run python -m aria.ledger.demo` | typed events + metrics |
| Dataset export | `uv run python -m aria.training_data.demo` | SFT/DPO export from ledger |

All run from `apps/backend`. The golden path prints a deterministic ROI snapshot and ends with a
"no paid API call, no network call" boundary line.

## 4. Capability status (summary — full detail in Truth & Claim Audit)

- **Built (V1):** runtime, router, PR/KPI/CI-CD/Jira/QA skills, fail-closed evidence gate,
  Work Ledger v2 + ROI + dashboard, governance T1–T3 (+T4 gated), memory, RAG, code intel,
  CrewAI crew, Decision Intelligence (greedy), governed evolution pipeline, Model Registry v1,
  dataset export.
- **Prototype:** fine-tuning (offline dry-run; nothing trained/deployed; active model NONE).
- **Partial:** live per-event ledger emission (terminal events only today); Jira/Teams live
  writes (mocks); model router → fine-tuned model (not wired).
- **Roadmap (V2/V3):** vLLM serving, real fine-tuning/deploy, live connectors, §28.1 subagents,
  §26.8 canvas, §28.4 eight capabilities, multi-tenant AaS, autonomous self-modification.

## 5. What must NOT be claimed

- ❌ a trained or deployed fine-tuned model · ❌ vLLM serving live
- ❌ live Jira/Teams automation in production · ❌ fully autonomous operation
- ❌ "all 24 pillars operational" · ❌ "operational self-evolution" (it's a governed pipeline)
- ❌ ROI figures as production data (they are deterministic demo/seeded data)

## 6. Public-safety gate (before any publication)

- See [week30_public_safety_audit.md](week30_public_safety_audit.md). Key items: genericize
  `jira.amar-ujala.internal`; note intentional fake test secrets; **employer/IP approval
  required**. Do **not** publish until every box there is ✅.

## 7. Codex acceptance

- Week 30 is **not** complete by self-declaration. It is complete only when **Codex independently
  accepts** the launch-readiness package. Until then: **Awaiting Codex Launch-Readiness Audit.**

---

## Week 30 deliverables index (this package)

| # | Deliverable | File |
|---|---|---|
| 1 | Truth & Claim Audit | `week30_truth_and_claim_audit.md` |
| 2 | Golden End-to-End Demo | `week30_golden_demo.md` |
| 3 | Demo Reliability | `week30_demo_reliability.md` |
| 4 | Launch Assets | `week30_demo_script_3min.md`, `week30_internal_presentation.md`, `week30_architecture_diagram_notes.md`, `week30_screenshot_checklist.md`, `week30_public_safe_readme_notes.md` |
| 5 | Public-Safety Audit | `week30_public_safety_audit.md` |
| 6 | Product Positioning | `week30_product_positioning.md` |
| 7 | Career / Product Artifacts | `week30_resume_bullets.md`, `week30_linkedin_draft.md`, `week30_executive_summary.md`, `week30_ai_employee_as_a_service_blueprint.md` |
| 8 | Architecture Summary | `week30_architecture_summary.md` |
| 9 | Final Proof Checklist | `week30_final_proof_checklist.md` (this file) |
| 10 | V1/V2/V3 Boundary | `week30_v1_v2_v3_boundary.md` |

Plus the demo harness: `apps/backend/aria/demo/golden_path.py` (+ `__init__.py`).
