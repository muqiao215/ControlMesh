"""AgentStack: encapsulates a complete bot stack for one agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from controlmesh.config import AgentConfig
from controlmesh.messenger.notifications import NotificationService
from controlmesh.workspace.init import init_workspace
from controlmesh.workspace.paths import ControlMeshPaths, resolve_paths

if TYPE_CHECKING:
    from controlmesh.messenger.protocol import BotProtocol
    from controlmesh.multiagent.bus import AsyncInterAgentResult
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.tasks.models import TaskResult

logger = logging.getLogger(__name__)


class AgentStackMode(StrEnum):
    """Execution mode for an agent stack."""

    TRANSPORT = "transport"
    HEADLESS = "headless"


class NullNotificationService:
    """Notification sink for headless agents."""

    async def notify(self, chat_id: object, text: str) -> None:
        return None

    async def notify_all(self, text: str) -> None:
        return None


class HeadlessBot:
    """BotProtocol-compatible adapter for a headless orchestrator."""

    def __init__(self, config: AgentConfig, orchestrator: Orchestrator) -> None:
        self._config = config
        self._orchestrator = orchestrator
        self._notification_service: NotificationService = NullNotificationService()

    @property
    def orchestrator(self) -> Orchestrator | None:
        return self._orchestrator

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def notification_service(self) -> NotificationService:
        return self._notification_service

    async def run(self) -> int:
        return 0

    async def shutdown(self) -> None:
        await self._orchestrator.shutdown()

    def register_startup_hook(self, hook: object) -> None:
        return None

    def set_abort_all_callback(self, callback: object) -> None:
        return None

    async def on_async_interagent_result(self, result: AsyncInterAgentResult) -> None:
        await self._orchestrator.handle_async_interagent_result(result)

    async def on_task_result(self, result: TaskResult) -> None:
        return None

    async def on_task_question(
        self,
        task_id: str,
        question: str,
        prompt_preview: str,
        chat_id: object,
        thread_id: object = None,
    ) -> None:
        return None

    def file_roots(self, paths: ControlMeshPaths) -> list[Path] | None:
        return [paths.workspace]


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
    mode: AgentStackMode = AgentStackMode.TRANSPORT
    is_main: bool = False

    @classmethod
    async def create(
        cls,
        name: str,
        config: AgentConfig,
        *,
        is_main: bool = False,
        mode: AgentStackMode | str = AgentStackMode.TRANSPORT,
    ) -> AgentStack:
        """Factory: initialize workspace and create the transport-specific bot.

        The workspace is seeded (Zone 2 + 3) and the bot created,
        but the event loop is NOT started yet — call ``run()`` for that.
        """
        import asyncio

        paths = resolve_paths(controlmesh_home=config.controlmesh_home)
        await asyncio.to_thread(init_workspace, paths)

        stack_mode = AgentStackMode(mode)
        if stack_mode is AgentStackMode.HEADLESS:
            from controlmesh.orchestrator.core import Orchestrator

            orchestrator = await Orchestrator.create(config, agent_name=name)
            bot = HeadlessBot(config, orchestrator)
        else:
            from controlmesh.messenger.registry import create_bot

            bot = create_bot(config, agent_name=name)

        logger.info(
            "AgentStack created: name=%s home=%s main=%s transport=%s",
            name,
            paths.controlmesh_home,
            is_main,
            config.transport,
        )
        return cls(
            name=name,
            config=config,
            paths=paths,
            bot=bot,
            mode=stack_mode,
            is_main=is_main,
        )

    async def run(self) -> int:
        """Start the bot (blocks until stop/crash).

        Returns exit code (0 = normal, 42 = restart requested).
        """
        return await self.bot.run()

    @property
    def orchestrator(self) -> Orchestrator | None:
        """Return the stack orchestrator, if initialized."""
        return self.bot.orchestrator

    @property
    def notification_service(self) -> NotificationService:
        """Return the stack notification service."""
        return self.bot.notification_service

    async def shutdown(self) -> None:
        """Gracefully shut down the bot and all observers."""
        await self.bot.shutdown()
        logger.info("AgentStack '%s' shut down", self.name)
