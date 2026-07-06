# V4.2 — Model Router + Sovereignty Mock Layer (Plan)

**Status:** `V4.2 plan doc awaiting review` — documentation only. No V4.2 code exists yet.
**Depends on:** V4.1 External Runtime Adapter Foundation (commit `ed66ec3`, focused suite 44 passed).
**Proves:** *ARIA can choose a model route by policy without depending on one provider, using deterministic mock providers only.*

V4.2 is **not** real model integration. Every route is a **decision**, never an execution.

---

## 1. The key finding (why this reshapes the plan)

V4.1 already ships — committed and accepted — a substantial model-routing surface in
[`apps/backend/aria/runtime_adapters/model_router.py`](../apps/backend/aria/runtime_adapters/model_router.py):

- All 8 `ModelCategory` values (`frontier_cloud_model`, `open_cloud_model`, `local_open_model`,
  `coding_model`, `reasoning_model`, `embedding_model`, `reranker_model`, `fallback_model`)
- `TrustBoundary` (`any_cloud` / `private_only` / `local_only`)
- Contract models: `ModelProvider`, `ModelCapabilityProfile`, `ModelCostLatencyProfile`,
  `ModelRiskProfile`, `FallbackPolicy`, `SovereigntyPolicy`, `RouteDecision`
- `DEFAULT_MOCK_PROVIDERS` (8 declared mock providers) + `DEFAULT_FALLBACK_POLICIES`
- An intent→category map (`_INTENT_CATEGORY`) covering the routing examples
- A deterministic, offline **`MockModelRouter`** that already:
  - picks a category from intent,
  - downgrades a cloud category to local when sovereignty forbids egress,
  - walks the fallback chain when a provider is unavailable,
  - and returns a `RouteDecision` with **`executed=False` always**.

**Consequence:** V4.2 is *not* "build a router." The in-memory decision function already exists.
Two of its inputs — the **capability, cost/latency, and risk profiles** — are **defined but never
consumed**, and the whole thing is **in-memory, unpersisted, unaudited**.

---

## 2. What V4.2 adds beyond V4.1

| V4.2 adds | Why V4.1 could not do it |
|---|---|
| **Governed persistence** — a path-confined SQLite registry + decision store with a transactional audit outbox → Work Ledger | V4.1's router keeps nothing: no registry to query, no persisted decisions, no ledger events |
| **Profile-aware routing** — actually consume cost/latency/risk profiles | V4.1 picks *"first enabled provider in category"*; the 3 profiles are dead models |
| **Auditable, source-linked decisions** — each route → a persisted `RouteDecision` + ledger event + `correlation_id` + optional eval record | V4.1 returns a value and forgets it |
| **Integration** — soft-link a decision to a V4.1 runtime-adapter request; feed chosen `model_id` into the eval hook | V4.1 router is standalone; nothing connects a route to an adapter run or an eval |

Everything V4.2 adds is **additive**. No accepted V4.1 logic is modified (see §14).

---

## 3. Approved decisions (#1–#6)

1. **New package** (created at implementation time, not now): `apps/backend/aria/model_routing/`.
2. **Reuse** the V4.1 contracts from `apps/backend/aria/runtime_adapters/model_router.py` — **import/re-export, never duplicate** them.
3. **Soft-link** compatibility with V4.1 runtime adapters via `correlation_id` / `adapter_request_id`. **Do not migrate or modify accepted V4.1 adapter storage.**
4. **Selection objective:** *cheapest eligible provider within category*, with **risk, sovereignty, outage, and export restriction as hard exclusions**.
5. **Model-routing ledger events** (added at implementation time), names similar to:
   `model_provider_registered`, `model_provider_status_changed`, `model_route_requested`,
   `model_route_decided`, `model_route_blocked`, `model_route_fallback_applied`.
6. **API wiring:** add a standalone `build_v4_routing_app()`; include the router into the unified
   `/api/v4` app **only if** implementation stays lightweight and safe.

---

## 4. Proposed file list

**New package `apps/backend/aria/model_routing/` (8 files):**

