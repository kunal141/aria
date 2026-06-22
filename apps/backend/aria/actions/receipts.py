"""
Execution receipt builders (V3.9).

A receipt is the artifact of an execution attempt. In V3.9 it is always a dry-run,
mock, blocked, or failed receipt — never proof of a real external write. Summaries are
safe (no secrets, no raw exception text) and always carry a rollback + compensation
note (advisory for dry-run/mock).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from aria.actions.models import ActionIntent, ActionReceipt, ExecutionMode


def _rid() -> str:
    return f"rcpt-{uuid.uuid4().hex}"


def dry_run_receipt(intent: ActionIntent, *, rollback_note: str, compensation_note: str,
                    executed_by: str, now: datetime) -> ActionReceipt:
    return ActionReceipt(
        receipt_id=_rid(), action_id=intent.action_id, target_system=intent.target_system,
        execution_mode=ExecutionMode.dry_run, executed_at=now, executed_by=executed_by,
        result_status="dry_run_ok", external_ref=None,
        receipt_summary=(f"DRY RUN: would '{intent.action_type.value}' on "
                         f"'{intent.target_system.value}'. Nothing was sent; no external "
                         "system was touched."),
        rollback_note=rollback_note, compensation_note=compensation_note,
    )


def mock_receipt(intent: ActionIntent, *, rollback_note: str, compensation_note: str,
                 executed_by: str, now: datetime) -> ActionReceipt:
    return ActionReceipt(
        receipt_id=_rid(), action_id=intent.action_id, target_system=intent.target_system,
        execution_mode=ExecutionMode.mock_live, executed_at=now, executed_by=executed_by,
        result_status="mock_executed",
        external_ref=f"mock://{intent.target_system.value}/{intent.action_id}",
        receipt_summary=(f"MOCK LIVE: simulated '{intent.action_type.value}' on "
                         "'internal_mock'. Recorded only in ARIA's local receipt store; "
                         "no external system, network, or connector was touched."),
        rollback_note=("Mock-only: delete this mock receipt to undo. " + rollback_note),
        compensation_note=compensation_note,
    )


def failed_receipt(intent: ActionIntent, *, mode: ExecutionMode, safe_error: str,
                   rollback_note: str, compensation_note: str, executed_by: str,
                   now: datetime) -> ActionReceipt:
    return ActionReceipt(
        receipt_id=_rid(), action_id=intent.action_id, target_system=intent.target_system,
        execution_mode=mode, executed_at=now, executed_by=executed_by, result_status="failed",
        external_ref=None,
        receipt_summary=(f"FAILED safely during '{mode.value}' of '{intent.action_type.value}'. "
                         f"safe_error={safe_error} (class only). No external write occurred."),
        rollback_note=rollback_note, compensation_note=compensation_note,
    )


def blocked_receipt(intent: ActionIntent, *, mode: ExecutionMode, reasons: list[str],
                    rollback_note: str, compensation_note: str, executed_by: str,
                    now: datetime) -> ActionReceipt:
    summary = "BLOCKED by policy (deny-by-default): " + "; ".join(reasons or ["not permitted"])
    return ActionReceipt(
        receipt_id=_rid(), action_id=intent.action_id, target_system=intent.target_system,
        execution_mode=mode, executed_at=now, executed_by=executed_by, result_status="blocked",
        external_ref=None, receipt_summary=summary[:500],
        rollback_note="Nothing executed — no rollback required.",
        compensation_note=compensation_note,
    )
