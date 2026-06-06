"""
Audit Log — Week 15

Append-only JSONL log of every tool invocation, permission check, and
security event. Never stores raw inputs — only hashes and metadata.

Why append-only JSONL:
  - Immutable by convention (no delete or update operations)
  - Line-per-entry = easy to tail, grep, and stream to SIEM
  - JSON per line = queryable with jq or pandas without parsing overhead
  - No external dependency — plain file I/O

What gets logged:
  - Every tool invocation (allowed AND blocked)
  - Permission check results
  - PII redaction events (count of redactions, not what was redacted)
  - Data sensitivity assignments

What is NEVER logged:
  - Raw user input or skill output (use LangSmith for that)
  - API keys, tokens, secrets
  - PII (the redactor runs before audit logging)

The input_hash field uses a one-way SHA-256 hash of the raw input so you
can correlate audit entries with LangSmith traces without storing the data.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional


_AUDIT_FILE = os.environ.get("ARIA_AUDIT_LOG_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "..", "tool_audit.jsonl"
)


# ── Public API ────────────────────────────────────────────────────────────────

def log_tool_call(
    task_id: str,
    tool_name: str,
    allowed: bool,
    reason: str,
    action_tier: Optional[str] = None,
    data_sensitivity: Optional[str] = None,
    input_preview: Optional[str] = None,   # will be hashed, never stored raw
    outcome: Optional[str] = None,          # "success" | "error" | "blocked"
    error: Optional[str] = None,
) -> None:
    """Log a tool invocation to tool_audit.jsonl."""
    entry = {
        "ts":               _now(),
        "event":            "tool_call",
        "task_id":          task_id,
        "tool_name":        tool_name,
        "allowed":          allowed,
        "action_tier":      action_tier,
        "data_sensitivity": data_sensitivity,
        "input_hash":       _hash(input_preview) if input_preview else None,
        "outcome":          outcome or ("blocked" if not allowed else "success"),
        "reason":           reason,
        "error":            error,
    }
    _append(entry)


def log_sensitivity_assignment(
    task_id: str,
    sensitivity: str,
    source: str,           # "inferred" | "explicit" | "default"
    task_type: Optional[str] = None,
) -> None:
    """Log when data_sensitivity is assigned to a task."""
    entry = {
        "ts":          _now(),
        "event":       "sensitivity_assigned",
        "task_id":     task_id,
        "sensitivity": sensitivity,
        "source":      source,
        "task_type":   task_type,
    }
    _append(entry)


def log_pii_redaction(
    task_id: str,
    context: str,           # "langsmith_trace" | "audit_log" | "response"
    redaction_count: int,   # how many replacements were made
    sensitivity: Optional[str] = None,
) -> None:
    """Log that PII redaction occurred (count only, never what was redacted)."""
    if redaction_count == 0:
        return
    entry = {
        "ts":               _now(),
        "event":            "pii_redacted",
        "task_id":          task_id,
        "context":          context,
        "redaction_count":  redaction_count,
        "data_sensitivity": sensitivity,
    }
    _append(entry)


def log_security_event(
    task_id: str,
    event_type: str,    # e.g. "secret_detected_in_input", "tier_violation_attempt"
    detail: str,
    severity: str = "warn",   # "info" | "warn" | "critical"
) -> None:
    """Log an arbitrary security event."""
    entry = {
        "ts":        _now(),
        "event":     "security_event",
        "task_id":   task_id,
        "type":      event_type,
        "severity":  severity,
        "detail":    detail,
    }
    _append(entry)


def tail(n: int = 20) -> list[dict]:
    """Return the last n entries from the audit log."""
    entries = _load_all()
    return entries[-n:]


def query(task_id: str) -> list[dict]:
    """Return all audit entries for a given task_id."""
    return [e for e in _load_all() if e.get("task_id") == task_id]


# ── Internal ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _append(entry: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_AUDIT_FILE), exist_ok=True)
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass   # audit log failure must never block task execution


def _load_all() -> list[dict]:
    if not os.path.exists(_AUDIT_FILE):
        return []
    entries = []
    try:
        with open(_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    return entries
