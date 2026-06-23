"""Telegram bot: aiogram 3.x frontend for the orchestrator."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramConflictError,
    TelegramNetworkError,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.filters import Command, CommandStart
from aiogram.methods import GetUpdates, TelegramMethod
from aiogram.types import BotCommand, ChatMemberUpdated, FSInputFile, Message, ReplyParameters

from controlmesh.command_registry import CommandTarget, get_command_names, is_command_available_for_agent
from controlmesh.bus.bus import MessageBus
from controlmesh.bus.lock_pool import LockPool
from controlmesh.commands import BOT_COMMANDS as _COMMAND_DEFS
from controlmesh.commands import MULTIAGENT_SUB_COMMANDS as _MA_SUB_DEFS
from controlmesh.config import AgentConfig
from controlmesh.files.allowed_roots import resolve_allowed_roots
from controlmesh.i18n import t
from controlmesh.infra.restart import EXIT_RESTART, consume_restart_marker, request_restart
from controlmesh.infra.updater import UpdateObserver
from controlmesh.infra.version import VersionInfo, get_current_version
from controlmesh.log_context import set_log_context
from controlmesh.messenger.notifications import NotificationService
from controlmesh.messenger.telegram.callbacks import (
    edit_selector_response,
    mark_button_choice,
    parse_ns_callback,
)
from controlmesh.messenger.telegram.chat_tracker import ChatRecord, ChatTracker
from controlmesh.messenger.telegram.file_browser import (
    file_browser_start,
    handle_file_browser_callback,
    is_file_browser_callback,
)
from controlmesh.messenger.telegram.formatting import markdown_to_telegram_html
from controlmesh.messenger.telegram.handlers import (
    handle_abort,
    handle_abort_all,
    handle_command,
    handle_interrupt,
    handle_new_session,
    strip_mention,
)
from controlmesh.messenger.telegram.inbound_spool import (
    TelegramInboundClaim,
    TelegramInboundSpool,
    TelegramInboundSpoolStats,
)
from controlmesh.messenger.telegram.lane_state import TelegramLaneStateStore
from controlmesh.messenger.telegram.media import (
    has_media,
    is_command_for_others,
    is_media_addressed,
    is_message_addressed,
    resolve_media_text,
)
from controlmesh.messenger.telegram.message_dispatch import (
    NonStreamingDispatch,
    StreamingDispatch,
    run_non_streaming_message,
    run_streaming_message,
)
from controlmesh.messenger.telegram.middleware import (
    MQ_PREFIX,
    AuthMiddleware,
    SequentialMiddleware,
)
from controlmesh.messenger.telegram.sender import SendRichOpts, send_rich
from controlmesh.messenger.telegram.sender import (
    build_outbound_message_key,
    send_files_from_text as _send_files_from_text,
)
from controlmesh.messenger.telegram.runtime_state import (
    TelegramOutboundEchoStore,
    TelegramRuntimeState,
    TelegramRuntimeStateStore,
)
from controlmesh.messenger.telegram.topic import (
    TopicNameCache,
    get_session_key,
    get_thread_id,
)
from controlmesh.messenger.telegram.typing import TypingContext as _TypingContext
from controlmesh.messenger.telegram.welcome import (
    build_welcome_keyboard,
    build_welcome_text,
    get_welcome_button_label,
    is_welcome_callback,
    resolve_welcome_callback,
)
from controlmesh.multiagent.bus import AsyncInterAgentResult
from controlmesh.security import detect_suspicious_patterns
from controlmesh.security import classify_inbound_text
from controlmesh.security import extract_pasted_chat_transcript_message
from controlmesh.session.key import SessionKey
from controlmesh.tasks.models import TaskResult
from controlmesh.text.response_format import SEP, fmt
from controlmesh.workspace.paths import ControlMeshPaths

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery, InlineKeyboardMarkup

    from controlmesh.orchestrator.core import Orchestrator

logger = logging.getLogger(__name__)


def _log_text_preview(text: str | None, *, limit: int = 120) -> str:
    """Return a compact diagnostic preview without logging full user content."""
    if not text:
        return ""
    preview = text.replace("\n", "\\n").replace("\r", "\\r")[:limit]
    for marker in ("token=", "key=", "password=", "secret="):
        lower = preview.lower()
        start = lower.find(marker)
        if start < 0:
            continue
        value_start = start + len(marker)
        value_end = len(preview)
        for separator in (" ", "&", "\\n"):
            pos = preview.find(separator, value_start)
            if pos >= 0:
                value_end = min(value_end, pos)
        preview = f"{preview[:value_start]}[redacted]{preview[value_end:]}"
    scheme_pos = preview.find("://")
    if scheme_pos >= 0:
        query_pos = preview.find("?", scheme_pos + 3)
        fragment_pos = preview.find("#", scheme_pos + 3)
        redaction_pos = min(pos for pos in (query_pos, fragment_pos) if pos >= 0) if query_pos >= 0 or fragment_pos >= 0 else -1
        if redaction_pos >= 0:
            tail = "..." if len(text) > limit else ""
            return f"{preview[:redaction_pos]}?[redacted]{tail}"
    return f"{preview}..." if len(text) > limit else preview


_WELCOME_IMAGE = Path(__file__).resolve().parent / "controlmesh_images" / "welcome.png"
_CAPTION_LIMIT = 1024
_INBOUND_DRAIN_OWNER = "telegram_frontstage"
# Hard ceiling for keeping a single inbound claim alive. A frontstage run that
# hangs forever (e.g. a provider call that never returns) must not renew the
# lease indefinitely, otherwise recover_stale_claims() can never reclaim the
# lane and that chat stays blocked. When the cap is hit the renewal loop stops,
# the lease expires within claim_ttl, and the backlog recovery reclaims it.
_MAX_CLAIM_LIFETIME_SECONDS = 1800.0


def _poll_restart_backoff_seconds(
    *,
    consecutive_failures: int,
    retry_after_seconds: float,
) -> float:
    """Seconds to wait before re-issuing getUpdates after a poll failure.

    ``retry_after`` (Telegram 429) wins when Telegram explicitly asked us to
    wait; otherwise we back off exponentially with the consecutive failure
    count.  Returning 0 means "no wait".  The cap keeps a long outage from
    parking the bot, while still damping the reconnect storm that itself
    triggers flood control.
    """
    retry_after = max(0.0, float(retry_after_seconds or 0.0))
    consecutive = max(0, int(consecutive_failures))
    if retry_after <= 0 and consecutive <= 0:
        return 0.0
    exponential = min(60.0, 0.5 * (2 ** min(consecutive, 7)))
    return max(retry_after, exponential)
_CONTROL_COMMAND_PREFIXES = (
    "/model",
    "/provider",
    "/stop",
    "/interrupt",
    "/reset",
    "/new",
    "/session",
    "/upgrade",
    "/status",
    "/queue",
)


@dataclass(slots=True)
class _QueuedMessageRun:
    """One frontstage Telegram message turn scheduled for detached execution."""

    message: Message
    key: SessionKey
    text: str
    thread_id: int | None
    claim: TelegramInboundClaim | None = None
    lane_key: str = ""
    input_message_id: int = 0
    input_spool_id: str | None = None
    generation: int = 0


@dataclass(slots=True)
class _TelegramPollDiagnostics:
    """In-memory Telegram getUpdates liveness and recovery diagnostics."""

    last_poll_started_at: float | None = None
    last_poll_finished_at: float | None = None
    last_poll_succeeded_at: float | None = None
    last_poll_offset: int | None = None
    last_poll_update_count: int = 0
    last_poll_last_update_id: int | None = None
    consecutive_failures: int = 0
    transport_dirty: bool = False
    restart_reason: str | None = None
    last_failure_reason: str | None = None
    last_retry_after_seconds: float = 0.0
    restart_requested: bool = False

    def note_poll_started(self, *, offset: int | None) -> None:
        self.last_poll_started_at = time.monotonic()
        self.last_poll_offset = offset

    def note_poll_succeeded(self, *, offset: int | None, update_ids: list[int]) -> None:
        now = time.monotonic()
        self.last_poll_finished_at = now
        self.last_poll_succeeded_at = now
        self.last_poll_offset = offset
        self.last_poll_update_count = len(update_ids)
        self.last_poll_last_update_id = update_ids[-1] if update_ids else None
        self.consecutive_failures = 0
        self.transport_dirty = False
        self.restart_reason = None
        self.last_failure_reason = None
        self.last_retry_after_seconds = 0.0
        self.restart_requested = False

    def note_poll_failed(
        self,
        *,
        reason: str,
        offset: int | None,
        mark_transport_dirty: bool,
        retry_after_seconds: float = 0.0,
    ) -> None:
        self.last_poll_finished_at = time.monotonic()
        self.last_poll_offset = offset
        self.consecutive_failures += 1
        self.last_failure_reason = reason
        self.last_retry_after_seconds = max(0.0, float(retry_after_seconds or 0.0))
        if mark_transport_dirty:
            self.transport_dirty = True
            self.restart_reason = reason

    def note_transport_rebuilt(self) -> None:
        self.transport_dirty = False
        self.restart_requested = False

    def poll_inflight_age_seconds(self) -> float | None:
        started = self.last_poll_started_at
        if started is None:
            return None
        finished = self.last_poll_finished_at
        if finished is not None and finished >= started:
            return None
        return max(0.0, time.monotonic() - started)

    def last_success_age_seconds(self) -> float | None:
        succeeded = self.last_poll_succeeded_at
        if succeeded is None:
            return None
        return max(0.0, time.monotonic() - succeeded)


class _TelegramPollingSession(BaseSession):
    """Wrap aiogram's session so Telegram polling can emit local diagnostics."""

    def __init__(
        self,
        inner: BaseSession,
        *,
        on_poll_started: Callable[[GetUpdates], None],
        on_poll_succeeded: Callable[[GetUpdates, object], None],
        on_poll_failed: Callable[[GetUpdates, Exception], Awaitable[None]],
    ) -> None:
        super().__init__(
            api=inner.api,
            json_loads=inner.json_loads,
            json_dumps=inner.json_dumps,
            timeout=inner.timeout,
        )
        self.middleware = inner.middleware
        self._inner = inner
        self._on_poll_started = on_poll_started
        self._on_poll_succeeded = on_poll_succeeded
        self._on_poll_failed = on_poll_failed

    async def close(self) -> None:
        await self._inner.close()

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[object],
        request_timeout: int | None = None,
        **kwargs: object,
    ) -> object:
        timeout_value = kwargs.pop("timeout", request_timeout)
        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword argument(s): {unknown}")
        if isinstance(method, GetUpdates):
            self._on_poll_started(method)
            try:
                result = await self._inner.make_request(
                    bot,
                    method,
                    timeout=timeout_value,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._on_poll_failed(method, exc)
                raise
            self._on_poll_succeeded(method, result)
            return result
        return await self._inner.make_request(bot, method, timeout=timeout_value)

    async def stream_content(
        self,
        url: str,
        headers: dict[str, object] | None = None,
        request_timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
        **kwargs: object,
    ):
        timeout_value = kwargs.pop("timeout", request_timeout)
        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword argument(s): {unknown}")
        async for chunk in self._inner.stream_content(
            url,
            headers=headers,
            timeout=timeout_value,
            chunk_size=chunk_size,
            raise_for_status=raise_for_status,
        ):
            yield chunk

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


# Backward-compatible patch points used by tests.
TypingContext = _TypingContext
send_files_from_text = _send_files_from_text

_BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command=cmd, description=desc) for cmd, desc in _COMMAND_DEFS
]

