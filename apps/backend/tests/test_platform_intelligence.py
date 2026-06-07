"""
Platform Intelligence V1 — Deterministic tests

Covers every critical invariant from the Codex directive:
  1. Staleness detection per source-type thresholds
  2. Conflicting CI sources — authority-based resolution
  3. CRITICAL: restricted content NEVER leaks into EvidencedAnswer
  4. Dependency impact analysis (BFS)
  5. Missing evidence gates the answer (fail-closed)
  6. kpi_node integration returns platform_evidence in state
  7. Phase-1 auth at retrieval — restricted source not returned
  8. Phase-2 auth at assembly — restricted source excluded even if retrieved
  9. AuthorizationDecision.reason contains no source content when denied
 10. EvidencedAnswer with unsupported claims has answer=""
 11. Unresolved conflicts exclude both sources
 12. sensitivity_rank ordering
 13. Catalog impact_analysis BFS correctness
 14. EvidencedAnswer.supported_source_ids only from authorized evidence
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from aria.platform.catalog import InMemoryCatalogStore, ServiceCatalog
from aria.platform.evaluator import (
    build_evidence,
    check_authorization,
    check_staleness,
    detect_conflicts,
)
from aria.platform.evidence import EvidenceAssembler
from aria.platform.fixtures import (
    build_service_fixtures,
    build_source_fixtures,
    load_fixtures_into,
)
from aria.platform.models import (
    ClaimSpec,
    KnowledgeSource,
    ServiceEntry,
    SOURCE_AUTHORITY,
    STALENESS_HOURS,
    SensitivityLevel,
    caller_can_access,
    sensitivity_rank,
)
from aria.platform.sources import SourceRepository


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ago_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _fresh_source(
    source_type: str = "ci",
    service_id: str = "analytics-pipeline",
    sensitivity: SensitivityLevel = "internal",
    content: str = "All tests passed.",
    version_ref: str = "build-001",
    source_id: str | None = None,
    hours_old: float = 0.0,
    authority: int | None = None,
) -> KnowledgeSource:
    if source_id is None:
        source_id = f"{service_id}:{source_type}:{uuid.uuid4().hex[:8]}"
    if authority is None:
        authority = SOURCE_AUTHORITY[source_type]
    ts = _ago_iso(hours_old)
    return KnowledgeSource(
        source_id=source_id,
        source_type=source_type,
        service_id=service_id,
        version_ref=version_ref,
        title=f"{service_id} {source_type} {version_ref}",
        content=content,
        sensitivity=sensitivity,
        authority=authority,
        ingested_at=ts,
        content_updated_at=ts,
    )


def _fresh_catalog_and_repo(*, include_restricted: bool = False):
    catalog = ServiceCatalog(InMemoryCatalogStore())
    repo = SourceRepository()
    load_fixtures_into(catalog, repo, include_restricted=include_restricted)
    return catalog, repo


# ─────────────────────────────────────────────────────────────────────────────
# 1. sensitivity_rank ordering
# ─────────────────────────────────────────────────────────────────────────────

def test_sensitivity_rank_ordering():
    assert sensitivity_rank("public") < sensitivity_rank("internal") < sensitivity_rank("restricted")


def test_caller_can_access_public_caller_denied_restricted():
    assert not caller_can_access("public", "restricted")
    assert not caller_can_access("public", "internal")
    assert caller_can_access("public", "public")


def test_caller_can_access_internal_caller():
    assert caller_can_access("internal", "public")
    assert caller_can_access("internal", "internal")
    assert not caller_can_access("internal", "restricted")


def test_caller_can_access_restricted_caller_sees_all():
    assert caller_can_access("restricted", "public")
    assert caller_can_access("restricted", "internal")
    assert caller_can_access("restricted", "restricted")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Staleness detection
# ─────────────────────────────────────────────────────────────────────────────

def test_fresh_telemetry_not_stale():
    src = _fresh_source("telemetry", hours_old=0.5)
    is_stale, hours = check_staleness(src)
    assert not is_stale
    assert hours is not None and hours < 1.0


def test_stale_telemetry_flagged():
    # Telemetry threshold is 1 hour — 2h old is definitely stale
    src = _fresh_source("telemetry", hours_old=2.0)
    is_stale, hours = check_staleness(src)
    assert is_stale
    assert hours is not None and hours >= 2.0


def test_fresh_documentation_not_stale():
    # Documentation threshold is 168h (1 week) — 10h old is fine
    src = _fresh_source("documentation", hours_old=10.0)
    is_stale, _ = check_staleness(src)
    assert not is_stale


def test_stale_documentation_flagged():
    src = _fresh_source("documentation", hours_old=200.0)
    is_stale, _ = check_staleness(src)
    assert is_stale


def test_invalid_timestamp_fails_closed():
    src = _fresh_source("ci")
    src = src.model_copy(update={"content_updated_at": "not-a-timestamp"})
    is_stale, hours = check_staleness(src)
    assert is_stale
    assert hours is None


def test_staleness_hours_match_thresholds():
    assert STALENESS_HOURS["telemetry"] == 1
    assert STALENESS_HOURS["documentation"] == 168
    assert STALENESS_HOURS["ci"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# 3. Conflict detection and resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_no_conflict_same_version_ref():
    src_a = _fresh_source("ci", version_ref="build-001", source_id="svc:ci:a")
    src_b = _fresh_source("ci", version_ref="build-001", source_id="svc:ci:b")
    conflicts = detect_conflicts("claim-1", [src_a, src_b])
    assert len(conflicts) == 0


def test_conflict_different_version_refs():
    src_a = _fresh_source("ci", version_ref="build-001", source_id="svc:ci:a", authority=8)
    src_b = _fresh_source("ci", version_ref="build-002", source_id="svc:ci:b", authority=8)
    conflicts = detect_conflicts("claim-1", [src_a, src_b])
    assert len(conflicts) == 1
    assert conflicts[0].claim_id == "claim-1"


def test_conflict_resolved_by_authority():
    # src_a has higher authority → selected
    src_a = _fresh_source("ci", version_ref="v1", source_id="svc:ci:a", authority=9)
    src_b = _fresh_source("ci", version_ref="v2", source_id="svc:ci:b", authority=6)
    conflicts = detect_conflicts("claim-x", [src_a, src_b])
    assert len(conflicts) == 1
    assert conflicts[0].resolved_by == "authority"
    assert conflicts[0].selected_source_id == "svc:ci:a"


def test_conflict_resolved_by_recency_when_equal_authority():
    older_ts = _ago_iso(10.0)
    newer_ts = _ago_iso(1.0)
    src_a = KnowledgeSource(
        source_id="svc:ci:a", source_type="ci", service_id="s",
        version_ref="v1", title="a", content="older",
        sensitivity="internal", authority=8,
        ingested_at=older_ts, content_updated_at=older_ts,
    )
    src_b = KnowledgeSource(
        source_id="svc:ci:b", source_type="ci", service_id="s",
        version_ref="v2", title="b", content="newer",
        sensitivity="internal", authority=8,
        ingested_at=newer_ts, content_updated_at=newer_ts,
    )
    conflicts = detect_conflicts("claim-x", [src_a, src_b])
    assert conflicts[0].resolved_by == "recency"
    assert conflicts[0].selected_source_id == "svc:ci:b"


def test_conflict_unresolved_when_equal_authority_and_timestamp():
    ts = _now_iso()
    src_a = KnowledgeSource(
        source_id="svc:ci:a", source_type="ci", service_id="s",
        version_ref="v1", title="a", content="same time",
        sensitivity="internal", authority=8,
        ingested_at=ts, content_updated_at=ts,
    )
    src_b = KnowledgeSource(
        source_id="svc:ci:b", source_type="ci", service_id="s",
        version_ref="v2", title="b", content="same time",
        sensitivity="internal", authority=8,
        ingested_at=ts, content_updated_at=ts,
    )
    conflicts = detect_conflicts("claim-x", [src_a, src_b])
    assert conflicts[0].resolved_by == "unresolved"
    assert conflicts[0].selected_source_id is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Authorization decisions
# ─────────────────────────────────────────────────────────────────────────────

def test_authorization_allowed():
    src = _fresh_source("ci", sensitivity="internal")
    decision = check_authorization("internal", src)
    assert decision.allowed is True


def test_authorization_denied():
    src = _fresh_source("ci", sensitivity="restricted")
    decision = check_authorization("internal", src)
    assert decision.allowed is False


def test_authorization_denied_reason_contains_no_source_content():
    """
    CRITICAL: when allowed=False, reason must NOT include source.content, source.title,
    or any text derived from the actual source data.
    """
    secret_content = "SECRET_API_KEY=abc123 DB_PASSWORD=hunter2"
    src = _fresh_source("repository", sensitivity="restricted", content=secret_content)
    src = src.model_copy(update={"title": "secret config file"})
    decision = check_authorization("public", src)
    assert decision.allowed is False
    # reason must not contain the secret content
    assert "SECRET_API_KEY" not in decision.reason
    assert "abc123" not in decision.reason
    assert "hunter2" not in decision.reason
    # reason must not contain the title
    assert "secret config file" not in decision.reason


# ─────────────────────────────────────────────────────────────────────────────
# 5. Phase-1 auth at retrieval — SourceRepository.query()
# ─────────────────────────────────────────────────────────────────────────────

def test_source_repo_phase1_blocks_restricted_source():
    repo = SourceRepository()
    secret_src = _fresh_source("repository", sensitivity="restricted",
                               content="SECRET_API_KEY=abc123")
    repo.ingest(secret_src)

    results = repo.query("internal")
    ids = {s.source_id for s in results}
    assert secret_src.source_id not in ids


def test_source_repo_phase1_blocks_via_get():
    repo = SourceRepository()
    secret_src = _fresh_source("repository", sensitivity="restricted",
                               content="SECRET_API_KEY=abc123")
    repo.ingest(secret_src)

    result = repo.get(secret_src.source_id, "internal")
    assert result is None


def test_source_repo_restricted_caller_sees_restricted():
    repo = SourceRepository()
    secret_src = _fresh_source("repository", sensitivity="restricted",
                               content="SECRET_API_KEY=abc123")
    repo.ingest(secret_src)

    result = repo.get(secret_src.source_id, "restricted")
    assert result is not None
    assert result.source_id == secret_src.source_id


def test_source_repo_public_source_visible_to_all():
    repo = SourceRepository()
    pub_src = _fresh_source("documentation", sensitivity="public")
    repo.ingest(pub_src)

    for level in ("public", "internal", "restricted"):
        r = repo.get(pub_src.source_id, level)  # type: ignore[arg-type]
        assert r is not None, f"Expected public source visible to {level}"


# ─────────────────────────────────────────────────────────────────────────────
# 6. CRITICAL: restricted content NEVER appears in EvidencedAnswer
# ─────────────────────────────────────────────────────────────────────────────

def test_restricted_content_never_in_evidenced_answer():
    """
    Asserts that the recognizable test secret 'SECRET_API_KEY=abc123' does NOT
    appear anywhere in the JSON-serialized EvidencedAnswer when the caller has
    'internal' level. Checks: answer, excerpts, reason fields, authorization
    decision reasons, blocked_reason, freshness_warnings.
    """
    catalog = ServiceCatalog(InMemoryCatalogStore())
    repo = SourceRepository()
    load_fixtures_into(catalog, repo, include_restricted=True)

    claim = ClaimSpec(
        claim_id="health",
        claim_text="Is analytics-pipeline healthy?",
        service_ids=["analytics-pipeline"],
        source_types=["repository", "telemetry", "ci"],
        keywords=["health", "error", "metrics"],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="What is the health of analytics-pipeline?",
        claims=[claim],
        caller_level="internal",
    )

    payload = evidenced.model_dump_json()

    assert "SECRET_API_KEY" not in payload, (
        f"SECRET_API_KEY leaked into EvidencedAnswer JSON:\n{payload[:500]}"
    )
    assert "abc123" not in payload, (
        f"Secret value 'abc123' leaked into EvidencedAnswer JSON:\n{payload[:500]}"
    )
    assert "hunter2" not in payload, (
        f"Secret value 'hunter2' leaked into EvidencedAnswer JSON"
    )


def test_restricted_content_not_in_authorization_decision_reason():
    """Even the authorization_decisions list must not expose restricted content."""
    catalog = ServiceCatalog(InMemoryCatalogStore())
    repo = SourceRepository()
    load_fixtures_into(catalog, repo, include_restricted=True)

    claim = ClaimSpec(
        claim_id="health",
        claim_text="Is analytics-pipeline healthy?",
        service_ids=["analytics-pipeline"],
        source_types=["repository"],
        keywords=["health"],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="health of analytics-pipeline",
        claims=[claim],
        caller_level="internal",
    )

    for decision in evidenced.authorization_decisions:
        assert "SECRET_API_KEY" not in decision.reason
        assert "abc123" not in decision.reason


def test_public_caller_gets_no_restricted_evidence():
    catalog, repo = _fresh_catalog_and_repo(include_restricted=True)

    claim = ClaimSpec(
        claim_id="any",
        claim_text="anything",
        service_ids=["analytics-pipeline"],
        source_types=["repository", "telemetry", "ci"],
        keywords=[],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="test",
        claims=[claim],
        caller_level="public",
    )

    payload = evidenced.model_dump_json()
    assert "SECRET_API_KEY" not in payload
    for ce in evidenced.claim_evidence_map:
        for ev in ce.evidence:
            assert ev.sensitivity != "restricted"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Missing evidence gates the answer (fail-closed)
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_evidence_produces_empty_answer():
    catalog = ServiceCatalog(InMemoryCatalogStore())
    repo = SourceRepository()  # empty — no sources ingested

    claim = ClaimSpec(
        claim_id="health",
        claim_text="Is recommendation-service healthy?",
        service_ids=["recommendation-service"],
        source_types=["telemetry"],
        keywords=["ctr"],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="What is CTR for recommendation-service?",
        claims=[claim],
        caller_level="internal",
    )

    assert not evidenced.is_safe_to_surface
    assert evidenced.answer == ""
    assert evidenced.blocked_reason is not None
    assert "health" in evidenced.blocked_reason


def test_unsupported_claim_flag():
    catalog = ServiceCatalog(InMemoryCatalogStore())
    repo = SourceRepository()

    claim = ClaimSpec(
        claim_id="ghost-claim",
        claim_text="No sources exist for this",
        service_ids=["nonexistent-service"],
        source_types=["telemetry"],
        keywords=["never-matches"],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="test", claims=[claim], caller_level="internal",
    )

    assert evidenced.has_unsupported_claims
    assert evidenced.answer == ""


def test_mixed_claims_any_unsupported_gates_answer():
    catalog, repo = _fresh_catalog_and_repo(include_restricted=False)

    supported_claim = ClaimSpec(
        claim_id="supported",
        claim_text="Analytics pipeline telemetry",
        service_ids=["analytics-pipeline"],
        source_types=["telemetry"],
        keywords=["latency"],
    )
    unsupported_claim = ClaimSpec(
        claim_id="missing",
        claim_text="No source for this service",
        service_ids=["nonexistent-service"],
        source_types=["telemetry"],
        keywords=["anything"],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="test",
        claims=[supported_claim, unsupported_claim],
        caller_level="internal",
    )

    assert not evidenced.is_safe_to_surface
    assert evidenced.answer == ""


# ─────────────────────────────────────────────────────────────────────────────
# 8. Unresolved conflict excludes both sources
# ─────────────────────────────────────────────────────────────────────────────

def test_unresolved_conflict_excludes_both_sources():
    """
    When two same-type sources with the same timestamp cannot be resolved,
    both are excluded. The claim becomes unsupported (no surviving evidence).
    """
    ts = _now_iso()
    repo = SourceRepository()
    catalog = ServiceCatalog(InMemoryCatalogStore())
    for s in build_service_fixtures():
        catalog.register(s)

    src_a = KnowledgeSource(
        source_id="s:ci:a", source_type="ci", service_id="analytics-pipeline",
        version_ref="v1", title="CI build A", content="tests passed",
        sensitivity="internal", authority=8,
        ingested_at=ts, content_updated_at=ts,
    )
    src_b = KnowledgeSource(
        source_id="s:ci:b", source_type="ci", service_id="analytics-pipeline",
        version_ref="v2", title="CI build B", content="tests failed",
        sensitivity="internal", authority=8,
        ingested_at=ts, content_updated_at=ts,
    )
    repo.ingest(src_a)
    repo.ingest(src_b)

    claim = ClaimSpec(
        claim_id="build-status",
        claim_text="CI build status",
        service_ids=["analytics-pipeline"],
        source_types=["ci"],
        keywords=["tests"],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="build status?", claims=[claim], caller_level="internal",
    )

    ce = evidenced.claim_evidence_map[0]
    assert len(ce.conflicts) == 1
    assert ce.conflicts[0].resolved_by == "unresolved"
    # Both excluded → no surviving evidence → unsupported
    assert not ce.is_supported
    assert not evidenced.is_safe_to_surface


# ─────────────────────────────────────────────────────────────────────────────
# 9. Dependency impact analysis (BFS)
# ─────────────────────────────────────────────────────────────────────────────

def test_impact_analysis_analytics_pipeline_down():
    """
    analytics-pipeline fails → recommendation-service + feed-ranking-service affected.
    notification-service is NOT directly affected (depends on recommendation-service,
    but that's a second-order failure — it IS included via BFS).
    """
    catalog, _ = _fresh_catalog_and_repo()
    affected = set(catalog.impact_analysis("analytics-pipeline"))
    assert "recommendation-service" in affected
    assert "feed-ranking-service" in affected
    # notification-service depends on recommendation-service, which depends on
    # analytics-pipeline → third-order, but BFS will find it
    assert "notification-service" in affected
    # cms-ingestion has no dependents
    assert "cms-ingestion" not in affected


def test_impact_analysis_recommendation_service_down():
    """
    recommendation-service fails →  notification-service + feed-ranking-service.
    analytics-pipeline is NOT in the impacted set (it's an upstream dependency, not downstream).
    """
    catalog, _ = _fresh_catalog_and_repo()
    affected = set(catalog.impact_analysis("recommendation-service"))
    assert "notification-service" in affected
    assert "feed-ranking-service" in affected
    assert "analytics-pipeline" not in affected
    assert "cms-ingestion" not in affected


def test_impact_analysis_leaf_service_has_no_affected():
    catalog, _ = _fresh_catalog_and_repo()
    # cms-ingestion has no dependents
    affected = catalog.impact_analysis("cms-ingestion")
    assert affected == []


def test_impact_analysis_notification_service_has_no_dependents():
    catalog, _ = _fresh_catalog_and_repo()
    affected = catalog.impact_analysis("notification-service")
    assert affected == []


def test_impact_analysis_does_not_include_origin_service():
    catalog, _ = _fresh_catalog_and_repo()
    affected = catalog.impact_analysis("analytics-pipeline")
    assert "analytics-pipeline" not in affected


# ─────────────────────────────────────────────────────────────────────────────
# 10. kpi_node integration — platform_evidence in state
# ─────────────────────────────────────────────────────────────────────────────

def test_kpi_node_returns_platform_evidence():
    from aria.nodes.skill_nodes import kpi_node
    import uuid as _uuid

    state = {
        "task_id":         _uuid.uuid4().hex,
        "raw_input":       "What is causing the CTR drop on analytics-pipeline?",
        "task_type":       "kpi",
        "task_status":     "executing",
        "routing_reason":  "kpi keyword matched",
        "steps_completed": ["intake", "router"],
        "skill_name":      None,
        "skill_output":    None,
        "response":        None,
        "messages":        [],
        "error":           None,
        "audience":        "developer",
        "langsmith_run_id": None,
        "routing_tier":    "smart",
        "complexity":      "normal",
        "approval_request_id": None,
        "data_sensitivity": "internal",
        "execution_mode":  "dry_run",
        "token_budget":    50000,
        "token_budget_used": 0,
        "platform_evidence": None,
    }

    result = kpi_node(state)

    assert "skill_output" in result
    assert result.get("platform_evidence") is not None, (
        "kpi_node should populate platform_evidence after skill execution"
    )

    # Validate it's parseable JSON with expected structure
    evidence_data = json.loads(result["platform_evidence"])
    assert "answer_id" in evidence_data
    assert "claim_evidence_map" in evidence_data
    assert "authorization_decisions" in evidence_data
    assert "is_safe_to_surface" in evidence_data


def test_kpi_node_platform_evidence_has_no_restricted_content():
    """
    platform_evidence from kpi_node (caller_level='internal') must not
    contain any restricted-sensitivity source content.
    """
    from aria.nodes.skill_nodes import kpi_node
    import uuid as _uuid

    state = {
        "task_id":         _uuid.uuid4().hex,
        "raw_input":       "KPI check for analytics-pipeline",
        "task_type":       "kpi",
        "task_status":     "executing",
        "routing_reason":  None,
        "steps_completed": ["intake", "router"],
        "skill_name":      None,
        "skill_output":    None,
        "response":        None,
        "messages":        [],
        "error":           None,
        "audience":        "developer",
        "langsmith_run_id": None,
        "routing_tier":    "smart",
        "complexity":      "normal",
        "approval_request_id": None,
        "data_sensitivity": "internal",
        "execution_mode":  "dry_run",
        "token_budget":    50000,
        "token_budget_used": 0,
        "platform_evidence": None,
    }

    result = kpi_node(state)
    pe = result.get("platform_evidence") or ""
    # Restricted fixture content must not appear
    assert "SECRET_API_KEY" not in pe
    assert "abc123" not in pe


# ─────────────────────────────────────────────────────────────────────────────
# 11. Freshness warnings in EvidencedAnswer
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_source_generates_freshness_warning():
    catalog = ServiceCatalog(InMemoryCatalogStore())
    for s in build_service_fixtures():
        catalog.register(s)

    repo = SourceRepository()
    # Stale telemetry source (>1h old)
    stale = _fresh_source("telemetry", service_id="analytics-pipeline",
                          content="old metrics", hours_old=5.0)
    repo.ingest(stale)

    claim = ClaimSpec(
        claim_id="health",
        claim_text="Analytics pipeline health",
        service_ids=["analytics-pipeline"],
        source_types=["telemetry"],
        keywords=["metrics"],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="health check", claims=[claim], caller_level="internal",
    )

    # Answer IS surfaced (stale evidence counts as supported)
    assert evidenced.is_safe_to_surface
    assert len(evidenced.freshness_warnings) > 0
    assert "health" in evidenced.freshness_warnings[0]


# ─────────────────────────────────────────────────────────────────────────────
# 12. EvidencedAnswer.supported_source_ids — only from authorized evidence
# ─────────────────────────────────────────────────────────────────────────────

def test_supported_source_ids_excludes_unauthorized():
    catalog = ServiceCatalog(InMemoryCatalogStore())
    for s in build_service_fixtures():
        catalog.register(s)

    repo = SourceRepository()
    pub_src = _fresh_source("ci", sensitivity="public", service_id="analytics-pipeline",
                            source_id="svc:ci:public")
    restricted_src = _fresh_source("repository", sensitivity="restricted",
                                   service_id="analytics-pipeline",
                                   source_id="svc:repo:restricted",
                                   content="SECRET_API_KEY=abc123")
    repo.ingest(pub_src)
    repo.ingest(restricted_src)

    claim = ClaimSpec(
        claim_id="c1",
        claim_text="Any info",
        service_ids=["analytics-pipeline"],
        source_types=["ci", "repository"],
        keywords=[],
    )

    assembler = EvidenceAssembler(catalog, repo)
    evidenced = assembler.assemble(
        query="test", claims=[claim], caller_level="internal",
    )

    # Only authorized sources (public/internal) appear in supported_source_ids
    assert "svc:repo:restricted" not in evidenced.supported_source_ids
    assert "svc:ci:public" in evidenced.supported_source_ids


# ─────────────────────────────────────────────────────────────────────────────
# 13. Fixture factories return fresh instances (no singleton leakage)
# ─────────────────────────────────────────────────────────────────────────────

def test_service_fixtures_return_distinct_instances():
    fixtures_a = build_service_fixtures()
    fixtures_b = build_service_fixtures()
    assert fixtures_a is not fixtures_b
    assert fixtures_a[0] is not fixtures_b[0]


def test_source_fixtures_return_distinct_instances():
    sources_a = build_source_fixtures()
    sources_b = build_source_fixtures()
    assert sources_a is not sources_b


def test_fixtures_load_into_fresh_catalog():
    catalog_a = ServiceCatalog(InMemoryCatalogStore())
    catalog_b = ServiceCatalog(InMemoryCatalogStore())
    repo_a = SourceRepository()
    repo_b = SourceRepository()
    load_fixtures_into(catalog_a, repo_a)
    load_fixtures_into(catalog_b, repo_b)

    # Mutating one catalog does not affect the other
    catalog_a.update_status("analytics-pipeline", "down")
    svc_a = catalog_a.get("analytics-pipeline")
    svc_b = catalog_b.get("analytics-pipeline")
    assert svc_a is not None and svc_a.status == "down"
    assert svc_b is not None and svc_b.status == "healthy"


# ─────────────────────────────────────────────────────────────────────────────
# 14. ServiceCatalog CRUD
# ─────────────────────────────────────────────────────────────────────────────

def test_catalog_require_raises_for_unknown_service():
    catalog = ServiceCatalog(InMemoryCatalogStore())
    with pytest.raises(KeyError):
        catalog.require("does-not-exist")


def test_catalog_update_status_persists():
    catalog, _ = _fresh_catalog_and_repo()
    catalog.update_status("cms-ingestion", "degraded")
    svc = catalog.get("cms-ingestion")
    assert svc is not None
    assert svc.status == "degraded"


def test_catalog_list_services_all_five():
    catalog, _ = _fresh_catalog_and_repo()
    ids = {s.service_id for s in catalog.list_services()}
    assert ids == {
        "analytics-pipeline",
        "cms-ingestion",
        "recommendation-service",
        "feed-ranking-service",
        "notification-service",
    }
