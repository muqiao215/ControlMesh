from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

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
