"""Pure OAuth device-flow helpers for Feishu user authorization."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp

from controlmesh.messenger.feishu.auth.brand import FeishuBrand, resolve_oauth_endpoints
from controlmesh.messenger.feishu.auth.errors import (
    DeviceAccessDeniedError,
    DeviceAuthorizationError,
    DeviceCodeExpiredError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(frozen=True, slots=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass(frozen=True, slots=True)
class DeviceTokenGrant:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_token_expires_in: int
    scope: str


def _scope_with_offline_access(scope: str | None) -> str:
    parts = [part for part in (scope or "").split() if part]
    if "offline_access" not in parts:
        parts.append("offline_access")
    return " ".join(parts)


async def request_device_authorization(
    session: aiohttp.ClientSession | Any,
    *,
    app_id: str,
    app_secret: str,
    brand: FeishuBrand = "feishu",
    scope: str | None = None,
) -> DeviceAuthorization:
    endpoints = resolve_oauth_endpoints(brand)
    request_scope = _scope_with_offline_access(scope)
    async with session.post(
        endpoints.device_authorization,
        data={"client_id": app_id, "scope": request_scope},
        auth=aiohttp.BasicAuth(app_id, app_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        text = await response.text()
        try:
            data = await response.json(content_type=None)
        except Exception as exc:
            raise DeviceAuthorizationError(
                f"Device authorization failed: HTTP {response.status}",
                status=response.status,
            ) from exc

    if response.status >= 400 or data.get("error"):
        raise DeviceAuthorizationError(
            str(data.get("error_description") or data.get("error") or text[:200]),
            code=data.get("error"),
            status=response.status,
            payload=data,
        )

    return DeviceAuthorization(
        device_code=str(data["device_code"]),
        user_code=str(data["user_code"]),
        verification_uri=str(data["verification_uri"]),
        verification_uri_complete=str(
            data.get("verification_uri_complete") or data["verification_uri"]
        ),
        expires_in=int(data.get("expires_in", 240)),
        interval=int(data.get("interval", 5)),
    )


async def poll_device_token(  # noqa: PLR0913
    session: aiohttp.ClientSession | Any,
    *,
    app_id: str,
    app_secret: str,
    brand: FeishuBrand = "feishu",
    device_code: str,
    interval: int,
    expires_in: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> DeviceTokenGrant:
    endpoints = resolve_oauth_endpoints(brand)
    deadline = monotonic() + expires_in
    poll_interval = interval

    while monotonic() < deadline:
        await sleep(poll_interval)
        async with session.post(
            endpoints.token,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": app_id,
                "client_secret": app_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            data = await response.json(content_type=None)

        error = data.get("error")
        if not error and data.get("access_token"):
            refresh_token = str(data.get("refresh_token", ""))
            expires = int(data.get("expires_in", 7200))
            refresh_expires = int(data.get("refresh_token_expires_in", expires))
            return DeviceTokenGrant(
                access_token=str(data["access_token"]),
                refresh_token=refresh_token,
                expires_in=expires,
                refresh_token_expires_in=refresh_expires,
                scope=str(data.get("scope", "")),
            )

        if error == "authorization_pending":
            continue
        if error == "slow_down":
            poll_interval = min(poll_interval + 5, 60)
            continue
        if error == "access_denied":
            raise DeviceAccessDeniedError(
                "user denied device authorization",
                code="access_denied",
                payload=data,
            )
        if error in {"expired_token", "invalid_grant"}:
            raise DeviceCodeExpiredError(
                "device code expired",
                code=error,
                payload=data,
            )
        if response.status >= 400:
            raise DeviceAuthorizationError(
                f"device token polling failed with HTTP {response.status}",
                code=error,
                status=response.status,
                payload=data,
            )

        raise DeviceAuthorizationError(
            str(data.get("error_description") or error or "unknown device token error"),
            code=error,
            payload=data,
        )

    raise DeviceCodeExpiredError("device authorization timed out", code="expired_token")
