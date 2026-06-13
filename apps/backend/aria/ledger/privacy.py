"""
Metadata + free-text redaction boundary for the Work Ledger.

Every event's persisted string fields — ``error``, ``status``, ``outcome``,
``actor`` and every entry in ``metadata`` — pass through this module
before being written to disk. The ledger is the substrate for ROI, the
dataset export, and the fine-tuning training set; a single leaked
credential propagates to every downstream consumer forever.

Two redaction surfaces
----------------------
1. ``sanitize_metadata(dict)`` — sanitises a metadata dict. Keys that
   look sensitive (``api_key``, ``password``, ``token``, ``raw_prompt``,
   …) are wholly replaced with ``REDACTED``. Other values are walked
   recursively and credential patterns embedded inside them are replaced
   in-line via ``redact_freetext``.

2. ``redact_freetext(str)`` — substring-level credential redaction.
   Patterns are NOT anchored to ``^``/``$``; they match anywhere inside
   the string so secrets embedded in a longer message
   (``"got 401 with Bearer eyJ..."``) get masked rather than passing
   through whole.

The sanitiser NEVER mutates the input.

``strict=True`` raises ``RedactionViolation`` on any redactable KEY in a
metadata dict (free-text matches still redact silently — they are
inherently surprise-detect-and-mask).
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from aria.ledger.exceptions import RedactionViolation


REDACTED: str = "[REDACTED]"


# Case-insensitive substrings that mark a metadata key as carrying
# sensitive data. The VALUE under such a key is entirely replaced.
_SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "secret",
    "credential",
    "token",
    "api_key",
    "apikey",
    "auth",
    "cookie",
    "session_id",
    "private_key",
    "ssn",
    "cvv",
    "bearer",
)

# Keys whose names imply they carry full input/output that should not be
# persisted by default.
_RESERVED_REDACT_KEYS: frozenset[str] = frozenset({
    "raw_prompt",
    "raw_input",
    "raw_tool_input",
    "raw_tool_output",
    "raw_artifact",
    "confidential",
})


# Free-text credential patterns. NOT anchored — used with ``re.sub`` so
# secrets embedded mid-string are masked. Each pattern is conservative
# enough to avoid false positives on ordinary prose.
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OpenAI-style API keys: sk-..., sk-proj-..., 16+ allowed chars
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}"),
    # Anthropic API keys
    re.compile(r"sk-ant-(?:api\d+-)?[A-Za-z0-9_\-]{16,}"),
    # GitHub Personal Access Tokens (classic + fine-grained + OAuth)
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    # Slack tokens
    re.compile(r"xox[bpa]-[A-Za-z0-9\-]{10,}"),
    # AWS access key IDs
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # AWS secret access keys (40-char base64)
    re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"),
    # Bearer tokens (case-insensitive prefix). Match the whole token
    # body so "Bearer eyJhbGc..." → "Bearer [REDACTED]".
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]+=*"),
    # Basic-auth credentials
    re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{16,}"),
    # JWT-shaped tokens (three dot-separated base64url segments)
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    # Stripe-style keys
    re.compile(r"(?:pk|sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    # Google API keys (AIzaSy...)
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
)


def _should_redact_key(key: str) -> bool:
    if key in _RESERVED_REDACT_KEYS:
        return True
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def contains_credential_pattern(value: str) -> bool:
    """True if ``value`` contains any credential-shaped substring."""
    if not isinstance(value, str) or not value:
        return False
    return any(pattern.search(value) for pattern in _CREDENTIAL_PATTERNS)


def redact_freetext(value: Optional[str]) -> Optional[str]:
    """
    Mask any credential-shaped substring inside ``value`` with
    ``REDACTED``. Returns the input unchanged if no pattern matches, or
    ``None`` if ``value`` is None. Bearer-prefixed tokens keep their
    ``"Bearer "`` literal so downstream readers can still tell what kind
    of credential leaked.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if not value:
        return value
    result = value
    for pattern in _CREDENTIAL_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


# ── Metadata sanitiser (dict-shaped) ──────────────────────────────────────────


def _redact_value(value: Any, *, strict: bool, path: str) -> Any:
    if isinstance(value, str):
        return redact_freetext(value)
    if isinstance(value, dict):
        return _walk_dict(value, strict=strict, _path=path)
    if isinstance(value, list):
        return _redact_list(value, strict=strict, path=path)
    return value


def _walk_dict(
    data: dict[str, Any],
    *,
    strict: bool,
    _path: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        nested_path = f"{_path}.{key}" if _path else key
        if not isinstance(key, str):
            # Non-string keys are exotic — keep as-is but still sanitise value.
            out[key] = _redact_value(value, strict=strict, path=nested_path)
            continue
        if _should_redact_key(key):
            if strict:
                raise RedactionViolation(
                    f"Redactable key present at {nested_path!r}; refusing to "
                    "persist in strict mode."
                )
            out[key] = REDACTED
            continue
        out[key] = _redact_value(value, strict=strict, path=nested_path)
    return out


def _redact_list(
    items: Iterable[Any],
    *,
    strict: bool,
    path: str,
) -> list[Any]:
    result: list[Any] = []
    for idx, item in enumerate(items):
        nested_path = f"{path}[{idx}]"
        result.append(_redact_value(item, strict=strict, path=nested_path))
    return result


def sanitize_metadata(
    metadata: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """
    Return a sanitized copy of ``metadata`` with:
      - sensitive KEYS wholly replaced with ``REDACTED``
      - free-text VALUES redacted via ``redact_freetext`` (substring match)
      - nested dicts / lists walked recursively

    Never mutates the input.
    """
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise TypeError(
            f"metadata must be a dict, got {type(metadata).__name__}"
        )
    return _walk_dict(metadata, strict=strict, _path="")
