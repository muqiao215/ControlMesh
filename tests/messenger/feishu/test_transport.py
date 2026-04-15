"""Tests for FeishuTransport delivery handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from controlmesh.bus.envelope import Envelope, Origin
from controlmesh.messenger.feishu.transport import FeishuTransport


def _make_transport() -> tuple[FeishuTransport, MagicMock]:
    bot = MagicMock()
    bot.send_text = AsyncMock()
    bot.broadcast_text = AsyncMock()
    return FeishuTransport(bot), bot


def _env(**kwargs: object) -> Envelope:
    defaults: dict[str, object] = {"origin": Origin.CRON, "chat_id": 42}
    defaults.update(kwargs)
    return Envelope(**defaults)  # type: ignore[arg-type]


class TestFeishuTransport:
    async def test_transport_name(self) -> None:
        transport, _ = _make_transport()
        assert transport.transport_name == "fs"

    async def test_heartbeat_uses_plain_text_send(self) -> None:
        transport, bot = _make_transport()

        await transport.deliver(
            _env(
                origin=Origin.HEARTBEAT,
                chat_id=99,
                result_text="heartbeat",
            )
        )

        bot.send_text.assert_awaited_once_with(99, "heartbeat")

    async def test_background_result_formats_plain_text(self) -> None:
        transport, bot = _make_transport()

        await transport.deliver(
            _env(
                origin=Origin.BACKGROUND,
                session_name="redowl",
                result_text="done",
                status="success",
                elapsed_seconds=12.0,
            )
        )

        bot.send_text.assert_awaited_once()
        text = bot.send_text.call_args[0][1]
        assert "[redowl] Complete" in text
        assert "done" in text

    async def test_cron_broadcast_uses_broadcast_text(self) -> None:
        transport, bot = _make_transport()

        await transport.deliver_broadcast(
            _env(
                origin=Origin.CRON,
                result_text="cron ok",
                status="success",
                metadata={"title": "Sync"},
            )
        )

        bot.broadcast_text.assert_awaited_once()
        text = bot.broadcast_text.call_args[0][0]
        assert "**TASK: Sync**" in text
        assert "cron ok" in text
