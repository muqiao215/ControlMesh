"""Extended CLIService tests -- covering _make_cli provider resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from controlmesh.cli.base import CLIConfig
from controlmesh.cli.process_registry import ProcessRegistry
from controlmesh.cli.service import CLIService, CLIServiceConfig
from controlmesh.cli.stream_events import (
    AssistantTextDelta,
    ResultEvent,
    SystemInitEvent,
    SystemStatusEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from controlmesh.cli.types import AgentRequest
from controlmesh.config import ModelRegistry


def _make_service(tmp_path: Path, **overrides: Any) -> CLIService:
    config = CLIServiceConfig(
        working_dir=str(tmp_path),
        default_model=overrides.pop("default_model", "opus"),
        provider=overrides.pop("provider", "claude"),
        max_turns=overrides.pop("max_turns", None),
        max_budget_usd=overrides.pop("max_budget_usd", None),
        permission_mode=overrides.pop("permission_mode", "bypassPermissions"),
        gemini_api_key=overrides.pop("gemini_api_key", None),
    )
    return CLIService(
        config=config,
        models=ModelRegistry(),
        available_providers=overrides.pop("available_providers", frozenset({"claude"})),
        process_registry=ProcessRegistry(),
    )


def test_make_cli_default_provider(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(AgentRequest(prompt="test", chat_id=1))

    call_args = mock_create.call_args[0][0]
    assert isinstance(call_args, CLIConfig)
    assert call_args.provider == "claude"
    assert call_args.model == "opus"


def test_make_cli_respects_openai_agents_service_provider(tmp_path: Path) -> None:
    svc = _make_service(tmp_path, default_model="gpt-5.4", provider="openai_agents")
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(AgentRequest(prompt="test", chat_id=1))

    call_args = mock_create.call_args[0][0]
    assert call_args.provider == "openai_agents"
    assert call_args.model == "gpt-5.4"


def test_make_cli_with_model_override(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(AgentRequest(prompt="test", model_override="sonnet", chat_id=1))

    call_args = mock_create.call_args[0][0]
    assert call_args.model == "sonnet"
    assert call_args.provider == "claude"


def test_make_cli_with_provider_override(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(AgentRequest(prompt="test", provider_override="codex", chat_id=1))

    call_args = mock_create.call_args[0][0]
    assert call_args.provider == "codex"


def test_make_cli_with_openai_agents_provider_override(tmp_path: Path) -> None:
    svc = _make_service(tmp_path, default_model="sonnet")
    svc.update_config(
        CLIServiceConfig(
            working_dir=str(tmp_path),
            default_model="sonnet",
            provider="claude",
            max_turns=None,
            max_budget_usd=None,
            permission_mode="bypassPermissions",
            claude_cli_parameters=("--claude-flag", "claude-value"),
        )
    )
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(
            AgentRequest(
                prompt="test",
                provider_override="openai_agents",
                model_override="gpt-5.4",
                chat_id=1,
            )
        )

    call_args = mock_create.call_args[0][0]
    assert call_args.provider == "openai_agents"
    assert call_args.model == "gpt-5.4"
    assert call_args.cli_parameters == []


def test_make_cli_passes_runtime_dependencies_to_openai_agents(tmp_path: Path) -> None:
    svc = _make_service(tmp_path, default_model="gpt-5.4", provider="openai_agents")
    task_hub = MagicMock()
    interagent_bus = MagicMock()
    svc.update_runtime_dependencies(task_hub=task_hub, interagent_bus=interagent_bus)

    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(AgentRequest(prompt="test", chat_id=1, topic_id=2))

    call_args = mock_create.call_args[0][0]
    assert call_args.provider == "openai_agents"
    assert call_args.task_hub is task_hub
    assert call_args.interagent_bus is interagent_bus


def test_make_cli_does_not_auto_fallback_provider(tmp_path: Path) -> None:
    """Native model/provider mapping should be preserved even if unavailable."""
    svc = _make_service(tmp_path, available_providers=frozenset({"codex"}))
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(AgentRequest(prompt="test", chat_id=1))

    call_args = mock_create.call_args[0][0]
    assert call_args.provider == "claude"
    assert call_args.model == "opus"


def test_make_cli_passes_system_prompts(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(
            AgentRequest(
                prompt="test",
                system_prompt="Be helpful",
                append_system_prompt="Follow rules",
                chat_id=1,
            )
        )

    call_args = mock_create.call_args[0][0]
    assert call_args.system_prompt == "Be helpful"
    assert call_args.append_system_prompt == "Follow rules"


def test_make_cli_passes_process_label(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(AgentRequest(prompt="test", chat_id=42, process_label="worker"))

    call_args = mock_create.call_args[0][0]
    assert call_args.chat_id == 42
    assert call_args.process_label == "worker"


def test_make_cli_passes_gemini_api_key(tmp_path: Path) -> None:
    svc = _make_service(tmp_path, gemini_api_key="cfg-key-123")
    with patch("controlmesh.cli.service.create_cli") as mock_create:
        mock_create.return_value = MagicMock()
        svc._make_cli(AgentRequest(prompt="test", provider_override="gemini", chat_id=1))

    call_args = mock_create.call_args[0][0]
    assert call_args.provider == "gemini"
    assert call_args.gemini_api_key == "cfg-key-123"


async def test_execute_streaming_openai_agents_dispatches_progress_callbacks(tmp_path: Path) -> None:
    svc = _make_service(tmp_path, default_model="gpt-5.4", provider="openai_agents")

    class FakeCLI:
        async def send_streaming(self, **_kwargs: Any) -> Any:
            yield SystemInitEvent(type="system", subtype="init")
            yield ToolUseEvent(type="assistant", tool_name="create_background_task")
            yield SystemStatusEvent(type="system", subtype="status", status="background_task_created")
            yield AssistantTextDelta(type="assistant", text="queued task")
            yield ResultEvent(type="result", result="queued task", is_error=False, returncode=0)

    with patch("controlmesh.cli.service.create_cli", return_value=FakeCLI()):
        text_events: list[str] = []
        tool_events: list[str] = []
        system_events: list[str | None] = []

        async def on_text(delta: str) -> None:
            text_events.append(delta)

        async def on_tool(name: str) -> None:
            tool_events.append(name)

        async def on_system(status: str | None) -> None:
            system_events.append(status)

        response = await svc.execute_streaming(
            AgentRequest(prompt="test", chat_id=1),
            on_text_delta=on_text,
            on_tool_activity=on_tool,
            on_system_status=on_system,
        )

    assert response.result == "queued task"
    assert text_events == ["queued task"]
    assert tool_events == ["create_background_task"]
    assert system_events == ["background_task_created"]


async def test_execute_streaming_ignores_tool_result_events_in_callback_contract(tmp_path: Path) -> None:
    svc = _make_service(tmp_path, default_model="gpt-5.4", provider="openai_agents")

    class FakeCLI:
        async def send_streaming(self, **_kwargs: Any) -> Any:
            yield SystemInitEvent(type="system", subtype="init")
            yield ToolResultEvent(
                type="tool_result",
                tool_id="tool-1",
                tool_name="create_background_task",
                status="success",
                output="created",
            )
            yield ResultEvent(type="result", result="done", is_error=False, returncode=0)

    with patch("controlmesh.cli.service.create_cli", return_value=FakeCLI()):
        tool_events: list[str] = []
        system_events: list[str | None] = []

        async def on_tool(name: str) -> None:
            tool_events.append(name)

        async def on_system(status: str | None) -> None:
            system_events.append(status)

        response = await svc.execute_streaming(
            AgentRequest(prompt="test", chat_id=1),
            on_tool_activity=on_tool,
            on_system_status=on_system,
        )

    assert response.result == "done"
    assert tool_events == []
    assert system_events == []
