"""Official QQ Bot HTTP API helpers."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from controlmesh.messenger.qqbot.target import parse_target

if TYPE_CHECKING:
    import aiohttp

_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
_API_BASE = "https://api.sgroup.qq.com"


@dataclass(frozen=True, slots=True)
class QQBotAccessToken:
    """Access token payload returned by the official QQ platform."""

    access_token: str
    expires_in: int
    expires_at: float


class QQBotApiError(RuntimeError):
    """HTTP or payload-level error from the official QQ API."""

    def __init__(self, message: str, *, status: int, path: str) -> None:
        super().__init__(message)
        self.status = status
        self.path = path


class QQBotMediaFileType(IntEnum):
    """Official QQ Bot media file type values."""

    IMAGE = 1
    FILE = 4


class QQBotApiClient:
    """Small aiohttp-backed client for the official QQ Bot APIs."""

    def __init__(self, session: aiohttp.ClientSession | Any, *, user_agent: str) -> None:
        self._session = session
        self._user_agent = user_agent
        self._msg_seq = 0

    async def fetch_access_token(self, app_id: str, client_secret: str) -> QQBotAccessToken:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self._user_agent,
        }
        async with self._session.post(
            _TOKEN_URL,
            json={"appId": app_id, "clientSecret": client_secret},
            headers=headers,
        ) as response:
            data = await _read_json(response, path="/app/getAppAccessToken")

        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 7200)
        if not isinstance(access_token, str) or not access_token:
            msg = "Official QQ token response did not contain access_token"
            raise QQBotApiError(msg, status=200, path="/app/getAppAccessToken")
        if not isinstance(expires_in, int):
            expires_in = 7200
        return QQBotAccessToken(
            access_token=access_token,
            expires_in=expires_in,
            expires_at=time.time() + expires_in,
        )

    async def fetch_gateway_url(self, access_token: str) -> str:
        async with self._session.get(
            f"{_API_BASE}/gateway",
            headers=self._auth_headers(access_token),
        ) as response:
            data = await _read_json(response, path="/gateway")
        url = data.get("url")
        if not isinstance(url, str) or not url:
            msg = "Official QQ gateway response did not contain url"
            raise QQBotApiError(msg, status=200, path="/gateway")
        return url

    async def send_text_message(
        self,
        access_token: str,
        target: str,
        text: str,
        *,
        msg_id: str | None = None,
        inline_keyboard: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        parsed = parse_target(target)
        if parsed.type == "c2c":
            path = f"/v2/users/{parsed.id}/messages"
            body: dict[str, Any] = {
                "content": text,
                "msg_type": 0,
                "msg_seq": self._next_msg_seq(),
            }
        elif parsed.type == "group":
            path = f"/v2/groups/{parsed.id}/messages"
            body = {
                "content": text,
                "msg_type": 0,
                "msg_seq": self._next_msg_seq(),
            }
        elif inline_keyboard is not None:
            msg = f"Official QQ inline keyboard send is not supported for target type {parsed.type!r}"
            raise ValueError(msg)
        elif parsed.type == "dm":
            path = f"/dms/{parsed.id}/messages"
            body = {"content": text}
        else:
            path = f"/channels/{parsed.id}/messages"
            body = {"content": text}
        if msg_id:
            body["msg_id"] = msg_id
        if inline_keyboard is not None:
            body["keyboard"] = inline_keyboard
        return await self._request_json(access_token, "POST", path, body)

    async def send_c2c_input_notify(
        self,
        access_token: str,
        openid: str,
        msg_id: str | None = None,
        input_second: int = 60,
    ) -> dict[str, str]:
        body: dict[str, Any] = {
            "msg_type": 6,
            "input_notify": {
                "input_type": 1,
                "input_second": input_second,
            },
            "msg_seq": self._next_msg_seq(),
        }
        if msg_id:
            body["msg_id"] = msg_id
        response = await self._request_json(
            access_token,
            "POST",
            f"/v2/users/{openid}/messages",
            body,
        )
        ext_info = response.get("ext_info")
        if not isinstance(ext_info, dict):
            return {}
        ref_idx = ext_info.get("ref_idx")
        if isinstance(ref_idx, str) and ref_idx:
            return {"ref_idx": ref_idx}
        return {}

    async def acknowledge_interaction(
        self,
        access_token: str,
        interaction_id: str,
        *,
        code: int = 0,
        data: dict[str, Any] | None = None,
    ) -> None:
        body: dict[str, Any] = {"code": code}
        if data:
            body["data"] = data
        await self._request_json(access_token, "PUT", f"/interactions/{interaction_id}", body)

    async def send_image_message(
        self,
        access_token: str,
        target: str,
        *,
        file_name: str,
        file_bytes: bytes,
        content: str | None = None,
        msg_id: str | None = None,
    ) -> dict[str, Any]:
        file_info = await self._upload_media(
            access_token,
            target,
            file_type=QQBotMediaFileType.IMAGE,
            file_bytes=file_bytes,
        )
        return await self._send_media_message(
            access_token,
            target,
            file_info,
            content=content,
            msg_id=msg_id,
        )

    async def send_file_message(
        self,
        access_token: str,
        target: str,
        *,
        file_name: str,
        file_bytes: bytes,
        content: str | None = None,
        msg_id: str | None = None,
    ) -> dict[str, Any]:
        file_info = await self._upload_media(
            access_token,
            target,
            file_type=QQBotMediaFileType.FILE,
            file_bytes=file_bytes,
            file_name=file_name,
        )
        return await self._send_media_message(
            access_token,
            target,
            file_info,
            content=content,
            msg_id=msg_id,
        )

    async def _upload_media(
        self,
        access_token: str,
        target: str,
        *,
        file_type: QQBotMediaFileType,
        file_bytes: bytes,
        file_name: str | None = None,
    ) -> str:
        parsed = parse_target(target)
        if parsed.type == "c2c":
            path = f"/v2/users/{parsed.id}/files"
        elif parsed.type == "group":
            path = f"/v2/groups/{parsed.id}/files"
        else:
            msg = f"Official QQ media upload is not supported for target type {parsed.type!r}"
            raise ValueError(msg)

        body: dict[str, Any] = {
            "file_type": int(file_type),
            "srv_send_msg": False,
            "file_data": base64.b64encode(file_bytes).decode("ascii"),
        }
        if file_type is QQBotMediaFileType.FILE and file_name:
            body["file_name"] = file_name

        data = await self._request_json(access_token, "POST", path, body)
        file_info = data.get("file_info")
        if not isinstance(file_info, str) or not file_info:
            msg = "Official QQ upload response did not contain file_info"
            raise QQBotApiError(msg, status=200, path=path)
        return file_info

    async def _send_media_message(
        self,
        access_token: str,
        target: str,
        file_info: str,
        *,
        content: str | None = None,
        msg_id: str | None = None,
    ) -> dict[str, Any]:
        parsed = parse_target(target)
        if parsed.type == "c2c":
            path = f"/v2/users/{parsed.id}/messages"
        elif parsed.type == "group":
            path = f"/v2/groups/{parsed.id}/messages"
        else:
            msg = f"Official QQ media send is not supported for target type {parsed.type!r}"
            raise ValueError(msg)
        body: dict[str, Any] = {
            "msg_type": 7,
            "media": {"file_info": file_info},
            "msg_seq": self._next_msg_seq(),
        }
        if content:
            body["content"] = content
        if msg_id:
            body["msg_id"] = msg_id
        return await self._request_json(access_token, "POST", path, body)

    async def _request_json(
        self,
        access_token: str,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = self._auth_headers(access_token)
        url = f"{_API_BASE}{path}"
        if method == "POST":
            request = self._session.post
        elif method == "PUT":
            request = self._session.put
        else:
            request = self._session.get
        kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        async with request(url, **kwargs) as response:
            return await _read_json(response, path=path)

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"QQBot {access_token}",
            "Content-Type": "application/json",
            "User-Agent": self._user_agent,
        }

    def _next_msg_seq(self) -> int:
        self._msg_seq = (self._msg_seq % 65535) + 1
        return self._msg_seq


async def _read_json(response: Any, *, path: str) -> dict[str, Any]:
    raw_body = await response.text()
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        msg = f"Official QQ API returned invalid JSON for {path}"
        raise QQBotApiError(msg, status=response.status, path=path) from exc
    if response.status >= 400:
        error_message = data.get("message") if isinstance(data, dict) else raw_body
        msg = f"Official QQ API request failed for {path}: {error_message}"
        raise QQBotApiError(msg, status=response.status, path=path)
    if not isinstance(data, dict):
        msg = f"Official QQ API returned non-object JSON for {path}"
        raise QQBotApiError(msg, status=response.status, path=path)
    return data
