from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


class TestTelegramStartupWatchdogCompat:
    async def test_run_startup_uses_current_watchdog_fields(self) -> None:
        from controlmesh.messenger.telegram import startup

        bot = MagicMock()
        bot._orchestrator = MagicMock()
        bot.bot_instance.get_me = AsyncMock(return_value=MagicMock(id=123, username="cm_bot"))
        bot._sync_commands = AsyncMock()
        bot._watch_restart_marker = AsyncMock()
        bot.audit_groups = AsyncMock()
        bot._run_group_audit_loop = AsyncMock()
        bot._watch_poll_health = AsyncMock()

        created = []

        def _fake_create_task(coro, *, name=None):
            coro.close()
            task = MagicMock()
            task.coro = coro
            task.name = name
            created.append(task)
            return task

        with patch("controlmesh.messenger.telegram.startup.asyncio.create_task", side_effect=_fake_create_task):
            await startup.run_startup(bot)

        assert bot._bot_id == 123
        assert bot._bot_username == "cm_bot"
        bot._sync_commands.assert_awaited_once()
        bot.audit_groups.assert_awaited_once()
        assert len(created) == 2
        assert bot._restart_watcher is created[0]
        assert bot._group_audit_task is created[1]
