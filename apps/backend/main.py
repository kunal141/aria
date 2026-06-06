import sys
sys.stdout.reconfigure(encoding="utf-8")  # Windows terminal fix for JSON/Unicode output

from aria.graph import aria_graph

TEST_INPUTS = [
    "Review my PR for the recommendation engine changes",
    "Our CTR has dropped 18% this week, can you investigate?",
    "The CI/CD pipeline is failing on the deploy step",
    "Create a Jira ticket for the notification service bug",
    "What is the capital of France?",
]


def run(raw_input: str) -> dict:
    return aria_graph.invoke({
        "task_id": "",
        "raw_input": raw_input,
        "task_type": None,
        "task_status": "pending",
        "routing_reason": None,
        "steps_completed": [],
        "skill_name": None,
        "skill_output": None,
        "response": None,
        "messages": [],
        "error": None,
    })


if __name__ == "__main__":
    print("=" * 60)
    print("ARIA — Week 8 (Artifact Engine live)")
    print("=" * 60)

    for user_input in TEST_INPUTS:
        result = run(user_input)
        print(f"\nINPUT  : {user_input}")
        print(f"TYPE   : {result['task_type']}")
        print(f"TRAIL  : {result['steps_completed']}")
        print(f"SKILL  : {result.get('skill_name', '-')}")
        print(f"OUTPUT :\n{result['response']}")
        print("-" * 60)
