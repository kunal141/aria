"""
Business-report generation — the seam between deterministic and real-model work.

The employee run is governed identically in both modes: route decision → adapter
request → preview receipt → mock receipt → **evaluation against source data** →
bounded repair. Only the authorship of the prose changes.

Two implementations:

- :class:`DeterministicReportGenerator` — the offline proof. Pure, stable, no model.
- :class:`ModelReportGenerator` — a real chat model writes the prose.

Safety properties that hold for the model path and are enforced *here*, not left to
the prompt:

1. **Provenance is never model-generated.** ``evidence_refs`` are copied from the
   dataset. A model may not invent, add to, or drop a citation — the single most
   dangerous thing a report generator could do.
2. **Prose is secret-masked** before it enters the report, so a leaked credential
   in model output never reaches storage, the workspace artifact, or a manager.
3. **Failures are class-only.** Raw model text never appears in an exception,
   because it is untrusted and may carry secrets or injected instructions.
4. **The answer is not supplied in the prompt.** The model receives the source
   counts and must do the arithmetic; the deterministic evaluator then verifies the
   result against the dataset. Handing over the pre-computed delta would make the
   anti-fabrication check vacuous.
"""
from __future__ import annotations

from typing import Any, Protocol

from aria.employee.models import BusinessAnalysisReport, BusinessPerformanceDataset
from aria.goals.sanitize import sanitize_text
from aria.skills.json_output import parse_json_object

# Report fields the model must supply. ``evidence_refs`` is deliberately absent —
# it is never taken from model output.
_REQUIRED_FIELDS = ("title", "executive_summary", "findings", "recommendations")

_MAX_ITEMS = 12
_MAX_ITEM_CHARS = 600
_MAX_SUMMARY_CHARS = 2_000

_SYSTEM_PROMPT = """You are a business analyst producing a manager-facing performance report.

Rules:
- Work ONLY from the supplied source counts. Do not invent data, segments, or causes.
- State the change in click-through rate in PERCENTAGE POINTS, computed from the counts,
  formatted with a sign and exactly two decimals, e.g. "Verified change: -1.23 percentage points."
- If the evidence does not support a claim, say so instead of asserting it.
- Do not include credentials, tokens, URLs, or internal hostnames.

Return ONLY a JSON object with these keys:
  title              string
  executive_summary  string
  findings           array of strings (include the percentage-point change)
  risks              array of strings
  recommendations    array of strings
"""


class ReportGenerationError(RuntimeError):
    """Report generation failed. Carries a class/code only — never model text."""


class ReportGenerator(Protocol):
    """Produces a business report for one attempt of an employee run."""

    def generate(
        self,
        dataset: BusinessPerformanceDataset,
        *,
        attempt_number: int,
        omit_risks: bool = False,
        repair_instructions: list[str] | None = None,
    ) -> BusinessAnalysisReport:
        ...


def _clean_line(value: Any) -> str:
    return (sanitize_text(str(value)) or "")[:_MAX_ITEM_CHARS].strip()


