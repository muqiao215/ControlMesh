"""Feishu domestic long-connection receive lifecycle."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from controlmesh.config import FeishuConfig

logger = logging.getLogger(__name__)
_DEFAULT_FEISHU_DOMAIN = "https://open.feishu.cn"
_START_TIMEOUT_SECONDS = 10.0
_STOP_TIMEOUT_SECONDS = 5.0
_CANCEL_RETRY_DELAY_SECONDS = 0.05

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


@dataclass
class _ConnectionAttempt:
    """One isolated long-connection attempt.

    Everything the worker thread touches lives on the attempt, never on the
    adapter, so a late cleanup from a superseded attempt cannot clobber the
    state of the attempt that replaced it.
    """

    generation: int
    app_id: str
    app_secret: str
    event_handler: FeishuEventHandler
    thread: threading.Thread | None = None
    loop: asyncio.AbstractEventLoop | None = None
    client: Any = None
    connect_task: asyncio.Task[None] | None = None
    ping_task: asyncio.Task[None] | None = None
    start_signal: threading.Event = field(default_factory=threading.Event)
    stop_requested: threading.Event = field(default_factory=threading.Event)
    start_error: BaseException | None = None
    cancel_requested: bool = False


class _SdkLongConnectionAdapter:
    """Official SDK-backed Feishu domestic long connection."""

    def __init__(self, *, lark_module: object, ws_client_module: object, domain: str) -> None:
        self._lark_module = lark_module
        self._ws_client_module = ws_client_module
        self._domain = domain
        self._state_lock = threading.Lock()
        self._generation_counter = 0
        self._attempt: _ConnectionAttempt | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._owner_tasks: set[asyncio.Task[None]] = set()

    async def start(
        self,
        *,
        app_id: str,
        app_secret: str,
        event_handler: FeishuEventHandler,
    ) -> None:
        self._owner_loop = asyncio.get_running_loop()
        previous = self._current_attempt()
        if previous is not None:
            if self._attempt_is_healthy(previous):
                return
            await self._abort_attempt(previous.generation)

        generation = self._claim_generation()
        attempt = _ConnectionAttempt(
            generation=generation,
            app_id=app_id,
            app_secret=app_secret,
            event_handler=event_handler,
        )
        with self._state_lock:
            self._attempt = attempt
        attempt.thread = threading.Thread(
            target=self._run_attempt,
            args=(attempt,),
            name=f"feishu-long-connection-{generation}",
            daemon=True,
        )
        attempt.thread.start()

        started = await asyncio.to_thread(attempt.start_signal.wait, _START_TIMEOUT_SECONDS)
        if not started:
            await self._abort_quietly(attempt.generation)
            msg = "Timed out starting Feishu long connection"
            raise RuntimeError(msg)
        if attempt.start_error is not None:
            error = attempt.start_error
            await self._abort_quietly(attempt.generation)
            if isinstance(error, Exception):
                raise error
            msg = "Feishu long connection failed during startup"
            raise RuntimeError(msg) from error

    async def stop(self) -> None:
        attempt = self._current_attempt()
        if attempt is None:
            return
        await self._abort_attempt(attempt.generation)

    def _current_attempt(self) -> _ConnectionAttempt | None:
        with self._state_lock:
            return self._attempt

    def _attempt_is_healthy(self, attempt: _ConnectionAttempt) -> bool:
        thread = attempt.thread
        return (
            thread is not None
            and thread.is_alive()
            and attempt.start_signal.is_set()
            and attempt.start_error is None
            and not attempt.cancel_requested
        )

    def _claim_generation(self) -> int:
        with self._state_lock:
            self._generation_counter += 1
            return self._generation_counter

    def _is_current_generation(self, generation: int) -> bool:
        attempt = self._current_attempt()
        return (
            attempt is not None
            and attempt.generation == generation
            and not attempt.cancel_requested
        )

    async def _abort_attempt(self, generation: int) -> None:
        with self._state_lock:
            attempt = self._attempt
            if attempt is None or attempt.generation != generation:
                return
            attempt.cancel_requested = True
        attempt.stop_requested.set()

        thread = attempt.thread
        loop = attempt.loop
        if loop is not None and thread is not None and thread.is_alive():
            def _cancel_attempt_work() -> None:
                cancelled_something = False
                for task in (attempt.connect_task, attempt.ping_task):
                    if task is not None and not task.done():
                        task.cancel()
                        cancelled_something = True
                if not cancelled_something and attempt.client is not None:
                    # The worker has not reached a cancellable await yet; check again
                    # until it creates the tasks or its shutdown closes the loop.
                    loop.call_later(_CANCEL_RETRY_DELAY_SECONDS, _cancel_attempt_work)

            try:
                loop.call_soon_threadsafe(_cancel_attempt_work)
            except RuntimeError:
                logger.debug("Feishu connection attempt %s loop already closed", generation)

        if thread is not None:
            await asyncio.to_thread(thread.join, _STOP_TIMEOUT_SECONDS)
            if thread.is_alive():
                msg = "Timed out stopping Feishu long connection"
                raise RuntimeError(msg)

    async def _abort_quietly(self, generation: int) -> None:
        try:
            await self._abort_attempt(generation)
        except Exception:
            logger.exception("Failed to abort Feishu connection attempt %s", generation)

    def _run_attempt(self, attempt: _ConnectionAttempt) -> None:
        loop = asyncio.new_event_loop()
        attempt.loop = loop
        asyncio.set_event_loop(loop)
        ws_client_module = self._ws_client_module
        if hasattr(ws_client_module, "loop"):
            ws_client_module.loop = loop
        try:
            client = self._build_sdk_client(
                app_id=attempt.app_id,
                app_secret=attempt.app_secret,
                dispatcher=self._build_dispatcher(attempt),
            )
            attempt.client = client
            loop.run_until_complete(self._run_attempt_loop(attempt, client))
        except BaseException as exc:
            if not attempt.cancel_requested:
                attempt.start_error = exc
            attempt.start_signal.set()
        finally:
            self._shutdown_attempt(attempt, loop)

    async def _run_attempt_loop(self, attempt: _ConnectionAttempt, client: Any) -> None:
        if attempt.stop_requested.is_set():
            return
        connect_task = asyncio.ensure_future(client._connect())
        attempt.connect_task = connect_task
        await connect_task
        if attempt.stop_requested.is_set():
            return
        ping_task = asyncio.ensure_future(client._ping_loop())
        attempt.ping_task = ping_task
        attempt.start_signal.set()
        await asyncio.to_thread(attempt.stop_requested.wait)

    def _shutdown_attempt(
        self,
        attempt: _ConnectionAttempt,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        try:
            client = attempt.client
            if client is not None:
                try:
                    loop.run_until_complete(client._disconnect())
                except BaseException:
                    logger.exception("Feishu long connection disconnect failed")
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            try:
                loop.close()
            finally:
                with self._state_lock:
                    if self._attempt is attempt:
                        self._attempt = None
                attempt.client = None
                attempt.connect_task = None
                attempt.ping_task = None
                attempt.loop = None
                attempt.start_signal.set()

    def _build_dispatcher(self, attempt: _ConnectionAttempt) -> object:
        builder = self._lark_module.EventDispatcherHandler.builder("", "")
        handler = self._make_sdk_event_handler(attempt)
        builder = builder.register_p2_im_message_receive_v1(handler)
        register_card_action = getattr(builder, "register_p2_card_action_trigger", None)
        if callable(register_card_action):
            builder = register_card_action(handler)
        return builder.build()

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
        attempt: _ConnectionAttempt,
    ) -> Callable[[object], None]:
        def _handle_receive_event(data: object) -> None:
            if not self._is_current_generation(attempt.generation):
                logger.info(
                    "Dropping Feishu event from superseded connection attempt %s",
                    attempt.generation,
                )
                return
            owner_loop = self._owner_loop
            if owner_loop is None:
                msg = "Feishu long connection owner loop is not available"
                raise RuntimeError(msg)
            payload = self._normalize_event_payload(data)
            owner_loop.call_soon_threadsafe(
                self._dispatch_to_owner_loop,
                attempt.generation,
                attempt.event_handler,
                payload,
            )

        return _handle_receive_event

    def _dispatch_to_owner_loop(
        self,
        generation: int,
        event_handler: FeishuEventHandler,
        payload: dict[str, Any],
    ) -> None:
        owner_loop = self._owner_loop
        if owner_loop is None or owner_loop.is_closed():
            logger.warning("Feishu long connection owner loop unavailable during dispatch")
            return
        if not self._is_current_generation(generation):
            logger.info("Dropping Feishu event from superseded connection attempt %s", generation)
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
