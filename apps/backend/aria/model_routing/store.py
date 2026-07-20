"""
SQLite model-routing store (V4.2).

Persists the model provider registry, capability/cost/risk profiles, fallback + sovereignty
policies, route requests, route decisions, and (source-linked) evaluation records. Same
discipline as the V2/V3/V4.1 stores: confined to
``${ARIA_DATA_DIR}/model_routing/store.sqlite`` (gitignored, never inside the importable
``aria`` source package), no import-time DB creation, lazy schema, restart-safe, and every
state change emits a Work Ledger event through a transactional **audit outbox**.

DECISION-ONLY / MOCK-LOCAL: nothing here calls a model, provider, network, SDK, or
credential. The store is the **second authority boundary** — it independently re-verifies
every persisted route decision (see :meth:`record_route_decision`) and rejects forged /
unsafe ones, so a caller can never persist an execution claim, a cloud route under a
no-egress policy, a decision for an unknown/mismatched request, or a chosen provider that is
unregistered / disabled / in outage / export-restricted.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

from aria.goals.sanitize import sanitize_text
from aria.ledger import ActorType, LedgerEventType
from aria.memory_v2.paths import ensure_confined, model_routing_db_path
from aria.model_routing.audit import build_route_event
from aria.model_routing.models import (
    ELIGIBLE_PROVIDER_STATUSES,
    PersistedRouteDecision,
    ProviderStatus,
    RouteRequest,
    RouteStatus,
)
from aria.model_routing.policy import RoutingPolicyGate
from aria.model_routing.selection import GovernedModelRouter
from aria.runtime_adapters.harness import EvalOutcome, EvaluationRecord
from aria.runtime_adapters.model_router import (
    _CLOUD_CATEGORIES,
    FallbackPolicy,
    ModelCapabilityProfile,
    ModelCategory,
    ModelCostLatencyProfile,
    ModelProvider,
    ModelRiskProfile,
    SovereigntyPolicy,
    TrustBoundary,
)

# Provenance/source refs that would imply a real external endpoint are rejected outright —
# V4.2 routing is decision-only and must never carry a live location.
_UNSAFE_REF_SCHEMES = ("http://", "https://", "github://", "slack://", "jira://", "mcp://")
_RISK_LEVELS = frozenset({"low", "medium", "high"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_provider (
    provider_id   TEXT PRIMARY KEY,
    vendor        TEXT NOT NULL DEFAULT 'mock',
    model_id      TEXT NOT NULL,
    category      TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'declared',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_category ON model_provider(category);
CREATE TABLE IF NOT EXISTS model_capability_profile (
    model_id       TEXT PRIMARY KEY,
    categories     TEXT NOT NULL DEFAULT '[]',
    context_window INTEGER NOT NULL DEFAULT 8192,
    modalities     TEXT NOT NULL DEFAULT '[]',
    strengths      TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS model_cost_profile (
    model_id           TEXT PRIMARY KEY,
    cost_per_1k_input  REAL NOT NULL DEFAULT 0,
    cost_per_1k_output REAL NOT NULL DEFAULT 0,
    typical_latency_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS model_risk_profile (
    model_id         TEXT PRIMARY KEY,
    data_egress_risk TEXT NOT NULL DEFAULT 'low',
    privacy_risk     TEXT NOT NULL DEFAULT 'low',
    output_risk      TEXT NOT NULL DEFAULT 'low',
    notes            TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS fallback_policy (
    category         TEXT PRIMARY KEY,
    ordered_fallback TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS sovereignty_policy (
    name               TEXT PRIMARY KEY,
    boundary           TEXT NOT NULL DEFAULT 'any_cloud',
    forbid_data_egress INTEGER NOT NULL DEFAULT 0,
    reason             TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS route_request (
    request_id         TEXT PRIMARY KEY,
    intent             TEXT NOT NULL,
    task_type          TEXT,
    sovereignty_name   TEXT NOT NULL DEFAULT 'default',
    adapter_request_id TEXT,
    source_refs        TEXT NOT NULL DEFAULT '[]',
    evidence_refs      TEXT NOT NULL DEFAULT '[]',
    status             TEXT NOT NULL DEFAULT 'requested',
    created_at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS route_decision (
    decision_id          TEXT PRIMARY KEY,
    route_request_id     TEXT NOT NULL,
    correlation_id       TEXT NOT NULL,
    adapter_request_id   TEXT,
    intent               TEXT NOT NULL,
    task_type            TEXT,
    chosen_category      TEXT NOT NULL,
    chosen_model_id      TEXT,
    chosen_provider_id   TEXT,
    providers_considered TEXT NOT NULL DEFAULT '[]',
    fallback_chain       TEXT NOT NULL DEFAULT '[]',
    sovereignty_boundary TEXT NOT NULL DEFAULT 'any_cloud',
    sovereignty_applied  INTEGER NOT NULL DEFAULT 0,
    fallback_used        INTEGER NOT NULL DEFAULT 0,
    cost_estimate        REAL,
    risk_summary         TEXT NOT NULL DEFAULT '',
    allowed              INTEGER NOT NULL DEFAULT 1,
    blocked_reasons      TEXT NOT NULL DEFAULT '[]',
    note                 TEXT NOT NULL DEFAULT '',
    executed             INTEGER NOT NULL DEFAULT 0,
    source_refs          TEXT NOT NULL DEFAULT '[]',
    evidence_refs        TEXT NOT NULL DEFAULT '[]',
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decision_request ON route_decision(route_request_id);
CREATE INDEX IF NOT EXISTS idx_decision_adapter ON route_decision(adapter_request_id);
CREATE TABLE IF NOT EXISTS eval_record (
    eval_id           TEXT PRIMARY KEY,
    goal_id           TEXT,
    task_id           TEXT,
    adapter_id        TEXT,
    model_id          TEXT,
    prompt_version    TEXT NOT NULL DEFAULT 'v0',
    skill_version     TEXT NOT NULL DEFAULT 'v0',
    input_ref         TEXT NOT NULL,
    output_ref        TEXT NOT NULL,
    expected_behavior TEXT NOT NULL DEFAULT '',
    actual_behavior   TEXT NOT NULL DEFAULT '',
    score             REAL NOT NULL DEFAULT 0,
    pass_fail         TEXT NOT NULL DEFAULT 'not_evaluated',
    failure_reason    TEXT NOT NULL DEFAULT '',
    human_label       TEXT NOT NULL DEFAULT '',
    cost_estimate     REAL,
    latency_ms        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_outbox (
    outbox_id   TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    event_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    flushed_at  TEXT
);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _jlist(items: list) -> str:
    return json.dumps([x.value if hasattr(x, "value") else str(x) for x in items])


def _has_secret(value: str) -> bool:
    return bool(value) and sanitize_text(value) != value


def _is_unsafe_ref(value: str) -> bool:
    v = (value or "").strip().lower()
    return any(v.startswith(scheme) for scheme in _UNSAFE_REF_SCHEMES)


def _sanitize_value(v: Any) -> Any:
    if isinstance(v, str):
        return sanitize_text(v) or ""
    if isinstance(v, dict):
        return {k: _sanitize_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_sanitize_value(x) for x in v]
    return v


class ProviderNotFound(ValueError):
    """A provider / request / decision id did not resolve."""


class ProviderAlreadyExists(ValueError):
    """A duplicate provider id was registered."""


class RoutingSecurityError(ValueError):
    """A governance/secret breach: a credential-shaped or unsafe value, a chosen provider
    that is disabled / in outage / export-restricted, or a cloud route under a no-egress
    sovereignty policy."""


class RoutingIntegrityError(ValueError):
    """A structural-consistency breach: an execution claim, an unknown/mismatched route
    request, a category/model mismatch, a chosen provider not in the registry, or a decision
    with no source references."""


def _guard_ids(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None and _has_secret(str(value)):
            raise RoutingSecurityError(
                f"structural identifier {name!r} carries a credential-shaped value")


def _guard_refs(**fields: list[str] | None) -> None:
    for name, values in fields.items():
        for v in values or []:
            if _has_secret(str(v)):
                raise RoutingSecurityError(
                    f"reference list {name!r} carries a credential-shaped value")
            if _is_unsafe_ref(str(v)):
                raise RoutingSecurityError(
                    f"reference list {name!r} carries an unsafe external ref {str(v)!r} "
                    "(http/https/github/slack/jira/mcp are not permitted in decision-only routing)")


class ModelRoutingStore:
    def __init__(self, db_path: Path | str | None = None, *, writer: Any = None,
                 execution_mode: str | None = None) -> None:
        resolved = Path(db_path) if db_path is not None else model_routing_db_path()
        self._db_path = ensure_confined(resolved)
        self._writer = writer
        self._execution_mode = execution_mode
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── Transactional audit outbox ───────────────────────────────────────────

    def _enqueue(self, conn: sqlite3.Connection, event_type: LedgerEventType, **fields) -> None:
        fields.setdefault("runtime_mode", self._execution_mode)
        event = build_route_event(event_type, **fields)
        conn.execute(
            "INSERT INTO audit_outbox (outbox_id, event_type, event_json, created_at, flushed_at) "
            "VALUES (?,?,?,?,NULL)",
            (f"obx-{uuid.uuid4().hex}", event_type.value, event.model_dump_json(), _iso(_now())),
        )

    def _resolve_writer(self, writer: Any = None):
        if writer is not None:
            return writer
        if self._writer is not None:
            return self._writer
        from aria.ledger.writer import get_default_writer

        return get_default_writer()

    def flush_outbox(self, writer: Any = None) -> int:
        conn = self._connect()
        target = self._resolve_writer(writer)
        rows = conn.execute(
            "SELECT outbox_id, event_json FROM audit_outbox WHERE flushed_at IS NULL ORDER BY rowid"
        ).fetchall()
        flushed = 0
        for row in rows:
            try:
                target.append(json.loads(row["event_json"]))
            except Exception:
                break
            with conn:
                conn.execute("UPDATE audit_outbox SET flushed_at=? WHERE outbox_id=?",
                             (_iso(_now()), row["outbox_id"]))
            flushed += 1
        return flushed

    def pending_audit_count(self) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS c FROM audit_outbox WHERE flushed_at IS NULL").fetchone()
        return int(row["c"])

    # ── Providers ─────────────────────────────────────────────────────────────

    def register_provider(self, p: ModelProvider, *, status: ProviderStatus | None = None,
                          actor: str = "aria") -> ModelProvider:
        if self.get_provider(p.provider_id) is not None:
            raise ProviderAlreadyExists(f"provider {p.provider_id!r} already registered")
        _guard_ids(provider_id=p.provider_id, model_id=p.model_id, vendor=p.vendor)
        st = status or (ProviderStatus(p.status) if p.status in
                        {s.value for s in ProviderStatus} else ProviderStatus.declared)
        enabled = p.enabled and st in ELIGIBLE_PROVIDER_STATUSES
        now = _now()
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO model_provider (provider_id, vendor, model_id, category, enabled, "
                "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (p.provider_id, sanitize_text(p.vendor), p.model_id, p.category.value,
                 1 if enabled else 0, st.value, _iso(now), _iso(now)),
            )
            self._enqueue(conn, LedgerEventType.model_provider_registered, task_id=p.provider_id,
                          actor=actor, actor_type=ActorType.aria, provider_id=p.provider_id,
                          model_id=p.model_id, category=p.category.value, correlation_id=p.provider_id,
                          status=st.value, outcome="registered")
        self.flush_outbox()
        return self.get_provider(p.provider_id)  # type: ignore[return-value]

    def set_provider_status(self, provider_id: str, status: ProviderStatus, *,
                            actor: str = "aria") -> ModelProvider:
        p = self.get_provider(provider_id)
        if p is None:
            raise ProviderNotFound(f"provider {provider_id!r} not found")
        enabled = status in ELIGIBLE_PROVIDER_STATUSES
        conn = self._connect()
        with conn:
            conn.execute("UPDATE model_provider SET status=?, enabled=?, updated_at=? "
                         "WHERE provider_id=?",
                         (status.value, 1 if enabled else 0, _iso(_now()), provider_id))
            self._enqueue(conn, LedgerEventType.model_provider_status_changed, task_id=provider_id,
                          actor=actor, actor_type=ActorType.aria, provider_id=provider_id,
                          model_id=p.model_id, category=p.category.value, correlation_id=provider_id,
                          status=status.value, outcome="status_changed")
        self.flush_outbox()
        return self.get_provider(provider_id)  # type: ignore[return-value]

    def get_provider(self, provider_id: str) -> ModelProvider | None:
        row = self._connect().execute("SELECT * FROM model_provider WHERE provider_id=?",
                                      (provider_id,)).fetchone()
        return self._row_to_provider(row) if row else None

    def list_providers(self, *, category: str | None = None,
                       status: str | None = None) -> list[ModelProvider]:
        conn = self._connect()
        clauses, params = [], []
        if category is not None:
            clauses.append("category=?")
            params.append(category)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM model_provider{where} ORDER BY created_at, provider_id",
                            params).fetchall()
        return [self._row_to_provider(r) for r in rows]

    # ── Profiles + policies ────────────────────────────────────────────────────

    def register_capability_profile(self, c: ModelCapabilityProfile) -> ModelCapabilityProfile:
        _guard_ids(model_id=c.model_id)
        if c.context_window <= 0:
            raise RoutingIntegrityError("model context_window must be positive")
        for modality in c.modalities:
            _guard_ids(modality=modality)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO model_capability_profile (model_id, categories, "
                "context_window, modalities, strengths) VALUES (?,?,?,?,?)",
                (c.model_id, _jlist(c.categories), c.context_window, _jlist(c.modalities),
                 json.dumps([sanitize_text(s) or "" for s in c.strengths])),
            )
        return c

    def get_capability_profile(self, model_id: str) -> ModelCapabilityProfile | None:
        row = self._connect().execute(
            "SELECT * FROM model_capability_profile WHERE model_id=?", (model_id,)).fetchone()
        return self._row_to_capability(row) if row else None

    def register_cost_profile(self, c: ModelCostLatencyProfile) -> ModelCostLatencyProfile:
        _guard_ids(model_id=c.model_id)
        costs = (c.cost_per_1k_input, c.cost_per_1k_output)
        if any(not isfinite(value) or value < 0 for value in costs):
            raise RoutingIntegrityError("model cost values must be finite and non-negative")
        if c.typical_latency_ms < 0:
            raise RoutingIntegrityError("model latency must be non-negative")
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO model_cost_profile (model_id, cost_per_1k_input, "
                "cost_per_1k_output, typical_latency_ms) VALUES (?,?,?,?)",
                (c.model_id, c.cost_per_1k_input, c.cost_per_1k_output, c.typical_latency_ms),
            )
        return c

    def get_cost_profile(self, model_id: str) -> ModelCostLatencyProfile | None:
        row = self._connect().execute(
            "SELECT * FROM model_cost_profile WHERE model_id=?", (model_id,)).fetchone()
        return self._row_to_cost(row) if row else None

    def list_cost_profiles(self) -> dict[str, ModelCostLatencyProfile]:
        rows = self._connect().execute("SELECT * FROM model_cost_profile").fetchall()
        return {r["model_id"]: self._row_to_cost(r) for r in rows}

    def register_risk_profile(self, r: ModelRiskProfile) -> ModelRiskProfile:
        _guard_ids(model_id=r.model_id)
        levels = (r.data_egress_risk, r.privacy_risk, r.output_risk)
        if any(level not in _RISK_LEVELS for level in levels):
            raise RoutingIntegrityError(
                "model risk levels must be one of: low, medium, high")
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO model_risk_profile (model_id, data_egress_risk, "
                "privacy_risk, output_risk, notes) VALUES (?,?,?,?,?)",
                (r.model_id, r.data_egress_risk, r.privacy_risk, r.output_risk,
                 sanitize_text(r.notes)),
            )
        return r

    def get_risk_profile(self, model_id: str) -> ModelRiskProfile | None:
        row = self._connect().execute(
            "SELECT * FROM model_risk_profile WHERE model_id=?", (model_id,)).fetchone()
        return self._row_to_risk(row) if row else None

    def list_risk_profiles(self) -> dict[str, ModelRiskProfile]:
        rows = self._connect().execute("SELECT * FROM model_risk_profile").fetchall()
        return {r["model_id"]: self._row_to_risk(r) for r in rows}

    def register_fallback_policy(self, f: FallbackPolicy) -> FallbackPolicy:
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO fallback_policy (category, ordered_fallback) VALUES (?,?)",
                (f.category.value, _jlist(f.ordered_fallback)),
            )
        return f

    def get_fallback_policies(self) -> dict[ModelCategory, list[ModelCategory]]:
        rows = self._connect().execute("SELECT * FROM fallback_policy").fetchall()
        return {ModelCategory(r["category"]): [ModelCategory(c) for c in
                json.loads(r["ordered_fallback"])] for r in rows}

    def register_sovereignty_policy(self, s: SovereigntyPolicy) -> SovereigntyPolicy:
        _guard_ids(name=s.name)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO sovereignty_policy (name, boundary, forbid_data_egress, "
                "reason) VALUES (?,?,?,?)",
                (s.name, s.boundary.value, 1 if s.forbid_data_egress else 0, sanitize_text(s.reason)),
            )
        return s

    def get_sovereignty_policy(self, name: str) -> SovereigntyPolicy | None:
        row = self._connect().execute(
            "SELECT * FROM sovereignty_policy WHERE name=?", (name,)).fetchone()
        if row is None:
            return None
        return SovereigntyPolicy(name=row["name"], boundary=TrustBoundary(row["boundary"]),
                                 forbid_data_egress=bool(row["forbid_data_egress"]),
                                 reason=row["reason"])

    # ── Route requests ─────────────────────────────────────────────────────────

    def create_route_request(self, r: RouteRequest, *, actor: str = "aria") -> RouteRequest:
        _guard_ids(request_id=r.request_id, adapter_request_id=r.adapter_request_id,
                   sovereignty_name=r.sovereignty_name, task_type=r.task_type)
        _guard_refs(source_refs=r.source_refs, evidence_refs=r.evidence_refs)
        if r.status is not RouteStatus.requested:
            raise RoutingIntegrityError("a new route request must start in requested status")
        if (r.sovereignty_name != "default"
                and self.get_sovereignty_policy(r.sovereignty_name) is None):
            raise RoutingIntegrityError(
                f"route request cites unknown sovereignty policy {r.sovereignty_name!r}")
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO route_request (request_id, intent, task_type, sovereignty_name, "
                "adapter_request_id, source_refs, evidence_refs, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (r.request_id, sanitize_text(r.intent), r.task_type, r.sovereignty_name,
                 r.adapter_request_id, _jlist(r.source_refs), _jlist(r.evidence_refs),
                 r.status.value, _iso(r.created_at)),
            )
            self._enqueue(conn, LedgerEventType.model_route_requested, task_id=r.request_id,
                          actor=actor, actor_type=ActorType.aria, request_id=r.request_id,
                          adapter_request_id=r.adapter_request_id,
                          correlation_id=r.adapter_request_id or r.request_id,
                          status=r.status.value, outcome="route_requested")
        self.flush_outbox()
        return self.get_route_request(r.request_id)  # type: ignore[return-value]

    def get_route_request(self, request_id: str) -> RouteRequest | None:
        row = self._connect().execute("SELECT * FROM route_request WHERE request_id=?",
                                      (request_id,)).fetchone()
        return self._row_to_request(row) if row else None

    # ── Route decisions (HARDENED AUTHORITY BOUNDARY) ──────────────────────────

    def record_route_decision(self, decision: PersistedRouteDecision, *, actor: str = "aria"
                              ) -> PersistedRouteDecision:
        """Persist a route decision after independently re-verifying it. This is the second
        authority boundary — it trusts nothing the caller asserts about execution, the request,
        or the chosen provider."""
        # 0) structural secret / unsafe-ref guards.
        _guard_ids(decision_id=decision.decision_id, route_request_id=decision.route_request_id,
                   correlation_id=decision.correlation_id,
                   adapter_request_id=decision.adapter_request_id,
                   chosen_provider_id=decision.chosen_provider_id,
                   chosen_model_id=decision.chosen_model_id)
        _guard_refs(source_refs=decision.source_refs, evidence_refs=decision.evidence_refs)
        # NB: free-text fields (note, risk_summary, blocked_reasons) are MASKED on write via
        # ``sanitize_text`` — never rejected. Rejecting free text false-positives on already
        # redacted content (e.g. an intent echoed as ``key=[REDACTED]``). Only STRUCTURAL ids
        # / model ids / refs are rejected (above), because a secret-shaped id is never valid.

        # 1) routing NEVER executes a model (model already forbids True; defend anyway).
        if decision.executed:
            raise RoutingIntegrityError("a route decision can never be marked executed=True")

        # 2) the cited request must exist (store self-resolves — never trusts a caller-passed one).
        request = self.get_route_request(decision.route_request_id)
        if request is None:
            raise RoutingIntegrityError(
                f"route decision cites unknown request {decision.route_request_id!r}")
        if request.status is not RouteStatus.requested:
            raise RoutingIntegrityError(
                f"route request {request.request_id!r} is already {request.status.value}")

        # 3) the decision must be ABOUT that request (mismatch guard).
        if decision.intent != request.intent or decision.task_type != request.task_type:
            raise RoutingIntegrityError(
                "route decision does not match its request (intent/task_type mismatch)")
        if decision.adapter_request_id != request.adapter_request_id:
            raise RoutingIntegrityError(
                "route decision adapter_request_id does not match its request")
        if decision.correlation_id not in {request.request_id, request.adapter_request_id or ""}:
            raise RoutingIntegrityError("route decision correlation_id does not match its request")
        if (decision.source_refs != request.source_refs
                or decision.evidence_refs != request.evidence_refs):
            raise RoutingIntegrityError(
                "route decision provenance does not match its persisted request")

        # 4) deny-by-default: an ALLOWED decision must be attributable. A blocked decision may
        #    legitimately have no sources (missing sources can be *why* it is blocked).
        if decision.allowed and not decision.source_refs:
            raise RoutingIntegrityError("an allowed route decision must cite source references")

        # 5) resolve the governing sovereignty policy from the store (authority, not the decision).
        sovereignty = (self.get_sovereignty_policy(request.sovereignty_name)
                       or SovereigntyPolicy())
        egress_forbidden = (sovereignty.forbid_data_egress
                            or sovereignty.boundary in (TrustBoundary.private_only,
                                                        TrustBoundary.local_only))

        # 6) a SUCCESS decision must name a registered, eligible, matching, egress-safe provider.
        is_success = decision.allowed and decision.chosen_model_id is not None
        if is_success:
            if not decision.chosen_provider_id:
                raise RoutingIntegrityError("a successful route decision must name a provider")
            provider = self.get_provider(decision.chosen_provider_id)
            if provider is None:
                raise RoutingIntegrityError(
                    f"chosen provider {decision.chosen_provider_id!r} is not in the registry")
            if not provider.enabled or ProviderStatus(provider.status) not in ELIGIBLE_PROVIDER_STATUSES:
                raise RoutingSecurityError(
                    f"chosen provider {decision.chosen_provider_id!r} is not eligible "
                    f"(status={provider.status}, enabled={provider.enabled})")
            if provider.category is not decision.chosen_category:
                raise RoutingIntegrityError("chosen provider category does not match the decision")
            if provider.model_id != decision.chosen_model_id:
                raise RoutingIntegrityError("chosen provider model_id does not match the decision")
            if egress_forbidden and provider.category in _CLOUD_CATEGORIES:
                raise RoutingSecurityError(
                    "a cloud provider was chosen under a no-egress sovereignty policy")
        elif decision.chosen_model_id is not None:
            # A blocked/not-allowed decision must not carry a chosen model.
            raise RoutingIntegrityError("a blocked route decision must not name a chosen model")

        # 7) Recompute the policy verdict and deterministic provider selection from persisted
        #    state. This prevents a direct caller from choosing a merely-eligible but non-policy
        #    provider, fabricating fallback/cost/risk metadata, or turning a blocked request into
        #    an allowed route. Caller-supplied routing metadata is evidence to verify, not truth.
        gate = RoutingPolicyGate().evaluate(request, sovereignty)
        if gate.allowed:
            selection = GovernedModelRouter(
                fallback_policies=self.get_fallback_policies() or None,
            ).route(
                intent=request.intent,
                task_type=request.task_type,
                providers=self.list_providers(),
                cost_profiles=self.list_cost_profiles(),
                risk_profiles=self.list_risk_profiles(),
                sovereignty=sovereignty,
            )
            routed = selection.decision
            expected = {
                "allowed": routed.allowed,
                "chosen_category": routed.chosen_category,
                "chosen_model_id": routed.chosen_model_id,
                "chosen_provider_id": selection.chosen_provider_id,
                "providers_considered": selection.providers_considered,
                "fallback_chain": routed.fallback_chain,
                "sovereignty_boundary": routed.sovereignty_boundary,
                "sovereignty_applied": selection.sovereignty_applied,
                "fallback_used": selection.fallback_used,
                "cost_estimate": selection.cost_estimate,
                "risk_summary": selection.risk_summary,
                "blocked_reasons": routed.blocked_reasons,
                "note": routed.note,
            }
        else:
            expected = {
                "allowed": False,
                "chosen_category": ModelCategory.fallback_model,
                "chosen_model_id": None,
                "chosen_provider_id": None,
                "providers_considered": [],
                "fallback_chain": [],
                "sovereignty_boundary": gate.sovereignty_boundary,
                "sovereignty_applied": False,
                "fallback_used": False,
                "cost_estimate": None,
                "risk_summary": "unknown",
                "blocked_reasons": gate.blocked_reasons,
                "note": gate.safe_message,
            }
        mismatched = [name for name, value in expected.items()
                      if getattr(decision, name) != value]
        if mismatched:
            raise RoutingIntegrityError(
                "route decision disagrees with governed routing policy: "
                + ", ".join(sorted(mismatched)))

        # 8) persist + advance request status + emit lifecycle events (one transaction).
        req_status = RouteStatus.decided if decision.allowed else RouteStatus.blocked
        lifecycle = (LedgerEventType.model_route_decided if decision.allowed
                     else LedgerEventType.model_route_blocked)
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO route_decision (decision_id, route_request_id, correlation_id, "
                "adapter_request_id, intent, task_type, chosen_category, chosen_model_id, "
                "chosen_provider_id, providers_considered, fallback_chain, sovereignty_boundary, "
                "sovereignty_applied, fallback_used, cost_estimate, risk_summary, allowed, "
                "blocked_reasons, note, executed, source_refs, evidence_refs, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    decision.decision_id, decision.route_request_id, decision.correlation_id,
                    decision.adapter_request_id, sanitize_text(decision.intent), decision.task_type,
                    decision.chosen_category.value, decision.chosen_model_id,
                    decision.chosen_provider_id, _jlist(decision.providers_considered),
                    _jlist(decision.fallback_chain), decision.sovereignty_boundary.value,
                    1 if decision.sovereignty_applied else 0, 1 if decision.fallback_used else 0,
                    decision.cost_estimate, sanitize_text(decision.risk_summary),
                    1 if decision.allowed else 0,
                    json.dumps([sanitize_text(b) or "" for b in decision.blocked_reasons]),
                    sanitize_text(decision.note), 0, _jlist(decision.source_refs),
                    _jlist(decision.evidence_refs), _iso(decision.created_at),
                ),
            )
            conn.execute("UPDATE route_request SET status=? WHERE request_id=?",
                         (req_status.value, decision.route_request_id))
            self._enqueue(conn, lifecycle, task_id=decision.route_request_id, actor=actor,
                          actor_type=ActorType.aria, request_id=decision.route_request_id,
                          decision_id=decision.decision_id, model_id=decision.chosen_model_id,
                          category=decision.chosen_category.value,
                          chosen_provider_id=decision.chosen_provider_id,
                          adapter_request_id=decision.adapter_request_id,
                          sovereignty_boundary=decision.sovereignty_boundary.value,
                          fallback_used=decision.fallback_used, cost_estimate=decision.cost_estimate,
                          correlation_id=decision.correlation_id, status=req_status.value,
                          outcome=req_status.value)
            if decision.fallback_used:
                self._enqueue(conn, LedgerEventType.model_route_fallback_applied,
                              task_id=decision.route_request_id, actor=actor,
                              actor_type=ActorType.aria, request_id=decision.route_request_id,
                              decision_id=decision.decision_id, model_id=decision.chosen_model_id,
                              category=decision.chosen_category.value,
                              chosen_provider_id=decision.chosen_provider_id,
                              correlation_id=decision.correlation_id, status=req_status.value,
                              outcome="fallback_applied")
        self.flush_outbox()
        return self.get_route_decision(decision.decision_id)  # type: ignore[return-value]

    def get_route_decision(self, decision_id: str) -> PersistedRouteDecision | None:
        row = self._connect().execute("SELECT * FROM route_decision WHERE decision_id=?",
                                      (decision_id,)).fetchone()
        return self._row_to_decision(row) if row else None

    def list_route_decisions(self, *, route_request_id: str | None = None,
                            adapter_request_id: str | None = None) -> list[PersistedRouteDecision]:
        conn = self._connect()
        clauses, params = [], []
        if route_request_id is not None:
            clauses.append("route_request_id=?")
            params.append(route_request_id)
        if adapter_request_id is not None:
            clauses.append("adapter_request_id=?")
            params.append(adapter_request_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"SELECT * FROM route_decision{where} ORDER BY created_at, decision_id",
                            params).fetchall()
        return [self._row_to_decision(r) for r in rows]

    # ── Evaluation records (source-linked; no ledger event) ───────────────────

    def create_eval_record(self, e: EvaluationRecord) -> EvaluationRecord:
        if not e.input_ref or not e.output_ref:
            raise RoutingIntegrityError("an evaluation record must be source-linked "
                                        "(input_ref and output_ref required)")
        _guard_ids(eval_id=e.eval_id, input_ref=e.input_ref, output_ref=e.output_ref,
                   model_id=e.model_id, adapter_id=e.adapter_id)
        if not isfinite(e.score) or not 0 <= e.score <= 1:
            raise RoutingIntegrityError("evaluation score must be finite and between 0 and 1")
        if e.cost_estimate is not None and (
                not isfinite(e.cost_estimate) or e.cost_estimate < 0):
            raise RoutingIntegrityError(
                "evaluation cost_estimate must be finite and non-negative")
        if e.latency_ms < 0:
            raise RoutingIntegrityError("evaluation latency_ms must be non-negative")
        conn = self._connect()
        with conn:
            conn.execute(
                "INSERT INTO eval_record (eval_id, goal_id, task_id, adapter_id, model_id, "
                "prompt_version, skill_version, input_ref, output_ref, expected_behavior, "
                "actual_behavior, score, pass_fail, failure_reason, human_label, cost_estimate, "
                "latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    e.eval_id, e.goal_id, e.task_id, e.adapter_id, e.model_id, e.prompt_version,
                    e.skill_version, e.input_ref, e.output_ref, sanitize_text(e.expected_behavior),
                    sanitize_text(e.actual_behavior), e.score, e.pass_fail.value,
                    sanitize_text(e.failure_reason), sanitize_text(e.human_label), e.cost_estimate,
                    e.latency_ms, _iso(e.created_at),
                ),
            )
        return e

    def list_eval_records(self, *, model_id: str | None = None) -> list[EvaluationRecord]:
        conn = self._connect()
        if model_id is not None:
            rows = conn.execute("SELECT * FROM eval_record WHERE model_id=? ORDER BY created_at",
                               (model_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM eval_record ORDER BY created_at").fetchall()
        return [self._row_to_eval(r) for r in rows]

    # ── Row → model ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_provider(row: sqlite3.Row) -> ModelProvider:
        return ModelProvider(
            provider_id=row["provider_id"], vendor=row["vendor"], model_id=row["model_id"],
            category=ModelCategory(row["category"]), enabled=bool(row["enabled"]),
            status=row["status"],
        )

    @staticmethod
    def _row_to_capability(row: sqlite3.Row) -> ModelCapabilityProfile:
        return ModelCapabilityProfile(
            model_id=row["model_id"], categories=[ModelCategory(c) for c in
            json.loads(row["categories"])], context_window=row["context_window"],
            modalities=json.loads(row["modalities"]), strengths=json.loads(row["strengths"]),
        )

    @staticmethod
    def _row_to_cost(row: sqlite3.Row) -> ModelCostLatencyProfile:
        return ModelCostLatencyProfile(
            model_id=row["model_id"], cost_per_1k_input=row["cost_per_1k_input"],
            cost_per_1k_output=row["cost_per_1k_output"], typical_latency_ms=row["typical_latency_ms"],
        )

    @staticmethod
    def _row_to_risk(row: sqlite3.Row) -> ModelRiskProfile:
        return ModelRiskProfile(
            model_id=row["model_id"], data_egress_risk=row["data_egress_risk"],
            privacy_risk=row["privacy_risk"], output_risk=row["output_risk"], notes=row["notes"],
        )

    @staticmethod
    def _row_to_request(row: sqlite3.Row) -> RouteRequest:
        return RouteRequest(
            request_id=row["request_id"], intent=row["intent"], task_type=row["task_type"],
            sovereignty_name=row["sovereignty_name"], adapter_request_id=row["adapter_request_id"],
            source_refs=json.loads(row["source_refs"]), evidence_refs=json.loads(row["evidence_refs"]),
            status=RouteStatus(row["status"]), created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> PersistedRouteDecision:
        return PersistedRouteDecision(
            decision_id=row["decision_id"], route_request_id=row["route_request_id"],
            correlation_id=row["correlation_id"], adapter_request_id=row["adapter_request_id"],
            intent=row["intent"], task_type=row["task_type"],
            chosen_category=ModelCategory(row["chosen_category"]),
            chosen_model_id=row["chosen_model_id"], chosen_provider_id=row["chosen_provider_id"],
            providers_considered=json.loads(row["providers_considered"]),
            fallback_chain=[ModelCategory(c) for c in json.loads(row["fallback_chain"])],
            sovereignty_boundary=TrustBoundary(row["sovereignty_boundary"]),
            sovereignty_applied=bool(row["sovereignty_applied"]),
            fallback_used=bool(row["fallback_used"]), cost_estimate=row["cost_estimate"],
            risk_summary=row["risk_summary"], allowed=bool(row["allowed"]),
            blocked_reasons=json.loads(row["blocked_reasons"]), note=row["note"],
            executed=bool(row["executed"]), source_refs=json.loads(row["source_refs"]),
            evidence_refs=json.loads(row["evidence_refs"]), created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_eval(row: sqlite3.Row) -> EvaluationRecord:
        return EvaluationRecord(
            eval_id=row["eval_id"], goal_id=row["goal_id"], task_id=row["task_id"],
            adapter_id=row["adapter_id"], model_id=row["model_id"], prompt_version=row["prompt_version"],
            skill_version=row["skill_version"], input_ref=row["input_ref"], output_ref=row["output_ref"],
            expected_behavior=row["expected_behavior"], actual_behavior=row["actual_behavior"],
            score=row["score"], pass_fail=EvalOutcome(row["pass_fail"]),
            failure_reason=row["failure_reason"], human_label=row["human_label"],
            cost_estimate=row["cost_estimate"], latency_ms=row["latency_ms"],
            created_at=_parse_dt(row["created_at"]),
        )
