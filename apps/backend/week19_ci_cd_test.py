"""
Week 19 — CI/CD & Release Intelligence + Proactive Notifications

Demonstrates:
  1. CI/CD skill — root cause analysis, deployment safety verdict
  2. Stage classification — build / test / deploy / lint / infra
  3. Severity calibration — critical (main+deploy) vs high vs medium vs low
  4. Proactive notification — notify_team=True → #engineering alert
  5. Cooldown governance — second alert in cooldown window is suppressed
  6. Full graph routing — ci_cd task type end-to-end

Run: uv run python week19_ci_cd_test.py
Exits 0 only if every check passes (or is skipped with a documented reason).
"""
import sys
import json
sys.stdout.reconfigure(encoding="utf-8")

from aria.skills.ci_cd_skill import CICDInput, CICDOutput
import aria.skills.ci_cd_skill as ci_cd_skill
from aria.notifications.notifier import (
    notify_ci_cd_failure,
    reset_cooldowns,
)
from aria.config import has_llm

_failures: list[str] = []


def _check(condition: bool, label: str, skip_reason: str = "") -> None:
    if skip_reason:
        print(f"  [{label}] SKIPPED — {skip_reason}")
        return
    if condition:
        print(f"  [{label}] PASS")
    else:
        print(f"  [{label}] FAIL")
        _failures.append(label)


print("=" * 60)
print("ARIA — Week 19: CI/CD Skill + Proactive Notifications")
print("=" * 60)
print(f"\n  LLM configured: {has_llm()}")
if not has_llm():
    print("  NOTE: severity/stage checks require LLM — marked SKIPPED in mock mode")


# ─────────────────────────────────────────────────────────────────────────────
# 1 — Test Stage Failure (Elasticsearch ConnectionRefusedError)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("1/5  Test stage failure — Elasticsearch port 9200")
print("─" * 60)

result1: CICDOutput = ci_cd_skill.run(CICDInput(
    raw_input="recommendation-service tests failing in CI with ConnectionRefusedError on port 9200",
    task_id="cicd-demo-001",
    pipeline_name="recommendation-service-test",
    branch="feature/ranking-v2",
))

print(f"\n  Summary       : {result1.failure_summary}")
print(f"  Stage failed  : {result1.stage_failed}")
print(f"  Severity      : {result1.severity}")
print(f"  Deploy safe   : {result1.deployment_safe}")
print(f"  Notify team   : {result1.notify_team}")
print(f"  Est. fix time : {result1.estimated_fix_time}")
print(f"\n  Root causes ({len(result1.root_causes)}):")
for rc in result1.root_causes:
    print(f"    [{rc.likelihood:6}] {rc.hypothesis[:65]}")
    print(f"             Fix: {rc.fix[:65]}")
print(f"\n  Suggested fixes:")
for i, fix in enumerate(result1.suggested_fixes, 1):
    print(f"    {i}. {fix[:75]}")

_check(result1.stage_failed == "test", "test-stage-fails-correctly",
       skip_reason="" if has_llm() else "mock always returns fixed stage")
_check(len(result1.root_causes) >= 2, "at-least-2-root-causes")
_check(len(result1.suggested_fixes) >= 1, "at-least-1-suggested-fix")


# ─────────────────────────────────────────────────────────────────────────────
# 2 — Critical Deploy Failure (OOMKilled on main)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("2/5  Critical deploy failure — OOMKilled on main branch")
print("─" * 60)

result2: CICDOutput = ci_cd_skill.run(CICDInput(
    raw_input="notification-service deploy failed on main branch — OOMKilled during startup",
    task_id="cicd-demo-002",
    pipeline_name="notification-service-deploy",
    branch="main",
))

print(f"\n  Summary  : {result2.failure_summary}")
print(f"  Stage    : {result2.stage_failed}  |  Severity: {result2.severity}")
print(f"  Deploy safe: {result2.deployment_safe}  |  Notify team: {result2.notify_team}")

_check(result2.severity == "critical", "oom-on-main-is-critical",
       skip_reason="" if has_llm() else "mock returns fixed severity regardless of input")
_check(result2.notify_team is True, "critical-deploy-notifies-team",
       skip_reason="" if has_llm() else "mock returns fixed notify_team")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Lint Failure (low severity)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("3/5  Lint failure — low severity, no team notification")
print("─" * 60)

result3: CICDOutput = ci_cd_skill.run(CICDInput(
    raw_input="cms-ingestion lint check failing — E501 line too long in article_parser.py",
    task_id="cicd-demo-003",
    pipeline_name="cms-ingestion-lint",
))

