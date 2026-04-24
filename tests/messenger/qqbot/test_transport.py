"""Tests for the minimal QQ Bot transport adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from controlmesh.bus.envelope import DeliveryMode, Envelope, Origin
from controlmesh.messenger.qqbot.bot import QQBotNotificationService
from controlmesh.messenger.qqbot.transport import QQBotTransport


def _env(**kwargs: object) -> Envelope:
    defaults: dict[str, object] = {
        "origin": Origin.CRON,
        "chat_id": "qqbot:c2c:OPENID",
        "transport": "qqbot",
        "delivery": DeliveryMode.UNICAST,
    }
    defaults.update(kwargs)
    return Envelope(**defaults)  # type: ignore[arg-type]


async def test_transport_delivers_to_string_target() -> None:
    sender = AsyncMock()
    transport = QQBotTransport(sender)

    env = _env(result_text="hello")
    await transport.deliver(env)

    sender.send_text.assert_awaited_once_with("qqbot:c2c:OPENID", "hello")


async def test_transport_rejects_non_string_target() -> None:
    sender = AsyncMock()
    transport = QQBotTransport(sender)

    env = Envelope(origin=Origin.CRON, chat_id=123, transport="qqbot", result_text="hello")
    with pytest.raises(TypeError, match="string chat_id"):
        await transport.deliver(env)


async def test_transport_broadcast_uses_sender_broadcast() -> None:
    sender = AsyncMock()
    transport = QQBotTransport(sender)

    env = _env(delivery=DeliveryMode.BROADCAST, result_text="hello all")
    await transport.deliver_broadcast(env)

    sender.broadcast_text.assert_awaited_once_with("hello all")


async def test_notification_service_accepts_string_target() -> None:
    sender = AsyncMock()
    service = QQBotNotificationService(sender)

    await service.notify("qqbot:group:GROUP_OPENID", "ping")

    sender.send_text.assert_awaited_once_with("qqbot:group:GROUP_OPENID", "ping")
