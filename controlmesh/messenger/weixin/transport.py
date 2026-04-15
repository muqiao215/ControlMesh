"""Weixin delivery adapter for the MessageBus."""

from __future__ import annotations

from typing import TYPE_CHECKING

from controlmesh.bus.envelope import Envelope

if TYPE_CHECKING:
    from controlmesh.messenger.weixin.bot import WeixinBot


class WeixinTransport:
    """Minimal TransportAdapter implementation for Weixin plain-text delivery."""

    def __init__(self, bot: WeixinBot) -> None:
        self._bot = bot

    @property
    def transport_name(self) -> str:
        return "wx"

    async def deliver(self, envelope: Envelope) -> None:
        text = envelope.result_text or envelope.prompt
        if text:
            await self._bot.send_text(envelope.chat_id, text)

    async def deliver_broadcast(self, envelope: Envelope) -> None:
        text = envelope.result_text or envelope.prompt
        if text:
            await self._bot.broadcast_text(text)
