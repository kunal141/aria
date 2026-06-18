"""
Full V2 internal-pilot end-to-end demo — Week 35 (offline, deterministic).

ONE command that walks the whole V2 internal AI-employee loop with no cloud
credentials and no live connectors:

    converse -> teach memory -> approve -> persist (SQLite) -> RESTART -> recall
    (cited) -> analytics pilot (memory explains + fixture evidence) -> CI/CD pilot
    (Teams preview) -> PR pilot (review drafts) -> workspace artifacts -> Work
    Ledger trace -> explicit boundary statement.

Run it from the backend directory:

    cd apps/backend
    uv run python -m aria.demo.v2_full_pilot        # delete temp state on exit
    uv run python -m aria.demo.v2_full_pilot --keep # keep temp state to inspect

Isolation (no repo pollution): the demo points ``ARIA_DATA_DIR`` and the v2 Work
Ledger at a throwaway temp directory, resets the default ledger writer, runs the
whole flow against the real FastAPI V2 app in-process, then restores the
environment and deletes the temp directory on exit. It strips every provider key
and forces ``CONNECTOR_MODE=fixtures`` so a paid call or a live connector is
impossible.

Nothing here is production code. No external write, no Jira/Teams/PR action, no
vLLM, no training, no deployment occurs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

try:  # Windows terminal fix for unicode output
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

_BAR = "=" * 70
_RULE = "-" * 70

CANONICAL = (
    "In story_events table, event_type = 1 means page_view, "
    "event_type = 2 means story_click, event_type = 3 means notification_open."
)

_PROVIDER_KEY_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY", "GITHUB_TOKEN",
)

_ISOLATED_ENV_VARS = (
    "ARIA_DATA_DIR", "ARIA_LEDGER_V2_PATH", "CONNECTOR_MODE", "ARIA_USER_ID",
    "ARIA_EXECUTION_MODE",
)


def _stream(client, sid: str, message: str) -> list[dict]:
    r = client.post(f"/api/v2/chat/sessions/{sid}/messages", json={"message": message})
    return [json.loads(line) for line in r.text.strip().splitlines()]


def _first(events: list[dict], event: str) -> dict | None:
    return next((e for e in events if e["event"] == event), None)


def run_demo(write=print, *, keep: bool = False) -> dict[str, Any]:
    """Run the full V2 pilot end-to-end in an isolated temp dir and return a typed
    proof summary. ``write`` is injectable so tests can capture output."""
    saved_env = {k: os.environ.get(k) for k in (_ISOLATED_ENV_VARS + _PROVIDER_KEY_VARS)}
    tmp = Path(tempfile.mkdtemp(prefix="aria_v2_demo_"))
    data_dir = tmp / "aria_data"
    ledger_path = tmp / "work_ledger_v2.jsonl"

    # Offline + fixtures + isolated. A paid call / live connector is impossible,
    # and the recorded execution_mode is pinned to offline_mock so an ambient
    # ARIA_EXECUTION_MODE=cloud_opt_in cannot leak a "cloud" label into the ledger.
    for var in _PROVIDER_KEY_VARS:
        os.environ.pop(var, None)
    os.environ["ARIA_DATA_DIR"] = str(data_dir)
    os.environ["ARIA_LEDGER_V2_PATH"] = str(ledger_path)
    os.environ["CONNECTOR_MODE"] = "fixtures"
    os.environ["ARIA_EXECUTION_MODE"] = "offline_mock"
    os.environ.pop("ARIA_USER_ID", None)

    from aria.ledger.writer import reset_default_writer

    reset_default_writer()  # rebind the default writer to the isolated ledger

    summary: dict[str, Any] = {"data_dir": str(data_dir), "ledger_path": str(ledger_path)}
    try:
        from fastapi.testclient import TestClient

        from aria.api.v2 import build_v2_app
        from aria.connectors import resolve_connector_mode
        from aria.llm import resolve_execution_mode

        summary["execution_mode"] = resolve_execution_mode().value
        summary["connector_mode"] = resolve_connector_mode().value

        write(_BAR)
        write("ARIA — FULL V2 INTERNAL-PILOT DEMO (Week 35)")
        write("offline · deterministic · fixtures · no cloud, no live connector")
        write(f"isolated ARIA_DATA_DIR: {data_dir}")
        write(f"execution mode        : {summary['execution_mode']} (pinned)")
        write(f"connector mode        : {summary['connector_mode']}")
        write(_BAR)

        client = TestClient(build_v2_app())

        # 1) start session
        sid = client.post("/api/v2/chat/sessions", json={"scope": "analytics.events"}).json()["session_id"]
        summary["session_id"] = sid
        write(f"\n[1] session started: {sid}")

        # 2-5) teach -> propose -> approve -> persist
        ev = _stream(client, sid, CANONICAL)
        proposed = _first(ev, "memory.proposed")
        proposal_id = proposed["data"]["proposal_id"]
        write(f"[2-3] taught canonical fact; ARIA proposed memory {proposal_id[:14]} (pending approval)")
        decision = client.post(f"/api/v2/memory/proposals/{proposal_id}/decision",
                               json={"decision": "approve", "session_id": sid}).json()
        mem_id = decision["memory_id"]
        summary["memory_id"] = mem_id
        write(f"[4-5] user approved; memory {mem_id[:14]} v{decision['memory_version']} persisted in SQLite")

        # 6) RESTART — a brand-new app/client reading the same SQLite
        client2 = TestClient(build_v2_app())
        write("[6] restarted (fresh app + fresh DB connections, same ARIA_DATA_DIR)")

        # 7-8) recall after restart, with citation
        ev = _stream(client2, sid, "What does event_type mean in story_events?")
        recalled = _first(ev, "memory.recalled")
        summary["recall_cited"] = recalled is not None and recalled["data"]["memory_id"] == mem_id
        cite = recalled["data"] if recalled else {}
        write(f"[7-8] recalled after restart with citation: memory {cite.get('memory_id','?')[:14]} "
              f"v{cite.get('version')} — {cite.get('retrieval_reason','')}")

        # 9-12) analytics pilot: memory explains values, fixtures prove counts
        ev = _stream(client2, sid, "Check story_events event_type distribution and explain the values")
        an = _first(ev, "pilot.report")["data"]
        summary["analytics"] = {
            "pilot": an["pilot"], "memory_citations": len(an["memory_citations"]),
            "evidence": an["evidence_references"],
            "drafts": sum(1 for e in ev if e["event"] == "draft.created"),
            "connector_mode": an["connector_mode"],
        }
        write(f"[9-12] analytics pilot: {an['pilot']} (mode {an['connector_mode']}); "
              f"{len(an['memory_citations'])} memory citation(s); evidence {an['evidence_references']}; "
              f"{summary['analytics']['drafts']} draft-only action(s)")

        # 13-14) CI/CD pilot: diagnosis + Teams preview only
        ev = _stream(client2, sid, "Investigate the CI/CD pipeline failure")
        ci = _first(ev, "pilot.report")["data"]
        summary["ci_cd"] = {"pilot": ci["pilot"],
                            "drafts": sum(1 for e in ev if e["event"] == "draft.created")}
        write(f"[13-14] CI/CD pilot: {ci['pilot']}; {summary['ci_cd']['drafts']} Teams preview (not sent)")

        # 15-16) PR pilot: review comments + Jira drafts only
        ev = _stream(client2, sid, "Review this PR for the recommendation engine")
        pr = _first(ev, "pilot.report")["data"]
        summary["pr_review"] = {"pilot": pr["pilot"],
                               "drafts": sum(1 for e in ev if e["event"] == "draft.created")}
        write(f"[15-16] PR pilot: {pr['pilot']}; {summary['pr_review']['drafts']} review/Jira draft(s) (not posted)")

        # 17) workspace contains artifacts/evidence/citations/drafts
        ws_id = pr["workspace_id"]
        ws = client2.get(f"/api/v2/workspaces/{ws_id}").json()
        summary["workspace"] = {
            "workspace_id": ws_id, "artifacts": ws["artifact_refs"],
            "citations": len(ws["memory_citations"]), "drafts": len(ws["approval_refs"]),
            "status": ws["status"],
        }
        write(f"[17] workspace {ws_id[:14]}: {len(ws['artifact_refs'])} report artifact(s), "
              f"{len(ws['memory_citations'])} citation(s), {len(ws['approval_refs'])} draft ref(s)")

        # 18) Work Ledger trace
        types = _ledger_event_types(ledger_path)
        summary["ledger_event_types"] = sorted(set(types))
        write(f"[18] Work Ledger trace ({len(types)} events): "
              f"{', '.join(sorted(set(types)))}")

        # 19) explicit boundary statement
        summary["boundaries"] = _BOUNDARIES
        write(f"\n{_RULE}")
        write("BOUNDARY — what this demo did NOT do:")
        for b in _BOUNDARIES:
            write(f"  • {b}")

        # Active approved memory is listed read-only.
        mem_list = client2.get("/api/v2/memory").json()
        summary["active_memory_count"] = mem_list["count"]
        write(f"\nActive approved memory: {mem_list['count']} (read-only listing).")
        write(_BAR)
        write("Prototype / demonstration only. No external write, no cloud, no")
        write("training, and no deployment occurred during this run.")
        write(_BAR)

        summary["ok"] = True
        return summary
    finally:
        reset_default_writer()
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if keep:
            write(f"\n[--keep] temp V2 state retained at: {tmp}")
            summary["temp_cleaned"] = False
        else:
            shutil.rmtree(tmp, ignore_errors=True)
            summary["temp_cleaned"] = not tmp.exists()


_BOUNDARIES = (
    "no external writes",
    "no Jira ticket created",
    "no Teams message sent",
    "no PR comment posted",
    "no live connector used (CONNECTOR_MODE=fixtures)",
    "no cloud / paid model call (no provider key)",
    "no vLLM serving",
    "no real fine-tuning / training",
    "no model deployment",
)


def _ledger_event_types(ledger_path: Path) -> list[str]:
    if not ledger_path.exists():
        return []
    return [json.loads(line)["event_type"] for line in ledger_path.read_text(encoding="utf-8").splitlines()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m aria.demo.v2_full_pilot",
        description="Offline, deterministic full V2 internal-pilot demo (fixtures; no cloud).",
    )
    parser.add_argument("--keep", action="store_true",
                        help="keep the temp V2 state directory instead of deleting it on exit")
    args = parser.parse_args(argv)
    result = run_demo(write=print, keep=args.keep)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
