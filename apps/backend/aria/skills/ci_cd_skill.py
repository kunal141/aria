"""
CI/CD & Release Intelligence Skill — Week 19

Analyses build/pipeline failures and produces:
  - One-sentence failure summary
  - Which stage failed (build, test, deploy, lint)
  - Root cause hypotheses ranked by likelihood
  - Concrete fix suggestions with estimated time
  - Deployment safety verdict
  - Notification flag (should #engineering be alerted?)

Domain context: Amar Ujala engineering pipelines
  - recommendation-service  : Python FastAPI, ranking model serving
  - notification-service    : push delivery pipeline, rate limiter
  - cms-ingestion           : article parsing, enrichment, Elasticsearch indexing
  - analytics-pipeline      : CTR event processing, deduplication
  - feed-ranking-service    : personalised feed generation
"""
import json
from typing import Literal

from pydantic import BaseModel, Field

import aria.config
from aria.config import get_routed_llm, has_llm
from aria.tracing import traceable


# ── Input Schema ──────────────────────────────────────────────────────────────

class CICDInput(BaseModel):
    raw_input:        str = Field(..., description="Description of the CI/CD failure or paste of error output")
    task_id:          str = Field(..., description="Unique task identifier from ARIAState")
    failure_log:      str = Field(default="", description="Optional: raw log snippet from CI runner")
    pipeline_name:    str = Field(default="", description="Optional: pipeline name, e.g. recommendation-service-deploy")
    branch:           str = Field(default="", description="Optional: branch that triggered the failure")
    commit_sha:       str = Field(default="", description="Optional: commit SHA for correlation")
    data_sensitivity: str = Field(default="internal", description="Routing signal: public/internal/confidential/restricted")
    audience:         str = Field(default="developer", description="Routing signal: developer/manager/leadership")


# ── Output Schema ─────────────────────────────────────────────────────────────

class FailureHypothesis(BaseModel):
    hypothesis:  str
    likelihood:  Literal["high", "medium", "low"]
    evidence:    str    # what in the log / context supports this
    fix:         str    # concrete fix step


class CICDOutput(BaseModel):
    failure_summary:    str                              # one sentence
    stage_failed:       Literal["build", "test", "deploy", "lint", "infra", "unknown"]
    root_causes:        list[FailureHypothesis]
    suggested_fixes:    list[str]                        # ordered by priority
    estimated_fix_time: str                              # "5 min" | "30 min" | "2 hours"
    deployment_safe:    bool                             # safe to deploy if we fix this?
    notify_team:        bool                             # trigger #engineering notification?
    severity:           Literal["critical", "high", "medium", "low"]
    version:            str = "v1"


# ── Skill Prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """You are ARIA, a CI/CD intelligence specialist for Amar Ujala — India's largest Hindi media platform.

You analyse build and pipeline failures for these services:
- recommendation-service  : FastAPI, ranking model, Redis cache, Elasticsearch
- notification-service    : push delivery, Firebase/APNS, rate limiter, Redis
- cms-ingestion           : article parsing, enrichment, Elasticsearch indexing
- analytics-pipeline      : CTR events, Kafka, deduplication, ClickHouse
- feed-ranking-service    : personalised feed, A/B test assignment, ML model serving

Common failure patterns to recognise:
- Missing environment variable in deployment config
- Database migration conflict (schema change breaks running service)
- Import error after dependency version bump
- Flaky integration test (calls real external service)
- Docker image build failure (dependency conflict, base image change)
- Test timeout (async test with no proper wait condition)
- Lint failure (new rule added to .flake8 or ESLint config)
- Memory/resource exhaustion in test environment

Severity rules:
  critical → main/production branch, deploy stage failed, data loss risk
  high     → feature branch, test stage failed, blocks release
  medium   → test stage failed, flaky (intermittent)
  low      → lint failure, style issue only

notify_team = true when: severity is critical or high, or the failure blocks a scheduled release.

Respond with ONLY valid JSON:
{
  "failure_summary": "one sentence description of what failed and why",
  "stage_failed": "build|test|deploy|lint|infra|unknown",
  "root_causes": [
    {
      "hypothesis": "what caused this",
      "likelihood": "high|medium|low",
      "evidence": "what in the log/context points to this",
      "fix": "concrete fix step"
    }
  ],
  "suggested_fixes": ["priority 1 fix", "priority 2 fix"],
  "estimated_fix_time": "5 min|30 min|2 hours|unknown",
  "deployment_safe": true,
  "notify_team": false,
  "severity": "critical|high|medium|low"
}

