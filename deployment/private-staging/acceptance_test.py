"""Loopback-only end-to-end and restart verification for private ARIA staging."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _base(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("private staging acceptance only permits loopback HTTP URLs")
    return url.rstrip("/")


def _request(base: str, path: str, *, method: str = "GET", body=None,
             expected: int = 200):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{base}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = json.load(exc)
    if status != expected:
        raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {payload}")
    return payload


def _assert_completed(base: str, run_id: str, goal_id: str | None = None) -> dict:
    view = _request(base, f"/api/v4/employee-runs/{run_id}")
    assert view["run"]["status"] == "completed"
    if goal_id is not None:
        assert view["run"]["goal_id"] == goal_id
    assert [item["status"] for item in view["attempts"]] == ["quality_failed", "passed"]
    assert [item["passed"] for item in view["evaluations"]] == [False, True]
    assert len(view["repair_plans"]) == 1
    assert view["repair_plans"][0]["failure_codes"] == ["missing_risks"]
    assert view["final_report"]["evidence_refs"]
    assert view["run"]["manager_report_ref"]
    assert view["estimated_minutes_saved"] > 0
    assert "not production ROI" in view["roi_method"]
    assert len(view["adapter_requests"]) == 2
    assert len(view["receipt_refs"]) == 4
    assert len(set(view["receipt_refs"])) == 4
    ledger = _request(base, f"/api/v4/employee-runs/{run_id}/ledger")
    outcomes = [event.get("outcome") for event in ledger["events"]]
    for expected in (
        "employee_run_started", "route_requested", "quality_failed", "repair_planned",
        "retry_started", "quality_passed", "manager_report_created",
        "manager_approval_requested", "goal_completed", "roi_estimated",
        "employee_run_completed",
    ):
        assert expected in outcomes
    return view


def run(base: str, state_file: Path | None) -> dict:
    _request(base, "/ready")
    body = {
        "goal_text": "Investigate the notification CTR decline and produce a manager report.",
        "dataset_id": "fixture-private-staging-v1",
        "metric_name": "notification_ctr",
        "previous": {"label": "previous_week", "impressions": 100000, "clicks": 4200},
        "current": {"label": "current_week", "impressions": 105000, "clicks": 3780},
        "source_refs": ["fixture://private-staging/notification-ctr-v1"],
        "max_attempts": 2,
        "exercise_repair_loop": True,
    }
    pending = _request(
        base, "/api/v4/employee-runs/business-analysis", method="POST", body=body,
        expected=201,
    )
    assert pending["run"]["status"] == "awaiting_approval"
    assert pending["goal"]["status"] == "awaiting_approval"
    run_id = pending["run"]["run_id"]
    goal_id = pending["run"]["goal_id"]
    completed = _request(
        base, f"/api/v4/employee-runs/{run_id}/approve-completion", method="POST",
        body={"decision": "approve"},
    )
    assert completed["run"]["status"] == "completed"
    view = _assert_completed(base, run_id, goal_id)
    _request(
        base, f"/api/v4/employee-runs/{run_id}/approve-completion", method="POST",
        body={"decision": "approve"}, expected=409,
    )
    state = {"run_id": run_id, "goal_id": goal_id,
             "attempt_ids": [item["attempt_id"] for item in view["attempts"]],
             "receipt_refs": view["receipt_refs"]}
    if state_file is not None:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ACCEPTANCE_OK", **state}, sort_keys=True))
    return state


def verify(base: str, state_file: Path) -> dict:
    state = json.loads(state_file.read_text(encoding="utf-8"))
    view = _assert_completed(base, state["run_id"], state["goal_id"])
    assert [item["attempt_id"] for item in view["attempts"]] == state["attempt_ids"]
    assert view["receipt_refs"] == state["receipt_refs"]
    _request(
        base, f"/api/v4/employee-runs/{state['run_id']}/approve-completion", method="POST",
        body={"decision": "approve"}, expected=409,
    )
    print(json.dumps({"status": "RESTART_PERSISTENCE_OK", **state}, sort_keys=True))
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "verify"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args(argv)
    base = _base(args.base_url)
    if args.command == "run":
        run(base, args.state_file)
    else:
        if args.state_file is None:
            parser.error("verify requires --state-file")
        verify(base, args.state_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
