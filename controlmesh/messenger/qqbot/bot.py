"""Direct official QQ Bot runtime primitives."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
import time
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import aiohttp

from controlmesh.bus.bus import MessageBus
from controlmesh.bus.lock_pool import LockPool
from controlmesh.config import AgentConfig, QQBotAccountConfig
from controlmesh.files.allowed_roots import resolve_allowed_roots
from controlmesh.files.tags import FILE_PATH_RE, extract_file_paths, guess_mime, path_from_file_tag
from controlmesh.infra.version import get_current_version
from controlmesh.messenger.address import ChatRef, TopicRef, require_string_chat_ref
from controlmesh.messenger.qqbot.inbound import (
    QQBotInteraction,
    QQBotIncomingText,
    is_standalone_slash_command,
    matches_text_mention_patterns,
    normalize_interaction_event,
    normalize_gateway_event,
)
from controlmesh.messenger.qqbot.outbound import (
    button_grid_to_inline_keyboard,
    choose_reply_mode,
    record_passive_reply,
    sanitize_outbound_text,
)
from controlmesh.messenger.qqbot.known_targets import QQBotKnownTargetsStore
from controlmesh.messenger.qqbot.ref_index import QQBotRefIndexEntry, QQBotRefIndexStore
from controlmesh.messenger.protocol import BotProtocol
from controlmesh.messenger.qqbot.api import QQBotApiClient
from controlmesh.messenger.qqbot.gateway import QQBotGatewayClient
from controlmesh.messenger.qqbot.session_store import QQBotSessionStore
from controlmesh.messenger.qqbot.target import parse_target
from controlmesh.messenger.qqbot.typing_keepalive import QQBotTypingKeepAlive
from controlmesh.messenger.qqbot.token_manager import QQBotTokenManager
from controlmesh.messenger.qqbot.transport import QQBotTransport
from controlmesh.messenger.qqbot.types import QQBotRuntimeAccount
from controlmesh.security.paths import is_path_safe
from controlmesh.session.key import SessionKey
from controlmesh.workspace.paths import resolve_paths

if TYPE_CHECKING:
    from controlmesh.orchestrator.selectors.models import ButtonGrid
    from controlmesh.multiagent.bus import AsyncInterAgentResult
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.tasks.models import TaskResult
    from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)


@runtime_checkable
class QQBotSender(Protocol):
    """Minimal sender surface needed by the qqbot transport adapter."""

    async def send_text(self, target: str, text: str) -> None:
        """Send a text message to one canonical QQ target."""
        ...

    async def broadcast_text(self, text: str) -> None:
        """Broadcast a text message using transport-specific policy."""
        ...


class QQBotNotificationService:
    """Notification wrapper that uses canonical QQ target strings directly."""

    def __init__(self, sender: QQBotSender) -> None:
        self._sender = sender

    async def notify(self, chat_id: ChatRef, text: str) -> None:
        target = require_string_chat_ref(chat_id)
        await self._sender.send_text(target, text)

    async def notify_all(self, text: str) -> None:
        await self._sender.broadcast_text(text)


class QQBotBot(BotProtocol):
    """Direct official QQ bot runtime owner for ControlMesh."""

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
        self._lock_pool = lock_pool or LockPool()
        self._bus = bus or MessageBus(lock_pool=self._lock_pool)
        self._orchestrator: Orchestrator | None = None
        self._startup_hooks: list[Callable[[], Awaitable[None]]] = []
        self._abort_all_callback: Callable[[], Awaitable[int]] | None = None
        self._notification_service = QQBotNotificationService(self)
        self._stop_event = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None
        self._gateway: QQBotGatewayClient | None = None
        self._session_store = QQBotSessionStore(config.controlmesh_home)
        self._known_targets = QQBotKnownTargetsStore(config.controlmesh_home)
        self._ref_index = QQBotRefIndexStore(config.controlmesh_home)
        self._runtime_account: QQBotRuntimeAccount | None = None
        self._api_client: QQBotApiClient | None = None
        self._token_manager: QQBotTokenManager | None = None
        self._exit_code = 0
        self._bus.register_transport(QQBotTransport(self))

    @property
    def orchestrator(self) -> Orchestrator | None:
        return self._orchestrator

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def notification_service(self) -> QQBotNotificationService:
        return self._notification_service

    async def run(self) -> int:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))

        from controlmesh.orchestrator.core import Orchestrator

        try:
            if self._orchestrator is None:
                self._orchestrator = await Orchestrator.create(
                    self._config,
                    agent_name=self._agent_name,
                )
                self._orchestrator.wire_observers_to_bus(self._bus)

            await self._start_runtime()
            for hook in self._startup_hooks:
                await hook()

            waiters = [asyncio.create_task(self._stop_event.wait(), name="qqbot:stop-wait")]
            if self._gateway is not None:
                waiters.append(
                    asyncio.create_task(self._gateway.wait_closed(), name="qqbot:gateway-wait")
                )
            done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
        finally:
            await self._close_runtime()
        return self._exit_code

    async def shutdown(self) -> None:
        self._stop_event.set()
        await self._close_runtime()

    def register_startup_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._startup_hooks.append(hook)

    def set_abort_all_callback(self, callback: Callable[[], Awaitable[int]]) -> None:
        self._abort_all_callback = callback

    async def on_async_interagent_result(self, result: AsyncInterAgentResult) -> None:
        if result.result_text:
            await self.broadcast_text(result.result_text)

    async def on_task_result(self, result: TaskResult) -> None:
        if isinstance(result.chat_id, str) and result.result_text:
            await self.send_text(result.chat_id, result.result_text)

    async def on_task_question(
        self,
        task_id: str,
        question: str,
        prompt_preview: str,
        chat_id: ChatRef,
        thread_id: TopicRef = None,
    ) -> None:
        del thread_id
        if isinstance(chat_id, str):
            await self.send_text(
                chat_id,
                f"Task `{task_id}` has a question:\n{question}\n\n{prompt_preview}",
            )

    def file_roots(self, paths: ControlMeshPaths) -> list[Path] | None:
        return resolve_allowed_roots(self._config.file_access, paths.workspace)

    async def send_text(self, target: str, text: str) -> None:
        await self._send_text_target(target, text)

    async def _send_text_target(
        self,
        target: str,
        text: str,
        *,
        reply_to_message_id: str | None = None,
        buttons: ButtonGrid | None = None,
    ) -> None:
        account = self._runtime_account or self._resolve_account()
        api_client = self._require_api_client()
        token_manager = self._require_token_manager()
        token = await token_manager.get_token_value(account.app_id, account.client_secret)
        target_info = parse_target(target)
        prepared_text = sanitize_outbound_text(text)
        file_refs = extract_file_paths(prepared_text)
        clean_text = sanitize_outbound_text(FILE_PATH_RE.sub("", prepared_text))
        inline_keyboard = button_grid_to_inline_keyboard(buttons) if buttons is not None else None

        if clean_text:
            send_kwargs: dict[str, str] = {}
            reply_mode = choose_reply_mode(target_info.type, reply_to_message_id)
            effective_reply_to = reply_mode.msg_id
            if reply_mode.fallback_to_proactive:
                logger.info(
                    "QQ send fell back to proactive text target=%s original_msg_id=%s reason=%s",
                    target,
                    reply_to_message_id,
                    reply_mode.fallback_reason,
                )
            if effective_reply_to:
                send_kwargs["msg_id"] = effective_reply_to
            if inline_keyboard is not None:
                try:
                    response = await api_client.send_text_message(
                        token,
                        target,
                        clean_text,
                        inline_keyboard=inline_keyboard,
                        **send_kwargs,
                    )
                except ValueError:
                    fallback_text = (
                        f"{clean_text}\n\n"
                        "[ControlMesh qqbot skipped interactive buttons: "
                        "inline buttons are only supported for c2c/group targets.]"
                    )
                    response = await api_client.send_text_message(
                        token,
                        target,
                        fallback_text,
                        **send_kwargs,
                    )
                    clean_text = fallback_text
            else:
                response = await api_client.send_text_message(token, target, clean_text, **send_kwargs)
            if effective_reply_to:
                record_passive_reply(target_info.type, effective_reply_to)
            self._record_outbound_ref(account, target, response, clean_text)
        if not file_refs:
            return

        await self._send_tagged_files(
            token,
            target,
            file_refs,
            reply_to_message_id=reply_to_message_id,
        )

    async def broadcast_text(self, text: str) -> None:
        account = self._runtime_account or self._resolve_account()
        targets = list(self._broadcast_targets(account))
        if not targets:
            logger.info("QQ Bot broadcast skipped: no allowlisted proactive targets configured")
            return
        for target in dict.fromkeys(targets):
            await self.send_text(target, text)

    async def handle_incoming_text(self, message: QQBotIncomingText) -> None:
        if self._orchestrator is None:
            logger.warning("Ignoring QQ message before startup")
            return
        self._record_known_target(message.chat_id)

        logger.info(
            "Accepted QQ message event=%s chat_id=%s message_id=%s",
            message.event_type,
            message.chat_id,
            message.message_id,
        )
        typing_keepalive = await self._start_typing_keepalive(message)
        lock = self._lock_pool.get((message.chat_id, message.topic_id))
        try:
            async with lock:
                result = await self._orchestrator.handle_message_streaming(
                    SessionKey.for_transport("qqbot", message.chat_id, message.topic_id),
                    message.text,
                )
        finally:
            if typing_keepalive is not None:
                await typing_keepalive.stop()
        if not result.text:
            logger.info(
                "QQ reply skipped chat_id=%s message_id=%s empty_result=True",
                message.chat_id,
                message.message_id,
            )
            return

        logger.info(
            "QQ reply start chat_id=%s message_id=%s chars=%s",
            message.chat_id,
            message.message_id,
            len(result.text),
        )
        try:
            reply_buttons = getattr(result, "buttons", None)
            if self._api_client is None or self._token_manager is None:
                await self.send_text(message.chat_id, result.text)
            else:
                await self._send_text_target(
                    message.chat_id,
                    result.text,
                    reply_to_message_id=message.message_id,
                    buttons=reply_buttons,
                )
        except Exception:
            logger.exception(
                "QQ reply failed chat_id=%s message_id=%s",
                message.chat_id,
                message.message_id,
            )
            raise
        logger.info(
            "QQ reply success chat_id=%s message_id=%s chars=%s",
            message.chat_id,
            message.message_id,
            len(result.text),
        )

    async def _start_typing_keepalive(
        self,
        message: QQBotIncomingText,
    ) -> QQBotTypingKeepAlive | None:
        if self._api_client is None or self._token_manager is None:
            return None
        target = parse_target(message.chat_id)
        if target.type != "c2c":
            return None
        account = self._runtime_account or self._resolve_account()
        keepalive = QQBotTypingKeepAlive(
            api_client=self._api_client,
            token_manager=self._token_manager,
            account=account,
            openid=target.id,
            msg_id=message.message_id,
        )
        try:
            await keepalive.send_initial()
        except Exception as exc:
            logger.info(
                "QQ typing/input-notify skipped chat_id=%s message_id=%s reason=%s",
                message.chat_id,
                message.message_id,
                exc,
            )
            await keepalive.stop()
            return None
        keepalive.start()
        return keepalive

    def _resolve_account(self) -> QQBotRuntimeAccount:
        qq = self._config.qqbot
        if qq.default_account:
            account = qq.accounts.get(qq.default_account)
            if account is None:
                msg = f"QQ Bot default_account {qq.default_account!r} was not found"
                raise RuntimeError(msg)
            if not _account_is_complete(account):
                msg = f"QQ Bot default_account {qq.default_account!r} is incomplete"
                raise RuntimeError(msg)
            return _materialize_account(
                account_key=qq.default_account,
                account=account,
                controlmesh_home=Path(self._config.controlmesh_home),
            )

        if qq.app_id and (qq.client_secret or qq.client_secret_file):
            return _materialize_account(
                account_key="default",
                account=qq,
                controlmesh_home=Path(self._config.controlmesh_home),
            )

        for account_key, account in qq.accounts.items():
            if account.enabled and _account_is_complete(account):
                return _materialize_account(
                    account_key=account_key,
                    account=account,
                    controlmesh_home=Path(self._config.controlmesh_home),
                )

        msg = "QQ Bot transport requires at least one configured account"
        raise RuntimeError(msg)

    async def _start_runtime(self) -> None:
        self._runtime_account = self._resolve_account()
        user_agent = _build_user_agent()
        self._api_client = QQBotApiClient(self._session, user_agent=user_agent)
        self._token_manager = QQBotTokenManager(self._api_client.fetch_access_token)
        self._gateway = QQBotGatewayClient(
            session=self._session,
            api_client=self._api_client,
            token_manager=self._token_manager,
            session_store=self._session_store,
            account=self._runtime_account,
            user_agent=user_agent,
            on_dispatch=self._handle_gateway_dispatch,
        )
        await self._gateway.start()

    async def _close_runtime(self) -> None:
        if self._gateway is not None:
            await self._gateway.close()
            self._gateway = None
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _require_api_client(self) -> QQBotApiClient:
        if self._api_client is None:
            msg = "QQ Bot runtime is not initialized"
            raise RuntimeError(msg)
        return self._api_client

    def _require_token_manager(self) -> QQBotTokenManager:
        if self._token_manager is None:
            msg = "QQ Bot runtime is not initialized"
            raise RuntimeError(msg)
        return self._token_manager

    async def _handle_gateway_dispatch(self, event_type: str, payload: dict[str, object]) -> None:
        if event_type == "INTERACTION_CREATE":
            interaction = normalize_interaction_event(payload)
            if interaction is not None:
                await self._handle_interaction(interaction)
            return
        event = normalize_gateway_event(event_type, payload)
        if event is None:
            return
        event = self._activate_group_message_event(event)
        if not event.deliver_to_orchestrator:
            self._record_known_target(event.chat_id)
            logger.info(
                "Observed passive QQ message event=%s chat_id=%s message_id=%s",
                event.event_type,
                event.chat_id,
                event.message_id,
            )
            return
        await self.handle_incoming_text(event)

    async def _handle_interaction(self, interaction: QQBotInteraction) -> None:
        from controlmesh.messenger.callback_router import route_callback

        token_manager = self._require_token_manager()
        api_client = self._require_api_client()
        account = self._runtime_account or self._resolve_account()
        token = await token_manager.get_token_value(account.app_id, account.client_secret)
        await api_client.acknowledge_interaction(token, interaction.interaction_id)

        if interaction.button_data.startswith("approve:"):
            await self._send_text_target(
                interaction.chat_id,
                (
                    "[ControlMesh qqbot approvals are not implemented in the direct runtime yet. "
                    "OpenClaw approval-handler semantics remain reference-only in Phase 6.]"
                ),
                reply_to_message_id=interaction.message_id,
            )
            return

        if self._orchestrator is None:
            logger.warning("Ignoring QQ interaction before startup")
            return

        result = await route_callback(
            self._orchestrator,
            SessionKey.for_transport("qqbot", interaction.chat_id, interaction.topic_id),
            interaction.button_data,
        )
        if result.handled:
            if result.text:
                await self._send_text_target(
                    interaction.chat_id,
                    result.text,
                    reply_to_message_id=interaction.message_id,
                    buttons=result.buttons,
                )
            return

        fallback = await self._orchestrator.handle_message_streaming(
            SessionKey.for_transport("qqbot", interaction.chat_id, interaction.topic_id),
            interaction.button_data,
        )
        if fallback.text:
            fallback_buttons = getattr(fallback, "buttons", None)
            await self._send_text_target(
                interaction.chat_id,
                fallback.text,
                reply_to_message_id=interaction.message_id,
                buttons=fallback_buttons,
            )

    def _activate_group_message_event(self, event: QQBotIncomingText) -> QQBotIncomingText:
        if event.event_type != "GROUP_MESSAGE_CREATE" or event.deliver_to_orchestrator:
            return event
        account = self._runtime_account or self._resolve_account()
        if is_standalone_slash_command(event.text):
            logger.info(
                "Activated QQ plain group message via standalone slash command chat_id=%s message_id=%s",
                event.chat_id,
                event.message_id,
            )
            return replace(event, deliver_to_orchestrator=True)
        if account.group_message_mode == "mention_patterns" and matches_text_mention_patterns(
            event.text, account.mention_patterns
        ):
            logger.info(
                "Activated QQ plain group message via mention pattern chat_id=%s message_id=%s",
                event.chat_id,
                event.message_id,
            )
            return replace(event, deliver_to_orchestrator=True)
        if account.activate_on_bot_reply and event.ref_msg_idx:
            ref_entry = self._ref_index.get_ref(account.app_id, event.ref_msg_idx)
            if ref_entry is not None and ref_entry.is_bot and ref_entry.target == event.chat_id:
                logger.info(
                    "Activated QQ plain group message via bot reply reference chat_id=%s message_id=%s ref_msg_idx=%s",
                    event.chat_id,
                    event.message_id,
                    event.ref_msg_idx,
                )
                return replace(event, deliver_to_orchestrator=True)
        return event

    async def _send_tagged_files(
        self,
        token: str,
        target: str,
        file_refs: list[str],
        *,
        reply_to_message_id: str | None = None,
    ) -> None:
        api_client = self._require_api_client()
        account = self._runtime_account or self._resolve_account()
        target_type = parse_target(target).type
        # Live direct-message runtime now routes through sender-scoped `qqbot:c2c:*`,
        # so this `dm` branch only covers the narrow manual `qqbot:dm:{guild_id}` alias.
        if target_type in {"channel", "dm"}:
            label = "dm" if target_type == "dm" else "channel"
            send_kwargs: dict[str, str] = {}
            if reply_to_message_id:
                send_kwargs["msg_id"] = reply_to_message_id
            response = await api_client.send_text_message(
                token,
                target,
                (
                    "[ControlMesh qqbot skipped "
                    f"{len(file_refs)} attachment(s): {label} media delivery is not implemented yet.]"
                ),
                **send_kwargs,
            )
            self._record_outbound_ref(
                account,
                target,
                response,
                (
                    "[ControlMesh qqbot skipped "
                    f"{len(file_refs)} attachment(s): {label} media delivery is not implemented yet.]"
                ),
            )
            return

        paths = resolve_paths(controlmesh_home=self._config.controlmesh_home)
        allowed_roots = self.file_roots(paths)
        for file_ref in file_refs:
            reply_mode = choose_reply_mode(target_type, reply_to_message_id)
            effective_reply_to = reply_mode.msg_id
            if reply_mode.fallback_to_proactive:
                logger.info(
                    "QQ send fell back to proactive media target=%s original_msg_id=%s reason=%s",
                    target,
                    reply_to_message_id,
                    reply_mode.fallback_reason,
                )
            file_path = path_from_file_tag(file_ref)
            if allowed_roots is not None and not is_path_safe(file_path, allowed_roots):
                send_kwargs: dict[str, str] = {}
                if effective_reply_to:
                    send_kwargs["msg_id"] = effective_reply_to
                response = await api_client.send_text_message(
                    token,
                    target,
                    f"[Attachment blocked outside allowed roots: {file_path.name}]",
                    **send_kwargs,
                )
                self._record_outbound_ref(
                    account,
                    target,
                    response,
                    f"[Attachment blocked outside allowed roots: {file_path.name}]",
                )
                if effective_reply_to:
                    record_passive_reply(target_type, effective_reply_to)
                continue
            exists = await asyncio.to_thread(file_path.exists)
            if not exists:
                send_kwargs = {}
                if effective_reply_to:
                    send_kwargs["msg_id"] = effective_reply_to
                response = await api_client.send_text_message(
                    token,
                    target,
                    f"[Attachment not found: {file_path.name}]",
                    **send_kwargs,
                )
                self._record_outbound_ref(
                    account,
                    target,
                    response,
                    f"[Attachment not found: {file_path.name}]",
                )
                if effective_reply_to:
                    record_passive_reply(target_type, effective_reply_to)
                continue

            mime = await asyncio.to_thread(guess_mime, file_path)
            file_bytes = await asyncio.to_thread(file_path.read_bytes)
            if mime.startswith("image/"):
                send_kwargs = {}
                if effective_reply_to:
                    send_kwargs["msg_id"] = effective_reply_to
                response = await api_client.send_image_message(
                    token,
                    target,
                    file_name=file_path.name,
                    file_bytes=file_bytes,
                    **send_kwargs,
                )
                if effective_reply_to:
                    record_passive_reply(target_type, effective_reply_to)
                self._record_outbound_ref(account, target, response, f"[image:{file_path.name}]")
            else:
                send_kwargs = {}
                if effective_reply_to:
                    send_kwargs["msg_id"] = effective_reply_to
                response = await api_client.send_file_message(
                    token,
                    target,
                    file_name=file_path.name,
                    file_bytes=file_bytes,
                    **send_kwargs,
                )
                if effective_reply_to:
                    record_passive_reply(target_type, effective_reply_to)
                self._record_outbound_ref(account, target, response, f"[file:{file_path.name}]")

    def _record_known_target(self, target: str) -> None:
        account = self._runtime_account or self._resolve_account()
        self._known_targets.record_target(account.app_id, target)

    def _broadcast_targets(self, account: QQBotRuntimeAccount) -> tuple[str, ...]:
        targets: list[str] = []
        if account.dm_policy == "open":
            targets.extend(self._known_targets.list_targets(account.app_id, kinds=("c2c", "dm")))
            targets.extend(_qualified_targets("c2c", account.allow_from))
        elif account.dm_policy == "allowlist":
            targets.extend(_qualified_targets("c2c", account.allow_from))
        if account.group_policy == "open":
            targets.extend(self._known_targets.list_targets(account.app_id, kinds=("group",)))
            targets.extend(_qualified_targets("group", account.group_allow_from))
        elif account.group_policy == "allowlist":
            targets.extend(_qualified_targets("group", account.group_allow_from))
        return tuple(targets)

    def _record_outbound_ref(
        self,
        account: QQBotRuntimeAccount,
        target: str,
        response: object,
        content: str,
    ) -> None:
        if not isinstance(response, dict):
            return
        ext_info = response.get("ext_info")
        if not isinstance(ext_info, dict):
            return
        ref_idx = ext_info.get("ref_idx")
        if not isinstance(ref_idx, str) or not ref_idx:
            return
        self._ref_index.record_ref(
            account.app_id,
            ref_idx,
            QQBotRefIndexEntry(
                target=target,
                content=content,
                timestamp_ms=int(time.time() * 1000),
                is_bot=True,
            ),
        )


def _build_user_agent() -> str:
    return f"ControlMesh/{get_current_version()} (qqbot)"


def _materialize_account(
    *,
    account_key: str,
    account: QQBotAccountConfig,
    controlmesh_home: Path,
) -> QQBotRuntimeAccount:
    client_secret = account.client_secret
    if account.client_secret_file:
        secret_path = Path(account.client_secret_file)
        if not secret_path.is_absolute():
            secret_path = controlmesh_home / secret_path
        client_secret = secret_path.read_text(encoding="utf-8").strip()
    return QQBotRuntimeAccount(
        account_key=account_key,
        app_id=account.app_id,
        client_secret=client_secret,
        allow_from=tuple(account.allow_from),
        group_allow_from=tuple(account.group_allow_from),
        dm_policy=account.dm_policy,
        group_policy=account.group_policy,
        group_message_mode=account.group_message_mode,
        mention_patterns=tuple(account.mention_patterns),
        activate_on_bot_reply=account.activate_on_bot_reply,
    )


def _account_is_complete(account: QQBotAccountConfig) -> bool:
    return bool(account.app_id) and bool(account.client_secret or account.client_secret_file)


def _qualified_targets(kind: str, values: tuple[str, ...]) -> list[str]:
    return [f"qqbot:{kind}:{value}" for value in values if value and value != "*"]
