"""Tests for Feishu startup wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from controlmesh.infra.updater import write_upgrade_sentinel
from controlmesh.messenger.feishu.startup import run_feishu_startup


class TestFeishuStartup:
    async def test_primary_startup_creates_orchestrator_and_runs_hooks(self, tmp_path: Path) -> None:
        bot = MagicMock()
        bot._orchestrator = None
        bot._orch = MagicMock()
        bot._orch.paths.controlmesh_home = tmp_path
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

    async def test_secondary_startup_skips_orchestrator_creation(self, tmp_path: Path) -> None:
        bot = MagicMock()
        bot._orchestrator = MagicMock()
        bot._orch = MagicMock()
        bot._orch.paths.controlmesh_home = tmp_path
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

    async def test_startup_consumes_upgrade_sentinel_and_notifies_chat(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(tmp_path, chat_id=42, old_version="0.15.0", new_version="0.16.0")

        bot = MagicMock()
        bot._orchestrator = MagicMock()
        bot._orch = MagicMock()
        bot._orch.paths.controlmesh_home = tmp_path
        bot._config = MagicMock()
        bot._config.feishu.app_id = "cli_123"
        bot._agent_name = "main"
        bot._bus = MagicMock()
        bot.start_inbound_listener = AsyncMock()
        bot.start_long_connection = AsyncMock()
        bot._startup_hooks = []
        bot.notification_service.notify = AsyncMock()

        with patch(
            "controlmesh.messenger.feishu.startup.Orchestrator.create",
            AsyncMock(),
        ) as create:
            await run_feishu_startup(bot)

        create.assert_not_awaited()
        bot.notification_service.notify.assert_awaited_once()
