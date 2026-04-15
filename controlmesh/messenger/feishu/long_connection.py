"""Feishu domestic long-connection receive lifecycle."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from controlmesh.config import FeishuConfig

logger = logging.getLogger(__name__)
_DEFAULT_FEISHU_DOMAIN = "https://open.feishu.cn"
_START_TIMEOUT_SECONDS = 10.0
_STOP_TIMEOUT_SECONDS = 5.0

FeishuEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class FeishuLongConnectionAdapter(Protocol):
    """Adapter boundary for the actual Feishu long-connection client."""

    async def start(
        self,
        *,
        app_id: str,
        app_secret: str,
        event_handler: FeishuEventHandler,
    ) -> None:
        """Start the receive runtime."""

    async def stop(self) -> None:
        """Stop the receive runtime."""


class _SdkLongConnectionAdapter:
    """Official SDK-backed Feishu domestic long connection."""

    def __init__(self, *, lark_module: object, ws_client_module: object, domain: str) -> None:
        self._lark_module = lark_module
        self._ws_client_module = ws_client_module
        self._domain = domain
        self._thread: threading.Thread | None = None
        self._thread_loop: asyncio.AbstractEventLoop | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._owner_tasks: set[asyncio.Task[None]] = set()
        self._ping_task: asyncio.Task[None] | None = None
        self._sdk_client: Any = None
        self._start_signal = threading.Event()
        self._stop_requested = threading.Event()
        self._start_error: BaseException | None = None

    async def start(
        self,
        *,
        app_id: str,
        app_secret: str,
        event_handler: FeishuEventHandler,
    ) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._owner_loop = asyncio.get_running_loop()
        self._start_signal.clear()
        self._stop_requested.clear()
        self._start_error = None
        self._thread = threading.Thread(
            target=self._run_sdk_client,
            kwargs={
                "app_id": app_id,
                "app_secret": app_secret,
                "event_handler": event_handler,
            },
            name="feishu-long-connection",
            daemon=True,
        )
        self._thread.start()

        started = await asyncio.to_thread(self._start_signal.wait, _START_TIMEOUT_SECONDS)
        if not started:
            await self.stop()
            msg = "Timed out starting Feishu long connection"
            raise RuntimeError(msg)
        if self._start_error is not None:
            await self.stop()
            error = self._start_error
            if isinstance(error, Exception):
                raise error
            msg = "Feishu long connection failed during startup"
            raise RuntimeError(msg) from error

    async def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return

        self._stop_requested.set()
        await asyncio.to_thread(thread.join, _STOP_TIMEOUT_SECONDS)
        if thread.is_alive():
            msg = "Timed out stopping Feishu long connection"
            raise RuntimeError(msg)
        self._thread = None

    def _run_sdk_client(
        self,
        *,
        app_id: str,
        app_secret: str,
        event_handler: FeishuEventHandler,
    ) -> None:
        loop = asyncio.new_event_loop()
        self._thread_loop = loop
        asyncio.set_event_loop(loop)
        ws_client_module = self._ws_client_module
        if hasattr(ws_client_module, "loop"):
            ws_client_module.loop = loop
        try:
            dispatcher = self._build_dispatcher(event_handler)
            client = self._build_sdk_client(
                app_id=app_id,
                app_secret=app_secret,
                dispatcher=dispatcher,
            )
            self._sdk_client = client
            loop.run_until_complete(self._run_until_stopped(client))
        except BaseException as exc:
            self._start_error = exc
            self._start_signal.set()
        finally:
            self._shutdown_loop(loop)

    async def _run_until_stopped(self, client: Any) -> None:
        await client._connect()
        self._ping_task = asyncio.create_task(client._ping_loop())
        self._start_signal.set()
        await asyncio.to_thread(self._stop_requested.wait)

    def _build_dispatcher(self, event_handler: FeishuEventHandler) -> object:
        builder = self._lark_module.EventDispatcherHandler.builder("", "")
        return builder.register_p2_im_message_receive_v1(
            self._make_sdk_event_handler(event_handler)
        ).build()

    def _build_sdk_client(self, *, app_id: str, app_secret: str, dispatcher: object) -> Any:
        log_level = getattr(getattr(self._lark_module, "LogLevel", None), "INFO", None)
        return self._ws_client_module.Client(
            app_id,
            app_secret,
            log_level=log_level,
            event_handler=dispatcher,
            domain=self._domain,
            auto_reconnect=True,
        )

    def _make_sdk_event_handler(
        self,
        event_handler: FeishuEventHandler,
    ) -> Callable[[object], None]:
        def _handle_receive_event(data: object) -> None:
            owner_loop = self._owner_loop
            if owner_loop is None:
                msg = "Feishu long connection owner loop is not available"
                raise RuntimeError(msg)
            payload = self._normalize_event_payload(data)
            owner_loop.call_soon_threadsafe(self._dispatch_to_owner_loop, event_handler, payload)

        return _handle_receive_event

    def _dispatch_to_owner_loop(
        self,
        event_handler: FeishuEventHandler,
        payload: dict[str, Any],
    ) -> None:
        owner_loop = self._owner_loop
        if owner_loop is None or owner_loop.is_closed():
            logger.warning("Feishu long connection owner loop unavailable during dispatch")
            return
        task = owner_loop.create_task(event_handler(payload))
        self._owner_tasks.add(task)
        task.add_done_callback(self._on_owner_task_done)

    def _on_owner_task_done(self, task: asyncio.Task[None]) -> None:
        self._owner_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Feishu long connection event handler failed")

    def _normalize_event_payload(self, data: object) -> dict[str, Any]:
        raw_payload = self._lark_module.JSON.marshal(data)
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict):
            msg = "Feishu SDK returned a non-object event payload"
            raise TypeError(msg)

        header = payload.get("header")
        event = payload.get("event")
        if isinstance(header, dict) and isinstance(event, dict):
            normalized = payload
        elif isinstance(payload.get("sender"), dict) and isinstance(payload.get("message"), dict):
            normalized = {
                "schema": payload.get("schema", "2.0"),
                "header": {"event_type": "im.message.receive_v1"},
                "event": payload,
            }
        else:
            msg = f"Unexpected Feishu SDK event payload shape: {payload!r}"
            raise TypeError(msg)

        normalized_header = normalized.get("header")
        if not isinstance(normalized_header, dict):
            msg = "Feishu SDK event payload is missing a valid header"
            raise TypeError(msg)
        normalized_header.setdefault("event_type", "im.message.receive_v1")
        return normalized

    def _shutdown_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            if self._sdk_client is not None:
                loop.run_until_complete(self._sdk_client._disconnect())
        except BaseException as exc:
            if self._start_error is None:
                self._start_error = exc
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self._owner_tasks.clear()
            self._ping_task = None
            self._thread_loop = None
            self._sdk_client = None
            self._start_signal.set()


def build_long_connection_adapter(
    *,
    domain: str = _DEFAULT_FEISHU_DOMAIN,
) -> FeishuLongConnectionAdapter | None:
    """Build the live adapter when the Feishu SDK is available."""
    try:
        lark_module = importlib.import_module("lark_oapi")
        ws_client_module = importlib.import_module("lark_oapi.ws.client")
    except ModuleNotFoundError:
        logger.warning(
            "Feishu long connection SDK unavailable; install `lark-oapi` to enable "
            "domestic WebSocket receive"
        )
        return None
    return _SdkLongConnectionAdapter(
        lark_module=lark_module,
        ws_client_module=ws_client_module,
        domain=domain,
    )


class FeishuLongConnectionClient:
    """Lifecycle owner for the domestic Feishu long-connection receive runtime."""

    def __init__(
        self,
        config: FeishuConfig,
        event_handler: FeishuEventHandler,
        *,
        adapter: FeishuLongConnectionAdapter | None = None,
    ) -> None:
        self._config = config
        self._event_handler = event_handler
        self._adapter = (
            adapter
            if adapter is not None
            else build_long_connection_adapter(domain=self._config.domain)
        )
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> bool:
        if self._running:
            return True
        if not self._config.app_id or not self._config.app_secret:
            logger.info("Skipping Feishu long connection: missing app_id/app_secret")
            return False
        if self._adapter is None:
            logger.warning("Skipping Feishu long connection: no SDK adapter available")
            return False
        try:
            await self._adapter.start(
                app_id=self._config.app_id,
                app_secret=self._config.app_secret,
                event_handler=self._event_handler,
            )
        except Exception:
            logger.exception("Feishu long connection failed to start")
            raise
        self._running = True
        logger.info("Feishu long connection started")
        return True

    async def stop(self) -> None:
        if not self._running or self._adapter is None:
            return
        await self._adapter.stop()
        self._running = False
        logger.info("Feishu long connection stopped")
