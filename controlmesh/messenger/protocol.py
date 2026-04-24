"""Transport-agnostic bot protocol for the supervisor/stack layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from controlmesh.messenger.address import ChatRef, TopicRef

if TYPE_CHECKING:
    from controlmesh.config import AgentConfig
    from controlmesh.messenger.notifications import NotificationService
    from controlmesh.multiagent.bus import AsyncInterAgentResult
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.tasks.models import TaskResult
    from controlmesh.workspace.paths import ControlMeshPaths


@runtime_checkable
class BotProtocol(Protocol):
    """Interface that both TelegramBot and MatrixBot implement.

    The supervisor, AgentStack, and InterAgentBus depend ONLY on this protocol,
    never on transport-specific classes.
    """

    @property
    def orchestrator(self) -> Orchestrator | None: ...

    @property
    def config(self) -> AgentConfig: ...

    @property
    def notification_service(self) -> NotificationService: ...

    async def run(self) -> int:
        """Start the bot event loop. Blocks until shutdown. Returns exit code."""
        ...

    async def shutdown(self) -> None:
        """Gracefully shut down the bot."""
        ...

    def register_startup_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Register a callback to run after orchestrator creation."""
        ...

    def set_abort_all_callback(self, callback: Callable[[], Awaitable[int]]) -> None:
        """Set multi-agent abort callback (injected by supervisor)."""
        ...

    async def on_async_interagent_result(self, result: AsyncInterAgentResult) -> None:
        """Handle async inter-agent result delivery."""
        ...

    async def on_task_result(self, result: TaskResult) -> None:
        """Handle background task completion."""
        ...

    async def on_task_question(
        self,
        task_id: str,
        question: str,
        prompt_preview: str,
        chat_id: ChatRef,
        thread_id: TopicRef = None,
    ) -> None:
        """Handle background task question delivery."""
        ...

    def file_roots(self, paths: ControlMeshPaths) -> list[Path] | None:
        """Allowed root directories for file sends."""
        ...
