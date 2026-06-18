"""
Draft-only action builders (Week 34 §5).

These produce :class:`DraftAction` **data artifacts** with explicit boundary text.
They deliberately do NOT import or call any existing Jira / Teams / GitHub
integration function — nothing here can post, send, create, or mutate an external
system. A draft is just structured data attached to a workspace + the Work Ledger.
"""
from __future__ import annotations

import uuid

from aria.pilots.models import (
    JIRA_BOUNDARY,
    PR_COMMENT_BOUNDARY,
    TEAMS_BOUNDARY,
    DraftAction,
    DraftKind,
)


def _draft_id() -> str:
    return f"draft-{uuid.uuid4().hex}"


def jira_draft(*, title: str, body: str, would_target: str = "jira") -> DraftAction:
    return DraftAction(
        draft_id=_draft_id(), kind=DraftKind.jira, title=title, body=body,
        boundary=JIRA_BOUNDARY, would_target=would_target,
    )


def teams_preview(*, title: str, body: str, would_target: str = "teams") -> DraftAction:
    return DraftAction(
        draft_id=_draft_id(), kind=DraftKind.teams, title=title, body=body,
        boundary=TEAMS_BOUNDARY, would_target=would_target,
    )


def pr_comment_draft(*, title: str, body: str, would_target: str = "github_pr") -> DraftAction:
    return DraftAction(
        draft_id=_draft_id(), kind=DraftKind.pr_comment, title=title, body=body,
        boundary=PR_COMMENT_BOUNDARY, would_target=would_target,
    )