| File | Purpose |
|---|---|
| `__init__.py` | Package doc + exports; re-exports V4.1 contracts from `runtime_adapters.model_router` |
| `models.py` | V4.2-only persisted models: `RouteRequest`, `PersistedRouteDecision`; enums `RouteStatus` (requested/decided/blocked), `ProviderStatus` (declared/enabled/disabled/outage/export_restricted); `ROUTING_BOUNDARY` note |
| `selection.py` | `GovernedModelRouter` — profile-aware, deterministic, `executed=False` always |
| `policy.py` | `RoutingPolicyGate` — deny-by-default: sovereignty + export-control + attribution checks; returns `RoutingPolicyDecision` |
| `store.py` | `ModelRoutingStore` — path-confined SQLite, audit outbox, secret guards, **hardened `record_route_decision`** |
| `audit.py` | `build_route_event` — maps new ledger event types → event classes |
| `service.py` | `ModelRoutingService` — register defaults, `route(...)`, persist, emit ledger, emit eval, adapter soft-link, reads |

**New test file:** `apps/backend/tests/test_v4_2_model_routing.py`
**New API module:** `apps/backend/aria/api/v4_routing.py` (own `v4_routing_router` + `build_v4_routing_app()`)

**Additive edits to existing files (no refactor of accepted logic):**

