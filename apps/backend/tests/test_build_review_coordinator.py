from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import aria.braintrust.app as braintrust_app_module
from aria.braintrust.app import app
from aria.braintrust.build_review import (
    ApplyAcceptedRequest,
    BuildReviewControl,
    BuildReviewError,
    BuildReviewManager,
    BuildReviewRequest,
    BuildReviewSession,
    CancelBuildReviewRequest,
    FindingWaiverRequest,
    ReviewReport,
    WorkerInvocation,
    claude_reviewer_command,
    codex_builder_command,
)


class _FakeWriter:
    def write(self, _data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass


class _BlockingReader:
    async def readline(self) -> bytes:
        await asyncio.Future()
        return b""

    async def read(self) -> bytes:
        await asyncio.Future()
        return b""


class _BlockingProcess:
    def __init__(self) -> None:
        self.stdin = _FakeWriter()
        self.stdout = _BlockingReader()
        self.stderr = _BlockingReader()
        self.returncode: int | None = None
        self.terminated = False

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -1


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "ARIA Test")
    _git(repo, "config", "user.email", "aria-test@example.invalid")
    (repo / ".gitignore").write_text(".aria_build_review/\n", encoding="utf-8")
    (repo / "README.md").write_text("# Test repo\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "README.md")
    _git(repo, "commit", "-m", "baseline")
    return repo


def _request(*, max_rounds: int = 2, allowed_paths: list[str] | None = None) -> BuildReviewRequest:
    return BuildReviewRequest(
        title="Add a governed sample feature",
        objective="Implement a small sample feature without changing unrelated repository files.",
        acceptance_criteria=[
            "The sample returns a deterministic value.",
            "A focused regression test covers the behavior.",
        ],
        allowed_paths=allowed_paths or ["src/", "tests/"],
        validation_commands=["pytest tests/test_sample.py -q"],
        max_rounds=max_rounds,
    )


def _wait_for_session_status(
    client: TestClient,
    session_id: str,
    expected_status: str,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    delay = 0.02
    last_state: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/build-review/sessions/{session_id}")
        assert response.status_code == 200
        last_state = response.json()
        assert "approval_token" not in last_state
        if last_state["control"]["status"] == expected_status:  # type: ignore[index]
            return last_state
        time.sleep(delay)
        delay = min(delay * 1.5, 0.5)
    pytest.fail(f"session {session_id} did not reach {expected_status}; last={last_state}")


def _builder_report() -> dict[str, object]:
    return {
        "summary": "Implemented the sample and its focused test.",
        "files_changed": ["src/sample.py", "tests/test_sample.py"],
        "tests": [
            {
                "command": "pytest tests/test_sample.py -q",
                "status": "passed",
                "summary": "1 passed",
            }
        ],
        "limitations": [],
        "ready_for_review": True,
    }


def _accepted(invocation: WorkerInvocation) -> dict[str, object]:
    return {
        "verdict": "accepted",
        "reviewed_diff_sha256": invocation.diff_sha256,
        "summary": "The frozen revision satisfies the work order.",
        "findings": [],
        "tests_reviewed": [
            {
                "command": "pytest tests/test_sample.py -q",
                "status": "passed",
                "summary": "1 passed independently",
                "snapshot": "current",
            }
        ],
        "remaining_risks": [],
        "review_depth": "full",
        "self_authorship_disclosed": False,
        "next_actor": "human",
    }


class _AcceptingWorkers:
    def __init__(self) -> None:
        self.invocations: list[WorkerInvocation] = []

    async def __call__(self, invocation: WorkerInvocation) -> dict[str, object]:
        self.invocations.append(invocation)
        if invocation.actor == "codex":
            source = invocation.workspace / "src" / "sample.py"
            test = invocation.workspace / "tests" / "test_sample.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            test.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("def value() -> int:\n    return 42\n", encoding="utf-8")
            test.write_text(
                "from src.sample import value\n\ndef test_value():\n    assert value() == 42\n",
                encoding="utf-8",
            )
            return _builder_report()
        return _accepted(invocation)


@pytest.mark.asyncio
async def test_complete_loop_freezes_reviews_and_requires_human_apply(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workers = _AcceptingWorkers()
    manager = BuildReviewManager(
        repo=repo,
        runtime_root=repo / ".aria_build_review",
        worker_runner=workers,
    )

    session = await manager.create(_request())
    assert session.task is not None
    await session.task

    assert session.control.status == "accepted"
    assert session.control.next_actor == "human"
    assert session.control.diff_sha256
    assert session.control.review_depth == "full"
    assert not (repo / "src" / "sample.py").exists()
    patch = manager._patch_path(session.control.session_id, session.control.diff_sha256)
    assert patch.is_file()
    assert workers.invocations[1].actor == "claude"
    assert workers.invocations[1].previous_workspace is None

    await manager.apply_accepted(
        session.control.session_id,
        ApplyAcceptedRequest(
            confirmation="apply_accepted_patch",
            approval_token=session.approval_token,
        ),
    )
    assert session.control.status == "applied"
    assert (repo / "src" / "sample.py").read_text(encoding="utf-8").endswith("return 42\n")
    assert "src/sample.py" in _git(repo, "status", "--short", "--untracked-files=all")
    assert not _git(repo, "diff", "--cached", "--name-only")


class _FixingWorkers:
    def __init__(self) -> None:
        self.claude_rounds: list[WorkerInvocation] = []

    async def __call__(self, invocation: WorkerInvocation) -> dict[str, object]:
        if invocation.actor == "codex":
            source = invocation.workspace / "src" / "sample.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            value = "safe" if invocation.round == 2 else "unsafe"
            source.write_text(f'VALUE = "{value}"\n', encoding="utf-8")
            return {
                **_builder_report(),
                "files_changed": ["src/sample.py"],
            }
        self.claude_rounds.append(invocation)
        if invocation.round == 1:
            return {
                "verdict": "failed",
                "reviewed_diff_sha256": invocation.diff_sha256,
                "summary": "The unsafe value violates the required boundary.",
                "findings": [
                    {
                        "id": "CLAUDE-P1-001",
                        "severity": "P1",
                        "title": "Unsafe value persisted",
                        "file": "src/sample.py",
                        "line": 1,
                        "evidence": "The current snapshot contains VALUE = unsafe.",
                        "required_fix": "Persist the safe value instead.",
                        "regression_test": "Prove unsafe before and safe after the fix.",
                        "status": "open",
                    }
                ],
                "tests_reviewed": [],
                "remaining_risks": [],
                "review_depth": "full",
                "self_authorship_disclosed": False,
                "next_actor": "codex",
            }
        result = _accepted(invocation)
        result["findings"] = [
            {
                "id": "CLAUDE-P1-001",
                "severity": "P1",
                "title": "Unsafe value persisted",
                "file": "src/sample.py",
                "line": 1,
                "evidence": "The pre-fix snapshot is unsafe and the revised snapshot is safe.",
                "required_fix": "Persist the safe value instead.",
                "regression_test": "Pre-fix reproduction failed and revised check passed.",
                "status": "fixed",
            }
        ]
        result["tests_reviewed"] = [
            {
                "command": "adversarial value probe",
                "status": "failed",
                "summary": "Pre-fix snapshot reproduced the unsafe value.",
                "snapshot": "pre_fix",
                "finding_ids": ["CLAUDE-P1-001"],
            },
            {
                "command": "adversarial value probe",
                "status": "passed",
                "summary": "Revised snapshot contains only the safe value.",
                "snapshot": "current",
                "finding_ids": ["CLAUDE-P1-001"],
            },
        ]
        return result


@pytest.mark.asyncio
async def test_reaudit_receives_pre_fix_and_current_snapshots(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workers = _FixingWorkers()
    manager = BuildReviewManager(repo=repo, worker_runner=workers)

    session = await manager.create(_request(max_rounds=3, allowed_paths=["src/"]))
    assert session.task is not None
    await session.task

    assert session.control.status == "accepted"
    assert len(workers.claude_rounds) == 2
    second = workers.claude_rounds[1]
    assert second.previous_workspace is not None
    assert (second.previous_workspace / "src" / "sample.py").read_text(encoding="utf-8") == 'VALUE = "unsafe"\n'
    assert (second.workspace / "src" / "sample.py").read_text(encoding="utf-8") == 'VALUE = "safe"\n'
    report = manager._latest_review(session.control.session_id)
    assert report is not None
    assert report.findings[0].status == "fixed"


class _MutatingReviewer(_AcceptingWorkers):
    async def __call__(self, invocation: WorkerInvocation) -> dict[str, object]:
        result = await super().__call__(invocation)
        if invocation.actor == "claude":
            (invocation.workspace / "src" / "sample.py").write_text(
                "def value() -> int:\n    return 99\n", encoding="utf-8"
            )
        return result


@pytest.mark.asyncio
async def test_reviewer_mutation_discards_verdict(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo, worker_runner=_MutatingReviewer())
    session = await manager.create(_request())
    assert session.task is not None
    await session.task

    assert session.control.status == "verification_failed"
    assert session.control.next_actor == "human"
    assert not (repo / "src" / "sample.py").exists()


class _ScopeViolatingWorkers(_AcceptingWorkers):
    async def __call__(self, invocation: WorkerInvocation) -> dict[str, object]:
        result = await super().__call__(invocation)
        if invocation.actor == "codex":
            (invocation.workspace / "README.md").write_text("changed\n", encoding="utf-8")
        return result


@pytest.mark.asyncio
async def test_out_of_scope_builder_change_stops_before_review(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workers = _ScopeViolatingWorkers()
    manager = BuildReviewManager(repo=repo, worker_runner=workers)
    session = await manager.create(_request())
    assert session.task is not None
    await session.task

    assert session.control.status == "human_intervention_required"
    assert [call.actor for call in workers.invocations] == ["codex"]
    assert not (repo / "src" / "sample.py").exists()


class _P2Workers(_AcceptingWorkers):
    async def __call__(self, invocation: WorkerInvocation) -> dict[str, object]:
        result = await super().__call__(invocation)
        if invocation.actor == "claude":
            return {
                "verdict": "partially_accepted",
                "reviewed_diff_sha256": invocation.diff_sha256,
                "summary": "One noncritical reliability issue remains.",
                "findings": [
                    {
                        "id": "CLAUDE-P2-001",
                        "severity": "P2",
                        "title": "Retry note is incomplete",
                        "file": "src/sample.py",
                        "line": 1,
                        "evidence": "The limitation is documented but not automated.",
                        "required_fix": "Add retry handling or obtain a human waiver.",
                        "regression_test": "Exercise retry handling.",
                        "status": "open",
                    }
                ],
                "tests_reviewed": [],
                "remaining_risks": ["Retry remains manual."],
                "review_depth": "full",
                "self_authorship_disclosed": False,
                "next_actor": "codex",
            }
        return result


@pytest.mark.asyncio
async def test_open_p2_blocks_and_requires_explicit_human_waiver(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo, worker_runner=_P2Workers())
    session = await manager.create(_request(max_rounds=1))
    assert session.task is not None
    await session.task

    assert session.control.status == "failed_review"
    assert session.control.open_p2 == 1
    with pytest.raises(BuildReviewError, match="only_open_p2"):
        await manager.waive_p2(
            session.control.session_id,
            FindingWaiverRequest(
                approval_token=session.approval_token,
                finding_ids=["CLAUDE-P1-001"],
                justification="This is intentionally not a valid P2 waiver request.",
            ),
        )
    control = await manager.waive_p2(
        session.control.session_id,
        FindingWaiverRequest(
            approval_token=session.approval_token,
            finding_ids=["CLAUDE-P2-001"],
            justification="The founder accepts this bounded reliability limitation for the trial.",
        ),
    )
    assert control.status == "accepted"
    assert (manager._session_dir(control.session_id) / "human" / "p2-waiver.json").is_file()


@pytest.mark.asyncio
async def test_canonical_change_blocks_apply(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo, worker_runner=_AcceptingWorkers())
    session = await manager.create(_request())
    assert session.task is not None
    await session.task
    (repo / "README.md").write_text("founder changed this\n", encoding="utf-8")

    with pytest.raises(BuildReviewError, match="canonical_workspace_changed"):
        await manager.apply_accepted(
            session.control.session_id,
            ApplyAcceptedRequest(
                confirmation="apply_accepted_patch",
                approval_token=session.approval_token,
            ),
        )
    assert session.control.status == "conflicting_workspace_change"
    assert not (repo / "src" / "sample.py").exists()


@pytest.mark.asyncio
async def test_head_change_blocks_apply_even_when_status_is_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo, worker_runner=_AcceptingWorkers())
    session = await manager.create(_request())
    assert session.task is not None
    await session.task
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-m", "later")
    assert _git(repo, "status", "--short") == ""

    with pytest.raises(BuildReviewError, match="canonical_workspace_changed"):
        await manager.apply_accepted(
            session.control.session_id,
            ApplyAcceptedRequest(
                confirmation="apply_accepted_patch",
                approval_token=session.approval_token,
            ),
        )
    assert session.control.status == "conflicting_workspace_change"


@pytest.mark.asyncio
async def test_apply_requires_session_human_authorization(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo, worker_runner=_AcceptingWorkers())
    session = await manager.create(_request())
    assert session.task is not None
    await session.task

    with pytest.raises(BuildReviewError, match="human_authorization_required"):
        await manager.apply_accepted(
            session.control.session_id,
            ApplyAcceptedRequest(
                confirmation="apply_accepted_patch",
                approval_token="0" * 64,
            ),
        )
    assert session.control.status == "accepted"
    assert not (repo / "src" / "sample.py").exists()


@pytest.mark.asyncio
async def test_cancel_requires_session_human_authorization(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo)
    session = BuildReviewSession(
        control=BuildReviewControl(
            session_id="br-fedcba654321",
            max_rounds=2,
            base_commit=_git(repo, "rev-parse", "HEAD").strip(),
            base_branch=_git(repo, "branch", "--show-current").strip(),
            initial_workspace_sha256=await manager._workspace_digest(repo),
        ),
        request=_request(),
    )
    manager._sessions[session.control.session_id] = session

    with pytest.raises(BuildReviewError, match="human_authorization_required"):
        await manager.cancel(
            session.control.session_id,
            CancelBuildReviewRequest(approval_token="0" * 64),
        )
    assert session.control.status == "queued"

    await manager.cancel(
        session.control.session_id,
        CancelBuildReviewRequest(approval_token=session.approval_token),
    )
    assert session.control.status == "cancelled"


def test_commands_enforce_single_writer_and_read_only_reviewer(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    codex = codex_builder_command(tmp_path, schema)
    claude = claude_reviewer_command(tmp_path, tmp_path / "scratch", {"type": "object"})

    assert "workspace-write" in codex
    assert "--ask-for-approval" in codex
    assert "never" in codex
    assert codex.index("--ask-for-approval") < codex.index("exec")
    assert "--ephemeral" in codex
    assert "--output-schema" in codex

    assert "plan" in claude
    assert "Read,Glob,Grep,Bash" in claude
    denied = claude[claude.index("--disallowed-tools") + 1]
    assert "Edit" in denied and "Write" in denied and "WebFetch" in denied
    assert "--no-session-persistence" in claude
    assert "--safe-mode" in claude
    assert "--disable-slash-commands" in claude
    assert "--strict-mcp-config" in claude


def test_claude_structured_result_parser_uses_validated_result_payload() -> None:
    assert BuildReviewManager._claude_structured(
        {"type": "result", "structured_output": {"verdict": "accepted"}}
    ) == {"verdict": "accepted"}
    assert BuildReviewManager._claude_structured(
        {"type": "result", "result": '{"verdict":"failed"}'}
    ) == {"verdict": "failed"}
    assert BuildReviewManager._claude_structured(
        {"type": "stream_event", "structured_output": {"verdict": "accepted"}}
    ) is None


@pytest.mark.asyncio
async def test_cancelled_worker_is_terminated_and_does_not_survive(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    process = _BlockingProcess()

    async def process_factory(*_args: object, **_kwargs: object) -> _BlockingProcess:
        return process

    manager = BuildReviewManager(repo=repo, process_factory=process_factory)
    session = BuildReviewSession(
        control=BuildReviewControl(
            session_id="br-abcdef123456",
            max_rounds=2,
            base_commit=_git(repo, "rev-parse", "HEAD").strip(),
            base_branch=_git(repo, "branch", "--show-current").strip(),
            initial_workspace_sha256=await manager._workspace_digest(repo),
        ),
        request=_request(),
    )
    invocation = WorkerInvocation(
        actor="codex",
        session_id=session.control.session_id,
        round=1,
        workspace=repo,
        scratch=repo / ".aria_build_review" / "scratch",
        prompt="Return a report.",
        schema={"type": "object"},
    )

    task = asyncio.create_task(manager._invoke_worker(session, invocation))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.terminated is True
    assert session.process is None


def test_manager_has_no_import_or_constructor_time_runtime_write(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runtime = repo / ".aria_build_review"

    BuildReviewManager(repo=repo, runtime_root=runtime)

    assert not runtime.exists()


def test_worker_environment_removes_provider_and_credential_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "TOP_SECRET")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "TOP_SECRET")
    monkeypatch.setenv("AWS_PROFILE", "production")
    monkeypatch.setenv("GH_TOKEN", "TOP_SECRET")
    monkeypatch.setenv("NORMAL_SETTING", "kept")

    env = BuildReviewManager._worker_environment(tmp_path)

    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "AWS_PROFILE" not in env
    assert "GH_TOKEN" not in env
    assert env["NORMAL_SETTING"] == "kept"
    assert env["ARIA_DATA_DIR"] == str(tmp_path / "aria_data")
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_review_contract_rejects_blockers_and_shallow_acceptance() -> None:
    digest = "a" * 64
    with pytest.raises(ValueError, match="open P1/P2"):
        ReviewReport.model_validate(
            {
                "verdict": "accepted",
                "reviewed_diff_sha256": digest,
                "summary": "Incorrect acceptance with a blocker.",
                "findings": [
                    {
                        "id": "CLAUDE-P1-001",
                        "severity": "P1",
                        "title": "Authority bypass",
                        "evidence": "Direct store call bypasses policy.",
                        "required_fix": "Enforce policy in the store.",
                        "regression_test": "Add a direct-store abuse test.",
                    }
                ],
                "review_depth": "full",
                "next_actor": "human",
            }
        )


def test_reaudit_requires_stable_findings_and_p1_before_after_proof() -> None:
    digest = "b" * 64
    previous = ReviewReport.model_validate(
        {
            "verdict": "failed",
            "reviewed_diff_sha256": "a" * 64,
            "summary": "Direct authority bypass found.",
            "findings": [
                {
                    "id": "CLAUDE-P1-001",
                    "severity": "P1",
                    "title": "Authority bypass",
                    "evidence": "A direct call bypasses policy.",
                    "required_fix": "Move enforcement into the authority store.",
                    "regression_test": "Prove the direct call fails before and passes after.",
                }
            ],
            "review_depth": "full",
            "next_actor": "codex",
        }
    )
    missing = ReviewReport.model_validate(
        {
            "verdict": "accepted",
            "reviewed_diff_sha256": digest,
            "summary": "Finding was silently omitted.",
            "review_depth": "full",
            "next_actor": "human",
        }
    )
    with pytest.raises(BuildReviewError, match="continuity"):
        BuildReviewManager._validate_finding_continuity(missing, previous)

    fixed_without_proof = ReviewReport.model_validate(
        {
            "verdict": "accepted",
            "reviewed_diff_sha256": digest,
            "summary": "Finding marked fixed without a pre-fix reproduction.",
            "findings": [
                {
                    "id": "CLAUDE-P1-001",
                    "severity": "P1",
                    "title": "Authority bypass",
                    "evidence": "The revised path is guarded.",
                    "required_fix": "Move enforcement into the authority store.",
                    "regression_test": "Prove the direct call fails before and passes after.",
                    "status": "fixed",
                }
            ],
            "review_depth": "full",
            "next_actor": "human",
        }
    )
    with pytest.raises(BuildReviewError, match="p1_regression_proof_missing"):
        BuildReviewManager._validate_finding_continuity(fixed_without_proof, previous)
    with pytest.raises(ValueError, match="shallow"):
        ReviewReport.model_validate(
            {
                "verdict": "accepted",
                "reviewed_diff_sha256": digest,
                "summary": "A shallow review cannot accept.",
                "review_depth": "shallow",
                "next_actor": "human",
            }
        )


def test_work_order_rejects_traversal_and_protocol_paths() -> None:
    with pytest.raises(ValueError):
        _request(allowed_paths=["../outside.py"])
    with pytest.raises(ValueError):
        _request(allowed_paths=[".aria_build_review/session/control.json"])
    with pytest.raises(ValueError):
        _request(allowed_paths=[".git/config"])
    with pytest.raises(ValueError):
        BuildReviewRequest(
            title="Invalid empty acceptance list",
            objective="This work order deliberately supplies only blank acceptance criteria.",
            acceptance_criteria=["   "],
            allowed_paths=["src/"],
        )


def test_build_review_page_and_health_are_exposed() -> None:
    client = TestClient(app)
    page = client.get("/build-review")
    assert page.status_code == 200
    assert "ARIA Build &amp; Review" in page.text
    assert "Codex writes / Claude audits / founder authorizes" in page.text
    assert "Apply accepted patch" in page.text
    assert client.get("/api/braintrust/health").json()["modes"] == [
        "strategy_braintrust",
        "build_review",
    ]


def test_api_runs_loop_and_requires_capability_to_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo, worker_runner=_AcceptingWorkers())
    monkeypatch.setattr(braintrust_app_module, "build_review_manager", manager)
    payload = _request().model_dump(mode="json")

    with TestClient(app) as client:
        created = client.post("/api/build-review/sessions", json=payload)
        assert created.status_code == 202
        session_id = created.json()["session_id"]
        assert "approval_token" not in created.json()
        token_path = Path(created.json()["approval_token_path"])
        assert token_path.name == f"{session_id}.token"
        assert token_path.parent.name == ".human"
        assert not (manager._session_dir(session_id) / "human" / "approval-token").exists()
        with pytest.raises(ValueError):
            token_path.resolve().relative_to(manager._session_dir(session_id).resolve())
        approval_token = token_path.read_text(encoding="utf-8").strip()
        state = _wait_for_session_status(client, session_id, "accepted")
        assert state["control"]["status"] == "accepted"  # type: ignore[index]

        denied = client.post(
            f"/api/build-review/sessions/{session_id}/apply",
            json={"confirmation": "apply_accepted_patch", "approval_token": "0" * 64},
        )
        assert denied.status_code == 409
        assert denied.json()["detail"] == "human_authorization_required"

        applied = client.post(
            f"/api/build-review/sessions/{session_id}/apply",
            json={
                "confirmation": "apply_accepted_patch",
                "approval_token": approval_token,
            },
        )
        assert applied.status_code == 200
        assert applied.json()["status"] == "applied"
    assert (repo / "src" / "sample.py").is_file()


@pytest.mark.asyncio
async def test_runtime_records_are_reloadable_and_secret_sanitized(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo, worker_runner=_AcceptingWorkers())
    request = _request()
    request.objective = "Implement this while password=DO_NOT_PERSIST remains private."
    session = await manager.create(request)
    assert session.task is not None
    await session.task

    directory = manager._session_dir(session.control.session_id)
    assert "DO_NOT_PERSIST" not in (directory / "work_order.json").read_text(encoding="utf-8")
    restored = BuildReviewManager(repo=repo).get(session.control.session_id)
    assert restored.control.status == "accepted"
    assert restored.events[-1].status == "accepted"
    assert json.loads((directory / "control.json").read_text(encoding="utf-8"))["next_actor"] == "human"


@pytest.mark.asyncio
async def test_interrupted_session_reloads_as_human_intervention(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    async def never_called(invocation: WorkerInvocation) -> dict[str, object]:
        del invocation
        raise AssertionError("worker should not run")

    manager = BuildReviewManager(repo=repo, worker_runner=never_called)
    request = _request()
    base = _git(repo, "rev-parse", "HEAD").strip()
    session_id = "br-123456789abc"
    directory = manager._session_dir(session_id)
    directory.mkdir(parents=True)
    control = {
        "schema_version": 1,
        "session_id": session_id,
        "revision": 4,
        "status": "reviewing",
        "next_actor": "claude",
        "round": 1,
        "max_rounds": 3,
        "base_commit": base,
        "base_branch": "master",
        "initial_workspace_sha256": "0" * 64,
    }
    (directory / "control.json").write_text(json.dumps(control), encoding="utf-8")
    (directory / "work_order.json").write_text(request.model_dump_json(), encoding="utf-8")
    (directory / "events.jsonl").write_text("", encoding="utf-8")
    token_path = manager.approval_token_path(session_id)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("a" * 64, encoding="utf-8")

    restored = BuildReviewManager(repo=repo).get(session_id)

    assert restored.control.status == "human_intervention_required"
    assert restored.control.next_actor == "human"
    assert restored.events[-1].content.startswith("The coordinator restarted")


@pytest.mark.asyncio
async def test_event_metadata_is_recursively_sanitized(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = BuildReviewManager(repo=repo, worker_runner=_AcceptingWorkers())
    session = await manager.create(_request())
    await manager._emit(
        session,
        "probe",
        "coordinator",
        "safe",
        metadata={"nested": ["password=EVENT_SECRET", {"value": "Bearer EVENT_TOKEN"}]},
    )

    persisted = (manager._session_dir(session.control.session_id) / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert "EVENT_SECRET" not in persisted
    assert "EVENT_TOKEN" not in persisted
    await manager.cancel(
        session.control.session_id,
        CancelBuildReviewRequest(approval_token=session.approval_token),
    )