Root causes: 2–3 hypotheses ranked by likelihood. Fixes must be actionable in under 5 minutes."""


# ── Skill Function ─────────────────────────────────────────────────────────────

@traceable(
    run_type="chain",
    name="ci_cd_skill_v1",
    tags=["skill", "ci_cd", "aria"],
)
def run(input: CICDInput) -> CICDOutput:
    if not has_llm():
        return CICDOutput(
            failure_summary="[Mock] Test stage failed in recommendation-service — likely missing mock for Elasticsearch",
            stage_failed="test",
            root_causes=[
                FailureHypothesis(
                    hypothesis="Integration test calls real Elasticsearch without a running instance in CI",
                    likelihood="high",
                    evidence="ConnectionRefusedError pattern typically indicates real service call in test environment",
                    fix="Add @pytest.mark.usefixtures('es_mock') or start elasticsearch-test-container in CI config",
                ),
                FailureHypothesis(
                    hypothesis="Missing ELASTICSEARCH_URL environment variable in CI runner",
                    likelihood="medium",
                    evidence="Tests pass locally where .env is present, fail in CI where .env is not committed",
                    fix="Add ELASTICSEARCH_URL=http://localhost:9200 to CI environment variables in GitHub Actions secrets",
                ),
                FailureHypothesis(
                    hypothesis="Recent dependency update changed the ES client API",
                    likelihood="low",
                    evidence="Check git log for recent elasticsearch-py version changes in requirements.txt",
                    fix="Pin elasticsearch-py==8.x.x in requirements.txt to the last known working version",
                ),
            ],
            suggested_fixes=[
                "Add elasticsearch service to CI yaml: services: elasticsearch: image: elasticsearch:8.x",
                "Add ELASTICSEARCH_URL to GitHub Actions env section or repository secrets",
                "Run tests with --ignore=tests/integration until infra is fixed",
            ],
            estimated_fix_time="30 min",
            deployment_safe=False,
            notify_team=True,
            severity="high",
        )

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    human_msg = input.raw_input
    if input.pipeline_name:
        human_msg = f"Pipeline: {input.pipeline_name}  Branch: {input.branch or 'unknown'}\n\n{human_msg}"
    if input.failure_log:
        human_msg += f"\n\n--- FAILURE LOG ---\n{input.failure_log[:3000]}"

    chain = (
        ChatPromptTemplate.from_messages([
            ("system", _SYSTEM),
            ("human", "{raw_input}"),
        ])
        | get_routed_llm(task_type="ci_cd", data_sensitivity=input.data_sensitivity, audience=input.audience, temperature=0)
        | StrOutputParser()
    )

    raw = chain.invoke({"raw_input": human_msg})

    try:
        data = json.loads(raw)
        return CICDOutput(**data)
    except Exception as e:
        return CICDOutput(
            failure_summary=f"Parse error: {e}",
            stage_failed="unknown",
            root_causes=[],
            suggested_fixes=[f"Could not parse analysis: {str(e)[:100]}"],
            estimated_fix_time="unknown",
            deployment_safe=False,
            notify_team=False,
            severity="medium",
        )


# ── Eval-Lite ─────────────────────────────────────────────────────────────────

EVAL_RUBRIC = """
CI/CD Skill — Eval Rubric (1–5)

5 — Root causes are specific to the pipeline/service. Each fix is executable in < 5 min.
    Severity is correctly calibrated (main + deploy = critical, not just "high").
    Estimated fix time is realistic. notify_team matches severity.

4 — Root causes are specific. Minor gap in one fix step. Severity correct.

3 — Root causes present but generic ("dependency issue"). Fixes are vague ("check config").
    Estimated fix time missing or wrong.

2 — Only one root cause. No fix steps. Severity under/over-stated.

1 — Generic CI/CD advice. No service-specific context. No actionable output.
"""

GOLDEN_EXAMPLES = [
    {
        "input": "recommendation-service tests failing in CI with ConnectionRefusedError on port 9200",
        "pipeline_name": "recommendation-service-test",
        "expected_stage": "test",
        "expected_severity": "high",
        "notes": "Port 9200 = Elasticsearch — missing service in CI, not a code bug",
    },
    {
        "input": "notification-service deploy failed on main branch — OOMKilled during startup",
        "pipeline_name": "notification-service-deploy",
        "branch": "main",
        "expected_stage": "deploy",
        "expected_severity": "critical",
        "expected_notify_team": True,
        "notes": "OOMKilled on main deploy = critical; should alert #engineering immediately",
    },
    {
        "input": "cms-ingestion lint check failing — E501 line too long in article_parser.py",
        "pipeline_name": "cms-ingestion-lint",
        "expected_stage": "lint",
        "expected_severity": "low",
        "expected_notify_team": False,
        "notes": "Lint failure = low severity; fix is trivial; no team notification needed",
    },
    {
        "input": "analytics-pipeline build failing: ImportError cannot import name 'AsyncClient' from 'httpx'",
        "pipeline_name": "analytics-pipeline-build",
        "expected_stage": "build",
        "expected_severity": "high",
        "notes": "httpx API change — AsyncClient was added in httpx 0.20.0; check version in requirements.txt",
    },
    {
        "input": "feed-ranking-service tests flaky — passing 7/10 times, random timeout in test_ab_assignment",
        "pipeline_name": "feed-ranking-service-test",
        "expected_stage": "test",
        "expected_severity": "medium",
        "notes": "Flaky = medium; root cause is time.sleep or real service call (Week 18 lesson)",
    },
]
