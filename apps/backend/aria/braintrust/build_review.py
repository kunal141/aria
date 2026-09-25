"""Isolated Codex-build / Claude-review orchestration for the local console.

Codex is the sole product-code writer. It works in a disposable private clone.
Claude reviews frozen snapshots and may write only disposable verification output.
The canonical repository changes only after an explicit human apply request.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from aria.goals.sanitize import sanitize_text

BuildActor = Literal["human", "codex", "claude", "coordinator"]
NextActor = Literal["codex", "claude", "human", "none"]
ReviewDepth = Literal["full", "partitioned", "shallow", "rejected_for_size"]
Severity = Literal["P1", "P2", "P3"]
FindingStatus = Literal["open", "fixed", "superseded"]
ReviewVerdict = Literal["accepted", "partially_accepted", "failed"]
BuildStatus = Literal[
    "queued",
    "preparing",
    "building",
    "freezing",
    "reviewing",
    "accepted",
    "failed_review",
    "human_intervention_required",
    "conflicting_workspace_change",
    "worker_timeout",
    "verification_failed",
    "cancelled",
    "applied",
]

_SESSION_PATTERN = re.compile(r"^br-[0-9a-f]{12}$")
_FINDING_PATTERN = re.compile(r"^(?:CLAUDE|COORD)-P[123]-[0-9]{3}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_EVENT_CONTENT = 20_000
_MAX_CHANGED_FILES = 25
_FULL_REVIEW_LINES = 800
_PARTITIONED_REVIEW_LINES = 2_000
_CODEX_TIMEOUT_SECONDS = 3_600
_CLAUDE_TIMEOUT_SECONDS = 1_800
_STREAM_LIMIT_BYTES = 4 * 1024 * 1024
_TERMINAL_STATUSES = {
    "accepted",
    "failed_review",
    "human_intervention_required",
    "conflicting_workspace_change",
    "worker_timeout",
    "verification_failed",
    "cancelled",
    "applied",
}
_GENERATED_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "uv.lock",
    "poetry.lock",
}
_SECRET_ENV_PATTERN = re.compile(
    r"(?:^|_)(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIALS?|"
    r"PRIVATE_?KEY|ACCESS_?KEY|SESSION_?KEY|COOKIE)(?:_|$)",
    re.IGNORECASE,
)
_CLOUD_ENV_PREFIXES = (
    "ANTHROPIC_",
    "AWS_",
    "AZURE_",
    "COHERE_",
    "GITHUB_",
    "GOOGLE_",
    "GROQ_",
    "HF_",
    "LANGSMITH_",
    "MISTRAL_",
    "OLLAMA_",
    "OPENAI_",
    "PERPLEXITY_",
    "SLACK_",
    "TOGETHER_",
    "VERTEX_",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _safe_text(value: str | None, fallback: str = "") -> str:
    return sanitize_text(value) or fallback


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value, "[redacted]")
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    return value


def _relative_path(value: str) -> str:
    candidate = value.strip().replace("\\", "/")
    if sanitize_text(candidate) != candidate:
        raise ValueError("path contains sensitive text")
    path = PurePosixPath(candidate)
    if (
        not candidate
        or path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
        or ".aria_build_review" in path.parts
    ):
        raise ValueError("paths must be repository-relative and outside protocol metadata")
    return path.as_posix().rstrip("/") + ("/" if candidate.endswith("/") else "")


class BuildReviewRequest(BaseModel):
    """A bounded human work order for the single-writer review loop."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=5, max_length=160)
    objective: str = Field(min_length=20, max_length=30_000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=40)
    allowed_paths: list[str] = Field(min_length=1, max_length=40)
    validation_commands: list[str] = Field(default_factory=list, max_length=20)
    max_rounds: int = Field(default=4, ge=1, le=8)

    @field_validator("acceptance_criteria", "validation_commands")
    @classmethod
    def clean_lines(cls, values: list[str], info: ValidationInfo) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if info.field_name == "acceptance_criteria" and not cleaned:
            raise ValueError("at least one acceptance criterion is required")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("list values must be unique")
        if any(len(value) > 2_000 for value in cleaned):
            raise ValueError("a work-order line is too long")
        return cleaned

    @field_validator("allowed_paths")
    @classmethod
    def clean_paths(cls, values: list[str]) -> list[str]:
        cleaned = [_relative_path(value) for value in values]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("allowed paths must be unique")
        return cleaned


class BuilderTestResult(BaseModel):
    command: str = Field(min_length=1, max_length=2_000)
    status: Literal["passed", "failed", "not_run"]
    summary: str = Field(min_length=1, max_length=4_000)


class BuilderReport(BaseModel):
    summary: str = Field(min_length=1, max_length=12_000)
    files_changed: list[str] = Field(default_factory=list, max_length=100)
    tests: list[BuilderTestResult] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=40)
    ready_for_review: bool


class ReviewFinding(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    severity: Severity
    title: str = Field(min_length=3, max_length=240)
    file: str | None = Field(default=None, max_length=512)
    line: int | None = Field(default=None, ge=1)
    evidence: str = Field(min_length=3, max_length=8_000)
    required_fix: str = Field(min_length=3, max_length=8_000)
    regression_test: str = Field(min_length=3, max_length=4_000)
    status: FindingStatus = "open"

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not _FINDING_PATTERN.fullmatch(value):
            raise ValueError("finding id must use CLAUDE-Pn-nnn or COORD-Pn-nnn")
        return value

    @field_validator("file")
    @classmethod
    def safe_file(cls, value: str | None) -> str | None:
        return _relative_path(value) if value else None


class ReviewCheck(BaseModel):
    command: str = Field(min_length=1, max_length=2_000)
    status: Literal["passed", "failed", "not_run", "supplied_not_rerun"]
    summary: str = Field(min_length=1, max_length=4_000)
    snapshot: Literal["current", "pre_fix", "not_applicable"] = "current"
    finding_ids: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("finding_ids")
    @classmethod
    def valid_finding_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not _FINDING_PATTERN.fullmatch(v) for v in values):
            raise ValueError("check finding ids must be unique structured finding ids")
        return values


