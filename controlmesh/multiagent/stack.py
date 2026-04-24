"""AgentStack: encapsulates a complete bot stack for one agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from controlmesh.config import AgentConfig
from controlmesh.workspace.init import init_workspace
from controlmesh.workspace.paths import ControlMeshPaths, resolve_paths

if TYPE_CHECKING:
    from controlmesh.messenger.protocol import BotProtocol

logger = logging.getLogger(__name__)


@dataclass
class AgentStack:
    """Container for one agent's entire bot stack.

    Each agent gets its own Bot → Orchestrator → CLIService pipeline,
    its own workspace, sessions, cron jobs, and webhooks.
    """

    name: str
    config: AgentConfig
    paths: ControlMeshPaths
    bot: BotProtocol
    is_main: bool = False

    @classmethod
    async def create(
        cls,
        name: str,
        config: AgentConfig,
        *,
        is_main: bool = False,
    ) -> AgentStack:
        """Factory: initialize workspace and create the transport-specific bot.

        The workspace is seeded (Zone 2 + 3) and the bot created,
        but the event loop is NOT started yet — call ``run()`` for that.
        """
        import asyncio

        paths = resolve_paths(controlmesh_home=config.controlmesh_home)
        await asyncio.to_thread(init_workspace, paths)

        from controlmesh.messenger.registry import create_bot
        from controlmesh.qq_bridge.relay import attach_qq_bridge_relay

        bot = create_bot(config, agent_name=name)
        attach_qq_bridge_relay(bot)

        logger.info(
            "AgentStack created: name=%s home=%s main=%s transport=%s",
            name,
            paths.controlmesh_home,
            is_main,
            config.transport,
        )
        return cls(name=name, config=config, paths=paths, bot=bot, is_main=is_main)

    async def run(self) -> int:
        """Start the bot (blocks until stop/crash).

        Returns exit code (0 = normal, 42 = restart requested).
        """
        return await self.bot.run()

    async def shutdown(self) -> None:
        """Gracefully shut down the bot and all observers."""
        await self.bot.shutdown()
        logger.info("AgentStack '%s' shut down", self.name)
