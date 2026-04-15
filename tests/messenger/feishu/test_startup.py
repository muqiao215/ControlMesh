"""Tests for Feishu startup wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from controlmesh.messenger.feishu.startup import run_feishu_startup


class TestFeishuStartup:
    async def test_primary_startup_creates_orchestrator_and_runs_hooks(self) -> None:
        bot = MagicMock()
        bot._orchestrator = None
        bot._config = MagicMock()
        bot._agent_name = "main"
        bot._bus = MagicMock()
        bot.start_inbound_listener = AsyncMock()
        bot.start_long_connection = AsyncMock()
        bot._startup_hooks = [AsyncMock()]

        orch = MagicMock()
        orch.wire_observers_to_bus = MagicMock()

        with patch(
            "controlmesh.messenger.feishu.startup.Orchestrator.create",
            AsyncMock(return_value=orch),
        ):
            await run_feishu_startup(bot)

        assert bot._orchestrator is orch
        orch.wire_observers_to_bus.assert_called_once_with(bot._bus)
        bot.start_inbound_listener.assert_awaited_once()
        bot.start_long_connection.assert_awaited_once()
        bot._startup_hooks[0].assert_awaited_once()

    async def test_secondary_startup_skips_orchestrator_creation(self) -> None:
        bot = MagicMock()
        bot._orchestrator = MagicMock()
        bot._config = MagicMock()
        bot._agent_name = "secondary"
        bot._bus = MagicMock()
        bot.start_inbound_listener = AsyncMock()
        bot.start_long_connection = AsyncMock()
        bot._startup_hooks = [AsyncMock()]

        with patch(
            "controlmesh.messenger.feishu.startup.Orchestrator.create",
            AsyncMock(),
        ) as create:
            await run_feishu_startup(bot)

        create.assert_not_awaited()
        bot.start_inbound_listener.assert_awaited_once()
        bot.start_long_connection.assert_awaited_once()
        bot._startup_hooks[0].assert_awaited_once()
