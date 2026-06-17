"""
Sensitive-memory boundary (Week 32 §5).

V2 has **no authenticated identity layer**, so confidential / restricted /
sensitive memory is out of scope: it must be refused on persist AND return
nothing on retrieve. ``ARIA_USER_ID`` (or any caller-supplied actor) is metadata
only — it is NEVER treated as proof of authorization, so a caller cannot unlock
sensitive memory by claiming an identity.

Classification is deliberately conservative (false-positives are safe — they just
refuse): an explicit declared level wins, otherwise we sniff the scope name and
the structured value for sensitivity markers.
"""
from __future__ import annotations

from typing import Any

from aria.memory_v2.models import SENSITIVE_LEVELS, Sensitivity

# Markers that force a sensitive classification when they appear in the scope
# name or anywhere in the structured value. Conservative on purpose.
_SENSITIVE_MARKERS = (
    "confidential", "restricted", "sensitive", "secret", "password",
    "api_key", "api key", "apikey", "credential", "private_key", "token",
    "ssn", "pii",
)


class SensitiveMemoryError(PermissionError):
    """Raised when a sensitive memory persist is attempted in V2."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Sensitive/confidential/restricted memory is not supported in V2 "
            f"(no authenticated identity layer): {reason}. Proposal refused."
        )
        self.reason = reason


def coerce_sensitivity(value: str | Sensitivity | None) -> Sensitivity:
    """Coerce a declared sensitivity string to the enum (unknown → sensitive).

    An unrecognised declared value is treated as sensitive (fail-closed), never
    silently downgraded to normal.
    """
    if value is None:
        return Sensitivity.normal
    if isinstance(value, Sensitivity):
        return value
    try:
        return Sensitivity(str(value).strip().lower())
    except ValueError:
        return Sensitivity.sensitive


def _contains_marker(text: str) -> str | None:
    low = text.lower()
    for marker in _SENSITIVE_MARKERS:
        if marker in low:
            return marker
    return None


def classify(
    *,
    scope: str,
    structured_value: dict[str, Any] | None,
    declared: str | Sensitivity | None = None,
) -> tuple[bool, str]:
    """Return ``(is_sensitive, reason)``.

    ``declared`` (if confidential/restricted/sensitive) wins. Otherwise scrape the
    scope name and the structured value for sensitivity markers.
    """
    level = coerce_sensitivity(declared)
    if level in SENSITIVE_LEVELS:
        return True, f"declared sensitivity={level.value}"

    marker = _contains_marker(scope or "")
    if marker:
        return True, f"scope contains sensitivity marker {marker!r}"

    if structured_value:
        import json

        try:
            blob = json.dumps(structured_value, default=str)
        except Exception:
            blob = str(structured_value)
        marker = _contains_marker(blob)
        if marker:
            return True, f"value contains sensitivity marker {marker!r}"

    return False, "normal"


def is_sensitive(
    *,
    scope: str,
    structured_value: dict[str, Any] | None = None,
    declared: str | Sensitivity | None = None,
) -> bool:
    return classify(scope=scope, structured_value=structured_value, declared=declared)[0]


REDACTED_TURN_PLACEHOLDER = "[redacted: sensitive content withheld from chat history]"


def redact_chat_content(text: str) -> str:
    """Make chat-turn content safe to persist (Week 32 §5 / P1).

    1. Mask credential-shaped substrings (API keys, bearer tokens, ``password=…``)
       via the ledger redaction helper — applied to ALL content.
    2. If the content carries a sensitivity marker (secret/password/token/api_key/
       confidential/…), do not store the raw sentence at all — store a safe
       placeholder. V2 has no authenticated identity layer, so sensitive chat text
       is never retained verbatim.
    """
    from aria.ledger.privacy import redact_freetext

    if text is None:
        return ""
    masked = redact_freetext(text) or ""
    if _contains_marker(masked) or _contains_marker(text):
        return REDACTED_TURN_PLACEHOLDER
    return masked
