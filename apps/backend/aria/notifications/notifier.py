"""
Proactive Notification Infrastructure — Week 19

Governed delivery of alerts via Teams (mock) and console.
Every notification is a skill output — not a side-effect.

Rules:
  - CI/CD failure  → #engineering, 30-min cooldown per pipeline
  - PR risk HIGH+  → DM to PR author, per-PR cooldown
  - Severity maps to urgency: critical=immediate, high=30min, medium/low=batch

Governance:
  - Cooldown windows prevent alert fatigue
  - Every notification logged to Work Ledger (appended to notifications.jsonl)
  - notify_team=False on skill output → no notification emitted
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# ── Models ─────────────────────────────────────────────────────────────────────

class NotificationPayload(BaseModel):
    channel:    str                                   # "#engineering", "dm:user_id"
    title:      str
    body:       str
    severity:   Literal["critical", "high", "medium", "low"]
    source:     str                                   # skill that triggered this
    task_id:    str
    pipeline:   str = ""
    timestamp:  str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class DeliveryResult(BaseModel):
    sent:       bool
    channel:    str
    reason:     str                                   # "delivered" | "cooldown" | "suppressed"
    cooldown_remaining_s: int = 0


# ── Cooldown Store ─────────────────────────────────────────────────────────────

class _CooldownStore:
    """In-memory cooldown tracker. Key = (channel, pipeline)."""

    def __init__(self):
        self._last_sent: dict[tuple[str, str], datetime] = {}

    def is_cooling(self, channel: str, pipeline: str, window_s: int) -> tuple[bool, int]:
        key = (channel, pipeline)
        last = self._last_sent.get(key)
        if last is None:
            return False, 0
        elapsed = (datetime.utcnow() - last).total_seconds()
        remaining = int(window_s - elapsed)
        return remaining > 0, max(0, remaining)

    def mark_sent(self, channel: str, pipeline: str) -> None:
        self._last_sent[(channel, pipeline)] = datetime.utcnow()

    def clear(self) -> None:
        self._last_sent.clear()


_cooldowns = _CooldownStore()


# ── Notification Log ───────────────────────────────────────────────────────────

_LOG_PATH = Path(__file__).parent.parent.parent / "notifications.jsonl"


def _log(payload: NotificationPayload, result: DeliveryResult) -> None:
    entry = {
        "ts":       payload.timestamp,
        "task_id":  payload.task_id,
        "channel":  payload.channel,
        "source":   payload.source,
        "severity": payload.severity,
        "sent":     result.sent,
        "reason":   result.reason,
        "title":    payload.title,
    }
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Teams Delivery (mock) ──────────────────────────────────────────────────────

def _teams_send(payload: NotificationPayload) -> None:
    """Mock Teams delivery — prints the card to console."""
    bar = "═" * 60
    severity_icon = {"critical": "🚨", "high": "⚠️ ", "medium": "ℹ️ ", "low": "📋"}.get(payload.severity, "•")
    print(f"\n{bar}")
    print(f"  [TEAMS → {payload.channel}]  {severity_icon} {payload.title}")
    print(f"  {payload.body}")
    if payload.pipeline:
        print(f"  Pipeline: {payload.pipeline}")
    print(f"  Source: {payload.source}  |  Task: {payload.task_id[:12]}...")
    print(f"  {bar}\n")


# ── Public API ─────────────────────────────────────────────────────────────────

_COOLDOWN_WINDOWS: dict[str, int] = {
    "critical": 0,      # no cooldown — always send
    "high":     1800,   # 30 minutes
    "medium":   3600,   # 1 hour
    "low":      86400,  # 1 day
}


def notify(
    payload: NotificationPayload,
    *,
    override_cooldown: bool = False,
) -> DeliveryResult:
    """
    Deliver a notification with cooldown governance.

    Args:
        payload:          The notification to send.
        override_cooldown: Force send regardless of cooldown (use for critical incidents only).
    """
    window_s = _COOLDOWN_WINDOWS.get(payload.severity, 1800)

    if not override_cooldown and window_s > 0:
        cooling, remaining = _cooldowns.is_cooling(payload.channel, payload.pipeline, window_s)
        if cooling:
            result = DeliveryResult(
                sent=False,
                channel=payload.channel,
                reason="cooldown",
                cooldown_remaining_s=remaining,
            )
            _log(payload, result)
            return result

    _teams_send(payload)
    _cooldowns.mark_sent(payload.channel, payload.pipeline)

    result = DeliveryResult(sent=True, channel=payload.channel, reason="delivered")
    _log(payload, result)
    return result


def notify_ci_cd_failure(
    *,
    task_id: str,
    pipeline_name: str,
    failure_summary: str,
    severity: Literal["critical", "high", "medium", "low"],
    suggested_fix: str,
    notify_team: bool,
) -> DeliveryResult | None:
    """
    CI/CD-specific notification helper.
    Returns None if notify_team=False (suppressed by skill output).
    """
    if not notify_team:
        return None

    channel = "#engineering"
    body = f"{failure_summary}\nSuggested fix: {suggested_fix}"

    payload = NotificationPayload(
        channel=channel,
        title=f"CI/CD Failure — {pipeline_name or 'unknown pipeline'}",
        body=body,
        severity=severity,
        source="ci_cd_skill",
        task_id=task_id,
        pipeline=pipeline_name,
    )
    return notify(payload, override_cooldown=(severity == "critical"))


def reset_cooldowns() -> None:
    """Test helper — clears all cooldown state."""
    _cooldowns.clear()
