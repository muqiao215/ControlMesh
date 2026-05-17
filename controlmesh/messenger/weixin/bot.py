"""Weixin iLink bot runtime skeleton."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

from controlmesh.bus.bus import MessageBus
from controlmesh.bus.lock_pool import LockPool
from controlmesh.config import AgentConfig
from controlmesh.files.allowed_roots import resolve_allowed_roots
from controlmesh.infra.restart import EXIT_RESTART, consume_restart_marker
from controlmesh.messenger.notifications import NotificationService
from controlmesh.messenger.weixin.api import WeixinIlinkApiError, WeixinIlinkHttpClient
from controlmesh.messenger.weixin.auth_state import WeixinAuthStateStore
from controlmesh.messenger.weixin.auth_store import WeixinCredentialStore
from controlmesh.messenger.weixin.id_map import WeixinIdMap
from controlmesh.messenger.weixin.inbound_spool import WeixinInboundSpool
from controlmesh.messenger.weixin.runtime import (
    WeixinContextTokenRequiredError,
    WeixinIncomingText,
    WeixinLongPollRuntime,
    WeixinPollResult,
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


@dataclass(slots=True)
class WeixinPollDiagnostics:
    """In-memory liveness and recovery diagnostics for one poller."""

    last_poll_started_at: float | None = None
    last_poll_finished_at: float | None = None
    last_poll_succeeded_at: float | None = None
    last_poll_cursor: str = ""
    last_poll_message_count: int = 0
    last_poll_delivered_text_count: int = 0
    last_poll_recovered_stale_claim_count: int = 0
    backlog_pending_count: int = 0
    blocked_lane_count: int = 0
    consecutive_failures: int = 0
    transport_dirty: bool = False
    restart_reason: str | None = None
    last_failure_reason: str | None = None
    unhealthy_reason: str | None = None

    def note_poll_started(self, *, cursor: str) -> None:
        self.last_poll_started_at = time.monotonic()
        self.last_poll_cursor = cursor

    def note_poll_succeeded(self, result: WeixinPollResult) -> None:
        now = time.monotonic()
        self.last_poll_finished_at = now
        self.last_poll_succeeded_at = now
        self.last_poll_cursor = result.cursor
        self.last_poll_message_count = result.message_count
        self.last_poll_delivered_text_count = result.delivered_text_count
        self.last_poll_recovered_stale_claim_count = result.recovered_stale_claim_count
        self.backlog_pending_count = result.backlog_pending_count
        self.blocked_lane_count = result.blocked_lane_count
        self.consecutive_failures = 0
        self.transport_dirty = False
        self.restart_reason = None
        self.last_failure_reason = None
        self.unhealthy_reason = result.unhealthy_reason

    def note_poll_failed(self, *, reason: str, cursor: str, mark_transport_dirty: bool) -> None:
        self.last_poll_finished_at = time.monotonic()
        self.last_poll_cursor = cursor
        self.consecutive_failures += 1
        self.last_failure_reason = reason
        if mark_transport_dirty:
            self.transport_dirty = True
            self.restart_reason = reason

    def note_transport_rebuilt(self) -> None:
        self.transport_dirty = False

    def last_success_age_seconds(self) -> float | None:
        if self.last_poll_succeeded_at is None:
            return None
        return max(0.0, time.monotonic() - self.last_poll_succeeded_at)


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
        self._restart_watcher: asyncio.Task[None] | None = None
        self._shutdown_started = False
        self._exit_code = 0
        self._poll_diagnostics = WeixinPollDiagnostics()
        self._poll_stall_timeout_seconds = self._compute_poll_stall_timeout_seconds()

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
        self._restart_marker = Path(config.controlmesh_home).expanduser() / "restart-requested"

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
        self._ensure_session()

        from controlmesh.orchestrator.core import Orchestrator

        try:
            if self._orchestrator is None:
                self._orchestrator = await Orchestrator.create(
                    self._config,
                    agent_name=self._agent_name,
                )
                self._orchestrator.wire_observers_to_bus(self._bus)

            self._start_runtime()
            if self._restart_watcher is None:
                self._restart_watcher = asyncio.create_task(
                    self._watch_restart_marker(),
                    name="weixin:restart-watch",
                )
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
        logger.info(
            "Accepted Weixin message user_id=%s chat_id=%s message_id=%s",
            message.user_id,
            chat_id,
            message.message_id,
        )
        lock = self._lock_pool.get((chat_id, None))
        async with lock:
            result = await self._orchestrator.handle_message_streaming(
                SessionKey.for_transport("wx", chat_id),
                message.text,
            )
        if result.text:
            logger.info(
                "Weixin reply start chat_id=%s message_id=%s chars=%s",
                chat_id,
                message.message_id,
                len(result.text),
            )
            try:
                await self._runtime.reply(message, result.text)
            except Exception:
                logger.exception(
                    "Weixin reply failed chat_id=%s message_id=%s",
                    chat_id,
                    message.message_id,
                )
                raise
            logger.info(
                "Weixin reply success chat_id=%s message_id=%s chars=%s",
                chat_id,
                message.message_id,
                len(result.text),
            )
            return
        logger.info(
            "Weixin reply skipped chat_id=%s message_id=%s empty_result=True",
            chat_id,
            message.message_id,
        )

    async def send_text(self, chat_id: int, text: str) -> None:
        user_id = self._id_map.int_to_user(chat_id)
        if user_id is None:
            msg = f"No Weixin user mapping for chat_id {chat_id}"
            raise WeixinContextTokenRequiredError(msg)
        if self._runtime is None:
            raise WeixinContextTokenRequiredError("Weixin runtime is not initialized")
        logger.info("Weixin send_text start chat_id=%s chars=%s", chat_id, len(text))
        try:
            await self._runtime.send_text(user_id, text)
        except Exception:
            logger.exception("Weixin send_text failed chat_id=%s chars=%s", chat_id, len(text))
            raise
        logger.info("Weixin send_text success chat_id=%s chars=%s", chat_id, len(text))

    async def broadcast_text(self, text: str) -> None:
        for chat_id in self._id_map.known_user_ids():
            await self.send_text(chat_id, text)

    def _start_runtime(self) -> None:
        if self._runtime is None:
            self._runtime = self._build_runtime()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop(), name="weixin:poll")

    async def _poll_loop(self) -> None:
        retry_delay_seconds = 1.0
        while not self._stop_event.is_set():
            try:
                if self._poll_diagnostics.transport_dirty:
                    await self._rebuild_transport()
                if self._runtime is None:
                    self._runtime = self._build_runtime()
                if self._runtime is None:
                    msg = "Weixin runtime is not initialized"
                    raise RuntimeError(msg)
                self._poll_diagnostics.note_poll_started(cursor=self._runtime_cursor())
                poll_result = await asyncio.wait_for(
                    self._runtime.poll_once(),
                    timeout=self._poll_stall_timeout_seconds,
                )
                self._poll_diagnostics.note_poll_succeeded(poll_result)
                retry_delay_seconds = 1.0
                if poll_result.empty_success:
                    logger.debug(
                        "Weixin poll success with no new messages cursor=%s backlog_pending=%s blocked_lanes=%s recovered_stale_claims=%s unhealthy=%s",
                        poll_result.cursor,
                        poll_result.backlog_pending_count,
                        poll_result.blocked_lane_count,
                        poll_result.recovered_stale_claim_count,
                        poll_result.unhealthy_reason or "none",
                    )
                elif poll_result.unhealthy_reason:
                    logger.warning(
                        "Weixin inbound backlog unhealthy reason=%s cursor=%s backlog_pending=%s blocked_lanes=%s",
                        poll_result.unhealthy_reason,
                        poll_result.cursor,
                        poll_result.backlog_pending_count,
                        poll_result.blocked_lane_count,
                    )
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
            except Exception as exc:
                if self._handle_recoverable_poll_error(exc):
                    await self._wait_for_retry_delay(retry_delay_seconds)
                    retry_delay_seconds = min(retry_delay_seconds * 2, 10.0)
                    continue
                self._poll_diagnostics.note_poll_failed(
                    reason="poll_fatal_error",
                    cursor=self._runtime_cursor(),
                    mark_transport_dirty=False,
                )
                logger.exception("Weixin iLink poll failed")
                await self._wait_for_retry_delay(retry_delay_seconds)
                retry_delay_seconds = min(retry_delay_seconds * 2, 10.0)

    async def _on_auth_expired(self, _credentials: object) -> None:
        self._auth_state_store.mark_reauth_required()
        self._credential_store.clear()
        self._runtime_state_store.clear()

    async def _watch_restart_marker(self) -> None:
        try:
            while True:
                await asyncio.sleep(2.0)
                if await asyncio.to_thread(consume_restart_marker, marker_path=self._restart_marker):
                    logger.info("Weixin restart marker detected, requesting restart")
                    self._exit_code = EXIT_RESTART
                    self._stop_event.set()
                    return
        except asyncio.CancelledError:
            logger.debug("Weixin restart watcher cancelled")

    async def _close_runtime(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        if self._restart_watcher is not None:
            self._restart_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._restart_watcher
            self._restart_watcher = None

        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None

        await self._close_transport_session()

        if self._orchestrator is not None:
            shutdown = getattr(self._orchestrator, "shutdown", None)
            if shutdown is not None:
                await shutdown()

    def _build_runtime(self) -> WeixinLongPollRuntime:
        self._ensure_session()
        if self._session is None:
            msg = "Weixin runtime requires an aiohttp session"
            raise RuntimeError(msg)
        credentials = self._credential_store.load_credentials()
        if credentials is None:
            msg = f"Weixin iLink credentials not found at {self._credential_store.path}"
            raise RuntimeError(msg)
        runtime = WeixinLongPollRuntime(
            credentials=credentials,
            client=WeixinIlinkHttpClient(self._session, self._config.weixin),
            on_text=self.handle_incoming_text,
            on_auth_expired=self._on_auth_expired,
            cursor=self._config.weixin.poll_initial_cursor,
            state_store=self._runtime_state_store,
            inbound_spool=WeixinInboundSpool(self._config.controlmesh_home, credentials),
        )
        persisted_state = self._runtime_state_store.load_state(credentials)
        reply_state = "ready" if persisted_state.context_tokens else "waiting_first_message"
        logger.info(
            "Weixin runtime started account_id=%s reply_state=%s cached_context_tokens=%s",
            credentials.account_id,
            reply_state,
            len(persisted_state.context_tokens),
        )
        return runtime

    def _compute_poll_stall_timeout_seconds(self) -> float:
        longpoll_seconds = max(self._config.weixin.longpoll_timeout_ms / 1000.0, 1.0)
        return max(longpoll_seconds + 15.0, longpoll_seconds * 1.25)

    def _create_client_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession()

    def _ensure_session(self) -> None:
        if self._session is None or self._session.closed:
            self._session = self._create_client_session()

    async def _close_transport_session(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _rebuild_transport(self) -> None:
        reason = self._poll_diagnostics.restart_reason or "dirty_transport"
        logger.info(
            "Weixin rebuilding poll transport reason=%s cursor=%s last_success_age=%s failures=%s",
            reason,
            self._poll_diagnostics.last_poll_cursor,
            self._format_last_success_age(),
            self._poll_diagnostics.consecutive_failures,
        )
        self._runtime = None
        await self._close_transport_session()
        self._ensure_session()
        self._runtime = self._build_runtime()
        self._poll_diagnostics.note_transport_rebuilt()

    async def _wait_for_retry_delay(self, retry_delay_seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=retry_delay_seconds)

    def _handle_recoverable_poll_error(self, exc: Exception) -> bool:
        reason = self._recoverable_poll_reason(exc)
        if reason is None:
            return False
        self._poll_diagnostics.note_poll_failed(
            reason=reason,
            cursor=self._runtime_cursor(),
            mark_transport_dirty=True,
        )
        logger.warning(
            "Weixin poll marked transport dirty reason=%s cursor=%s last_success_age=%s failures=%s",
            reason,
            self._runtime_cursor(),
            self._format_last_success_age(),
            self._poll_diagnostics.consecutive_failures,
            exc_info=exc,
        )
        return True

    def _recoverable_poll_reason(self, exc: Exception) -> str | None:
        if isinstance(exc, asyncio.TimeoutError):
            return "poll_stall"
        if isinstance(exc, aiohttp.ClientError):
            return "recoverable_client_error"
        if isinstance(exc, WeixinIlinkApiError):
            if exc.status == 409:
                return "poll_conflict_409"
            if exc.status in {408, 429} or 500 <= exc.status < 600:
                return f"recoverable_http_{exc.status}"
        return None

    def _runtime_cursor(self) -> str:
        runtime = self._runtime
        if runtime is None:
            return self._poll_diagnostics.last_poll_cursor
        cursor = getattr(runtime, "cursor", "")
        return cursor if isinstance(cursor, str) else self._poll_diagnostics.last_poll_cursor

    def _format_last_success_age(self) -> str:
        age = self._poll_diagnostics.last_success_age_seconds()
        if age is None:
            return "never"
        return f"{age:.2f}s"