print(f"\n  Stage    : {result3.stage_failed}")
print(f"  Severity : {result3.severity}")
print(f"  Notify team: {result3.notify_team}")

_check(result3.stage_failed == "lint" and result3.severity == "low" and not result3.notify_team,
       "lint-is-low-no-notify",
       skip_reason="" if has_llm() else "mock returns fixed stage/severity regardless of input")


# ─────────────────────────────────────────────────────────────────────────────
# 4 — Proactive Notification + Cooldown Governance
#   These checks do NOT depend on the LLM — always assert.
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("4/5  Proactive notification + cooldown governance")
print("─" * 60)

reset_cooldowns()

print("\n  4a — First CI/CD alert (should deliver):")
r1 = notify_ci_cd_failure(
    task_id="cicd-demo-004a",
    pipeline_name="recommendation-service-test",
    failure_summary="Test stage failed — Elasticsearch not reachable in CI",
    severity="high",
    suggested_fix="Add elasticsearch service to CI yaml",
    notify_team=True,
)
_check(r1 is not None and r1.sent, "first-alert-delivered")

print("  4b — Same pipeline within cooldown window (should suppress):")
r2 = notify_ci_cd_failure(
    task_id="cicd-demo-004b",
    pipeline_name="recommendation-service-test",
    failure_summary="Still failing — retry triggered same error",
    severity="high",
    suggested_fix="Add elasticsearch service to CI yaml",
    notify_team=True,
)
if r2:
    print(f"  Result: sent={r2.sent}  reason={r2.reason}  cooldown_remaining={r2.cooldown_remaining_s}s")
_check(r2 is not None and not r2.sent and r2.reason == "cooldown", "cooldown-suppresses-repeat")

print("  4c — notify_team=False (lint failure, should not notify):")
r3 = notify_ci_cd_failure(
    task_id="cicd-demo-004c",
    pipeline_name="cms-ingestion-lint",
    failure_summary="Lint failure — E501",
    severity="low",
    suggested_fix="Run black formatter",
    notify_team=False,
)
_check(r3 is None, "notify-team-false-suppresses")

print("  4d — Critical severity overrides cooldown:")
r4 = notify_ci_cd_failure(
    task_id="cicd-demo-004d",
    pipeline_name="recommendation-service-test",  # same as 4a — would normally be in cooldown
    failure_summary="OOMKilled on main during deploy",
    severity="critical",
    suggested_fix="Increase memory limit in k8s deployment yaml",
    notify_team=True,
)
_check(r4 is not None and r4.sent, "critical-overrides-cooldown")


# ─────────────────────────────────────────────────────────────────────────────
# 5 — Full graph run — ci_cd routing
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("5/5  Full graph run — ci_cd task type routing")
print("─" * 60)

from aria.graph import aria_graph as graph

reset_cooldowns()

state = graph.invoke({
    "raw_input":       "analytics-pipeline build failing: ImportError cannot import name 'AsyncClient' from 'httpx'",
    "task_status":     "pending",
    "messages":        [],
    "steps_completed": [],
    "audience":        "developer",
})

print(f"\n  task_id         : {state['task_id'][:12]}...")
print(f"  task_type       : {state.get('task_type')}")
print(f"  routing_tier    : {state.get('routing_tier')}")
print(f"  steps_completed : {state['steps_completed']}")

_check(state.get("task_type") == "ci_cd", "graph-routes-to-ci-cd")
_check("ci_cd_node" in state["steps_completed"], "ci-cd-node-ran")

try:
    output_data = json.loads(state.get("skill_output", "{}"))
    _check(bool(output_data.get("failure_summary")), "output-is-valid-cicd-schema")
    print(f"\n  skill stage_failed : {output_data.get('stage_failed')}")
    print(f"  skill severity     : {output_data.get('severity')}")
    print(f"  skill notify_team  : {output_data.get('notify_team')}")
    print(f"  root_causes count  : {len(output_data.get('root_causes', []))}")
except Exception as e:
    _check(False, f"output-parse-failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("Week 19 — What Was Built:")
print("  skills/ci_cd_skill.py          → failure_summary, stage_failed, root_causes,")
print("                                    suggested_fixes, deployment_safe, severity")
print("  notifications/notifier.py      → Teams delivery mock, 30-min cooldown,")
print("                                    critical override, notify_team gate")
print("  nodes/skill_nodes.py           → ci_cd_node wired + proactive notification")
print("  graph.py                       → ci_cd task type already routed")

if _failures:
    print(f"\nFAIL — {len(_failures)} check(s) failed:")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("\nPASS — all checks passed.")
