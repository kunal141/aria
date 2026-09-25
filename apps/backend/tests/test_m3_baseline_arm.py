"""
M3 — Baseline arm: adversarial tests, written before implementation.

The benchmark is worthless if Arm B is a strawman, and a strawman is the *easy*
mistake to make because it flatters the result. So the tests here mostly defend the
baseline's competence rather than ARIA's:

  - the baseline gets the same facts, the same manifest, and the same vocabulary;
  - its prompt must address every manifest item and must permit abstention;
  - its configuration is hashed, so post-hoc tuning is detectable;
  - it is never allowed to answer fewer items than ARIA — reconciliation applies
    to both arms identically.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aria.proof import Verdict

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def _snapshot(**over):
    from aria.roles.release_readiness import Approval, CheckRun, ReleaseSnapshot

    payload = {
        "release_ref": "rel-0042",
        "merge_commit_sha": "sha-merge",
        "author_id": "author-1",
        "approvals": [
            Approval(approver="reviewer-a", state="approved", is_codeowner=True,
                     timestamp=NOW - timedelta(hours=2)),
            Approval(approver="reviewer-b", state="approved",
                     timestamp=NOW - timedelta(hours=2)),
        ],
        "required_check_names": ["build", "test"],
        "check_runs": [
            CheckRun(name="build", commit_sha="sha-merge", conclusion="success",
                     completed_at=NOW - timedelta(hours=1)),
            CheckRun(name="test", commit_sha="sha-merge", conclusion="success",
                     completed_at=NOW - timedelta(hours=1)),
        ],
        "rollback_plan_ref": "doc://rollback/rel-0042",
        "release_ticket_id": "REL-77",
        "affected_services": ["payments"],
        "incident_feed_observed_at": NOW - timedelta(minutes=10),
        "advisory_db_observed_at": NOW - timedelta(hours=2),
        "decision_time": NOW,
    }
    payload.update(over)
    return ReleaseSnapshot(**payload)


class _StubModel:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def invoke(self, messages):
        self.prompts.append(str(messages))
        return type("AIMessage", (), {"content": self.reply})()


def _all_supported_reply() -> str:
    items = ", ".join(
        f'{{"manifest_item_id": "{rule}", "verdict": "supported", '
        f'"cited_policy_rule_id": "{rule}"}}'
        for rule in ("RR-001", "RR-002", "RR-003", "RR-004", "RR-005", "RR-006")
    )
    return f'{{"verdicts": [{items}]}}'


# ── Fairness: identical inputs and vocabulary ─────────────────────────────────


class TestArmParity:
    def test_both_arms_answer_the_same_manifest(self):
        from aria.benchmark import AriaArm, BaselineArm, release_manifest

        manifest = release_manifest()
        snapshot = _snapshot()
        aria_result = AriaArm().run(snapshot, manifest, now=NOW)
        baseline_result = BaselineArm(_StubModel(_all_supported_reply())).run(
            snapshot, manifest, now=NOW)
        assert [v.manifest_item_id for v in aria_result.verdicts] == \
               [v.manifest_item_id for v in baseline_result.verdicts]

    def test_both_arms_use_the_same_verdict_vocabulary(self):
        from aria.benchmark import AriaArm, BaselineArm, release_manifest

        manifest = release_manifest()
        for result in (
            AriaArm().run(_snapshot(), manifest, now=NOW),
            BaselineArm(_StubModel(_all_supported_reply())).run(
                _snapshot(), manifest, now=NOW),
        ):
            for verdict in result.verdicts:
                assert isinstance(verdict.verdict, Verdict)

    def test_baseline_receives_the_same_facts(self):
        from aria.benchmark import BaselineArm, release_manifest

        model = _StubModel(_all_supported_reply())
        BaselineArm(model).run(_snapshot(), release_manifest(), now=NOW)
        prompt = model.prompts[0]
        for fact in ("reviewer-a", "sha-merge", "REL-77", "payments"):
            assert fact in prompt, f"baseline was denied access to {fact}"


# ── Anti-strawman: the baseline must be genuinely competent ───────────────────


class TestBaselineIsNotAStrawman:
    def test_prompt_addresses_every_manifest_item(self):
        from aria.benchmark import BaselineArm, release_manifest

        model = _StubModel(_all_supported_reply())
        BaselineArm(model).run(_snapshot(), release_manifest(), now=NOW)
        prompt = model.prompts[0]
        for item in release_manifest():
            assert item.manifest_item_id in prompt

    def test_prompt_permits_abstention(self):
        """A baseline forbidden from saying 'I don't know' would be rigged."""
        from aria.benchmark import BaselineArm, release_manifest

        model = _StubModel(_all_supported_reply())
        BaselineArm(model).run(_snapshot(), release_manifest(), now=NOW)
        assert "abstain" in model.prompts[0].lower()

    def test_prompt_states_the_freshness_and_approval_policy(self):
        from aria.benchmark import BaselineArm, release_manifest

        model = _StubModel(_all_supported_reply())
        BaselineArm(model).run(_snapshot(), release_manifest(), now=NOW)
        prompt = model.prompts[0].lower()
        assert "codeowner" in prompt and "fresh" in prompt

    def test_baseline_can_reach_every_verdict_value(self):
        from aria.benchmark import BaselineArm, release_manifest

        reply = (
            '{"verdicts": ['
            '{"manifest_item_id": "RR-001", "verdict": "unsatisfied"},'
            '{"manifest_item_id": "RR-002", "verdict": "abstained",'
            ' "abstention_reason": "stale"},'
            '{"manifest_item_id": "RR-003", "verdict": "supported"}]}'
        )
        result = BaselineArm(_StubModel(reply)).run(
            _snapshot(), release_manifest(), now=NOW)
        verdicts = {v.manifest_item_id: v.verdict for v in result.verdicts}
        assert verdicts["RR-001"] is Verdict.unsatisfied
        assert verdicts["RR-002"] is Verdict.abstained
        assert verdicts["RR-003"] is Verdict.supported


