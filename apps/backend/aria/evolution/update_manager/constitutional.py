"""
Constitutional AI Safety Checker — Week 28

Deterministic rules that prevent self-improvement proposals from weakening
ARIA's governance, safety, or audit infrastructure.

Rules are case-insensitive regex patterns matched against:
  - update.changelog
  - update.content  (if present)
  - update.evidence_refs (each item)

If any rule fires, the update is BLOCKED before approval is even checked.
Constitutional rules are never overridable by a proposal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from aria.evolution.update_manager.models import UpdateRelease


@dataclass(frozen=True)
class ConstitutionalRule:
    pattern: re.Pattern
    violation: str


# ── Rule registry ──────────────────────────────────────────────────────────────
# Every rule is compiled once at import time.

_RAW_RULES: list[tuple[str, str]] = [
    # Governance weakening
    (r"disable\s+governance",              "disables governance layer"),
    (r"remove\s+governance",               "disables governance layer"),
    (r"weaken\s+governance",               "weakens governance layer"),
    (r"bypass\s+t[45]\b",                  "bypasses T4/T5 approval gate"),
    (r"skip\s+approval",                   "skips T4 approval requirement"),
    (r"no\s+approval\s+required",          "skips T4 approval requirement"),
    (r"auto.?approve",                     "enables auto-approval (self-governance bypass)"),
    # Evidence gate
    (r"disable\s+evidence\s+gate",         "disables evidence gate"),
    (r"remove\s+evidence\s+gate",          "disables evidence gate"),
    (r"bypass\s+evidence",                 "bypasses evidence gate"),
    # Privacy gate
    (r"disable\s+privacy\s+gate",          "disables privacy gate"),
    (r"remove\s+privacy\s+gate",           "disables privacy gate"),
    (r"bypass\s+privacy",                  "bypasses privacy gate"),
    # Audit log
    (r"disable\s+audit",                   "disables audit logging"),
    (r"skip\s+audit",                      "disables audit logging"),
    (r"remove\s+audit",                    "disables audit logging"),
    # Risk ceiling manipulation
    (r"raise\s+(own\s+)?risk\s+ceiling",   "raises own risk ceiling"),
    (r"increase\s+(own\s+)?risk\s+ceiling","raises own risk ceiling"),
    # Self-modification of rules
    (r"modify\s+constitutional",           "modifies constitutional rules"),
    (r"update\s+constitutional\s+rule",    "modifies constitutional rules"),
    (r"override\s+constitutional",         "overrides constitutional rules"),
    # Executable code import
    (r"import\s+marketplace",              "imports executable marketplace code"),
    (r"from\s+marketplace\s+import",       "imports executable marketplace code"),
    # Dangerous builtins in update content
    (r"\bexec\s*\(",                        "contains exec() call"),
    (r"\beval\s*\(",                        "contains eval() call"),
    (r"__import__\s*\(",                   "uses __import__ (dynamic code execution)"),
]

CONSTITUTIONAL_RULES: list[ConstitutionalRule] = [
    ConstitutionalRule(
        pattern=re.compile(raw, re.IGNORECASE | re.DOTALL),
        violation=violation,
    )
    for raw, violation in _RAW_RULES
]


# ── Checker ────────────────────────────────────────────────────────────────────

def check_constitutional(update: UpdateRelease) -> list[str]:
    """
    Return a list of violation descriptions.
    Empty list means the update is constitutionally safe.

    Checked surfaces: changelog, content, evidence_refs.
    """
    texts: list[str] = []
    if update.changelog:
        texts.append(update.changelog)
    if update.content:
        texts.append(update.content)
    for ref in update.evidence_refs:
        texts.append(ref)

    combined = "\n".join(texts)
    violations: list[str] = []

    for rule in CONSTITUTIONAL_RULES:
        if rule.pattern.search(combined):
            violations.append(rule.violation)

    return violations


def is_constitutionally_safe(update: UpdateRelease) -> bool:
    return len(check_constitutional(update)) == 0
