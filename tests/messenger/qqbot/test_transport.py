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


async def test_transport_prefers_delivery_text_for_injected_task_payload() -> None:
    sender = AsyncMock()
    transport = QQBotTransport(sender)

    env = _env(
        origin=Origin.TASK_QUESTION,
        prompt="internal question",
        result_text="internal response",
        delivery_text="Ask the user for UTF-8.",
    )
    await transport.deliver(env)

    sender.send_text.assert_awaited_once_with("qqbot:c2c:OPENID", "Ask the user for UTF-8.")


async def test_transport_falls_back_to_prompt_for_task_question_without_injector() -> None:
    sender = AsyncMock()
    transport = QQBotTransport(sender)

    env = _env(origin=Origin.TASK_QUESTION, prompt="What encoding?")
    await transport.deliver(env)

    sender.send_text.assert_awaited_once_with("qqbot:c2c:OPENID", "What encoding?")


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


async def test_transport_broadcast_prefers_delivery_text() -> None:
    sender = AsyncMock()
    transport = QQBotTransport(sender)

    env = _env(delivery=DeliveryMode.BROADCAST, result_text="internal", delivery_text="visible")
    await transport.deliver_broadcast(env)

    sender.broadcast_text.assert_awaited_once_with("visible")


async def test_notification_service_accepts_string_target() -> None:
    sender = AsyncMock()
    service = QQBotNotificationService(sender)

    await service.notify("qqbot:group:GROUP_OPENID", "ping")

    sender.send_text.assert_awaited_once_with("qqbot:group:GROUP_OPENID", "ping")
