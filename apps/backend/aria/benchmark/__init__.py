"""
aria.benchmark — the two arms the Work Proof Benchmark compares.

**Arm A (ARIA)** answers the manifest with deterministic validators, explicit
abstention, and hash-bound evidence.

**Arm B (baseline)** is a competent LLM agent with the same facts, the same manifest,
the same verdict vocabulary, and a tool-call audit log — i.e. what a good engineer
would build today without a proof layer.

The single largest threat to this benchmark's credibility is a strawman baseline,
because a weak Arm B flatters ARIA and nobody reading the result can tell. Three
controls exist here for that reason:

1. The baseline prompt is built from the *same manifest* ARIA answers, so it can never
   be denied a check ARIA is credited for.
2. The prompt explicitly permits abstention. A baseline forbidden from saying "I don't
   know" would be rigged toward false confidence.
3. Every arm's configuration — prompt, model, framework, temperature, tools, and the
   hours spent building it — is hashed. Post-hoc tuning changes the hash and is
   therefore detectable by a reviewer who never saw the build.

Reconciliation is applied to **both** arms identically, so neither can shrink the
denominator by answering only the easy checks.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aria.proof import (
    ClaimVerdict,
    EvidenceRef,
    EvidenceState,
    ManifestItem,
    Materiality,
    Tier,
    Verdict,
    content_hash,
    reconcile,
)
from aria.roles.release_readiness import ReleaseSnapshot, evaluate_release_readiness

_MAX_AUDIT_DETAIL = 200


def _now() -> datetime:
    return datetime.now(UTC)


class ArmConfig(BaseModel):
    """Frozen, hashable description of how an arm was built."""
    model_config = ConfigDict(frozen=True)

    arm: Literal["aria", "baseline"]
    framework: str
    model: str
    temperature: float
    prompt: str
    tools: list[str] = Field(default_factory=list)
    build_hours: float = 0.0

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str
    detail: str = ""
    at: datetime


class ArmResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    arm: str
    config_hash: str
    verdicts: list[ClaimVerdict]
    audit_log: list[AuditEntry] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime


def release_manifest() -> list[ManifestItem]:
    """The frozen mandatory checks both arms must answer.

    Materiality mirrors RELEASE_READINESS_POLICY_RULES_V0: RR-004 (change record) is
    major; every other rule blocks a release.
    """
    specs = (
        ("RR-001", "The release satisfies the change-approval policy.",
         "source_control", Materiality.critical, None),
        ("RR-002", "All required CI checks passed on the release commit.",
         "ci_system", Materiality.critical, 24.0),
        ("RR-003", "A documented rollback path exists for this release.",
         "release_tracker", Materiality.critical, None),
        ("RR-004", "A traceable, approved change record covers this commit.",
         "issue_tracker", Materiality.major, 72.0),
        ("RR-005", "No open blocking incident affects a touched service.",
         "incident_management", Materiality.critical, 1.0),
        ("RR-006", "No known-critical vulnerable dependency was introduced.",
         "dependency_scanner", Materiality.critical, 24.0),
    )
    return [
        ManifestItem(
            manifest_item_id=rule_id, tier=Tier.B, claim_text=text,
            policy_rule_id=rule_id, materiality=materiality,
            authoritative_source=source, freshness_window_hours=freshness,
        )
        for rule_id, text, source, materiality, freshness in specs
    ]


class AriaArm:
    """Arm A — deterministic validators with explicit abstention."""

    def __init__(self) -> None:
        self.config = ArmConfig(
            arm="aria", framework="aria.roles.release_readiness",
            model="deterministic", temperature=0.0,
            prompt="(no prompt — rules are deterministic predicates over Tier-A facts)",
            tools=["release_snapshot"], build_hours=0.0,
        )

    def run(
        self, snapshot: ReleaseSnapshot, manifest: list[ManifestItem],
        *, now: datetime | None = None,
    ) -> ArmResult:
        started = now or _now()
        verdicts = evaluate_release_readiness(snapshot, now=started)
        return ArmResult(
            arm="aria", config_hash=self.config.config_hash(),
            verdicts=reconcile(manifest, verdicts),
            audit_log=[AuditEntry(action="rules_evaluated",
                                  detail=f"{len(verdicts)} rules", at=started)],
            started_at=started, finished_at=now or _now(),
        )


_BASELINE_PROMPT_HEADER = """You are a release-readiness reviewer. Decide whether a \
release is ready to ship, using ONLY the facts supplied below.

For EVERY checklist item return exactly one verdict:
  supported    - the check is satisfied, and the supplied facts show it
  unsatisfied  - the check is not satisfied
  abstained    - you cannot tell from the supplied facts; say so rather than guessing

