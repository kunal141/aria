"""
Typed ledger exceptions.

The reader surfaces malformed records through ``MalformedLedgerRecord``
rather than silently dropping them (per Round-29 persistence rule
"malformed lines produce observable reader errors, not silent deletion").

The writer raises ``LedgerPersistenceError`` on any disk-flush failure,
so logging-failure paths never fabricate successful lifecycle events.

``RedactionViolation`` is raised by ``privacy.sanitize_metadata`` when a
caller asks for ``strict=True`` and a redactable key is present — for
production code paths that want fail-closed behaviour rather than silent
redaction.
"""
from __future__ import annotations


class LedgerError(RuntimeError):
    """Base class for all ledger errors."""


class LedgerPersistenceError(LedgerError):
    """Raised when the ledger writer cannot durably flush a record to disk."""


class RedactionViolation(LedgerError):
    """Raised when strict redaction is requested and a redactable key is present."""


class MalformedLedgerRecord(LedgerError):
    """
    Wrap a single un-parseable line from the JSONL ledger.

    Used by ``LedgerReader`` as a typed record alongside successfully parsed
    events — readers MUST observe these rather than silently skip them.
    Carries:
      - ``source``        : which file the bad line came from
      - ``line_number``   : 1-indexed line in that file
      - ``raw``           : the raw line text (preserved, never discarded)
      - ``parse_error``   : exception message from the failed parse
    """

    def __init__(
        self,
        source: str,
        line_number: int,
        raw: str,
        parse_error: str,
    ) -> None:
        self.source       = source
        self.line_number  = line_number
        self.raw          = raw
        self.parse_error  = parse_error
        super().__init__(
            f"Malformed ledger record at {source}:{line_number}: {parse_error}"
        )
