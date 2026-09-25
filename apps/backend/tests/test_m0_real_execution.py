"""
M0 — real execution under governance: adversarial tests.

Written BEFORE the implementation they test (development-plan §4 discipline).

The property under test is not "the model produces a nice report". It is that a
*real*, non-deterministic model can be introduced into the employee run **without
weakening any existing guarantee**:

  - provenance is never model-generated (an LLM may not invent a citation);
  - model prose is secret-masked before it is persisted or rendered;
  - malformed model output fails safely with a class-only error, never raw text;
  - a fabricated metric fails the deterministic evaluator and drives the repair loop;
  - unsafe source-ref schemes stay rejected regardless of execution mode;
  - offline_mock remains bit-for-bit deterministic and calls no model;
  - cloud_opt_in stays closed on the authenticated tenant surface.

No test here contacts a real Ollama daemon or any network: the model is injected.
"""
from __future__ import annotations

import pytest

from aria.employee.evaluation import evaluate_business_report
from aria.employee.models import (
    BusinessAnalysisReport,
    BusinessMetricPeriod,
    BusinessPerformanceDataset,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _dataset(source_refs: list[str] | None = None) -> BusinessPerformanceDataset:
    return BusinessPerformanceDataset(
        dataset_id="ds-notification-ctr-2026-08",
        metric_name="notification_ctr",
        previous=BusinessMetricPeriod(label="previous", impressions=100_000, clicks=4_200),
        current=BusinessMetricPeriod(label="current", impressions=100_000, clicks=3_800),
        source_refs=source_refs or ["fixture://notifications/2026-08"],
    )


class _StubModel:
    """Stands in for a chat model. Records prompts; returns a scripted reply."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def invoke(self, messages):  # mirrors the langchain chat-model surface
        self.prompts.append(str(messages))
        return type("AIMessage", (), {"content": self.reply})()


def _valid_model_reply(delta_token: str = "-0.40 percentage points") -> str:
    return (
        '```json\n'
        '{"title": "Business Performance Analysis",'
        ' "executive_summary": "Notification CTR declined against the supplied fixture.",'
        f' "findings": ["Verified change: {delta_token}."],'
        ' "risks": ["The fixture proves a change, not a cause."],'
        ' "recommendations": ["Validate by segment before acting."],'
        ' "evidence_refs": ["fixture://notifications/2026-08"]}'
        '\n```'
    )


# ── The deterministic evaluator is the guard on model output ──────────────────


class TestEvaluatorGuardsModelOutput:
    def test_correct_delta_passes(self):
        dataset = _dataset()
        report = BusinessAnalysisReport(
            title="t", executive_summary="s",
            findings=["Verified change: -0.40 percentage points."],
            risks=["r"], recommendations=["rec"],
            evidence_refs=list(dataset.source_refs),
        )
        result = evaluate_business_report(
            run_id="r1", attempt_id="a1", report=report, dataset=dataset)
        assert result.passed is True
        assert result.criteria["metric_delta_correct"] is True

    def test_fabricated_delta_fails_and_yields_repair_instruction(self):
        """A model that invents a number must fail — this is the anti-fabrication guard."""
        dataset = _dataset()
        report = BusinessAnalysisReport(
            title="t", executive_summary="s",
            findings=["Verified change: +9.99 percentage points."],  # fabricated
            risks=["r"], recommendations=["rec"],
            evidence_refs=list(dataset.source_refs),
        )
        result = evaluate_business_report(
            run_id="r1", attempt_id="a1", report=report, dataset=dataset)
        assert result.passed is False
        assert any(issue.code == "incorrect_metric_delta" for issue in result.issues)

    def test_uncited_evidence_fails(self):
        dataset = _dataset()
        report = BusinessAnalysisReport(
            title="t", executive_summary="s",
            findings=["Verified change: -0.40 percentage points."],
            risks=["r"], recommendations=["rec"],
            evidence_refs=[],  # model dropped the citation
        )
        result = evaluate_business_report(
            run_id="r1", attempt_id="a1", report=report, dataset=dataset)
        assert result.passed is False
        assert any(issue.code == "missing_evidence" for issue in result.issues)


# ── Report generation: the new seam ───────────────────────────────────────────


class TestDeterministicGenerator:
    def test_offline_mode_calls_no_model(self):
        from aria.employee.generation import DeterministicReportGenerator

        generator = DeterministicReportGenerator()
        report = generator.generate(_dataset(), attempt_number=1, omit_risks=False)
        assert "-0.40 percentage points" in " ".join(report.findings)
        assert report.risks  # risks present when not intentionally omitted

    def test_omit_risks_is_honoured(self):
        from aria.employee.generation import DeterministicReportGenerator

        report = DeterministicReportGenerator().generate(
            _dataset(), attempt_number=1, omit_risks=True)
        assert report.risks == []

    def test_output_is_stable_across_calls(self):
        from aria.employee.generation import DeterministicReportGenerator

        generator = DeterministicReportGenerator()
        first = generator.generate(_dataset(), attempt_number=1, omit_risks=False)
        second = generator.generate(_dataset(), attempt_number=1, omit_risks=False)
        assert first == second


class TestModelGeneratorSafety:
    def test_evidence_refs_are_never_model_generated(self):
        """An LLM may not invent provenance. Citations come from the dataset only."""
        from aria.employee.generation import ModelReportGenerator

        forged = _valid_model_reply().replace(
            '"evidence_refs": ["fixture://notifications/2026-08"]',
            '"evidence_refs": ["https://attacker.example/forged", "fixture://not-real"]',
        )
        dataset = _dataset()
        report = ModelReportGenerator(_StubModel(forged)).generate(
            dataset, attempt_number=1, omit_risks=False)
        assert report.evidence_refs == list(dataset.source_refs)
        assert not any("attacker" in ref for ref in report.evidence_refs)

    def test_secrets_in_model_prose_are_masked(self):
        from aria.employee.generation import ModelReportGenerator

        leaky = _valid_model_reply().replace(
            "Notification CTR declined against the supplied fixture.",
            "Fetched with api_key=SUPERSECRETVALUE123 from the warehouse.",
        )
        report = ModelReportGenerator(_StubModel(leaky)).generate(
            _dataset(), attempt_number=1, omit_risks=False)
        assert "SUPERSECRETVALUE123" not in report.executive_summary
        assert "SUPERSECRETVALUE123" not in " ".join(
            [*report.findings, *report.risks, *report.recommendations])

    def test_malformed_output_fails_safely_without_leaking_raw_text(self):
        from aria.employee.generation import ModelReportGenerator, ReportGenerationError

        secret_noise = "not json at all; token=SHOULD_NOT_APPEAR"
        with pytest.raises(ReportGenerationError) as excinfo:
            ModelReportGenerator(_StubModel(secret_noise)).generate(
                _dataset(), attempt_number=1, omit_risks=False)
        assert "SHOULD_NOT_APPEAR" not in str(excinfo.value)

    def test_missing_required_field_fails_safely(self):
        from aria.employee.generation import ModelReportGenerator, ReportGenerationError

        incomplete = '{"title": "t"}'
        with pytest.raises(ReportGenerationError):
            ModelReportGenerator(_StubModel(incomplete)).generate(
                _dataset(), attempt_number=1, omit_risks=False)

    def test_prompt_supplies_source_numbers_not_the_answer(self):
        """The model must do the arithmetic; handing it the answer would void the test."""
        from aria.employee.generation import ModelReportGenerator

        model = _StubModel(_valid_model_reply())
        ModelReportGenerator(model).generate(_dataset(), attempt_number=1, omit_risks=False)
        prompt = model.prompts[0]
        assert "100000" in prompt.replace(",", "") or "100,000" in prompt
        assert "-0.40 percentage points" not in prompt

    def test_repair_instructions_reach_the_prompt(self):
        from aria.employee.generation import ModelReportGenerator

        model = _StubModel(_valid_model_reply())
        ModelReportGenerator(model).generate(
            _dataset(), attempt_number=2, omit_risks=False,
            repair_instructions=["Recalculate the percentage-point change from source data."],
        )
        assert "Recalculate the percentage-point change" in model.prompts[0]


# ── Source-ref policy: unsafe schemes stay rejected in every mode ─────────────


class TestSourceRefPolicy:
    @pytest.mark.parametrize("ref", [
        "https://internal.example/report",
        "http://internal.example/report",
        "github://org/repo",
        "slack://channel",
        "jira://PROJ-1",
        "mcp://server/tool",
        "file:///etc/passwd",
        "FILE://C:/secrets.txt",
        "ftp://host/x",
        "data:text/plain;base64,AAAA",
    ])
    def test_unsafe_schemes_rejected_even_when_policy_is_relaxed(self, ref):
        from aria.employee.service import _safe_dataset

        with pytest.raises(ValueError):
            _safe_dataset(_dataset([ref]), allowed_schemes=("fixture://", "tenant://"))

    @pytest.mark.parametrize("scheme,ref", [
        ("ssh://", "ssh://host/repo"),
        ("sftp://", "sftp://host/file"),
        ("mailto:", "mailto:admin@example.com"),
    ])
    def test_policy_widening_cannot_admit_unreviewed_transports(self, scheme, ref):
        from aria.employee.service import _safe_dataset

        with pytest.raises(ValueError):
            _safe_dataset(_dataset([ref]), allowed_schemes=("fixture://", scheme))

    def test_fixture_scheme_is_the_default_policy(self):
        from aria.employee.service import _safe_dataset

        with pytest.raises(ValueError):
            _safe_dataset(_dataset(["tenant://warehouse/ctr"]))

    def test_relaxed_policy_admits_declared_scheme(self):
        from aria.employee.service import _safe_dataset

        dataset = _safe_dataset(
            _dataset(["tenant://warehouse/ctr"]),
            allowed_schemes=("fixture://", "tenant://"),
        )
        assert dataset.source_refs == ["tenant://warehouse/ctr"]

    def test_credential_shaped_source_ref_rejected(self):
        from aria.employee.service import _safe_dataset

        with pytest.raises(ValueError):
            _safe_dataset(_dataset(["fixture://sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA"]))


# ── Execution-mode gate on the authenticated tenant surface ───────────────────


class TestExecutionModeGate:
    @pytest.mark.parametrize("mode,allowed", [
        ("offline_mock", True),
        ("local_ollama", True),
        ("cloud_opt_in", False),   # deliberately closed in M0
    ])
    def test_supported_modes(self, monkeypatch, mode, allowed):
        from aria.api import platform_employee

        monkeypatch.setenv("ARIA_EXECUTION_MODE", mode)
        resolved = platform_employee._mode()
        assert (resolved == mode) is allowed

    def test_unset_mode_defaults_to_offline_mock(self, monkeypatch):
        from aria.api import platform_employee

        monkeypatch.delenv("ARIA_EXECUTION_MODE", raising=False)
        assert platform_employee._mode() == "offline_mock"
