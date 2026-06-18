"""
Read-only CI/CD Investigation Pilot (Week 34 §3).

Reads a workflow run + logs from a deterministic fixture, identifies the failed
job/step, summarises the likely root cause (with evidence references), suggests a
fix, and produces a Teams **preview** (preview-only, never sent). Read-only: no
rerun, no cancel, no retry, no CI write.
"""
from __future__ import annotations

from aria.pilots.drafts import teams_preview
from aria.pilots.models import EvidenceReference, Finding, PilotKind, PilotReport


def _root_cause(excerpt: str) -> str:
    low = excerpt.lower()
    if "keyerror" in low:
        # e.g. "KeyError: 'freshness_boost'"
        key = excerpt.split("KeyError:", 1)[-1].strip() if "KeyError:" in excerpt else ""
        return f"Missing configuration/dictionary key {key} used by the failing code path."
    if "importerror" in low or "modulenotfound" in low:
        return "A required module/dependency is missing or not installed."
    if "assert" in low:
        return "An assertion failed — the code produced an unexpected value."
    if "timeout" in low:
        return "A step timed out — likely a slow or hung dependency."
    return "See the failing step log for the specific error."


def _suggested_fix(excerpt: str) -> str:
    low = excerpt.lower()
    if "keyerror" in low and "freshness_boost" in low:
        return "Provide a default 'freshness_boost' in services/recommendation/config.py."
    if "keyerror" in low:
        return "Ensure the missing key is set in config or guarded with a default."
    if "importerror" in low or "modulenotfound" in low:
        return "Add the missing dependency to the project requirements and reinstall."
    return "Reproduce locally with the failing test and add the missing input/guard."


def run_ci_cd(connector, *, run_id: str = "default") -> PilotReport:
    data, evidence = connector.read_ci_run(run_id)
    findings: list[Finding] = []
    drafts = []

    failed_job = next((j for j in data.get("jobs", []) if j.get("status") == "failed"), None)
    if failed_job is None:
        summary = f"Run {data['run_id']} ({data['workflow']}) has no failed job."
    else:
        failed_step = next((s for s in failed_job.get("steps", []) if s.get("status") == "failed"), None)
        excerpt = failed_step.get("log_excerpt", "") if failed_step else ""
        root_cause = _root_cause(excerpt)
        fix = _suggested_fix(excerpt)
        step_name = failed_step.get("name") if failed_step else "(unknown)"

        findings.append(Finding(
            kind="failed_step", summary=f"{failed_job['name']}/{step_name}: {excerpt}",
            severity="high", evidence=evidence,
        ))
        findings.append(Finding(kind="root_cause", summary=root_cause, severity="high", evidence=evidence))
        findings.append(Finding(kind="suggested_fix", summary=fix, severity="info", evidence=evidence))

        drafts.append(teams_preview(
            title=f"CI failure: {data['workflow']}",
            body=(f"{failed_job['name']}/{step_name} failed in run {data['run_id']}. "
                  f"Likely cause: {root_cause} Suggested fix: {fix}"),
            would_target="teams",
        ))
        summary = (
            f"Run {data['run_id']} ({data['workflow']}) failed at "
            f"{failed_job['name']}/{step_name}. Preview-only — nothing sent or rerun."
        )

    return PilotReport(
        pilot=PilotKind.ci_cd, title="CI/CD Failure Investigation", summary=summary,
        findings=findings, drafts=drafts,
        evidence_references=[EvidenceReference(source=s, detail=f"run {data['run_id']}") for s in evidence],
        connector_mode=connector.mode.value,
        boundary="Read-only CI/CD investigation. Preview-only, nothing sent or rerun.",
    )
