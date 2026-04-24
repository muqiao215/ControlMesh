"""C2C-only official QQ typing/input-notify keepalive."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from controlmesh.messenger.qqbot.api import QQBotApiClient, QQBotApiError
from controlmesh.messenger.qqbot.token_manager import QQBotTokenManager
from controlmesh.messenger.qqbot.types import QQBotRuntimeAccount

logger = logging.getLogger(__name__)

TYPING_INTERVAL_SECONDS = 50.0
TYPING_INPUT_SECOND = 60


class QQBotTypingKeepAlive:
    """Best-effort C2C typing keepalive aligned with the official input-notify API."""

    def __init__(
        self,
        *,
        api_client: QQBotApiClient,
        token_manager: QQBotTokenManager,
        account: QQBotRuntimeAccount,
        openid: str,
        msg_id: str | None,
        interval_seconds: float | None = None,
        input_second: int = TYPING_INPUT_SECOND,
    ) -> None:
        self._api_client = api_client
        self._token_manager = token_manager
        self._account = account
        self._openid = openid
        self._msg_id = msg_id
        self._interval_seconds = (
            TYPING_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
        )
        self._input_second = input_second
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    async def send_initial(self) -> dict[str, str]:
        """Send the first typing notify immediately."""
        return await self._send_once()

    def start(self) -> None:
        """Start periodic typing renewal after an initial notify succeeds."""
        if self._stopped or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name=f"qqbot:typing:{self._openid}")

    async def stop(self) -> None:
        """Stop periodic typing renewal."""
        self._stopped = True
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stopped:
            await asyncio.sleep(self._interval_seconds)
            if self._stopped:
                return
            try:
                await self._send_once()
            except Exception as exc:  # pragma: no cover - best-effort runtime path
                logger.debug("QQ typing keepalive send failed", exc_info=exc)

    async def _send_once(self) -> dict[str, str]:
        token = await self._token_manager.get_token_value(
            self._account.app_id,
            self._account.client_secret,
        )
        try:
            return await self._api_client.send_c2c_input_notify(
                token,
                self._openid,
                msg_id=self._msg_id,
                input_second=self._input_second,
            )
        except QQBotApiError as exc:
            if exc.status not in {401, 403}:
                raise
            self._token_manager.clear_cache(self._account.app_id)
            token = await self._token_manager.get_token_value(
                self._account.app_id,
                self._account.client_secret,
            )
            return await self._api_client.send_c2c_input_notify(
                token,
                self._openid,
                msg_id=self._msg_id,
                input_second=self._input_second,
            )
