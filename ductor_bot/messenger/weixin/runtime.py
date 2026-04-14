"""Minimal Weixin iLink long-poll runtime seam."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from ductor_bot.messenger.weixin.auth_store import StoredWeixinCredentials

_USER_MESSAGE_TYPE = 1
_TEXT_ITEM_TYPE = 1
_AUTHENTICATED = "authenticated"
_REAUTH_REQUIRED = "reauth_required"


class WeixinRuntimeError(RuntimeError):
    """Base runtime failure for Weixin iLink."""


class WeixinReauthRequiredError(WeixinRuntimeError):
    """Raised when the iLink session has expired and QR re-auth is required."""


class WeixinContextTokenRequiredError(WeixinRuntimeError):
    """Raised when no usable context token exists for a proactive send."""


@dataclass(frozen=True, slots=True)
class WeixinIncomingText:
    """Normalized inbound user text message from iLink getupdates."""

    user_id: str
    text: str
    context_token: str
    message_id: int
    raw: dict[str, object]


@dataclass(frozen=True, slots=True)
class WeixinUpdateBatch:
    """Normalized iLink getupdates response for runtime consumption."""

    cursor: str
    messages: list[dict[str, object]]


class WeixinIlinkClient(Protocol):
    """Network client contract used by the runtime skeleton."""

    async def get_updates(
        self,
        credentials: StoredWeixinCredentials,
        cursor: str,
    ) -> WeixinUpdateBatch: ...

    async def send_text(
        self,
        credentials: StoredWeixinCredentials,
        user_id: str,
        context_token: str,
        text: str,
    ) -> None: ...


TextHandler = Callable[[WeixinIncomingText], None | Awaitable[None]]
AuthExpiredHandler = Callable[[StoredWeixinCredentials], None | Awaitable[None]]


class WeixinLongPollRuntime:
    """Stateful iLink adapter for getupdates and context-token-aware text sends."""

    def __init__(
        self,
        *,
        credentials: StoredWeixinCredentials,
        client: WeixinIlinkClient,
        on_text: TextHandler,
        on_auth_expired: AuthExpiredHandler | None = None,
        cursor: str = "",
    ) -> None:
        self._credentials = credentials
        self._client = client
        self._on_text = on_text
        self._on_auth_expired = on_auth_expired
        self.cursor = cursor
        self._context_tokens: dict[str, str] = {}
        self._auth_state = _AUTHENTICATED

    @property
    def auth_state(self) -> str:
        return self._auth_state

    def context_token_for(self, user_id: str) -> str | None:
        return self._context_tokens.get(user_id)

    def remember_context(self, user_id: str, context_token: str) -> None:
        if user_id and context_token:
            self._context_tokens[user_id] = context_token

    def mark_reauth_required(self) -> None:
        self._auth_state = _REAUTH_REQUIRED
        self.cursor = ""
        self._context_tokens.clear()

    async def poll_once(self) -> None:
        try:
            batch = await self._client.get_updates(self._credentials, self.cursor)
        except Exception as exc:
            if getattr(exc, "is_session_expired", False):
                self.mark_reauth_required()
                if self._on_auth_expired is not None:
                    result = self._on_auth_expired(self._credentials)
                    if inspect.isawaitable(result):
                        await result
                raise WeixinReauthRequiredError("Weixin iLink session expired") from exc
            raise
        if batch.cursor:
            self.cursor = batch.cursor

        for raw in batch.messages:
            message = self._to_incoming_text(raw)
            if message is None:
                continue
            self.remember_context(message.user_id, message.context_token)
            result = self._on_text(message)
            if inspect.isawaitable(result):
                await result

    async def reply(self, message: WeixinIncomingText, text: str) -> None:
        self.remember_context(message.user_id, message.context_token)
        await self.send_text(message.user_id, text, context_token=message.context_token)

    async def send_text(
        self,
        user_id: str,
        text: str,
        *,
        context_token: str | None = None,
    ) -> None:
        if not text:
            raise ValueError("Weixin text replies cannot be empty")
        if self._auth_state != _AUTHENTICATED:
            raise WeixinReauthRequiredError("Weixin iLink session requires QR re-auth")
        resolved_context = context_token or self.context_token_for(user_id)
        if resolved_context is None:
            raise WeixinContextTokenRequiredError(f"No cached context token for user {user_id}")
        await self._client.send_text(self._credentials, user_id, resolved_context, text)

    @staticmethod
    def _to_incoming_text(raw: Mapping[str, object]) -> WeixinIncomingText | None:
        if raw.get("message_type") != _USER_MESSAGE_TYPE:
            return None

        user_id = raw.get("from_user_id")
        context_token = raw.get("context_token")
        message_id = raw.get("message_id")
        text = _extract_text(raw.get("item_list"))
        if (
            not isinstance(user_id, str)
            or not isinstance(context_token, str)
            or not isinstance(message_id, int)
            or not text
        ):
            return None
        return WeixinIncomingText(
            user_id=user_id,
            text=text,
            context_token=context_token,
            message_id=message_id,
            raw=dict(raw),
        )


def _extract_text(items: object) -> str:
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != _TEXT_ITEM_TYPE:
            continue
        text_item = item.get("text_item")
        if not isinstance(text_item, dict):
            continue
        text = text_item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)
