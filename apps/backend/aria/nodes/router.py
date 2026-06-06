"""
router.py

Keyword mode : no LLM configured → fast keyword matching (graph always runs)
LLM mode     : any provider configured → LCEL chain (real intelligence)

Same state contract either way. Same fields written. Different brain inside.
This pattern — graceful degradation — is used throughout production AI systems.

Set LLM_PROVIDER in .env to switch models:
  anthropic (default) | ollama | groq | google | openrouter | kimi | qwen | openai
"""
import re
import json
import aria.config  # loads .env before anything else

from aria.config import get_fast_llm, has_llm
from aria.state import ARIAState

# ─────────────────────────────────────────────────────────────────────────────
# Keyword router (no API key needed)
# ─────────────────────────────────────────────────────────────────────────────

# Short tokens that would falsely match inside longer words (e.g. "ci" in "pricing").
# These are tested with word boundaries (\b) instead of plain substring.
_WB_TOKENS = frozenset(["pr", "ci", "cd", "qa", "kpi", "ctr"])

# Rules listed most-specific first to prevent broad tokens swallowing specific phrases.
# test_review MUST precede ci_cd so "ci failing" / "tests failing" fire before "ci" / "failed".
# kpi comes after ci_cd so "failed" in ci_cd doesn't eat KPI anomaly descriptions.
_RULES = [
    (["review test", "test review", "flaky", "flakiness", "flaky test", "ci failing",
      "tests failing", "test quality", "regression test", "test suite", "why are my tests"],
     "test_review", "Input asks to review or diagnose an existing test suite"),
    (["pull request", "code review", "pr", "diff", "merge", "branch"],
     "pr_review", "Input mentions a PR or code review"),
    (["pipeline", "build failure", "build failed", "deploy failed", "deployment failed",
      "release", "github actions", "ci", "cd"],
     "ci_cd", "Input mentions CI/CD or a deployment pipeline"),
    (["jira", "ticket", "story", "sprint", "backlog", "blocker", "epic"],
     "jira", "Input refers to Jira, a ticket, or sprint management"),
    (["analytics crew", "analytics_qa", "deep investigate", "multi-agent analysis",
      "deep dive kpi", "deep dive into kpi"],
     "analytics_qa", "Input requests deep multi-agent analytics investigation"),
    (["kpi", "metric", "ctr", "click-through", "drop", "spike", "anomaly",
      "feed performance", "recommendation quality"],
     "kpi", "Input refers to a KPI, metric, or performance indicator"),
    (["test case", "unit test", "integration test", "edge case", "coverage", "qa",
      "generate test", "write test", "test", "tests"],
     "qa", "Input asks for test case generation or QA analysis"),
]


def _keyword_classify(raw: str) -> tuple[str, str]:
    lower = raw.lower()
    for keywords, skill, reason in _RULES:
        for kw in keywords:
            if kw in _WB_TOKENS:
                if re.search(rf'\b{re.escape(kw)}\b', lower):
                    return skill, reason
            elif kw in lower:
                return skill, reason
    return "general", "No keywords matched — routing to general"


# ─────────────────────────────────────────────────────────────────────────────
# LLM mode: any configured provider — LCEL chain
# ─────────────────────────────────────────────────────────────────────────────
_llm_chain = None

if has_llm():
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    _SYSTEM = """You are ARIA's task router. Classify the user input into exactly one task type.

Task types:
- pr_review   : code review, pull request, diff, branch, merge
- kpi         : metrics, CTR, feed performance, anomaly, drop, spike, recommendation quality
- ci_cd       : pipeline, build failure, deploy, release, CI/CD, GitHub Actions
- jira        : ticket, story, sprint, backlog, blocker, epic
- qa          : generate new test cases, unit/integration tests, QA analysis, coverage gaps
- test_review : review or diagnose EXISTING tests — flaky tests, CI failures, test quality
- general     : anything that does not clearly fit the above

Respond with ONLY valid JSON, no markdown:
{{"task_type": "<one of the 7 types>", "routing_reason": "<one sentence why>"}}"""

    _llm_chain = (
        ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", "{raw_input}")])
        | get_fast_llm(temperature=0)
        | StrOutputParser()
    )

VALID_TYPES = {"pr_review", "kpi", "ci_cd", "jira", "qa", "test_review", "analytics_qa", "general", "unknown"}


def router(state: ARIAState) -> dict:
    if _llm_chain:
        # LLM mode — provider-routed classification
        try:
            raw_output = _llm_chain.invoke({"raw_input": state["raw_input"]})
            parsed = json.loads(raw_output)
            task_type = parsed.get("task_type", "unknown")
            routing_reason = parsed.get("routing_reason", "")
            if task_type not in VALID_TYPES:
                task_type = "unknown"
            import os
            mode = f"[{os.getenv('LLM_PROVIDER', 'anthropic').title()}]"
        except Exception as e:
            task_type, routing_reason = _keyword_classify(state["raw_input"])
            mode = f"[Fallback: {e}]"
    else:
        # Keyword mode — no LLM configured
        task_type, routing_reason = _keyword_classify(state["raw_input"])
        mode = "[Keywords]"

    # Wire ModelRouter — set routing_tier in state (Week 16+)
    try:
        from aria.routing.model_router import route as model_route
        routing_decision = model_route(
            task_type=task_type,
            data_sensitivity=state.get("data_sensitivity"),
            audience=state.get("audience"),
            complexity=state.get("complexity"),
            input_length=len(state.get("raw_input", "")),
        )
        routing_tier = routing_decision.tier
    except Exception:
        routing_tier = "smart"   # safe default

    return {
        "task_type":      task_type,
        "routing_reason": f"{routing_reason} {mode}",
        "routing_tier":   routing_tier,
        "steps_completed": state["steps_completed"] + ["router"],
    }