# ── Configuration freezing: post-hoc tuning must be detectable ────────────────


class TestConfigFreezing:
    def test_config_hash_is_stable(self):
        from aria.benchmark import ArmConfig

        config = ArmConfig(arm="baseline", framework="langchain", model="m",
                           temperature=0.0, prompt="p", tools=["read"], build_hours=4.0)
        assert config.config_hash() == config.config_hash()

    def test_changing_the_prompt_changes_the_hash(self):
        from aria.benchmark import ArmConfig

        base = ArmConfig(arm="baseline", framework="langchain", model="m",
                         temperature=0.0, prompt="p", tools=["read"], build_hours=4.0)
        tuned = base.model_copy(update={"prompt": "p, but try harder"})
        assert base.config_hash() != tuned.config_hash()

    def test_result_records_the_config_hash_it_ran_under(self):
        from aria.benchmark import BaselineArm, release_manifest

        arm = BaselineArm(_StubModel(_all_supported_reply()))
        result = arm.run(_snapshot(), release_manifest(), now=NOW)
        assert result.config_hash == arm.config.config_hash()

    def test_build_hours_are_recorded_for_effort_parity_review(self):
        from aria.benchmark import BaselineArm

        assert BaselineArm(_StubModel("{}")).config.build_hours > 0


# ── Reconciliation applies identically to both arms ───────────────────────────


class TestReconciliationParity:
    def test_baseline_omission_is_recorded_not_dropped(self):
        from aria.benchmark import BaselineArm, release_manifest

        partial = ('{"verdicts": [{"manifest_item_id": "RR-001",'
                   ' "verdict": "supported", "cited_policy_rule_id": "RR-001"}]}')
        result = BaselineArm(_StubModel(partial)).run(
            _snapshot(), release_manifest(), now=NOW)
        omitted = [v.manifest_item_id for v in result.verdicts
                   if v.verdict is Verdict.omitted]
        assert "RR-002" in omitted
        assert len(result.verdicts) == len(release_manifest())

    def test_baseline_cannot_self_report_omitted(self):
        from aria.benchmark import BaselineArm, release_manifest

        sneaky = ('{"verdicts": [{"manifest_item_id": "RR-001",'
                  ' "verdict": "omitted"}]}')
        result = BaselineArm(_StubModel(sneaky)).run(
            _snapshot(), release_manifest(), now=NOW)
        rr1 = next(v for v in result.verdicts if v.manifest_item_id == "RR-001")
        # Discarded as invalid, then reconciled to omitted by the coordinator.
        assert rr1.verdict is Verdict.omitted
        assert rr1.origin == "reconciliation"

    def test_duplicate_verdicts_do_not_crash_the_arm(self):
        """A model repeating an item must fail safely, not abort the benchmark run."""
        from aria.benchmark import BaselineArm, release_manifest

        dup = ('{"verdicts": ['
               '{"manifest_item_id": "RR-001", "verdict": "supported"},'
               '{"manifest_item_id": "RR-001", "verdict": "unsatisfied"}]}')
        result = BaselineArm(_StubModel(dup)).run(
            _snapshot(), release_manifest(), now=NOW)
        assert len(result.verdicts) == len(release_manifest())
        rr1 = [v for v in result.verdicts if v.manifest_item_id == "RR-001"]
        assert len(rr1) == 1

    def test_unknown_item_from_baseline_is_ignored_not_fatal(self):
        from aria.benchmark import BaselineArm, release_manifest

        rogue = ('{"verdicts": [{"manifest_item_id": "RR-999",'
                 ' "verdict": "supported"}]}')
        result = BaselineArm(_StubModel(rogue)).run(
            _snapshot(), release_manifest(), now=NOW)
        assert all(v.manifest_item_id != "RR-999" for v in result.verdicts)

    def test_baseline_wrong_policy_citation_is_not_silently_corrected(self):
        from aria.benchmark import BaselineArm, release_manifest

        wrong = ('{"verdicts": [{"manifest_item_id": "RR-001",'
                 ' "verdict": "supported", "cited_policy_rule_id": "RR-999"}]}')
        result = BaselineArm(_StubModel(wrong)).run(
            _snapshot(), release_manifest(), now=NOW)
        rr1 = next(v for v in result.verdicts if v.manifest_item_id == "RR-001")
        assert rr1.verdict is Verdict.supported
        assert rr1.cited_policy_rule_id == "RR-999"


# ── Audit log + safe failure ──────────────────────────────────────────────────


class TestAuditAndFailure:
    def test_baseline_emits_an_audit_log(self):
        from aria.benchmark import BaselineArm, release_manifest

        result = BaselineArm(_StubModel(_all_supported_reply())).run(
            _snapshot(), release_manifest(), now=NOW)
        assert result.audit_log
        assert any("model" in entry.action for entry in result.audit_log)

    def test_malformed_reply_yields_all_omitted_not_a_crash(self):
        from aria.benchmark import BaselineArm, release_manifest

        result = BaselineArm(_StubModel("not json")).run(
            _snapshot(), release_manifest(), now=NOW)
        assert all(v.verdict is Verdict.omitted for v in result.verdicts)

    def test_raw_model_text_never_enters_the_audit_log(self):
        from aria.benchmark import BaselineArm, release_manifest

        leak = "token=SUPERSECRETVALUE123 and not json"
        result = BaselineArm(_StubModel(leak)).run(
            _snapshot(), release_manifest(), now=NOW)
        assert "SUPERSECRETVALUE123" not in result.model_dump_json()
