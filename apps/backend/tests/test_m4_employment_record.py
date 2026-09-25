"""
M4 — persistent employee identity and the employment record.

The audit finding this closes: agents were created with ``uuid4()`` per goal and every
store read was scoped ``WHERE goal_id=?``, so "the Data Freshness Agent" was destroyed
after every task. You cannot review an employee that does not survive its own work,
and without a record there is nothing for earned authority to be earned *from*.

Properties pinned here:

  - an employee id is stable across runs and restarts;
  - the record aggregates real outcomes, not injected counters;
  - the record is derived, so it cannot drift from the underlying attempts;
  - lifecycle is explicit: hire -> active -> restricted/retired;
  - a retired employee cannot be assigned new work;
  - records are tenant-scoped and never leak across tenants.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _store(tmp_path: Path, name: str = "default"):
    from aria.employee.registry import EmployeeRegistry

    return EmployeeRegistry(db_path=tmp_path / "aria_data" / name / "employees.sqlite")


def _hire(store, key="release-readiness", **over):
    payload = {
        "role_key": key,
        "display_name": "Release Readiness Coordinator",
        "human_sponsor": "human:kunal",
        "department": "engineering",
    }
    payload.update(over)
    return store.hire(**payload)


# ── Identity survives ─────────────────────────────────────────────────────────


class TestPersistentIdentity:
    def test_hire_returns_a_stable_id(self, tmp_path):
        store = _store(tmp_path)
        employee = _hire(store)
        assert employee.employee_id
        assert store.get(employee.employee_id).employee_id == employee.employee_id

    def test_identity_survives_restart(self, tmp_path):
        first = _store(tmp_path)
        employee = _hire(first)
        first.close()

        second = _store(tmp_path)
        assert second.get(employee.employee_id).display_name == employee.display_name
        second.close()

    def test_rehiring_the_same_role_key_is_rejected(self, tmp_path):
        from aria.employee.registry import EmployeeAlreadyHired

        store = _store(tmp_path)
        _hire(store)
        with pytest.raises(EmployeeAlreadyHired):
            _hire(store)

    def test_unknown_employee_raises(self, tmp_path):
        from aria.employee.registry import EmployeeNotFound

        with pytest.raises(EmployeeNotFound):
            _store(tmp_path).get("emp-does-not-exist")


# ── Lifecycle ─────────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_new_hire_starts_on_probation_at_the_lowest_tier(self, tmp_path):
        from aria.employee.registry import EmploymentStatus

        employee = _hire(_store(tmp_path))
        assert employee.status is EmploymentStatus.probation
        assert employee.authority_tier == 1

    def test_retired_employee_cannot_take_new_work(self, tmp_path):
        from aria.employee.registry import EmploymentStatus

        store = _store(tmp_path)
        employee = _hire(store)
        store.set_status(employee.employee_id, EmploymentStatus.retired,
                         actor="human:kunal", reason="role closed")
        assert store.get(employee.employee_id).can_accept_work is False

    def test_restricted_employee_cannot_take_new_work(self, tmp_path):
        from aria.employee.registry import EmploymentStatus

        store = _store(tmp_path)
        employee = _hire(store)
        store.set_status(employee.employee_id, EmploymentStatus.restricted,
                         actor="human:kunal", reason="quality regression")
        assert store.get(employee.employee_id).can_accept_work is False

    def test_active_employee_can_take_work(self, tmp_path):
        from aria.employee.registry import EmploymentStatus

        store = _store(tmp_path)
        employee = _hire(store)
        store.set_status(employee.employee_id, EmploymentStatus.active,
                         actor="human:kunal", reason="probation passed")
        assert store.get(employee.employee_id).can_accept_work is True

    def test_status_changes_are_recorded_with_actor_and_reason(self, tmp_path):
        from aria.employee.registry import EmploymentStatus

        store = _store(tmp_path)
        employee = _hire(store)
        store.set_status(employee.employee_id, EmploymentStatus.active,
                         actor="human:kunal", reason="probation passed")
        history = store.status_history(employee.employee_id)
        assert history[-1].actor == "human:kunal"
        assert history[-1].reason == "probation passed"


# ── The record is derived from real outcomes ──────────────────────────────────


class TestEmploymentRecord:
    def _with_outcomes(self, tmp_path):
        store = _store(tmp_path)
        employee = _hire(store)
        eid = employee.employee_id
        store.record_outcome(eid, run_id="r1", passed=True, corrected=False,
                             escalated=False, cost=0.10, latency_ms=900)
        store.record_outcome(eid, run_id="r2", passed=False, corrected=True,
                             escalated=False, cost=0.20, latency_ms=1_100)
        store.record_outcome(eid, run_id="r3", passed=True, corrected=False,
                             escalated=True, cost=0.30, latency_ms=700)
        return store, eid

    def test_record_aggregates_real_outcomes(self, tmp_path):
        store, eid = self._with_outcomes(tmp_path)
        record = store.employment_record(eid)
        assert record.total_runs == 3
        assert record.passed_runs == 2
        assert round(record.quality_pass_rate, 4) == round(2 / 3, 4)
        assert record.correction_count == 1
        assert record.escalation_count == 1

    def test_costs_and_latency_are_summarised(self, tmp_path):
        store, eid = self._with_outcomes(tmp_path)
        record = store.employment_record(eid)
        assert round(record.total_cost, 2) == 0.60
        assert record.median_latency_ms == 900

    def test_record_is_derived_not_stored(self, tmp_path):
        """Recomputed from outcomes, so it cannot drift from the underlying work."""
        store, eid = self._with_outcomes(tmp_path)
        before = store.employment_record(eid).quality_pass_rate
        store.record_outcome(eid, run_id="r4", passed=False, corrected=False,
                             escalated=False, cost=0.0, latency_ms=100)
        assert store.employment_record(eid).quality_pass_rate < before

    def test_empty_record_reports_no_data_rather_than_zero_quality(self, tmp_path):
        store = _store(tmp_path)
        record = store.employment_record(_hire(store).employee_id)
        assert record.total_runs == 0
        assert record.quality_pass_rate is None

    def test_duplicate_run_outcome_is_idempotent(self, tmp_path):
        store = _store(tmp_path)
        eid = _hire(store).employee_id
        for _ in range(2):
            store.record_outcome(eid, run_id="r1", passed=True, corrected=False,
                                 escalated=False, cost=0.1, latency_ms=100)
        assert store.employment_record(eid).total_runs == 1

    def test_window_limits_the_record_to_recent_work(self, tmp_path):
        store, eid = self._with_outcomes(tmp_path)
        assert store.employment_record(eid, last_n=2).total_runs == 2


# ── Isolation and safety ──────────────────────────────────────────────────────


class TestIsolationAndSafety:
    def test_two_tenants_do_not_share_employees(self, tmp_path):
        from aria.employee.registry import EmployeeNotFound

        alpha = _store(tmp_path, "alpha")
        beta = _store(tmp_path, "beta")
        employee = _hire(alpha)
        with pytest.raises(EmployeeNotFound):
            beta.get(employee.employee_id)

    def test_registry_db_path_must_stay_under_aria_data_dir(self, tmp_path):
        from aria.employee.registry import EmployeeRegistry
        from aria.memory_v2.paths import PathConfinementError

        with pytest.raises(PathConfinementError):
            EmployeeRegistry(db_path=tmp_path / "outside.sqlite")

    def test_credential_shaped_sponsor_is_rejected(self, tmp_path):
        store = _store(tmp_path)
        with pytest.raises(ValueError):
            _hire(store, human_sponsor="sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA")

    def test_reason_text_is_sanitised(self, tmp_path):
        from aria.employee.registry import EmploymentStatus

        store = _store(tmp_path)
        eid = _hire(store).employee_id
        store.set_status(eid, EmploymentStatus.restricted, actor="human:k",
                         reason="leaked token=SUPERSECRETVALUE123")
        assert "SUPERSECRETVALUE123" not in store.status_history(eid)[-1].reason

    def test_outcome_for_unknown_employee_is_rejected(self, tmp_path):
        from aria.employee.registry import EmployeeNotFound

        with pytest.raises(EmployeeNotFound):
            _store(tmp_path).record_outcome(
                "emp-nope", run_id="r1", passed=True, corrected=False,
                escalated=False, cost=0.0, latency_ms=0)
