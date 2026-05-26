from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

from controlmesh.config import AgentConfig
from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.terminal.enhanced_shell import EnhancedShell


class _Inbox:
    def list_unread(self) -> list[object]:
        return []


@pytest.mark.asyncio
async def test_enter_native_runs_native_session() -> None:
    runtime = type("Runtime", (), {"provider": "codex"})()
    shell = EnhancedShell(runtime=runtime, config=AgentConfig())
    native = AsyncMock()

    with patch("controlmesh.terminal.enhanced_shell.NativePTYSession", return_value=native):
        await shell.enter_native()

    native.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_command_enters_native_session() -> None:
    runtime = type(
        "Runtime",
        (),
        {"provider": "codex", "inbox": _Inbox()},
    )()
    inputs = iter(["native", "exit"])
    shell = EnhancedShell(runtime=runtime, config=AgentConfig(), prompt_input=lambda _prompt: next(inputs))
    shell.enter_native = AsyncMock()

    await shell.run()

    shell.enter_native.assert_awaited_once()


@pytest.mark.asyncio
async def test_cm_command_shows_guidance_with_legacy_config() -> None:
    runtime = type(
        "Runtime",
        (),
        {
            "provider": "codex",
            "inbox": _Inbox(),
            "handle_control_command": AsyncMock(),
        },
    )()
    config = AgentConfig()
    config.terminal.native_escape_command = "/cm"
    inputs = iter(["/cm", "exit"])
    output = StringIO()
    shell = EnhancedShell(
        runtime=runtime,
        config=config,
        prompt_input=lambda _prompt: next(inputs),
        console=Console(file=output, width=120),
    )
    shell.enter_native = AsyncMock()

    await shell.run()

    shell.enter_native.assert_not_awaited()
    assert "Run `native`" in output.getvalue()


@pytest.mark.asyncio
async def test_plain_text_calls_model() -> None:
    runtime = type(
        "Runtime",
        (),
        {
            "provider": "codex",
            "inbox": _Inbox(),
            "handle_user_message": AsyncMock(),
        },
    )()
    inputs = iter(["hello there", "exit"])
    output = StringIO()
    shell = EnhancedShell(
        runtime=runtime,
        config=AgentConfig(),
        prompt_input=lambda _prompt: next(inputs),
        console=Console(file=output, width=120),
    )

    await shell.run()

    runtime.handle_user_message.assert_awaited_once()
    assert runtime.handle_user_message.await_args.args[0] == "hello there"


@pytest.mark.asyncio
async def test_chat_command_calls_model_with_message() -> None:
    runtime = type(
        "Runtime",
        (),
        {
            "provider": "codex",
            "inbox": _Inbox(),
            "handle_user_message": AsyncMock(return_value=OrchestratorResult(text="ok")),
        },
    )()
    inputs = iter(["chat hello", "exit"])
    shell = EnhancedShell(runtime=runtime, config=AgentConfig(), prompt_input=lambda _prompt: next(inputs))

    await shell.run()

    runtime.handle_user_message.assert_awaited_once()
    assert runtime.handle_user_message.await_args.args[0] == "hello"


@pytest.mark.asyncio
async def test_slash_chat_command_calls_model_with_message() -> None:
    runtime = type(
        "Runtime",
        (),
        {
            "provider": "codex",
            "inbox": _Inbox(),
            "handle_user_message": AsyncMock(return_value=OrchestratorResult(text="ok")),
        },
    )()
    inputs = iter(["/chat hello", "exit"])
    shell = EnhancedShell(runtime=runtime, config=AgentConfig(), prompt_input=lambda _prompt: next(inputs))

    await shell.run()

    runtime.handle_user_message.assert_awaited_once()
    assert runtime.handle_user_message.await_args.args[0] == "hello"
