"""HTTP seam for the Weixin iLink Bot API."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, cast
from urllib.parse import urljoin
from uuid import uuid4

import aiohttp

from ductor_bot.config import WeixinConfig
from ductor_bot.messenger.weixin.auth_store import StoredWeixinCredentials
from ductor_bot.messenger.weixin.runtime import WeixinUpdateBatch


class WeixinIlinkApiError(Exception):
    """Raised for non-zero iLink API responses."""

    def __init__(self, message: str, *, status: int, code: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def is_session_expired(self) -> bool:
        return self.code == -14


class WeixinIlinkHttpClient:
    """Small aiohttp client that speaks the iLink getupdates/sendmessage shape."""

    def __init__(self, session: aiohttp.ClientSession, config: WeixinConfig) -> None:
        self._session = session
        self._config = config

    async def get_updates(
        self,
        credentials: StoredWeixinCredentials,
        cursor: str,
    ) -> WeixinUpdateBatch:
        payload = await self._post(
            credentials,
            "/ilink/bot/getupdates",
            {
                "get_updates_buf": cursor,
                "base_info": self._base_info(),
            },
            timeout_ms=self._config.longpoll_timeout_ms,
        )
        raw_messages = payload.get("msgs", [])
        messages = [dict(item) for item in raw_messages if isinstance(item, dict)]
        raw_cursor = payload.get("get_updates_buf")
        return WeixinUpdateBatch(
            cursor=raw_cursor if isinstance(raw_cursor, str) else cursor,
            messages=messages,
        )

    async def send_text(
        self,
        credentials: StoredWeixinCredentials,
        user_id: str,
        context_token: str,
        text: str,
    ) -> None:
        for chunk in _chunk_text(text, self._config.reply_chunk_chars):
            await self._post(
                credentials,
                "/ilink/bot/sendmessage",
                {
                    "msg": build_text_message(user_id, context_token, chunk),
                    "base_info": self._base_info(),
                },
                timeout_ms=15000,
            )

    async def _post(
        self,
        credentials: StoredWeixinCredentials,
        endpoint: str,
        body: dict[str, object],
        *,
        timeout_ms: int,
    ) -> dict[str, Any]:
        url = urljoin(f"{credentials.base_url.rstrip('/')}/", endpoint.lstrip("/"))
        timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)
        async with self._session.post(
            url,
            headers=build_headers(credentials.token),
            json=body,
            timeout=timeout,
        ) as response:
            return await _parse_json_response(response, endpoint)

    def _base_info(self) -> dict[str, str]:
        return {"channel_version": self._config.channel_version}


def build_text_message(
    user_id: str,
    context_token: str,
    text: str,
    *,
    client_id: str | None = None,
) -> dict[str, object]:
    """Build the iLink sendmessage `msg` object for a text reply."""
    return {
        "from_user_id": "",
        "to_user_id": user_id,
        "client_id": client_id or str(uuid4()),
        "message_type": 2,
        "message_state": 2,
        "context_token": context_token,
        "item_list": [
            {
                "type": 1,
                "text_item": {"text": text},
            }
        ],
    }


def build_headers(token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": _random_wechat_uin(),
    }


async def _parse_json_response(response: aiohttp.ClientResponse, label: str) -> dict[str, Any]:
    text = await response.text()
    payload = cast("dict[str, Any]", json.loads(text) if text else {})
    if response.status < 200 or response.status >= 300:
        raise WeixinIlinkApiError(
            str(payload.get("errmsg") or f"{label} failed with HTTP {response.status}"),
            status=response.status,
            code=_coerce_int(payload.get("errcode")),
        )
    ret = payload.get("ret")
    if isinstance(ret, int) and ret != 0:
        raise WeixinIlinkApiError(
            str(payload.get("errmsg") or f"{label} failed"),
            status=response.status,
            code=_coerce_int(payload.get("errcode", ret)),
        )
    return payload


def _random_wechat_uin() -> str:
    value = int.from_bytes(os.urandom(4), "big")
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0:
        return [text]
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)] or [text]


def _coerce_int(value: object) -> int | None:
    return value if isinstance(value, int) else None
