"""MessageBus transport adapter for the direct official QQ Bot route."""

from __future__ import annotations

from typing import TYPE_CHECKING

from controlmesh.bus.envelope import Envelope
from controlmesh.messenger.address import require_string_chat_ref
from controlmesh.text.response_format import compact_transport_text

if TYPE_CHECKING:
    from controlmesh.messenger.qqbot.bot import QQBotSender


class QQBotTransport:
    """Minimal text-delivery transport adapter for QQ Bot."""

    def __init__(self, sender: QQBotSender) -> None:
        self._sender = sender

    @property
    def transport_name(self) -> str:
        return "qqbot"

    async def deliver(self, envelope: Envelope) -> None:
        text = _visible_text(envelope)
        if not text:
            return
        target = require_string_chat_ref(envelope.chat_id)
        await self._sender.send_text(target, text)

    async def deliver_broadcast(self, envelope: Envelope) -> None:
        text = _visible_text(envelope)
        if not text:
            return
        await self._sender.broadcast_text(text)


def _visible_text(envelope: Envelope) -> str:
    """Return the user-visible payload for simple QQ bus delivery."""
    return compact_transport_text(
        envelope.delivery_text or envelope.result_text or envelope.prompt,
    )
