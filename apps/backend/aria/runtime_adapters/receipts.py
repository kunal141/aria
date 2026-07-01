"""
Runtime-adapter receipt builders (V4.1).

A receipt is the artifact of an adapter interaction. In V4.1 it is always a preview,
blocked, dry-run, mock, or failed receipt — never proof of a real external run. Summaries
are safe (no secrets, no raw exception text). Only the internal_mock adapter's mock
receipt carries a ``mock://internal_mock/…`` reference; nothing is a real external id.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from aria.runtime_adapters.models import (
    ExecutionMode,
    ReceiptStatus,
    RuntimeAdapterReceipt,
    RuntimeAdapterRequest,
)


def _rid() -> str:
    return f"radr-{uuid.uuid4().hex}"


def preview_receipt(request: RuntimeAdapterRequest, *, summary: str, now: datetime
                    ) -> RuntimeAdapterReceipt:
    return RuntimeAdapterReceipt(
        receipt_id=_rid(), request_id=request.request_id, adapter_id=request.adapter_id,
        execution_mode=ExecutionMode.preview, status=ReceiptStatus.previewed,
        output_summary=summary[:500], source_refs=list(request.source_refs),
        evidence_refs=list(request.evidence_refs), external_ref=None, created_at=now)


def blocked_receipt(request: RuntimeAdapterRequest, *, mode: ExecutionMode, reasons: list[str],
                    now: datetime) -> RuntimeAdapterReceipt:
    summary = "BLOCKED by policy (deny-by-default): " + "; ".join(reasons or ["not permitted"])
    return RuntimeAdapterReceipt(
        receipt_id=_rid(), request_id=request.request_id, adapter_id=request.adapter_id,
        execution_mode=mode, status=ReceiptStatus.blocked, output_summary=summary[:500],
        source_refs=list(request.source_refs), evidence_refs=list(request.evidence_refs),
        external_ref=None, created_at=now)


def dry_run_receipt(request: RuntimeAdapterRequest, *, summary: str,
                    output_payload: dict[str, Any] | None = None, now: datetime
                    ) -> RuntimeAdapterReceipt:
    return RuntimeAdapterReceipt(
        receipt_id=_rid(), request_id=request.request_id, adapter_id=request.adapter_id,
        execution_mode=ExecutionMode.dry_run, status=ReceiptStatus.dry_run_completed,
        output_summary=summary[:500], output_payload=output_payload or {},
        source_refs=list(request.source_refs), evidence_refs=list(request.evidence_refs),
        external_ref=None, created_at=now)


def mock_receipt(request: RuntimeAdapterRequest, *, summary: str,
                 output_payload: dict[str, Any] | None = None, now: datetime
                 ) -> RuntimeAdapterReceipt:
    return RuntimeAdapterReceipt(
        receipt_id=_rid(), request_id=request.request_id, adapter_id=request.adapter_id,
        execution_mode=ExecutionMode.mock, status=ReceiptStatus.mock_completed,
        output_summary=summary[:500], output_payload=output_payload or {},
        source_refs=list(request.source_refs), evidence_refs=list(request.evidence_refs),
        external_ref=f"mock://internal_mock/{request.request_id}", created_at=now)


def failed_receipt(request: RuntimeAdapterRequest, *, mode: ExecutionMode, safe_error: str,
                   now: datetime) -> RuntimeAdapterReceipt:
    return RuntimeAdapterReceipt(
        receipt_id=_rid(), request_id=request.request_id, adapter_id=request.adapter_id,
        execution_mode=mode, status=ReceiptStatus.failed,
        output_summary=f"FAILED safely during {mode.value}; safe_error={safe_error} "
                       "(class only). No external write occurred.",
        source_refs=list(request.source_refs), evidence_refs=list(request.evidence_refs),
        external_ref=None, safe_error=safe_error, created_at=now)
