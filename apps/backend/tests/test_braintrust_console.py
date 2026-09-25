from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aria.braintrust.app import app
from aria.braintrust.runner import (
    BraintrustManager,
    DebateRequest,
    DebateSession,
    FounderMessageRequest,
    InvalidContextPathError,
    WorkerExecutionError,
    claude_command,
    codex_command,
)


class _FakeWriter:
    def write(self, _data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeReader:
    def __init__(self, lines: list[bytes] | None = None) -> None:
        self._lines = list(lines or [])

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    async def read(self) -> bytes:
        content = b"".join(self._lines)
        self._lines.clear()
        return content


class _FakeProcess:
    def __init__(
        self,
        stdout_lines: list[bytes],
        *,
        returncode: int = 0,
        stderr: bytes = b"",
    ) -> None:
        self.stdin = _FakeWriter()
        self.stdout = _FakeReader(stdout_lines)
        self.stderr = _FakeReader([stderr] if stderr else [])
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -1


def test_worker_commands_are_fixed_and_read_only(tmp_path: Path) -> None:
    claude = claude_command(tmp_path)
    codex = codex_command(tmp_path)

    assert "opus" in claude
    assert "plan" in claude
    assert "Read,Glob,Grep" in claude
    assert "--no-session-persistence" in claude
    assert "Bash" not in claude
    assert "Edit" not in claude

    assert "gpt-5.6-sol" in codex
    assert 'model_reasoning_effort="xhigh"' in codex
    assert "read-only" in codex
    assert "--ephemeral" in codex


def test_request_is_bounded() -> None:
    request = DebateRequest(
        question="What category should ARIA own across business departments?",
        rounds=2,
    )
    assert request.rounds == 2
    assert len(DebateRequest(question="x" * 7_000).question) == 7_000

    with pytest.raises(ValueError):
        DebateRequest(question="x" * 30_001)


def test_founder_message_supports_explicit_and_trailing_recipient_tags() -> None:
    explicit = FounderMessageRequest(content="Audit this proposal", recipient="codex")
    trailing = FounderMessageRequest(content="Challenge the market claim @codex")
    leading = FounderMessageRequest(content="@claude check the Codex plan")

    assert explicit.recipient == "codex"
    assert trailing.recipient == "codex"
    assert trailing.content == "Challenge the market claim"
    assert leading.recipient == "claude"
    assert leading.content == "check the Codex plan"

    with pytest.raises(ValueError):
        FounderMessageRequest(content="@claude")


def test_context_paths_are_repository_confined(tmp_path: Path) -> None:
    manager = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime")
    context = tmp_path / "docs" / "plan.md"
    context.parent.mkdir()
    context.write_text("plan", encoding="utf-8")

    assert manager._resolve_context_paths(["docs/plan.md"]) == ["docs/plan.md"]
    with pytest.raises(InvalidContextPathError):
        manager._resolve_context_paths(["../outside.md"])
    with pytest.raises(InvalidContextPathError):
        manager._resolve_context_paths(["docs/missing.md"])


def test_stream_parsers_expose_only_visible_model_text() -> None:
    claude_line = {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "visible"},
        },
    }
    codex_line = {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "challenge"},
    }
    hidden = {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "private"},
        },
    }

    assert BraintrustManager._claude_chunk(claude_line) == "visible"
    assert BraintrustManager._codex_chunk(codex_line) == "challenge"
    assert BraintrustManager._claude_chunk(hidden) == ""


@pytest.mark.asyncio
async def test_worker_accepts_large_json_stream_lines(tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    final_line = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "challenge"},
            }
        ).encode("utf-8")
        + b"\n"
    )

    async def process_factory(*_args: object, **kwargs: object) -> _FakeProcess:
        captured.update(kwargs)
        return _FakeProcess([final_line])

    manager = BraintrustManager(
        repo=tmp_path,
        data_dir=tmp_path / "runtime",
        process_factory=process_factory,
    )
    session = DebateSession(
        session_id="bt-stream-limit",
        request=DebateRequest(question="How should ARIA challenge a category proposal?"),
    )

    result = await manager._run_worker(session, "codex", "challenge", "test prompt")

    assert result == "challenge"
    assert int(captured["limit"]) > 64 * 1024


