"""Tests for FeishuTransport delivery handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from controlmesh.bus.envelope import Envelope, Origin
from controlmesh.messenger.feishu.transport import FeishuTransport


def _make_transport() -> tuple[FeishuTransport, MagicMock]:
    bot = MagicMock()
    bot.send_text = AsyncMock()
    bot.send_rich = AsyncMock()
    bot.broadcast_text = AsyncMock()
    bot.broadcast_rich = AsyncMock()
    return FeishuTransport(bot), bot


def _env(**kwargs: object) -> Envelope:
    defaults: dict[str, object] = {"origin": Origin.CRON, "chat_id": 42}
    defaults.update(kwargs)
    return Envelope(**defaults)  # type: ignore[arg-type]


class TestFeishuTransport:
    async def test_transport_name(self) -> None:
        transport, _ = _make_transport()
        assert transport.transport_name == "fs"

    async def test_heartbeat_uses_rich_send(self) -> None:
        transport, bot = _make_transport()

        await transport.deliver(
            _env(
                origin=Origin.HEARTBEAT,
                chat_id=99,
                result_text="heartbeat",
            )
        )

        bot.send_rich.assert_awaited_once_with(99, "heartbeat")

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

        bot.send_rich.assert_awaited_once()
        text = bot.send_rich.call_args[0][1]
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

        bot.broadcast_rich.assert_awaited_once()
        text = bot.broadcast_rich.call_args[0][0]
        assert "**TASK: Sync**" in text
        assert "cron ok" in text

    async def test_interagent_prefers_delivery_text_over_internal_payload(self) -> None:
        transport, bot = _make_transport()

        await transport.deliver(
            _env(
                origin=Origin.INTERAGENT,
                result_text="internal interagent payload",
                delivery_text="frontstage interagent reply",
            )
        )

        bot.send_rich.assert_awaited_once_with(42, "frontstage interagent reply")

    async def test_task_result_prefers_delivery_text_over_internal_payload(self) -> None:
        transport, bot = _make_transport()

        await transport.deliver(
            _env(
                origin=Origin.TASK_RESULT,
                status="done",
                result_text="internal payload that should not hit frontstage",
                delivery_text="checked frontstage summary",
                elapsed_seconds=30.0,
                provider="claude",
                model="opus",
                metadata={"name": "research", "task_id": "t1"},
            )
        )

        assert bot.send_rich.await_count == 2
        delivered = bot.send_rich.call_args_list[1][0][1]
        assert "checked frontstage summary" in delivered
        assert "internal payload" not in delivered

    async def test_task_question_prefers_delivery_text_over_internal_payload(self) -> None:
        transport, bot = _make_transport()

        await transport.deliver(
            _env(
                origin=Origin.TASK_QUESTION,
                prompt="What encoding?",
                result_text="internal prompt analysis",
                delivery_text="Ask them to use UTF-8",
                metadata={"task_id": "q1"},
            )
        )

        assert bot.send_rich.await_count == 2
        question = bot.send_rich.call_args_list[0][0][1]
        assert "What encoding?" in question
        delivered = bot.send_rich.call_args_list[1][0][1]
        assert "Ask them to use UTF-8" in delivered
        assert "internal prompt analysis" not in delivered