_CMD_DESC: dict[str, str] = {**dict(_COMMAND_DEFS), **dict(_MA_SUB_DEFS)}


def _rebuild_commands() -> None:
    """Rebuild module-level command lists from current translations."""
    global _BOT_COMMANDS  # noqa: PLW0603
    from controlmesh.commands import get_bot_commands, get_multiagent_sub_commands

    cmd_defs = get_bot_commands()
    ma_defs = get_multiagent_sub_commands()
    _BOT_COMMANDS = [BotCommand(command=cmd, description=desc) for cmd, desc in cmd_defs]
    _CMD_DESC.clear()
    _CMD_DESC.update({**dict(cmd_defs), **dict(ma_defs)})


def _bot_commands_for_agent(agent_name: str) -> list[BotCommand]:
    """Return the Telegram popup commands applicable to one agent."""
    from controlmesh.commands import get_bot_commands

    return [
        BotCommand(command=cmd, description=desc)
        for cmd, desc in get_bot_commands(agent_name=agent_name)
    ]


def _help_line(command: str) -> str:
    """Return one command line for the help panel."""
    description = _CMD_DESC.get(command, "")
    return f"/{command} -- {description}" if description else f"/{command}"


def _build_help_text(agent_name: str = "main") -> str:
    capability_lines = [
        f"- {t('help.cap_model')}",
        f"- {t('help.cap_tasks')}",
        f"- {t('help.cap_cron')}",
        f"- {t('help.cap_memory')}",
    ]
    start_here_commands = ["help", "model", "mesh", "tasks", "upgrade", "cron"]
    daily_commands = ["interrupt", "new", "session", "status", "memory", "stop"]
    advanced_commands = ["cm", "settings", "showfiles", "info", "diagnose", "restart"]
    if agent_name == "main":
        capability_lines.insert(3, f"- {t('help.cap_agents')}")
        start_here_commands.append("agents")
        advanced_commands[3:3] = ["agent_start", "agent_stop", "agent_restart", "stop_all"]
    return fmt(
        t("help.overview_header"),
        t("help.overview_intro"),
        SEP,
        f"{t('help.capabilities_header')}\n" + "\n".join(capability_lines),
        f"{t('help.start_here_header')}\n"
        + "\n".join(_help_line(command) for command in start_here_commands),
        f"{t('help.daily_controls_header')}\n"
        + "\n".join(_help_line(command) for command in daily_commands),
        f"{t('help.advanced_header')}\n"
        + "\n".join(_help_line(command) for command in advanced_commands),
        SEP,
        t("help.footer"),
    )


async def _cancel_task(task: asyncio.Task[None] | None) -> None:
    """Cancel an asyncio task and suppress CancelledError."""
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _telegram_proxy_url() -> str | None:
    """Return the first configured Telegram proxy URL from environment."""
    for key in (
        "CONTROLMESH_TELEGRAM_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return None


def _redact_proxy_url(url: str) -> str:
    """Hide proxy credentials before logging."""
    parts = urlsplit(url)
    if parts.username is None:
        return url
    auth = parts.username
    if parts.password is not None:
        auth = f"{auth}:***"
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, f"{auth}@{host}", parts.path, parts.query, parts.fragment))


class TelegramNotificationService:
    """NotificationService implementation for Telegram."""

    def __init__(self, bot: Bot, config: AgentConfig) -> None:
        self._bot = bot
        self._config = config

    async def notify(self, chat_id: int, text: str) -> None:
        await send_rich(self._bot, chat_id, text, None)

    async def notify_all(self, text: str) -> None:
        for uid in self._config.allowed_user_ids:
            await send_rich(self._bot, uid, text, None)


