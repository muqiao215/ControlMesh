"""Feishu-specific startup sequence."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from controlmesh.orchestrator.core import Orchestrator

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.bot import FeishuBot

logger = logging.getLogger(__name__)


async def run_feishu_startup(bot: FeishuBot) -> None:
    """Initialize orchestrator wiring and run startup hooks."""
    if bot._orchestrator is None:
        bot._orchestrator = await Orchestrator.create(bot._config, agent_name=bot._agent_name)
        bot._orchestrator.wire_observers_to_bus(bot._bus)

    await bot.start_inbound_listener()
    await bot.start_long_connection()

    logger.info("Feishu bot online: app_id=%s", bot._config.feishu.app_id)

    for hook in bot._startup_hooks:
        await hook()