Abstain when required evidence is absent, stale (older than the item's freshness \
window), conflicting between sources, or not authorized for you to read. Guessing on \
missing evidence is worse than abstaining.

Policy notes: a change needs at least two approvals from people other than the author, \
including at least one CODEOWNER; retracted approvals do not count. Required CI checks \
must have passed on the exact release commit and be fresh. A rollback path must exist. \
Blocking incidents are SEV1/SEV2 open against a touched service.

Return ONLY a JSON object:
{"verdicts": [{"manifest_item_id": "...", "verdict": "...",
               "cited_policy_rule_id": "...", "abstention_reason": "..."}]}
"""


class BaselineArm:
    """Arm B — a competent agent with the same facts and no proof layer."""

    def __init__(self, model: Any, *, config: ArmConfig | None = None) -> None:
        self._model = model
        self.config = config or ArmConfig(
            arm="baseline", framework="langchain-chat-model",
            model=getattr(model, "model", "local"), temperature=0.0,
            prompt=_BASELINE_PROMPT_HEADER,
            tools=["release_snapshot"], build_hours=4.0,
        )

    def _prompt(self, snapshot: ReleaseSnapshot, manifest: list[ManifestItem]) -> str:
        checklist = "\n".join(
            f"  {item.manifest_item_id} [{item.materiality.value}] {item.claim_text}"
            f" (source: {item.authoritative_source}"
            + (f", freshness {item.freshness_window_hours}h)" if item.freshness_window_hours
               else ")")
            for item in manifest
        )
        facts = snapshot.model_dump_json(indent=2)
        return (
            f"{_BASELINE_PROMPT_HEADER}\nCHECKLIST:\n{checklist}\n\nFACTS:\n{facts}\n"
        )

    def run(
        self, snapshot: ReleaseSnapshot, manifest: list[ManifestItem],
        *, now: datetime | None = None,
    ) -> ArmResult:
        started = now or _now()
        audit = [AuditEntry(action="read_release_snapshot",
                            detail=snapshot.release_ref, at=started)]
        prompt = self._prompt(snapshot, manifest)
        verdicts: list[ClaimVerdict] = []
        try:
            from langchain_core.messages import HumanMessage

            response = self._model.invoke([HumanMessage(content=prompt)])
            audit.append(AuditEntry(action="model_invoked",
                                    detail=self.config.model, at=_now()))
            verdicts = self._parse(
                getattr(response, "content", ""), manifest, audit,
                self._snapshot_evidence(snapshot, started))
        except Exception as exc:  # class only — never echo model text
            audit.append(AuditEntry(action="model_invocation_failed",
                                    detail=type(exc).__name__, at=_now()))
        return ArmResult(
            arm="baseline", config_hash=self.config.config_hash(),
            verdicts=reconcile(manifest, verdicts),
            audit_log=audit, started_at=started, finished_at=now or _now(),
        )

    @staticmethod
    def _snapshot_evidence(snapshot: ReleaseSnapshot, now: datetime) -> EvidenceRef:
        """The baseline's citation: the whole snapshot it was handed.

        This is deliberately *truthful rather than flattering to ARIA*. The baseline
        genuinely read this payload, so it genuinely may cite it. Denying it any
        citation would make ``supported`` structurally unreachable for Arm B and turn
        the benchmark into a rigged comparison.

        The measurable difference between arms is therefore evidence **precision**:
        ARIA binds each claim to the specific facts that decided it, while the
        baseline can only point at the blob. That is a real quality gap the metrics
        can detect — not an artificial disqualification.
        """
        return EvidenceRef(
            source="release_snapshot",
            content_hash=content_hash(snapshot.model_dump_json().encode("utf-8")),
            observed_at=snapshot.decision_time or now,
            locator=snapshot.release_ref,
        )

    @staticmethod
    def _parse(
        raw: Any, manifest: list[ManifestItem], audit: list[AuditEntry],
        snapshot_evidence: EvidenceRef,
    ) -> list[ClaimVerdict]:
        """Decode verdicts, discarding anything invalid.

        Discarded items are NOT silently lost: reconciliation records them as
        ``omitted``, exactly as it does for ARIA.
        """
        from aria.skills.json_output import parse_json_object

        known = {item.manifest_item_id: item for item in manifest}
        seen: set[str] = set()
        try:
            payload = parse_json_object(raw if isinstance(raw, str) else "")
        except ValueError as exc:
            audit.append(AuditEntry(action="model_output_unparseable",
                                    detail=type(exc).__name__, at=_now()))
            return []
        parsed: list[ClaimVerdict] = []
        for entry in payload.get("verdicts", [])[:len(manifest)]:
            if not isinstance(entry, dict):
                continue
            item = known.get(str(entry.get("manifest_item_id", "")))
            if item is None:
                continue
            if item.manifest_item_id in seen:
                # A model repeating an item must fail safely. Passing duplicates to
                # reconcile() would raise and abort the whole benchmark run, turning a
                # model quirk into a lost measurement.
                audit.append(AuditEntry(action="duplicate_verdict_discarded",
                                        detail=item.manifest_item_id, at=_now()))
                continue
            seen.add(item.manifest_item_id)
            reason = entry.get("abstention_reason")
            cited = entry.get("cited_policy_rule_id")
            try:
                parsed.append(ClaimVerdict(
                    manifest_item_id=item.manifest_item_id,
                    verdict=Verdict(str(entry.get("verdict", ""))),
                    cited_policy_rule_id=str(cited).strip() if cited else None,
                    evidence_refs=[snapshot_evidence],
                    abstention_reason=EvidenceState(reason) if reason else None,
                ))
            except (ValueError, TypeError):
                # Invalid shape (including a self-reported 'omitted') is dropped;
                # reconciliation will record the omission.
                audit.append(AuditEntry(action="verdict_discarded",
                                        detail=item.manifest_item_id, at=_now()))
        return parsed


__all__ = [
    "AriaArm",
    "ArmConfig",
    "ArmResult",
    "AuditEntry",
    "BaselineArm",
    "release_manifest",
]