@pytest.mark.asyncio
async def test_failed_worker_preserves_partial_output_without_stderr_leak(tmp_path: Path) -> None:
    line = (
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Useful partial analysis"},
                },
            }
        ).encode("utf-8")
        + b"\n"
    )

    async def process_factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        return _FakeProcess([line], returncode=1, stderr=b"password=PROVIDER_SECRET")

    manager = BraintrustManager(
        repo=tmp_path,
        data_dir=tmp_path / "runtime",
        process_factory=process_factory,
    )
    session = DebateSession(
        session_id="bt-worker-failure",
        request=DebateRequest(question="How should ARIA recover a failed strategy worker?"),
    )

    with pytest.raises(WorkerExecutionError) as raised:
        await manager._run_worker(session, "claude", "proposal", "test prompt")

    assert raised.value.reason_code == "process_exit"
    assert raised.value.return_code == 1
    assert raised.value.stderr_bytes == len(b"password=PROVIDER_SECRET")
    assert raised.value.partial_output_preserved is True
    assert session.worker_outputs["proposal-partial"] == "Useful partial analysis"
    persisted = (manager.data_dir / "bt-worker-failure.jsonl").read_text(encoding="utf-8")
    assert "PROVIDER_SECRET" not in persisted


@pytest.mark.asyncio
async def test_failure_event_is_actionable_and_class_only(tmp_path: Path) -> None:
    manager = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime")
    session = DebateSession(
        session_id="bt-safe-failure",
        request=DebateRequest(question="How should ARIA report worker failures safely?"),
    )

    await manager._record_worker_failure(
        session,
        WorkerExecutionError(
            speaker="claude",
            phase="round-1-proposal",
            reason_code="process_exit",
            return_code=1,
            stderr_bytes=28,
            partial_output_preserved=True,
        ),
    )

    event = session.events[-1]
    assert event.kind == "error"
    assert event.metadata["worker"] == "claude"
    assert event.metadata["return_code"] == 1
    assert event.metadata["partial_output_preserved"] is True
    assert "Send a founder message" in event.content
    assert "provider details" in event.content


@pytest.mark.asyncio
async def test_failed_session_can_continue_from_saved_transcript(tmp_path: Path) -> None:
    claude_line = (
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Recovered response"},
                },
            }
        ).encode("utf-8")
        + b"\n"
    )
    codex_line = (
        json.dumps(
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Review"}}
        ).encode("utf-8")
        + b"\n"
    )
    processes = [_FakeProcess([claude_line]), _FakeProcess([codex_line])]

    async def process_factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        return processes.pop(0)

    manager = BraintrustManager(
        repo=tmp_path,
        data_dir=tmp_path / "runtime",
        process_factory=process_factory,
    )
    session = DebateSession(
        session_id="bt-failed-follow-up",
        request=DebateRequest(question="How should ARIA recover a partial strategy response?"),
        status="failed",
        worker_outputs={"round-1-proposal-partial": "Saved partial response"},
    )
    manager._sessions[session.session_id] = session

    disposition = await manager.add_founder_message(
        session.session_id,
        FounderMessageRequest(content="Continue and finish the recommendation."),
    )
    assert session.task is not None
    await session.task

    assert disposition == "follow_up_started"
    assert session.status == "completed"
    assert session.worker_outputs["follow-up-1-claude"] == "Recovered response"
    assert session.worker_outputs["follow-up-1-codex"] == "Review"


def test_failed_session_reloads_partial_output_from_transcript(tmp_path: Path) -> None:
    first = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime")
    session = DebateSession(
        session_id="bt-abcdef123456",
        request=DebateRequest(question="How should ARIA retain a partial strategy response?"),
    )
    first._emit(
        session,
        "session",
        "founder",
        "question",
        session.request.question,
        metadata={"rounds": 1, "context_paths": []},
    )
    first._emit(session, "message_start", "claude", "round-1-proposal")
    first._emit(session, "delta", "claude", "round-1-proposal", "Saved partial")
    first._emit(
        session,
        "error",
        "system",
        "failed",
        "Worker stopped safely. Raw provider details were not exposed.",
    )

    restored = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime").get(
        session.session_id
    )

    assert restored.status == "failed"
    assert restored.request.question == session.request.question
    assert restored.worker_outputs["round-1-proposal-partial"] == "Saved partial"


def test_session_reload_rejects_path_shaped_ids(tmp_path: Path) -> None:
    manager = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime")

    with pytest.raises(KeyError):
        manager.get("../outside")


