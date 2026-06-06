from langgraph.graph import StateGraph, END

from aria.state import ARIAState
from aria.nodes.intake import intake
from aria.nodes.router import router
from aria.nodes.respond import respond
from aria.nodes.skill_nodes import (
    pr_review_node, kpi_node, qa_node, test_review_node, ci_cd_node,
    jira_node, analytics_qa_crew_node, general_node,
)


def _route_to_skill(state: ARIAState) -> str:
    """
    Conditional edge function — reads task_type from state,
    returns the NAME of the next node to execute.

    LangGraph calls this after the router node completes.
    The returned string must match a registered node name exactly.
    """
    return {
        "pr_review": "pr_review_node",
        "kpi":       "kpi_node",
        "qa":          "qa_node",
        "test_review": "test_review_node",
        "ci_cd":       "ci_cd_node",
        "jira":      "jira_node",
    }.get(state.get("task_type", "general"), "general_node")


def build_graph():
    graph = StateGraph(ARIAState)

    # Register all nodes
    graph.add_node("intake",         intake)
    graph.add_node("router",         router)
    graph.add_node("pr_review_node", pr_review_node)
    graph.add_node("kpi_node",       kpi_node)
    graph.add_node("qa_node",          qa_node)
    graph.add_node("test_review_node", test_review_node)
    graph.add_node("ci_cd_node",              ci_cd_node)
    graph.add_node("jira_node",               jira_node)
    graph.add_node("analytics_qa_crew_node",  analytics_qa_crew_node)
    graph.add_node("general_node",            general_node)
    graph.add_node("respond",        respond)

    # Fixed edges
    graph.set_entry_point("intake")
    graph.add_edge("intake", "router")

    # Conditional edge — router branches to the right skill node
    # Week 3: router → respond (fixed)
    # Week 4: router → [pr_review_node | kpi_node | ci_cd_node | jira_node | general_node]
    graph.add_conditional_edges(
        "router",           # from this node
        _route_to_skill,    # call this function to decide next node
        {                   # map return values to node names
            "pr_review_node": "pr_review_node",
            "kpi_node":       "kpi_node",
            "qa_node":          "qa_node",
            "test_review_node": "test_review_node",
            "ci_cd_node":       "ci_cd_node",
            "jira_node":      "jira_node",
            "general_node":   "general_node",
        }
    )

    # All skill nodes converge back to respond
    for skill_node in [
        "pr_review_node", "kpi_node", "qa_node", "test_review_node",
        "ci_cd_node", "jira_node", "analytics_qa_crew_node", "general_node",
    ]:
        graph.add_edge(skill_node, "respond")

    graph.add_edge("respond", END)

    return graph.compile()


aria_graph = build_graph()