class ReviewReport(BaseModel):
    verdict: ReviewVerdict
    reviewed_diff_sha256: str
    summary: str = Field(min_length=1, max_length=12_000)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=100)
    tests_reviewed: list[ReviewCheck] = Field(default_factory=list, max_length=100)
    remaining_risks: list[str] = Field(default_factory=list, max_length=40)
    review_depth: ReviewDepth
    self_authorship_disclosed: bool = False
    next_actor: Literal["codex", "human"]

    @field_validator("reviewed_diff_sha256")
    @classmethod
    def valid_digest(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("reviewed diff must be identified by SHA-256")
        return value

    @model_validator(mode="after")
    def coherent_verdict(self) -> ReviewReport:
        ids = [finding.id for finding in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("review finding ids must be unique")
        blockers = [
            finding
            for finding in self.findings
            if finding.status == "open" and finding.severity in {"P1", "P2"}
        ]
        if self.verdict == "accepted" and blockers:
            raise ValueError("accepted review cannot contain open P1/P2 findings")
        if self.review_depth in {"shallow", "rejected_for_size"} and self.verdict == "accepted":
            raise ValueError("shallow or oversized reviews cannot accept a change")
        if self.verdict == "accepted" and self.next_actor != "human":
            raise ValueError("accepted review must return authority to the human")
        if blockers and self.next_actor != "codex":
            raise ValueError("open P1/P2 findings must return work to Codex")
        return self


class FindingWaiverRequest(BaseModel):
    approval_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    finding_ids: list[str] = Field(min_length=1, max_length=40)
    justification: str = Field(min_length=20, max_length=4_000)

    @field_validator("finding_ids")
    @classmethod
    def valid_finding_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not _FINDING_PATTERN.fullmatch(v) for v in values):
            raise ValueError("waiver finding ids must be unique structured finding ids")
        return values


class ApplyAcceptedRequest(BaseModel):
    confirmation: Literal["apply_accepted_patch"]
    approval_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class CancelBuildReviewRequest(BaseModel):
    approval_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class BuildReviewEvent(BaseModel):
    event_id: int
    kind: str
    actor: BuildActor
    status: BuildStatus
    content: str = ""
    timestamp: str = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuildReviewControl(BaseModel):
    schema_version: Literal[1] = 1
    session_id: str
    revision: int = 1
    status: BuildStatus = "queued"
    next_actor: NextActor = "codex"
    round: int = 0
    max_rounds: int
    base_commit: str
    base_branch: str
    initial_workspace_sha256: str
    diff_sha256: str | None = None
    previous_diff_sha256: str | None = None
    changed_files: int = 0
    handwritten_changed_lines: int = 0
    generated_changed_lines: int = 0
    review_depth: ReviewDepth | None = None
    latest_verdict: ReviewVerdict | None = None
    open_p1: int = 0
    open_p2: int = 0
    open_p3: int = 0
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    accepted_at: str | None = None
    applied_at: str | None = None


@dataclass
class BuildReviewSession:
    control: BuildReviewControl
    request: BuildReviewRequest
    events: list[BuildReviewEvent] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    process: asyncio.subprocess.Process | None = None
    cancel_requested: bool = False
    wake: asyncio.Condition = field(default_factory=asyncio.Condition)
    approval_token: str = field(default_factory=lambda: secrets.token_hex(32))


@dataclass(frozen=True)
class WorkerInvocation:
    actor: Literal["codex", "claude"]
    session_id: str
    round: int
    workspace: Path
    scratch: Path
    prompt: str
    schema: dict[str, Any]
    diff_sha256: str | None = None
    previous_workspace: Path | None = None


class WorkerRunner(Protocol):
    async def __call__(self, invocation: WorkerInvocation) -> dict[str, Any]: ...


def codex_builder_command(workspace: Path, schema_path: Path) -> list[str]:
    """Return a fixed workspace-write command for the sole code-writing worker."""
    executable = shutil.which("codex") or "codex"
    return [
        executable,
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--json",
        "--ignore-user-config",
        "-m",
        "gpt-5.6-sol",
        "-c",
        'model_reasoning_effort="xhigh"',
        "--sandbox",
        "workspace-write",
        "--output-schema",
        str(schema_path),
        "-C",
        str(workspace),
        "-",
    ]


def claude_reviewer_command(
    workspace: Path,
    scratch: Path,
    schema: dict[str, Any],
    previous_workspace: Path | None = None,
) -> list[str]:
    """Return a fixed plan-mode reviewer command with no edit/write tools."""
    executable = shutil.which("claude") or "claude"
    command = [
        executable,
        "-p",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--no-session-persistence",
        "--safe-mode",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--model",
        "opus",
        "--effort",
        "max",
        "--permission-mode",
        "plan",
        "--tools",
        "Read,Glob,Grep,Bash",
        "--disallowed-tools",
        "Edit,Write,NotebookEdit,WebFetch,WebSearch",
        "--add-dir",
        str(workspace),
        "--add-dir",
        str(scratch),
        "--json-schema",
        json.dumps(schema, separators=(",", ":")),
    ]
    if previous_workspace is not None:
        command.extend(["--add-dir", str(previous_workspace)])
    return command


class BuildReviewError(RuntimeError):
    """A safe, typed orchestration failure with no provider-controlled details."""

    def __init__(self, code: str, *, actor: BuildActor = "coordinator") -> None:
        super().__init__(code)
        self.code: str = code
        self.actor: BuildActor = actor


class BuildReviewManager:
    """Run a bounded Codex-build / Claude-review loop in disposable clones."""

    def __init__(
        self,
        *,
        repo: Path | None = None,
        runtime_root: Path | None = None,
        process_factory: Callable[..., Any] = asyncio.create_subprocess_exec,
        worker_runner: WorkerRunner | None = None,
    ) -> None:
        self.repo = (repo or Path(__file__).resolve().parents[4]).resolve()
        self.runtime_root = (runtime_root or self.repo / ".aria_build_review").resolve()
        try:
            self.runtime_root.relative_to(self.repo)
        except ValueError as exc:
            raise ValueError("build-review runtime root must remain inside the repository") from exc
        self._process_factory = process_factory
        self._worker_runner = worker_runner
        self._sessions: dict[str, BuildReviewSession] = {}

    async def create(self, request: BuildReviewRequest) -> BuildReviewSession:
        sanitized = BuildReviewRequest.model_validate(
            {
                **request.model_dump(),
                "title": _safe_text(request.title, "[redacted work order]"),
                "objective": _safe_text(request.objective, "[redacted objective]"),
                "acceptance_criteria": [_safe_text(item, "[redacted]") for item in request.acceptance_criteria],
                "validation_commands": [_safe_text(item, "[redacted]") for item in request.validation_commands],
            }
        )
        base_commit = (await self._git(self.repo, "rev-parse", "HEAD")).strip()
        base_branch = (await self._git(self.repo, "branch", "--show-current")).strip()
        initial_workspace_sha256 = await self._workspace_digest(self.repo)
        session_id = f"br-{uuid.uuid4().hex[:12]}"
        control = BuildReviewControl(
            session_id=session_id,
            max_rounds=sanitized.max_rounds,
            base_commit=base_commit,
            base_branch=base_branch,
            initial_workspace_sha256=initial_workspace_sha256,
        )
        session = BuildReviewSession(control=control, request=sanitized)
        self._sessions[session_id] = session
        self._session_dir(session_id).mkdir(parents=True)
        self._write_work_order(session)
        self._write_approval_token(session)
        self._write_control(session)
        await self._emit(
            session,
            "session_created",
            "human",
            "Work order accepted. Codex is the only product-code writer.",
            metadata={"base_commit": base_commit, "max_rounds": sanitized.max_rounds},
        )
        session.task = asyncio.create_task(self._run_loop(session))
        return session

    def get(self, session_id: str) -> BuildReviewSession:
        if session_id in self._sessions:
            return self._sessions[session_id]
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise KeyError("unknown build-review session")
        directory = self._session_dir(session_id)
        try:
            control = BuildReviewControl.model_validate_json(
                (directory / "control.json").read_text(encoding="utf-8")
            )
            request = self._read_work_order(directory / "work_order.json")
            events = [
                BuildReviewEvent.model_validate_json(line)
                for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            approval_token = self.approval_token_path(session_id).read_text(
                encoding="utf-8"
            ).strip()
            if not re.fullmatch(r"[0-9a-f]{64}", approval_token):
                raise ValueError("invalid approval token")
        except (OSError, ValueError):
            raise KeyError("unknown build-review session") from None
        session = BuildReviewSession(
            control=control,
            request=request,
            events=events,
            approval_token=approval_token,
        )
        if control.status not in _TERMINAL_STATUSES:
            self._mark_interrupted(session)
        self._sessions[session_id] = session
        return session

    async def cancel(self, session_id: str, request: CancelBuildReviewRequest) -> None:
        session = self.get(session_id)
        self._authorize(session, request.approval_token)
        if session.control.status in _TERMINAL_STATUSES:
            raise BuildReviewError("session_already_terminal")
        session.cancel_requested = True
        if session.process and session.process.returncode is None:
            session.process.terminate()
        if session.task and not session.task.done():
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.task
        if session.control.status != "cancelled":
            await self._set_state(session, "cancelled", "human", "none", "Session cancelled.")

    async def apply_accepted(
        self, session_id: str, request: ApplyAcceptedRequest
    ) -> BuildReviewControl:
        session = self.get(session_id)
        self._authorize(session, request.approval_token)
        if session.control.status != "accepted" or not session.control.diff_sha256:
            raise BuildReviewError("accepted_patch_required")
        current_head = (await self._git(self.repo, "rev-parse", "HEAD")).strip()
        current_branch = (await self._git(self.repo, "branch", "--show-current")).strip()
        current_workspace_sha256 = await self._workspace_digest(self.repo)
        if (
            current_head != session.control.base_commit
            or current_branch != session.control.base_branch
            or current_workspace_sha256 != session.control.initial_workspace_sha256
        ):
            await self._set_state(
                session,
                "conflicting_workspace_change",
                "coordinator",
                "human",
                "Canonical working tree changed after the work order was created.",
            )
            raise BuildReviewError("canonical_workspace_changed")
        patch = self._patch_path(session.control.session_id, session.control.diff_sha256)
        if hashlib.sha256(patch.read_bytes()).hexdigest() != session.control.diff_sha256:
            raise BuildReviewError("accepted_patch_hash_mismatch")
        await self._git(self.repo, "apply", "--binary", "--whitespace=nowarn", str(patch))
        session.control.applied_at = _now()
        await self._set_state(
            session,
            "applied",
            "human",
            "human",
            "Accepted Codex-authored patch applied. Nothing was staged or committed.",
        )
        return session.control

    async def waive_p2(
        self, session_id: str, request: FindingWaiverRequest
    ) -> BuildReviewControl:
        session = self.get(session_id)
        self._authorize(session, request.approval_token)
        if session.control.status not in {"failed_review", "human_intervention_required"}:
            raise BuildReviewError("p2_waiver_not_available")
        report = self._latest_review(session_id)
        if report is None:
            raise BuildReviewError("review_required")
        requested = set(request.finding_ids)
        findings = {finding.id: finding for finding in report.findings}
        if any(
            finding_id not in findings
            or findings[finding_id].severity != "P2"
            or findings[finding_id].status != "open"
            for finding_id in requested
        ):
            raise BuildReviewError("only_open_p2_findings_can_be_waived")
        remaining_p1 = [f for f in report.findings if f.severity == "P1" and f.status == "open"]
        remaining_p2 = [
            f
            for f in report.findings
            if f.severity == "P2" and f.status == "open" and f.id not in requested
        ]
        if remaining_p1 or remaining_p2:
            raise BuildReviewError("blocking_findings_remain")
        waiver = {
            "finding_ids": sorted(requested),
            "justification": _safe_text(request.justification, "[redacted]"),
            "recorded_at": _now(),
        }
        _atomic_text(
            self._session_dir(session_id) / "human" / "p2-waiver.json",
            json.dumps(waiver, indent=2, sort_keys=True),
        )
        session.control.accepted_at = _now()
        session.control.open_p2 = 0
        await self._set_state(
            session,
            "accepted",
            "human",
            "human",
            "Human explicitly waived the remaining P2 findings. Patch is ready for apply review.",
            metadata={"waived_findings": sorted(requested)},
        )
        return session.control

    async def events(
        self, session_id: str, after: int = 0
    ) -> AsyncIterator[BuildReviewEvent]:
        session = self.get(session_id)
        cursor = after
        while True:
            while cursor < len(session.events):
                event = session.events[cursor]
                cursor += 1
                yield event
            if session.control.status in _TERMINAL_STATUSES:
                return
            async with session.wake:
                try:
                    await asyncio.wait_for(session.wake.wait(), timeout=15)
                except TimeoutError:
                    yield BuildReviewEvent(
                        event_id=cursor,
                        kind="heartbeat",
                        actor="coordinator",
                        status=session.control.status,
                        metadata={"ephemeral": True},
                    )

    async def _run_loop(self, session: BuildReviewSession) -> None:
        try:
            await self._set_state(
                session, "preparing", "coordinator", "codex", "Preparing an isolated builder clone."
            )
            builder = self._builder_dir(session.control.session_id)
            await self._create_clone(builder, session.control.base_commit)
            for round_number in range(1, session.control.max_rounds + 1):
                if session.cancel_requested:
                    raise asyncio.CancelledError
                session.control.round = round_number
                session.control.revision += 1
                self._write_control(session)
                await self._set_state(
                    session,
                    "building",
                    "codex",
                    "codex",
                    f"Codex implementation round {round_number} started.",
                )
                builder_report = await self._run_builder(session, builder)
                self._write_builder_report(session, round_number, builder_report)
                if not builder_report.ready_for_review:
                    raise BuildReviewError("builder_not_ready", actor="codex")
                await self._set_state(
                    session,
                    "freezing",
                    "coordinator",
                    "claude",
                    "Freezing and hashing the complete Codex diff.",
                )
                frozen = await self._freeze(session, builder)
                if frozen is None:
                    return
                digest, review_workspace = frozen
                await self._set_state(
                    session,
                    "reviewing",
                    "claude",
                    "claude",
                    f"Claude is independently reviewing frozen revision {digest[:12]}.",
                )
                report = await self._run_reviewer(session, review_workspace, digest)
                self._write_review(session, round_number, report)
                if not await self._review_snapshot_unchanged(session, review_workspace, digest):
                    await self._set_state(
                        session,
                        "verification_failed",
                        "coordinator",
                        "human",
                        "Reviewer snapshot changed during review; the verdict was discarded.",
                    )
                    return
                blockers = [
                    finding
                    for finding in report.findings
                    if finding.status == "open" and finding.severity in {"P1", "P2"}
                ]
                session.control.latest_verdict = report.verdict
                session.control.open_p1 = sum(
                    f.status == "open" and f.severity == "P1" for f in report.findings
                )
                session.control.open_p2 = sum(
                    f.status == "open" and f.severity == "P2" for f in report.findings
                )
                session.control.open_p3 = sum(
                    f.status == "open" and f.severity == "P3" for f in report.findings
                )
                self._write_control(session)
                await self._emit(
                    session,
                    "review_completed",
                    "claude",
                    report.summary,
                    metadata={
                        "verdict": report.verdict,
                        "findings": [f.model_dump(mode="json") for f in report.findings],
                        "review_depth": report.review_depth,
                    },
                )
                if report.verdict == "accepted" and not blockers:
                    session.control.accepted_at = _now()
                    await self._set_state(
                        session,
                        "accepted",
                        "coordinator",
                        "human",
                        "Claude accepted the frozen diff. Human apply/commit decision required.",
                    )
                    return
                if round_number >= session.control.max_rounds:
                    await self._set_state(
                        session,
                        "failed_review",
                        "coordinator",
                        "human",
                        "Maximum rounds reached with unresolved P1/P2 findings.",
                    )
                    return
                session.control.previous_diff_sha256 = digest
                self._write_control(session)
            raise BuildReviewError("loop_ended_without_terminal_state")
        except asyncio.CancelledError:
            if session.control.status != "cancelled":
                await self._set_state(
                    session, "cancelled", "human", "none", "Session cancelled."
                )
        except BuildReviewError as exc:
            status: BuildStatus = (
                "worker_timeout" if exc.code == "worker_timeout" else "human_intervention_required"
            )
            await self._set_state(
                session,
                status,
                exc.actor,
                "human",
                f"Build-review stopped safely ({exc.code}). Raw worker details were not exposed.",
            )
        except Exception as exc:
            await self._set_state(
                session,
                "human_intervention_required",
                "coordinator",
                "human",
                f"Build-review stopped safely ({type(exc).__name__}). Details were redacted.",
            )

    async def _run_builder(self, session: BuildReviewSession, workspace: Path) -> BuilderReport:
        previous = self._latest_review(session.control.session_id)
        prompt = self._builder_prompt(session, previous)
        invocation = WorkerInvocation(
            actor="codex",
            session_id=session.control.session_id,
            round=session.control.round,
            workspace=workspace,
            scratch=self._round_scratch(session.control.session_id, session.control.round, "codex"),
            prompt=prompt,
            schema=BuilderReport.model_json_schema(),
        )
        payload = _sanitize_value(await self._invoke_worker(session, invocation))
        try:
            return BuilderReport.model_validate(payload)
        except ValueError as exc:
            raise BuildReviewError("builder_report_invalid", actor="codex") from exc

    async def _run_reviewer(
        self, session: BuildReviewSession, workspace: Path, digest: str
    ) -> ReviewReport:
        previous_workspace = (
            self._review_dir(session.control.session_id, session.control.round - 1)
            if session.control.round > 1
            else None
        )
        scratch = self._round_scratch(session.control.session_id, session.control.round, "claude")
        scratch.mkdir(parents=True, exist_ok=True)
        prompt = self._reviewer_prompt(session, workspace, previous_workspace, digest, scratch)
        invocation = WorkerInvocation(
            actor="claude",
            session_id=session.control.session_id,
            round=session.control.round,
            workspace=workspace,
            previous_workspace=previous_workspace,
            scratch=scratch,
            prompt=prompt,
            schema=ReviewReport.model_json_schema(),
            diff_sha256=digest,
        )
        payload = _sanitize_value(await self._invoke_worker(session, invocation))
        try:
            report = ReviewReport.model_validate(payload)
        except ValueError as exc:
            raise BuildReviewError("review_report_invalid", actor="claude") from exc
        if report.reviewed_diff_sha256 != digest:
            raise BuildReviewError("reviewed_diff_hash_mismatch", actor="claude")
        if report.review_depth != session.control.review_depth:
            raise BuildReviewError("review_depth_mismatch", actor="claude")
        self._validate_finding_continuity(
            report, self._latest_review(session.control.session_id)
        )
        return report

    async def _invoke_worker(
        self, session: BuildReviewSession, invocation: WorkerInvocation
    ) -> dict[str, Any]:
        invocation.scratch.mkdir(parents=True, exist_ok=True)
        if self._worker_runner is not None:
            return await self._worker_runner(invocation)
        schema_path = invocation.scratch / "output-schema.json"
        _atomic_text(schema_path, json.dumps(invocation.schema, indent=2, sort_keys=True))
        if invocation.actor == "codex":
            command = codex_builder_command(invocation.workspace, schema_path)
            timeout = _CODEX_TIMEOUT_SECONDS
        else:
            command = claude_reviewer_command(
                invocation.workspace,
                invocation.scratch,
                invocation.schema,
                invocation.previous_workspace,
            )
            timeout = _CLAUDE_TIMEOUT_SECONDS
        env = self._worker_environment(invocation.scratch)
        Path(env["TEMP"]).mkdir(parents=True, exist_ok=True)
        try:
            process = await self._process_factory(
                *command,
                cwd=str(invocation.workspace),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT_BYTES,
            )
        except Exception as exc:
            raise BuildReviewError("worker_unavailable", actor=invocation.actor) from exc
        session.process = process
        assert process.stdin and process.stdout and process.stderr
        pieces: list[str] = []
        structured_result: dict[str, Any] | None = None
        stderr_task = asyncio.create_task(process.stderr.read())
        try:
            process.stdin.write(invocation.prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
            async with asyncio.timeout(timeout):
                while line := await process.stdout.readline():
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = (
                        self._codex_chunk(payload)
                        if invocation.actor == "codex"
                        else self._claude_chunk(payload)
                    )
                    if invocation.actor == "claude":
                        structured = self._claude_structured(payload)
                        if structured is not None:
                            structured_result = structured
                    if chunk:
                        pieces.append(chunk)
                        await self._emit(
                            session,
                            "worker_output",
                            invocation.actor,
                            chunk,
                            metadata={"round": invocation.round},
                        )
                return_code = await process.wait()
                stderr = await stderr_task
        except TimeoutError as exc:
            if process.returncode is None:
                process.terminate()
                with contextlib.suppress(ProcessLookupError):
                    await process.wait()
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
            raise BuildReviewError("worker_timeout", actor=invocation.actor) from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
                with contextlib.suppress(ProcessLookupError):
                    await process.wait()
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
            raise
        except Exception as exc:
            if process.returncode is None:
                process.terminate()
                with contextlib.suppress(ProcessLookupError):
                    await process.wait()
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
            raise BuildReviewError("worker_stream_failed", actor=invocation.actor) from exc
        finally:
            session.process = None
        if return_code != 0:
            await self._emit(
                session,
                "worker_failed",
                invocation.actor,
                "Worker exited unsuccessfully; provider details were redacted.",
                metadata={"return_code": return_code, "stderr_bytes": len(stderr)},
            )
            raise BuildReviewError("worker_process_exit", actor=invocation.actor)
        if invocation.actor == "claude" and structured_result is not None:
            return structured_result
        content = "".join(pieces).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise BuildReviewError("worker_output_not_json", actor=invocation.actor) from exc

    async def _freeze(
        self, session: BuildReviewSession, builder: Path
    ) -> tuple[str, Path] | None:
        untracked = await self._git_lines(
            builder, "ls-files", "--others", "--exclude-standard"
        )
        if untracked:
            await self._git(builder, "add", "-N", "--", *untracked)
        changed = await self._git_lines(
            builder, "diff", session.control.base_commit, "--name-only", "--", "."
        )
        if not changed:
            await self._set_state(
                session,
                "human_intervention_required",
                "coordinator",
                "human",
                "Codex reported completion but produced no repository diff.",
            )
            return None
        violations = [
            path
            for path in changed
            if sanitize_text(path) != path
            or not self._path_allowed(path, session.request.allowed_paths)
        ]
        if violations:
            await self._emit(
                session,
                "scope_violation",
                "coordinator",
                "Codex changed files outside the work-order allowlist.",
                metadata={"files": violations},
            )
            await self._set_state(
                session,
                "human_intervention_required",
                "coordinator",
                "human",
                "Out-of-scope files were changed in the disposable builder clone.",
            )
            return None
        patch = await self._git_bytes(
            builder,
            "diff",
            session.control.base_commit,
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--",
            ".",
        )
        digest = hashlib.sha256(patch).hexdigest()
        patch_path = self._patch_path(session.control.session_id, digest)
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_bytes(patch)
        handwritten, generated = await self._changed_line_counts(
            builder, session.control.base_commit
        )
        depth: ReviewDepth
        if len(changed) > _MAX_CHANGED_FILES or handwritten > _PARTITIONED_REVIEW_LINES:
            depth = "rejected_for_size"
        elif handwritten > _FULL_REVIEW_LINES:
            depth = "partitioned"
        else:
            depth = "full"
        session.control.previous_diff_sha256 = session.control.diff_sha256
        session.control.diff_sha256 = digest
        session.control.changed_files = len(changed)
        session.control.handwritten_changed_lines = handwritten
        session.control.generated_changed_lines = generated
        session.control.review_depth = depth
        self._write_control(session)
        await self._emit(
            session,
            "diff_frozen",
            "coordinator",
            f"Frozen {len(changed)} files at SHA-256 {digest}.",
            metadata={
                "diff_sha256": digest,
                "changed_files": changed,
                "handwritten_changed_lines": handwritten,
                "generated_changed_lines": generated,
                "review_depth": depth,
            },
        )
        if depth == "rejected_for_size":
            await self._set_state(
                session,
                "human_intervention_required",
                "coordinator",
                "human",
                "Diff exceeds automatic review limits; split the work order or approve an override.",
            )
            return None
        review_workspace = self._review_dir(session.control.session_id, session.control.round)
        await self._create_clone(review_workspace, session.control.base_commit)
        await self._git(
            review_workspace,
            "apply",
            "--binary",
            "--whitespace=nowarn",
            str(patch_path),
        )
        review_untracked = await self._git_lines(
            review_workspace, "ls-files", "--others", "--exclude-standard"
        )
        if review_untracked:
            await self._git(review_workspace, "add", "-N", "--", *review_untracked)
        return digest, review_workspace

    async def _review_snapshot_unchanged(
        self, session: BuildReviewSession, workspace: Path, expected_digest: str
    ) -> bool:
        untracked = await self._git_lines(workspace, "ls-files", "--others", "--exclude-standard")
        source_untracked = [path for path in untracked if not path.startswith(".review_scratch/")]
        if source_untracked:
            return False
        patch = await self._git_bytes(
            workspace,
            "diff",
            session.control.base_commit,
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--",
            ".",
        )
        actual = hashlib.sha256(patch).hexdigest()
        if actual != expected_digest:
            await self._emit(
                session,
                "reviewer_mutation_detected",
                "coordinator",
                "Claude's review snapshot no longer matches the frozen diff.",
                metadata={"expected": expected_digest, "actual": actual},
            )
            return False
        return True

    async def _create_clone(self, target: Path, base_commit: str) -> None:
        if target.exists():
            raise BuildReviewError("isolated_clone_already_exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._git(
            self.repo,
            "clone",
            "--no-hardlinks",
            "--no-checkout",
            str(self.repo),
            str(target),
        )
        await self._git(target, "remote", "remove", "origin")
        await self._git(target, "checkout", "--detach", base_commit)

    async def _changed_line_counts(
        self, workspace: Path, base_commit: str
    ) -> tuple[int, int]:
        output = await self._git(
            workspace, "diff", base_commit, "--numstat", "--", "."
        )
        handwritten = 0
        generated = 0
        for line in output.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
                continue
            total = int(parts[0]) + int(parts[1])
            if PurePosixPath(parts[2]).name in _GENERATED_NAMES:
                generated += total
            else:
                handwritten += total
        return handwritten, generated

    def _builder_prompt(
        self, session: BuildReviewSession, previous: ReviewReport | None
    ) -> str:
        criteria = "\n".join(f"- {item}" for item in session.request.acceptance_criteria)
        paths = "\n".join(f"- {item}" for item in session.request.allowed_paths)
        commands = "\n".join(f"- {item}" for item in session.request.validation_commands) or "- Choose focused repository-native checks."
        findings = "[]"
        if previous is not None:
            findings = json.dumps(
                [
                    {
                        "id": finding.id,
                        "severity": finding.severity,
                        "title": finding.title,
                        "file": finding.file,
                        "line": finding.line,
                        "required_fix": finding.required_fix,
                        "regression_test": finding.regression_test,
                        "status": finding.status,
                    }
                    for finding in previous.findings
                ],
                indent=2,
            )
        return f"""
You are the sole product-code writer in an isolated ARIA builder clone.

WORK ORDER
Title: {session.request.title}
Objective: {session.request.objective}

MANDATORY ACCEPTANCE CRITERIA
{criteria}

ALLOWED PATHS
{paths}

REQUESTED VALIDATION
{commands}

PRIOR STRUCTURED FINDINGS FOR CLOSURE ONLY
{findings}

RULES
- Inspect the repository before editing and follow its established patterns.
- Modify only allowlisted paths. Do not touch .git or .aria_build_review.
- Implement the work end to end and add focused tests.
- Every P1 requires a regression test that fails against the prior frozen snapshot when applicable.
- Out-of-diff changes are permitted only when strictly necessary to close an in-scope P1/P2; explain them in the report and remain inside the allowlist.
- Do not commit, push, deploy, publish, contact external services, or read secrets.
- Do not use API keys or .env files.
- Return only JSON matching the supplied schema.
""".strip()

    def _reviewer_prompt(
        self,
        session: BuildReviewSession,
        workspace: Path,
        previous_workspace: Path | None,
        digest: str,
        scratch: Path,
    ) -> str:
        criteria = "\n".join(f"- {item}" for item in session.request.acceptance_criteria)
        commands = "\n".join(f"- {item}" for item in session.request.validation_commands) or "- Select focused checks."
        previous = self._latest_review(session.control.session_id)
        prior_findings = "[]"
        if previous is not None:
            prior_findings = json.dumps(
                [finding.model_dump(mode="json") for finding in previous.findings], indent=2
            )
        previous_note = (
            str(previous_workspace)
            if previous_workspace and previous_workspace.is_dir()
            else "Not applicable for the first review round."
        )
        return f"""
You are the independent read-only reviewer. Codex is the only product-code writer.

WORK ORDER
Title: {session.request.title}
Objective: {session.request.objective}

MANDATORY ACCEPTANCE CRITERIA
{criteria}

FROZEN CURRENT SNAPSHOT
Path: {workspace}
Diff SHA-256: {digest}
Review depth required: {session.control.review_depth}

PRE-FIX SNAPSHOT FOR REGRESSION PROOF
{previous_note}

WRITABLE VERIFICATION SCRATCH ONLY
{scratch}

REQUESTED VALIDATION
{commands}

PRIOR FINDINGS FOR STABLE IDS AND CLOSURE ONLY
{prior_findings}

REVIEW CONTRACT
- Review the frozen diff and surrounding code; do not trust the builder report alone.
- You may run tests and adversarial probes. Put probe scripts and outputs only in the scratch path.
- Do not edit source, tests, configuration, Git state, or the canonical repository.
- Label each check independently executed, supplied_not_rerun, failed, or not_run.
- P1: security/authority/governance bypass, secret leak, unintended external action, data corruption/audit divergence, core correctness defect, unmet mandatory criterion, or missing regression test for a new security boundary.
- P2: meaningful noncritical correctness/reliability defect, incomplete failure handling, misleading contract, inadequate changed-behavior tests, or regression-prone maintainability issue.
- P3: advisory improvement only.
- Open P1 and P2 block acceptance. P3 does not.
- Every P1 requires a final regression test and pre-fix reproduction when technically applicable. A test that passes before and after does not close it.
- Require an out-of-diff fix only when strictly necessary for an in-scope defect, and justify it.
- Keep finding IDs stable across rounds; mark fixed/superseded explicitly.
- Disclose self-authorship if this diff touches code you previously wrote.
- Never expose secrets or raw provider error text.
- Return only JSON matching the supplied schema and set reviewed_diff_sha256 exactly.
""".strip()

    async def _set_state(
        self,
        session: BuildReviewSession,
        status: BuildStatus,
        actor: BuildActor,
        next_actor: NextActor,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        session.control.status = status
        session.control.next_actor = next_actor
        session.control.revision += 1
        session.control.updated_at = _now()
        self._write_control(session)
        await self._emit(session, "status", actor, content, metadata=metadata)

    async def _emit(
        self,
        session: BuildReviewSession,
        kind: str,
        actor: BuildActor,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> BuildReviewEvent:
        event = BuildReviewEvent(
            event_id=len(session.events),
            kind=kind,
            actor=actor,
            status=session.control.status,
            content=_safe_text(content, "[redacted]")[:_MAX_EVENT_CONTENT],
            metadata=metadata or {},
        )
        event.metadata = _sanitize_value(event.metadata)
        session.events.append(event)
        path = self._session_dir(session.control.session_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        async with session.wake:
            session.wake.notify_all()
        return event

    def _write_control(self, session: BuildReviewSession) -> None:
        _atomic_text(
            self._session_dir(session.control.session_id) / "control.json",
            session.control.model_dump_json(indent=2),
        )

    def _write_work_order(self, session: BuildReviewSession) -> None:
        directory = self._session_dir(session.control.session_id)
        _atomic_text(directory / "work_order.json", session.request.model_dump_json(indent=2))
        criteria = "\n".join(f"- {item}" for item in session.request.acceptance_criteria)
        paths = "\n".join(f"- `{item}`" for item in session.request.allowed_paths)
        commands = "\n".join(f"- `{item}`" for item in session.request.validation_commands) or "- Builder/reviewer selects focused checks."
        _atomic_text(
            directory / "work_order.md",
            f"# {session.request.title}\n\n## Objective\n\n{session.request.objective}\n\n"
            f"## Acceptance Criteria\n\n{criteria}\n\n## Allowed Paths\n\n{paths}\n\n"
            f"## Validation\n\n{commands}\n",
        )

    def _write_approval_token(self, session: BuildReviewSession) -> None:
        _atomic_text(self.approval_token_path(session.control.session_id), session.approval_token)

    @staticmethod
    def _authorize(session: BuildReviewSession, supplied_token: str) -> None:
        if not secrets.compare_digest(session.approval_token, supplied_token):
            raise BuildReviewError("human_authorization_required")

    def _mark_interrupted(self, session: BuildReviewSession) -> None:
        session.control.status = "human_intervention_required"
        session.control.next_actor = "human"
        session.control.revision += 1
        session.control.updated_at = _now()
        self._write_control(session)
        event = BuildReviewEvent(
            event_id=len(session.events),
            kind="status",
            actor="coordinator",
            status="human_intervention_required",
            content="The coordinator restarted while a worker was active. Human restart is required.",
        )
        session.events.append(event)
        with (self._session_dir(session.control.session_id) / "events.jsonl").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(event.model_dump_json() + "\n")

    def _write_builder_report(
        self, session: BuildReviewSession, round_number: int, report: BuilderReport
    ) -> None:
        path = self._session_dir(session.control.session_id) / "codex" / f"round-{round_number}.json"
        _atomic_text(path, report.model_dump_json(indent=2))

    def _write_review(
        self, session: BuildReviewSession, round_number: int, report: ReviewReport
    ) -> None:
        path = self._session_dir(session.control.session_id) / "claude" / f"review-round-{round_number}.json"
        _atomic_text(path, report.model_dump_json(indent=2))

    def _latest_review(self, session_id: str) -> ReviewReport | None:
        directory = self._session_dir(session_id) / "claude"
        paths = sorted(directory.glob("review-round-*.json")) if directory.is_dir() else []
        if not paths:
            return None
        try:
            return ReviewReport.model_validate_json(paths[-1].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _validate_finding_continuity(
        report: ReviewReport, previous: ReviewReport | None
    ) -> None:
        if previous is None:
            return
        current = {finding.id: finding for finding in report.findings}
        prior_blockers = [
            finding
            for finding in previous.findings
            if finding.status == "open" and finding.severity in {"P1", "P2"}
        ]
        for prior in prior_blockers:
            finding = current.get(prior.id)
            if finding is None or finding.severity != prior.severity:
                raise BuildReviewError("review_finding_continuity_failed", actor="claude")
            if prior.severity == "P1" and finding.status in {"fixed", "superseded"}:
                pre_fix = any(
                    prior.id in check.finding_ids
                    and check.snapshot == "pre_fix"
                    and check.status == "failed"
                    for check in report.tests_reviewed
                )
                current_pass = any(
                    prior.id in check.finding_ids
                    and check.snapshot == "current"
                    and check.status == "passed"
                    for check in report.tests_reviewed
                )
                if not pre_fix or not current_pass:
                    raise BuildReviewError("p1_regression_proof_missing", actor="claude")

    @staticmethod
    def _read_work_order(path: Path) -> BuildReviewRequest:
        return BuildReviewRequest.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _path_allowed(path: str, allowed: list[str]) -> bool:
        normalized = PurePosixPath(path).as_posix()
        return any(
            normalized == item.rstrip("/")
            or (item.endswith("/") and normalized.startswith(item))
            for item in allowed
        )

    def _session_dir(self, session_id: str) -> Path:
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise ValueError("invalid build-review session id")
        return self.runtime_root / session_id

    def approval_token_path(self, session_id: str) -> Path:
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise ValueError("invalid build-review session id")
        return self.runtime_root / ".human" / f"{session_id}.token"

    def _builder_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "workspaces" / "builder"

    def _review_dir(self, session_id: str, round_number: int) -> Path:
        return self._session_dir(session_id) / "workspaces" / f"review-round-{round_number}"

    def _round_scratch(self, session_id: str, round_number: int, actor: str) -> Path:
        return self._session_dir(session_id) / "verification" / f"round-{round_number}" / actor

    def _patch_path(self, session_id: str, digest: str) -> Path:
        if not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError("invalid diff digest")
        return self._session_dir(session_id) / "snapshots" / f"diff-{digest}.patch"

    async def _git_status(self, cwd: Path) -> bytes:
        return await self._git_bytes(cwd, "status", "--porcelain=v1", "-z", "--untracked-files=all")

    async def _workspace_digest(self, cwd: Path) -> str:
        digest = hashlib.sha256()
        digest.update(
            await self._git_bytes(
                cwd,
                "diff",
                "HEAD",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--",
                ".",
            )
        )
        untracked = await self._git_lines(cwd, "ls-files", "--others", "--exclude-standard")
        for relative in sorted(untracked):
            path = cwd / relative
            stat = path.lstat()
            digest.update(relative.encode("utf-8"))
            digest.update(f"\0{stat.st_mode}\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode())
        return digest.hexdigest()

    @staticmethod
    def _worker_environment(scratch: Path) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not _SECRET_ENV_PATTERN.search(key)
            and not key.upper().startswith(_CLOUD_ENV_PREFIXES)
            and key.upper() not in {"GH_TOKEN", "GIT_ASKPASS", "SSH_AUTH_SOCK"}
        }
        env.update(
            {
                "ARIA_DATA_DIR": str(scratch / "aria_data"),
                "TMP": str(scratch / "tmp"),
                "TEMP": str(scratch / "tmp"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_ADDOPTS": "-p no:cacheprovider",
                "NO_COLOR": "1",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        return env

    async def _git_lines(self, cwd: Path, *args: str) -> list[str]:
        return [line for line in (await self._git(cwd, *args)).splitlines() if line]

    async def _git(self, cwd: Path, *args: str) -> str:
        return (await self._git_bytes(cwd, *args)).decode("utf-8", errors="replace")

    async def _git_bytes(self, cwd: Path, *args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise BuildReviewError(
                "git_command_failed",
                actor="coordinator",
            ) from RuntimeError(f"git stderr bytes={len(stderr)}")
        return stdout

    @staticmethod
    def _codex_chunk(payload: dict[str, Any]) -> str:
        if payload.get("type") != "item.completed":
            return ""
        item = payload.get("item") or {}
        return str(item.get("text", "")) if item.get("type") == "agent_message" else ""

    @staticmethod
    def _claude_chunk(payload: dict[str, Any]) -> str:
        if payload.get("type") != "stream_event":
            return ""
        event = payload.get("event") or {}
        if event.get("type") != "content_block_delta":
            return ""
        delta = event.get("delta") or {}
        return str(delta.get("text", "")) if delta.get("type") == "text_delta" else ""

    @staticmethod
    def _claude_structured(payload: dict[str, Any]) -> dict[str, Any] | None:
        if payload.get("type") != "result":
            return None
        structured = payload.get("structured_output")
        if isinstance(structured, dict):
            return structured
        result = payload.get("result")
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            with contextlib.suppress(json.JSONDecodeError):
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    return parsed
        return None


__all__ = [
    "ApplyAcceptedRequest",
    "BuildReviewControl",
    "BuildReviewError",
    "BuildReviewEvent",
    "BuildReviewManager",
    "BuildReviewRequest",
    "BuilderReport",
    "CancelBuildReviewRequest",
    "FindingWaiverRequest",
    "ReviewFinding",
    "ReviewReport",
    "WorkerInvocation",
    "claude_reviewer_command",
    "codex_builder_command",
]
