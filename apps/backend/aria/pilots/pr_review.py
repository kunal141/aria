"""
Read-only PR Review Pilot (Week 34 §2).

Reads PR metadata + change summary from a deterministic fixture, summarises the
PR, flags risky files and missing tests, and produces draft review comments +
draft Jira items. Read-only: no posting, no GitHub write, no status update — the
drafts are data artifacts only.
"""
from __future__ import annotations

from aria.pilots.drafts import jira_draft, pr_comment_draft
from aria.pilots.models import (
    DraftAction,
    EvidenceReference,
    Finding,
    PilotKind,
    PilotReport,
)


def _module_name(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def run_pr_review(connector, *, pr_id: str = "default") -> PilotReport:
    data, evidence = connector.read_pr(pr_id)
    files = data.get("files", [])
    existing_tests = list(data.get("existing_tests", []))

    findings: list[Finding] = []

    # Risk areas (high/medium-risk files).
    risky = [f for f in files if f.get("risk") in ("high", "medium")]
    for f in risky:
        findings.append(Finding(
            kind="risk", summary=f"{f['path']} — {f.get('reason', 'risky change')}",
            severity=f["risk"], evidence=evidence,
        ))

    # Missing tests: changed Python source files with no matching test file.
    src_files = [f["path"] for f in files
                 if f["path"].endswith(".py") and "/test" not in f["path"]]
    missing = [p for p in src_files
               if not any(_module_name(p) in t for t in existing_tests)]
    for p in missing:
        findings.append(Finding(
            kind="missing_tests", summary=f"No test appears to cover {p}",
            severity="medium", evidence=evidence,
        ))

    # Draft-only review comments (one per risky file) + a draft Jira if tests missing.
    drafts: list[DraftAction] = [
        pr_comment_draft(
            title=f"Review: {f['path']}",
            body=(f"This is a {f['risk']}-risk change ({f.get('reason', '')}). "
                  f"Please add/extend tests and verify {f['path']} before merge."),
            would_target=f"{data['pr_id']}",
        )
        for f in risky
    ]
    if missing:
        drafts.append(jira_draft(
            title=f"Add missing tests for {data['pr_id']}",
            body="Files changed without an apparent test: " + ", ".join(missing),
            would_target="jira",
        ))

    summary = (
        f"PR {data['pr_id']} '{data['title']}' by {data['author']}: "
        f"{len(files)} files changed, {len(risky)} risky, {len(missing)} without tests. "
        f"Draft-only review — nothing posted."
    )
    return PilotReport(
        pilot=PilotKind.pr_review, title="PR Review Report", summary=summary,
        findings=findings, drafts=drafts,
        evidence_references=[EvidenceReference(source=s, detail=f"PR {data['pr_id']}") for s in evidence],
        connector_mode=connector.mode.value,
        boundary="Read-only PR review. Draft-only, nothing posted.",
    )
