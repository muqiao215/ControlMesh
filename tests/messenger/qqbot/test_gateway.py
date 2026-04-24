from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from aiohttp import WSMsgType
import pytest

from controlmesh.messenger.qqbot.api import QQBotAccessToken
from controlmesh.messenger.qqbot.gateway import QQBotGatewayClient
from controlmesh.messenger.qqbot.session_store import QQBotSessionState, QQBotSessionStore
from controlmesh.messenger.qqbot.types import QQBotRuntimeAccount


@dataclass
class _FakeWSMessage:
    type: WSMsgType
    data: str


class _FakeWebSocket:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self._queue: asyncio.Queue[_FakeWSMessage] = asyncio.Queue()
        for payload in payloads:
            self._queue.put_nowait(_FakeWSMessage(WSMsgType.TEXT, json.dumps(payload)))
        self.sent_json: list[dict[str, object]] = []
        self.closed = False

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent_json.append(payload)

    async def receive(self) -> _FakeWSMessage:
        return await self._queue.get()

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(_FakeWSMessage(WSMsgType.CLOSE, ""))


class _FakeSession:
    def __init__(self, websocket: _FakeWebSocket) -> None:
        self.websocket = websocket
        self.ws_connect_calls: list[dict[str, object]] = []

    async def ws_connect(self, url: str, *, headers: dict[str, str] | None = None) -> _FakeWebSocket:
        self.ws_connect_calls.append({"url": url, "headers": headers or {}})
        return self.websocket


def _account() -> QQBotRuntimeAccount:
    return QQBotRuntimeAccount(
        account_key="default",
        app_id="1903891442",
        client_secret="secret",
        allow_from=("USER_A",),
        group_allow_from=("GROUP_A",),
        dm_policy="open",
        group_policy="open",
    )


async def test_gateway_identify_bootstrap_persists_ready_state(tmp_path) -> None:
    websocket = _FakeWebSocket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60000}},
            {"op": 0, "t": "READY", "s": 5, "d": {"session_id": "sess-1"}},
        ]
    )
    session = _FakeSession(websocket)
    store = QQBotSessionStore(tmp_path)
    api_client = SimpleNamespace(fetch_gateway_url=AsyncMock(return_value="wss://gateway.example/ws"))
    token_manager = SimpleNamespace(
        get_access_token=AsyncMock(
            return_value=QQBotAccessToken("TOKEN123", 7200, 9_999_999_999.0)
        ),
        clear_cache=AsyncMock(),
    )

    gateway = QQBotGatewayClient(
        session=session,
        api_client=api_client,
        token_manager=token_manager,
        session_store=store,
        account=_account(),
        ready_timeout_seconds=0.5,
        user_agent="ControlMesh/Test",
    )

    await gateway.start()
    await gateway.close()

    assert session.ws_connect_calls == [
        {
            "url": "wss://gateway.example/ws",
            "headers": {"User-Agent": "ControlMesh/Test"},
        }
    ]
    assert websocket.sent_json[0]["op"] == 2
    assert websocket.sent_json[0]["d"] == {
        "token": "QQBot TOKEN123",
        "intents": gateway.FULL_INTENTS,
        "shard": [0, 1],
    }
    assert store.load_state("1903891442") == QQBotSessionState(
        session_id="sess-1",
        last_seq=5,
        gateway_url="wss://gateway.example/ws",
    )


