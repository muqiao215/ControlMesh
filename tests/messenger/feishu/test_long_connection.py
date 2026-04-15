"""Tests for Feishu domestic long-connection receive lifecycle."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.bot import FeishuBot, FeishuIncomingText
from controlmesh.messenger.feishu.long_connection import (
    FeishuLongConnectionClient,
    build_long_connection_adapter,
)

FeishuEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class _FakeLongConnectionAdapter:
    def __init__(self) -> None:
        self.start_calls: list[dict[str, object]] = []
        self.stop_calls = 0
        self.event_handler: FeishuEventHandler | None = None

    async def start(
        self,
        *,
        app_id: str,
        app_secret: str,
        event_handler: FeishuEventHandler,
    ) -> None:
        self.start_calls.append({"app_id": app_id, "app_secret": app_secret})
        self.event_handler = event_handler

    async def stop(self) -> None:
        self.stop_calls += 1

    async def emit(self, payload: dict[str, Any]) -> None:
        if self.event_handler is None:
            raise AssertionError("adapter was not started")
        await self.event_handler(payload)


def _make_feishu_config(tmp_path: Path, **feishu_overrides: object) -> AgentConfig:
    feishu_config: dict[str, object] = {
        "mode": "bot_only",
        "brand": "feishu",
        "app_id": "cli_123",
        "app_secret": "sec_456",
    }
    feishu_config.update(feishu_overrides)
    return AgentConfig(
        transport="feishu",
        transports=["feishu"],
        controlmesh_home=str(tmp_path),
        feishu=feishu_config,
    )


def _text_event(*, create_time_ms: int | None = None) -> dict[str, Any]:
    if create_time_ms is None:
        create_time_ms = int(time.time() * 1000)
    return {
        "schema": "2.0",
        "header": {
            "event_id": "evt_1",
            "event_type": "im.message.receive_v1",
            "create_time": str(create_time_ms),
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
                "content": '{"text":"hello from feishu ws"}',
            },
        },
    }


class _FakeSdkPayload:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload


class _FakeSdkDispatcher:
    def __init__(self, callback: Callable[[object], None]) -> None:
        self.callback = callback


class _FakeSdkDispatcherBuilder:
    def __init__(self) -> None:
        self.callback: Callable[[object], None] | None = None

    def register_p2_im_message_receive_v1(
        self,
        callback: Callable[[object], None],
    ) -> _FakeSdkDispatcherBuilder:
        self.callback = callback
        return self

    def build(self) -> _FakeSdkDispatcher:
        if self.callback is None:
            raise AssertionError("dispatcher callback missing")
        return _FakeSdkDispatcher(self.callback)


class _FakeSdkEventDispatcherHandler:
    @staticmethod
    def builder(_encrypt_key: str, _verification_token: str) -> _FakeSdkDispatcherBuilder:
        return _FakeSdkDispatcherBuilder()


class _FakeSdkJson:
    @staticmethod
    def marshal(data: object, indent: int | None = None) -> str:
        del indent
        if isinstance(data, _FakeSdkPayload):
            return json.dumps(data.payload)
        if isinstance(data, dict):
            return json.dumps(data)
        msg = f"unexpected sdk payload type: {type(data)!r}"
        raise TypeError(msg)


class _FakeSdkClient:
    fail_on_connect: BaseException | None = None
    instances: list[_FakeSdkClient] = []

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        log_level: object,
        event_handler: _FakeSdkDispatcher,
        domain: str,
        auto_reconnect: bool = True,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.log_level = log_level
        self.event_handler = event_handler
        self.domain = domain
        self.auto_reconnect = auto_reconnect
        self._conn: object | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.disconnect_calls = 0
        self.emit_calls = 0
        type(self).instances.append(self)

    async def _connect(self) -> None:
        if type(self).fail_on_connect is not None:
            raise type(self).fail_on_connect
        self._loop = asyncio.get_running_loop()
        self._conn = object()

    async def _disconnect(self) -> None:
        self.disconnect_calls += 1
        self._conn = None

    async def _ping_loop(self) -> None:
        await asyncio.Event().wait()

    def emit(self, payload: dict[str, Any]) -> None:
        if self._loop is None:
            raise AssertionError("fake sdk client is not connected")
        self.emit_calls += 1
        done = threading.Event()
        error: BaseException | None = None

        def _dispatch() -> None:
            nonlocal error
            try:
                self.event_handler.callback(_FakeSdkPayload(payload))
            except BaseException as exc:
                error = exc
            finally:
                done.set()

        self._loop.call_soon_threadsafe(_dispatch)
        if not done.wait(timeout=1):
            raise AssertionError("sdk event dispatch timed out")
        if error is not None:
            raise error


def _fake_sdk_import(name: str) -> object:
    if name == "lark_oapi":
        return SimpleNamespace(
            EventDispatcherHandler=_FakeSdkEventDispatcherHandler,
            JSON=_FakeSdkJson,
            LogLevel=SimpleNamespace(INFO="INFO"),
        )
    if name == "lark_oapi.ws.client":
        return SimpleNamespace(Client=_FakeSdkClient, loop=None)
    msg = f"unexpected import request: {name}"
    raise ModuleNotFoundError(msg)


class TestFeishuLongConnectionClient:
    async def test_start_requires_bot_credentials(self, tmp_path: Path) -> None:
        adapter = _FakeLongConnectionAdapter()
        config = _make_feishu_config(tmp_path, app_id="", app_secret="")
        handler = AsyncMock()
        client = FeishuLongConnectionClient(
            config.feishu,
            handler,
            adapter=adapter,
        )

        started = await client.start()

        assert started is False
        assert client.is_running is False
        assert adapter.start_calls == []

    async def test_start_registers_event_handler_with_adapter(self, tmp_path: Path) -> None:
        adapter = _FakeLongConnectionAdapter()
        config = _make_feishu_config(tmp_path)
        handler = AsyncMock()
        client = FeishuLongConnectionClient(
            config.feishu,
            handler,
            adapter=adapter,
        )

        started = await client.start()

        assert started is True
        assert client.is_running is True
        assert adapter.start_calls == [{"app_id": "cli_123", "app_secret": "sec_456"}]

    async def test_fake_ws_text_event_uses_existing_bot_event_path(self, tmp_path: Path) -> None:
        adapter = _FakeLongConnectionAdapter()
        bot = FeishuBot(_make_feishu_config(tmp_path))
        bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]
        client = FeishuLongConnectionClient(
            bot.config.feishu,
            bot.handle_incoming_event,
            adapter=adapter,
        )

        await client.start()
        await adapter.emit(_text_event())

        bot.handle_incoming_text.assert_awaited_once_with(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="hello from feishu ws",
                thread_id="omt_1",
                create_time_ms=bot.handle_incoming_text.await_args.args[0].create_time_ms,
            )
        )

    async def test_stop_closes_started_adapter_once(self, tmp_path: Path) -> None:
        adapter = _FakeLongConnectionAdapter()
        config = _make_feishu_config(tmp_path)
        client = FeishuLongConnectionClient(config.feishu, AsyncMock(), adapter=adapter)

        await client.start()
        await client.stop()
        await client.stop()

        assert adapter.stop_calls == 1
        assert client.is_running is False

    async def test_start_does_not_fake_success_when_adapter_start_fails(
        self,
        tmp_path: Path,
    ) -> None:
        adapter = _FakeLongConnectionAdapter()
        adapter.start = AsyncMock(side_effect=RuntimeError("auth failed"))  # type: ignore[method-assign]
        config = _make_feishu_config(tmp_path)
        client = FeishuLongConnectionClient(config.feishu, AsyncMock(), adapter=adapter)

        with pytest.raises(RuntimeError, match="auth failed"):
            await client.start()

        assert client.is_running is False


class TestBuildLongConnectionAdapter:
    def test_returns_none_and_logs_when_sdk_dependency_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from controlmesh.messenger.feishu import long_connection

        def _raise_missing(name: str) -> object:
            raise ModuleNotFoundError(name)

        monkeypatch.setattr(long_connection.importlib, "import_module", _raise_missing)

        with caplog.at_level("WARNING"):
            adapter = build_long_connection_adapter()

        assert adapter is None
        assert "lark-oapi" in caplog.text

    async def test_constructs_sdk_adapter_and_routes_receive_event(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from controlmesh.messenger.feishu import long_connection

        _FakeSdkClient.instances.clear()
        _FakeSdkClient.fail_on_connect = None
        monkeypatch.setattr(long_connection.importlib, "import_module", _fake_sdk_import)
        adapter = build_long_connection_adapter()
        assert adapter is not None

        handler = AsyncMock()
        await adapter.start(
            app_id="cli_123",
            app_secret="sec_456",
            event_handler=handler,
        )

        client = _FakeSdkClient.instances[-1]
        payload = _text_event()
        await asyncio.to_thread(client.emit, payload)
        handler.assert_awaited_once_with(payload)

        await adapter.stop()
        assert client.disconnect_calls == 1

    async def test_sdk_adapter_does_not_block_receive_thread_on_slow_handler(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from controlmesh.messenger.feishu import long_connection

        _FakeSdkClient.instances.clear()
        _FakeSdkClient.fail_on_connect = None
        monkeypatch.setattr(long_connection.importlib, "import_module", _fake_sdk_import)
        adapter = build_long_connection_adapter()
        assert adapter is not None

        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_handler(_payload: dict[str, Any]) -> None:
            started.set()
            await release.wait()

        await adapter.start(
            app_id="cli_123",
            app_secret="sec_456",
            event_handler=_slow_handler,
        )

        client = _FakeSdkClient.instances[-1]
        await asyncio.wait_for(asyncio.to_thread(client.emit, _text_event()), timeout=0.2)
        await asyncio.wait_for(started.wait(), timeout=1)
        release.set()
        await asyncio.sleep(0)

        await adapter.stop()
