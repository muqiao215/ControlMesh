"""Feishu bot-only messenger skeleton."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp

from controlmesh.bus.bus import MessageBus
from controlmesh.bus.envelope import Envelope
from controlmesh.bus.lock_pool import LockPool
from controlmesh.cli.stream_events import ToolResultEvent, ToolUseEvent
from controlmesh.cli.types import AgentRequest
from controlmesh.config import AgentConfig
from controlmesh.files.allowed_roots import resolve_allowed_roots
from controlmesh.files.storage import sanitize_filename as _sanitize_filename
from controlmesh.files.tags import FILE_PATH_RE, extract_file_paths
from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.infra.restart import EXIT_RESTART
from controlmesh.infra.updater import perform_upgrade_pipeline, write_upgrade_sentinel
from controlmesh.infra.version import VersionInfo, check_latest_version, get_current_version
from controlmesh.log_context import set_log_context
from controlmesh.messenger.feishu.auth.card_auth_runner import FeishuCardAuthRunner
from controlmesh.messenger.feishu.auth.feishu_card_sender import (
    BotFeishuCardSender,
    FeishuCardHandle,
)
from controlmesh.messenger.feishu.auth.native_auth_all_runner import (
    FeishuNativeAuthAllRunner,
    is_native_auth_all_command,
)
from controlmesh.messenger.feishu.auth.native_auth_useful_runner import (
    FeishuNativeAuthUsefulRunner,
    is_native_auth_useful_command,
)
from controlmesh.messenger.feishu.auth.orchestration_runner import FeishuAuthOrchestrationRunner
from controlmesh.messenger.feishu.auth.runtime_auth import resolve_feishu_auth
from controlmesh.messenger.feishu.bundled_runtime import (
    BundledCodexRuntimeConfig,
    BundledFeishuRuntimeTurn,
    run_bundled_codex_turn,
)
from controlmesh.messenger.feishu.media import ResolveMediaRequest, is_supported_media_message_type
from controlmesh.messenger.feishu.media import resolve_media_text as _resolve_media_text
from controlmesh.messenger.feishu.media_meta import parse_mp4_duration, prepare_audio_upload
from controlmesh.messenger.feishu.message_context import (
    build_feishu_agent_input,
    extract_feishu_content_from_event,
)
from controlmesh.messenger.feishu.native_tools import (
    FeishuNativeToolExecutor,
    format_native_tool_result,
    parse_native_tool_command,
)
from controlmesh.messenger.feishu.native_tools.agent_runtime import (
    build_native_agent_tool_selection_prompt,
    build_tool_result_followup_prompt,
    parse_native_agent_tool_selection,
)
from controlmesh.messenger.feishu.settings_card import (
    ParsedSettingsCardAction,
    build_settings_card,
    parse_settings_card_action,
    resolve_initial_settings_tab,
)
from controlmesh.messenger.feishu.tool_auth import (
    FeishuNativeToolAuthContract,
    FeishuNativeToolAuthRequiredError,
    build_feishu_inbound_context,
)
from controlmesh.messenger.notifications import NotificationService
from controlmesh.messenger.telegram.dedup import DedupeCache
from controlmesh.orchestrator.selectors.settings_selector import handle_settings_callback
from controlmesh.session.key import SessionKey
from controlmesh.text.tool_event_format import format_tool_event_text
from controlmesh.workspace.paths import ControlMeshPaths

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.inbound import FeishuInboundServer
    from controlmesh.messenger.feishu.long_connection import FeishuLongConnectionClient
    from controlmesh.multiagent.bus import AsyncInterAgentResult
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.tasks.models import TaskResult

logger = logging.getLogger(__name__)
# Feishu long-connection retries can arrive minutes after the first delivery,
# especially while a turn is still blocked on model/tool work.
_FEISHU_DEDUP_TTL_SECONDS = 86400.0
_FEISHU_DEDUP_MAX_SIZE = 10000
_FEISHU_CONTENT_DEDUP_TTL_SECONDS = 300.0
_FEISHU_CONTENT_DEDUP_MAX_SIZE = 4000
_FEISHU_OLD_MESSAGE_GRACE_SECONDS = 2.0
_FEISHU_PROGRESS_ACK_DELAY_SECONDS = 1.5
_FEISHU_PROGRESS_MAX_MESSAGES = 8
_TextStreamCallback = Callable[[str], Awaitable[None]]
_StatusStreamCallback = Callable[[str | None], Awaitable[None]]
_ToolEventStreamCallback = Callable[[ToolUseEvent | ToolResultEvent], Awaitable[None]]
_FEISHU_COMMAND_GUIDE_VERSION = 1
_FEISHU_COMMAND_GUIDE_TEXT = (
    "ControlMesh 已接入。\n\n"
    "常用命令:\n"
    "/help — 查看命令\n"
    "/status — 查看当前状态\n"
    "/model — 切换模型\n"
    "/feishu_auth_all — 批量补齐飞书原生权限\n"
    "/feishu_auth_useful — 除黑名单外批量补齐应用已开放权限\n"
    "/claude_native on — 打开 Claude 原生命令模式\n"
    "/claude_native off — 关闭 Claude 原生命令模式\n"
    "/cm /status — 强制走 ControlMesh 命令\n\n"
    "不知道发什么时, 直接说需求也可以。"
)


def _stream_callbacks_for_output_mode(
    mode: str,
    *,
    on_text: _TextStreamCallback,
    on_tool: _TextStreamCallback | None,
    on_tool_event: _ToolEventStreamCallback | None,
    on_system: _StatusStreamCallback,
) -> tuple[
    _TextStreamCallback | None,
    _TextStreamCallback | None,
    _ToolEventStreamCallback | None,
    _StatusStreamCallback | None,
]:
    """Map output mode to Feishu streaming callbacks."""
    if mode == "full":
        return on_text, on_tool, on_tool_event, on_system
    if mode == "tools":
        return on_text, on_tool, on_tool_event, None
    if mode == "conversation":
        return on_text, None, None, None
    if mode == "off":
        return None, None, None, None
    return on_text, on_tool, on_tool_event, on_system


class _FeishuProgressReporter:
    """Emit lightweight progress messages for long-running Feishu turns."""

    _SYSTEM_LABELS: dict[str, str] = {
        "thinking": "处理中...",
        "compacting": "整理上下文后继续...",
        "recovering": "恢复会话后继续...",
        "timeout_warning": "处理时间较长, 继续执行中...",
        "timeout_extended": "已延长处理时间, 继续执行中...",
    }

    def __init__(
        self,
        bot: FeishuBot,
        *,
        chat_ref: str,
        reply_to_message_id: str | None,
    ) -> None:
        self._bot = bot
        self._chat_ref = chat_ref
        self._reply_to_message_id = reply_to_message_id
        self._sent_labels: set[str] = set()
        self._progress_count = 0
        self._delay_task: asyncio.Task[None] | None = None
        self.handles_final_response = False

    def start(self) -> None:
        self._delay_task = asyncio.create_task(self._send_delayed_ack())

    async def close(self) -> None:
        task = self._delay_task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def on_tool(self, tool_name: str) -> None:
        if not tool_name:
            return
        await self._emit(f"[TOOL: {tool_name}]")

    async def on_system(self, status: str | None) -> None:
        if status is None:
            return
        label = self._SYSTEM_LABELS.get(status)
        if label:
            await self._emit(label)

    async def on_text_delta(self, _text: str) -> None:
        return None

    async def finish_success(self, _text: str) -> None:
        return None

    async def finish_failure(self, _error_text: str) -> None:
        return None

    async def on_agent_event(self, _event: dict[str, Any]) -> None:
        return None

    async def finish_with_single_card_run(self, _run: dict[str, Any]) -> None:
        return None

    async def _send_delayed_ack(self) -> None:
        await asyncio.sleep(_FEISHU_PROGRESS_ACK_DELAY_SECONDS)
        await self._emit("处理中...")

    async def _emit(self, label: str) -> None:
        if not label or label in self._sent_labels:
            return
        if self._progress_count >= _FEISHU_PROGRESS_MAX_MESSAGES:
            return
        self._sent_labels.add(label)
        self._progress_count += 1
        await self._bot._send_text_to_chat_ref(
            self._chat_ref,
            label,
            reply_to_message_id=self._reply_to_message_id,
        )


@dataclass(slots=True)
class FeishuIncomingText:
    """Normalized Feishu text message event."""

    sender_id: str
    chat_id: str
    message_id: str
    text: str
    thread_id: str | None = None
    create_time_ms: int | None = None
    message_type: str = "text"
    root_id: str | None = None
    parent_id: str | None = None
    quote_summary: str | None = None
    post_title: str | None = None


class FeishuNotificationService:
    """NotificationService implementation for Feishu."""

    def __init__(self, bot: FeishuBot) -> None:
        self._bot = bot

    async def notify(self, chat_id: int, text: str) -> None:
        await self._bot.send_text(chat_id, text)

    async def notify_all(self, text: str) -> None:
        await self._bot.broadcast_text(text)


class FeishuBot:
    """Minimal Feishu bot-only runtime for config/startup/plumbing cut 1."""

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
        self._tenant_access_token: str = ""
        self._tenant_access_token_expiry: float = 0.0
        self._process_start_time = time.time()
        self._shutdown_started = False
        self._exit_code = 0
        self._upgrade_lock = asyncio.Lock()
        self._upgrade_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._paths = ControlMeshPaths(Path(config.controlmesh_home).expanduser())
        self._dedup = DedupeCache(
            ttl_seconds=_FEISHU_DEDUP_TTL_SECONDS,
            max_size=_FEISHU_DEDUP_MAX_SIZE,
        )
        self._recent_content_dedup = DedupeCache(
            ttl_seconds=_FEISHU_CONTENT_DEDUP_TTL_SECONDS,
            max_size=_FEISHU_CONTENT_DEDUP_MAX_SIZE,
        )
        self._inflight_content_keys: set[str] = set()

        store_path = Path(config.controlmesh_home).expanduser() / "feishu_store"
        store_path.mkdir(parents=True, exist_ok=True)

        from controlmesh.messenger.feishu.id_map import FeishuIdMap
        from controlmesh.messenger.feishu.transport import FeishuTransport

        self._id_map = FeishuIdMap(store_path)
        self._inbound_server: FeishuInboundServer | None = None
        self._long_connection: FeishuLongConnectionClient | None = None
        self._card_auth_runner: FeishuCardAuthRunner | None = None
        self._auth_orchestration_runner: FeishuAuthOrchestrationRunner | None = None
        self._native_auth_all_runner: FeishuNativeAuthAllRunner | None = None
        self._native_auth_useful_runner: FeishuNativeAuthUsefulRunner | None = None
        self._native_tool_executor: FeishuNativeToolExecutor | None = None
        self._notification_service: NotificationService = FeishuNotificationService(self)
        self._bus.register_transport(FeishuTransport(self))
        self._command_guide_path = store_path / "command_guide_sent.json"

    @property
    def _orch(self) -> Orchestrator:
        if self._orchestrator is None:
            msg = "Orchestrator not initialized -- call after startup"
            raise RuntimeError(msg)
        return self._orchestrator

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

    async def start_inbound_listener(self) -> None:
        if self._inbound_server is None:
            from controlmesh.messenger.feishu.inbound import FeishuInboundServer

            self._inbound_server = FeishuInboundServer(self._config.feishu, self.handle_incoming_event)
        await self._inbound_server.start()

    async def start_long_connection(self) -> bool:
        if self._long_connection is None:
            from controlmesh.messenger.feishu.long_connection import FeishuLongConnectionClient

            self._long_connection = FeishuLongConnectionClient(
                self._config.feishu,
                self.handle_incoming_event,
            )
        return await self._long_connection.start()

    async def run(self) -> int:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

        from controlmesh.messenger.feishu.startup import run_feishu_startup

        try:
            await run_feishu_startup(self)
            await self._stop_event.wait()
        finally:
            await self._close_runtime()
        return self._exit_code

    async def shutdown(self) -> None:
        self._stop_event.set()
        await self._close_runtime()

    async def _close_runtime(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        if self._long_connection is not None:
            await self._long_connection.stop()

        if self._card_auth_runner is not None:
            await self._card_auth_runner.shutdown()

        if self._auth_orchestration_runner is not None:
            await self._auth_orchestration_runner.shutdown()

        if self._inbound_server is not None:
            await self._inbound_server.stop()

        await self._cancel_background_tasks()

        if self._session is not None and not self._session.closed:
            await self._session.close()

        if self._orchestrator is not None:
            shutdown = getattr(self._orchestrator, "shutdown", None)
            if shutdown is not None:
                await shutdown()

    async def _cancel_background_tasks(self) -> None:
        background_tasks = list(self._background_tasks)
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def handle_incoming_event(self, payload: dict[str, Any]) -> None:
        if self._is_card_action_event(payload):
            if await self._handle_settings_card_action_event(payload):
                return
            self._ensure_auth_orchestration_runner().schedule_card_action(payload)
            return
        message = await self._parse_incoming_message(payload)
        if message is None:
            return
        if self._is_old_message(message):
            logger.info(
                "Ignoring old Feishu message after startup chat_id=%s message_id=%s",
                message.chat_id,
                message.message_id,
            )
            return
        await self.handle_incoming_text(message)

    async def handle_incoming_text(self, message: FeishuIncomingText) -> None:
        content_key = await self._prepare_incoming_message(message)
        if content_key is False:
            return

        chat_id = self._id_map.chat_to_int(message.chat_id)
        reply_to = message.message_id if self._config.feishu.reply_to_trigger else None
        topic_id = (
            self._id_map.thread_to_int(message.thread_id)
            if self._config.feishu.thread_isolation and message.thread_id
            else None
        )
        await self._maybe_send_command_guide(message, reply_to_message_id=reply_to)
        set_log_context(operation="feishu-msg", chat_id=chat_id)
        lock = self._lock_pool.get((chat_id, topic_id))
        progress = self._build_progress_reporter(message.chat_id, reply_to)
        auth_routed = False
        try:
            async with lock:
                if await self._handle_pre_stream_shortcuts(
                    message,
                    reply_to_message_id=reply_to,
                    content_key=content_key,
                ):
                    return
                if self._should_start_progress():
                    progress.start()
                if content_key:
                    self._inflight_content_keys.add(content_key)
                auth_routed, result = await self._run_streaming_turn(
                    message,
                    chat_id=chat_id,
                    topic_id=topic_id,
                    progress=progress,
                )
        except Exception as exc:
            await progress.finish_failure(str(exc))
            raise
        finally:
            if content_key:
                self._inflight_content_keys.discard(content_key)
            await progress.close()
        if content_key:
            self._recent_content_dedup.check(content_key)
        if auth_routed or result is None:
            return
        await self._deliver_stream_result(
            result=result,
            chat_ref=message.chat_id,
            reply_to_message_id=reply_to,
            progress=progress,
        )

    async def _prepare_incoming_message(self, message: FeishuIncomingText) -> str | bool | None:
        dedup_key = f"{message.chat_id}:{message.message_id}"
        if self._dedup.check(dedup_key):
            logger.info(
                "Ignoring duplicate Feishu message chat_id=%s message_id=%s",
                message.chat_id,
                message.message_id,
            )
            return False
        if not self._sender_allowed(message.sender_id):
            logger.info("Ignoring Feishu message from unauthorized sender=%s", message.sender_id)
            return False
        if self._orchestrator is None:
            logger.warning("Ignoring Feishu message before startup")
            return False
        if await self._handle_auth_message(message):
            return False

        content_key = self._should_ignore_content_duplicate(message)
        if content_key is False:
            return False
        logger.info(
            "Accepted Feishu message chat_id=%s message_id=%s",
            message.chat_id,
            message.message_id,
        )
        return content_key

    async def _handle_pre_stream_shortcuts(
        self,
        message: FeishuIncomingText,
        *,
        reply_to_message_id: str | None,
        content_key: str | None,
    ) -> bool:
        if await self._handle_native_tool_command(message, reply_to_message_id=reply_to_message_id):
            if content_key:
                self._recent_content_dedup.check(content_key)
            return True
        if await self._handle_settings_panel_command(
            message,
            reply_to_message_id=reply_to_message_id,
        ):
            if content_key:
                self._recent_content_dedup.check(content_key)
            return True
        return False

    async def _handle_settings_panel_command(
        self,
        message: FeishuIncomingText,
        *,
        reply_to_message_id: str | None,
    ) -> bool:
        initial_tab = resolve_initial_settings_tab(message.text)
        if initial_tab is None or self._orchestrator is None:
            return False

        version_info: VersionInfo | None = None
        note: str | None = None
        if initial_tab == "version":
            version_info = await check_latest_version(fresh=True)
            if version_info is None:
                note = "Version check failed."

        await self._send_card_to_chat_ref(
            message.chat_id,
            build_settings_card(
                self._orchestrator._config,
                selected_tab=initial_tab,
                note=note,
                version_info=version_info,
            ),
            reply_to_message_id=reply_to_message_id,
        )
        return True

    async def _handle_settings_card_action_event(self, payload: dict[str, Any]) -> bool:
        parsed = parse_settings_card_action(payload)
        if parsed is None:
            return False
        if self._orchestrator is None:
            logger.warning("Ignoring Feishu settings card action before startup")
            return True
        if not parsed.operator_open_id or not self._sender_allowed(parsed.operator_open_id):
            logger.info(
                "Ignoring Feishu settings card action from unauthorized operator=%s",
                parsed.operator_open_id,
            )
            return True

        version_info: VersionInfo | None = None
        note: str | None = None
        if parsed.kind == "apply":
            if parsed.callback_data:
                resp = await handle_settings_callback(self._orchestrator, parsed.callback_data)
                note = self._extract_settings_panel_note(resp.text)
            else:
                note = "Missing settings action."
        elif parsed.kind == "version_refresh":
            version_info = await check_latest_version(fresh=True)
            note = "Version status refreshed." if version_info is not None else "Version check failed."
        elif parsed.kind == "upgrade":
            version_info = self._settings_upgrade_version_info(parsed.target_version)
            note = await self._start_settings_upgrade(parsed, version_info=version_info)
        elif parsed.kind == "upgrade_hint":
            note = "Use `/settings upgrade` to run the verified self-upgrade flow."

        if not parsed.message_id:
            logger.warning("Ignoring Feishu settings card action without message id")
            return True

        await self._update_interactive_card(
            FeishuCardHandle(chat_id=parsed.chat_id or "", message_id=parsed.message_id),
            build_settings_card(
                self._orchestrator._config,
                selected_tab=parsed.tab,
                note=note,
                version_info=version_info,
            ),
        )
        return True

    async def _start_settings_upgrade(
        self,
        parsed: ParsedSettingsCardAction,
        *,
        version_info: VersionInfo | None,
    ) -> str:
        if self._upgrade_task is not None and not self._upgrade_task.done():
            return "Upgrade already in progress."
        target_version = parsed.target_version or (
            version_info.latest if version_info is not None and version_info.update_available else None
        )
        if not target_version:
            return "No newer version available. Refresh version status first."
        if not parsed.message_id:
            return "Upgrade action missing message id."
        if not parsed.chat_id:
            return "Upgrade action missing chat id."

        handle = FeishuCardHandle(chat_id=parsed.chat_id, message_id=parsed.message_id)
        self._upgrade_task = self._spawn_background_task(
            self._run_settings_upgrade(handle=handle, target_version=target_version)
        )
        return f"Upgrade started: `{target_version}`. ControlMesh will restart after verification passes."

    @staticmethod
    def _settings_upgrade_version_info(target_version: str | None) -> VersionInfo | None:
        if not target_version:
            return None
        current = get_current_version()
        return VersionInfo(
            current=current,
            latest=target_version,
            update_available=target_version != current,
            summary="pending",
            source="github",
        )

    async def _run_settings_upgrade(
        self,
        *,
        handle: FeishuCardHandle,
        target_version: str,
    ) -> None:
        async with self._upgrade_lock:
            installed_before = get_current_version()
            changed, installed_version, output = await perform_upgrade_pipeline(
                current_version=installed_before,
                target_version=target_version,
            )

            if not changed:
                version_info = await check_latest_version(fresh=True)
                await self._update_interactive_card(
                    handle,
                    build_settings_card(
                        self._orchestrator._config,
                        selected_tab="version",
                        note=f"Upgrade verification failed. Still at `{installed_version}`.",
                        version_info=version_info,
                    ),
                )
                tail = output.strip()[-1200:]
                if tail:
                    await self._send_plain_text_to_chat_ref(
                        handle.chat_id,
                        f"Upgrade output tail:\n```text\n{tail}\n```",
                    )
                return

            chat_id_int = self._id_map.chat_to_int(handle.chat_id)
            await asyncio.to_thread(
                write_upgrade_sentinel,
                self._paths.controlmesh_home,
                chat_id=chat_id_int,
                old_version=installed_before,
                new_version=installed_version,
                transport="feishu",
            )
            await self._update_interactive_card(
                handle,
                build_settings_card(
                    self._orchestrator._config,
                    selected_tab="version",
                    note=f"Upgrade installed: `{installed_version}`. Restarting ControlMesh...",
                    version_info=VersionInfo(
                        current=installed_before,
                        latest=installed_version,
                        update_available=False,
                        summary="installed",
                        source="github",
                    ),
                ),
            )
            self._exit_code = EXIT_RESTART
            self._stop_event.set()

    def _spawn_background_task(self, coro: Awaitable[None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _handle_auth_message(self, message: FeishuIncomingText) -> bool:
        if is_native_auth_useful_command(message.text) and await self._ensure_native_auth_useful_runner().handle_message(message):
            return True
        if is_native_auth_all_command(message.text) and await self._ensure_native_auth_all_runner().handle_message(message):
            return True
        if await self._ensure_auth_orchestration_runner().handle_message(message):
            return True
        return await self._ensure_card_auth_runner().handle_message(message)

    async def _handle_native_tool_command(
        self,
        message: FeishuIncomingText,
        *,
        reply_to_message_id: str | None,
    ) -> bool:
        if self._config.feishu.runtime_mode != "native":
            return False
        try:
            parsed = parse_native_tool_command(message.text)
        except ValueError as exc:
            await self._send_plain_text_to_chat_ref(
                message.chat_id,
                str(exc),
                reply_to_message_id=reply_to_message_id,
            )
            return True
        if parsed is None:
            return False
        if self._native_tool_executor is None:
            await self._ensure_session()
        try:
            result = await self._ensure_native_tool_executor().execute(
                parsed.tool_name,
                parsed.arguments,
                context=build_feishu_inbound_context(self._config, message),
            )
        except FeishuNativeToolAuthRequiredError as exc:
            await self._handle_native_tool_auth_required(message, exc.contract)
            return True
        await self._send_plain_text_to_chat_ref(
            message.chat_id,
            format_native_tool_result(parsed.tool_name, result),
            reply_to_message_id=reply_to_message_id,
        )
        return True

    async def _run_streaming_turn(
        self,
        message: FeishuIncomingText,
        *,
        chat_id: int,
        topic_id: int | None,
        progress: _FeishuProgressReporter,
    ) -> tuple[bool, Any]:
        try:
            prompt_text = await self._prepare_native_agent_prompt(
                message,
                chat_id=chat_id,
                topic_id=topic_id,
                progress=progress,
            )
            if self._should_use_bundled_native_runtime():
                turn = await self._run_bundled_native_runtime_turn(
                    message,
                    prompt_text=prompt_text,
                )
                for event in turn.events:
                    await progress.on_agent_event(event)
                await progress.finish_with_single_card_run(turn.card)
                return False, turn
            tool_cb_input: _TextStreamCallback | None = progress.on_tool
            tool_event_input: _ToolEventStreamCallback | None = None
            if self._config.streaming.tool_display == "details":
                reply_to = message.message_id if self._config.feishu.reply_to_trigger else None

                async def emit_tool_event(event: ToolUseEvent | ToolResultEvent) -> None:
                    await self._emit_tool_event_detail(message.chat_id, reply_to, event)

                tool_cb_input = None
                tool_event_input = emit_tool_event

            text_cb, tool_cb, tool_event_cb, system_cb = _stream_callbacks_for_output_mode(
                self._config.streaming.output_mode,
                on_text=progress.on_text_delta,
                on_tool=tool_cb_input,
                on_tool_event=tool_event_input,
                on_system=progress.on_system,
            )
            result = await self._orchestrator.handle_message_streaming(
                SessionKey.for_transport("fs", chat_id, topic_id),
                prompt_text,
                on_text_delta=text_cb,
                on_tool_activity=tool_cb,
                on_tool_event=tool_event_cb,
                on_system_status=system_cb,
            )
        except FeishuNativeToolAuthRequiredError as exc:
            await self._handle_native_tool_auth_required(message, exc.contract)
            return True, None
        return False, result

    def _should_use_bundled_native_runtime(self) -> bool:
        if self._config.feishu.runtime_mode != "native" or self._orchestrator is None:
            return False
        resolve_runtime_target = getattr(self._orchestrator, "resolve_runtime_target", None)
        if resolve_runtime_target is None:
            return False
        _model, provider = resolve_runtime_target(self._config.model)
        return provider == "codex"

    def _should_start_progress(self) -> bool:
        """Return True when Feishu should emit non-conversation progress UI."""
        return self._config.streaming.output_mode in {"full", "tools"}

    async def _emit_tool_event_detail(
        self,
        chat_ref: str,
        reply_to_message_id: str | None,
        event: ToolUseEvent | ToolResultEvent,
    ) -> None:
        await self._send_text_to_chat_ref(
            chat_ref,
            format_tool_event_text(event),
            reply_to_message_id=reply_to_message_id,
        )

    async def _run_bundled_native_runtime_turn(
        self,
        message: FeishuIncomingText,
        *,
        prompt_text: str,
    ) -> BundledFeishuRuntimeTurn:
        model = self._config.model
        if self._orchestrator is not None:
            model, _provider = self._orchestrator.resolve_runtime_target(self._config.model)
        return await asyncio.to_thread(
            run_bundled_codex_turn,
            message,
            prompt_text=prompt_text,
            runtime_config=BundledCodexRuntimeConfig(
                model=model,
                cwd=self._paths.workspace,
                cli_args=list(self._config.cli_parameters.codex),
            ),
        )

    async def _prepare_native_agent_prompt(
        self,
        message: FeishuIncomingText,
        *,
        chat_id: int,
        topic_id: int | None,
        progress: _FeishuProgressReporter,
    ) -> str:
        prompt_text = build_feishu_agent_input(message)
        if self._config.feishu.runtime_mode != "native" or self._orchestrator is None:
            return prompt_text

        cli_service = getattr(self._orchestrator, "cli_service", None)
        execute = getattr(cli_service, "execute", None)
        if execute is None:
            return prompt_text

        context = build_feishu_inbound_context(self._config, message)
        selector_prompt = build_native_agent_tool_selection_prompt(
            user_text=prompt_text,
            inbound_context=context.to_dict(),
        )
        selector_response = await execute(
            AgentRequest(
                prompt=selector_prompt,
                chat_id=chat_id,
                topic_id=topic_id,
                process_label="feishu-native-tool-select",
                timeout_seconds=20.0,
            )
        )
        selection = parse_native_agent_tool_selection(selector_response.result)
        if selection is None:
            return prompt_text

        await progress.on_tool(selection.tool_name)
        if self._native_tool_executor is None:
            await self._ensure_session()
        try:
            tool_result = await self._ensure_native_tool_executor().execute(
                selection.tool_name,
                selection.arguments,
                context=context,
            )
        except ValueError:
            logger.info("Ignoring invalid Feishu native agent tool selection: %s", selection.tool_name)
            return prompt_text

        return build_tool_result_followup_prompt(
            original_text=prompt_text,
            tool_name=selection.tool_name,
            arguments=selection.arguments,
            result=tool_result,
        )

    async def _deliver_stream_result(
        self,
        *,
        result: Any,
        chat_ref: str,
        reply_to_message_id: str | None,
        progress: _FeishuProgressReporter,
    ) -> None:
        result_text = getattr(result, "text", None)
        if not isinstance(result_text, str):
            result_text = getattr(result, "output_text", "")
        status = getattr(result, "status", "completed")
        if status != "completed":
            error_text = result_text or "处理失败"
            await progress.finish_failure(error_text)
            if error_text:
                await self._send_text_to_chat_ref(
                    chat_ref,
                    error_text,
                    reply_to_message_id=reply_to_message_id,
                )
            return
        file_tags = extract_file_paths(result_text)
        visible_text = FILE_PATH_RE.sub("", result_text).strip() if file_tags else result_text
        progress_text = visible_text or ("已发送附件。" if file_tags else result_text)
        await progress.finish_success(progress_text)
        if file_tags:
            from controlmesh.messenger.feishu.sender import send_files_from_text

            await send_files_from_text(
                self,
                chat_ref,
                result_text,
                allowed_roots=self.file_roots(self._paths),
                reply_to_message_id=reply_to_message_id,
            )
        if visible_text and not progress.handles_final_response:
            await self._send_text_to_chat_ref(
                chat_ref,
                visible_text,
                reply_to_message_id=reply_to_message_id,
            )

    def _should_ignore_content_duplicate(self, message: FeishuIncomingText) -> str | bool | None:
        content_key = self._content_dedup_key(message)
        if content_key and content_key in self._inflight_content_keys:
            logger.info(
                "Ignoring repeated Feishu content while in flight chat_id=%s sender_id=%s",
                message.chat_id,
                message.sender_id,
            )
            return False
        if content_key and self._recent_content_dedup.check(content_key):
            logger.info(
                "Ignoring repeated Feishu content chat_id=%s sender_id=%s",
                message.chat_id,
                message.sender_id,
            )
            return False
        return content_key

    def _build_progress_reporter(
        self,
        chat_ref: str,
        reply_to_message_id: str | None,
    ) -> _FeishuProgressReporter:
        if self._config.streaming.output_mode == "off":
            return _FeishuProgressReporter(
                self,
                chat_ref=chat_ref,
                reply_to_message_id=reply_to_message_id,
            )
        if self._config.feishu.progress_mode == "card_stream":
            from controlmesh.messenger.feishu.card_stream import FeishuCardStreamReporter

            return FeishuCardStreamReporter(
                self,
                chat_ref=chat_ref,
                reply_to_message_id=reply_to_message_id,
                title="ControlMesh",
                note="Feishu CardKit streaming",
            )
        if self._config.feishu.progress_mode == "card_preview":
            from controlmesh.messenger.feishu.progress_preview import FeishuCardPreviewReporter

            return FeishuCardPreviewReporter(
                self,
                chat_ref=chat_ref,
                reply_to_message_id=reply_to_message_id,
                max_messages=_FEISHU_PROGRESS_MAX_MESSAGES,
            )
        return _FeishuProgressReporter(
            self,
            chat_ref=chat_ref,
            reply_to_message_id=reply_to_message_id,
        )

    @staticmethod
    def _content_dedup_key(message: FeishuIncomingText) -> str | None:
        normalized_text = " ".join(message.text.split())
        if not normalized_text:
            return None
        return f"{message.chat_id}:{message.sender_id}:{message.thread_id or ''}:{normalized_text[:500]}"

    def _is_old_message(self, message: FeishuIncomingText) -> bool:
        if message.create_time_ms is None:
            return False
        return (message.create_time_ms / 1000.0) < (
            self._process_start_time - _FEISHU_OLD_MESSAGE_GRACE_SECONDS
        )

    async def send_text(self, chat_id: int, text: str) -> None:
        chat_ref = self._id_map.int_to_chat(chat_id)
        if not chat_ref:
            logger.warning("Feishu send_text: unknown chat_id=%s", chat_id)
            return
        await self._send_text_to_chat_ref(chat_ref, text)

    async def send_rich(self, chat_id: int, text: str) -> None:
        await self.send_text(chat_id, text)

    async def broadcast_text(self, text: str) -> None:
        for chat_id in self._id_map.known_chat_ids():
            await self.send_text(chat_id, text)

    async def broadcast_rich(self, text: str) -> None:
        for chat_id in self._id_map.known_chat_ids():
            await self.send_rich(chat_id, text)

    async def _send_text_to_chat_ref(
        self,
        chat_ref: str,
        text: str,
        *,
        reply_to_message_id: str | None = None,
    ) -> None:
        from controlmesh.messenger.feishu.sender import send_rich

        if not text:
            return
        await send_rich(
            self,
            chat_ref,
            text,
            allowed_roots=self.file_roots(self._paths),
            reply_to_message_id=reply_to_message_id,
        )

    async def _send_plain_text_to_chat_ref(
        self,
        chat_ref: str,
        text: str,
        *,
        reply_to_message_id: str | None = None,
    ) -> None:
        if not text:
            return
        await self._send_message_to_chat_ref(
            chat_ref,
            msg_type="text",
            content={"text": text},
            reply_to_message_id=reply_to_message_id,
        )

    async def _maybe_send_command_guide(
        self,
        message: FeishuIncomingText,
        *,
        reply_to_message_id: str | None,
    ) -> None:
        if self._config.feishu.runtime_mode != "native":
            return
        if message.text.strip().startswith("/"):
            return
        guide_key = self._command_guide_key(message.chat_id)
        if self._command_guide_sent(guide_key):
            return
        try:
            await self._send_plain_text_to_chat_ref(
                message.chat_id,
                _FEISHU_COMMAND_GUIDE_TEXT,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception:
            logger.warning("Failed to send Feishu command guide chat_id=%s", message.chat_id, exc_info=True)
            return
        self._mark_command_guide_sent(guide_key)

    def _command_guide_key(self, chat_ref: str) -> str:
        app_id = self._config.feishu.app_id or "unknown-app"
        return f"v{_FEISHU_COMMAND_GUIDE_VERSION}:{app_id}:{chat_ref}"

    def _command_guide_sent(self, key: str) -> bool:
        raw = load_json(self._command_guide_path) or {}
        sent = raw.get("sent")
        return isinstance(sent, list) and key in sent

    def _mark_command_guide_sent(self, key: str) -> None:
        raw = load_json(self._command_guide_path) or {}
        sent_raw = raw.get("sent")
        sent = [str(item) for item in sent_raw] if isinstance(sent_raw, list) else []
        if key in sent:
            return
        sent.append(key)
        atomic_json_save(self._command_guide_path, {"sent": sent})

    async def _send_card_to_chat_ref(
        self,
        chat_ref: str,
        content: dict[str, object],
        *,
        reply_to_message_id: str | None = None,
    ) -> str | None:
        return await self._send_message_to_chat_ref(
            chat_ref,
            msg_type="interactive",
            content=content,
            reply_to_message_id=reply_to_message_id,
        )

    async def _send_message_to_chat_ref(
        self,
        chat_ref: str,
        *,
        msg_type: str,
        content: dict[str, object],
        reply_to_message_id: str | None = None,
    ) -> str | None:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = f"{self._config.feishu.domain.rstrip('/')}/open-apis/im/v1/messages"
        payload: dict[str, object] = {
            "receive_id": chat_ref,
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        headers = {"Authorization": f"Bearer {token}"}
        async with session.post(
            url,
            params={"receive_id_type": "chat_id"},
            json=payload,
            headers=headers,
        ) as response:
            body = await response.text()
            if response.status >= 400:
                logger.warning(
                    "Feishu send failed: status=%s body=%s",
                    response.status,
                    body[:500],
                )
                return None
        try:
            payload_data = json.loads(body)
        except json.JSONDecodeError:
            return None
        data = payload_data.get("data", {})
        if isinstance(data, dict):
            message_id = data.get("message_id")
            if isinstance(message_id, str) and message_id:
                return message_id
        return None

    async def _patch_message(
        self,
        message_id: str,
        *,
        msg_type: str,
        content: dict[str, object],
    ) -> None:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = f"{self._config.feishu.domain.rstrip('/')}/open-apis/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        }
        async with session.patch(url, json=payload, headers=headers) as response:
            if response.status >= 400:
                body = await response.text()
                logger.warning(
                    "Feishu patch failed: status=%s body=%s",
                    response.status,
                    body[:500],
                )
                return None
            data = await response.json(content_type=None)
            raw = data.get("data", {}) if isinstance(data, dict) else {}
            if isinstance(raw, dict):
                message_id = raw.get("message_id")
                if isinstance(message_id, str) and message_id:
                    return message_id
            return None

    async def _update_interactive_card(
        self,
        handle: FeishuCardHandle,
        card: dict[str, Any],
    ) -> None:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = (
            f"{self._config.feishu.domain.rstrip('/')}"
            f"/open-apis/im/v1/messages/{handle.message_id}"
        )
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "content": json.dumps(card, ensure_ascii=False),
            "msg_type": "interactive",
        }
        async with session.patch(url, json=payload, headers=headers) as response:
            if response.status >= 400:
                body = await response.text()
                logger.warning(
                    "Feishu card update failed: status=%s body=%s",
                    response.status,
                    body[:500],
                )

    async def _upload_image(self, path: Path) -> str:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = f"{self._config.feishu.domain.rstrip('/')}/open-apis/im/v1/images"
        form = aiohttp.FormData()
        form.add_field("image_type", "message")
        with path.open("rb") as file_obj:
            form.add_field(
                "image",
                file_obj,
                filename=path.name,
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            async with session.post(
                url,
                data=form,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                data = await response.json(content_type=None)
        image_key = ""
        if isinstance(data, dict):
            raw = data.get("data", {})
            if isinstance(raw, dict):
                image_key = str(raw.get("image_key", "") or "")
        if not image_key:
            msg = f"Feishu image upload failed: {data}"
            raise RuntimeError(msg)
        return image_key

    async def _upload_file(
        self,
        path: Path,
        *,
        file_type: str,
        duration_ms: int | None = None,
    ) -> str:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = f"{self._config.feishu.domain.rstrip('/')}/open-apis/im/v1/files"
        form = aiohttp.FormData()
        form.add_field("file_type", file_type)
        form.add_field("file_name", _sanitize_filename(path.name))
        if duration_ms is not None:
            form.add_field("duration", str(duration_ms))
        with path.open("rb") as file_obj:
            form.add_field(
                "file",
                file_obj,
                filename=path.name,
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            async with session.post(
                url,
                data=form,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                data = await response.json(content_type=None)
        file_key = ""
        if isinstance(data, dict):
            raw = data.get("data", {})
            if isinstance(raw, dict):
                file_key = str(raw.get("file_key", "") or "")
        if not file_key:
            msg = f"Feishu file upload failed: {data}"
            raise RuntimeError(msg)
        return file_key

    async def _send_local_file_to_chat_ref(
        self,
        chat_ref: str,
        path: Path,
        *,
        upload_mode: str,
        reply_to_message_id: str | None = None,
    ) -> None:
        if upload_mode == "image":
            image_key = await self._upload_image(path)
            await self._send_message_to_chat_ref(
                chat_ref,
                msg_type="image",
                content={"image_key": image_key},
                reply_to_message_id=reply_to_message_id,
            )
            return

        mime = mimetypes.guess_type(path.name)[0] or ""
        send_path = path
        duration_ms: int | None = None
        if upload_mode == "audio":
            try:
                send_path, duration_ms = await asyncio.to_thread(
                    self._prepare_audio_send_payload,
                    path,
                    mime,
                )
            except RuntimeError as exc:
                logger.info(
                    "Feishu audio upload falling back to document for %s: %s",
                    path.name,
                    exc,
                )
                upload_mode = "document"
            if send_path == path and path.suffix.lower() not in {".ogg", ".opus"}:
                logger.info(
                    "Feishu audio upload falling back to document for %s because Opus conversion was unavailable",
                    path.name,
                )
                upload_mode = "document"
        elif upload_mode == "video":
            duration_ms = await asyncio.to_thread(self._parse_video_duration_ms, path)
        file_type = self._detect_upload_file_type(path, mime)
        if upload_mode == "audio":
            file_type = "opus"
        file_key = await self._upload_file(send_path, file_type=file_type, duration_ms=duration_ms)
        msg_type = {"audio": "audio", "video": "media"}.get(upload_mode, "file")
        try:
            await self._send_message_to_chat_ref(
                chat_ref,
                msg_type=msg_type,
                content={"file_key": file_key},
                reply_to_message_id=reply_to_message_id,
            )
        finally:
            if send_path != path:
                with suppress(OSError):
                    send_path.unlink()

    @staticmethod
    def _detect_upload_file_type(path: Path, mime: str) -> str:
        suffix = path.suffix.lower()
        suffix_map = {
            ".ogg": "opus",
            ".opus": "opus",
            ".pdf": "pdf",
            ".doc": "doc",
            ".docx": "doc",
            ".xls": "xls",
            ".xlsx": "xls",
            ".csv": "xls",
            ".ppt": "ppt",
            ".pptx": "ppt",
        }
        if mime.startswith("video/") or suffix in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            return "mp4"
        return suffix_map.get(suffix, "stream")

    @staticmethod
    def _prepare_audio_send_payload(path: Path, mime: str) -> tuple[Path, int | None]:
        payload = prepare_audio_upload(path, mime)
        return payload.path, payload.duration_ms

    @staticmethod
    def _parse_video_duration_ms(path: Path) -> int | None:
        try:
            return parse_mp4_duration(path.read_bytes())
        except OSError:
            return None

    async def _create_streaming_card(self, card: dict[str, object]) -> str | None:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = f"{self._config.feishu.domain.rstrip('/')}/open-apis/cardkit/v1/cards"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "type": "card_json",
            "data": json.dumps(card, ensure_ascii=False),
        }
        async with session.post(url, json=payload, headers=headers) as response:
            body = await response.text()
            if response.status >= 400:
                logger.warning(
                    "Feishu cardkit create failed: status=%s body=%s",
                    response.status,
                    body[:500],
                )
                return None
        try:
            payload_data = json.loads(body)
        except json.JSONDecodeError:
            return None
        data = payload_data.get("data", {})
        if isinstance(data, dict):
            card_id = data.get("card_id")
            if isinstance(card_id, str) and card_id:
                return card_id
        logger.warning("Feishu cardkit create returned no card_id body=%s", body[:500])
        return None

    async def _update_streaming_card_content(
        self,
        card_id: str,
        content: str,
        *,
        sequence: int,
        uuid: str,
    ) -> None:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = (
            f"{self._config.feishu.domain.rstrip('/')}"
            f"/open-apis/cardkit/v1/cards/{card_id}/elements/content/content"
        )
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "content": content,
            "sequence": sequence,
            "uuid": uuid,
        }
        async with session.put(url, json=payload, headers=headers) as response:
            if response.status >= 400:
                body = await response.text()
                logger.warning(
                    "Feishu cardkit content update failed: status=%s body=%s",
                    response.status,
                    body[:500],
                )

    async def _close_streaming_card(
        self,
        card_id: str,
        *,
        summary: str,
        sequence: int,
        uuid: str,
    ) -> None:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = f"{self._config.feishu.domain.rstrip('/')}/open-apis/cardkit/v1/cards/{card_id}/settings"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "settings": json.dumps(
                {
                    "config": {
                        "streaming_mode": False,
                        "summary": {"content": summary or "完成"},
                    }
                },
                ensure_ascii=False,
            ),
            "sequence": sequence,
            "uuid": uuid,
        }
        async with session.patch(url, json=payload, headers=headers) as response:
            if response.status >= 400:
                body = await response.text()
                logger.warning(
                    "Feishu cardkit close failed: status=%s body=%s",
                    response.status,
                    body[:500],
                )

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _ensure_card_auth_runner(self) -> FeishuCardAuthRunner:
        if self._card_auth_runner is None:
            sender = BotFeishuCardSender(
                send_card_func=self._send_auth_card_from_context,
                update_card_func=self._update_interactive_card,
            )
            self._card_auth_runner = FeishuCardAuthRunner(
                self._config,
                session_factory=self._ensure_session,
                sender=sender,
                text_reply=self._reply_card_auth_text,
                inject_retry=self._inject_auth_synthetic_retry,
            )
        return self._card_auth_runner

    def _ensure_auth_orchestration_runner(self) -> FeishuAuthOrchestrationRunner:
        if self._auth_orchestration_runner is None:
            sender = BotFeishuCardSender(
                send_card_func=self._send_auth_card_from_context,
                update_card_func=self._update_interactive_card,
            )
            self._auth_orchestration_runner = FeishuAuthOrchestrationRunner(
                self._config,
                sender=sender,
                inject_retry=self._inject_auth_synthetic_retry,
            )
        return self._auth_orchestration_runner

    def _ensure_native_auth_all_runner(self) -> FeishuNativeAuthAllRunner:
        if self._native_auth_all_runner is None:
            self._native_auth_all_runner = FeishuNativeAuthAllRunner(
                self._config,
                session_factory=self._ensure_session,
                get_tenant_access_token=self._get_tenant_access_token,
                start_app_permission_flow=self._ensure_auth_orchestration_runner().start_permission_flow,
                start_user_auth_flow=self._ensure_card_auth_runner().start_retryable_auth_flow,
                text_reply=self._reply_card_auth_text,
            )
        return self._native_auth_all_runner

    def _ensure_native_auth_useful_runner(self) -> FeishuNativeAuthUsefulRunner:
        if self._native_auth_useful_runner is None:
            self._native_auth_useful_runner = FeishuNativeAuthUsefulRunner(
                self._config,
                session_factory=self._ensure_session,
                get_tenant_access_token=self._get_tenant_access_token,
                start_user_auth_flow=self._ensure_card_auth_runner().start_retryable_auth_flow,
                text_reply=self._reply_card_auth_text,
            )
        return self._native_auth_useful_runner

    def _ensure_native_tool_executor(self) -> FeishuNativeToolExecutor:
        if self._native_tool_executor is None:
            if self._session is None:
                msg = "Feishu session not initialized"
                raise RuntimeError(msg)
            self._native_tool_executor = FeishuNativeToolExecutor(
                self._config,
                session=self._session,
                get_tenant_access_token=self._get_tenant_access_token,
            )
        return self._native_tool_executor

    async def _reply_card_auth_text(
        self,
        chat_ref: str,
        text: str,
        reply_to_message_id: str | None,
    ) -> None:
        await self._send_text_to_chat_ref(
            chat_ref,
            text,
            reply_to_message_id=reply_to_message_id,
        )

    async def _send_auth_card_from_context(
        self,
        context: Any,
        card: dict[str, Any],
    ) -> str | None:
        return await self._send_card_to_chat_ref(
            context.chat_id,
            card,
            reply_to_message_id=context.trigger_message_id if self._config.feishu.reply_to_trigger else None,
        )

    async def _inject_auth_synthetic_retry(self, entry: Any, artifact: dict[str, Any]) -> None:
        text = artifact.get("text")
        retry_text = text if isinstance(text, str) and text else entry.retry_text
        await self.handle_incoming_text(
            FeishuIncomingText(
                sender_id=entry.sender_open_id,
                chat_id=entry.chat_id,
                message_id=f"{entry.operation_id}:auth-retry",
                text=retry_text,
                thread_id=entry.thread_id,
            )
        )

    async def _handle_native_tool_auth_required(
        self,
        message: FeishuIncomingText,
        contract: FeishuNativeToolAuthContract,
    ) -> None:
        context = build_feishu_inbound_context(self._config, message)
        requirement = contract.with_runtime_defaults(context=context, original_text=message.text)
        if requirement.error_kind == "app_scope_missing":
            await self._ensure_auth_orchestration_runner().start_auth_requirement(
                message,
                requirement,
            )
            return
        await self._ensure_card_auth_runner().start_retryable_auth_flow(
            message,
            required_scopes=list(requirement.required_scopes),
            retry_text=requirement.retry_text,
            operation_id=requirement.operation_id,
        )

    async def _get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._tenant_access_token_expiry:
            return self._tenant_access_token

        resolved_auth = resolve_feishu_auth(config=self._config, now_ms=int(now * 1000))
        app_id = self._config.feishu.app_id
        app_secret = self._config.feishu.app_secret
        if resolved_auth.auth_mode == "bot_only":
            app_id = resolved_auth.app_id
            app_secret = resolved_auth.app_secret
        elif resolved_auth.auth_mode == "device_flow":
            logger.info(
                "Feishu runtime auth resolved to device_flow, but tenant-level sends still use "
                "app_id/app_secret to mint a tenant access token"
            )

        session = await self._ensure_session()
        url = (
            f"{self._config.feishu.domain.rstrip('/')}"
            "/open-apis/auth/v3/tenant_access_token/internal"
        )
        async with session.post(
            url,
            json={
                "app_id": app_id,
                "app_secret": app_secret,
            },
        ) as response:
            data = await response.json(content_type=None)
            token = str(data.get("tenant_access_token", ""))
            expire = int(data.get("expire", 7200))
            if not token:
                msg = f"Feishu token request failed: {data}"
                raise RuntimeError(msg)
            self._tenant_access_token = token
            self._tenant_access_token_expiry = now + max(expire - 60, 60)
            return token

    def _sender_allowed(self, sender_id: str) -> bool:
        allow_from = self._config.feishu.allow_from
        return not allow_from or sender_id in allow_from

    async def _parse_incoming_message(self, payload: dict[str, Any]) -> FeishuIncomingText | None:
        header = payload.get("header")
        event = payload.get("event")
        if (
            not isinstance(header, dict)
            or not isinstance(event, dict)
            or header.get("event_type") != "im.message.receive_v1"
        ):
            return None

        message = event.get("message")
        sender = event.get("sender")
        if not isinstance(message, dict) or not isinstance(sender, dict):
            return None

        parts = self._extract_message_identity(sender, message)
        if parts is None:
            return None
        sender_id, chat_id, message_id = parts

        message_type = message.get("message_type")
        parsed_content = None
        if isinstance(message_type, str) and message_type in {
            "text",
            "post",
            "interactive",
            "merge_forward",
        }:
            parsed_content = extract_feishu_content_from_event(
                payload,
                message_type,
                message.get("content"),
            )
            text = parsed_content.text
        elif isinstance(message_type, str) and is_supported_media_message_type(message_type):
            text = await self._resolve_incoming_media_text(
                message_id=message_id,
                message_type=message_type,
                raw_content=message.get("content"),
            )
        else:
            return None
        if not text:
            return None

        thread_id = message.get("thread_id") or message.get("root_id") or message.get("parent_id")
        root_id = message.get("root_id")
        parent_id = message.get("parent_id")
        create_time_ms = self._extract_create_time_ms(header.get("create_time"))
        return FeishuIncomingText(
            sender_id=sender_id,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            thread_id=thread_id if isinstance(thread_id, str) and thread_id else None,
            create_time_ms=create_time_ms,
            message_type=message_type if isinstance(message_type, str) else "text",
            root_id=root_id if isinstance(root_id, str) and root_id else None,
            parent_id=parent_id if isinstance(parent_id, str) and parent_id else None,
            quote_summary=parsed_content.quote_summary if parsed_content else None,
            post_title=parsed_content.post_title if parsed_content else None,
        )

    @staticmethod
    def _extract_message_identity(
        sender: dict[str, Any],
        message: dict[str, Any],
    ) -> tuple[str, str, str] | None:
        sender_id = FeishuBot._extract_sender_id(sender)
        chat_id = message.get("chat_id")
        message_id = message.get("message_id")
        if not all(
            (
                isinstance(sender_id, str) and sender_id,
                isinstance(chat_id, str) and chat_id,
                isinstance(message_id, str) and message_id,
            )
        ):
            return None
        return sender_id, chat_id, message_id

    async def _resolve_incoming_media_text(
        self,
        *,
        message_id: str,
        message_type: str,
        raw_content: object,
    ) -> str | None:
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        return await _resolve_media_text(
            ResolveMediaRequest(
                session=session,
                config=self._config.feishu,
                message_id=message_id,
                message_type=message_type,
                raw_content=raw_content,
                files_dir=self._paths.feishu_files_dir,
                workspace=self._paths.workspace,
                tenant_access_token=token,
            )
        )

    @staticmethod
    def _is_card_action_event(payload: dict[str, Any]) -> bool:
        header = payload.get("header")
        if isinstance(header, dict) and header.get("event_type") == "card.action.trigger":
            return True
        event = payload.get("event")
        if isinstance(event, dict) and isinstance(event.get("action"), dict):
            return True
        return isinstance(payload.get("action"), dict)

    @staticmethod
    def _extract_sender_id(sender: dict[str, Any]) -> str:
        sender_id = sender.get("sender_id")
        if not isinstance(sender_id, dict):
            return ""
        for key in ("open_id", "user_id", "union_id"):
            value = sender_id.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    @staticmethod
    def _extract_text(raw_content: object) -> str:
        if isinstance(raw_content, dict):
            value = raw_content.get("text")
            return value.strip() if isinstance(value, str) else ""
        if not isinstance(raw_content, str):
            return ""
        try:
            content = json.loads(raw_content)
        except json.JSONDecodeError:
            return raw_content.strip()
        value = content.get("text") if isinstance(content, dict) else None
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _extract_settings_panel_note(text: str) -> str | None:
        sections = [section.strip() for section in text.split("\n\n") if section.strip()]
        if len(sections) < 2 or "Advanced Settings" not in sections[0]:
            return None
        note = sections[1]
        return None if note.startswith("**") else note

    @staticmethod
    def _extract_create_time_ms(raw_create_time: object) -> int | None:
        if isinstance(raw_create_time, str) and raw_create_time.isdigit():
            return int(raw_create_time)
        if isinstance(raw_create_time, int):
            return raw_create_time
        return None

    async def on_async_interagent_result(self, result: AsyncInterAgentResult) -> None:
        from controlmesh.bus.adapters import from_interagent_result

        chat_id = result.chat_id or next(iter(self._id_map.known_chat_ids()), 0)
        if not chat_id:
            logger.warning("No Feishu chat available for async interagent result delivery")
            return
        set_log_context(operation="ia-async", chat_id=chat_id)
        await self._submit_feishu_envelope(from_interagent_result(result, chat_id))

    async def on_task_result(self, result: TaskResult) -> None:
        from controlmesh.bus.adapters import from_task_result

        chat_id = result.chat_id or next(iter(self._id_map.known_chat_ids()), 0)
        if not chat_id:
            logger.warning("No Feishu chat available for task result delivery")
            return
        set_log_context(operation="task", chat_id=chat_id)
        await self._submit_feishu_envelope(from_task_result(result))

    async def on_task_question(
        self,
        task_id: str,
        question: str,
        prompt_preview: str,
        chat_id: int,
        thread_id: int | None = None,
    ) -> None:
        from controlmesh.bus.adapters import from_task_question

        if not chat_id:
            chat_id = next(iter(self._id_map.known_chat_ids()), 0)
        if not chat_id:
            logger.warning("No Feishu chat available for task question delivery")
            return
        set_log_context(operation="task-question", chat_id=chat_id)
        await self._submit_feishu_envelope(
            from_task_question(
                task_id,
                question,
                prompt_preview,
                chat_id,
                topic_id=thread_id,
            )
        )

    async def _submit_feishu_envelope(self, envelope: Envelope) -> None:
        """Route bus deliveries explicitly through the Feishu transport."""
        envelope.transport = "fs"
        await self._bus.submit(envelope)
