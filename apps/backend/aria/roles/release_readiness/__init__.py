"""
Release Readiness role pack — executable form of RELEASE_READINESS_POLICY_RULES_V0.

Each rule is a deterministic predicate over Tier-A facts, and every rule inherits the
universal abstention condition: **never evaluate on assumed facts.** If a required
input is absent, stale, conflicting, or unauthorized, the rule abstains rather than
concluding. That is the single most important behaviour here — a confident verdict on
missing evidence is precisely the failure that ships broken releases.

Untrusted text (PR bodies, ticket descriptions) is *never* consulted by any rule. It
is scanned only so an injection attempt can be flagged; it can never influence a
verdict, because the verdicts are computed from structured facts alone.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aria.proof import ClaimVerdict, EvidenceRef, EvidenceState, Verdict, content_hash

# Freshness windows per rule, in hours (policy doc §2).
_CHECK_FRESHNESS_HOURS = 24.0
_INCIDENT_FRESHNESS_HOURS = 1.0
_ADVISORY_FRESHNESS_HOURS = 24.0

_SUCCESS = "success"

# Phrases that indicate an attempt to steer the reviewer via source content. Used
# for FLAGGING ONLY — no rule reads untrusted text to decide anything.
_INJECTION_PATTERNS = (
    r"ignore\s+(?:all\s+)?previous\s+instructions",
    r"disregard\s+(?:the\s+)?above",
    r"mark\s+(?:this\s+)?(?:release\s+)?(?:as\s+)?approved",
    r"report\s+every\s+check\s+as\s+passed",
    r"you\s+are\s+now\s+",
)


class Disposition(str, Enum):
    ready = "ready"
    not_ready = "not-ready"
    insufficient_evidence = "insufficient-evidence"


class Approval(BaseModel):
    model_config = ConfigDict(frozen=True)
    approver: str
    state: Literal["approved", "changes_requested", "commented"]
    timestamp: datetime
    is_codeowner: bool = False
    retracted: bool = False


class CheckRun(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    commit_sha: str
    conclusion: str
    completed_at: datetime


class Incident(BaseModel):
    model_config = ConfigDict(frozen=True)
    severity: str
    affected_service: str
    state: str


class Advisory(BaseModel):
    model_config = ConfigDict(frozen=True)
    package: str
    severity: str
    has_valid_exception: bool = False


class ReleaseSnapshot(BaseModel):
    """Tier-A facts for one release, captured from systems of record."""
    model_config = ConfigDict(frozen=True)

    release_ref: str
    merge_commit_sha: str
    author_id: str

    approvals: list[Approval] = Field(default_factory=list)
    codeowners_available: bool = True

    required_check_names: list[str] = Field(default_factory=list)
    check_runs: list[CheckRun] = Field(default_factory=list)
    ci_log_intact: bool = True

    rollback_plan_ref: str | None = None
    rollback_plan_reachable: bool = True
    has_irreversible_migration: bool | None = False
    forward_fix_documented: bool = False

    release_ticket_id: str | None = None
    release_ticket_state: str = "approved"
    release_ticket_covers_commit: bool = True

    affected_services: list[str] = Field(default_factory=list)
    open_incidents: list[Incident] = Field(default_factory=list)
    incident_feed_observed_at: datetime | None = None

    dependency_advisories: list[Advisory] = Field(default_factory=list)
    advisory_db_observed_at: datetime | None = None

    # Sources the tenant is not authorized to read for this commitment.
    unauthorized_sources: list[str] = Field(default_factory=list)
    # Attacker-influenceable content. Scanned for flags; never used in a decision.
    untrusted_text: str = ""

    decision_time: datetime | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _stale(observed_at: datetime | None, window_hours: float, now: datetime) -> bool:
    if observed_at is None:
        return True
    return (now - observed_at).total_seconds() > window_hours * 3_600


def detect_injection(text: str) -> list[str]:
    """Flag steering attempts found in untrusted source content."""
    if not text:
        return []
    lowered = text.lower()
    return (
        ["prompt_injection_detected"]
        if any(re.search(pattern, lowered) for pattern in _INJECTION_PATTERNS)
        else []
    )


def _evidence(source: str, facts: object, observed_at: datetime | None,
              now: datetime) -> EvidenceRef:
    """Bind a verdict to the exact facts it was decided from.

    The hash is taken over the canonical serialization of the *facts the rule
    actually read*, so the citation is verifiable rather than decorative: if the
    underlying snapshot changes, the hash no longer matches.
    """
    payload = repr(facts).encode("utf-8")
    return EvidenceRef(
        source=source,
        content_hash=content_hash(payload),
        observed_at=observed_at or now,
        locator=source,
    )


def _verdict(
    rule_id: str, verdict: Verdict, *, reason: EvidenceState | None = None,
    flags: list[str] | None = None, evidence: list[EvidenceRef] | None = None,
) -> ClaimVerdict:
    return ClaimVerdict(
        manifest_item_id=rule_id,
        verdict=verdict,
        cited_policy_rule_id=rule_id,
        evidence_refs=evidence or [],
        abstention_reason=reason,
        flags=flags or [],
    )


# ── Rules ─────────────────────────────────────────────────────────────────────


def _ci_evidence(s: "ReleaseSnapshot", now: datetime) -> list[EvidenceRef]:
    return [_evidence("ci_system", s.check_runs,
                      max((r.completed_at for r in s.check_runs), default=None), now)]


def rr_001_approvals(s: ReleaseSnapshot, now: datetime) -> ClaimVerdict:
    if "source_control" in s.unauthorized_sources:
        return _verdict("RR-001", Verdict.abstained, reason=EvidenceState.unauthorized)
    if not s.codeowners_available:
        return _verdict("RR-001", Verdict.abstained, reason=EvidenceState.absent)
    if not s.approvals:
        return _verdict("RR-001", Verdict.unsatisfied)
    valid = [
        a for a in s.approvals
        if a.state == "approved" and not a.retracted and a.approver != s.author_id
    ]
    ev = [_evidence("source_control", s.approvals,
                    max((a.timestamp for a in s.approvals), default=None), now)]
    if len(valid) < 2 or not any(a.is_codeowner for a in valid):
        return _verdict("RR-001", Verdict.unsatisfied, evidence=ev)
    return _verdict("RR-001", Verdict.supported, evidence=ev)


def rr_002_required_checks(s: ReleaseSnapshot, now: datetime) -> ClaimVerdict:
    if "ci_system" in s.unauthorized_sources:
        return _verdict("RR-002", Verdict.abstained, reason=EvidenceState.unauthorized)
    if not s.required_check_names:
        # No policy rule exists for what "required" means — cannot conclude.
        return _verdict("RR-002", Verdict.abstained, reason=EvidenceState.absent)
    if not s.ci_log_intact:
        return _verdict("RR-002", Verdict.abstained, reason=EvidenceState.absent)

    for name in s.required_check_names:
        on_commit = [r for r in s.check_runs
                     if r.name == name and r.commit_sha == s.merge_commit_sha]
        if not on_commit:
            return _verdict("RR-002", Verdict.unsatisfied, evidence=_ci_evidence(s, now))
        if len({r.conclusion for r in on_commit}) > 1:
            return _verdict("RR-002", Verdict.abstained, reason=EvidenceState.conflicting)
        if any(_stale(r.completed_at, _CHECK_FRESHNESS_HOURS, now) for r in on_commit):
            return _verdict("RR-002", Verdict.abstained, reason=EvidenceState.stale)
        if any(r.conclusion != _SUCCESS for r in on_commit):
            return _verdict("RR-002", Verdict.unsatisfied, evidence=_ci_evidence(s, now))
    return _verdict("RR-002", Verdict.supported, evidence=_ci_evidence(s, now))


def rr_003_rollback(s: ReleaseSnapshot, now: datetime) -> ClaimVerdict:
    if s.rollback_plan_ref is None:
        return _verdict("RR-003", Verdict.unsatisfied,
                        evidence=[_evidence("release_tracker", None, s.decision_time, now)])
    if not s.rollback_plan_reachable:
        return _verdict("RR-003", Verdict.abstained, reason=EvidenceState.absent)
    if s.has_irreversible_migration is None:
        return _verdict("RR-003", Verdict.abstained, reason=EvidenceState.absent)
    ev = [_evidence("release_tracker",
                    (s.rollback_plan_ref, s.has_irreversible_migration,
                     s.forward_fix_documented), s.decision_time, now)]
    if s.has_irreversible_migration and not s.forward_fix_documented:
        return _verdict("RR-003", Verdict.unsatisfied, evidence=ev)
    return _verdict("RR-003", Verdict.supported, evidence=ev)


def rr_004_change_record(s: ReleaseSnapshot, now: datetime) -> ClaimVerdict:
    if not s.release_ticket_id:
        return _verdict("RR-004", Verdict.unsatisfied,
                        evidence=[_evidence("issue_tracker", None, s.decision_time, now)])
    if "," in s.release_ticket_id:
        # Ambiguous / duplicate identifiers — escalate rather than pick one.
        return _verdict("RR-004", Verdict.abstained, reason=EvidenceState.conflicting)
    ev = [_evidence("issue_tracker",
                    (s.release_ticket_id, s.release_ticket_state,
                     s.release_ticket_covers_commit), s.decision_time, now)]
    if s.release_ticket_state != "approved" or not s.release_ticket_covers_commit:
        return _verdict("RR-004", Verdict.unsatisfied, evidence=ev)
    return _verdict("RR-004", Verdict.supported, evidence=ev)


def rr_005_incidents(s: ReleaseSnapshot, now: datetime) -> ClaimVerdict:
    if "incident_management" in s.unauthorized_sources:
        return _verdict("RR-005", Verdict.abstained, reason=EvidenceState.unauthorized)
    if not s.affected_services:
        return _verdict("RR-005", Verdict.abstained, reason=EvidenceState.absent)
    if _stale(s.incident_feed_observed_at, _INCIDENT_FRESHNESS_HOURS, now):
        return _verdict("RR-005", Verdict.abstained, reason=EvidenceState.stale)
    blocking = [
        i for i in s.open_incidents
        if i.severity.upper() in {"SEV1", "SEV2"}
        and i.state.upper() == "OPEN"
        and i.affected_service in s.affected_services
    ]
    ev = [_evidence("incident_management", s.open_incidents,
                    s.incident_feed_observed_at, now)]
    return _verdict("RR-005", Verdict.unsatisfied if blocking else Verdict.supported,
                    evidence=ev)


def rr_006_dependencies(s: ReleaseSnapshot, now: datetime) -> ClaimVerdict:
    if _stale(s.advisory_db_observed_at, _ADVISORY_FRESHNESS_HOURS, now):
        return _verdict("RR-006", Verdict.abstained, reason=EvidenceState.stale)
    blocking = [
        a for a in s.dependency_advisories
        if a.severity.upper() == "CRITICAL" and not a.has_valid_exception
    ]
    ev = [_evidence("dependency_scanner", s.dependency_advisories,
                    s.advisory_db_observed_at, now)]
    return _verdict("RR-006", Verdict.unsatisfied if blocking else Verdict.supported,
                    evidence=ev)


_RULES = (
    rr_001_approvals,
    rr_002_required_checks,
    rr_003_rollback,
    rr_004_change_record,
    rr_005_incidents,
    rr_006_dependencies,
)

# Rules whose failure blocks a release (policy doc materiality=critical).
_CRITICAL_RULES = {"RR-001", "RR-002", "RR-003", "RR-005", "RR-006"}


def evaluate_release_readiness(
    snapshot: ReleaseSnapshot, *, now: datetime | None = None
) -> list[ClaimVerdict]:
    """Apply every rule. Injection flags ride along; they never alter a verdict."""
    moment = now or snapshot.decision_time or _now()
    flags = detect_injection(snapshot.untrusted_text)
    verdicts = [rule(snapshot, moment) for rule in _RULES]
    if not flags:
        return verdicts
    return [v.model_copy(update={"flags": [*v.flags, *flags]}) for v in verdicts]


def release_disposition(verdicts) -> Disposition:
    """Policy-derived disposition.

    Ordering is deliberate: a **known** critical failure outranks a cannot-determine,
    because "it is broken" and "we cannot tell" call for different manager actions.
    ``insufficient-evidence`` is never silently treated as ``ready``.
    """
    items = list(verdicts)
    critical = [v for v in items if v.manifest_item_id in _CRITICAL_RULES]
    if any(v.verdict is Verdict.unsatisfied for v in critical):
        return Disposition.not_ready
    if any(v.verdict in {Verdict.abstained, Verdict.omitted} for v in critical):
        return Disposition.insufficient_evidence
    if any(v.verdict is Verdict.unsatisfied for v in items):
        return Disposition.not_ready
    if any(v.verdict in {Verdict.abstained, Verdict.omitted} for v in items):
        return Disposition.insufficient_evidence
    return Disposition.ready


__all__ = [
    "Advisory",
    "Approval",
    "CheckRun",
    "Disposition",
    "Incident",
    "ReleaseSnapshot",
    "detect_injection",
    "evaluate_release_readiness",
    "release_disposition",
]