| File | Edit (additive only) |
|---|---|
| `aria/memory_v2/paths.py` | +1 function `model_routing_db_path()` (mirrors `runtime_adapters_db_path`) |
| `aria/ledger/events.py` | +~6 enum values, +~6 frozen event classes, extend `LedgerEvent` union |
| `aria/ledger/__init__.py` | export the new event classes |
| `aria/api/v4.py` | **1-line** `include_router(v4_routing_router)` in `build_v4_app` (only if kept lightweight; decision #6) |
| `aria/api/__init__.py` | export `build_v4_routing_app`, `v4_routing_router` |

**Untouched V4.1 files:** `model_router.py`, `runtime_adapters/{store,service,interface,policy,models,receipts,audit}.py` — zero changes.

---

## 5. Proposed models / classes

**Reused from V4.1 (import, do not redefine):** `ModelCategory`, `TrustBoundary`, `ModelProvider`,
`ModelCapabilityProfile`, `ModelCostLatencyProfile`, `ModelRiskProfile`, `FallbackPolicy`,
`SovereigntyPolicy`, `RouteDecision`.

**New (V4.2):**
- `RouteRequest` (frozen): `request_id`, `intent`, `task_type`, `sovereignty_name`,
  `adapter_request_id | None`, `source_refs`, `evidence_refs`, `status: RouteStatus`, `created_at`.
- `PersistedRouteDecision` (frozen): wraps a `RouteDecision` + `decision_id`, `route_request_id`,
  `correlation_id`, `chosen_provider_id`, `cost_estimate`, `risk_summary`, `providers_considered`,
  `fallback_used: bool`, `sovereignty_applied: bool`, `created_at`.
- Enums: `RouteStatus`, `ProviderStatus`.
- Classes: `GovernedModelRouter`, `RoutingPolicyGate`, `RoutingPolicyDecision`,
  `ModelRoutingStore`, `ModelRoutingService`.
- Store exceptions (mirror V4.1): `ProviderNotFound`, `ProviderAlreadyExists`,
  `RoutingSecurityError`, `RoutingIntegrityError`.

---

## 6. Routing policy design

`GovernedModelRouter.route(intent, task_type, sovereignty, providers, profiles)` is deterministic:

1. `intent → category` via the reused V4.1 `_INTENT_CATEGORY` map. The routing examples resolve as:
   - hard reasoning / high-risk planning → `reasoning_model` / `frontier_cloud_model`
   - repetitive coding / summarization → `coding_model` / `open_cloud_model` (cheaper)
   - private / offline / fallback → `local_open_model`
   - embedding / retrieval → `embedding_model`; rerank → `reranker_model`
2. **Sovereignty** (reused logic): if egress forbidden and category is cloud → downgrade to
   `local_open_model` (or block if none available).
3. **Profile-aware selection (NEW)** — among *enabled* providers in the category:
   - **hard-exclude** any provider whose `ModelRiskProfile.data_egress_risk == "high"` when
     sovereignty forbids egress;
   - **hard-exclude** providers flagged `ProviderStatus.export_restricted` under a matching sovereignty;
   - **hard-exclude** providers flagged `ProviderStatus.outage`/`disabled`;
   - **rank** survivors by cost (`cost_per_1k_input + cost_per_1k_output`), tie-break by
     `typical_latency_ms`, then `provider_id` (stable, deterministic);
   - choose the top; record `providers_considered` + a human-readable `note`.
4. If none survive → walk the `FallbackPolicy` chain (reused), re-applying the same exclusions.
5. Return `RouteDecision(executed=False, allowed=..., blocked_reasons=..., note=...)`.

Default selection objective = **cheapest-eligible-in-category**, with risk / sovereignty / outage /
export restriction as **hard constraints** (decision #4).

---

## 7. Fallback policy design

- Reuse `DEFAULT_FALLBACK_POLICIES` (e.g. frontier → open_cloud → local_open → fallback).
- **Provider outage** = `ProviderStatus.outage` (or `enabled=False`) → excluded, triggers the chain;
  the persisted decision sets `fallback_used=True` and emits `model_route_fallback_applied`.
- **Export-control** = `ProviderStatus.export_restricted` + a `SovereigntyPolicy.reason` carrying an
  export marker → provider excluded under matching sovereignty; recorded in `blocked_reasons`/`note`.
- Terminal case: chain exhausted → `allowed=False`, `chosen_model_id=None`, `model_route_blocked`
  event. **No execution, ever.**

---

## 8. Sovereignty policy design

- Reuse `TrustBoundary` (`any_cloud` / `private_only` / `local_only`) and `SovereigntyPolicy`
  (`forbid_data_egress`, `reason`).
- Persist named policies in the store; a `RouteRequest` references one by `sovereignty_name`.
- Enforced in **both** the router (cloud→local downgrade) and the `RoutingPolicyGate` (hard block if a
  cloud model is somehow chosen under `local_only`) — defense in depth, mirroring V4.1's
  policy/adapter double-check.

---

## 9. Mock provider behavior

- Providers are **declared metadata only** (`status="declared"`, `vendor="mock"`,
  `model_id="mock-*-x"`) — never a live SDK client, never a credential, never I/O.
- `register_default_providers/profiles/policies` seeds the 8 `DEFAULT_MOCK_PROVIDERS` plus mock
  cost/latency/risk profiles. To exercise exclusions deterministically, the seed intentionally
  includes at least one provider with `data_egress_risk="high"` and one marked `export_restricted`.
- The router reads provider metadata and returns a decision. No provider object performs any call.

---

## 10. V4.2 → V4.1 runtime-adapter compatibility

- **Soft link, no V4.1 schema migration.** A `RouteRequest` may carry `adapter_request_id`; the
  `PersistedRouteDecision.correlation_id` is set to that adapter request's id, so both appear under one
  correlation trail in the Work Ledger.
- The chosen `model_id` flows into the **existing** V4.1 eval hook —
  `EvaluationHook.evaluate_receipt(receipt, request, model_id=...)` already accepts `model_id`. No
  change to the `adapter_request` / `adapter_receipt` tables.
- Result: "runtime adapter X (mock worker) would run on model route Y" is fully auditable **without
  touching accepted V4.1 storage**.

---

## 11. Evaluation hook connection

- Reuse V4.1 `EvaluationHook.build_record(...)` (source-linked; `model_id` supported).
- On each decided route, `ModelRoutingService` optionally emits a source-linked eval record:
  `input_ref=route_request:<id>`, `output_ref=route_decision:<id>`, `model_id=<chosen>`,
  `pass_fail = pass if allowed else fail`, `cost_estimate` from the cost profile, `latency_ms=0`
  (declared, not measured). Persisted via an `eval_record` table in the routing store with the same
  source-linked guard as V4.1.
- Honest scope: this records *the routing decision's* eval, not a model-output eval — **no model runs**.

---

## 12. Safety boundaries

- **Deterministic + offline only.** No real provider, no SDK import, no network, no API key, no
  `.env`, no credential, no subprocess, no cloud, no deploy.
- **`executed` is structurally `False`** in every `RouteDecision`; store `record_route_decision`
  **rejects** any decision with `executed=True`.
- **Store authority hardened from day one** (applying the V4.1 P1 lesson): `record_route_decision`
  self-resolves the `RouteRequest`, rejects unknown/mismatched request ids, rejects any
  `chosen_provider_id` not in the registry, and rejects a chosen model from a
  disabled/outage/export-restricted provider. Caller-supplied provider metadata is never trusted.
- **Path confinement:** `${ARIA_DATA_DIR}/model_routing/store.sqlite`, `ensure_confined`, lazy schema,
  no import-time DB creation, restart-safe, never inside the importable `aria` package.
- **Secret discipline:** `sanitize_text` masking on free text/payloads; structural-secret guards
  reject credential-shaped ids/refs.
- **`ARIA_USER_ID`** = attribution only, never authorization.
- **Package isolation:** importing `aria.model_routing` must not load V1 LLM skills, and vice-versa
  (verified by a subprocess-scan test).

---

## 13. Test plan — `tests/test_v4_2_model_routing.py`

- **TestRegistry** — register/list providers; duplicate `provider_id` rejected; structural-secret rejected.
- **TestProfilesPolicies** — register + retrieve capability/cost/risk profiles + fallback + sovereignty policies.
- **TestGovernedRouter** — each routing example maps correctly; **cost-aware** pick (cheapest eligible in category); **risk-aware** exclusion of high-egress under sovereignty.
- **TestSovereignty** — `private_only` / `local_only` / `forbid_data_egress` downgrade cloud→local; block when no local exists.
- **TestFallback** — outage → chain; `export_restricted` excluded; exhausted chain → `allowed=False`, blocked event.
- **TestExecutedNever** — every decision `executed is False`; no path sets it True; persisted decision `executed False`.
- **TestStoreAuthority** (P1-style) — reject `executed=True`, unknown route_request, mismatched `route_request_id`, provider-not-in-registry, disabled/outage provider as chosen; path-confined; no secret in SQLite; outbox → ledger.
- **TestLedger** — new event types present; `make_envelope` round-trips; legacy-reader compatibility preserved.
- **TestEvalHook** — decided route → source-linked eval record with `model_id` populated.
- **TestAdapterCompat** — route `correlation_id` links to a runtime-adapter request; V4.1 tables unchanged.
- **TestSafety** — package scan: no network/SDK/subprocess/`os.getenv`(secret)/`.env` imports; package isolation.
- **TestApi** — register/list/route endpoints; **no** execute/live/credential endpoint; safe typed errors.

Target: ~40–48 focused tests. Success gate = focused suite green **and** full backend regression
unchanged (baseline **1615 passed, 1 skipped** → expect ~`1615 + N` passed, 1 skipped).

---

## 14. Risks and stop conditions

**V4.1 refactor needed? — No.** Only additive touches: `paths.py` (+1 fn), `ledger` (additive
enum/classes/exports), and an optional 1-line `v4.py` include. No accepted V4.1 logic is modified.

**Risks:**
- *Scope creep toward "real" routing* → locked to mock/decision-only; no real cost metering, no
  latency measurement, no provider I/O.
- *Re-introducing a V4.1-style store bypass* → mitigated by hardening `record_route_decision` and
  writing the P1-style authority tests first.
- *Dependency-direction inversion* (routing imports contracts from adapters) → accepted and
  documented; a contracts-move is a **future** consolidation, explicitly out of V4.2 scope.

**Stop conditions (at implementation time, only after approval):** stop and report if a step appears
to require any API key / secret / `.env` / network / provider SDK / real model / subprocess / cloud /
deployment; or if a change would force a **migration of accepted V4.1 storage**; or if a design
choice above becomes ambiguous. Never commit, push, deploy, or touch the two unrelated presentation
files without an explicit instruction.

---

## 15. Explicit non-goals

V4.2 **must not** implement any of the following:

```
real OpenAI calls
real Anthropic calls
real Claude Managed Agents
real OpenAI Agents SDK
real MCP
real local model serving
real vLLM
real HuggingFace model loading
provider SDKs
network calls
API keys
.env dependency
credentials
cloud execution
deployment
public release
```

**Only deterministic local/mock routing is allowed.** Every route is a decision; no model is ever run.
