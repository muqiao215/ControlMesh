"""Tests for the optional OpenAI Agents SDK CLI backend seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from controlmesh.cli.base import CLIConfig
from controlmesh.cli.openai_agents_provider import OpenAIAgentsCLI
from controlmesh.cli.stream_events import AssistantTextDelta, ResultEvent, SystemInitEvent


@dataclass(slots=True)
class _FakeRunResult:
    final_output: str
    usage: dict[str, Any] | None = None


async def test_send_maps_sdk_final_output_to_cli_response() -> None:
    cli = OpenAIAgentsCLI(CLIConfig(provider="openai_agents", model="gpt-5.4"))
    cli._run_sdk = _fake_run_sdk(_FakeRunResult("planned answer"))

    response = await cli.send("route this turn")

    assert response.result == "planned answer"
    assert response.is_error is False
    assert response.returncode == 0


async def test_send_streaming_emits_controlmesh_stream_events() -> None:
    cli = OpenAIAgentsCLI(CLIConfig(provider="openai_agents", model="gpt-5.4"))
    cli._run_sdk = _fake_run_sdk(_FakeRunResult("streamed answer"))

    events = [event async for event in cli.send_streaming("route this turn")]

    assert isinstance(events[0], SystemInitEvent)
    assert events[0].session_id is None
    assert isinstance(events[1], AssistantTextDelta)
    assert events[1].text == "streamed answer"
    assert isinstance(events[2], ResultEvent)
    assert events[2].result == "streamed answer"
    assert events[2].is_error is False
    assert events[2].session_id is None


async def test_missing_sdk_returns_not_installed_error(monkeypatch: Any) -> None:
    cli = OpenAIAgentsCLI(CLIConfig(provider="openai_agents", model="gpt-5.4"))

    def fail_import() -> tuple[type[object], type[object]]:
        msg = "No module named 'agents'"
        raise ImportError(msg)

    monkeypatch.setattr("controlmesh.cli.openai_agents_provider._load_agents_sdk", fail_import)

    response = await cli.send("route this turn")

    assert response.is_error is True
    assert response.returncode == 1
    assert "install controlmesh[openai-agents]" in response.result


async def test_send_builds_sdk_agent_with_runtime_tools(monkeypatch: Any) -> None:
    created_agents: list[dict[str, Any]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            created_agents.append(kwargs)

    class FakeRunner:
        @staticmethod
        async def run(_agent: Any, _prompt: str) -> _FakeRunResult:
            return _FakeRunResult("planned answer")

    wrapped_tools: list[Any] = []

    def fake_function_tool(func: Any) -> Any:
        wrapped_tools.append(func)
        return {"tool_name": func.__name__}

    monkeypatch.setattr(
        "controlmesh.cli.openai_agents_provider._load_agents_sdk",
        lambda: (FakeAgent, FakeRunner, fake_function_tool),
    )

    cli = OpenAIAgentsCLI(
        CLIConfig(
            provider="openai_agents",
            model="gpt-5.4",
            agent_name="main",
            chat_id=42,
            topic_id=9,
            process_label="task:feedbeef",
            task_hub=MagicMock(),
            interagent_bus=MagicMock(),
        )
    )

    response = await cli.send("route this turn")

    assert response.result == "planned answer"
    assert len(created_agents) == 1
    tools = created_agents[0]["tools"]
    assert {tool["tool_name"] for tool in tools} == {
        "create_background_task",
        "resume_background_task",
        "ask_parent",
        "send_async_to_agent",
    }
    assert len(wrapped_tools) == 4


def _fake_run_sdk(result: _FakeRunResult) -> Any:
    async def run_sdk(_prompt: str) -> _FakeRunResult:
        return result

    return run_sdk
