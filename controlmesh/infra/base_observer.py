"""Base class for periodic background observers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseObserver(ABC):
    """Abstract base for asyncio background observers.

    Provides start/stop lifecycle with task management and crash logging.
    Subclasses implement ``_run()`` which is the main loop body.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @abstractmethod
    async def _run(self) -> None:
        """Main loop body. Called once by start(). Must loop internally."""
        ...

    async def start(self) -> None:
        """Start the background loop."""
        self._running = True
        self._task = asyncio.create_task(self._run())
        self._task.add_done_callback(_log_task_crash)

    async def stop(self) -> None:
        """Stop the background loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @property
    def running(self) -> bool:
        return self._running


def _log_task_crash(task: asyncio.Task[None]) -> None:
    """Log if a background observer task crashes unexpectedly."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Observer task crashed: %s", exc, exc_info=exc)
