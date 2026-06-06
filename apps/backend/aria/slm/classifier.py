"""
SLM Classifier — Week 25 (Pillar 24, Model Router v2).

A lightweight classification interface that routes to the fastest available method:

  1. Local SLM (Phi-3-mini / Qwen-0.5B via vLLM) — Week 29+
  2. Keyword matcher                               — V1 default, deterministic

The interface is fixed so the calling layer never changes when the backing
model is upgraded.
"""
from __future__ import annotations

from typing import Callable, Literal, Optional
from pydantic import BaseModel

from aria.nodes.router import _keyword_classify as _keyword_router

TaskType = Literal[
    "pr_review", "kpi", "ci_cd", "jira", "qa", "test_review", "analytics_qa", "general", "unknown"
]

_ALLOWED_TASK_TYPES: frozenset[str] = frozenset({
    "pr_review", "kpi", "ci_cd", "jira", "qa", "test_review", "analytics_qa", "general", "unknown"
})

Method = Literal["slm", "keyword", "mock"]


class ClassificationResult(BaseModel):
    """Output of SLMClassifier.classify()."""
    task_type:  str
    confidence: float   # 0.0–1.0; keyword path sets heuristic value
    method:     Method  # which backend produced this result
    reason:     str     # one-line explanation

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.6


# ── Confidence heuristics for keyword path ────────────────────────────────────

_KEYWORD_CONFIDENCE: dict[str, float] = {
    "pr_review":   0.85,
    "kpi":         0.85,
    "ci_cd":       0.85,
    "jira":        0.85,
    "qa":          0.85,
    "test_review": 0.85,
    "general":     0.60,
    "unknown":     0.30,
}


class SLMClassifier:
    """
    Thin wrapper that selects the fastest classification backend available.

    Args:
        slm_fn:  Optional callable matching signature (text: str) → str
                 returning a task_type string.  When provided, "slm" method
                 is used (vLLM-hosted Phi-3-mini in production).
    """

    def __init__(self, slm_fn: Optional[Callable[[str], str]] = None) -> None:
        self._slm = slm_fn

    def classify(self, text: str) -> ClassificationResult:
        if self._slm is not None:
            return self._classify_slm(text)
        return self._classify_keyword(text)

    def _classify_slm(self, text: str) -> ClassificationResult:
        try:
            raw = self._slm(text)  # type: ignore[misc]
            task_type = str(raw).strip().lower()
            if task_type not in _ALLOWED_TASK_TYPES:
                # SLM returned an unsupported task type — fall back to keyword
                result = self._classify_keyword(text)
                return result.model_copy(
                    update={"reason": f"SLM returned invalid task_type '{raw}'; fell back to keyword"}
                )
            confidence = _KEYWORD_CONFIDENCE.get(task_type, 0.7)
            return ClassificationResult(
                task_type=task_type,
                confidence=confidence,
                method="slm",
                reason="Classified by local SLM (vLLM-hosted)",
            )
        except Exception as exc:
            # SLM raised — fall back to keyword
            result = self._classify_keyword(text)
            return result.model_copy(update={"reason": f"SLM failed ({exc}); fell back to keyword"})

    def _classify_keyword(self, text: str) -> ClassificationResult:
        task_type, kw_reason = _keyword_router(text)
        confidence = _KEYWORD_CONFIDENCE.get(task_type, 0.5)
        return ClassificationResult(
            task_type=task_type,
            confidence=confidence,
            method="keyword",
            reason=kw_reason or f"Keyword rule matched task_type='{task_type}'",
        )


# ── Module-level singleton (keyword-backed until vLLM is wired) ───────────────

slm_classifier = SLMClassifier()