def _clean_lines(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = [_clean_line(item) for item in values[:_MAX_ITEMS]]
    return [line for line in cleaned if line]


class DeterministicReportGenerator:
    """The offline proof path: pure, repeatable, and model-free."""

    def generate(
        self,
        dataset: BusinessPerformanceDataset,
        *,
        attempt_number: int,
        omit_risks: bool = False,
        repair_instructions: list[str] | None = None,
    ) -> BusinessAnalysisReport:
        from aria.employee.service import build_business_report

        return build_business_report(
            dataset, attempt_number=attempt_number, omit_risks=omit_risks
        )


class ModelReportGenerator:
    """A real chat model writes the prose; this class keeps the guarantees."""

    def __init__(self, model: Any) -> None:
        if model is None:
            raise ReportGenerationError("no model was available for report generation")
        self._model = model

    # ── prompt ────────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        dataset: BusinessPerformanceDataset,
        *,
        attempt_number: int,
        repair_instructions: list[str] | None,
    ) -> str:
        previous, current = dataset.previous, dataset.current
        lines = [
            f"Metric: {sanitize_text(dataset.metric_name)}",
            f"Dataset: {sanitize_text(dataset.dataset_id)}",
            "",
            "Source counts (authoritative — compute from these):",
            f"  {previous.label}: impressions={previous.impressions} clicks={previous.clicks}",
            f"  {current.label}: impressions={current.impressions} clicks={current.clicks}",
            "",
            f"Attempt number: {attempt_number}",
        ]
        if repair_instructions:
            lines += [
                "",
                "A previous attempt failed review. Address each instruction exactly:",
                *[f"  - {_clean_line(item)}" for item in repair_instructions[:_MAX_ITEMS]],
            ]
        return "\n".join(lines)

    # ── generation ────────────────────────────────────────────────────────────

    def generate(
        self,
        dataset: BusinessPerformanceDataset,
        *,
        attempt_number: int,
        omit_risks: bool = False,
        repair_instructions: list[str] | None = None,
    ) -> BusinessAnalysisReport:
        prompt = self._build_prompt(
            dataset, attempt_number=attempt_number, repair_instructions=repair_instructions
        )
        raw = self._invoke(prompt)
        payload = self._decode(raw)
        return self._to_report(payload, dataset, omit_risks=omit_risks)

    def _invoke(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        try:
            response = self._model.invoke(
                [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)]
            )
        except Exception as exc:  # class only — model errors may echo input
            raise ReportGenerationError(
                f"model invocation failed ({type(exc).__name__}); details redacted"
            ) from None
        content = getattr(response, "content", response)
        if not isinstance(content, str) or not content.strip():
            raise ReportGenerationError("model returned no text content")
        return content

    @staticmethod
    def _decode(raw: str) -> dict[str, Any]:
        try:
            payload = parse_json_object(raw)
        except ValueError as exc:
            # Never echo `raw`: it is untrusted and may carry secrets or injection.
            raise ReportGenerationError(
                f"model output was not a JSON object ({type(exc).__name__}); details redacted"
            ) from None
        missing = [field for field in _REQUIRED_FIELDS if not payload.get(field)]
        if missing:
            raise ReportGenerationError(
                f"model output omitted required fields: {', '.join(sorted(missing))}"
            )
        return payload

    @staticmethod
    def _to_report(
        payload: dict[str, Any],
        dataset: BusinessPerformanceDataset,
        *,
        omit_risks: bool,
    ) -> BusinessAnalysisReport:
        findings = _clean_lines(payload.get("findings"))
        recommendations = _clean_lines(payload.get("recommendations"))
        if not findings or not recommendations:
            raise ReportGenerationError("model output contained no usable findings")
        summary = (sanitize_text(str(payload.get("executive_summary", ""))) or "")[
            :_MAX_SUMMARY_CHARS
        ].strip()
        if not summary:
            raise ReportGenerationError("model output contained no executive summary")
        return BusinessAnalysisReport(
            title=_clean_line(payload.get("title")) or "Business Performance Analysis",
            executive_summary=summary,
            findings=findings,
            risks=[] if omit_risks else _clean_lines(payload.get("risks")),
            recommendations=recommendations,
            # Provenance is structural, never model-authored.
            evidence_refs=list(dataset.source_refs),
        )


def build_report_generator(execution_mode: str, *, model: Any = None) -> ReportGenerator:
    """Select the generator for the active execution mode.

    ``offline_mock`` is deterministic and never touches a model. Any other mode
    requires a model to have been built by the caller; there is no silent
    downgrade to the deterministic path, because a manager reading a real-mode
    report must not receive templated prose that looks like analysis.
    """
    if execution_mode == "offline_mock":
        return DeterministicReportGenerator()
    if model is None:
        raise ReportGenerationError(
            f"execution mode '{execution_mode}' requires a model; none was supplied"
        )
    return ModelReportGenerator(model)


__all__ = [
    "DeterministicReportGenerator",
    "ModelReportGenerator",
    "ReportGenerationError",
    "ReportGenerator",
    "build_report_generator",
]
