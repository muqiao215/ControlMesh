"""Tests for Feishu bot routing on async/task return paths."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp

from ductor_bot.config import AgentConfig
from ductor_bot.messenger.feishu.bot import FeishuBot, FeishuIncomingText


@dataclass
class _FakeTaskResult:
    task_id: str = "t1"
    chat_id: int = 123
    parent_agent: str = "main"
    name: str = "research"
    prompt_preview: str = "find info"
    result_text: str = "found it"
    status: str = "done"
    elapsed_seconds: float = 5.0
    provider: str = "claude"
    model: str = "sonnet"
    session_id: str = "tsid1"
    error: str = ""
    task_folder: str = "/tmp/tasks/t1"
    original_prompt: str = "find info about X"
    thread_id: int | None = None


def _make_bot(tmp_path: Path, **feishu_overrides: object) -> FeishuBot:
    feishu_config: dict[str, object] = {
        "mode": "bot_only",
        "brand": "feishu",
        "app_id": "cli_123",
        "app_secret": "sec_456",
    }
    feishu_config.update(feishu_overrides)
    config = AgentConfig(
        transport="feishu",
        transports=["feishu"],
        ductor_home=str(tmp_path),
        feishu=feishu_config,
    )
    bot = FeishuBot(config)
    bot.send_text = AsyncMock()  # type: ignore[method-assign]
    bot.broadcast_text = AsyncMock()  # type: ignore[method-assign]
    return bot


class TestFeishuBotRouting:
    async def test_handle_incoming_event_normalizes_text_payload(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_1",
                "event_type": "im.message.receive_v1",
                "create_time": "1710000000000",
                "tenant_key": "tenant_1",
                "app_id": "cli_123",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_sender"}},
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_chat_1",
                    "thread_id": "omt_1",
                    "message_type": "text",
                    "content": '{"text":"hello from feishu"}',
                },
            },
        }

        await bot.handle_incoming_event(payload)

        bot.handle_incoming_text.assert_awaited_once_with(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="hello from feishu",
                thread_id="omt_1",
            )
        )

    async def test_handle_incoming_text_routes_to_orchestrator_and_replies(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._orchestrator = SimpleNamespace(
            handle_message=AsyncMock(return_value=SimpleNamespace(text="pong"))
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._orchestrator.handle_message.assert_awaited_once()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "pong",
            reply_to_message_id="om_1",
        )

    async def test_on_task_result_routes_to_fs_and_delivers(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        await bot.on_task_result(_FakeTaskResult())

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()

    async def test_on_task_question_routes_to_fs_and_delivers(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        await bot.on_task_question("t1", "what color?", "what co...", 123)

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()

    async def test_on_async_interagent_result_routes_to_fs_and_delivers(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        result = SimpleNamespace(
            task_id="ia1",
            sender="agent-a",
            recipient="agent-b",
            message_preview="please do X",
            result_text="done",
            success=True,
            error=None,
            elapsed_seconds=2.0,
            session_name="ia-agent-a",
            provider_switch_notice="",
            original_message="full message",
            chat_id=123,
            topic_id=None,
        )

        await bot.on_async_interagent_result(result)

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()


class TestFeishuInboundListener:
    async def test_start_inbound_listener_accepts_event_payload(self, tmp_path: Path) -> None:
        bot = _make_bot(
            tmp_path,
            callback_host="127.0.0.1",
            callback_port=0,
            callback_path="/feishu/events",
        )
        bot._orchestrator = SimpleNamespace(
            handle_message=AsyncMock(return_value=SimpleNamespace(text="pong")),
            shutdown=AsyncMock(),
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        await bot.start_inbound_listener()
        assert bot._inbound_server is not None

        url = (
            f"http://{bot.config.feishu.listener_host}:"
            f"{bot._inbound_server.bound_port}"
            f"{bot.config.feishu.listener_path}"
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_1",
                "event_type": "im.message.receive_v1",
                "create_time": "1710000000000",
                "tenant_key": "tenant_1",
                "app_id": "cli_123",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_sender"}},
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_chat_1",
                    "thread_id": "omt_1",
                    "message_type": "text",
                    "content": '{"text":"hello from feishu"}',
                },
            },
        }

        async with (
            aiohttp.ClientSession() as session,
            session.post(url, json=payload) as response,
        ):
            assert response.status == 202
            assert await response.json() == {"accepted": True}

        await asyncio.sleep(0)
        bot._orchestrator.handle_message.assert_awaited_once()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "pong",
            reply_to_message_id="om_1",
        )
        await bot.shutdown()

    async def test_start_inbound_listener_handles_url_verification(self, tmp_path: Path) -> None:
        bot = _make_bot(
            tmp_path,
            callback_host="127.0.0.1",
            callback_port=0,
            callback_path="/feishu/events",
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        await bot.start_inbound_listener()
        assert bot._inbound_server is not None

        url = (
            f"http://{bot.config.feishu.listener_host}:"
            f"{bot._inbound_server.bound_port}"
            f"{bot.config.feishu.listener_path}"
        )

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                url,
                json={"type": "url_verification", "challenge": "verify-me"},
            ) as response,
        ):
            assert response.status == 200
            assert await response.json() == {"challenge": "verify-me"}

        bot._send_text_to_chat_ref.assert_not_awaited()
        await bot.shutdown()

    async def test_shutdown_stops_inbound_listener(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot._inbound_server = SimpleNamespace(stop=AsyncMock())

        await bot.shutdown()

        bot._inbound_server.stop.assert_awaited_once()
