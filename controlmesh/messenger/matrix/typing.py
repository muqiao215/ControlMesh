"""Matrix typing indicator context manager with keep-alive."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from types import TracebackType

    from nio import AsyncClient


class MatrixTypingContext:
    """Context manager that shows typing indicator in a Matrix room.

    A background keep-alive task re-sends the typing notification every
    ``interval`` seconds.  This is necessary because Matrix clients
    (e.g. Element) clear the indicator when the bot sends a message,
    and the server expires it after the timeout.
    """

    def __init__(
        self,
        client: AsyncClient,
        room_id: str,
        *,
        interval: float = 5.0,
        timeout: int = 30000,
    ) -> None:
        self._client = client
        self._room_id = room_id
        self._interval = interval
        self._timeout = timeout
        self._task: asyncio.Task[None] | None = None

    async def _keep_alive(self) -> None:
        """Periodically re-send typing indicator."""
        while True:
            await asyncio.sleep(self._interval)
            with contextlib.suppress(Exception):
                await self._client.room_typing(
                    self._room_id, typing_state=True, timeout=self._timeout
                )

    async def __aenter__(self) -> Self:
        with contextlib.suppress(Exception):
            await self._client.room_typing(self._room_id, typing_state=True, timeout=self._timeout)
        self._task = asyncio.create_task(self._keep_alive())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        with contextlib.suppress(Exception):
            await self._client.room_typing(self._room_id, typing_state=False)
