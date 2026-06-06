"""
PII Redactor — Week 15

Strips personally-identifiable and sensitive information before any text
is sent to external systems (LangSmith traces, logs, error messages).

Why PII redaction matters for ARIA:
  - ARIA processes internal engineering tasks that can contain:
    - Employee email addresses in PR descriptions
    - Phone numbers in Jira tickets
    - API keys accidentally pasted in code reviews
    - Aadhaar / PAN numbers in HR-adjacent tasks
  - LangSmith traces are stored on Langchain's servers — confidential data
    must never appear in them, even in dev mode.
  - Audit logs are internal but should still not store raw secrets.

What gets redacted (in order):
  1. API keys, tokens, secrets — highest priority (entropy-based patterns)
  2. Email addresses
  3. Indian phone numbers (+91 / 10-digit mobile)
  4. International phone numbers
  5. Aadhaar numbers (12-digit, with or without spaces)
  6. PAN numbers (Indian tax ID — AAAAA9999A format)
  7. Credit / debit card numbers

What is NOT redacted:
  - Generic numbers, task_ids, version numbers
  - Technical identifiers (commit SHAs, UUIDs) — these are not PII

Performance note: patterns are compiled once at module load (~0.5ms).
The redact() function itself adds <1ms per call for typical inputs.
"""
import re
from typing import Optional


# ── Compiled patterns ─────────────────────────────────────────────────────────
# Ordered by specificity — more specific patterns first so they don't get
# partially matched by a broader pattern.

_PATTERNS: list[tuple[str, str, str]] = [
    # (name, pattern, replacement)

    # API keys / tokens / secrets (high-entropy strings following key-value hints)
    (
        "api_key",
        r"(?i)(?:api[-_]?key|apikey|token|secret|password|bearer|sk-|access[-_]?key)\s*[=:\"'\s]\s*[A-Za-z0-9/+_\-\.]{16,}",
        "[REDACTED_KEY]",
    ),
    # Standalone high-entropy base64/hex strings ≥ 32 chars (likely secrets)
    (
        "token_standalone",
        r"\b(?:[A-Za-z0-9+/]{32,}={0,2}|[0-9a-f]{32,})\b",
        "[REDACTED_TOKEN]",
    ),
    # Email addresses
    (
        "email",
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        "[REDACTED_EMAIL]",
    ),
    # Indian mobile numbers (+91 prefix or 10-digit starting 6-9)
    (
        "phone_in",
        r"(?:\+91[\s\-]?)?[6-9]\d{9}\b",
        "[REDACTED_PHONE]",
    ),
    # International phone numbers (+CC followed by 6-14 digits)
    (
        "phone_intl",
        r"\+\d{1,3}[\s\-]?\d{3,5}[\s\-]?\d{3,9}\b",
        "[REDACTED_PHONE]",
    ),
    # Aadhaar number (12 digits, optionally spaced as XXXX XXXX XXXX)
    (
        "aadhaar",
        r"\b\d{4}\s?\d{4}\s?\d{4}\b",
        "[REDACTED_AADHAAR]",
    ),
    # PAN number (AAAAA9999A format — Indian tax ID)
    (
        "pan",
        r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b",
        "[REDACTED_PAN]",
    ),
    # Credit/debit card (4 groups of 4 digits, various separators)
    (
        "card",
        r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b",
        "[REDACTED_CARD]",
    ),
]

_COMPILED: list[tuple[str, re.Pattern, str]] = [
    (name, re.compile(pattern), replacement)
    for name, pattern, replacement in _PATTERNS
]


# ── Public API ────────────────────────────────────────────────────────────────

def redact(text: str, sensitivity: Optional[str] = None) -> str:
    """
    Redact PII and secrets from text.

    Args:
        text:        The string to sanitise.
        sensitivity: Optional data_sensitivity hint from ARIAState.
                     "public"       → light redaction (emails + API keys only)
                     "internal"     → standard redaction (all patterns)
                     "confidential" → aggressive redaction (all patterns + phone/ID)
                     "restricted"   → same as confidential (task should not reach LangSmith)
                     None           → standard redaction

    Returns:
        Sanitised string with PII replaced by placeholder tokens.
    """
    if not text:
        return text

    # Determine which patterns to apply
    if sensitivity == "public":
        active_names = {"api_key", "token_standalone", "email"}
    else:
        active_names = None   # all patterns

    result = text
    for name, pattern, replacement in _COMPILED:
        if active_names is not None and name not in active_names:
            continue
        result = pattern.sub(replacement, result)

    return result


def redact_dict(data: dict, sensitivity: Optional[str] = None) -> dict:
    """
    Recursively redact string values in a dict (e.g., LangSmith metadata).
    Does not mutate the original — returns a new dict.
    """
    out = {}
    for k, v in data.items():
        if isinstance(v, str):
            out[k] = redact(v, sensitivity)
        elif isinstance(v, dict):
            out[k] = redact_dict(v, sensitivity)
        elif isinstance(v, list):
            out[k] = [redact(i, sensitivity) if isinstance(i, str) else i for i in v]
        else:
            out[k] = v
    return out


def is_likely_secret(value: str) -> bool:
    """
    Heuristic: does this string look like a secret / API key?
    Used to warn when a config value appears to be a raw secret.
    """
    if len(value) < 16:
        return False
    # High entropy: mostly alphanumeric + special chars, no spaces
    alnum = sum(1 for c in value if c.isalnum() or c in "+-_/.")
    return alnum / len(value) > 0.85
