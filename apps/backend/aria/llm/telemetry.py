"""
Model telemetry events — Week 31 item 6 (V2 plan §6 / §17).

We do NOT add a new ledger event type. The existing Work Ledger v2 ``ModelUsed``
event already carries model name, latency (``duration_ms``), token counts
(``token_input`` / ``token_output``), failure (``status`` / ``error``), and
``outcome``. The only V2-new facts — **provider** and **execution mode** — go
into the event's sanitised ``metadata`` (per the accepted plan §17: reuse
``model_used`` / ``cost_recorded`` with V2 metadata, don't duplicate event types).

The envelope's validators redact credential-shaped substrings from free-text
fields, so we deliberately record only an error *class/reason*, never raw
exception text.
"""
from __future__ import annotations

from aria.ledger import ActorType, ModelUsed
from aria.ledger.events import make_envelope


def build_model_telemetry_event(
    *,
    task_id: str,
    model_name: str,
    provider: str,
    execution_mode: str,
    latency_ms: int | None = None,
    token_input: int | None = None,
    token_output: int | None = None,
    status: str = "ok",
    outcome: str | None = None,
    failure_reason: str | None = None,
    correlation_id: str | None = None,
    actor: str = "aria",
    actor_type: ActorType = ActorType.aria,
) -> ModelUsed:
    """Build (but do not persist) a ``ModelUsed`` telemetry event.

    ``provider`` and ``execution_mode`` are stored in ``metadata`` (sanitised at
    the type boundary). ``failure_reason`` should be a short label / exception
    class name — never raw exception text.
    """
    envelope = make_envelope(
        task_id=task_id,
        actor=actor,
        actor_type=actor_type,
        correlation_id=correlation_id,
        model_name=model_name,
        duration_ms=latency_ms,
        token_input=token_input,
        token_output=token_output,
        status=status,
        outcome=outcome,
        error=failure_reason,
        metadata={"provider": provider, "execution_mode": execution_mode},
    )
    return ModelUsed(**envelope)


def record_model_telemetry(*, writer=None, **kwargs) -> bool:
    """Append a ``ModelUsed`` telemetry event to the Work Ledger.

    Uses the default v2 writer unless one is injected (tests inject an isolated
    writer; the autouse conftest fixture also redirects the default writer to a
    temp file). Returns the writer's ``append`` result (``True`` if newly
    written).
    """
    if writer is None:
        from aria.ledger.writer import get_default_writer

        writer = get_default_writer()
    return writer.append(build_model_telemetry_event(**kwargs))
