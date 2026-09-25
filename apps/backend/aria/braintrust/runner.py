"""Read-only Claude/Codex debate orchestration for the local braintrust UI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aria.goals.sanitize import sanitize_text

Speaker = Literal["founder", "claude", "codex", "system"]
Recipient = Literal["claude", "codex", "both"]
HandoffTarget = Literal["claude", "codex", "human"]
EventKind = Literal[
    "session",
    "status",
    "founder_message",
    "message_start",
    "delta",
    "message_end",
    "handoff",
    "error",
    "done",
]

_STREAM_LIMIT_BYTES = 4 * 1024 * 1024
_WORKER_TIMEOUT_SECONDS = 600
_MAX_CONTEXT_PATHS = 16
_MAX_FOLLOW_UPS = 30
_SESSION_ID_PATTERN = re.compile(r"^bt-[0-9a-f]{12}$")
_LEADING_RECIPIENT_PATTERN = re.compile(
    r"^\s*@(claude|codex|both)(?:\s*[:,\-]\s*|\s+)", re.IGNORECASE
)
_TRAILING_RECIPIENT_PATTERN = re.compile(r"(?:^|\s)@(claude|codex|both)\s*$", re.IGNORECASE)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DebateRequest(BaseModel):
    """One bounded strategy question. Two rounds are intentionally the maximum."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=12, max_length=30_000)
    rounds: int = Field(default=1, ge=1, le=2)
    context_paths: list[str] = Field(default_factory=list, max_length=_MAX_CONTEXT_PATHS)

    @field_validator("context_paths")
    @classmethod
    def clean_context_paths(cls, paths: list[str]) -> list[str]:
        cleaned = [path.strip() for path in paths if path.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("context paths must be unique")
        if any(len(path) > 512 for path in cleaned):
            raise ValueError("context path is too long")
        return cleaned


class FounderMessageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=2, max_length=12_000)
    recipient: Recipient = "both"

    @model_validator(mode="after")
    def apply_recipient_tags(self) -> FounderMessageRequest:
        content = self.content
        leading = _LEADING_RECIPIENT_PATTERN.match(content)
        if leading is not None:
            self.recipient = leading.group(1).lower()  # type: ignore[assignment]
            content = content[leading.end() :].strip()
        trailing = _TRAILING_RECIPIENT_PATTERN.search(content)
        if trailing is not None:
            self.recipient = trailing.group(1).lower()  # type: ignore[assignment]
            content = content[: trailing.start()].strip()
        if len(content) < 2:
            raise ValueError("message content is required before the recipient tag")
        self.content = content
        return self


class InvalidContextPathError(ValueError):
    """A requested context file is outside the repository or unavailable."""


