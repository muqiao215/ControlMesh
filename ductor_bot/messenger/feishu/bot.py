"""Feishu bot-only messenger skeleton."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp

from ductor_bot.bus.bus import MessageBus
from ductor_bot.bus.envelope import Envelope
from ductor_bot.bus.lock_pool import LockPool
from ductor_bot.config import AgentConfig
from ductor_bot.files.allowed_roots import resolve_allowed_roots
from ductor_bot.log_context import set_log_context
from ductor_bot.messenger.notifications import NotificationService
from ductor_bot.session.key import SessionKey

if TYPE_CHECKING:
    from ductor_bot.multiagent.bus import AsyncInterAgentResult
    from ductor_bot.orchestrator.core import Orchestrator
    from ductor_bot.tasks.models import TaskResult
    from ductor_bot.workspace.paths import DuctorPaths

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FeishuIncomingText:
    """Normalized Feishu text message event."""

    sender_id: str
    chat_id: str
    message_id: str
    text: str
    thread_id: str | None = None


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
        self._shutdown_started = False
        self._exit_code = 0

        store_path = Path(config.ductor_home).expanduser() / "feishu_store"
        store_path.mkdir(parents=True, exist_ok=True)

        from ductor_bot.messenger.feishu.id_map import FeishuIdMap
        from ductor_bot.messenger.feishu.transport import FeishuTransport

        self._id_map = FeishuIdMap(store_path)
        self._notification_service: NotificationService = FeishuNotificationService(self)
        self._bus.register_transport(FeishuTransport(self))

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

    def file_roots(self, paths: DuctorPaths) -> list[Path] | None:
        return resolve_allowed_roots(self._config.file_access, paths.workspace)

    async def run(self) -> int:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

        from ductor_bot.messenger.feishu.startup import run_feishu_startup

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

        if self._session is not None and not self._session.closed:
            await self._session.close()

        if self._orchestrator is not None:
            await self._orchestrator.shutdown()

    async def handle_incoming_event(self, payload: dict[str, Any]) -> None:
        message = self._parse_incoming_text(payload)
        if message is None:
            return
        await self.handle_incoming_text(message)

    async def handle_incoming_text(self, message: FeishuIncomingText) -> None:
        if not self._sender_allowed(message.sender_id):
            logger.info("Ignoring Feishu message from unauthorized sender=%s", message.sender_id)
            return
        if self._orchestrator is None:
            logger.warning("Ignoring Feishu message before startup")
            return

        chat_id = self._id_map.chat_to_int(message.chat_id)
        topic_id = (
            self._id_map.thread_to_int(message.thread_id)
            if self._config.feishu.thread_isolation and message.thread_id
            else None
        )
        set_log_context(operation="feishu-msg", chat_id=chat_id)
        lock = self._lock_pool.get((chat_id, topic_id))
        async with lock:
            result = await self._orchestrator.handle_message(
                SessionKey.for_transport("fs", chat_id, topic_id),
                message.text,
            )
        if result.text:
            reply_to = message.message_id if self._config.feishu.reply_to_trigger else None
            await self._send_text_to_chat_ref(message.chat_id, result.text, reply_to_message_id=reply_to)

    async def send_text(self, chat_id: int, text: str) -> None:
        chat_ref = self._id_map.int_to_chat(chat_id)
        if not chat_ref:
            logger.warning("Feishu send_text: unknown chat_id=%s", chat_id)
            return
        await self._send_text_to_chat_ref(chat_ref, text)

    async def broadcast_text(self, text: str) -> None:
        for chat_id in self._id_map.known_chat_ids():
            await self.send_text(chat_id, text)

    async def _send_text_to_chat_ref(
        self,
        chat_ref: str,
        text: str,
        *,
        reply_to_message_id: str | None = None,
    ) -> None:
        if not text:
            return
        session = await self._ensure_session()
        token = await self._get_tenant_access_token()
        url = f"{self._config.feishu.domain.rstrip('/')}/open-apis/im/v1/messages"
        payload: dict[str, object] = {
            "receive_id": chat_ref,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
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
            if response.status >= 400:
                body = await response.text()
                logger.warning(
                    "Feishu send failed: status=%s body=%s",
                    response.status,
                    body[:500],
                )

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._tenant_access_token_expiry:
            return self._tenant_access_token

        session = await self._ensure_session()
        url = (
            f"{self._config.feishu.domain.rstrip('/')}"
            "/open-apis/auth/v3/tenant_access_token/internal"
        )
        async with session.post(
            url,
            json={
                "app_id": self._config.feishu.app_id,
                "app_secret": self._config.feishu.app_secret,
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

    def _parse_incoming_text(self, payload: dict[str, Any]) -> FeishuIncomingText | None:
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
        if not isinstance(message, dict) or not isinstance(sender, dict) or message.get(
            "message_type"
        ) != "text":
            return None

        sender_id = self._extract_sender_id(sender)
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
        assert isinstance(chat_id, str)
        assert isinstance(message_id, str)

        text = self._extract_text(message.get("content"))
        if not text:
            return None

        thread_id = message.get("thread_id") or message.get("root_id") or message.get("parent_id")
        return FeishuIncomingText(
            sender_id=sender_id,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            thread_id=thread_id if isinstance(thread_id, str) and thread_id else None,
        )

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

    async def on_async_interagent_result(self, result: AsyncInterAgentResult) -> None:
        from ductor_bot.bus.adapters import from_interagent_result

        chat_id = result.chat_id or next(iter(self._id_map.known_chat_ids()), 0)
        if not chat_id:
            logger.warning("No Feishu chat available for async interagent result delivery")
            return
        set_log_context(operation="ia-async", chat_id=chat_id)
        await self._submit_feishu_envelope(from_interagent_result(result, chat_id))

    async def on_task_result(self, result: TaskResult) -> None:
        from ductor_bot.bus.adapters import from_task_result

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
        from ductor_bot.bus.adapters import from_task_question

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
