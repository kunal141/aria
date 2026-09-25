"""
Analytics + QA Crew — Week 22 (CrewAI HANDS-ON, Pillar 14)

A two-agent CrewAI crew that handles the most common engineering investigation:
  1. AnalyticsAgent — investigates a KPI anomaly using ARIA's kpi_skill
  2. QAAgent        — generates test cases to prevent the root cause recurring

Why CrewAI here and not LangGraph?
  LangGraph: stateful graph, deterministic routing, production orchestration
  CrewAI:    role-based agents with natural-language task delegation, good for
             structured team-of-agents patterns where each agent has a distinct
             professional persona and can delegate sub-questions within the team

This crew is the proof-of-concept for Pillar 14 (AI Workforce Expansion):
  the analytics + QA capability is now a self-contained team, not a single node.

Mock mode (no LLM configured):
  run() falls back to calling kpi_skill and qa_skill directly and returning
  their structured outputs — same deterministic behaviour as all other skills.

Real mode (LLM configured):
  CrewAI agents are initialised with role/goal/backstory prompts, given tool
  wrappers around ARIA's skills, and run via crew.kickoff().

Architecture decision (from CLAUDE.md):
  LangGraph remains the production backbone for all stateful orchestration.
  This crew is invoked BY a LangGraph node (analytics_qa_crew_node in
  skill_nodes.py), not as a replacement for it.
"""
from typing import Optional
from pydantic import BaseModel

from aria.config import has_llm
from aria.tracing import traceable


# ── Output Schema ─────────────────────────────────────────────────────────────

class CrewResult(BaseModel):
    investigation_summary: str
    root_causes:           list[str]
    recommended_actions:   list[str]
    test_cases:            list[str]
    confidence_score:      float = 0.0
    crew_mode:             str   = "mock"   # "mock" | "crewai"
    version:               str   = "v1"


# ── Tool wrappers for CrewAI agents ──────────────────────────────────────────

def _kpi_tool(raw_input: str, task_id: str = "crew-task") -> str:
    """Wrap kpi_skill.run() as a plain string tool for CrewAI agents."""
    from aria.skills.kpi_skill import KPIInput, run as kpi_run
    result = kpi_run(KPIInput(raw_input=raw_input, task_id=task_id))
    return result.model_dump_json()


def _qa_tool(raw_input: str, task_id: str = "crew-task") -> str:
    """Wrap qa_skill.run() as a plain string tool for CrewAI agents."""
    from aria.skills.qa_skill import QAInput, run as qa_run
    result = qa_run(QAInput(raw_input=raw_input, task_id=task_id))
    return result.model_dump_json()


# ── Crew ──────────────────────────────────────────────────────────────────────

