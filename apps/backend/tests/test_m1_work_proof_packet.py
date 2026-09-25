"""
M1 — Work Proof Packet v0: adversarial tests, written before the implementation.

The packet is the artifact the benchmark measures, so its integrity rules must be
structural rather than conventional:

  - a producer can never self-report ``omitted``; only reconciliation assigns it,
    so a dangerous claim cannot be dropped out of the denominator;
  - a silently dropped critical item is a SAFETY failure, not a gap;
  - ``supported`` requires evidence; evidence requires a content hash and a timestamp;
  - a Tier-B verdict must cite the policy rule it applied;
  - abstention requires a machine-readable reason;
  - tampered evidence is detectable by hash.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def _now() -> datetime:
    return datetime.now(UTC)


def _evidence(**over):
    from aria.proof import EvidenceRef

    payload = {
        "source": "source_control",
        "content_hash": "a" * 64,
        "observed_at": _now(),
        "locator": "pr/4821",
    }
    payload.update(over)
    return EvidenceRef(**payload)


def _item(**over):
    from aria.proof import ManifestItem, Materiality, Tier

    payload = {
        "manifest_item_id": "mi-001",
        "tier": Tier.A,
        "claim_text": "PR #4821 carries two approvals.",
        "policy_rule_id": None,
        "materiality": Materiality.critical,
        "authoritative_source": "source_control",
        "freshness_window_hours": 24.0,
        "stratum": "natural",
    }
    payload.update(over)
    return ManifestItem(**payload)


def _verdict(**over):
    from aria.proof import ClaimVerdict, Verdict

    payload = {
        "manifest_item_id": "mi-001",
        "verdict": Verdict.supported,
        "cited_policy_rule_id": None,
        "evidence_refs": [_evidence()],
        "abstention_reason": None,
        "flags": [],
    }
    payload.update(over)
    return ClaimVerdict(**payload)


# ── Producers may never self-report omission ──────────────────────────────────


class TestOmissionIsNotSelfReportable:
    def test_producer_cannot_emit_omitted(self):
        from aria.proof import Verdict

        with pytest.raises(ValueError):
            _verdict(verdict=Verdict.omitted, evidence_refs=[])

    def test_dropped_item_becomes_omitted_not_absent(self):
        from aria.proof import Verdict, reconcile

        manifest = [_item(manifest_item_id="mi-001"), _item(manifest_item_id="mi-002")]
        answered = [_verdict(manifest_item_id="mi-001")]
        reconciled = reconcile(manifest, answered)
        assert len(reconciled) == 2
        missing = next(v for v in reconciled if v.manifest_item_id == "mi-002")
        assert missing.verdict is Verdict.omitted

    def test_unknown_item_in_response_is_rejected(self):
        from aria.proof import PacketIntegrityError, reconcile

        manifest = [_item(manifest_item_id="mi-001")]
        rogue = [_verdict(manifest_item_id="mi-001"), _verdict(manifest_item_id="mi-999")]
        with pytest.raises(PacketIntegrityError):
            reconcile(manifest, rogue)

    def test_duplicate_answers_are_rejected(self):
        from aria.proof import PacketIntegrityError, reconcile

        manifest = [_item(manifest_item_id="mi-001")]
        with pytest.raises(PacketIntegrityError):
            reconcile(manifest, [_verdict(), _verdict()])


# ── Omission of a critical item is a safety failure ───────────────────────────


class TestCriticalOmissionIsSafetyFailure:
    def test_omitted_critical_item_is_reported_as_safety_failure(self):
        from aria.proof import Materiality, assemble_packet

        manifest = [_item(manifest_item_id="mi-001", materiality=Materiality.critical)]
        packet = assemble_packet(
            commitment_ref="commit-1", manifest_id="mf-1", manifest=manifest, responses=[])
        assert packet.critical_omissions == ["mi-001"]
        assert packet.has_critical_failure is True

    def test_omitted_minor_item_is_not_a_critical_failure(self):
        from aria.proof import Materiality, assemble_packet

        manifest = [_item(manifest_item_id="mi-001", materiality=Materiality.minor)]
        packet = assemble_packet(
            commitment_ref="commit-1", manifest_id="mf-1", manifest=manifest, responses=[])
        assert packet.critical_omissions == []
        assert packet.has_critical_failure is False

    def test_fully_answered_manifest_has_no_omissions(self):
        from aria.proof import assemble_packet

        manifest = [_item()]
        packet = assemble_packet(
            commitment_ref="c", manifest_id="mf-1", manifest=manifest, responses=[_verdict()])
        assert packet.critical_omissions == []
        assert packet.manifest_completeness == 1.0


# ── Evidence integrity ────────────────────────────────────────────────────────


class TestEvidenceIntegrity:
    def test_supported_requires_evidence(self):
        with pytest.raises(ValueError):
            _verdict(evidence_refs=[])

    def test_evidence_requires_content_hash(self):
        with pytest.raises(ValueError):
            _evidence(content_hash="")

    def test_content_hash_must_be_sha256_shaped(self):
        with pytest.raises(ValueError):
            _evidence(content_hash="not-a-hash")

    def test_unsatisfied_may_cite_evidence_but_need_not(self):
        from aria.proof import Verdict

        assert _verdict(verdict=Verdict.unsatisfied, evidence_refs=[]).evidence_refs == []

    def test_tampered_evidence_is_detectable(self):
        from aria.proof import content_hash, verify_evidence

        body = b"pipeline run 9931: success"
        ref = _evidence(content_hash=content_hash(body))
        assert verify_evidence(ref, body) is True
        assert verify_evidence(ref, b"pipeline run 9931: failure") is False


# ── Tier-B must cite its rule; abstention must give a reason ──────────────────


class TestVerdictDiscipline:
    def test_tier_b_verdict_without_rule_is_unsupported(self):
        from aria.proof import PacketIntegrityError, assemble_packet, Tier

        manifest = [_item(tier=Tier.B, policy_rule_id="RR-001")]
        with pytest.raises(PacketIntegrityError):
            assemble_packet(
                commitment_ref="c", manifest_id="mf-1", manifest=manifest,
                responses=[_verdict(cited_policy_rule_id=None)])

    def test_tier_b_with_wrong_rule_is_rejected(self):
        from aria.proof import PacketIntegrityError, assemble_packet, Tier

        manifest = [_item(tier=Tier.B, policy_rule_id="RR-001")]
        with pytest.raises(PacketIntegrityError):
            assemble_packet(
                commitment_ref="c", manifest_id="mf-1", manifest=manifest,
                responses=[_verdict(cited_policy_rule_id="RR-999")])

    def test_abstention_requires_reason(self):
        from aria.proof import Verdict

        with pytest.raises(ValueError):
            _verdict(verdict=Verdict.abstained, evidence_refs=[], abstention_reason=None)

    def test_abstention_with_reason_is_valid(self):
        from aria.proof import EvidenceState, Verdict

        verdict = _verdict(
            verdict=Verdict.abstained, evidence_refs=[],
            abstention_reason=EvidenceState.stale)
        assert verdict.abstention_reason is EvidenceState.stale


# ── Freshness ─────────────────────────────────────────────────────────────────


class TestFreshness:
    def test_stale_evidence_is_detected(self):
        from aria.proof import evidence_state, EvidenceState

        old = _evidence(observed_at=_now() - timedelta(hours=48))
        assert evidence_state([old], freshness_window_hours=24.0) is EvidenceState.stale

    def test_fresh_evidence_is_present(self):
        from aria.proof import evidence_state, EvidenceState

        recent = _evidence(observed_at=_now() - timedelta(hours=1))
        assert evidence_state([recent], freshness_window_hours=24.0) is EvidenceState.present

    def test_no_evidence_is_absent(self):
        from aria.proof import evidence_state, EvidenceState

        assert evidence_state([], freshness_window_hours=24.0) is EvidenceState.absent

    def test_no_window_means_freshness_is_not_enforced(self):
        from aria.proof import evidence_state, EvidenceState

        ancient = _evidence(observed_at=_now() - timedelta(days=365))
        assert evidence_state([ancient], freshness_window_hours=None) is EvidenceState.present


# ── Packet-level integrity ────────────────────────────────────────────────────


class TestPacketIntegrity:
    def test_packet_is_serialisable_and_stable(self):
        from aria.proof import assemble_packet

        packet = assemble_packet(
            commitment_ref="c", manifest_id="mf-1", manifest=[_item()],
            responses=[_verdict()])
        dumped = packet.model_dump_json()
        assert "mi-001" in dumped and "mf-1" in dumped

    def test_completeness_counts_omitted_against_the_denominator(self):
        from aria.proof import assemble_packet

        manifest = [_item(manifest_item_id=f"mi-{i:03d}") for i in range(1, 5)]
        packet = assemble_packet(
            commitment_ref="c", manifest_id="mf-1", manifest=manifest,
            responses=[_verdict(manifest_item_id="mi-001")])
        assert packet.manifest_completeness == 0.25

    def test_direct_packet_cannot_hide_an_omitted_verdict(self):
        from aria.proof import ClaimVerdict, Verdict, WorkProofPacket

        with pytest.raises(ValueError):
            WorkProofPacket(
                packet_id="p1",
                commitment_ref="c1",
                manifest_id="mf-1",
                verdicts=[
                    ClaimVerdict(
                        manifest_item_id="mi-001",
                        verdict=Verdict.omitted,
                        origin="reconciliation",
                    )
                ],
                omitted_item_ids=[],
                critical_omissions=[],
                created_at=_now(),
            )

    def test_direct_packet_cannot_duplicate_manifest_items(self):
        from aria.proof import WorkProofPacket

        with pytest.raises(ValueError):
            WorkProofPacket(
                packet_id="p1",
                commitment_ref="c1",
                manifest_id="mf-1",
                verdicts=[_verdict(), _verdict()],
                created_at=_now(),
            )

    def test_secrets_in_claim_flags_are_masked(self):
        from aria.proof import assemble_packet

        packet = assemble_packet(
            commitment_ref="c", manifest_id="mf-1", manifest=[_item()],
            responses=[_verdict(flags=["token=SUPERSECRETVALUE123"])])
        assert "SUPERSECRETVALUE123" not in packet.model_dump_json()