class WorkerExecutionError(RuntimeError):
    """A worker stopped without exposing provider-controlled error text."""

    def __init__(
        self,
        *,
        speaker: Literal["claude", "codex"],
        phase: str,
        reason_code: str,
        return_code: int | None = None,
        stderr_bytes: int = 0,
        partial_output_preserved: bool = False,
        error_type: str | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.speaker = speaker
        self.phase = phase
        self.reason_code = reason_code
        self.return_code = return_code
        self.stderr_bytes = stderr_bytes
        self.partial_output_preserved = partial_output_preserved
        self.error_type = error_type

    def metadata(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            "worker": self.speaker,
            "worker_phase": self.phase,
            "reason_code": self.reason_code,
            "stderr_bytes": self.stderr_bytes,
            "partial_output_preserved": self.partial_output_preserved,
        }
        if self.return_code is not None:
            details["return_code"] = self.return_code
        if self.error_type:
            details["error_type"] = self.error_type
        return details


class DebateEvent(BaseModel):
    event_id: int
    kind: EventKind
    speaker: Speaker
    phase: str
    content: str = ""
    model: str | None = None
    timestamp: str = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class FounderInterjection:
    content: str
    recipient: Recipient


@dataclass
class DebateSession:
    session_id: str
    request: DebateRequest
    events: list[DebateEvent] = field(default_factory=list)
    status: str = "queued"
    current_phase: str = "queued"
    task: asyncio.Task[None] | None = None
    process: asyncio.subprocess.Process | None = None
    wake: asyncio.Condition = field(default_factory=asyncio.Condition)
    cancel_requested: bool = False
    pending_founder_messages: list[FounderInterjection] = field(default_factory=list)
    worker_outputs: dict[str, str] = field(default_factory=dict)
    follow_up_count: int = 0


def claude_command(repo: Path) -> list[str]:
    """Return the fixed, no-edit Claude worker command."""
    executable = shutil.which("claude") or "claude"
    return [
        executable,
        "-p",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--no-session-persistence",
        "--model",
        "opus",
        "--effort",
        "max",
        "--permission-mode",
        "plan",
        "--tools",
        "Read,Glob,Grep",
        "--add-dir",
        str(repo),
    ]


def codex_command(repo: Path) -> list[str]:
    """Return the fixed, ephemeral, read-only Codex worker command."""
    executable = shutil.which("codex") or "codex"
    return [
        executable,
        "exec",
        "--ephemeral",
        "--json",
        "--ignore-user-config",
        "--ignore-rules",
        "-m",
        "gpt-5.6-sol",
        "-c",
        'model_reasoning_effort="xhigh"',
        "--sandbox",
        "read-only",
        "-C",
        str(repo),
        "-",
    ]


def _strategy_contract(question: str, context_paths: list[str] | None = None) -> str:
    paths = context_paths or []
    context = "\n".join(f"- {path}" for path in paths) or "- No additional files supplied."
    return f"""
FOUNDER QUESTION
{question}

FOUNDER-SUPPLIED REPOSITORY CONTEXT
{context}

SHARED CONTRACT
- ARIA is an independently developed, cross-department virtual employee platform.
- Do not use or reproduce private Yukti implementation details.
- Distinguish verified facts, assumptions, opinions, and future hypotheses.
- Challenge broad novelty claims and identify what would falsify each thesis.
- Think beyond engineering while preserving a narrow first commercial entry point.
- Inspect founder-supplied context files when present and cite repository-relative paths.
- No production edits. This is strategy work only.
- Return explicit reasoning summaries, not hidden chain-of-thought.
- Be concise enough for a founder to compare alternatives.
""".strip()


def _claude_proposal_prompt(question: str, context_paths: list[str] | None = None) -> str:
    return f"""You are the Venture Architect in an ARIA founder braintrust.

    {_strategy_contract(question, context_paths)}

Propose three materially different category theses for ARIA. For each include:
customer pain, buyer, why now, product mechanism, cross-department expansion,
defensibility, strongest counterargument, falsifier, and cheapest validation experiment.
End with your recommended thesis and the assumption most likely to make it fail.
"""


def _codex_challenge_prompt(
    question: str, proposal: str, context_paths: list[str] | None = None
) -> str:
    return f"""You are the Evidence Challenger in an ARIA founder braintrust.

    {_strategy_contract(question, context_paths)}

CLAUDE PROPOSAL
{proposal}

Audit the proposal adversarially against the current ARIA repository and current market.
Separate sound insight from unsupported claims. Score each thesis from 1-10 on customer
pain, differentiation, feasibility, IP safety, go-to-market, and evidence. Identify the
strongest missing alternative and specify the minimum experiment needed before coding.
"""


def _claude_rebuttal_prompt(
    question: str,
    proposal: str,
    challenge: str,
    context_paths: list[str] | None = None,
) -> str:
    return f"""You are the Venture Architect responding to a rigorous review.

    {_strategy_contract(question, context_paths)}

YOUR ORIGINAL PROPOSAL
{proposal}

CODEX CHALLENGE
{challenge}

Concede valid criticisms explicitly. Defend only claims supported by evidence. Produce a
revised category, positioning statement, universal employee kernel, first sellable role,
and 90-day validation plan. List unresolved disagreements for the founder.
"""


def _codex_synthesis_prompt(
    question: str,
    proposal: str,
    challenge: str,
    rebuttal: str,
    *,
    final_round: bool,
    context_paths: list[str] | None = None,
) -> str:
    round_note = (
        "This is the final synthesis." if final_round else "Prepare the first-round synthesis."
    )
    return f"""You are the neutral Strategy Chair for the ARIA founder braintrust.

    {_strategy_contract(question, context_paths)}

CLAUDE PROPOSAL
{proposal}

CODEX CHALLENGE
{challenge}

CLAUDE REBUTTAL
{rebuttal}

{round_note} Produce: agreed facts, remaining assumptions, decision options, recommended
direction, risks, no-code validation experiments, and the exact founder decision required.
Do not manufacture consensus. Mark every unresolved disagreement clearly.
"""


def _codex_alternative_prompt(
    question: str, synthesis: str, context_paths: list[str] | None = None
) -> str:
    return f"""You are now the divergent Venture Architect; roles have been reversed.

    {_strategy_contract(question, context_paths)}

ROUND-ONE SYNTHESIS
{synthesis}

Develop the strongest credible alternative that round one underexplored. It must support
virtual employees across departments and remain commercially focused. Include the same
evidence, counterargument, falsifier, and validation-experiment discipline.
"""


def _claude_challenge_prompt(
    question: str, alternative: str, context_paths: list[str] | None = None
) -> str:
    return f"""You are now the Evidence Challenger; roles have been reversed.

    {_strategy_contract(question, context_paths)}

CODEX ALTERNATIVE
{alternative}

Attack this alternative constructively. Check category crowding, customer urgency,
cross-department coherence, build sequence, legal/IP posture, and founder feasibility.
State what survives, what fails, and the experiment that would decide between this and
the first-round direction.
"""


def _claude_follow_up_prompt(
    question: str,
    founder_message: str,
    latest_synthesis: str,
    context_paths: list[str] | None = None,
) -> str:
    return f"""You are the Venture Architect continuing an ARIA founder braintrust.

{_strategy_contract(question, context_paths)}

LATEST BRAINTRUST SYNTHESIS
{latest_synthesis}

FOUNDER FOLLOW-UP
{founder_message}

Answer the follow-up directly. Re-open assumptions when necessary, cite repository paths,
and finish with the decision or experiment the founder should make next.
"""


def _codex_follow_up_prompt(
    question: str,
    founder_message: str,
    claude_response: str,
    context_paths: list[str] | None = None,
) -> str:
    return f"""You are the Evidence Challenger and Strategy Chair continuing an ARIA founder
braintrust.

{_strategy_contract(question, context_paths)}

FOUNDER FOLLOW-UP
{founder_message}

CLAUDE RESPONSE
{claude_response}

Challenge unsupported claims, preserve valid insights, and give a concise decision-ready
    synthesis. Cite repository paths where they support a claim. Do not manufacture consensus.
    """


def _codex_direct_follow_up_prompt(
    question: str,
    founder_message: str,
    latest_synthesis: str,
    context_paths: list[str] | None = None,
) -> str:
    return f"""You are the Evidence Challenger and Strategy Chair continuing an ARIA founder
braintrust. The founder addressed this message directly to Codex; do not wait for or simulate
a Claude response.

{_strategy_contract(question, context_paths)}

LATEST SAVED BRAINTRUST OUTPUT
{latest_synthesis}

FOUNDER MESSAGE TO CODEX
{founder_message}

Answer the founder directly. Challenge unsupported claims, cite repository paths where they
support a claim, and finish with a concise decision or next experiment.
"""


class BraintrustManager:
    """Own local sessions and stream explicit model messages to browser clients."""

    def __init__(
        self,
        *,
        repo: Path | None = None,
        data_dir: Path | None = None,
        process_factory: Callable[..., Any] = asyncio.create_subprocess_exec,
    ) -> None:
        self.repo = (repo or Path(__file__).resolve().parents[4]).resolve()
        base = data_dir or Path(os.getenv("ARIA_DATA_DIR", self.repo / ".aria_data"))
        self.data_dir = (base / "braintrust").resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, DebateSession] = {}
        self._process_factory = process_factory

    async def create(self, request: DebateRequest) -> DebateSession:
        resolved_paths = self._resolve_context_paths(request.context_paths)
        sanitized_question = sanitize_text(request.question) or ""
        request = DebateRequest.model_validate(
            {
                **request.model_dump(),
                "question": sanitized_question,
                "context_paths": resolved_paths,
            }
        )
        session = DebateSession(session_id=f"bt-{uuid.uuid4().hex[:12]}", request=request)
        self._sessions[session.session_id] = session
        self._emit(
            session,
            "session",
            "founder",
            "question",
            request.question,
            metadata={
                "rounds": request.rounds,
                "context_paths": request.context_paths,
            },
        )
        if request.context_paths:
            self._emit(
                session,
                "status",
                "system",
                "context",
                "Context files: " + ", ".join(request.context_paths),
            )
        session.task = asyncio.create_task(self._run_debate(session))
        return session

    def _resolve_context_paths(self, paths: list[str]) -> list[str]:
        resolved: list[str] = []
        for supplied in paths:
            if sanitize_text(supplied) != supplied:
                raise InvalidContextPathError("context path contains sensitive text")
            candidate = Path(supplied)
            target = (candidate if candidate.is_absolute() else self.repo / candidate).resolve()
            try:
                relative = target.relative_to(self.repo)
            except ValueError as exc:
                raise InvalidContextPathError(
                    "context files must be located inside the ARIA repository"
                ) from exc
            if not target.is_file():
                raise InvalidContextPathError(f"context file is unavailable: {relative.as_posix()}")
            resolved.append(relative.as_posix())
        return resolved

    def get(self, session_id: str) -> DebateSession:
        if session_id in self._sessions:
            return self._sessions[session_id]
        session = self._load_session(session_id)
        if session is None:
            raise KeyError("unknown braintrust session")
        self._sessions[session_id] = session
        return session

    def _load_session(self, session_id: str) -> DebateSession | None:
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            return None
        path = self.data_dir / f"{session_id}.jsonl"
        if not path.is_file():
            return None
        try:
            events = [
                DebateEvent.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, ValueError):
            return None
        question_event = next(
            (event for event in events if event.kind == "session" and event.phase == "question"),
            None,
        )
        if question_event is None:
            return None
        metadata = question_event.metadata
        try:
            request = DebateRequest(
                question=question_event.content,
                rounds=int(metadata.get("rounds", 1)),
                context_paths=list(metadata.get("context_paths") or []),
            )
        except (TypeError, ValueError):
            return None

        outputs: dict[str, str] = {}
        active_phase: str | None = None
        active_pieces: list[str] = []
        for event in events:
            if event.kind == "message_start":
                active_phase = event.phase
                active_pieces = []
            elif event.kind == "delta" and active_phase == event.phase:
                active_pieces.append(event.content)
            elif event.kind == "message_end" and active_phase == event.phase:
                content = "".join(active_pieces).strip()
                if content:
                    suffix = "-partial" if event.metadata.get("partial") else ""
                    outputs[f"{active_phase}{suffix}"] = content
                active_phase = None
                active_pieces = []
        if active_phase and active_pieces:
            outputs[f"{active_phase}-partial"] = "".join(active_pieces).strip()

        final = events[-1] if events else question_event
        if final.kind == "done":
            status = "cancelled" if final.phase == "cancelled" else "completed"
        elif final.kind == "error":
            status = "failed"
        else:
            status = "failed"
        return DebateSession(
            session_id=session_id,
            request=request,
            events=events,
            status=status,
            current_phase=final.phase,
            worker_outputs=outputs,
            follow_up_count=sum(1 for event in events if event.kind == "founder_message"),
        )

    async def add_founder_message(self, session_id: str, request: FounderMessageRequest) -> str:
        session = self.get(session_id)
        if session.status == "cancelled":
            raise RuntimeError("start a new session after a cancelled session")
        if session.status != "running" and session.follow_up_count >= _MAX_FOLLOW_UPS:
            raise RuntimeError("follow-up limit reached for this session")
        content = sanitize_text(request.content) or "[redacted]"
        await self._emit_async(
            session,
            "founder_message",
            "founder",
            "founder-follow-up",
            content,
            metadata={"recipient": request.recipient},
        )
        if session.status == "running":
            session.pending_founder_messages.append(
                FounderInterjection(content=content, recipient=request.recipient)
            )
            return f"queued_for_{request.recipient}"
        session.follow_up_count += 1
        session.status = "running"
        session.cancel_requested = False
        session.task = asyncio.create_task(
            self._run_follow_up(session, content, request.recipient)
        )
        return "follow_up_started"

    def export_markdown(self, session_id: str) -> str:
        session = self.get(session_id)
        lines = [
            "# ARIA Braintrust Transcript",
            "",
            f"Session: `{session.session_id}`",
            f"Status: `{session.status}`",
            "",
            "## Founder Question",
            "",
            session.request.question,
        ]
        if session.request.context_paths:
            lines.extend(["", "## Context Files", ""])
            lines.extend(f"- `{path}`" for path in session.request.context_paths)

        active: dict[str, str] | None = None
        for event in session.events:
            if event.kind == "message_start":
                active = {
                    "speaker": event.speaker.title(),
                    "model": event.model or "",
                    "content": "",
                }
            elif event.kind == "delta" and active is not None:
                active["content"] += event.content
            elif event.kind == "message_end" and active is not None:
                heading = active["speaker"]
                if active["model"]:
                    heading += f" ({active['model']})"
                lines.extend(["", f"## {heading}", "", active["content"].strip()])
                active = None
            elif event.kind == "founder_message":
                recipient = event.metadata.get("recipient", "both")
                lines.extend(
                    ["", f"## Founder Follow-up -> @{recipient}", "", event.content]
                )
            elif event.kind == "handoff":
                target = event.metadata.get("target", "human")
                lines.extend(["", f"**Handoff:** {event.speaker.title()} -> @{target}"])
            elif event.kind in {"error", "done"}:
                lines.extend(["", "## Session Status", "", event.content])
        return "\n".join(lines).strip() + "\n"

    async def cancel(self, session_id: str) -> None:
        session = self.get(session_id)
        session.cancel_requested = True
        if session.task and not session.task.done():
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.task
        elif session.process and session.process.returncode is None:
            session.process.terminate()
            with contextlib.suppress(ProcessLookupError):
                await session.process.wait()
        session.status = "cancelled"
        session.current_phase = "cancelled"
        await self._emit_async(
            session, "done", "system", "cancelled", "Session stopped by founder."
        )

    async def events(self, session_id: str, after: int = 0) -> AsyncIterator[DebateEvent]:
        session = self.get(session_id)
        cursor = max(0, after)
        while True:
            while cursor < len(session.events):
                event = session.events[cursor]
                cursor += 1
                yield event
            if session.status in {"completed", "failed", "cancelled"}:
                return
            async with session.wake:
                try:
                    await asyncio.wait_for(session.wake.wait(), timeout=12)
                except TimeoutError:
                    yield DebateEvent(
                        event_id=cursor,
                        kind="status",
                        speaker="system",
                        phase=session.current_phase,
                        content="Working...",
                        metadata={"ephemeral": True},
                    )

    def _emit(
        self,
        session: DebateSession,
        kind: EventKind,
        speaker: Speaker,
        phase: str,
        content: str = "",
        *,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DebateEvent:
        event = DebateEvent(
            event_id=len(session.events),
            kind=kind,
            speaker=speaker,
            phase=phase,
            content=content,
            model=model,
            metadata=metadata or {},
        )
        session.events.append(event)
        path = self.data_dir / f"{session.session_id}.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.model_dump_json() + "\n")
        return event

    async def _emit_async(self, *args: Any, **kwargs: Any) -> DebateEvent:
        session: DebateSession = args[0]
        event = self._emit(*args, **kwargs)
        async with session.wake:
            session.wake.notify_all()
        return event

    async def _run_debate(self, session: DebateSession) -> None:
        try:
            session.status = "running"
            question = session.request.question
            context_paths = session.request.context_paths
            proposal = await self._run_worker(
                session,
                "claude",
                "round-1-proposal",
                _claude_proposal_prompt(question, context_paths),
                handoff_to="codex",
            )
            challenge = await self._run_worker(
                session,
                "codex",
                "round-1-challenge",
                _codex_challenge_prompt(question, proposal, context_paths),
                handoff_to="claude",
            )
            rebuttal = await self._run_worker(
                session,
                "claude",
                "round-1-rebuttal",
                _claude_rebuttal_prompt(question, proposal, challenge, context_paths),
                handoff_to="codex",
            )
            synthesis = await self._run_worker(
                session,
                "codex",
                "round-1-synthesis",
                _codex_synthesis_prompt(
                    question,
                    proposal,
                    challenge,
                    rebuttal,
                    final_round=session.request.rounds == 1,
                    context_paths=context_paths,
                ),
                handoff_to="codex" if session.request.rounds == 2 else "human",
            )
            if session.request.rounds == 2:
                alternative = await self._run_worker(
                    session,
                    "codex",
                    "round-2-alternative",
                    _codex_alternative_prompt(question, synthesis, context_paths),
                    handoff_to="claude",
                )
                second_challenge = await self._run_worker(
                    session,
                    "claude",
                    "round-2-challenge",
                    _claude_challenge_prompt(question, alternative, context_paths),
                    handoff_to="codex",
                )
                await self._run_worker(
                    session,
                    "codex",
                    "round-2-final-synthesis",
                    _codex_synthesis_prompt(
                        question,
                        synthesis,
                        alternative,
                        second_challenge,
                        final_round=True,
                        context_paths=context_paths,
                    ),
                    handoff_to="human",
                )
            await self._drain_pending_interjections(session)
            session.status = "completed"
            session.current_phase = "completed"
            await self._emit_async(
                session,
                "done",
                "system",
                "completed",
                "Braintrust complete. Founder decision is required before strategy changes.",
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await self._record_worker_failure(session, exc)

    async def _run_follow_up(
        self,
        session: DebateSession,
        founder_message: str,
        recipient: Recipient,
    ) -> None:
        try:
            await self._run_follow_up_exchange(session, founder_message, recipient)
            await self._drain_pending_interjections(session)
            session.status = "completed"
            session.current_phase = "completed"
            await self._emit_async(
                session,
                "done",
                "system",
                "completed",
                "Follow-up complete. Founder decision is required before strategy changes.",
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await self._record_worker_failure(session, exc)

    async def _run_follow_up_exchange(
        self,
        session: DebateSession,
        founder_message: str,
        recipient: Recipient,
    ) -> None:
        session.current_phase = "founder-follow-up"
        latest_synthesis = next(
            reversed(session.worker_outputs.values()),
            "No prior synthesis is available; answer from the founder question and repository.",
        )
        claude_response: str | None = None
        if recipient in {"claude", "both"}:
            claude_response = await self._run_worker(
                session,
                "claude",
                f"follow-up-{session.follow_up_count}-claude",
                _claude_follow_up_prompt(
                    session.request.question,
                    founder_message,
                    latest_synthesis,
                    session.request.context_paths,
                ),
                handoff_to="codex" if recipient == "both" else "human",
            )
        if recipient in {"codex", "both"}:
            prompt = (
                _codex_follow_up_prompt(
                    session.request.question,
                    founder_message,
                    claude_response,
                    session.request.context_paths,
                )
                if claude_response is not None
                else _codex_direct_follow_up_prompt(
                    session.request.question,
                    founder_message,
                    latest_synthesis,
                    session.request.context_paths,
                )
            )
            await self._run_worker(
                session,
                "codex",
                f"follow-up-{session.follow_up_count}-codex",
                prompt,
                handoff_to="human",
            )

    async def _drain_pending_interjections(self, session: DebateSession) -> None:
        while session.pending_founder_messages:
            interjection = session.pending_founder_messages.pop(0)
            session.follow_up_count += 1
            await self._run_follow_up_exchange(
                session,
                interjection.content,
                interjection.recipient,
            )

    async def _emit_handoff(
        self,
        session: DebateSession,
        speaker: Literal["claude", "codex"],
        phase: str,
        target: HandoffTarget,
    ) -> None:
        await self._emit_async(
            session,
            "handoff",
            speaker,
            phase,
            f"@{target}",
            metadata={"target": target},
        )

    async def _record_worker_failure(
        self, session: DebateSession, exc: Exception
    ) -> None:
        session.status = "failed"
        session.current_phase = "failed"
        if isinstance(exc, WorkerExecutionError):
            phase = exc.phase.replace("-", " ")
            content = (
                f"{exc.speaker.title()} stopped during {phase} "
                f"({exc.reason_code}"
                + (f", exit {exc.return_code}" if exc.return_code is not None else "")
                + "). Raw provider details were not exposed."
            )
            if exc.partial_output_preserved:
                content += " The partial response was preserved."
            content += " Send a founder message to continue from the saved transcript."
            metadata = exc.metadata()
        else:
            content = (
                f"Worker failed safely ({type(exc).__name__}). Raw provider details were not "
                "exposed. Send a founder message to continue from the saved transcript."
            )
            metadata = {"reason_code": "internal_error", "error_type": type(exc).__name__}
        await self._emit_async(
            session,
            "error",
            "system",
            "failed",
            content,
            metadata=metadata,
        )

    async def _preserve_partial_output(
        self,
        session: DebateSession,
        speaker: Literal["claude", "codex"],
        phase: str,
        model: str,
        pieces: list[str],
        metadata: dict[str, Any],
    ) -> bool:
        content = "".join(pieces).strip()
        if not content:
            return False
        session.worker_outputs[f"{phase}-partial"] = content
        await self._emit_async(
            session,
            "message_end",
            speaker,
            phase,
            "",
            model=model,
            metadata={**metadata, "partial": True},
        )
        return True

    async def _run_worker(
        self,
        session: DebateSession,
        speaker: Literal["claude", "codex"],
        phase: str,
        prompt: str,
        *,
        handoff_to: HandoffTarget | None = None,
    ) -> str:
        if session.cancel_requested:
            raise asyncio.CancelledError
        session.current_phase = phase
        if session.pending_founder_messages:
            matching = [
                message
                for message in session.pending_founder_messages
                if message.recipient in {speaker, "both"}
            ]
            session.pending_founder_messages = [
                message
                for message in session.pending_founder_messages
                if message.recipient not in {speaker, "both"}
            ]
            if matching:
                updates = "\n\n".join(message.content for message in matching)
                prompt += (
                    "\n\nFOUNDER INTERJECTIONS ADDRESSED TO YOU\n"
                    f"{updates}\n\nAddress these explicitly in this turn."
                )
        model = "Claude Opus 5" if speaker == "claude" else "GPT-5.6 Sol - xhigh"
        await self._emit_async(
            session,
            "message_start",
            speaker,
            phase,
            "",
            model=model,
        )
        command = claude_command(self.repo) if speaker == "claude" else codex_command(self.repo)
        try:
            process = await self._process_factory(
                *command,
                cwd=str(self.repo),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT_BYTES,
            )
        except Exception as exc:
            raise WorkerExecutionError(
                speaker=speaker,
                phase=phase,
                reason_code="worker_unavailable",
                error_type=type(exc).__name__,
            ) from exc
        session.process = process
        assert process.stdin and process.stdout and process.stderr
        process.stdin.write(prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

        pieces: list[str] = []
        metadata: dict[str, Any] = {}
        stderr_task = asyncio.create_task(process.stderr.read())
        try:
            async with asyncio.timeout(_WORKER_TIMEOUT_SECONDS):
                while line := await process.stdout.readline():
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if speaker == "claude":
                        chunk = self._claude_chunk(payload)
                        if payload.get("type") == "system" and payload.get("subtype") == "init":
                            metadata["reported_model"] = payload.get("model")
                        if payload.get("type") == "result":
                            usage = payload.get("usage") or {}
                            metadata.update(
                                {
                                    "duration_ms": payload.get("duration_ms"),
                                    "input_tokens": usage.get("input_tokens"),
                                    "output_tokens": usage.get("output_tokens"),
                                }
                            )
                    else:
                        chunk = self._codex_chunk(payload)
                        if payload.get("type") == "thread.started":
                            metadata["thread_id"] = payload.get("thread_id")
                        if payload.get("type") == "turn.completed":
                            metadata.update(payload.get("usage") or {})
                    if chunk:
                        pieces.append(chunk)
                        await self._emit_async(session, "delta", speaker, phase, chunk, model=model)

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
            partial = await self._preserve_partial_output(
                session, speaker, phase, model, pieces, metadata
            )
            raise WorkerExecutionError(
                speaker=speaker,
                phase=phase,
                reason_code="worker_timeout",
                partial_output_preserved=partial,
            ) from exc
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
            partial = await self._preserve_partial_output(
                session, speaker, phase, model, pieces, metadata
            )
            raise WorkerExecutionError(
                speaker=speaker,
                phase=phase,
                reason_code="stream_error",
                partial_output_preserved=partial,
                error_type=type(exc).__name__,
            ) from exc
        finally:
            session.process = None
        if return_code != 0:
            partial = await self._preserve_partial_output(
                session, speaker, phase, model, pieces, metadata
            )
            raise WorkerExecutionError(
                speaker=speaker,
                phase=phase,
                reason_code="process_exit",
                return_code=return_code,
                stderr_bytes=len(stderr),
                partial_output_preserved=partial,
            )
        content = "".join(pieces).strip()
        if not content:
            raise WorkerExecutionError(
                speaker=speaker,
                phase=phase,
                reason_code="empty_response",
            )
        session.worker_outputs[phase] = content
        await self._emit_async(
            session,
            "message_end",
            speaker,
            phase,
            "",
            model=model,
            metadata=metadata,
        )
        if handoff_to is not None:
            await self._emit_handoff(session, speaker, phase, handoff_to)
        return content

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
    def _codex_chunk(payload: dict[str, Any]) -> str:
        if payload.get("type") != "item.completed":
            return ""
        item = payload.get("item") or {}
        return str(item.get("text", "")) if item.get("type") == "agent_message" else ""


__all__ = [
    "BraintrustManager",
    "DebateEvent",
    "DebateRequest",
    "FounderMessageRequest",
    "InvalidContextPathError",
    "claude_command",
    "codex_command",
]