@pytest.mark.asyncio
async def test_founder_message_is_visible_queued_and_sanitized(tmp_path: Path) -> None:
    manager = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime")
    session = DebateSession(
        session_id="bt-founder-message",
        request=DebateRequest(question="How should ARIA validate the founder thesis?"),
        status="running",
    )
    manager._sessions[session.session_id] = session

    disposition = await manager.add_founder_message(
        session.session_id,
        FounderMessageRequest(content="Challenge this with password=TOP_SECRET"),
    )

    assert disposition == "queued_for_both"
    assert "TOP_SECRET" not in session.pending_founder_messages[0].content
    assert session.pending_founder_messages[0].recipient == "both"
    assert session.events[-1].kind == "founder_message"
    assert "TOP_SECRET" not in session.events[-1].content
    assert session.events[-1].metadata["recipient"] == "both"


@pytest.mark.asyncio
async def test_completed_session_accepts_founder_follow_up(tmp_path: Path) -> None:
    claude_line = (
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Claude follow-up"},
                },
            }
        ).encode("utf-8")
        + b"\n"
    )
    codex_line = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Codex synthesis"},
            }
        ).encode("utf-8")
        + b"\n"
    )
    processes = [_FakeProcess([claude_line]), _FakeProcess([codex_line])]

    async def process_factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        return processes.pop(0)

    manager = BraintrustManager(
        repo=tmp_path,
        data_dir=tmp_path / "runtime",
        process_factory=process_factory,
    )
    session = DebateSession(
        session_id="bt-follow-up",
        request=DebateRequest(question="What strategy should ARIA validate next?"),
        status="completed",
        worker_outputs={"round-1-synthesis": "Prior synthesis"},
    )
    manager._sessions[session.session_id] = session

    disposition = await manager.add_founder_message(
        session.session_id,
        FounderMessageRequest(content="Compare the sales and marketing wedges."),
    )
    assert session.task is not None
    await session.task

    assert disposition == "follow_up_started"
    assert session.status == "completed"
    assert session.worker_outputs["follow-up-1-claude"] == "Claude follow-up"
    assert session.worker_outputs["follow-up-1-codex"] == "Codex synthesis"
    handoffs = [event for event in session.events if event.kind == "handoff"]
    assert [event.metadata["target"] for event in handoffs] == ["codex", "human"]
    assert session.events[-1].kind == "done"


@pytest.mark.asyncio
async def test_codex_direct_message_does_not_start_claude(tmp_path: Path) -> None:
    codex_line = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Codex direct answer"},
            }
        ).encode("utf-8")
        + b"\n"
    )
    processes = [_FakeProcess([codex_line])]

    async def process_factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        return processes.pop(0)

    manager = BraintrustManager(
        repo=tmp_path,
        data_dir=tmp_path / "runtime",
        process_factory=process_factory,
    )
    session = DebateSession(
        session_id="bt-codex-direct",
        request=DebateRequest(question="Which ARIA category claim should Codex challenge?"),
        status="completed",
        worker_outputs={"round-1-synthesis": "Prior synthesis"},
    )
    manager._sessions[session.session_id] = session

    disposition = await manager.add_founder_message(
        session.session_id,
        FounderMessageRequest(content="Audit only this positioning claim", recipient="codex"),
    )
    assert session.task is not None
    await session.task

    assert disposition == "follow_up_started"
    assert session.worker_outputs["follow-up-1-codex"] == "Codex direct answer"
    assert "follow-up-1-claude" not in session.worker_outputs
    starts = [event for event in session.events if event.kind == "message_start"]
    assert [event.speaker for event in starts] == ["codex"]
    assert session.events[-2].kind == "handoff"
    assert session.events[-2].metadata["target"] == "human"


