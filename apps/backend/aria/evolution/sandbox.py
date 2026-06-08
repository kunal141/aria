"""
Evolution Sandbox — Week 27

Evaluates an EvolutionProposal in an isolated environment before any integration.

V1 checks (all deterministic, no LLM):
  1. compile_check   — proposed artifact (if any) compiles as valid Python
  2. schema_check    — proposal fields are structurally valid
  3. risk_ceiling    — risk_score does not exceed type ceiling
  4. golden_test     — at least one evidence item matches expected patterns

SandboxResult.passed=False → integration is BLOCKED regardless of approval.
No bypass path exists.
"""
from __future__ import annotations

import ast
import re
from typing import Optional

from aria.evolution.models import (
    RISK_CEILING,
    EvolutionProposal,
    SandboxResult,
    utc_now,
)

_ALL_CHECKS = ["compile_check", "schema_check", "risk_ceiling_check", "golden_test"]


def run_sandbox(
    proposal: EvolutionProposal,
    artifact_source: Optional[str] = None,
) -> SandboxResult:
    """
    Run all V1 sandbox checks.

    Parameters
    ----------
    proposal       : The proposal to evaluate.
    artifact_source: Optional Python source code for compile_check.
                     When None, compile_check is skipped (not failed).
    """
    findings: list[str] = []
    checks_run: list[str] = []

    # 1. Compile check
    if artifact_source is not None:
        checks_run.append("compile_check")
        finding = _compile_check(artifact_source)
        if finding:
            findings.append(finding)
    else:
        checks_run.append("compile_check:skipped")

    # 2. Schema check
    checks_run.append("schema_check")
    finding = _schema_check(proposal)
    if finding:
        findings.append(finding)

    # 3. Risk ceiling check
    checks_run.append("risk_ceiling_check")
    finding = _risk_ceiling_check(proposal)
    if finding:
        findings.append(finding)

    # 4. Golden test
    checks_run.append("golden_test")
    finding = _golden_test(proposal)
    if finding:
        findings.append(finding)

    return SandboxResult(
        proposal_id=proposal.proposal_id,
        passed=len(findings) == 0,
        checks_run=checks_run,
        findings=findings,
        evaluated_at=utc_now(),
    )


# ── Individual checks ──────────────────────────────────────────────────────────

def _compile_check(source: str) -> Optional[str]:
    """Return error string if source is not valid Python, else None."""
    try:
        ast.parse(source)
        return None
    except SyntaxError as exc:
        return f"compile_check FAILED: SyntaxError at line {exc.lineno} — {exc.msg}"


def _schema_check(proposal: EvolutionProposal) -> Optional[str]:
    """Check mandatory prose fields are non-empty."""
    if not proposal.title.strip():
        return "schema_check FAILED: title is empty"
    if not proposal.description.strip():
        return "schema_check FAILED: description is empty"
    if not proposal.evidence:
        return "schema_check FAILED: evidence list is empty"
    if not proposal.expected_gain.strip():
        return "schema_check FAILED: expected_gain is empty"
    return None


def _risk_ceiling_check(proposal: EvolutionProposal) -> Optional[str]:
    """Fail if risk_score exceeds type ceiling."""
    ceiling = RISK_CEILING.get(proposal.evolution_type.value, 1.0)
    if proposal.risk_score > ceiling:
        return (
            f"risk_ceiling_check FAILED: risk_score {proposal.risk_score} exceeds "
            f"ceiling {ceiling} for {proposal.evolution_type.value}"
        )
    return None


def _golden_test(proposal: EvolutionProposal) -> Optional[str]:
    """
    V1 golden test: at least one evidence item must be a non-trivial sentence
    (≥ 10 chars, contains a digit or percentage or keyword from a small set).
    """
    _KEYWORDS = re.compile(
        r"\d+|%|error|fail|rate|task|run|drop|improve|suggest|detect",
        re.IGNORECASE,
    )
    for item in proposal.evidence:
        if len(item) >= 10 and _KEYWORDS.search(item):
            return None  # at least one good evidence item

    return (
        "golden_test FAILED: no evidence item meets minimum quality threshold "
        "(≥10 chars with a quantitative or descriptive signal)"
    )
