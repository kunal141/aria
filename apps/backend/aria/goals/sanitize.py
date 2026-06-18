"""
Goal-text sensitivity boundary (V3.1 P1 fix).

Goal text is persisted to SQLite and rendered into workspace artifacts — neither is
covered by the Work Ledger's metadata redaction. So a vague request that carries a
secret (``password=…``, ``api_key=…``, ``Bearer …``, ``sk-ant-…``) must be masked
BEFORE it is stored or rendered, or the secret leaks into runtime data.

Two layers, both substring-level (the goal text stays usable — only the secret is
masked, the surrounding plan is preserved):

  1. ``redact_freetext`` — masks credential-SHAPED substrings (the same patterns the
     ledger uses: ``sk-…``, ``sk-ant-…``, ``Bearer …``, JWTs, AWS/Slack/Stripe keys).
  2. ``_mask_assignments`` — masks ``<secret-key> = <value>`` / ``<secret-key>: <value>``
     assignments (``password=…``, ``api_key: …``, ``token=…``) whose VALUE is not a
     recognised credential shape but is still a secret by virtue of the key name.

``sanitize_goal_intake`` applies both to every free-text field of a ``GoalIntake``.
It NEVER mutates the input (returns a copy). It is idempotent — re-sanitising
already-masked text is a no-op — so it is safe to apply at both the intake engine
and the persistence boundary.
"""
from __future__ import annotations

import re

from aria.goals.models import GoalIntake
from aria.ledger.privacy import REDACTED, redact_freetext

# Secret-bearing assignment: a sensitive key followed by ``=`` or ``:`` and a value.
# The value (group 3) is replaced; the key + separator are preserved so the masked
# text still reads sensibly (``password=[REDACTED]``).
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    r"passwords?|passwd|pwd|secrets?|client_secret|api[_-]?keys?|apikey|"
    r"access[_-]?key|secret[_-]?key|tokens?|credentials?|private[_-]?key|"
    r"authorization|auth[_-]?token|session[_-]?id|cvv|ssn"
    r")(\s*[:=]\s*)(\S+)"
)


def _mask_assignments(text: str) -> str:
    return _SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)


def sanitize_text(text: str | None) -> str | None:
    """Mask credential shapes AND secret key=value assignments in free text."""
    if not text:
        return text
    masked = redact_freetext(text) or ""
    return _mask_assignments(masked)


def _sanitize_list(items: list[str]) -> list[str]:
    return [sanitize_text(x) or "" for x in items]


def sanitize_goal_intake(intake: GoalIntake) -> GoalIntake:
    """Return a copy of ``intake`` with every free-text field sanitised. Safe to
    call more than once (idempotent)."""
    return intake.model_copy(update={
        "title": sanitize_text(intake.title),
        "raw_request": sanitize_text(intake.raw_request),
        "problem_statement": sanitize_text(intake.problem_statement),
        "goal": sanitize_text(intake.goal),
        "success_criteria": _sanitize_list(intake.success_criteria),
        "known_context": _sanitize_list(intake.known_context),
        "missing_context": _sanitize_list(intake.missing_context),
        "clarifying_questions": _sanitize_list(intake.clarifying_questions),
        "constraints": _sanitize_list(intake.constraints),
        "stakeholders": _sanitize_list(intake.stakeholders),
        "scope": sanitize_text(intake.scope) or intake.scope,
    })
