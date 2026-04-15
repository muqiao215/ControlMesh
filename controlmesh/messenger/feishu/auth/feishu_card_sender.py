"""Thin sender/update adapter for Feishu auth cards."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from controlmesh.messenger.feishu.auth.card_auth_context import FeishuCardAuthContext


@dataclass(frozen=True, slots=True)
class FeishuCardHandle:
    chat_id: str
    message_id: str


class FeishuCardSender(Protocol):
    async def send_card(
        self,
        context: FeishuCardAuthContext,
        card: dict[str, Any],
    ) -> FeishuCardHandle:
        """Send a new auth card and return its handle."""

    async def update_card(
        self,
        handle: FeishuCardHandle,
        card: dict[str, Any],
    ) -> None:
        """Update an existing auth card."""


class BotFeishuCardSender:
    """Wrap bot-level send/update callbacks behind a stable adapter seam."""

    def __init__(
        self,
        *,
        send_card_func: Callable[[FeishuCardAuthContext, dict[str, Any]], Awaitable[str | None]],
        update_card_func: Callable[[FeishuCardHandle, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._send_card_func = send_card_func
        self._update_card_func = update_card_func

    async def send_card(
        self,
        context: FeishuCardAuthContext,
        card: dict[str, Any],
    ) -> FeishuCardHandle:
        message_id = await self._send_card_func(context, card)
        if not message_id:
            msg = "Feishu auth card send returned no message id"
            raise RuntimeError(msg)
        return FeishuCardHandle(chat_id=context.chat_id, message_id=message_id)

    async def update_card(
        self,
        handle: FeishuCardHandle,
        card: dict[str, Any],
    ) -> None:
        await self._update_card_func(handle, card)
