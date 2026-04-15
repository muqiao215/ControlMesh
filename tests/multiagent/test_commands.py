"""Tests for multiagent/commands.py: Telegram command handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from controlmesh.multiagent.commands import (
    cmd_agent_restart,
    cmd_agent_start,
    cmd_agent_stop,
    cmd_agents,
)
from controlmesh.multiagent.health import AgentHealth


def _make_orch(*, with_supervisor: bool = True) -> MagicMock:
    """Create a mock Orchestrator with optional supervisor."""
    orch = MagicMock()
    if not with_supervisor:
        orch.supervisor = None
    else:
        supervisor = MagicMock()
        supervisor.health = {}
        supervisor.stacks = {}
        supervisor.stop_agent = AsyncMock()
        supervisor.start_agent_by_name = AsyncMock(return_value="Agent 'sub1' started.")
        supervisor.restart_agent = AsyncMock(return_value="Agent 'sub1' restarted.")
        orch.supervisor = supervisor
    return orch


class TestCmdAgents:
    """Test /agents command."""

    async def test_no_supervisor(self) -> None:
        orch = _make_orch(with_supervisor=False)
        result = await cmd_agents(orch, 1, "/agents")
        assert "not active" in result.text

    async def test_no_agents(self) -> None:
        orch = _make_orch()
        result = await cmd_agents(orch, 1, "/agents")
        assert "No agents" in result.text

    async def test_lists_running_agent(self) -> None:
        orch = _make_orch()
        h = AgentHealth(name="main")
        h.mark_running()
        orch.supervisor.health = {"main": h}
        stack = MagicMock()
        stack.is_main = True
        orch.supervisor.stacks = {"main": stack}

        result = await cmd_agents(orch, 1, "/agents")
        assert "main" in result.text
        assert "running" in result.text

    async def test_lists_crashed_agent_with_error(self) -> None:
        orch = _make_orch()
        h = AgentHealth(name="sub1")
        h.mark_crashed("Connection refused")
        orch.supervisor.health = {"sub1": h}
        stack = MagicMock()
        stack.is_main = False
        orch.supervisor.stacks = {"sub1": stack}

        result = await cmd_agents(orch, 1, "/agents")
        assert "crashed" in result.text
        assert "Connection refused" in result.text

    async def test_shows_restart_count(self) -> None:
        orch = _make_orch()
        h = AgentHealth(name="sub1")
        h.mark_crashed("err1")
        h.mark_crashed("err2")
        orch.supervisor.health = {"sub1": h}
        stack = MagicMock()
        stack.is_main = False
        orch.supervisor.stacks = {"sub1": stack}

        result = await cmd_agents(orch, 1, "/agents")
        assert "restarts: 2" in result.text

    async def test_shows_uptime_for_running(self) -> None:
        orch = _make_orch()
        h = AgentHealth(name="main")
        h.mark_running()
        orch.supervisor.health = {"main": h}
        stack = MagicMock()
        stack.is_main = True
        orch.supervisor.stacks = {"main": stack}

        result = await cmd_agents(orch, 1, "/agents")
        # Uptime is very short, so it shows seconds
        assert "s)" in result.text or "m)" in result.text

    async def test_multiple_agents_sorted(self) -> None:
        orch = _make_orch()
        h_main = AgentHealth(name="main")
        h_main.mark_running()
        h_sub = AgentHealth(name="alpha")
        h_sub.mark_running()
        orch.supervisor.health = {"main": h_main, "alpha": h_sub}
        orch.supervisor.stacks = {
            "main": MagicMock(is_main=True),
            "alpha": MagicMock(is_main=False),
        }

        result = await cmd_agents(orch, 1, "/agents")
        # "alpha" should come before "main" (sorted)
        alpha_pos = result.text.index("alpha")
        main_pos = result.text.index("main")
        assert alpha_pos < main_pos


class TestCmdAgentStop:
    """Test /agent_stop command."""

    async def test_no_supervisor(self) -> None:
        orch = _make_orch(with_supervisor=False)
        result = await cmd_agent_stop(orch, 1, "/agent_stop sub1")
        assert "not active" in result.text

    async def test_missing_name(self) -> None:
        orch = _make_orch()
        result = await cmd_agent_stop(orch, 1, "/agent_stop")
        assert "Usage" in result.text

    async def test_cannot_stop_main(self) -> None:
        orch = _make_orch()
        result = await cmd_agent_stop(orch, 1, "/agent_stop main")
        assert "Cannot stop the main agent" in result.text

    async def test_agent_not_running(self) -> None:
        orch = _make_orch()
        result = await cmd_agent_stop(orch, 1, "/agent_stop sub1")
        assert "not running" in result.text

    async def test_stop_success(self) -> None:
        orch = _make_orch()
        orch.supervisor.stacks = {"sub1": MagicMock()}
        result = await cmd_agent_stop(orch, 1, "/agent_stop sub1")
        assert "stopped" in result.text
        orch.supervisor.stop_agent.assert_called_once_with("sub1")


class TestCmdAgentStart:
    """Test /agent_start command."""

    async def test_no_supervisor(self) -> None:
        orch = _make_orch(with_supervisor=False)
        result = await cmd_agent_start(orch, 1, "/agent_start sub1")
        assert "not active" in result.text

    async def test_missing_name(self) -> None:
        orch = _make_orch()
        result = await cmd_agent_start(orch, 1, "/agent_start")
        assert "Usage" in result.text

    async def test_start_success(self) -> None:
        orch = _make_orch()
        result = await cmd_agent_start(orch, 1, "/agent_start sub1")
        assert "started" in result.text
        orch.supervisor.start_agent_by_name.assert_called_once_with("sub1")


class TestCmdAgentRestart:
    """Test /agent_restart command."""

    async def test_no_supervisor(self) -> None:
        orch = _make_orch(with_supervisor=False)
        result = await cmd_agent_restart(orch, 1, "/agent_restart sub1")
        assert "not active" in result.text

    async def test_missing_name(self) -> None:
        orch = _make_orch()
        result = await cmd_agent_restart(orch, 1, "/agent_restart")
        assert "Usage" in result.text

    async def test_cannot_restart_main(self) -> None:
        orch = _make_orch()
        orch.supervisor.restart_agent = AsyncMock(
            return_value="Cannot restart main agent via this command. Use /restart instead."
        )
        result = await cmd_agent_restart(orch, 1, "/agent_restart main")
        assert "Cannot restart main" in result.text

    async def test_restart_success(self) -> None:
        orch = _make_orch()
        result = await cmd_agent_restart(orch, 1, "/agent_restart sub1")
        assert "restarted" in result.text
        orch.supervisor.restart_agent.assert_called_once_with("sub1")