class TelegramBot:
    """Telegram frontend. All logic lives in the Orchestrator."""

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
        self._startup_complete = False
        self._telegram_proxy = _telegram_proxy_url()
        self._poll_timeout_seconds = 10
        self._poll_stall_timeout_seconds = self._compute_poll_stall_timeout_seconds()
        self._poll_diagnostics = _TelegramPollDiagnostics()

        session = None
        if self._telegram_proxy:
            logger.info("Telegram bot using proxy %s", _redact_proxy_url(self._telegram_proxy))
            try:
                session = AiohttpSession(proxy=self._telegram_proxy)
            except RuntimeError as exc:
                raise RuntimeError(
                    "Telegram proxy support requires aiohttp-socks to be installed"
                ) from exc

        self._bot = Bot(
            token=config.telegram_token,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._notification_service: NotificationService = TelegramNotificationService(
            self._bot, config
        )
        self._bot_id: int | None = None
        self._bot_username: str | None = None
        self._runtime_state_store = TelegramRuntimeStateStore(config.controlmesh_home)
        self._recent_outbound = TelegramOutboundEchoStore()
        self._lane_state_store: TelegramLaneStateStore | None = None
        self._restored_poll_offset: int | None = None
        self._inbound_spool: TelegramInboundSpool | None = None
        self._last_inbound_drain_at: float | None = None
        self._last_recovered_stale_claim_count: int = 0
        self._last_inbound_spool_stats = TelegramInboundSpoolStats()

        self._dp = Dispatcher()
        self._router = Router(name="main")
        self._exit_code: int = 0
        self._restart_watcher: asyncio.Task[None] | None = None
        self._poll_watchdog: asyncio.Task[None] | None = None
        self._update_observer: UpdateObserver | None = None
        self._upgrade_lock = asyncio.Lock()
        self._group_audit_task: asyncio.Task[None] | None = None
        self._frontstage_run_loops: dict[tuple[int, int | None], asyncio.Task[None]] = {}
        self._frontstage_run_queues: dict[tuple[int, int | None], deque[_QueuedMessageRun]] = {}

        allowed = set(config.allowed_user_ids)
        allowed_groups = set(config.allowed_group_ids)
        self._allowed_users = allowed
        self._allowed_groups = allowed_groups
        self._groups_enabled = bool(config.telegram_groups_enabled)
        self._chat_tracker: ChatTracker | None = None  # set in _on_startup
        self._topic_names = TopicNameCache()
        self._lock_pool = lock_pool or LockPool()
        self._bus = bus or MessageBus(lock_pool=self._lock_pool)

        from controlmesh.messenger.telegram.transport import TelegramTransport

        self._bus.register_transport(TelegramTransport(self))
        self._sequential = SequentialMiddleware(
            lock_pool=self._lock_pool, topic_names=self._topic_names
        )
        self._sequential.set_bot(self._bot)
        self._sequential.set_interrupt_handler(self._on_interrupt)
        self._sequential.set_abort_handler(self._on_abort)
        self._sequential.set_abort_all_handler(self._on_abort_all)
        self._sequential.set_quick_command_handler(self._on_quick_command)
        on_rejected = self._on_group_rejected
        self._message_auth = AuthMiddleware(
            allowed,
            allowed_group_ids=allowed_groups,
            groups_enabled=self._groups_enabled,
            on_rejected=on_rejected,
        )
        self._callback_auth = AuthMiddleware(
            allowed,
            allowed_group_ids=allowed_groups,
            groups_enabled=self._groups_enabled,
            on_rejected=on_rejected,
        )
        self._router.message.outer_middleware(self._message_auth)
        self._router.message.outer_middleware(self._sequential)
        self._router.callback_query.outer_middleware(self._callback_auth)

        self._register_handlers()
        self._register_member_handlers()
        self._dp.include_router(self._router)
        self._dp.startup.register(self._on_startup)
        self._install_polling_session()
        self._bot._controlmesh_remember_outbound_message = self._remember_outbound_message

    @property
    def _orch(self) -> Orchestrator:
        if self._orchestrator is None:
            msg = "Orchestrator not initialized -- call after startup"
            raise RuntimeError(msg)
        return self._orchestrator

    @property
    def orchestrator(self) -> Orchestrator | None:
        """Public read-only access to the orchestrator (None before startup)."""
        return self._orchestrator

    def set_abort_all_callback(self, callback: Callable[[], Awaitable[int]]) -> None:
        """Set a callback that kills processes on ALL agents (set by supervisor)."""
        self._abort_all_callback = callback

    @property
    def dispatcher(self) -> Dispatcher:
        """Public read-only access to the aiogram Dispatcher."""
        return self._dp

    @property
    def bot_instance(self) -> Bot:
        """Public read-only access to the aiogram Bot instance."""
        return self._bot

    @property
    def config(self) -> AgentConfig:
        """Public read-only access to the agent configuration."""
        return self._config

    @property
    def notification_service(self) -> NotificationService:
        """Transport-agnostic notification interface."""
        return self._notification_service

    def register_startup_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Register a callback to run after bot startup (used by supervisor)."""
        self._dp.startup.register(hook)

    @property
    def sequential(self) -> SequentialMiddleware:
        """Public read-only access to the sequential middleware."""
        return self._sequential

    @property
    def lock_pool(self) -> LockPool:
        """Shared lock pool (used by middleware, bus, and API server)."""
        return self._lock_pool

    def _is_addressed(self, message: Message) -> bool:
        """True if the message is addressed to this bot instance."""
        if message.chat.type not in ("group", "supergroup"):
            return True
        return is_message_addressed(message, self._bot_id, self._bot_username)

    def _is_for_others(self, message: Message) -> bool:
        """True if the message is a command explicitly for another bot."""
        if message.chat.type not in ("group", "supergroup"):
            return False
        return is_command_for_others(message, self._bot_username)

    def file_roots(self, paths: ControlMeshPaths) -> list[Path] | None:
        """Allowed root directories for ``<file:...>`` tag sends."""
        return resolve_allowed_roots(self._config.file_access, paths.workspace)

    async def broadcast(self, text: str, opts: SendRichOpts | None = None) -> None:
        """Send a message to all allowed users."""
        for uid in self._config.allowed_user_ids:
            await send_rich(self._bot, uid, text, opts)

    async def _on_startup(self) -> None:
        if not self._startup_complete:
            from controlmesh.messenger.telegram.startup import run_startup

            await run_startup(self)
            self._restore_runtime_state()
            self._configure_inbound_spool()
            self._sequential.set_bot_username(self._bot_username)
            await self._recover_inbound_spool()
            await self.audit_groups()
            if self._poll_watchdog is None or self._poll_watchdog.done():
                self._poll_watchdog = asyncio.create_task(
                    self._watch_poll_health(),
                    name="telegram:poll-watchdog",
                )
            self._startup_complete = True

    def _register_handlers(self) -> None:
        r = self._router
        r.message(CommandStart(ignore_case=True))(self._on_start)
        r.message(Command("help", ignore_case=True))(self._on_help)
        r.message(Command("info", ignore_case=True))(self._on_info)
        r.message(Command("stop_all", ignore_case=True))(self._on_stop_all)
        r.message(Command("stop", ignore_case=True))(self._on_stop)
        r.message(Command("restart", ignore_case=True))(self._on_restart)
        r.message(Command("new", ignore_case=True))(self._on_new)
        r.message(Command("session", ignore_case=True))(self._on_session)
        r.message(Command("sessions", ignore_case=True))(self._on_sessions)
        r.message(Command("tasks", ignore_case=True))(self._on_tasks)
        r.message(Command("showfiles", ignore_case=True))(self._on_showfiles)
        r.message(Command("agent_commands", ignore_case=True))(self._on_agent_commands)
        base_cmds = get_command_names(
            agent_name=self._agent_name,
            targets=frozenset({CommandTarget.ORCHESTRATOR, CommandTarget.MULTIAGENT}),
        )
        for cmd in base_cmds:
            r.message(Command(cmd, ignore_case=True))(self._on_command)
        r.message(F.forum_topic_created)(self._on_forum_topic_created)
        r.message(F.forum_topic_edited)(self._on_forum_topic_edited)
        r.message()(self._on_message)
        r.callback_query()(self._on_callback_query)

    def _register_member_handlers(self) -> None:
        """Register my_chat_member handlers on the dispatcher (not router).

        ``ChatMemberUpdated`` events bypass message middleware, so they go
        directly on the dispatcher.
        """
        from aiogram.filters import ChatMemberUpdatedFilter
        from aiogram.filters.chat_member_updated import (
            IS_MEMBER,
            IS_NOT_MEMBER,
        )

        self._dp.my_chat_member.register(
            self._on_bot_added,
            ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER),
        )
        self._dp.my_chat_member.register(
            self._on_bot_removed,
            ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER),
        )

    def _on_auth_hot_reload(self, config: AgentConfig, hot: dict[str, object]) -> None:
        """Update auth sets and language in-place when config is hot-reloaded."""
        if "allowed_user_ids" in hot:
            self._allowed_users.clear()
            self._allowed_users.update(config.allowed_user_ids)
            logger.info("Auth hot-reloaded: allowed_user_ids (%d)", len(self._allowed_users))
        if "allowed_group_ids" in hot:
            self._allowed_groups.clear()
            self._allowed_groups.update(config.allowed_group_ids)
            logger.info("Auth hot-reloaded: allowed_group_ids (%d)", len(self._allowed_groups))
            self._group_audit_task = asyncio.create_task(self._fire_audit())
        if "telegram_groups_enabled" in hot:
            val = bool(config.telegram_groups_enabled)
            self._groups_enabled = val
            self._message_auth._groups_enabled = val
            self._callback_auth._groups_enabled = val
            logger.info("Auth hot-reloaded: telegram_groups_enabled=%s", val)
        if "language" in hot:
            _rebuild_commands()
            self._lang_sync_task = asyncio.create_task(self._sync_commands())
            logger.info("Language hot-reloaded: commands re-synced")

    # -- Chat tracker (my_chat_member + /where + /leave) ------------------------

    def _on_group_rejected(self, chat_id: int, chat_type: str, title: str) -> None:
        """Callback from AuthMiddleware when a group message is rejected."""
        if self._chat_tracker:
            self._chat_tracker.record_rejected(chat_id, chat_type, title)

    async def _on_bot_added(self, event: ChatMemberUpdated) -> None:
        """Bot was added to a group."""
        chat = event.chat
        if not self._groups_enabled:
            with contextlib.suppress(TelegramAPIError):
                await self._bot.leave_chat(chat.id)
            if self._chat_tracker:
                self._chat_tracker.record_leave(chat.id, "auto_left")
            logger.info("Auto-left group chat_id=%d because telegram_groups_enabled=false", chat.id)
            return
        allowed = chat.id in self._allowed_groups
        if self._chat_tracker:
            self._chat_tracker.record_join(
                chat.id,
                chat.type,
                chat.title or "",
                allowed=allowed,
            )
        if not allowed:
            with contextlib.suppress(TelegramAPIError):
                await self._bot.send_message(
                    chat.id,
                    t("telegram.group_rejected"),
                )
            with contextlib.suppress(TelegramAPIError):
                await self._bot.leave_chat(chat.id)
            if self._chat_tracker:
                self._chat_tracker.record_leave(chat.id, "auto_left")
            logger.info("Auto-left unauthorized group chat_id=%d title=%s", chat.id, chat.title)
            return
        await self._send_join_notification(chat.id)

    async def _on_bot_removed(self, event: ChatMemberUpdated) -> None:
        """Bot was removed from a group."""
        chat = event.chat
        status = "kicked" if event.new_chat_member.status == "kicked" else "left"
        if self._chat_tracker:
            self._chat_tracker.record_leave(chat.id, status)
        logger.info("Bot removed from group chat_id=%d status=%s", chat.id, status)

    async def _send_join_notification(self, chat_id: int) -> None:
        """Send JOIN_NOTIFICATION.md content and try to pin it."""
        if not self._orchestrator:
            return
        path = self._orch.paths.join_notification_path
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return
        from controlmesh.messenger.telegram.sender import _send_text_chunks

        msg = await _send_text_chunks(self._bot, chat_id, text)
        if msg:
            with contextlib.suppress(TelegramAPIError):
                await self._bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)

    _GROUP_AUDIT_INTERVAL = 86400  # 24 hours

    async def _fire_audit(self) -> None:
        """Fire-and-forget wrapper for ``audit_groups``."""
        await self.audit_groups()

    async def _run_group_audit_loop(self) -> None:
        """Run ``audit_groups`` every 24 hours."""
        while True:
            await asyncio.sleep(self._GROUP_AUDIT_INTERVAL)
            try:
                left = await self.audit_groups()
                if left:
                    logger.info("Periodic group audit: left %d group(s)", left)
            except Exception:
                logger.debug("Periodic group audit error", exc_info=True)

    async def audit_groups(self) -> int:
        """Leave groups where the bot is still a member but no longer allowed.

        Checks tracked active groups against ``allowed_group_ids`` and calls
        ``leave_chat`` for any that lost authorization.  Returns the number
        of groups left.
        """
        if not self._chat_tracker:
            return 0
        left = 0
        for rec in self._chat_tracker.get_all():
            if rec.status != "active":
                continue
            if not self._groups_enabled:
                try:
                    await self._bot.leave_chat(rec.chat_id)
                except TelegramAPIError:
                    logger.debug("audit_groups: leave_chat failed for %d", rec.chat_id, exc_info=True)
                self._chat_tracker.record_leave(rec.chat_id, "auto_left")
                logger.info("Audit: auto-left group %d (%s) because telegram_groups_enabled=false", rec.chat_id, rec.title)
                left += 1
                continue
            if rec.chat_id in self._allowed_groups:
                continue
            # Not allowed — try to leave.
            try:
                await self._bot.leave_chat(rec.chat_id)
            except TelegramAPIError:
                logger.debug("audit_groups: leave_chat failed for %d", rec.chat_id, exc_info=True)
            self._chat_tracker.record_leave(rec.chat_id, "auto_left")
            logger.info("Audit: auto-left group %d (%s)", rec.chat_id, rec.title)
            left += 1
        return left

    @staticmethod
    def _where_line(r: ChatRecord) -> str:
        """Format a single chat record for /where output."""
        title = r.title or "untitled"
        return f"`{r.chat_id}` — {title} ({r.chat_type})"

    def _format_where(self) -> str:
        """Build the /where response text."""
        if not self._chat_tracker:
            return fmt(t("telegram.where_header"), SEP, t("telegram.where_no_tracker"))
        records = self._chat_tracker.get_all()
        if not records:
            return fmt(t("telegram.where_header"), SEP, t("telegram.where_empty"))

        sections: list[str] = []
        active = [r for r in records if r.status == "active" and r.allowed]
        rejected = [r for r in records if not r.allowed or r.status == "rejected"]
        left = [r for r in records if r.status in ("left", "kicked", "auto_left")]

        if active:
            lines = [self._where_line(r) for r in active]
            sections.append("**Active**\n" + "\n".join(lines))
        if rejected:
            lines = []
            for r in rejected:
                extra = f" — {r.rejected_count}x rejected" if r.rejected_count else ""
                lines.append(f"{self._where_line(r)}{extra}")
            sections.append("**Rejected**\n" + "\n".join(lines))
        if left:
            lines = [f"{self._where_line(r)} [{r.status}]" for r in left]
            sections.append("**Left**\n" + "\n".join(lines))

        return fmt(t("telegram.where_header"), SEP, *sections)

    async def _handle_where(self, chat_id: int, message: Message) -> None:
        """Handle /where: show all tracked chats/groups."""
        await send_rich(
            self._bot,
            chat_id,
            self._format_where(),
            SendRichOpts(
                reply_to_message_id=message.message_id,
                thread_id=get_thread_id(message),
            ),
        )

    async def _handle_leave(self, chat_id: int, message: Message) -> None:
        """Handle /leave <group_id>: manually leave a group."""
        thread_id = get_thread_id(message)
        parts = (message.text or "").strip().split(None, 1)
        if len(parts) < 2:
            await send_rich(
                self._bot,
                chat_id,
                fmt(t("telegram.leave_usage_header"), SEP, t("telegram.leave_usage")),
                SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
            )
            return

        try:
            group_id = int(parts[1].strip())
        except ValueError:
            await send_rich(
                self._bot,
                chat_id,
                t("telegram.leave_invalid_id"),
                SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
            )
            return

        try:
            await self._bot.leave_chat(group_id)
        except TelegramAPIError as exc:
            await send_rich(
                self._bot,
                chat_id,
                t("telegram.leave_failed", error=exc),
                SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
            )
            return

        if self._chat_tracker:
            self._chat_tracker.record_leave(group_id, "left")

        await send_rich(
            self._bot,
            chat_id,
            t("telegram.left_group", group_id=group_id),
            SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
        )

    # -- Welcome & help ---------------------------------------------------------

    async def _show_welcome(self, message: Message) -> None:
        """Send the welcome screen with auth status and quick-start buttons."""
        from controlmesh.cli.auth import check_all_auth

        chat_id = message.chat.id
        thread_id = get_thread_id(message)
        user_name = message.from_user.first_name if message.from_user else ""

        auth_results = await asyncio.to_thread(check_all_auth)
        text = build_welcome_text(user_name, auth_results, self._config)
        keyboard = build_welcome_keyboard()

        sent_with_image = await self._send_welcome_image(
            chat_id, text, keyboard, message, thread_id=thread_id
        )
        if not sent_with_image:
            await send_rich(
                self._bot,
                chat_id,
                text,
                SendRichOpts(
                    reply_to_message_id=message.message_id,
                    reply_markup=keyboard,
                    thread_id=thread_id,
                ),
            )

    async def _send_welcome_image(
        self,
        chat_id: int,
        text: str,
        keyboard: InlineKeyboardMarkup,
        reply_to: Message,
        *,
        thread_id: int | None = None,
    ) -> bool:
        """Try to send welcome.png with caption. Returns True if caption was attached."""
        if not _WELCOME_IMAGE.is_file():
            return False

        html_caption: str | None = None
        if len(text) <= _CAPTION_LIMIT:
            html_caption = markdown_to_telegram_html(text)

        try:
            message = await self._bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(_WELCOME_IMAGE),
                caption=html_caption,
                parse_mode=ParseMode.HTML if html_caption else None,
                reply_markup=keyboard if html_caption else None,
                reply_parameters=ReplyParameters(message_id=reply_to.message_id),
                message_thread_id=thread_id,
            )
            self._remember_outbound_message(chat_id, getattr(message, "message_id", None))
        except TelegramBadRequest:
            logger.warning("Welcome image caption failed, retrying without")
            try:
                message = await self._bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(_WELCOME_IMAGE),
                    reply_parameters=ReplyParameters(message_id=reply_to.message_id),
                    message_thread_id=thread_id,
                )
                self._remember_outbound_message(chat_id, getattr(message, "message_id", None))
            except (TelegramAPIError, OSError):
                logger.exception("Failed to send welcome image")
                return False
            return False
        except (TelegramAPIError, OSError):
            logger.exception("Failed to send welcome image")
            return False
        return html_caption is not None

    async def _on_start(self, message: Message) -> None:
        """Handle /start: always show welcome screen."""
        if self._is_for_others(message):
            return
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        await self._show_welcome(message)
        await self._send_join_notification(message.chat.id)

    async def _on_help(self, message: Message) -> None:
        """Handle /help: show command reference."""
        if self._is_for_others(message):
            return
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        await send_rich(
            self._bot,
            message.chat.id,
            _build_help_text(self._agent_name),
            SendRichOpts(reply_to_message_id=message.message_id, thread_id=get_thread_id(message)),
        )

    async def _on_agent_commands(self, message: Message) -> None:
        """Handle /agent_commands: explain multi-agent system + list commands."""
        if self._is_for_others(message):
            return
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        chat_id = message.chat.id
        thread_id = get_thread_id(message)

        if self._agent_name != "main":
            text = fmt(t("agents.system_header"), SEP, t("agents.telegram_explanation"))
            await send_rich(
                self._bot,
                chat_id,
                text,
                SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
            )
            return

        lines = [
            t("agents.telegram_explanation"),
            "",
            t("agents.commands_header"),
            "`/agents` — list all agents and their status",
            "`/agent_start <name>` — start a sub-agent",
            "`/agent_stop <name>` — stop a sub-agent",
            "`/agent_restart <name>` — restart a sub-agent",
            "",
            t("agents.setup_header"),
            t("agents.setup_instruction"),
        ]
        text = fmt(t("agents.system_header"), SEP, "\n".join(lines))
        await send_rich(
            self._bot,
            chat_id,
            text,
            SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
        )

    async def _on_info(self, message: Message) -> None:
        """Handle /info: show project links and version."""
        if self._is_for_others(message):
            return
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        version = get_current_version()
        text = fmt(
            t("info.header"),
            t("info.version", version=version),
            SEP,
            t("info.telegram_description"),
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="GitHub", url="https://github.com/muqiao215/ControlMesh"
                    ),
                    InlineKeyboardButton(
                        text="Changelog",
                        url="https://github.com/muqiao215/ControlMesh/releases",
                    ),
                ],
                [InlineKeyboardButton(text="PyPI", url="https://pypi.org/project/controlmesh/")],
            ],
        )
        await send_rich(
            self._bot,
            message.chat.id,
            text,
            SendRichOpts(
                reply_to_message_id=message.message_id,
                reply_markup=keyboard,
                thread_id=get_thread_id(message),
            ),
        )

    async def _on_showfiles(self, message: Message) -> None:
        """Handle /showfiles: interactive file browser for ~/.controlmesh."""
        text, keyboard = await file_browser_start(self._orch.paths)
        await send_rich(
            self._bot,
            message.chat.id,
            text,
            SendRichOpts(
                reply_to_message_id=message.message_id,
                reply_markup=keyboard,
                thread_id=get_thread_id(message),
            ),
        )

    # -- Interrupt, abort, commands, sessions ----------------------------------

    async def _on_interrupt(self, chat_id: int, message: Message) -> bool:
        self._bump_lane_generation_for_message(message, reason="interrupt")
        return await handle_interrupt(
            self._orchestrator,
            self._bot,
            chat_id=chat_id,
            message=message,
        )

    async def _on_abort_all(self, chat_id: int, message: Message) -> bool:
        return await handle_abort_all(
            self._orchestrator,
            self._bot,
            chat_id=chat_id,
            message=message,
            abort_all_callback=self._abort_all_callback,
        )

    async def _on_abort(self, chat_id: int, message: Message) -> bool:
        await self._supersede_lane_runtime(message, reason="abort")
        return await handle_abort(
            self._orchestrator,
            self._bot,
            chat_id=chat_id,
            message=message,
        )

    async def _dispatch_direct_command(
        self,
        chat_id: int,
        message: Message,
        text_lower: str,
    ) -> bool | None:
        """Handle commands that don't need the orchestrator. Returns True/None."""
        if text_lower.startswith("/where"):
            await self._handle_where(chat_id, message)
            return True
        if text_lower.startswith("/leave"):
            await self._handle_leave(chat_id, message)
            return True
        if text_lower.startswith("/showfiles") and self._orchestrator is not None:
            await self._on_showfiles(message)
            return True
        return None

    async def _on_quick_command(self, chat_id: int, message: Message) -> bool:
        """Handle a read-only command without the sequential lock.

        ``/model`` is special: when the chat is busy it returns an immediate
        "agent is working" message; otherwise it acquires the lock for an
        atomic model switch.
        """
        if self._is_for_others(message) or (
            self._config.group_mention_only and not self._is_addressed(message)
        ):
            return False

        text_lower = (message.text or "").strip().lower()
        if self._is_control_command_text(text_lower):
            self._bump_lane_generation_for_message(message, reason="quick_command")

        direct = await self._dispatch_direct_command(chat_id, message, text_lower)
        if direct is not None or self._orchestrator is None:
            return direct or False

        if text_lower.startswith(("/sessions", "/tasks")):
            await handle_command(self._orchestrator, self._bot, message)
            return True

        if text_lower.startswith("/model"):
            await handle_command(self._orchestrator, self._bot, message)
            return True

        await handle_command(self._orchestrator, self._bot, message)
        return True

    async def _on_stop_all(self, message: Message) -> None:
        if self._is_for_others(message):
            return
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        if not is_command_available_for_agent("stop_all", agent_name=self._agent_name):
            await self._on_help(message)
            return
        await handle_abort_all(
            self._orchestrator,
            self._bot,
            chat_id=message.chat.id,
            message=message,
            abort_all_callback=self._abort_all_callback,
        )

    async def _on_stop(self, message: Message) -> None:
        if self._is_for_others(message):
            return
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        await self._supersede_lane_runtime(message, reason="user_stop")
        await handle_abort(
            self._orchestrator,
            self._bot,
            chat_id=message.chat.id,
            message=message,
        )

    async def _on_command(self, message: Message) -> None:
        if self._is_for_others(message):
            return
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        if self._is_control_command_text(message.text or ""):
            self._bump_lane_generation_for_message(message, reason="control_command")
        await handle_command(self._orch, self._bot, message)

    async def _on_new(self, message: Message) -> None:
        if self._is_for_others(message):
            return
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        await self._supersede_lane_runtime(message, reason="new_session")
        await handle_new_session(self._orch, self._bot, message, topic_names=self._topic_names)

    async def _on_forum_topic_created(self, message: Message) -> None:
        """Cache the name when a forum topic is created."""
        from controlmesh.messenger.telegram.topic import get_topic_name_from_message

        name = get_topic_name_from_message(message)
        if name and message.message_thread_id is not None:
            self._topic_names.set(message.chat.id, message.message_thread_id, name)
            logger.debug(
                "Topic name cached: %d/%d = %s", message.chat.id, message.message_thread_id, name
            )

    async def _on_forum_topic_edited(self, message: Message) -> None:
        """Update the cache when a forum topic is renamed."""
        from controlmesh.messenger.telegram.topic import get_topic_name_from_message

        name = get_topic_name_from_message(message)
        if name and message.message_thread_id is not None:
            self._topic_names.set(message.chat.id, message.message_thread_id, name)
            logger.debug(
                "Topic name updated: %d/%d = %s", message.chat.id, message.message_thread_id, name
            )

    def _build_session_help(self) -> str:
        """Build the /session hub: explain the system + show commands."""
        providers = self._orch.available_providers
        lines: list[str] = [
            t("session_help.telegram_explanation"),
            "",
            t("session_help.usage_header"),
        ]

        if len(providers) == 1:
            p = next(iter(providers))
            if p == "claude":
                lines.append(t("session_help.claude_single"))
                lines.append(t("session_help.claude_model"))
            elif p == "codex":
                lines.append(t("session_help.codex_single"))
            else:
                lines.append(t("session_help.gemini_single"))
                lines.append(t("session_help.gemini_model"))
        else:
            lines.append(t("session_help.default_provider"))
            if "claude" in providers:
                lines.append(t("session_help.claude_multi"))
            if "codex" in providers:
                lines.append(t("session_help.codex_multi"))
            if "gemini" in providers:
                lines.append(t("session_help.gemini_multi"))
            lines.append(t("session_help.explicit"))

        lines += [
            "",
            t("session_help.followup_header"),
            t("session_help.followup_line"),
            "",
            t("session_help.commands_header"),
            t("session_help.telegram_sessions_cmd"),
            t("session_help.telegram_stop_cmd"),
        ]

        return fmt(t("session_help.header"), SEP, "\n".join(lines))

    async def _on_session(self, message: Message) -> None:
        """Handle /session: submit a named background session."""
        import re

        text = (message.text or "").strip()
        parts = text.split(None, 1)
        chat_id = message.chat.id
        thread_id = get_thread_id(message)

        if len(parts) < 2 or not parts[1].strip():
            await send_rich(
                self._bot,
                chat_id,
                self._build_session_help(),
                SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
            )
            return

        prompt = parts[1].strip()
        self._bump_lane_generation_for_message(message, reason="session_command")

        # Parse optional @directive prefix:
        #   @provider [model] <prompt>    — e.g. @codex, @claude opus
        #   @model <prompt>               — e.g. @opus (infers provider)
        #   @session-name <prompt>        — follow-up to existing session
        provider_override: str | None = None
        model_override: str | None = None
        session_followup: str | None = None
        directive_match = re.match(r"@([a-zA-Z][a-zA-Z0-9_.-]*)\s+", prompt)
        if directive_match:
            key = directive_match.group(1).lower()
            rest = prompt[directive_match.end() :]

            resolved = self._orch.resolve_session_directive(key)
            if resolved:
                provider_override, model_override = resolved[0], resolved[1] or None
                prompt = rest
                # If key was a provider name, check for optional model after it
                if key in ("claude", "codex", "gemini"):
                    model_match = re.match(r"([a-zA-Z][a-zA-Z0-9_.-]*)\s+", prompt)
                    if model_match:
                        candidate = model_match.group(1).lower()
                        if self._orch.is_known_model(candidate):
                            model_override = candidate
                            prompt = prompt[model_match.end() :]
            elif self._orch.get_named_session(chat_id, key):
                session_followup = key
                prompt = rest

        try:
            if session_followup:
                task_id = self._orch.submit_named_followup_bg(
                    chat_id, session_followup, prompt, message.message_id, thread_id
                )
                await send_rich(
                    self._bot,
                    chat_id,
                    fmt(
                        f"**[{session_followup}] Follow-up sent**",
                        SEP,
                        f"Task `{task_id}` queued.",
                    ),
                    SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
                )
            else:
                from controlmesh.orchestrator.core import NamedSessionRequest

                ns_request = NamedSessionRequest(
                    message_id=message.message_id,
                    thread_id=thread_id,
                    provider_override=provider_override,
                    model_override=model_override,
                )
                task_id, session_name = self._orch.submit_named_session(
                    chat_id,
                    prompt,
                    ns_request,
                )
                ns = self._orch.get_named_session(chat_id, session_name)
                provider = ns.provider if ns else (provider_override or self._orch.config.provider)
                model = ns.model if ns else ""
                provider_label = {"claude": "Claude", "codex": "Codex", "gemini": "Gemini"}.get(
                    provider, provider
                )
                model_info = f" ({model})" if model else ""
                await send_rich(
                    self._bot,
                    chat_id,
                    fmt(
                        f"**Session `{session_name}` started**",
                        SEP,
                        f"Running on {provider_label}{model_info}.\n"
                        f"Follow up: `@{session_name} <message>`",
                    ),
                    SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
                )
        except ValueError as exc:
            await send_rich(
                self._bot,
                chat_id,
                str(exc),
                SendRichOpts(reply_to_message_id=message.message_id, thread_id=thread_id),
            )

    async def _on_sessions(self, message: Message) -> None:
        """Handle /sessions: show session management UI."""
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        await handle_command(self._orch, self._bot, message)

    async def _on_tasks(self, message: Message) -> None:
        """Handle /tasks: show background task management UI."""
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        await handle_command(self._orch, self._bot, message)

    async def _on_restart(self, message: Message) -> None:
        if self._config.group_mention_only and not self._is_addressed(message):
            return
        from controlmesh.infra.restart import write_restart_sentinel

        chat_id = message.chat.id
        paths = self._orch.paths
        sentinel = paths.controlmesh_home / "restart-sentinel.json"
        await asyncio.to_thread(
            write_restart_sentinel, chat_id, t("startup.restart_default"), sentinel_path=sentinel
        )
        text = fmt(t("startup.restart_header"), SEP, t("startup.restart_body"))
        await send_rich(
            self._bot,
            message.chat.id,
            text,
            SendRichOpts(reply_to_message_id=message.message_id, thread_id=get_thread_id(message)),
        )
        marker = paths.controlmesh_home / "restart-requested"
        delegated = await asyncio.to_thread(request_restart, marker_path=marker)
        self._exit_code = EXIT_RESTART
        if not delegated:
            await self._dp.stop_polling()

    # -- Callbacks -------------------------------------------------------------

    async def _on_callback_query(self, callback: CallbackQuery) -> None:
        """Handle inline keyboard button presses.

        Welcome quick-start (``w:`` prefix), model selector (``ms:`` prefix),
        and generic button callbacks are each routed to their own handler.

        All orchestrator interactions acquire the per-chat lock to prevent
        race conditions with concurrent webhook wake dispatch or model switches.
        """
        from aiogram.types import InaccessibleMessage

        await callback.answer()
        data = callback.data
        msg = callback.message
        if not data or msg is None or isinstance(msg, InaccessibleMessage):
            return

        chat_id = msg.chat.id
        key = get_session_key(msg)
        thread_id = get_thread_id(msg)
        set_log_context(operation="cb", chat_id=chat_id)
        logger.info("Callback data=%s", data[:40])

        # Resolve display label before data gets rewritten
        display_label: str = data
        if is_welcome_callback(data):
            display_label = get_welcome_button_label(data) or data
            resolved = resolve_welcome_callback(data)
            if not resolved:
                return
            data = resolved

        if await self._route_special_callback(key, msg.message_id, data, thread_id=thread_id):
            return

        await self._mark_button_choice(chat_id, msg, display_label)

        async with self._sequential.get_lock(key.lock_key):
            if self._use_streaming_output():
                await self._handle_streaming(msg, key, data, thread_id=thread_id)
            else:
                await self._handle_non_streaming(msg, key, data, thread_id=thread_id)

    async def _route_special_callback(
        self, key: SessionKey, message_id: int, data: str, *, thread_id: int | None = None
    ) -> bool:
        """Handle known callback namespaces. Returns True when handled."""
        if await self._route_prefix_callback(key, message_id, data, thread_id=thread_id):
            return True

        from controlmesh.orchestrator.selectors.model_selector import is_model_selector_callback

        if is_model_selector_callback(data):
            await self._handle_model_selector(key, message_id, data)
            return True

        from controlmesh.orchestrator.selectors.cron_selector import is_cron_selector_callback

        if is_cron_selector_callback(data):
            await self._handle_cron_selector(key.chat_id, message_id, data)
            return True

        from controlmesh.orchestrator.selectors.settings_selector import (
            is_settings_selector_callback,
        )

        if is_settings_selector_callback(data):
            await self._handle_settings_selector(key.chat_id, message_id, data)
            return True

        if is_file_browser_callback(data):
            await self._handle_file_browser(key, message_id, data, thread_id=thread_id)
            return True

        return False

    async def _route_prefix_callback(
        self, key: SessionKey, message_id: int, data: str, *, thread_id: int | None = None
    ) -> bool:
        """Handle prefix-based callback namespaces. Returns True when handled."""
        chat_id = key.chat_id
        if data.startswith(MQ_PREFIX):
            await self._handle_queue_cancel(chat_id, data)
            return True

        if data.startswith("upg:"):
            await self._handle_upgrade_callback(chat_id, message_id, data, thread_id=thread_id)
            return True

        from controlmesh.orchestrator.selectors.session_selector import is_session_selector_callback
        from controlmesh.orchestrator.selectors.task_selector import is_task_selector_callback

        if is_session_selector_callback(data):
            await self._handle_session_selector(chat_id, message_id, data)
            return True

        if is_task_selector_callback(data):
            await self._handle_task_selector(chat_id, message_id, data)
            return True

        if data.startswith("ns:"):
            await self._handle_ns_callback(key, data, thread_id=thread_id)
            return True

        return False

    async def _handle_model_selector(self, key: SessionKey, message_id: int, data: str) -> None:
        """Handle model selector wizard by editing the message in-place."""
        from controlmesh.orchestrator.selectors.model_selector import handle_model_callback

        async with self._sequential.get_lock(key.lock_key):
            await self._supersede_lane_by_key(key, reason="model_selector")
            resp = await handle_model_callback(self._orch, key, data)
        await edit_selector_response(self._bot, key.chat_id, message_id, resp)

    async def _handle_cron_selector(self, chat_id: int, message_id: int, data: str) -> None:
        """Handle cron selector wizard by editing the message in-place."""
        from controlmesh.orchestrator.selectors.cron_selector import handle_cron_callback

        async with self._sequential.get_lock(chat_id):
            resp = await handle_cron_callback(self._orch, data)
        await edit_selector_response(self._bot, chat_id, message_id, resp)

    async def _handle_settings_selector(self, chat_id: int, message_id: int, data: str) -> None:
        """Handle settings selector wizard by editing the message in-place."""
        from controlmesh.orchestrator.selectors.settings_selector import handle_settings_callback

        async with self._sequential.get_lock(chat_id):
            resp = await handle_settings_callback(self._orch, data)
        await edit_selector_response(self._bot, chat_id, message_id, resp)

    async def _handle_session_selector(self, chat_id: int, message_id: int, data: str) -> None:
        """Handle session selector wizard by editing the message in-place."""
        from controlmesh.orchestrator.selectors.session_selector import handle_session_callback

        async with self._sequential.get_lock(chat_id):
            resp = await handle_session_callback(self._orch, chat_id, data)
        await edit_selector_response(self._bot, chat_id, message_id, resp)

    async def _handle_task_selector(self, chat_id: int, message_id: int, data: str) -> None:
        """Handle task selector wizard by editing the message in-place."""
        from controlmesh.orchestrator.selectors.task_selector import handle_task_callback

        hub = self._orch.task_hub
        if hub is None:
            return
        resp = await handle_task_callback(hub, chat_id, data)
        await edit_selector_response(self._bot, chat_id, message_id, resp)

    async def _handle_ns_callback(
        self, key: SessionKey, data: str, *, thread_id: int | None = None
    ) -> None:
        """Handle ``ns:<session_name>:<label>`` button callbacks from session results."""
        parsed = parse_ns_callback(data)
        if parsed is None:
            return
        session_name, label = parsed

        async with self._sequential.get_lock(key.lock_key):
            if self._use_streaming_output():
                from controlmesh.orchestrator.flows import named_session_streaming

                result = await named_session_streaming(self._orch, key, session_name, label)
            else:
                from controlmesh.orchestrator.flows import named_session_flow

                result = await named_session_flow(self._orch, key, session_name, label)

            if result.text:
                await send_rich(
                    self._bot,
                    key.chat_id,
                    result.text,
                    SendRichOpts(
                        allowed_roots=self.file_roots(self._orch.paths),
                        thread_id=thread_id,
                    ),
                )

    async def _handle_file_browser(
        self, key: SessionKey, message_id: int, data: str, *, thread_id: int | None = None
    ) -> None:
        """Handle file browser navigation or file request."""
        chat_id = key.chat_id
        text, keyboard, prompt = await handle_file_browser_callback(self._orch.paths, data)

        if prompt:
            # File request: remove the keyboard and send prompt to orchestrator
            with contextlib.suppress(TelegramBadRequest):
                await self._bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=message_id, reply_markup=None
                )
            async with self._sequential.get_lock(key.lock_key):
                if self._use_streaming_output():
                    fake_msg = await self._bot.send_message(
                        chat_id,
                        prompt,
                        parse_mode=None,
                        message_thread_id=thread_id,
                    )
                    await self._handle_streaming(fake_msg, key, prompt, thread_id=thread_id)
                else:
                    await self._handle_non_streaming(None, key, prompt, thread_id=thread_id)
            return

        # Directory navigation: edit message in-place
        with contextlib.suppress(TelegramBadRequest):
            await self._bot.edit_message_text(
                text=markdown_to_telegram_html(text),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )

    async def _handle_queue_cancel(self, chat_id: int, data: str) -> None:
        """Handle a ``mq:<entry_id>`` callback to cancel a queued message."""
        try:
            entry_id = int(data[len(MQ_PREFIX) :])
        except (ValueError, IndexError):
            return
        await self._sequential.cancel_entry(chat_id, entry_id)

    async def _mark_button_choice(self, chat_id: int, msg: Message, label: str) -> None:
        """Edit the bot message to append ``[USER ANSWER] label`` and remove the keyboard."""
        await mark_button_choice(self._bot, chat_id, msg, label)

    # -- Messages --------------------------------------------------------------

    async def _on_message(self, message: Message) -> None:
        if self._is_persisted_outbound_self_echo(message):
            logger.debug(
                "Telegram persisted self-echo suppressed chat_id=%s message_id=%s",
                message.chat.id,
                message.message_id,
            )
            self._persist_runtime_state()
            return
        if not self._groups_enabled and message.chat.type in ("group", "supergroup"):
            logger.info(
                "telegram drop: groups disabled chat_id=%s message_id=%s from_user=%s text_preview=%r",
                message.chat.id,
                message.message_id,
                getattr(getattr(message, "from_user", None), "id", None),
                _log_text_preview(message.text),
            )
            return
        raw_text = strip_mention(message.text or "", self._bot_username) if message.text else ""
        inbound_kind = classify_inbound_text(raw_text) if raw_text else "normal_chat"
        if inbound_kind == "control_command":
            self._bump_lane_generation_for_message(message, reason="control_command")
            await self._on_command(message)
            return
        text = await self._resolve_text(message)
        if text is None:
            return

        key = get_session_key(message)
        thread_id = get_thread_id(message)
        logger.debug("Message text=%s", text[:80])

        if self._config.scene.seen_reaction:
            await self._set_seen_reaction(message)
        if self._inbound_spool is None:
            generation = self._update_lane_latest_for_message(message, spool_id=None)
            self._enqueue_frontstage_run(
                message,
                key,
                text,
                thread_id=thread_id,
                lane_key=self._message_lane_key(message),
                input_message_id=message.message_id,
                input_spool_id=None,
                generation=generation,
            )
            return
        if inbound_kind == "quarantine":
            entry = self._inbound_spool.enqueue(
                [
                    message.model_dump(
                        mode="python",
                        exclude_none=True,
                        exclude={"link_preview_options"},
                    )
                ]
            )
            if entry:
                pending = self._inbound_spool.find_pending(message.chat.id, message.message_id)
                if pending is not None:
                    self._inbound_spool.quarantine(pending, reason="suspicious_input")
            return
        enqueued = self._inbound_spool.enqueue(
            [
                message.model_dump(
                    mode="python",
                    exclude_none=True,
                    exclude={"link_preview_options"},
                )
            ]
        )
        pending_entry = self._inbound_spool.find_pending(message.chat.id, message.message_id)
        if pending_entry is not None:
            generation = self._update_lane_latest_for_message(message, spool_id=pending_entry.spool_id)
            if generation != pending_entry.generation:
                # lane_state is the source of truth; spool generation is advisory only
                pass
        self._last_inbound_spool_stats = self._inbound_spool.stats()
        if enqueued:
            logger.debug(
                "Telegram inbound spool enqueued chat_id=%s message_id=%s pending=%s blocked_lanes=%s",
                message.chat.id,
                message.message_id,
                self._last_inbound_spool_stats.pending_count,
                self._last_inbound_spool_stats.blocked_lane_count,
            )
        await self._drain_inbound_spool()

    def _enqueue_frontstage_run(
        self,
        message: Message,
        key: SessionKey,
        text: str,
        *,
        thread_id: int | None = None,
        claim: TelegramInboundClaim | None = None,
        lane_key: str = "",
        input_message_id: int = 0,
        input_spool_id: str | None = None,
        generation: int = 0,
    ) -> None:
        """Detach one incoming frontstage turn from the transport handler lifetime."""
        lock_key = key.lock_key
        queue = self._frontstage_run_queues.setdefault(lock_key, deque())
        queue.append(
            _QueuedMessageRun(
                message=message,
                key=key,
                text=text,
                thread_id=thread_id,
                claim=claim,
                lane_key=lane_key,
                input_message_id=input_message_id,
                input_spool_id=input_spool_id,
                generation=generation,
            )
        )
        loop_task = self._frontstage_run_loops.get(lock_key)
        if loop_task is None or loop_task.done():
            self._frontstage_run_loops[lock_key] = asyncio.create_task(
                self._run_frontstage_queue(lock_key),
                name=f"tg-frontstage:{key.chat_id}:{key.topic_id or 0}",
            )

    async def _run_frontstage_queue(self, lock_key: tuple[int, int | None]) -> None:
        """Drain one session-scoped Telegram run queue in the background."""
        try:
            while True:
                queue = self._frontstage_run_queues.get(lock_key)
                if not queue:
                    return
                item = queue.popleft()
                if not queue:
                    self._frontstage_run_queues.pop(lock_key, None)
                renew_task: asyncio.Task[None] | None = None

                async with self._sequential.get_lock(lock_key):
                    try:
                        if not await self._freshness_guard(
                            item.lane_key,
                            item.input_message_id,
                            item.generation,
                        ):
                            if item.claim is not None and self._inbound_spool is not None:
                                self._inbound_spool.supersede(item.claim, reason="stale_before_run")
                            continue
                        claim = item.claim
                        renew_task = (
                            asyncio.create_task(
                                self._keep_inbound_claim_alive(claim),
                                name=f"tg-spool-lease:{item.key.chat_id}:{item.key.topic_id or 0}",
                            )
                            if claim is not None
                            else None
                        )
                        if self._use_streaming_output():
                            await self._handle_streaming(
                                item.message,
                                item.key,
                                item.text,
                                thread_id=item.thread_id,
                                lane_key=item.lane_key,
                                input_message_id=item.input_message_id,
                                generation=item.generation,
                            )
                        else:
                            await self._handle_non_streaming(
                                item.message,
                                item.key,
                                item.text,
                                thread_id=item.thread_id,
                                lane_key=item.lane_key,
                                input_message_id=item.input_message_id,
                                generation=item.generation,
                            )
                        if claim is not None and self._inbound_spool is not None:
                            self._inbound_spool.ack(claim)
                            self._last_inbound_drain_at = time.time()
                            self._persist_runtime_state()
                    except (TelegramRetryAfter, TelegramNetworkError, TelegramServerError):
                        if item.claim is not None and self._inbound_spool is not None:
                            self._inbound_spool.retry_later(item.claim, reason="transient_telegram_error")
                        logger.exception(
                            "Detached Telegram frontstage transient failure chat_id=%s topic_id=%s",
                            item.key.chat_id,
                            item.key.topic_id,
                        )
                    except (TelegramForbiddenError, TelegramBadRequest):
                        if item.claim is not None and self._inbound_spool is not None:
                            self._inbound_spool.dead_letter(item.claim, reason="unrunnable_or_rejected")
                        logger.exception(
                            "Detached Telegram frontstage unrecoverable delivery failure chat_id=%s topic_id=%s",
                            item.key.chat_id,
                            item.key.topic_id,
                        )
                    except Exception:
                        if item.claim is not None and self._inbound_spool is not None:
                            self._inbound_spool.release(item.claim)
                        logger.exception(
                            "Detached Telegram frontstage run failed chat_id=%s topic_id=%s",
                            item.key.chat_id,
                            item.key.topic_id,
                        )
                    finally:
                        if renew_task is not None:
                            renew_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await renew_task
        finally:
            current = self._frontstage_run_loops.get(lock_key)
            if current is asyncio.current_task():
                self._frontstage_run_loops.pop(lock_key, None)

    async def _set_seen_reaction(self, message: Message) -> None:
        """Set a seen reaction on the user message. Graceful degradation on failure."""
        try:
            from aiogram.types import ReactionTypeEmoji

            await self._bot.set_message_reaction(
                chat_id=message.chat.id,
                message_id=message.message_id,
                reaction=[ReactionTypeEmoji(emoji="\U0001f440")],
            )
        except Exception:
            logger.debug("Failed to set seen reaction", exc_info=True)

    async def _resolve_text(self, message: Message) -> str | None:
        """Extract processable text from *message* (plain text or media prompt)."""
        is_group = message.chat.type in ("group", "supergroup")
        if is_group and not self._groups_enabled:
            logger.info(
                "telegram drop: groups disabled chat_id=%s message_id=%s from_user=%s text_preview=%r content_type=%s",
                message.chat.id,
                message.message_id,
                getattr(getattr(message, "from_user", None), "id", None),
                _log_text_preview(message.text),
                getattr(message, "content_type", None),
            )
            return None

        if has_media(message):
            if is_group and (
                self._is_for_others(message)
                or (
                    self._config.group_mention_only
                    and not is_media_addressed(message, self._bot_id, self._bot_username)
                )
            ):
                logger.info(
                    "telegram drop: media not addressed chat_id=%s message_id=%s from_user=%s content_type=%s",
                    message.chat.id,
                    message.message_id,
                    getattr(getattr(message, "from_user", None), "id", None),
                    getattr(message, "content_type", None),
                )
                return None
            paths = self._orch.paths
            return await resolve_media_text(
                self._bot, message, paths.telegram_files_dir, paths.workspace
            )
        if not message.text:
            logger.info(
                "telegram drop: no message.text chat_id=%s message_id=%s from_user=%s content_type=%s",
                message.chat.id,
                message.message_id,
                getattr(getattr(message, "from_user", None), "id", None),
                getattr(message, "content_type", None),
            )
            return None
        if is_group:
            if self._is_for_others(message):
                logger.info(
                    "telegram drop: command for other bot chat_id=%s message_id=%s from_user=%s text_preview=%r entities=%r",
                    message.chat.id,
                    message.message_id,
                    getattr(getattr(message, "from_user", None), "id", None),
                    _log_text_preview(message.text),
                    getattr(message, "entities", None),
                )
                return None
            if self._config.group_mention_only and not self._is_addressed(message):
                logger.info(
                    "telegram drop: group_mention_only not addressed chat_id=%s message_id=%s from_user=%s text_preview=%r entities=%r",
                    message.chat.id,
                    message.message_id,
                    getattr(getattr(message, "from_user", None), "id", None),
                    _log_text_preview(message.text),
                    getattr(message, "entities", None),
                )
                return None
        text = strip_mention(message.text, self._bot_username)
        inbound_kind = classify_inbound_text(text)
        transcript_message = extract_pasted_chat_transcript_message(text)
        if inbound_kind == "pasted_transcript_extractable" and transcript_message is not None:
            logger.warning(
                "Telegram pasted transcript reduced chat=%s message_id=%s from_user=%s",
                message.chat.id,
                message.message_id,
                getattr(getattr(message, "from_user", None), "id", None),
            )
            text = transcript_message
        patterns = detect_suspicious_patterns(text)
        if "raw_agent_event_stream" in patterns:
            via_bot = getattr(message, "via_bot", None)
            forward_origin = getattr(message, "forward_origin", None)
            sender_chat = getattr(message, "sender_chat", None)
            reply_to = getattr(message, "reply_to_message", None)
            logger.warning(
                "Telegram raw agent event stream received chat=%s message_id=%s from_user=%s via_bot=%s sender_chat=%s forward_origin=%s reply_to=%s",
                message.chat.id,
                message.message_id,
                getattr(getattr(message, "from_user", None), "id", None),
                getattr(via_bot, "username", None) or getattr(via_bot, "id", None),
                getattr(sender_chat, "id", None),
                type(forward_origin).__name__ if forward_origin is not None else None,
                getattr(reply_to, "message_id", None),
            )
            return None
        if inbound_kind == "quarantine":
            logger.warning(
                "telegram drop: inbound quarantine chat_id=%s message_id=%s from_user=%s patterns=%s",
                message.chat.id,
                message.message_id,
                getattr(getattr(message, "from_user", None), "id", None),
                ", ".join(patterns) if patterns else "none",
            )
            return None
        return text

    def _use_streaming_output(self) -> bool:
        """Return True when Telegram should emit incremental streaming output."""
        return self._config.streaming.enabled and self._config.streaming.output_mode != "off"

    async def _handle_streaming(
        self,
        message: Message,
        key: SessionKey,
        text: str,
        *,
        thread_id: int | None = None,
        lane_key: str = "",
        input_message_id: int = 0,
        generation: int = 0,
    ) -> None:
        """Streaming flow: coalescer -> stream editor -> Telegram."""
        await run_streaming_message(
            StreamingDispatch(
                bot=self._bot,
                orchestrator=self._orch,
                message=message,
                key=key,
                text=text,
                streaming_cfg=self._config.streaming,
                allowed_roots=self.file_roots(self._orch.paths),
                thread_id=thread_id,
                scene_config=self._config.scene,
                before_send=lambda: self._freshness_guard(lane_key, input_message_id, generation),
                before_critical_send=lambda: self._freshness_guard(
                    lane_key,
                    input_message_id,
                    generation,
                    freshness_bypass=True,
                ),
            ),
        )

    async def _handle_non_streaming(
        self,
        reply_to: Message | None,
        key: SessionKey,
        text: str,
        *,
        thread_id: int | None = None,
        lane_key: str = "",
        input_message_id: int = 0,
        generation: int = 0,
    ) -> None:
        """Non-streaming flow: one-shot orchestrator call -> Telegram delivery."""
        await run_non_streaming_message(
            NonStreamingDispatch(
                bot=self._bot,
                orchestrator=self._orch,
                key=key,
                text=text,
                allowed_roots=self.file_roots(self._orch.paths),
                reply_to=reply_to,
                thread_id=thread_id,
                scene_config=self._config.scene,
                before_send=lambda: self._freshness_guard(lane_key, input_message_id, generation),
                before_critical_send=lambda: self._freshness_guard(
                    lane_key,
                    input_message_id,
                    generation,
                    freshness_bypass=True,
                ),
            ),
        )

    # -- Background handlers ---------------------------------------------------

    async def on_async_interagent_result(self, result: AsyncInterAgentResult) -> None:
        """Handle async inter-agent result via the message bus."""
        from controlmesh.bus.adapters import from_interagent_result

        # Prefer the originating chat context carried by the result;
        # fall back to the sender agent's default DM.
        chat_id = result.chat_id or (
            self._config.allowed_user_ids[0] if self._config.allowed_user_ids else 0
        )
        if not chat_id:
            logger.warning("No chat_id available for async interagent result delivery")
            return
        set_log_context(operation="ia-async", chat_id=chat_id)
        await self._bus.submit(from_interagent_result(result, chat_id))

    async def on_task_result(self, result: TaskResult) -> None:
        """Handle background task result via the message bus."""
        from controlmesh.bus.adapters import from_task_result

        chat_id = result.chat_id
        if not chat_id:
            chat_id = self._config.allowed_user_ids[0] if self._config.allowed_user_ids else 0
        if not chat_id:
            logger.warning("No chat_id for task result delivery (task=%s)", result.task_id)
            return
        set_log_context(operation="task", chat_id=chat_id)
        await self._bus.submit(from_task_result(result))

    async def on_task_question(
        self,
        task_id: str,
        question: str,
        prompt_preview: str,
        chat_id: int,
        thread_id: int | None = None,
    ) -> None:
        """Deliver a background task question via the message bus."""
        from controlmesh.bus.adapters import from_task_question

        if not chat_id:
            chat_id = self._config.allowed_user_ids[0] if self._config.allowed_user_ids else 0
        if not chat_id:
            logger.warning("No chat_id for task question delivery (task=%s)", task_id)
            return
        set_log_context(operation="task", chat_id=chat_id)
        await self._bus.submit(
            from_task_question(task_id, question, prompt_preview, chat_id, topic_id=thread_id)
        )

    async def _handle_webhook_wake(self, chat_id: int, prompt: str) -> str | None:
        """Process webhook wake prompt via the message bus."""
        from controlmesh.bus.envelope import LockMode

        set_log_context(operation="wh", chat_id=chat_id)
        key = SessionKey(chat_id=chat_id)
        lock = self._lock_pool.get(key.lock_key)
        async with lock:
            result = await self._orch.handle_message(key, prompt)

        # Deliver result — lock already released, skip bus lock
        from controlmesh.bus.adapters import from_webhook_wake

        env = from_webhook_wake(chat_id, prompt)
        env.result_text = result.text
        env.lock_mode = LockMode.NONE  # Lock already held above
        await self._bus.submit(env)
        return result.text

    # -- Update notifications --------------------------------------------------

    async def _on_update_available(self, info: VersionInfo) -> None:
        """Notify all users about a new version via Telegram."""
        from controlmesh.messenger.telegram.upgrade_handler import on_update_available

        await on_update_available(self, info)

    async def _handle_upgrade_callback(
        self, chat_id: int, message_id: int, data: str, *, thread_id: int | None = None
    ) -> None:
        """Handle ``upg:yes:<version>``, ``upg:no``, and ``upg:cl:<version>`` callbacks."""
        from controlmesh.messenger.telegram.upgrade_handler import handle_upgrade_callback

        fake_message = Message.model_validate(
            {
                "message_id": message_id,
                "date": int(time.time()),
                "chat": {"id": chat_id, "type": "private"},
                "text": "/upgrade",
                "message_thread_id": thread_id,
            }
        )
        await self._supersede_lane_runtime(fake_message, reason="upgrade_restart")
        await handle_upgrade_callback(self, chat_id, message_id, data, thread_id=thread_id)

    async def _sync_commands(self) -> None:
        from aiogram.types import (
            BotCommandScopeAllGroupChats,
            BotCommandScopeAllPrivateChats,
            BotCommandScopeChat,
        )

        desired = _bot_commands_for_agent(self._agent_name)

        # Clear legacy scoped commands (previous versions set per-scope lists).
        # Telegram keeps scoped commands independently — they must be deleted
        # explicitly or they shadow the default-scope list.
        scoped_chat_ids = list(
            dict.fromkeys([*self._config.allowed_user_ids, *self._config.allowed_group_ids]),
        )
        scopes: list[
            BotCommandScopeAllPrivateChats | BotCommandScopeAllGroupChats | BotCommandScopeChat
        ] = [
            BotCommandScopeAllPrivateChats(),
            BotCommandScopeAllGroupChats(),
            *(BotCommandScopeChat(chat_id=chat_id) for chat_id in scoped_chat_ids),
        ]
        for scope in scopes:
            try:
                scoped = await self._bot.get_my_commands(scope=scope)
                if scoped:
                    await self._bot.delete_my_commands(scope=scope)
                    logger.info("Cleared legacy %s commands", type(scope).__name__)
            except TelegramAPIError:
                pass  # scope not set — nothing to clear

        # Set default-scope commands (shown everywhere).
        # Compare as ordered list so reordering triggers an update.
        current = await self._bot.get_my_commands()
        current_tuples = [(c.command, c.description) for c in current]
        desired_tuples = [(c.command, c.description) for c in desired]
        if current_tuples != desired_tuples:
            await self._bot.set_my_commands(desired)
            logger.info("Updated %d bot commands", len(desired))

    async def _watch_restart_marker(self) -> None:
        """Poll for restart-requested marker file."""
        paths = self._orch.paths
        marker = paths.controlmesh_home / "restart-requested"
        try:
            while True:
                await asyncio.sleep(2.0)
                restart_meta = await asyncio.to_thread(consume_restart_marker, marker_path=marker)
                if restart_meta:
                    logger.info(
                        "Restart marker detected source=%s requested_at=%s, stopping polling",
                        restart_meta.get("source", "unknown"),
                        restart_meta.get("requested_at", ""),
                    )
                    self._exit_code = EXIT_RESTART
                    await self._dp.stop_polling()
        except asyncio.CancelledError:
            logger.debug("Restart watcher cancelled")

    async def _watch_poll_health(self) -> None:
        """Request a fresh Telegram polling transport when getUpdates stalls."""
        next_backlog_log = 0.0
        try:
            while True:
                await asyncio.sleep(1.0)
                snapshot = self._last_inbound_spool_stats
                if (
                    self._inbound_spool is not None
                    and snapshot is not None
                    and (snapshot.pending_count or snapshot.blocked_lane_count)
                    and time.monotonic() >= next_backlog_log
                ):
                    live = self._inbound_spool.stats()
                    if live.pending_count or live.blocked_lane_count:
                        oldest_age = (
                            f"{live.oldest_pending_age_seconds:.0f}"
                            if live.oldest_pending_age_seconds is not None
                            else "n/a"
                        )
                        logger.info(
                            "Telegram inbound backlog pending=%s blocked_lanes=%s oldest_age=%ss unhealthy=%s",
                            live.pending_count,
                            live.blocked_lane_count,
                            oldest_age,
                            live.unhealthy_reason or "no",
                        )
                    next_backlog_log = time.monotonic() + 60.0
                if self._exit_code == EXIT_RESTART or self._poll_diagnostics.transport_dirty:
                    continue
                inflight_age = self._poll_diagnostics.poll_inflight_age_seconds()
                if inflight_age is None or inflight_age <= self._poll_stall_timeout_seconds:
                    continue
                offset = self._current_poll_offset()
                self._poll_diagnostics.note_poll_failed(
                    reason="poll_stall",
                    offset=offset,
                    mark_transport_dirty=True,
                )
                logger.warning(
                    "Telegram poll marked transport dirty reason=%s offset=%s last_success_age=%s failures=%s inflight_age=%ss",
                    "poll_stall",
                    offset,
                    self._format_last_success_age(),
                    self._poll_diagnostics.consecutive_failures,
                    f"{inflight_age:.2f}",
                )
                await self._request_poll_restart("poll_stall")
        except asyncio.CancelledError:
            logger.debug("Telegram poll watchdog cancelled")

    async def run(self) -> int:
        """Start polling. Returns exit code (0 = normal, 42 = restart)."""
        logger.info("Starting Telegram bot (aiogram, long-polling)...")
        await self._bot.delete_webhook(drop_pending_updates=False)
        allowed_updates = self._dp.resolve_used_update_types()
        logger.info("Polling allowed_updates=%s", ",".join(allowed_updates))
        while True:
            start_polling_error = False
            try:
                await self._dp.start_polling(
                    self._bot,
                    allowed_updates=allowed_updates,
                    close_bot_session=True,
                    handle_signals=False,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                start_polling_error = True
                raise
            finally:
                if (
                    not start_polling_error
                    and self._exit_code != EXIT_RESTART
                    and self._poll_diagnostics.transport_dirty
                    and not self._poll_diagnostics.restart_requested
                ):
                    self._poll_diagnostics.restart_requested = True
                    logger.warning(
                        "Telegram polling stopped while transport was dirty; forcing transport rebuild reason=%s offset=%s last_success_age=%s failures=%s",
                        self._poll_diagnostics.restart_reason or "dirty_transport",
                        self._current_poll_offset(),
                        self._format_last_success_age(),
                        self._poll_diagnostics.consecutive_failures,
                    )
            if self._exit_code == EXIT_RESTART or not self._poll_diagnostics.transport_dirty:
                break
            backoff = self._compute_poll_restart_backoff_seconds()
            if backoff > 0:
                logger.info(
                    "Telegram backing off %.1fs before poll restart reason=%s failures=%s retry_after=%.1fs",
                    backoff,
                    self._poll_diagnostics.restart_reason or "dirty_transport",
                    self._poll_diagnostics.consecutive_failures,
                    float(self._poll_diagnostics.last_retry_after_seconds or 0.0),
                )
                await asyncio.sleep(backoff)
            await self._rebuild_poll_transport()
        return self._exit_code

    def _compute_poll_restart_backoff_seconds(self) -> float:
        """Honor Telegram 429 retry_after and add exponential backoff on failures.

        Without this, a burst of transient network errors makes controlmesh
        rebuild the transport and immediately re-issue getUpdates, which trips
        Telegram's getUpdates flood control (429) and locks inbound delivery
        out for an escalating window -- every chat stops receiving replies
        while the process stays alive.
        """
        return _poll_restart_backoff_seconds(
            consecutive_failures=self._poll_diagnostics.consecutive_failures,
            retry_after_seconds=self._poll_diagnostics.last_retry_after_seconds,
        )

    async def shutdown(self) -> None:
        await _cancel_task(self._restart_watcher)
        await _cancel_task(self._poll_watchdog)
        await _cancel_task(self._group_audit_task)
        for task in list(self._frontstage_run_loops.values()):
            await _cancel_task(task)
        self._frontstage_run_loops.clear()
        self._frontstage_run_queues.clear()
        if self._update_observer:
            await self._update_observer.stop()
        if self._orchestrator:
            await self._orchestrator.shutdown()

        # Release the Telegram polling session so a new bot instance can start.
        # Without this, Telegram rejects the next getUpdates call with
        # TelegramConflictError ("terminated by other getUpdates request").
        with contextlib.suppress(Exception):
            await self._dp.stop_polling()
        with contextlib.suppress(Exception):
            await self._bot.delete_webhook(drop_pending_updates=False)
        with contextlib.suppress(Exception):
            await self._bot.session.close()

        logger.info("Telegram bot shut down")

    def _install_polling_session(self) -> None:
        raw_session = getattr(self._bot, "session", None)
        if not isinstance(raw_session, BaseSession):
            return
        self._bot.session = _TelegramPollingSession(
            raw_session,
            on_poll_started=self._note_poll_started,
            on_poll_succeeded=self._note_poll_succeeded,
            on_poll_failed=self._note_poll_failed,
        )

    def _compute_poll_stall_timeout_seconds(self) -> float:
        return max(self._poll_timeout_seconds + 15.0, self._poll_timeout_seconds * 1.25)

    def _note_poll_started(self, method: GetUpdates) -> None:
        if self._restored_poll_offset is not None and method.offset is None:
            method.offset = self._restored_poll_offset
        self._poll_diagnostics.note_poll_started(offset=method.offset)

    def _note_poll_succeeded(self, method: GetUpdates, result: object) -> None:
        update_ids = [update.update_id for update in result] if isinstance(result, list) else []
        next_offset = update_ids[-1] + 1 if update_ids else method.offset
        self._poll_diagnostics.note_poll_succeeded(offset=next_offset, update_ids=update_ids)
        if next_offset is not None:
            self._restored_poll_offset = next_offset
            self._persist_runtime_state()
        if self._inbound_spool is not None:
            self._last_inbound_spool_stats = self._inbound_spool.stats()
        if not update_ids:
            logger.debug(
                "Telegram poll success with no new updates offset=%s backlog_pending=%s blocked_lanes=%s recovered_stale_claims=%s unhealthy=%s last_success_age=%s",
                next_offset,
                self._last_inbound_spool_stats.pending_count,
                self._last_inbound_spool_stats.blocked_lane_count,
                self._last_recovered_stale_claim_count,
                self._last_inbound_spool_stats.unhealthy_reason,
                self._format_last_success_age(),
            )

    async def _note_poll_failed(self, method: GetUpdates, exc: Exception) -> None:
        reason = self._recoverable_poll_reason(exc)
        if reason is None:
            return
        retry_after = 0.0
        if isinstance(exc, TelegramRetryAfter):
            try:
                retry_after = float(getattr(exc, "retry_after", 0) or 0)
            except (TypeError, ValueError):
                retry_after = 0.0
        self._poll_diagnostics.note_poll_failed(
            reason=reason,
            offset=method.offset,
            mark_transport_dirty=True,
            retry_after_seconds=retry_after,
        )
        logger.warning(
            "Telegram poll marked transport dirty reason=%s offset=%s last_success_age=%s failures=%s",
            reason,
            method.offset,
            self._format_last_success_age(),
            self._poll_diagnostics.consecutive_failures,
            exc_info=exc,
        )
        await self._request_poll_restart(reason)

    async def _request_poll_restart(self, reason: str) -> None:
        if self._exit_code == EXIT_RESTART or self._poll_diagnostics.restart_requested:
            return
        self._poll_diagnostics.restart_requested = True
        logger.info(
            "Telegram rebuilding poll transport requested reason=%s offset=%s last_success_age=%s failures=%s",
            reason,
            self._current_poll_offset(),
            self._format_last_success_age(),
            self._poll_diagnostics.consecutive_failures,
        )
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._dp.stop_polling()

    async def _rebuild_poll_transport(self) -> None:
        reason = self._poll_diagnostics.restart_reason or "dirty_transport"
        logger.info(
            "Telegram rebuilding poll transport reason=%s offset=%s last_success_age=%s failures=%s",
            reason,
            self._current_poll_offset(),
            self._format_last_success_age(),
            self._poll_diagnostics.consecutive_failures,
        )
        with contextlib.suppress(Exception):
            await self._bot.session.close()
        if self._telegram_proxy:
            self._bot.session = AiohttpSession(proxy=self._telegram_proxy)
        else:
            self._bot.session = AiohttpSession()
        self._install_polling_session()
        self._poll_diagnostics.note_transport_rebuilt()

    def _recoverable_poll_reason(self, exc: Exception) -> str | None:
        if isinstance(exc, TelegramConflictError):
            return "poll_conflict_409"
        if isinstance(exc, TelegramNetworkError):
            return "recoverable_network_error"
        if isinstance(exc, TelegramRetryAfter):
            return "recoverable_http_429"
        if isinstance(exc, TelegramServerError):
            return "recoverable_http_5xx"
        return None

    def _current_poll_offset(self) -> int | None:
        return self._poll_diagnostics.last_poll_offset

    def _format_last_success_age(self) -> str:
        age = self._poll_diagnostics.last_success_age_seconds()
        if age is None:
            return "never"
        return f"{age:.2f}s"

    def _restore_runtime_state(self) -> None:
        pending_recent_outbound = self._recent_outbound.snapshot()
        state = self._runtime_state_store.load_state(
            token=self._config.telegram_token,
            bot_id=self._bot_id,
            bot_username=self._bot_username,
        )
        self._recent_outbound = TelegramOutboundEchoStore(state.recent_outbound)
        for message_key, seen_at in pending_recent_outbound:
            self._recent_outbound.remember(message_key, now=seen_at)
        self._restored_poll_offset = state.cursor
        self._poll_diagnostics.last_poll_offset = state.cursor

    def _configure_inbound_spool(self) -> None:
        self._inbound_spool = TelegramInboundSpool(
            self._config.controlmesh_home,
            token=self._config.telegram_token,
            bot_id=self._bot_id,
            bot_username=self._bot_username,
        )
        self._lane_state_store = TelegramLaneStateStore(
            self._config.controlmesh_home,
            token=self._config.telegram_token,
            bot_id=self._bot_id,
            bot_username=self._bot_username,
        )
        self._last_inbound_spool_stats = self._inbound_spool.stats()

    def _persist_runtime_state(self) -> None:
        self._runtime_state_store.save_state(
            token=self._config.telegram_token,
            bot_id=self._bot_id,
            bot_username=self._bot_username,
            state=TelegramRuntimeState(
                cursor=self._restored_poll_offset,
                recent_outbound=self._recent_outbound.snapshot(),
            ),
        )

    def _remember_outbound_message(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        self._recent_outbound.remember(build_outbound_message_key(chat_id, message_id))
        self._persist_runtime_state()

    def _is_persisted_outbound_self_echo(self, message: Message) -> bool:
        from_user = getattr(message, "from_user", None)
        if from_user is None or self._bot_id is None or getattr(from_user, "id", None) != self._bot_id:
            return False
        message_key = build_outbound_message_key(message.chat.id, message.message_id)
        return self._recent_outbound.consume(message_key)

    async def _recover_inbound_spool(self) -> None:
        if self._inbound_spool is None:
            return
        self._last_recovered_stale_claim_count = self._inbound_spool.recover_stale_claims()
        if self._last_recovered_stale_claim_count:
            logger.info(
                "Telegram recovered stale inbound claims count=%s",
                self._last_recovered_stale_claim_count,
            )
        for entry in list(self._inbound_spool._load_pending_entries()):
            kind = classify_inbound_text(str(entry.raw.get("text", "") or ""))
            if kind == "quarantine":
                self._inbound_spool.quarantine(entry, reason="startup_hygiene")
        await self._drain_inbound_spool()

    def _lane_state(self, lane_key: str) -> TelegramLaneStateStore:
        if self._lane_state_store is None:
            self._lane_state_store = TelegramLaneStateStore(
                self._config.controlmesh_home,
                token=self._config.telegram_token,
                bot_id=self._bot_id,
                bot_username=self._bot_username,
            )
        return self._lane_state_store

    def _lane_is_current(self, lane_key: str, message_id: int, generation: int) -> bool:
        if self._lane_state_store is None:
            return True
        return self._lane_state_store.is_current(lane_key, message_id, generation)

    def _message_lane_key(self, message: Message) -> str:
        thread_id = get_thread_id(message) or 0
        return f"{message.chat.id}:{thread_id}"

    def _bump_lane_generation_for_message(self, message: Message, *, reason: str) -> int:
        state = self._lane_state(self._message_lane_key(message)).bump_generation(
            self._message_lane_key(message),
            reason=reason,
        )
        return state.generation

    def _update_lane_latest_for_message(
        self,
        message: Message,
        *,
        spool_id: str | None,
    ) -> int:
        state = self._lane_state(self._message_lane_key(message)).update_latest(
            self._message_lane_key(message),
            message.message_id,
            spool_id,
        )
        return state.generation

    async def _supersede_lane_runtime(self, message: Message, *, reason: str) -> None:
        lane_key = self._message_lane_key(message)
        self._bump_lane_generation_for_message(message, reason=reason)
        if self._inbound_spool is not None:
            self._inbound_spool.clear_claim(lane_key)
            self._inbound_spool.supersede_lane(lane_key, reason=reason)
        queue = self._frontstage_run_queues.get((message.chat.id, get_thread_id(message)))
        if queue:
            queue.clear()

    async def _supersede_lane_by_key(self, key: SessionKey, *, reason: str) -> None:
        lane_key = f"{key.chat_id}:{key.topic_id or 0}"
        self._lane_state(lane_key).bump_generation(lane_key, reason=reason)
        if self._inbound_spool is not None:
            self._inbound_spool.clear_claim(lane_key)
            self._inbound_spool.supersede_lane(lane_key, reason=reason)
        queue = self._frontstage_run_queues.get(key.lock_key)
        if queue:
            queue.clear()

    def _is_control_command_text(self, text: str) -> bool:
        lowered = text.strip().lower()
        return lowered.startswith(_CONTROL_COMMAND_PREFIXES)

    async def _freshness_guard(
        self,
        lane_key: str,
        message_id: int,
        generation: int,
        *,
        freshness_bypass: bool = False,
    ) -> bool:
        if freshness_bypass:
            return True
        return self._lane_is_current(lane_key, message_id, generation)

    async def _drain_inbound_spool(self) -> int:
        if self._inbound_spool is None:
            return 0
        delivered = 0
        while True:
            claim = self._inbound_spool.claim_latest(owner=_INBOUND_DRAIN_OWNER)
            if claim is None:
                break
            try:
                message = Message.model_validate(claim.entry.raw)
            except Exception:
                self._inbound_spool.dead_letter(claim, reason="invalid_message_payload")
                continue
            if self._is_persisted_outbound_self_echo(message):
                self._inbound_spool.ack(claim)
                self._persist_runtime_state()
                continue
            text = await self._resolve_text(message)
            if text is None:
                self._inbound_spool.quarantine(claim, reason="non_runnable_input")
                continue
            key = get_session_key(message)
            thread_id = get_thread_id(message)
            generation = self._update_lane_latest_for_message(message, spool_id=claim.spool_id)
            self._enqueue_frontstage_run(
                message,
                key,
                text,
                thread_id=thread_id,
                claim=claim,
                lane_key=claim.entry.lane_key,
                input_message_id=message.message_id,
                input_spool_id=claim.spool_id,
                generation=generation,
            )
            delivered += 1
        self._last_inbound_spool_stats = self._inbound_spool.stats()
        if self._last_inbound_spool_stats.unhealthy_reason:
            logger.warning(
                "Telegram inbound backlog unhealthy reason=%s pending=%s blocked_lanes=%s recovered_stale_claims=%s",
                self._last_inbound_spool_stats.unhealthy_reason,
                self._last_inbound_spool_stats.pending_count,
                self._last_inbound_spool_stats.blocked_lane_count,
                self._last_recovered_stale_claim_count,
            )
        return delivered

    async def _keep_inbound_claim_alive(self, claim: TelegramInboundClaim) -> None:
        if self._inbound_spool is None:
            return
        current_claim = claim
        interval = max(1.0, self._inbound_spool.claim_ttl_seconds / 3.0)
        deadline = time.monotonic() + _MAX_CLAIM_LIFETIME_SECONDS
        while True:
            if time.monotonic() >= deadline:
                logger.warning(
                    "Telegram inbound claim exceeded max lifetime; letting lease expire "
                    "so the backlog can be reclaimed lane=%s chat_id=%s spool_id=%s",
                    claim.lane_key,
                    claim.entry.chat_id,
                    claim.spool_id,
                )
                return
            await asyncio.sleep(interval)
            renewed = self._inbound_spool.renew(current_claim)
            if renewed is None:
                return
            current_claim = renewed
