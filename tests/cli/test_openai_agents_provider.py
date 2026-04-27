"""Tests for the optional OpenAI Agents SDK CLI backend seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from controlmesh.cli.base import CLIConfig
from controlmesh.cli.openai_agents_provider import OpenAIAgentsCLI
from controlmesh.cli.stream_events import (
    AssistantTextDelta,
    ResultEvent,
    SystemInitEvent,
    SystemStatusEvent,
    ToolResultEvent,
    ToolUseEvent,
)


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


async def test_send_streaming_maps_sdk_stream_events_to_normalized_progress(
    monkeypatch: Any,
) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

    class FakeRunner:
        @staticmethod
        def run_streamed(_agent: Any, **kwargs: Any) -> _FakeStreamedRun:
            assert kwargs["input"] == "route this turn"
            return _FakeStreamedRun(
                final_output="final answer",
                events=[
                    _FakeSdkEvent(
                        "raw_response_event",
                        data=_FakeSdkData("response.output_text.delta", delta="partial "),
                    ),
                    _FakeSdkEvent(
                        "run_item_stream_event",
                        name="tool_called",
                        item=_FakeSdkItem("tool_call_item", name="create_background_task"),
                    ),
                    _FakeSdkEvent(
                        "run_item_stream_event",
                        name="tool_output",
                        item=_FakeSdkItem(
                            "tool_call_output_item",
                            output={
                                "ok": True,
                                "operation": "create_background_task",
                                "summary": "Created background task task_123.",
                                "data": {"task_id": "task_123"},
                            },
                        ),
                    ),
                    _FakeSdkEvent(
                        "run_item_stream_event",
                        name="handoff_requested",
                        item=_FakeSdkItem("handoff_call_item", name="codex"),
                    ),
                ],
            )

        @staticmethod
        async def run(_agent: Any, _prompt: str) -> _FakeRunResult:
            return _FakeRunResult("unused")

    monkeypatch.setattr(
        "controlmesh.cli.openai_agents_provider._load_agents_sdk",
        lambda: (FakeAgent, FakeRunner, lambda func: func),
    )

    cli = OpenAIAgentsCLI(CLIConfig(provider="openai_agents", model="gpt-5.4"))

    events = [event async for event in cli.send_streaming("route this turn")]

    assert isinstance(events[0], SystemInitEvent)
    assert any(isinstance(event, AssistantTextDelta) and event.text == "partial " for event in events)
    assert any(
        isinstance(event, ToolUseEvent) and event.tool_name == "create_background_task"
        for event in events
    )
    assert any(
        isinstance(event, ToolResultEvent)
        and event.tool_name == "create_background_task"
        and event.status == "success"
        for event in events
    )
    assert any(
        isinstance(event, SystemStatusEvent) and event.status == "background_task_created"
        for event in events
    )
    assert any(
        isinstance(event, SystemStatusEvent) and event.status == "handoff_requested"
        for event in events
    )
    assert isinstance(events[-1], ResultEvent)
    assert events[-1].result == "final answer"
    assert events[-1].is_error is False


async def test_send_streaming_midstream_fallback_only_emits_missing_suffix(
    monkeypatch: Any,
) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

    class FakeRunner:
        @staticmethod
        def run_streamed(_agent: Any, **_kwargs: Any) -> _BrokenStreamedRun:
            return _BrokenStreamedRun()

        @staticmethod
        async def run(_agent: Any, _prompt: str) -> _FakeRunResult:
            return _FakeRunResult("partial final answer")

    monkeypatch.setattr(
        "controlmesh.cli.openai_agents_provider._load_agents_sdk",
        lambda: (FakeAgent, FakeRunner, lambda func: func),
    )

    cli = OpenAIAgentsCLI(CLIConfig(provider="openai_agents", model="gpt-5.4"))

    events = [event async for event in cli.send_streaming("route this turn")]

    text_deltas = [event.text for event in events if isinstance(event, AssistantTextDelta)]
    assert text_deltas == ["partial ", "final answer"]
    assert isinstance(events[-1], ResultEvent)
    assert events[-1].result == "partial final answer"


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
        "check_parent_updates",
        "tell_background_task",
        "send_async_to_agent",
    }
    assert len(wrapped_tools) == 6


def _fake_run_sdk(result: _FakeRunResult) -> Any:
    async def run_sdk(_prompt: str) -> _FakeRunResult:
        return result

    return run_sdk


class _FakeStreamedRun:
    def __init__(self, *, final_output: str, events: list[Any]) -> None:
        self.final_output = final_output
        self.usage: dict[str, Any] = {}
        self._events = events

    async def stream_events(self) -> Any:
        for event in self._events:
            yield event


class _BrokenStreamedRun:
    final_output = "unused"
    usage: dict[str, Any] = {}

    async def stream_events(self) -> Any:
        yield _FakeSdkEvent(
            "raw_response_event",
            data=_FakeSdkData("response.output_text.delta", delta="partial "),
        )
        msg = "stream interrupted"
        raise RuntimeError(msg)


class _FakeSdkEvent:
    def __init__(
        self,
        event_type: str,
        *,
        name: str = "",
        item: Any = None,
        data: Any = None,
    ) -> None:
        self.type = event_type
        self.name = name
        self.item = item
        self.data = data


class _FakeSdkData:
    def __init__(self, event_type: str, *, delta: str = "") -> None:
        self.type = event_type
        self.delta = delta


class _FakeSdkItem:
    def __init__(self, item_type: str, *, name: str = "", output: Any = None) -> None:
        self.type = item_type
        self.name = name
        self.output = output
