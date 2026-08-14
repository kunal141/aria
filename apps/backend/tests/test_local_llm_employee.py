"""Local-LLM employee integration regressions."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from aria import config
from aria.api.staging import build_staging_app
from aria.conversation.orchestrator import ConversationOrchestrator
from aria.memory_v2.store import DomainMemoryStore
from aria.memory_v2.workspace import WorkspaceStore
from aria.skills import (
    ci_cd_skill,
    jira_skill,
    kpi_skill,
    pr_review_skill,
    qa_skill,
    test_review_skill,
)
from aria.skills.json_output import parse_json_object


@pytest.mark.parametrize(
    "system_prompt",
    [
        kpi_skill._SYSTEM,
        pr_review_skill._SYSTEM,
        qa_skill._SYSTEM,
        test_review_skill._SYSTEM,
        ci_cd_skill._SYSTEM,
        jira_skill._SYSTEM,
    ],
)
def test_skill_json_prompts_are_literal_messages(system_prompt):
    prompt = ChatPromptTemplate.from_messages(
        [SystemMessage(content=system_prompt), ("human", "{raw_input}")]
    )
    messages = prompt.format_messages(raw_input="test request")
    assert messages[0].content == system_prompt
    assert messages[1].content == "test request"


def test_parse_json_object_accepts_fenced_and_prefixed_output():
    assert parse_json_object('```json\n{"status": "ok"}\n```') == {"status": "ok"}
    assert parse_json_object('Result follows: {"status": "ok"}') == {"status": "ok"}


@pytest.mark.parametrize("value", ["", "not json", "[1, 2, 3]"])
def test_parse_json_object_rejects_missing_objects(value):
    with pytest.raises(ValueError):
        parse_json_object(value)


@pytest.mark.parametrize(
    ("skill_module", "input_type"),
    [
        (ci_cd_skill, "CICDInput"),
        (jira_skill, "JiraInput"),
        (kpi_skill, "KPIInput"),
        (pr_review_skill, "PRReviewInput"),
        (qa_skill, "QAInput"),
        (test_review_skill, "TestReviewInput"),
    ],
)
def test_invalid_local_model_output_is_redacted(monkeypatch, skill_module, input_type):
    secret = "password=LOCAL_MODEL_SECRET"
    monkeypatch.setattr(skill_module, "has_llm", lambda: True)
    monkeypatch.setattr(
        skill_module,
        "get_routed_llm",
        lambda **kwargs: RunnableLambda(lambda _: secret),
    )
    request = getattr(skill_module, input_type)(
        raw_input="Produce a structured response.",
        task_id="task-redaction",
    )
    result = skill_module.run(request)
    rendered = json.dumps(result.model_dump(mode="json"))
    assert "LOCAL_MODEL_SECRET" not in rendered
    assert "details redacted" in rendered


def test_kpi_skill_accepts_fenced_json(monkeypatch):
    output = """```json
    {
      "summary": "CTR declined and needs segmented investigation.",
      "root_causes": [{
        "hypothesis": "Audience mix changed",
        "likelihood": "medium",
        "evidence": "Compare CTR by segment"
      }],
      "recommended_actions": ["Compare segments"],
      "data_needed": ["CTR by segment"],
      "confidence_score": 0.5
    }
    ```"""
    monkeypatch.setattr(kpi_skill, "has_llm", lambda: True)
    monkeypatch.setattr(
        kpi_skill,
        "get_routed_llm",
        lambda **kwargs: RunnableLambda(lambda _: output),
    )
    result = kpi_skill.run(
        kpi_skill.KPIInput(raw_input="CTR dropped", task_id="task-local-llm")
    )
    assert result.summary == "CTR declined and needs segmented investigation."
    assert result.confidence_score == 0.5


def test_ollama_defaults_disable_reasoning_and_bound_output(monkeypatch):
    captured = {}

    class FakeChatOllama:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import langchain_ollama

    monkeypatch.setattr(langchain_ollama, "ChatOllama", FakeChatOllama)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    config.get_llm(provider="ollama", model="gemma4:latest", num_predict=128)
    assert captured["model"] == "gemma4:latest"
    assert captured["base_url"] == "http://127.0.0.1:11434"
    assert captured["reasoning"] is False
    assert captured["num_predict"] == 128
    assert captured["keep_alive"] == "30m"


def test_local_conversation_is_tool_free_and_redacted(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path))
    store = DomainMemoryStore(execution_mode="local_ollama")
    orchestrator = ConversationOrchestrator(store, execution_mode="local_ollama")
    session = orchestrator.start_session(owner="human:test", scope="general")

    class FakeLocalModel:
        def invoke(self, messages):
            assert len(messages) == 3
            assert "ARIA CONTEXT" in messages[1].content
            assert '"workspace": null' in messages[1].content
            return AIMessage(content="I can help plan that work without executing tools.")

    import aria.llm.active_llm

    monkeypatch.setattr(
        aria.llm.active_llm, "build_active_llm", lambda mode: FakeLocalModel()
    )
    result = orchestrator.handle(
        "Hello ARIA, help me plan today", session=session, allow_llm=True
    )
    assert result.response == "I can help plan that work without executing tools."

    called = False

    def should_not_build(mode):
        nonlocal called
        called = True
        return FakeLocalModel()

    monkeypatch.setattr(aria.llm.active_llm, "build_active_llm", should_not_build)
    refused = orchestrator.handle(
        "my password=TOP_SECRET_VALUE", session=session, allow_llm=True
    )
    assert "sensitive" in refused.response.lower()
    assert "TOP_SECRET_VALUE" not in refused.response
    assert called is False
    store.close()


def test_local_conversation_receives_persisted_workspace_context(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path))
    store = DomainMemoryStore(execution_mode="local_ollama")
    workspace_store = WorkspaceStore(execution_mode="local_ollama")
    orchestrator = ConversationOrchestrator(
        store,
        execution_mode="local_ollama",
        workspace_store=workspace_store,
    )
    session = orchestrator.start_session(owner="human:test", scope="general")
    workspace = workspace_store.create_workspace(
        owner=session.owner,
        scope=session.scope,
        session_id=session.session_id,
        correlation_id=session.session_id,
    )
    workspace_store.update_workspace(
        workspace.workspace_id,
        status="planning",
        add_artifact_ref="ws-safe/priority-plan.md",
        final_outcome="planning",
    )

    class ContextAwareModel:
        def invoke(self, messages):
            context = messages[1].content
            assert workspace.workspace_id in context
            assert "priority-plan.md" in context
            assert '"status": "planning"' in context
            return AIMessage(content="The current workspace is in planning.")

    import aria.llm.active_llm

    monkeypatch.setattr(
        aria.llm.active_llm, "build_active_llm", lambda mode: ContextAwareModel()
    )
    result = orchestrator.handle(
        "What is the current workspace status?", session=session, allow_llm=True
    )
    assert result.response == "The current workspace is in planning."
    workspace_store.close()
    store.close()


def test_v2_web_chat_enables_llm_only_for_local_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARIA_LEDGER_V2_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("ARIA_EXECUTION_MODE", "local_ollama")
    monkeypatch.setenv("CONNECTOR_MODE", "fixtures")
    monkeypatch.setenv("ARIA_LIVE_EXECUTION", "false")
    monkeypatch.setattr(
        ConversationOrchestrator,
        "_local_conversation",
        lambda self, text, **kwargs: "Local model web response.",
    )
    client = TestClient(build_staging_app())
    created = client.post("/api/v2/chat/sessions", json={"scope": "general"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    response = client.post(
        f"/api/v2/chat/sessions/{session_id}/messages",
        json={"message": "Hello ARIA, help me plan"},
    )
    assert response.status_code == 200
    assert "Local model web response." in response.text
