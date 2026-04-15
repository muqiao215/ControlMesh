"""Weixin iLink bot runtime skeleton."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

from controlmesh.bus.bus import MessageBus
from controlmesh.bus.lock_pool import LockPool
from controlmesh.config import AgentConfig
from controlmesh.files.allowed_roots import resolve_allowed_roots
from controlmesh.messenger.notifications import NotificationService
from controlmesh.messenger.weixin.api import WeixinIlinkHttpClient
from controlmesh.messenger.weixin.auth_state import WeixinAuthStateStore
from controlmesh.messenger.weixin.auth_store import WeixinCredentialStore
from controlmesh.messenger.weixin.id_map import WeixinIdMap
from controlmesh.messenger.weixin.runtime import (
    WeixinContextTokenRequiredError,
    WeixinIncomingText,
    WeixinLongPollRuntime,
    WeixinReauthRequiredError,
)
from controlmesh.messenger.weixin.runtime_state import WeixinRuntimeStateStore
from controlmesh.messenger.weixin.transport import WeixinTransport
from controlmesh.session.key import SessionKey

if TYPE_CHECKING:
    from controlmesh.multiagent.bus import AsyncInterAgentResult
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.tasks.models import TaskResult
    from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)


class WeixinNotificationService:
    """NotificationService implementation for Weixin."""

    def __init__(self, bot: WeixinBot) -> None:
        self._bot = bot

    async def notify(self, chat_id: int, text: str) -> None:
        await self._bot.send_text(chat_id, text)

    async def notify_all(self, text: str) -> None:
        await self._bot.broadcast_text(text)


class WeixinBot:
    """Minimal iLink bot based on QR credentials and getupdates long polling."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        agent_name: str = "main",
        bus: MessageBus | None = None,
        lock_pool: LockPool | None = None,
    ) -> None:
        self._config = config
        self._agent_name = agent_name
        self._orchestrator: Orchestrator | None = None
        self._abort_all_callback: Callable[[], Awaitable[int]] | None = None
        self._startup_hooks: list[Callable[[], Awaitable[None]]] = []
        self._lock_pool = lock_pool or LockPool()
        self._bus = bus or MessageBus(lock_pool=self._lock_pool)
        self._stop_event = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None
        self._runtime: WeixinLongPollRuntime | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._shutdown_started = False
        self._exit_code = 0

        store_path = Path(config.controlmesh_home).expanduser() / "weixin_store"
        store_path.mkdir(parents=True, exist_ok=True)
        self._id_map = WeixinIdMap(store_path)
        self._credential_store = WeixinCredentialStore(
            config.controlmesh_home,
            relative_path=config.weixin.credentials_path,
        )
        self._auth_state_store = WeixinAuthStateStore(config.controlmesh_home)
        self._runtime_state_store = WeixinRuntimeStateStore(config.controlmesh_home)
        self._notification_service: NotificationService = WeixinNotificationService(self)
        self._bus.register_transport(WeixinTransport(self))

    @property
    def orchestrator(self) -> Orchestrator | None:
        return self._orchestrator

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def notification_service(self) -> NotificationService:
        return self._notification_service

    def register_startup_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._startup_hooks.append(hook)

    def set_abort_all_callback(self, callback: Callable[[], Awaitable[int]]) -> None:
        self._abort_all_callback = callback

    def file_roots(self, paths: ControlMeshPaths) -> list[Path] | None:
        return resolve_allowed_roots(self._config.file_access, paths.workspace)

    async def run(self) -> int:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

        from controlmesh.orchestrator.core import Orchestrator

        try:
            if self._orchestrator is None:
                self._orchestrator = await Orchestrator.create(
                    self._config,
                    agent_name=self._agent_name,
                )
                self._orchestrator.wire_observers_to_bus(self._bus)

            self._start_runtime()
            for hook in self._startup_hooks:
                await hook()
            await self._stop_event.wait()
        finally:
            await self._close_runtime()
        return self._exit_code

    async def shutdown(self) -> None:
        self._stop_event.set()
        await self._close_runtime()

    async def on_async_interagent_result(self, result: AsyncInterAgentResult) -> None:
        if result.text:
            await self.notification_service.notify_all(result.text)

    async def on_task_result(self, result: TaskResult) -> None:
        if result.chat_id and result.result_text:
            await self.send_text(result.chat_id, result.result_text)

    async def on_task_question(
        self,
        task_id: str,
        question: str,
        prompt_preview: str,
        chat_id: int,
        thread_id: int | None = None,
    ) -> None:
        del thread_id
        await self.send_text(chat_id, f"Task `{task_id}` has a question:\n{question}\n\n{prompt_preview}")

    async def handle_incoming_text(self, message: WeixinIncomingText) -> None:
        if self._orchestrator is None:
            logger.warning("Ignoring Weixin message before startup")
            return
        if self._runtime is None:
            logger.warning("Ignoring Weixin message before runtime init")
            return

        chat_id = self._id_map.user_to_int(message.user_id)
        lock = self._lock_pool.get((chat_id, None))
        async with lock:
            result = await self._orchestrator.handle_message_streaming(
                SessionKey.for_transport("wx", chat_id),
                message.text,
            )
        if result.text:
            await self._runtime.reply(message, result.text)

    async def send_text(self, chat_id: int, text: str) -> None:
        user_id = self._id_map.int_to_user(chat_id)
        if user_id is None:
            msg = f"No Weixin user mapping for chat_id {chat_id}"
            raise WeixinContextTokenRequiredError(msg)
        if self._runtime is None:
            raise WeixinContextTokenRequiredError("Weixin runtime is not initialized")
        await self._runtime.send_text(user_id, text)

    async def broadcast_text(self, text: str) -> None:
        for chat_id in self._id_map.known_user_ids():
            await self.send_text(chat_id, text)

    def _start_runtime(self) -> None:
        if self._runtime is not None:
            return
        if self._session is None:
            msg = "Weixin runtime requires an aiohttp session"
            raise RuntimeError(msg)
        credentials = self._credential_store.load_credentials()
        if credentials is None:
            msg = f"Weixin iLink credentials not found at {self._credential_store.path}"
            raise RuntimeError(msg)
        self._runtime = WeixinLongPollRuntime(
            credentials=credentials,
            client=WeixinIlinkHttpClient(self._session, self._config.weixin),
            on_text=self.handle_incoming_text,
            on_auth_expired=self._on_auth_expired,
            cursor=self._config.weixin.poll_initial_cursor,
            state_store=self._runtime_state_store,
        )
        self._poll_task = asyncio.create_task(self._poll_loop(), name="weixin:poll")

    async def _poll_loop(self) -> None:
        retry_delay_seconds = 1.0
        while not self._stop_event.is_set():
            try:
                if self._runtime is not None:
                    await self._runtime.poll_once()
                retry_delay_seconds = 1.0
            except asyncio.CancelledError:
                raise
            except WeixinReauthRequiredError:
                logger.warning("Weixin iLink session expired; QR re-auth required")
                self._auth_state_store.mark_reauth_required()
                self._credential_store.clear()
                self._runtime_state_store.clear()
                self._runtime = None
                self._stop_event.set()
                return
            except Exception:
                logger.exception("Weixin iLink poll failed")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=retry_delay_seconds)
                retry_delay_seconds = min(retry_delay_seconds * 2, 10.0)

    async def _on_auth_expired(self, _credentials: object) -> None:
        self._auth_state_store.mark_reauth_required()
        self._credential_store.clear()
        self._runtime_state_store.clear()

    async def _close_runtime(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None

        if self._session is not None and not self._session.closed:
            await self._session.close()

        if self._orchestrator is not None:
            shutdown = getattr(self._orchestrator, "shutdown", None)
            if shutdown is not None:
                await shutdown()
