"""
Day 2 — LCEL Router Chain (standalone, no graph)

Goal: understand the | pipe operator before plugging into LangGraph.

The chain:
    prompt_template | llm | output_parser

Each | passes the output of the left side as input to the right side.
"""
import json
import aria.config  # loads .env and sets LangSmith env vars

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ── 1. Prompt template ────────────────────────────────────────────────────────
# {raw_input} is the only variable — filled in at invoke() time
SYSTEM_PROMPT = """You are ARIA's task router. Your only job is to classify
the user's input into exactly one task type.

Task types:
- pr_review   : code review, pull request, diff, branch, merge
- kpi         : metrics, CTR, click rate, feed performance, anomaly, drop, spike
- ci_cd       : pipeline, build failure, deploy, release, CI/CD
- jira        : ticket, story, sprint, backlog, blocker, epic
- general     : anything that does not clearly fit the above

Respond with ONLY valid JSON — no explanation, no markdown:
{{"task_type": "<one of the 5 types>", "routing_reason": "<one sentence why>"}}"""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{raw_input}"),
])

# ── 2. LLM ────────────────────────────────────────────────────────────────────
# claude-haiku: fast and cheap — perfect for classification tasks
llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

# ── 3. Output parser ──────────────────────────────────────────────────────────
# StrOutputParser extracts the text content from Claude's response object
str_parser = StrOutputParser()

# ── 4. The chain ──────────────────────────────────────────────────────────────
# This is LCEL. The | operator passes output of each step to the next.
# prompt.invoke(input) → ChatMessage
# llm.invoke(ChatMessage) → AIMessage
# str_parser.invoke(AIMessage) → plain string
chain = prompt | llm | str_parser


def classify(raw_input: str) -> dict:
    raw_output = chain.invoke({"raw_input": raw_input})
    return json.loads(raw_output)


# ── Test ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_inputs = [
        "Review my PR for the recommendation engine changes",
        "Our story feed CTR dropped 18% this week",
        "The GitHub Actions deploy job is failing",
        "Create a Jira story for the notification bug",
        "What is the capital of France?",
        # This one keyword router got wrong — no "kpi" keyword, but Claude knows
        "Our recommendation system seems to be surfacing old content",
    ]

    print("Day 2 — Claude LCEL Router (standalone)\n" + "=" * 50)
    for text in test_inputs:
        result = classify(text)
        print(f"\nINPUT  : {text}")
        print(f"TYPE   : {result['task_type']}")
        print(f"REASON : {result['routing_reason']}")
