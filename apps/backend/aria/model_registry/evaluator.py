"""
Offline deterministic evaluation harness — Week 29 Priority 4.

The registry forbids activating a model that has never been evaluated. This
module supplies the evaluation that produces those metrics — but in V1 it is a
fully offline, deterministic adapter, NOT a real model invocation:

  - No network call, no LLM, no GPU. The "score" for a model is a stable
    pseudo-metric derived from a SHA-256 over the model's immutable identity
    fingerprint and the holdout's content hash. The same (model, holdout) pair
    always yields the same numbers, which is exactly what the deterministic
    test-suite and the offline demo require.
  - Real evaluators (a LangSmith rubric run against a served endpoint) plug in
    later behind the same ``Evaluator`` Protocol — the registry only ever sees
    an ``EvaluationReport``, so the production swap is dependency injection with
    no registry change.

This is prototype evaluation evidence. It is explicitly labelled as such in the
report (``evaluator_version`` carries the ``offline-deterministic`` marker) so a
reviewer can never mistake a pseudo-score for a real benchmark.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aria.model_registry.models import ModelRecord, utc_now


EVALUATOR_VERSION = "offline-deterministic-v1"


class HoldoutExample(BaseModel):
    """One fixed offline evaluation fixture (no live data, no PII)."""
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    example_id: str = Field(min_length=1)
    prompt:     str = Field(min_length=1)
    reference:  str = Field(min_length=1)


def holdout_fingerprint(examples: list[HoldoutExample]) -> str:
    """Stable SHA-256 over an ordered holdout set (its content identity)."""
    payload = json.dumps(
        [
            {"example_id": e.example_id, "prompt": e.prompt, "reference": e.reference}
            for e in examples
        ],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EvaluationReport(BaseModel):
    """
    Immutable result of evaluating one model version against a fixed holdout.

    ``metrics`` is the dict that the registry records on the model via
    ``record_evaluation``; the registry's own validator re-checks the values
    are finite numbers, so a malformed report cannot smuggle NaN/inf into a
    record.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    report_id:         str = Field(min_length=1)
    model_id:          str = Field(min_length=1)
    holdout_id:        str = Field(min_length=1)
    holdout_hash:      str
    num_examples:      int = Field(ge=0)
    metrics:           dict[str, float]
    evaluator_version: str = EVALUATOR_VERSION
    created_at:        datetime
    notes:             Optional[str] = None

    @field_validator("holdout_hash")
    @classmethod
    def _valid_hash(cls, v: str) -> str:
        normalised = v.lower()
        if len(normalised) != 64 or any(c not in "0123456789abcdef" for c in normalised):
            raise ValueError("holdout_hash must be a 64-char lowercase SHA-256 hex string.")
        return normalised

    @field_validator("metrics", mode="before")
    @classmethod
    def _finite_metrics(cls, v: dict[str, float]) -> dict[str, float]:
        # Runs BEFORE Pydantic's float coercion so a raw bool (a subclass of
        # int) or a NaN/inf cannot enter the report — the report is the
        # evidence a model is later activated on, so it must be as strict as
        # ``ModelRecord.evaluation_metrics`` itself (defence in depth).
        import math
        if not isinstance(v, dict):
            raise ValueError("metrics must be a mapping of name -> number.")
        for name, value in v.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"metrics[{name!r}] must be a number.")
            if not math.isfinite(float(value)):
                raise ValueError(f"metrics[{name!r}] must be finite.")
        return v

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("EvaluationReport.created_at must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)


@runtime_checkable
class Evaluator(Protocol):
    def evaluate(
        self, record: ModelRecord, holdout: list[HoldoutExample]
    ) -> EvaluationReport: ...


class OfflineEvaluator:
    """
    Deterministic offline evaluator. Produces stable pseudo-metrics from a hash
    of the model's identity and the holdout content — NEVER a real inference.
    """

    def __init__(self, evaluator_version: str = EVALUATOR_VERSION) -> None:
        self._version = evaluator_version

    def _digest(self, record: ModelRecord, holdout_hash: str) -> bytes:
        seed = f"{record.identity_fingerprint()}::{holdout_hash}::{self._version}"
        return hashlib.sha256(seed.encode("utf-8")).digest()

    @staticmethod
    def _unit(byte_pair: int) -> float:
        # Map two bytes (0..65535) to a stable float in [0, 1], rounded so the
        # value is reproducible across platforms and JSON round-trips.
        return round(byte_pair / 65535.0, 6)

    def evaluate(
        self, record: ModelRecord, holdout: list[HoldoutExample]
    ) -> EvaluationReport:
        if not holdout:
            raise ValueError("OfflineEvaluator requires a non-empty holdout set.")
        h_hash = holdout_fingerprint(holdout)
        digest = self._digest(record, h_hash)

        accuracy   = self._unit((digest[0] << 8) | digest[1])
        pass_rate  = self._unit((digest[2] << 8) | digest[3])
        # Rubric score in [1.0, 5.0], deterministic.
        rubric     = round(1.0 + 4.0 * self._unit((digest[4] << 8) | digest[5]), 4)

        metrics = {
            "accuracy": accuracy,
            "pass_rate": pass_rate,
            "rubric_score": rubric,
            "num_examples": float(len(holdout)),
        }
        report_id = "eval-" + hashlib.sha256(
            f"{record.model_id}::{h_hash}::{self._version}".encode("utf-8")
        ).hexdigest()[:16]

        return EvaluationReport(
            report_id=report_id,
            model_id=record.model_id,
            holdout_id=h_hash[:12],
            holdout_hash=h_hash,
            num_examples=len(holdout),
            metrics=metrics,
            evaluator_version=self._version,
            created_at=utc_now(),
            notes="Offline deterministic pseudo-evaluation — prototype evidence only.",
        )


def default_pr_review_holdout() -> list[HoldoutExample]:
    """A tiny fixed, privacy-safe holdout used by the demo and tests."""
    return [
        HoldoutExample(
            example_id="holdout-pr-001",
            prompt="Review this PR adding a null check to the recommendation ranker.",
            reference="Risk LOW. Null check is correct; add one regression test.",
        ),
        HoldoutExample(
            example_id="holdout-pr-002",
            prompt="Review this PR refactoring the notification batching loop.",
            reference="Risk MEDIUM. Verify ordering is preserved; add a coverage test.",
        ),
        HoldoutExample(
            example_id="holdout-pr-003",
            prompt="Review this PR changing the CMS cache TTL from 60s to 600s.",
            reference="Risk MEDIUM. Confirm staleness budget with editorial before merge.",
        ),
    ]