async def test_gateway_uses_resume_when_session_state_exists(tmp_path) -> None:
    store = QQBotSessionStore(tmp_path)
    store.save_state(
        "1903891442",
        QQBotSessionState(session_id="sess-1", last_seq=41, gateway_url="wss://gateway.example/ws"),
    )
    websocket = _FakeWebSocket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60000}},
            {"op": 0, "t": "RESUMED", "s": 42, "d": {}},
        ]
    )
    session = _FakeSession(websocket)
    api_client = SimpleNamespace(fetch_gateway_url=AsyncMock(return_value="wss://gateway.example/ws"))
    token_manager = SimpleNamespace(
        get_access_token=AsyncMock(
            return_value=QQBotAccessToken("TOKEN123", 7200, 9_999_999_999.0)
        ),
        clear_cache=AsyncMock(),
    )

    gateway = QQBotGatewayClient(
        session=session,
        api_client=api_client,
        token_manager=token_manager,
        session_store=store,
        account=_account(),
        ready_timeout_seconds=0.5,
        user_agent="ControlMesh/Test",
    )

    await gateway.start()
    await gateway.close()

    assert websocket.sent_json[0] == {
        "op": 6,
        "d": {
            "token": "QQBot TOKEN123",
            "session_id": "sess-1",
            "seq": 41,
        },
    }
    assert store.load_state("1903891442") == QQBotSessionState(
        session_id="sess-1",
        last_seq=42,
        gateway_url="wss://gateway.example/ws",
    )


async def test_invalid_session_after_ready_closes_runtime_and_clears_state(tmp_path) -> None:
    store = QQBotSessionStore(tmp_path)
    store.save_state(
        "1903891442",
        QQBotSessionState(session_id="sess-1", last_seq=41, gateway_url="wss://gateway.example/ws"),
    )
    websocket = _FakeWebSocket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60000}},
            {"op": 0, "t": "READY", "s": 42, "d": {"session_id": "sess-2"}},
            {"op": 9, "d": False},
        ]
    )
    session = _FakeSession(websocket)
    api_client = SimpleNamespace(fetch_gateway_url=AsyncMock(return_value="wss://gateway.example/ws"))
    token_manager = SimpleNamespace(
        get_access_token=AsyncMock(
            return_value=QQBotAccessToken("TOKEN123", 7200, 9_999_999_999.0)
        ),
        clear_cache=MagicMock(),
    )

    gateway = QQBotGatewayClient(
        session=session,
        api_client=api_client,
        token_manager=token_manager,
        session_store=store,
        account=_account(),
        ready_timeout_seconds=0.5,
        user_agent="ControlMesh/Test",
    )

    await gateway.start()
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="rejected stored session"):
        await asyncio.wait_for(gateway.wait_closed(), timeout=0.5)

    token_manager.clear_cache.assert_called_once_with("1903891442")
    assert store.load_state("1903891442") == QQBotSessionState()


async def test_gateway_dispatches_message_events_to_callback(tmp_path) -> None:
    websocket = _FakeWebSocket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60000}},
            {"op": 0, "t": "READY", "s": 5, "d": {"session_id": "sess-1"}},
            {
                "op": 0,
                "t": "C2C_MESSAGE_CREATE",
                "s": 6,
                "d": {
                    "id": "msg-1",
                    "content": "hello",
                    "timestamp": "2026-04-24T00:00:00Z",
                    "author": {
                        "id": "user-id",
                        "union_openid": "union-id",
                        "user_openid": "USER_A",
                    },
                },
            },
        ]
    )
    session = _FakeSession(websocket)
    store = QQBotSessionStore(tmp_path)
    api_client = SimpleNamespace(fetch_gateway_url=AsyncMock(return_value="wss://gateway.example/ws"))
    token_manager = SimpleNamespace(
        get_access_token=AsyncMock(
            return_value=QQBotAccessToken("TOKEN123", 7200, 9_999_999_999.0)
        ),
        clear_cache=AsyncMock(),
    )
    on_dispatch = AsyncMock()

    gateway = QQBotGatewayClient(
        session=session,
        api_client=api_client,
        token_manager=token_manager,
        session_store=store,
        account=_account(),
        ready_timeout_seconds=0.5,
        user_agent="ControlMesh/Test",
        on_dispatch=on_dispatch,
    )

    await gateway.start()
    await asyncio.sleep(0)
    await gateway.close()

    on_dispatch.assert_awaited_once_with(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg-1",
            "content": "hello",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "user-id",
                "union_openid": "union-id",
                "user_openid": "USER_A",
            },
        },
    )
