"""
Platform Intelligence — Public API

Import from here, not from individual submodules, to keep the public surface stable.
"""
from .catalog import CatalogStore, InMemoryCatalogStore, ServiceCatalog
from .evidence import EvidenceAssembler
from .evaluator import (
    build_evidence,
    check_authorization,
    check_staleness,
    detect_conflicts,
)
from .fixtures import (
    build_service_fixtures,
    build_source_fixtures,
    load_fixtures_into,
)
from .models import (
    AuthorizationDecision,
    ClaimEvidence,
    ClaimSpec,
    ConflictRecord,
    Evidence,
    EvidencedAnswer,
    KnowledgeSource,
    STALENESS_HOURS,
    SOURCE_AUTHORITY,
    SensitivityLevel,
    ServiceEntry,
    caller_can_access,
    sensitivity_rank,
)
from .sources import InMemorySourceStore, SourceRepository, SourceStore

__all__ = [
    # catalog
    "CatalogStore",
    "InMemoryCatalogStore",
    "ServiceCatalog",
    # evidence
    "EvidenceAssembler",
    # evaluator
    "build_evidence",
    "check_authorization",
    "check_staleness",
    "detect_conflicts",
    # fixtures
    "build_service_fixtures",
    "build_source_fixtures",
    "load_fixtures_into",
    # models
    "AuthorizationDecision",
    "ClaimEvidence",
    "ClaimSpec",
    "ConflictRecord",
    "Evidence",
    "EvidencedAnswer",
    "KnowledgeSource",
    "STALENESS_HOURS",
    "SOURCE_AUTHORITY",
    "SensitivityLevel",
    "ServiceEntry",
    "caller_can_access",
    "sensitivity_rank",
    # sources
    "InMemorySourceStore",
    "SourceRepository",
    "SourceStore",
]
