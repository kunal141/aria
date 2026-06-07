"""
Platform Intelligence — Configurable Fixtures

Factory functions that return fresh instances of the 5 seeded platform services
and their associated KnowledgeSources.

These are NOT singletons. Every call returns a new object so tests can mutate
fixtures without inter-test leakage. Production code should call these once
at startup and register the results into a ServiceCatalog + SourceRepository.

Service dependency graph:
  analytics-pipeline          (no dependencies)
  cms-ingestion               (no dependencies)
  recommendation-service  →  analytics-pipeline
  feed-ranking-service    →  recommendation-service + analytics-pipeline
  notification-service    →  recommendation-service
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import KnowledgeSource, ServiceEntry, SOURCE_AUTHORITY


def _utc(offset_hours: float = 0.0) -> str:
    """Return a UTC ISO timestamp offset_hours relative to an epoch fixture base."""
    base = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(hours=offset_hours)).isoformat()


# ── Service fixtures ──────────────────────────────────────────────────────────

def build_service_fixtures() -> list[ServiceEntry]:
    """Return the 5 canonical platform services as fresh ServiceEntry objects."""
    return [
        ServiceEntry(
            service_id="analytics-pipeline",
            name="Analytics Pipeline",
            version="v2.4.1",
            owner_team="data-platform",
            oncall_contact="data-oncall@example.com",
            tech_stack=["Spark", "Kafka", "Python"],
            dependencies=[],
            sensitivity="internal",
            status="healthy",
            registered_at=_utc(0),
            updated_at=_utc(0),
            repository_url="https://git.internal/analytics-pipeline",
            jira_project="ANLYT",
        ),
        ServiceEntry(
            service_id="cms-ingestion",
            name="CMS Ingestion Service",
            version="v1.8.3",
            owner_team="content-platform",
            oncall_contact="cms-oncall@example.com",
            tech_stack=["Python", "Celery", "PostgreSQL"],
            dependencies=[],
            sensitivity="internal",
            status="healthy",
            registered_at=_utc(0),
            updated_at=_utc(0),
            repository_url="https://git.internal/cms-ingestion",
            jira_project="CMS",
        ),
        ServiceEntry(
            service_id="recommendation-service",
            name="Recommendation Service",
            version="v3.2.1",
            owner_team="ml-platform",
            oncall_contact="ml-oncall@example.com",
            tech_stack=["Python", "TensorFlow", "Redis"],
            dependencies=["analytics-pipeline"],
            sensitivity="internal",
            status="healthy",
            registered_at=_utc(0),
            updated_at=_utc(0),
            repository_url="https://git.internal/recommendation-service",
            jira_project="RECSYS",
        ),
        ServiceEntry(
            service_id="feed-ranking-service",
            name="Feed Ranking Service",
            version="v2.1.0",
            owner_team="ml-platform",
            oncall_contact="ml-oncall@example.com",
            tech_stack=["Python", "Elasticsearch"],
            dependencies=["recommendation-service", "analytics-pipeline"],
            sensitivity="internal",
            status="healthy",
            registered_at=_utc(0),
            updated_at=_utc(0),
            repository_url="https://git.internal/feed-ranking-service",
            jira_project="FEED",
        ),
        ServiceEntry(
            service_id="notification-service",
            name="Notification Service",
            version="v1.5.2",
            owner_team="platform-infra",
            oncall_contact="infra-oncall@example.com",
            tech_stack=["Go", "RabbitMQ"],
            dependencies=["recommendation-service"],
            sensitivity="internal",
            status="healthy",
            registered_at=_utc(0),
            updated_at=_utc(0),
            repository_url="https://git.internal/notification-service",
            jira_project="NOTIF",
        ),
    ]


# ── Source fixtures ───────────────────────────────────────────────────────────

def build_source_fixtures(
    now_iso: str | None = None,
    *,
    include_restricted: bool = True,
) -> list[KnowledgeSource]:
    """
    Return representative KnowledgeSources for each seeded service.

    now_iso: optional UTC ISO string used as content_updated_at for "fresh" sources.
             Defaults to 2026-06-07T00:00:00+00:00 (recent enough to be non-stale).

    include_restricted: if False, restricted-sensitivity sources are omitted.
                        Useful for tests asserting that restricted content is absent.
    """
    if now_iso is None:
        now_iso = "2026-06-07T00:00:00+00:00"

    # A timestamp that is definitely stale for telemetry (>1h old)
    stale_ts = "2026-06-06T00:00:00+00:00"

    sources: list[KnowledgeSource] = [
        # ── analytics-pipeline ────────────────────────────────────────────────
        KnowledgeSource(
            source_id="analytics-pipeline:ci:build-20240601",
            source_type="ci",
            service_id="analytics-pipeline",
            version_ref="build-20240601",
            title="Analytics pipeline CI build",
            content="All 247 tests passed. Build time 4m32s. No regressions.",
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["ci"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),
        KnowledgeSource(
            source_id="analytics-pipeline:telemetry:metrics-latest",
            source_type="telemetry",
            service_id="analytics-pipeline",
            version_ref="2026-06-07",
            title="Analytics pipeline live metrics",
            content=(
                "p99 latency 230ms. Error rate 0.02%. "
                "Throughput 14000 events/s. Memory 78% of limit."
            ),
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["telemetry"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),
        KnowledgeSource(
            source_id="analytics-pipeline:telemetry:metrics-stale",
            source_type="telemetry",
            service_id="analytics-pipeline",
            version_ref="2026-06-06",
            title="Analytics pipeline metrics (previous day)",
            content="p99 latency 280ms. Error rate 0.08%. Throughput 12000 events/s.",
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["telemetry"],
            ingested_at=stale_ts,
            content_updated_at=stale_ts,
        ),

        # ── cms-ingestion ─────────────────────────────────────────────────────
        KnowledgeSource(
            source_id="cms-ingestion:repository:main-sha",
            source_type="repository",
            service_id="cms-ingestion",
            version_ref="abc1234",
            title="CMS ingestion main branch",
            content="Ingestion pipeline handles 3 content types: articles, videos, galleries.",
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["repository"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),
        KnowledgeSource(
            source_id="cms-ingestion:jira:sprint-42",
            source_type="jira",
            service_id="cms-ingestion",
            version_ref="sprint-42",
            title="CMS sprint 42 status",
            content="2 blockers: video encoding timeout, duplicate dedup logic regression.",
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["jira"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),

        # ── recommendation-service ────────────────────────────────────────────
        KnowledgeSource(
            source_id="recommendation-service:telemetry:ctr-latest",
            source_type="telemetry",
            service_id="recommendation-service",
            version_ref="2026-06-07",
            title="Recommendation service CTR metrics",
            content=(
                "CTR 3.2% (down from 3.8% yesterday). "
                "Model version v3.2 serving 100% traffic. "
                "Latency p99 45ms."
            ),
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["telemetry"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),
        KnowledgeSource(
            source_id="recommendation-service:ci:build-20240601",
            source_type="ci",
            service_id="recommendation-service",
            version_ref="build-20240601",
            title="Recommendation service CI build",
            content="3 tests failing in model_serving_test.py. Feature extraction OK.",
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["ci"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),

        # ── feed-ranking-service ──────────────────────────────────────────────
        KnowledgeSource(
            source_id="feed-ranking-service:documentation:arch-v2",
            source_type="documentation",
            service_id="feed-ranking-service",
            version_ref="doc-v2",
            title="Feed ranking architecture",
            content=(
                "Depends on recommendation-service for user interest scores "
                "and analytics-pipeline for engagement signals."
            ),
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["documentation"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),

        # ── notification-service ──────────────────────────────────────────────
        KnowledgeSource(
            source_id="notification-service:telemetry:delivery-latest",
            source_type="telemetry",
            service_id="notification-service",
            version_ref="2026-06-07",
            title="Notification service delivery metrics",
            content=(
                "Push delivery rate 97.3%. SMS 99.1%. Email 98.8%. "
                "Mean delivery latency 1.2s."
            ),
            sensitivity="internal",
            authority=SOURCE_AUTHORITY["telemetry"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),
    ]

    if include_restricted:
        sources.extend(_restricted_source_fixtures(now_iso))

    return sources


def _restricted_source_fixtures(now_iso: str) -> list[KnowledgeSource]:
    """
    Restricted-sensitivity sources — contain synthetic secrets for testing.
    These must NEVER appear in answers or citations for public/internal callers.
    The content includes a recognizable test secret: SECRET_API_KEY=abc123.
    """
    return [
        KnowledgeSource(
            source_id="analytics-pipeline:repository:secrets-config",
            source_type="repository",
            service_id="analytics-pipeline",
            version_ref="secrets-ref-1",
            title="Analytics pipeline secrets config",
            content="SECRET_API_KEY=abc123 DB_PASSWORD=hunter2 WEBHOOK_TOKEN=xyzxyz",
            sensitivity="restricted",
            authority=SOURCE_AUTHORITY["repository"],
            ingested_at=now_iso,
            content_updated_at=now_iso,
        ),
    ]


# ── Convenience loader ────────────────────────────────────────────────────────

def load_fixtures_into(catalog, source_repo, *, include_restricted: bool = True) -> None:
    """
    Populate a ServiceCatalog and SourceRepository with the canonical fixtures.

    catalog:      ServiceCatalog instance
    source_repo:  SourceRepository instance
    """
    for svc in build_service_fixtures():
        catalog.register(svc)
    for src in build_source_fixtures(include_restricted=include_restricted):
        source_repo.ingest(src)
