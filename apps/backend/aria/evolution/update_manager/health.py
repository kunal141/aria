"""
Health Checks — Week 28

Run before canary promotion and rollback to verify an update is safe to activate.

V1 checks (all deterministic, no LLM):
  hash_verification  — SHA-256(content) matches content_hash
  constitutional     — no governance-weakening patterns in content/changelog
  content_non_empty  — content is a non-empty string
  version_format     — semantic_version matches x.y.z pattern

All checks must pass before an update may go active or be used as a rollback target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from aria.evolution.update_manager.models import UpdateRelease, compute_hash
from aria.evolution.update_manager.constitutional import check_constitutional


@dataclass
class HealthCheckResult:
    passed:      bool
    checks_run:  list[str] = field(default_factory=list)
    findings:    list[str] = field(default_factory=list)


def run_health_checks(update: UpdateRelease) -> HealthCheckResult:
    """
    Run all V1 health checks on an UpdateRelease.

    Returns HealthCheckResult; passed=False blocks promotion/rollback.
    """
    findings: list[str] = []
    checks_run: list[str] = []

    # 1. Content non-empty
    checks_run.append("content_non_empty")
    if not update.content or not update.content.strip():
        findings.append("content_non_empty FAILED: content is absent or empty")

    # 2. Hash verification
    checks_run.append("hash_verification")
    if update.content:
        actual = compute_hash(update.content)
        if actual != update.content_hash:
            findings.append(
                f"hash_verification FAILED: computed {actual[:12]}… "
                f"does not match stored {update.content_hash[:12]}…"
            )
    else:
        findings.append("hash_verification FAILED: no content to hash")

    # 3. Constitutional safety
    checks_run.append("constitutional_check")
    violations = check_constitutional(update)
    for v in violations:
        findings.append(f"constitutional_check FAILED: {v}")

    # 4. Version format
    checks_run.append("version_format")
    import re
    if not re.match(r"^\d+\.\d+\.\d+", update.semantic_version):
        findings.append(
            f"version_format FAILED: {update.semantic_version!r} is not semver"
        )

    return HealthCheckResult(
        passed=len(findings) == 0,
        checks_run=checks_run,
        findings=findings,
    )
