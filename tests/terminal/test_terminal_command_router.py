from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from rich.console import Console

from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.terminal.command_router import TerminalCommandRouter
from controlmesh.terminal.inbox import TerminalInbox, TerminalInboxItem


@pytest.mark.asyncio
async def test_at_agent_command_routes_to_runtime_agent() -> None:
    runtime = SimpleNamespace(send_agent=AsyncMock(return_value=OrchestratorResult(text="ok")))
    router = TerminalCommandRouter(runtime)

    result = await router.handle("/@coder inspect this")

    runtime.send_agent.assert_awaited_once_with("coder", "inspect this")
    assert result is not None
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_inbox_command_lists_items(tmp_path) -> None:
    inbox = TerminalInbox(tmp_path / "inbox.jsonl")
    inbox.append(TerminalInboxItem(kind="task_update", title="Done", body="task finished"))
    runtime = SimpleNamespace(inbox=inbox)
    router = TerminalCommandRouter(runtime)

    result = await router.handle("/inbox")

    assert result is not None
    assert "Done" in result.text
    assert "task finished" in result.text


@pytest.mark.asyncio
async def test_memory_inject_queues_hit() -> None:
    memory = SimpleNamespace(inject=Mock())
    runtime = SimpleNamespace(memory=memory)
    router = TerminalCommandRouter(runtime)

    result = await router.handle("/memory inject hit_001")

    memory.inject.assert_called_once_with("hit_001")
    assert result is not None
    assert "Queued hit_001" in result.text


@pytest.mark.asyncio
async def test_help_is_local_and_does_not_call_runtime() -> None:
    runtime = SimpleNamespace(handle_control_command=AsyncMock())
    output = StringIO()
    router = TerminalCommandRouter(runtime, console=Console(file=output, width=120))

    result = await router.handle("help")

    runtime.handle_control_command.assert_not_awaited()
    assert result is not None
    assert result.text.startswith("ControlMesh")
    assert "chat <message>" in output.getvalue()


@pytest.mark.asyncio
async def test_slash_help_is_local_and_does_not_call_runtime() -> None:
    runtime = SimpleNamespace(handle_control_command=AsyncMock())
    router = TerminalCommandRouter(runtime)

    result = await router.handle("/help")

    runtime.handle_control_command.assert_not_awaited()
    assert result is not None
    assert "native" in result.text


@pytest.mark.asyncio
async def test_status_routes_to_controlmesh_status_command() -> None:
    runtime = SimpleNamespace(
        handle_control_command=AsyncMock(return_value=OrchestratorResult(text="status ok"))
    )
    router = TerminalCommandRouter(runtime)

    result = await router.handle("status")

    runtime.handle_control_command.assert_awaited_once_with("/status")
    assert result is not None
    assert result.text == "status ok"


@pytest.mark.asyncio
async def test_slash_status_routes_to_controlmesh_status_command() -> None:
    runtime = SimpleNamespace(
        handle_control_command=AsyncMock(return_value=OrchestratorResult(text="status ok"))
    )
    router = TerminalCommandRouter(runtime)

    await router.handle("/status")

    runtime.handle_control_command.assert_awaited_once_with("/status")


@pytest.mark.asyncio
async def test_non_slash_runtime_command_is_canonicalized() -> None:
    runtime = SimpleNamespace(
        handle_control_command=AsyncMock(return_value=OrchestratorResult(text="tasks"))
    )
    router = TerminalCommandRouter(runtime)

    await router.handle("tasks list")

    runtime.handle_control_command.assert_awaited_once_with("/tasks list")


@pytest.mark.asyncio
async def test_cm_returns_compatibility_guidance() -> None:
    runtime = SimpleNamespace(handle_control_command=AsyncMock())
    router = TerminalCommandRouter(runtime)

    result = await router.handle("/cm")

    runtime.handle_control_command.assert_not_awaited()
    assert result is not None
    assert "native" in result.text


@pytest.mark.asyncio
async def test_model_overview_is_terminal_native() -> None:
    runtime = SimpleNamespace(
        model_overview=Mock(return_value=OrchestratorResult(text="Model\nCurrent: codex / gpt-5.5")),
        handle_control_command=AsyncMock(),
    )
    router = TerminalCommandRouter(runtime)

    result = await router.handle("model")

    runtime.model_overview.assert_called_once_with()
    runtime.handle_control_command.assert_not_awaited()
    assert result is not None
    assert "Current:" in result.text


@pytest.mark.asyncio
async def test_model_switch_is_terminal_native() -> None:
    runtime = SimpleNamespace(
        switch_model=AsyncMock(return_value=OrchestratorResult(text="switched")),
        handle_control_command=AsyncMock(),
    )
    router = TerminalCommandRouter(runtime)

    result = await router.handle("model codex gpt-5.5")

    runtime.switch_model.assert_awaited_once_with("codex", "gpt-5.5")
    runtime.handle_control_command.assert_not_awaited()
    assert result is not None
    assert result.text == "switched"
