"""Bridge the Feishu message surface into device-flow card auth."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.auth_cards import build_auth_failed_card
from controlmesh.messenger.feishu.auth.card_auth import (
    DeviceFlowCardAuthResult,
    DeviceFlowCardAuthStart,
    complete_device_flow_card_auth,
    start_device_flow_card_auth,
)
from controlmesh.messenger.feishu.auth.card_auth_context import (
    FeishuCardAuthContext,
    build_card_auth_context,
)
from controlmesh.messenger.feishu.auth.feishu_card_sender import FeishuCardHandle, FeishuCardSender
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.bot import FeishuIncomingText

logger = logging.getLogger(__name__)

_AUTH_COMMANDS = frozenset({"/feishu_auth", "feishu auth", "授权飞书", "登录飞书"})
_DUPLICATE_FLOW_TEXT = "已有进行中的飞书授权, 请先完成当前授权。"


def is_card_auth_command(text: str) -> bool:
    return text.strip().lower() in _AUTH_COMMANDS


async def verify_access_token_identity(
    session: Any,
    *,
    brand: str,
    access_token: str,
) -> str:
    domain = "https://open.larksuite.com" if brand == "lark" else "https://open.feishu.cn"
    url = f"{domain}/open-apis/authen/v1/user_info"
    async with session.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    ) as response:
        payload = await response.json(content_type=None)
        if response.status >= 400 or not isinstance(payload, dict) or payload.get("code") not in (None, 0):
            logger.warning("Feishu auth identity verification failed: payload=%s", payload)
            return ""
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return ""
    open_id = data.get("open_id")
    return open_id.strip() if isinstance(open_id, str) else ""


class FeishuCardAuthRunner:
    """Own the in-process device-flow card auth bridge and duplicate guard."""

    def __init__(  # noqa: PLR0913
        self,
        config: AgentConfig,
        *,
        session_factory: Callable[[], Awaitable[Any]],
        sender: FeishuCardSender,
        text_reply: Callable[[str, str, str | None], Awaitable[None]],
        start_auth: Callable[..., Awaitable[DeviceFlowCardAuthStart]] = start_device_flow_card_auth,
        complete_auth: Callable[..., Awaitable[DeviceFlowCardAuthResult]] = complete_device_flow_card_auth,
        identity_verifier: Callable[..., Awaitable[str]] | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._config = config
        self._session_factory = session_factory
        self._sender = sender
        self._text_reply = text_reply
        self._start_auth = start_auth
        self._complete_auth = complete_auth
        self._identity_verifier = identity_verifier
        self._now_ms = now_ms
        self._token_store = FeishuTokenStore(config.controlmesh_home)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def handle_message(self, message: FeishuIncomingText) -> bool:
        if not is_card_auth_command(message.text):
            return False

        context = build_card_auth_context(self._config, message)
        flow_key = self._flow_key(context)
        active_task = self._tasks.get(flow_key)
        if active_task is not None and not active_task.done():
            await self._text_reply(
                context.chat_id,
                _DUPLICATE_FLOW_TEXT,
                context.trigger_message_id,
            )
            return True

        session = await self._session_factory()
        sent_handle: FeishuCardHandle | None = None

        async def _send_initial_card(*, sender_open_id: str, card: dict[str, Any]) -> None:
            del sender_open_id
            nonlocal sent_handle
            sent_handle = await self._sender.send_card(context, card)

        start_result = await self._start_auth(
            session,
            app_id=context.app_id,
            app_secret=context.app_secret,
            sender_open_id=context.sender_open_id,
            brand=context.brand,
            send_card=_send_initial_card,
        )
        if sent_handle is None:
            msg = "Feishu auth card start did not produce a sent handle"
            raise RuntimeError(msg)

        task = asyncio.create_task(
            self._complete_flow(
                flow_key=flow_key,
                context=context,
                handle=sent_handle,
                authorization=start_result.authorization,
            )
        )
        self._tasks[flow_key] = task
        task.add_done_callback(lambda _: self._tasks.pop(flow_key, None))
        return True

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _complete_flow(
        self,
        *,
        flow_key: str,
        context: FeishuCardAuthContext,
        handle: FeishuCardHandle,
        authorization: Any,
    ) -> None:
        try:
            session = await self._session_factory()

            async def _verify_identity(*, access_token: str) -> str:
                if self._identity_verifier is not None:
                    return await self._identity_verifier(
                        session=session,
                        brand=context.brand,
                        access_token=access_token,
                    )
                return await verify_access_token_identity(
                    session,
                    brand=context.brand,
                    access_token=access_token,
                )

            async def _update_result_card(*, sender_open_id: str, card: dict[str, Any]) -> None:
                del sender_open_id
                await self._sender.update_card(handle, card)

            complete_kwargs: dict[str, Any] = {
                "app_id": context.app_id,
                "app_secret": context.app_secret,
                "sender_open_id": context.sender_open_id,
                "authorization": authorization,
                "token_store": self._token_store,
                "identity_verifier": _verify_identity,
                "brand": context.brand,
                "send_result_card": _update_result_card,
            }
            if self._now_ms is not None:
                complete_kwargs["now_ms"] = self._now_ms
            await self._complete_auth(session, **complete_kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Feishu card auth flow failed")
            await self._sender.update_card(handle, build_auth_failed_card(reason=str(exc)))
        finally:
            self._tasks.pop(flow_key, None)

    @staticmethod
    def _flow_key(context: FeishuCardAuthContext) -> str:
        return f"{context.app_id}:{context.sender_open_id}"
