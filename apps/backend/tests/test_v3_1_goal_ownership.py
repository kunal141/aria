"""
V3.1 — Goal Ownership Foundation tests.

Covers the deterministic goal intake engine, roadmap planner, SQLite task board,
workspace integration, Work Ledger planning events, runtime isolation, and the V3
API. PLANNING ONLY — nothing here executes a tool or writes externally.

Isolation: the autouse conftest fixtures redirect ``ARIA_DATA_DIR`` and
``ARIA_LEDGER_V2_PATH`` to a per-test ``tmp_path``, so the goal SQLite store and
the Work Ledger never touch real runtime files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from datetime import UTC, datetime

from aria.goals import (
    GoalService,
    GoalStore,
    GoalStatus,
    OwnerType,
    TaskStatus,
    build_roadmap,
    run_intake,
)
from aria.goals.models import GoalIntake
from aria.goals.store import GoalNotFound
from aria.ledger import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import PathConfinementError, aria_data_dir, goals_db_path
from aria.memory_v2.workspace import WorkspaceStore

_CTR_REQUEST = "Our notification CTR is dropping. Own this."
_QUALITY_REQUEST = "Turn this problem into tasks: daily horoscope language quality is inconsistent"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> LedgerWriter:
    return LedgerWriter(tmp_path / "v3_ledger.jsonl")


@pytest.fixture
def service(writer: LedgerWriter):
    """A GoalService wired to an injected ledger writer + workspace, default
    (isolated) ARIA_DATA_DIR SQLite store."""
    store = GoalStore(writer=writer, execution_mode="offline_mock")
    ws = WorkspaceStore(writer=writer, execution_mode="offline_mock")
    return GoalService(store, workspace_store=ws, execution_mode="offline_mock", actor="human:test")


def _event_types(writer: LedgerWriter) -> list[str]:
    if not writer.path.exists():
        return []
    return [json.loads(l)["event_type"] for l in writer.path.read_text(encoding="utf-8").splitlines()]


# ── 1. Goal intake ────────────────────────────────────────────────────────────


class TestGoalIntake:
    def test_vague_request_creates_structured_problem_statement(self):
        intake = run_intake(_CTR_REQUEST, scope="analytics.notifications")
        assert intake.goal_id.startswith("goal-")
        assert intake.problem_statement.strip()
        assert intake.goal.strip()
        assert intake.title.strip()
        assert intake.status is GoalStatus.intake

    def test_missing_context_produces_clarifying_questions(self):
        intake = run_intake(_CTR_REQUEST)
        assert intake.clarifying_questions, "expected clarifying questions for a vague request"
        assert intake.missing_context, "expected missing-context items"
        # The baseline value must be ASKED for, never assumed.
        assert any("baseline" in m.lower() for m in intake.missing_context)

    def test_success_criteria_generated_with_governance_criterion(self):
        intake = run_intake(_CTR_REQUEST)
        assert intake.success_criteria
        assert "no production writes performed" in intake.success_criteria

    def test_no_unsupported_metrics_hallucinated(self):
        intake = run_intake(_CTR_REQUEST)
        blob = " ".join(
            intake.success_criteria + intake.known_context + [intake.problem_statement, intake.goal]
        )
        # No fabricated numeric metric (e.g. "12%", "baseline 4.5") anywhere — the
        # engine asks for numbers as evidence, it never invents them.
        assert not re.search(r"\d+(\.\d+)?\s*%", blob), f"hallucinated a percentage: {blob!r}"
        assert not re.search(r"\bbaseline\s+\d", blob.lower()), "asserted a baseline value"

    def test_memory_definitions_do_not_become_factual_evidence(self):
        # Intake is a pure, memory-free planner: a request that names a table/field
        # still produces an *evidence-required* plan, never asserted counts. Even if
        # memory could define what a field means, the plan demands evidence.
        intake = run_intake("In story_events, notification_open rate is dropping. Own it.",
                            scope="analytics.events")
        roadmap = build_roadmap(intake)
        all_evidence = [e for p in roadmap.phases for e in p.evidence_needed]
        assert all_evidence, "a metric goal must require evidence to be gathered"
        assert any("evidence" in c.lower() for c in intake.success_criteria)
        # No asserted count slipped into the plan.
        assert not re.search(r"\d+(\.\d+)?\s*%", " ".join(intake.success_criteria))


# ── 2. Roadmap ────────────────────────────────────────────────────────────────


class TestRoadmap:
    def test_phases_evidence_deliverables_risks_generated_and_linked(self):
        intake = run_intake(_CTR_REQUEST)
        roadmap = build_roadmap(intake)
        assert roadmap.goal_id == intake.goal_id           # linked to goal
        assert len(roadmap.phases) >= 5                     # phases generated
        assert all(p.order >= 1 and p.name and p.objective for p in roadmap.phases)
        assert roadmap.evidence_needed                      # evidence listed
        assert roadmap.deliverables                         # deliverables listed
        assert roadmap.risks                                # risks listed


# ── 3. Task board ─────────────────────────────────────────────────────────────


class TestTaskBoard:
    def test_tasks_generated_from_roadmap(self, service: GoalService):
        plan = service.own_goal(_CTR_REQUEST, scope="analytics.notifications")
        assert len(plan.tasks) == len(plan.roadmap.phases) + 1   # one per phase + approval gate
        assert all(t.goal_id == plan.goal.goal_id for t in plan.tasks)
        assert all(t.roadmap_id == plan.roadmap.roadmap_id for t in plan.tasks)
        assert plan.goal.status is GoalStatus.planned

    def test_task_status_updates_correctly(self, service: GoalService):
        plan = service.own_goal(_CTR_REQUEST)
        t0 = plan.tasks[0]
        upd = service.update_task_status(t0.task_id, TaskStatus.in_progress)
        assert upd.status is TaskStatus.in_progress
        done = service.update_task_status(t0.task_id, "completed")
        assert done.status is TaskStatus.completed

    def test_blocked_task_records_blocked_by(self, service: GoalService):
        plan = service.own_goal(_CTR_REQUEST)
        t0 = plan.tasks[0]
        blocked = service.update_task_status(t0.task_id, TaskStatus.blocked,
                                            blocked_by=["awaiting data source"])
        assert blocked.status is TaskStatus.blocked
        assert blocked.blocked_by == ["awaiting data source"]

    def test_approval_required_task_present(self, service: GoalService):
        plan = service.own_goal(_CTR_REQUEST)
        approval_tasks = [t for t in plan.tasks if t.approval_required]
        assert len(approval_tasks) == 1
        assert approval_tasks[0].owner_type is OwnerType.human

    def test_progress_summary(self, service: GoalService):
        plan = service.own_goal(_CTR_REQUEST)
        total = len(plan.tasks)
        service.update_task_status(plan.tasks[0].task_id, TaskStatus.completed)
        progress = service.get_progress(plan.goal.goal_id)
        assert progress.total_tasks == total
        assert progress.completed_tasks == 1
        assert progress.pending_tasks == total - 1
        assert progress.next_action is not None      # still work to do

    def test_restart_survival(self, tmp_path: Path, writer: LedgerWriter):
        db = aria_data_dir() / "goals" / "store.sqlite"   # under isolated ARIA_DATA_DIR
        store = GoalStore(db_path=db, writer=writer, execution_mode="offline_mock")
        svc = GoalService(store, execution_mode="offline_mock")
        plan = svc.own_goal(_CTR_REQUEST)
        gid = plan.goal.goal_id
        store.close()
        # Fresh store, same DB file → goal + tasks survive a "restart".
        store2 = GoalStore(db_path=db, writer=writer, execution_mode="offline_mock")
        assert store2.get_goal(gid) is not None
        assert len(store2.get_tasks(gid)) == len(plan.tasks)


# ── 4. Persistence / isolation ────────────────────────────────────────────────


class TestPersistenceIsolation:
    def test_sqlite_path_under_aria_data_dir(self):
        store = GoalStore()
        assert str(store.db_path).startswith(str(aria_data_dir()))
        assert "goals" in store.db_path.parts

    def test_no_import_time_db_creation(self):
        # Constructing the store must NOT create the DB; only a method call does.
        assert not goals_db_path().exists()
        store = GoalStore()
        assert not store.db_path.exists()
        store.create_goal(run_intake(_CTR_REQUEST))
        assert store.db_path.exists()

    def test_no_runtime_writes_into_source_package(self, service: GoalService):
        service.own_goal(_CTR_REQUEST)
        backend = Path(__file__).resolve().parents[1]           # apps/backend
        source_pkg = backend / "aria" / "goals"
        assert not list(source_pkg.glob("*.sqlite"))
        assert not (backend / ".aria_data").exists() or str(aria_data_dir()).startswith(
            str(Path(__file__).resolve().parents[1])) is False
        # The active data dir is the isolated tmp dir, never the source package.
        assert source_pkg not in aria_data_dir().parents

    def test_path_confinement_rejects_escape(self, tmp_path: Path):
        outside = tmp_path.parent / "escape" / "store.sqlite"
        with pytest.raises(PathConfinementError):
            GoalStore(db_path=outside)


# ── 5. Workspace + Work Ledger ────────────────────────────────────────────────


class TestWorkspaceAndLedger:
    def test_workspace_linked_to_goal(self, writer: LedgerWriter):
        store = GoalStore(writer=writer, execution_mode="offline_mock")
        ws = WorkspaceStore(writer=writer, execution_mode="offline_mock")
        svc = GoalService(store, workspace_store=ws, execution_mode="offline_mock")
        plan = svc.own_goal(_CTR_REQUEST)
        assert plan.workspace_id is not None
        assert plan.goal.workspace_id == plan.workspace_id
        wsrow = ws.get_workspace(plan.workspace_id)
        assert wsrow.correlation_id == plan.goal.goal_id
        assert wsrow.task_id == plan.goal.goal_id

    def test_roadmap_and_tasks_attached_to_workspace(self, service: GoalService):
        plan = service.own_goal(_CTR_REQUEST)
        ws = service._workspace_store.get_workspace(plan.workspace_id)
        assert len(ws.artifact_refs) == 2                       # goal_brief.md + roadmap.md
        assert f"goal:{plan.goal.goal_id}" in ws.ledger_refs
        assert f"roadmap:{plan.roadmap.roadmap_id}" in ws.ledger_refs
        assert any(r.startswith("task:") for r in ws.ledger_refs)
        assert len(ws.approval_refs) == 1                       # the approval-required task

    def test_planning_events_emitted(self, service: GoalService, writer: LedgerWriter):
        plan = service.own_goal(_CTR_REQUEST)
        service.update_task_status(plan.tasks[0].task_id, TaskStatus.in_progress)
        service.get_progress(plan.goal.goal_id, report=True)
        types = set(_event_types(writer))
        for expected in (
            "goal_created", "problem_statement_generated", "roadmap_created",
            "task_board_created", "task_status_updated", "goal_progress_reported",
            "workspace_created", "workspace_updated",
        ):
            assert expected in types, f"missing ledger event: {expected}"

    def test_no_pending_audit_after_flow(self, service: GoalService):
        service.own_goal(_CTR_REQUEST)
        # State + audit committed atomically and drained — nothing left queued.
        assert service._store.pending_audit_count() == 0
        assert service._workspace_store.pending_audit_count() == 0

    def test_legacy_ledger_compatibility_preserved(self, service: GoalService, writer: LedgerWriter):
        """Adding goal events must not break the unified reader. The v2 reader still
        validates the new events, and a legacy task file still surfaces alongside."""
        service.own_goal(_CTR_REQUEST)
        # Round-trip the v2 ledger through the reader (validates the union).
        v2_events = list(LedgerReader(v2_path=writer.path).v2_events())
        assert any(e.event_type.value == "goal_created" for e in v2_events)
        # A legacy task line still reads through the same reader.
        legacy = writer.path.parent / "legacy_task.jsonl"
        legacy.write_text(json.dumps({
            "task_id": "legacy-1", "task_type": "pr_review",
            "timestamp": "2026-01-01T00:00:00+00:00", "week": 8,
        }) + "\n", encoding="utf-8")
        records = LedgerReader(v2_path=writer.path, legacy_task_path=legacy).read_all()
        assert any(getattr(r, "task_id", None) == "legacy-1" for r in records)


# ── 6. V3 API ─────────────────────────────────────────────────────────────────


# ── 6b. Secret redaction (P1) ─────────────────────────────────────────────────


_SECRET_REQUEST = (
    "Own this: password=TOP_SECRET_TOKEN, key sk-ant-api03-ABCDEF1234567890abcdefXYZ, "
    "api_key=mykey12345secretval, Authorization: Bearer eyJhbGciOi.JeyJzdWIiOi.SflKxwRJ"
)
_SECRETS = [
    "TOP_SECRET_TOKEN", "sk-ant-api03-ABCDEF1234567890abcdefXYZ",
    "mykey12345secretval", "eyJhbGciOi.JeyJzdWIiOi.SflKxwRJ",
]


def _no_secret(text: str) -> bool:
    return not any(s in text for s in _SECRETS)


class TestSecretRedaction:
    def test_no_secret_in_runtime_surfaces(self, writer: LedgerWriter):
        from aria.memory_v2.paths import workspace_artifact_dir

        store = GoalStore(writer=writer, execution_mode="offline_mock")
        ws = WorkspaceStore(writer=writer, execution_mode="offline_mock")
        svc = GoalService(store, workspace_store=ws, execution_mode="offline_mock")
        plan = svc.own_goal(_SECRET_REQUEST, scope="analytics.notifications")

        # 1) returned goal
        assert _no_secret(plan.goal.model_dump_json())
        # 2) SQLite bytes
        assert _no_secret(store.db_path.read_bytes().decode("utf-8", "ignore"))
        # 3) workspace artifact bytes
        art_dir = workspace_artifact_dir(plan.workspace_id)
        art_blob = "".join(p.read_text(encoding="utf-8") for p in art_dir.glob("*"))
        assert _no_secret(art_blob)
        # 4) ledger JSONL
        assert _no_secret(writer.path.read_text(encoding="utf-8"))
        # the masking is surgical — the field is preserved, only the secret is gone
        assert "[REDACTED]" in plan.goal.raw_request

    def test_direct_store_create_goal_is_sanitized(self, writer: LedgerWriter):
        """A hand-built secret-bearing GoalIntake cannot bypass the persistence
        boundary — create_goal sanitises it regardless of how it was constructed."""
        now = datetime.now(UTC)
        dirty = GoalIntake(
            goal_id="goal-handbuilt", title="api_key=mykey12345secretval",
            raw_request="password=TOP_SECRET_TOKEN", problem_statement="leak sk-ant-api03-ABCDEF1234567890abcdefXYZ",
            goal="do the thing", success_criteria=["Authorization: Bearer eyJhbGciOi.JeyJzdWIiOi.SflKxwRJ"],
            known_context=["api_key=mykey12345secretval"], scope="general",
            created_at=now, updated_at=now,
        )
        store = GoalStore(writer=writer, execution_mode="offline_mock")
        stored = store.create_goal(dirty)
        assert _no_secret(stored.model_dump_json())
        # reload from SQLite — still clean
        assert _no_secret(store.get_goal("goal-handbuilt").model_dump_json())
        assert _no_secret(store.db_path.read_bytes().decode("utf-8", "ignore"))

    def test_each_credential_shape_is_covered(self):
        from aria.goals.sanitize import sanitize_text

        for secret, marker in [
            ("password=TOP_SECRET_TOKEN", "TOP_SECRET_TOKEN"),
            ("api_key=mykey12345secretval", "mykey12345secretval"),
            ("Bearer eyJhbGciOi.JeyJzdWIiOi.SflKxwRJ", "eyJhbGciOi.JeyJzdWIiOi.SflKxwRJ"),
            ("here is sk-ant-api03-ABCDEF1234567890abcdefXYZ", "sk-ant-api03-ABCDEF1234567890abcdefXYZ"),
        ]:
            out = sanitize_text(secret)
            assert marker not in out, f"{marker!r} not masked in {out!r}"
            assert "[REDACTED]" in out

    def test_normal_goal_text_remains_usable(self):
        from aria.goals.sanitize import sanitize_text

        intake = run_intake(_CTR_REQUEST)
        # No false-positive masking of ordinary planning text.
        assert "[REDACTED]" not in intake.raw_request
        assert "[REDACTED]" not in " ".join(intake.success_criteria)
        assert sanitize_text("Investigate the notification CTR drop on web") == \
            "Investigate the notification CTR drop on web"

    def test_api_response_has_no_secret(self):
        from fastapi.testclient import TestClient

        from aria.api.v3 import build_v3_app

        c = TestClient(build_v3_app())
        r = c.post("/api/v3/goals", json={"raw_request": _SECRET_REQUEST, "scope": "analytics.notifications"})
        assert r.status_code == 201
        assert _no_secret(r.text)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aria.api.v3 import build_v3_app

    return TestClient(build_v3_app())


class TestApi:
    def test_create_and_get_goal(self, client):
        r = client.post("/api/v3/goals", json={"raw_request": _CTR_REQUEST, "scope": "analytics.notifications"})
        assert r.status_code == 201
        body = r.json()
        gid = body["goal"]["goal_id"]
        assert body["roadmap"]["phases"]
        assert body["tasks"]
        got = client.get(f"/api/v3/goals/{gid}")
        assert got.status_code == 200
        assert got.json()["goal_id"] == gid

    def test_get_roadmap_tasks_progress(self, client):
        gid = client.post("/api/v3/goals", json={"raw_request": _CTR_REQUEST}).json()["goal"]["goal_id"]
        assert client.get(f"/api/v3/goals/{gid}/roadmap").status_code == 200
        tasks = client.get(f"/api/v3/goals/{gid}/tasks").json()
        assert tasks["count"] >= 1
        prog = client.get(f"/api/v3/goals/{gid}/progress").json()
        assert prog["total_tasks"] == tasks["count"]

    def test_patch_task_status(self, client):
        gid = client.post("/api/v3/goals", json={"raw_request": _CTR_REQUEST}).json()["goal"]["goal_id"]
        tid = client.get(f"/api/v3/goals/{gid}/tasks").json()["tasks"][0]["task_id"]
        r = client.patch(f"/api/v3/goals/{gid}/tasks/{tid}", json={"status": "in_progress"})
        assert r.status_code == 200
        assert r.json()["status"] == "in_progress"

    def test_list_goals(self, client):
        client.post("/api/v3/goals", json={"raw_request": _CTR_REQUEST, "scope": "s1"})
        client.post("/api/v3/goals", json={"raw_request": _QUALITY_REQUEST, "scope": "s2"})
        listed = client.get("/api/v3/goals").json()
        assert listed["count"] >= 2
        scoped = client.get("/api/v3/goals", params={"scope": "s1"}).json()
        assert scoped["count"] == 1

    def test_safe_errors(self, client):
        # invalid request → 400, never raw text
        bad = client.post("/api/v3/goals", json={"raw_request": "   "})
        assert bad.status_code == 422 or bad.status_code == 400  # pydantic min_length or builder guard
        # unknown goal → 404
        nf = client.get("/api/v3/goals/goal-missing")
        assert nf.status_code == 404 and nf.json()["error_code"] == "goal_not_found"
        # unknown task → 404 ; invalid status → 400
        gid = client.post("/api/v3/goals", json={"raw_request": _CTR_REQUEST}).json()["goal"]["goal_id"]
        tid = client.get(f"/api/v3/goals/{gid}/tasks").json()["tasks"][0]["task_id"]
        assert client.patch(f"/api/v3/goals/{gid}/tasks/taskitem-x", json={"status": "completed"}).status_code == 404
        assert client.patch(f"/api/v3/goals/{gid}/tasks/{tid}", json={"status": "nope"}).status_code == 400
