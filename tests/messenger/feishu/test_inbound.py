"""Tests for Feishu inbound listener wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.inbound import FeishuInboundServer


def _make_config() -> AgentConfig:
    return AgentConfig(
        transport="feishu",
        transports=["feishu"],
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "app_id": "cli_123",
            "app_secret": "sec_456",
        },
    )


def _make_app(server: FeishuInboundServer) -> web.Application:
    app = web.Application()
    app.router.add_post(server.path, server.handle_request)
    return app


class TestFeishuInboundServer:
    async def test_challenge_request_returns_challenge_without_dispatch(self) -> None:
        handler = AsyncMock()
        server = FeishuInboundServer(_make_config().feishu, handler)
        client = TestClient(TestServer(_make_app(server)))
        await client.start_server()
        try:
            response = await client.post(server.path, json={"challenge": "abc123"})
            assert response.status == 200
            assert await response.json() == {"challenge": "abc123"}
            handler.assert_not_awaited()
        finally:
            await client.close()

    async def test_message_event_dispatches_payload_to_handler(self) -> None:
        handler = AsyncMock()
        server = FeishuInboundServer(_make_config().feishu, handler)
        client = TestClient(TestServer(_make_app(server)))
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
                "sender": {
                    "sender_id": {
                        "open_id": "ou_sender",
                    }
                },
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_chat_1",
                    "message_type": "text",
                    "content": '{"text":"hello from feishu"}',
                },
            },
        }
        await client.start_server()
        try:
            response = await client.post(server.path, json=payload)
            assert response.status == 202
            assert await response.json() == {"accepted": True}
            handler.assert_awaited_once_with(payload)
        finally:
            await client.close()
