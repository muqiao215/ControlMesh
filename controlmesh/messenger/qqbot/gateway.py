"""Official QQ gateway bootstrap and heartbeat runtime."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType

from controlmesh.messenger.qqbot.session_store import QQBotSessionState, QQBotSessionStore
from controlmesh.messenger.qqbot.types import QQBotRuntimeAccount

if TYPE_CHECKING:
    import aiohttp

    from controlmesh.messenger.qqbot.api import QQBotApiClient
    from controlmesh.messenger.qqbot.token_manager import QQBotTokenManager

logger = logging.getLogger(__name__)

FULL_INTENTS = (1 << 30) | (1 << 12) | (1 << 25) | (1 << 26)
_OP_DISPATCH = 0
_OP_HEARTBEAT = 1
_OP_IDENTIFY = 2
_OP_RESUME = 6
_OP_RECONNECT = 7
_OP_INVALID_SESSION = 9
_OP_HELLO = 10


class QQBotGatewayClient:
    """Bootstrap the official QQ websocket session and keep heartbeat alive."""

    FULL_INTENTS = FULL_INTENTS

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession | Any,
        api_client: QQBotApiClient,
        token_manager: QQBotTokenManager | Any,
        session_store: QQBotSessionStore,
        account: QQBotRuntimeAccount,
        ready_timeout_seconds: float = 10.0,
        user_agent: str,
        on_dispatch: Any | None = None,
    ) -> None:
        self._session = session
        self._api_client = api_client
        self._token_manager = token_manager
        self._session_store = session_store
        self._account = account
        self._ready_timeout_seconds = ready_timeout_seconds
        self._user_agent = user_agent
        self._on_dispatch = on_dispatch

        self._ws: Any | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._ready_future: asyncio.Future[str] | None = None
        self._closed = asyncio.Event()
        self._background_error: Exception | None = None
        self._stop_requested = False

        self._session_id = ""
        self._last_seq: int | None = None
        self._gateway_url = ""

    async def start(self) -> None:
        state = self._session_store.load_state(self._account.app_id)
        can_resume = bool(state.session_id) and state.last_seq is not None
        try:
            await self._connect(state=state, resume=can_resume)
        except _ResumeRejectedError:
            await self.close()
            self._closed = asyncio.Event()
            self._background_error = None
            self._stop_requested = False
            self._session_store.clear(self._account.app_id)
            await self._connect(state=QQBotSessionState(), resume=False)

    async def close(self) -> None:
        self._stop_requested = True
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            await _await_cancelled(self._heartbeat_task)
            self._heartbeat_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._reader_task is not None and self._reader_task is not asyncio.current_task():
            self._reader_task.cancel()
            await _await_cancelled(self._reader_task)
            self._reader_task = None
        self._closed.set()

    async def wait_closed(self) -> None:
        await self._closed.wait()
        if self._background_error is not None:
            raise self._background_error

    async def _connect(self, *, state: QQBotSessionState, resume: bool) -> None:
        self._session_id = state.session_id
        self._last_seq = state.last_seq
        token = await self._token_manager.get_access_token(
            self._account.app_id,
            self._account.client_secret,
        )
        self._gateway_url = state.gateway_url or await self._api_client.fetch_gateway_url(
            token.access_token
        )
        self._ws = await self._session.ws_connect(
            self._gateway_url,
            headers={"User-Agent": self._user_agent},
        )
        hello = await self._receive_json()
        heartbeat_interval_ms = _read_heartbeat_interval(hello)

        self._ready_future = asyncio.get_running_loop().create_future()
        self._reader_task = asyncio.create_task(self._reader_loop(), name="qqbot:gateway-reader")
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(heartbeat_interval_ms),
            name="qqbot:gateway-heartbeat",
        )

        if resume and self._session_id and self._last_seq is not None:
            await self._ws.send_json(
                {
                    "op": _OP_RESUME,
                    "d": {
                        "token": f"QQBot {token.access_token}",
                        "session_id": self._session_id,
                        "seq": self._last_seq,
                    },
                }
            )
        else:
            await self._ws.send_json(
                {
                    "op": _OP_IDENTIFY,
                    "d": {
                        "token": f"QQBot {token.access_token}",
                        "intents": FULL_INTENTS,
                        "shard": [0, 1],
                    },
                }
            )

        if self._ready_future is None:
            msg = "QQ gateway ready future was not initialized"
            raise RuntimeError(msg)
        try:
            await asyncio.wait_for(self._ready_future, timeout=self._ready_timeout_seconds)
        except Exception:
            await self.close()
            raise

    async def _reader_loop(self) -> None:
        try:
            while not self._stop_requested and self._ws is not None:
                message = await self._ws.receive()
                if message.type == WSMsgType.TEXT:
                    payload = json.loads(message.data)
                    await self._handle_payload(payload)
                    continue
                if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED}:
                    raise RuntimeError("QQ gateway websocket closed")
                if message.type == WSMsgType.ERROR:
                    raise RuntimeError("QQ gateway websocket error")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_exception(exc)
            else:
                self._background_error = exc
        finally:
            self._closed.set()

    async def _handle_payload(self, payload: dict[str, Any]) -> None:
        seq = payload.get("s")
        if isinstance(seq, int):
            self._last_seq = seq
            self._persist_state()

        op = payload.get("op")
        if op == _OP_DISPATCH:
            event_type = payload.get("t")
            data = payload.get("d")
            if event_type == "READY":
                data = payload.get("d", {})
                session_id = data.get("session_id") if isinstance(data, dict) else None
                if isinstance(session_id, str) and session_id:
                    self._session_id = session_id
                    self._persist_state()
                if self._ready_future is not None and not self._ready_future.done():
                    self._ready_future.set_result("ready")
            elif event_type == "RESUMED":
                self._persist_state()
                if self._ready_future is not None and not self._ready_future.done():
                    self._ready_future.set_result("resumed")
            elif self._on_dispatch is not None and isinstance(event_type, str) and isinstance(data, dict):
                await self._on_dispatch(event_type, data)
            return

        if op == _OP_RECONNECT:
            exc = RuntimeError("QQ gateway requested reconnect")
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_exception(exc)
            else:
                self._background_error = exc
            self._stop_requested = True
            if self._ws is not None:
                await self._ws.close()
            self._closed.set()
            return

        if op == _OP_INVALID_SESSION:
            self._session_store.clear(self._account.app_id)
            self._token_manager.clear_cache(self._account.app_id)
            exc = _ResumeRejectedError("QQ gateway rejected stored session")
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_exception(exc)
            else:
                self._background_error = exc
            self._stop_requested = True
            if self._ws is not None:
                await self._ws.close()
            self._closed.set()

    async def _heartbeat_loop(self, interval_ms: int) -> None:
        try:
            while not self._stop_requested and self._ws is not None:
                await asyncio.sleep(interval_ms / 1000)
                if self._stop_requested or self._ws is None:
                    return
                await self._ws.send_json({"op": _OP_HEARTBEAT, "d": self._last_seq})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("QQ gateway heartbeat loop failed", exc_info=exc)
            self._background_error = exc
            self._closed.set()

    async def _receive_json(self) -> dict[str, Any]:
        if self._ws is None:
            msg = "QQ gateway websocket is not connected"
            raise RuntimeError(msg)
        message = await self._ws.receive()
        if message.type != WSMsgType.TEXT:
            msg = f"Expected QQ gateway text frame, got {message.type!r}"
            raise RuntimeError(msg)
        payload = json.loads(message.data)
        if payload.get("op") != _OP_HELLO:
            msg = f"Expected QQ gateway HELLO, got op={payload.get('op')!r}"
            raise RuntimeError(msg)
        return payload

    def _persist_state(self) -> None:
        self._session_store.save_state(
            self._account.app_id,
            QQBotSessionState(
                session_id=self._session_id,
                last_seq=self._last_seq,
                gateway_url=self._gateway_url,
            ),
        )


class _ResumeRejectedError(RuntimeError):
    """Stored session resume failed and should fall back to IDENTIFY."""


def _read_heartbeat_interval(payload: dict[str, Any]) -> int:
    data = payload.get("d", {})
    interval = data.get("heartbeat_interval") if isinstance(data, dict) else None
    if not isinstance(interval, int):
        msg = "QQ gateway HELLO did not include heartbeat_interval"
        raise RuntimeError(msg)
    return interval


async def _await_cancelled(task: asyncio.Task[None]) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        await task