@pytest.mark.asyncio
async def test_active_codex_message_skips_claude_and_waits_for_codex(tmp_path: Path) -> None:
    claude_line = (
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Claude turn"},
                },
            }
        ).encode("utf-8")
        + b"\n"
    )
    codex_line = (
        json.dumps(
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Codex turn"}}
        ).encode("utf-8")
        + b"\n"
    )
    processes = [_FakeProcess([claude_line]), _FakeProcess([codex_line])]

    async def process_factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        return processes.pop(0)

    manager = BraintrustManager(
        repo=tmp_path,
        data_dir=tmp_path / "runtime",
        process_factory=process_factory,
    )
    session = DebateSession(
        session_id="bt-directed-queue",
        request=DebateRequest(question="Which worker should receive this directed message?"),
        status="running",
    )
    manager._sessions[session.session_id] = session

    disposition = await manager.add_founder_message(
        session.session_id,
        FounderMessageRequest(content="Challenge this claim", recipient="codex"),
    )
    await manager._run_worker(session, "claude", "claude-turn", "Claude prompt")

    assert disposition == "queued_for_codex"
    assert [message.recipient for message in session.pending_founder_messages] == ["codex"]

    await manager._run_worker(session, "codex", "codex-turn", "Codex prompt")

    assert session.pending_founder_messages == []
    assert session.worker_outputs["codex-turn"] == "Codex turn"


@pytest.mark.asyncio
async def test_session_allows_followups_beyond_old_six_message_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime")
    session = DebateSession(
        session_id="bt-followup-seven",
        request=DebateRequest(question="Can the founder continue a long strategy session?"),
        status="completed",
        follow_up_count=6,
    )
    manager._sessions[session.session_id] = session

    async def complete_without_worker(
        active_session: DebateSession, _content: str, _recipient: str
    ) -> None:
        active_session.status = "completed"

    monkeypatch.setattr(manager, "_run_follow_up", complete_without_worker)

    disposition = await manager.add_founder_message(
        session.session_id,
        FounderMessageRequest(content="Continue with Claude", recipient="claude"),
    )
    assert session.task is not None
    await session.task

    assert disposition == "follow_up_started"
    assert session.follow_up_count == 7

    session.follow_up_count = 30
    with pytest.raises(RuntimeError, match="follow-up limit"):
        await manager.add_founder_message(
            session.session_id,
            FounderMessageRequest(content="One message too many", recipient="claude"),
        )


def test_markdown_export_collects_visible_model_output(tmp_path: Path) -> None:
    manager = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime")
    session = DebateSession(
        session_id="bt-markdown",
        request=DebateRequest(
            question="What strategy should ARIA validate next?",
            context_paths=["docs/plan.md"],
        ),
        status="completed",
    )
    manager._sessions[session.session_id] = session
    manager._emit(session, "message_start", "claude", "proposal", model="Claude Opus 5")
    manager._emit(session, "delta", "claude", "proposal", "Visible proposal")
    manager._emit(session, "message_end", "claude", "proposal")

    markdown = manager.export_markdown(session.session_id)

    assert "Visible proposal" in markdown
    assert "docs/plan.md" in markdown
    assert "hidden chain-of-thought" not in markdown


@pytest.mark.asyncio
async def test_transcript_is_written_under_configured_runtime_dir(tmp_path: Path) -> None:
    manager = BraintrustManager(repo=tmp_path, data_dir=tmp_path / "runtime")
    request = DebateRequest(question="How should ARIA validate a category thesis?")
    session = await manager.create(request)
    assert manager.data_dir == (tmp_path / "runtime" / "braintrust").resolve()
    transcript = manager.data_dir / f"{session.session_id}.jsonl"
    first = json.loads(transcript.read_text(encoding="utf-8").splitlines()[0])
    assert first["speaker"] == "founder"
    session.task.cancel()


def test_local_console_health_and_html() -> None:
    client = TestClient(app)
    health = client.get("/api/braintrust/health")
    page = client.get("/")

    assert health.status_code == 200
    assert health.json()["local_only"] is True
    assert health.json()["workers"][0]["model"] == "claude-opus-5"
    assert health.json()["workers"][1]["model"] == "gpt-5.6-sol"
    assert page.status_code == 200
    assert "ARIA Braintrust" in page.text
    assert 'maxlength="30000"' in page.text
    assert "Message the braintrust" in page.text
    assert "Partial work is saved" in page.text
    assert 'data-recipient="claude"' in page.text
    assert 'data-recipient="codex"' in page.text
    assert 'data-recipient="both"' in page.text
    assert "event.kind === 'handoff'" in page.text
    assert "data.status === 'failed'" in page.text
    assert "new URLSearchParams(location.search).get('session')" in page.text

    config = client.get("/api/braintrust/config").json()
    assert config["max_question_characters"] == 30_000
    assert config["max_follow_ups"] == 30