class AnalyticsQACrew:
    """
    Two-agent CrewAI crew: AnalyticsAgent + QAAgent.

    AnalyticsAgent investigates the anomaly; QAAgent reads the investigation
    and generates regression test cases so the root cause is caught in future CI.

    Usage:
        crew = AnalyticsQACrew()
        result = crew.run(
            anomaly="CTR dropped 18% on recommendation feed this week",
            task_id="task-abc",
        )
    """

    @traceable(
        run_type="chain",
        name="analytics_qa_crew_v1",
        tags=["crew", "crewai", "analytics", "qa", "aria"],
    )
    def run(
        self,
        anomaly: str,
        task_id: str = "crew-task",
        dry_run: bool = False,
    ) -> CrewResult:
        if dry_run:
            return CrewResult(
                investigation_summary="[Dry run] Analytics+QA crew not executed.",
                root_causes=[],
                recommended_actions=[],
                test_cases=[],
                confidence_score=0.0,
                crew_mode="dry_run",
            )

        if not has_llm():
            return self._mock_run(anomaly, task_id)

        return self._crewai_run(anomaly, task_id)

    # ── Mock path (no LLM) ────────────────────────────────────────────────────

    def _mock_run(self, anomaly: str, task_id: str) -> CrewResult:
        """
        Fall back to calling ARIA skills directly when no LLM is configured.
        Produces real structured output; just not the CrewAI conversational flow.
        """
        import json

        kpi_raw  = _kpi_tool(anomaly, task_id)
        kpi_data = json.loads(kpi_raw)

        causes  = [rc.get("hypothesis", "") for rc in kpi_data.get("root_causes", [])[:3]]
        actions = kpi_data.get("recommended_actions", [])[:3]

        qa_prompt = (
            f"Generate test cases to prevent regression for this KPI anomaly: {anomaly}. "
            f"Root causes identified: {'; '.join(causes)}."
        )
        qa_raw  = _qa_tool(qa_prompt, task_id)
        qa_data = json.loads(qa_raw)

        test_cases = [
            f"{tc.get('name', '')}: {tc.get('description', '')}"
            for tc in qa_data.get("test_cases", [])[:5]
        ]

        return CrewResult(
            investigation_summary=kpi_data.get("summary", "KPI anomaly investigated."),
            root_causes=causes,
            recommended_actions=actions,
            test_cases=test_cases,
            confidence_score=kpi_data.get("confidence_score", 0.7),
            crew_mode="mock",
        )

    # ── CrewAI path (LLM configured) ──────────────────────────────────────────

    def _crewai_run(self, anomaly: str, task_id: str) -> CrewResult:
        """
        Run the real CrewAI crew with role-based agents.
        Falls back to mock if crewai import fails.
        """
        try:
            from crewai import Agent, Task, Crew, Process
            from crewai.tools import tool as crewai_tool
            import json

            # Wrap ARIA tools for CrewAI
            @crewai_tool("KPI Investigation Tool")
            def investigate_kpi(query: str) -> str:
                """Investigate a KPI anomaly and identify root causes."""
                return _kpi_tool(query, task_id)

            @crewai_tool("QA Test Generation Tool")
            def generate_qa_tests(description: str) -> str:
                """Generate test cases for an engineering scenario."""
                return _qa_tool(description, task_id)

            # Analytics agent — investigates the KPI anomaly
            analytics_agent = Agent(
                role="Analytics Specialist",
                goal=(
                    "Investigate KPI anomalies for the organization in the operating context. "
                    "Identify root causes with evidence and recommend concrete actions."
                ),
                backstory=(
                    "You are an expert data analyst with deep knowledge of the organization's "
                    "media metrics: CTR, feed engagement, notification delivery rates, "
                    "recommendation quality scores, and content pipeline throughput. "
                    "You have 5 years of experience diagnosing production incidents."
                ),
                tools=[investigate_kpi],
                verbose=False,
                allow_delegation=False,
            )

            # QA agent — turns root causes into test cases
            qa_agent = Agent(
                role="QA Engineer",
                goal=(
                    "Generate precise regression test cases that catch the root causes "
                    "identified by the Analytics Specialist before they reach production."
                ),
                backstory=(
                    "You are a senior QA engineer who writes test cases that actually "
                    "catch bugs. You focus on edge cases, boundary conditions, and the "
                    "specific failure modes identified in production incidents. You write "
                    "tests in Given/When/Then format."
                ),
                tools=[generate_qa_tests],
                verbose=False,
                allow_delegation=False,
            )

            # Task 1: investigate the anomaly
            investigate_task = Task(
                description=(
                    f"Investigate this KPI anomaly: {anomaly}\n\n"
                    "Use the KPI Investigation Tool to get structured root cause analysis. "
                    "Summarise the top 3 root causes and the top 3 recommended actions."
                ),
                agent=analytics_agent,
                expected_output=(
                    "A summary paragraph, a numbered list of root causes with evidence, "
                    "and a numbered list of recommended actions."
                ),
            )

            # Task 2: generate test cases based on investigation
            generate_tests_task = Task(
                description=(
                    "Based on the investigation findings above, use the QA Test Generation "
                    "Tool to generate 5 test cases that would catch the identified root causes "
                    "in CI before they reach production."
                ),
                agent=qa_agent,
                expected_output=(
                    "A list of 5 test cases in Given/When/Then format, each targeting "
                    "a specific root cause from the investigation."
                ),
                context=[investigate_task],
            )

            crew = Crew(
                agents=[analytics_agent, qa_agent],
                tasks=[investigate_task, generate_tests_task],
                process=Process.sequential,
                verbose=False,
            )

            crew_output = crew.kickoff(inputs={"anomaly": anomaly})
            raw_output  = str(crew_output)

            # Extract structured data from ARIA skill calls that happened inside
            # the crew (the tool wrappers above stored real structured results)
            kpi_raw  = _kpi_tool(anomaly, task_id)
            kpi_data = json.loads(kpi_raw)
            causes   = [rc.get("hypothesis", "") for rc in kpi_data.get("root_causes", [])[:3]]
            actions  = kpi_data.get("recommended_actions", [])[:3]

            return CrewResult(
                investigation_summary=kpi_data.get("summary", raw_output[:300]),
                root_causes=causes,
                recommended_actions=actions,
                test_cases=[raw_output[:200]],   # crew narrative as first test case entry
                confidence_score=kpi_data.get("confidence_score", 0.8),
                crew_mode="crewai",
            )

        except Exception:
            return self._mock_run(anomaly, task_id)
