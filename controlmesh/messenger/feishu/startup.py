"""Feishu-specific startup sequence."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from controlmesh.i18n import t
from controlmesh.infra.updater import consume_upgrade_sentinel
from controlmesh.infra.version import get_current_version
from controlmesh.orchestrator.core import Orchestrator

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.bot import FeishuBot

logger = logging.getLogger(__name__)


async def _handle_upgrade_recovery(bot: FeishuBot) -> None:
    upgrade = await asyncio.to_thread(
        consume_upgrade_sentinel,
        bot._orch.paths.controlmesh_home,
        transport="feishu",
    )
    if not upgrade:
        return
    chat_id = int(upgrade.get("chat_id", 0))
    if not chat_id:
        return
    old_version = upgrade.get("old_version", "?")
    new_version = upgrade.get("new_version", get_current_version())
    await bot.notification_service.notify(
        chat_id,
        t("startup.upgrade_complete", old=old_version, new=new_version),
    )


async def run_feishu_startup(bot: FeishuBot) -> None:
    """Initialize orchestrator wiring and run startup hooks."""
    if bot._orchestrator is None:
        bot._orchestrator = await Orchestrator.create(bot._config, agent_name=bot._agent_name)
        bot._orchestrator.wire_observers_to_bus(bot._bus)

    await bot.start_inbound_listener()
    await bot.start_long_connection()

    await _handle_upgrade_recovery(bot)

    logger.info("Feishu bot online: app_id=%s", bot._config.feishu.app_id)

    for hook in bot._startup_hooks:
        await hook()
