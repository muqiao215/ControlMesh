"""Refresh-aware wrappers around stored Feishu user access tokens."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from controlmesh.messenger.feishu.auth.brand import FeishuBrand, resolve_oauth_endpoints
from controlmesh.messenger.feishu.auth.errors import (
    LARK_ERROR,
    REFRESH_TOKEN_RETRYABLE,
    TOKEN_RETRY_CODES,
    NeedAuthorizationError,
    TokenRefreshError,
    extract_feishu_error_code,
)
from controlmesh.messenger.feishu.auth.token_store import (
    FeishuTokenStore,
    StoredFeishuToken,
    token_status,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(frozen=True, slots=True)
class UATClientConfig:
    app_id: str
    app_secret: str
    brand: FeishuBrand = "feishu"


class FeishuUATClient:
    """Wrapper that keeps token refresh and retry logic out of runtime flows."""

    def __init__(
        self,
        session: Any,
        store: FeishuTokenStore,
        config: UATClientConfig,
        *,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._session = session
        self._store = store
        self._config = config
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    async def get_valid_access_token(self, user_open_id: str) -> str:
        stored = self._require_token(user_open_id)
        status = token_status(stored, now_ms=self._now_ms())
        if status == "valid":
            return stored.access_token
        refreshed = await self.refresh_token(user_open_id)
        return refreshed.access_token

    async def refresh_token(self, user_open_id: str) -> StoredFeishuToken:
        key = self._store.account_key(self._config.app_id, user_open_id)
        lock = self._refresh_locks.setdefault(key, asyncio.Lock())
        async with lock:
            stored = self._require_token(user_open_id)
            if stored.refresh_expires_at <= self._now_ms():
                self._store.remove_token(self._config.app_id, user_open_id)
                raise NeedAuthorizationError(user_open_id)

            refreshed = await self._refresh_once(stored)
            self._store.save_token(refreshed)
            return refreshed

    async def call_with_token(
        self,
        user_open_id: str,
        api_call: Callable[[str], Awaitable[Any]],
    ) -> Any:
        token = await self.get_valid_access_token(user_open_id)
        try:
            return await api_call(token)
        except Exception as exc:
            if extract_feishu_error_code(exc) not in TOKEN_RETRY_CODES:
                raise
        refreshed = await self.refresh_token(user_open_id)
        return await api_call(refreshed.access_token)

    def _require_token(self, user_open_id: str) -> StoredFeishuToken:
        stored = self._store.load_token(self._config.app_id, user_open_id)
        if stored is None:
            raise NeedAuthorizationError(user_open_id)
        return stored

    async def _refresh_once(self, stored: StoredFeishuToken) -> StoredFeishuToken:
        endpoints = resolve_oauth_endpoints(self._config.brand)
        request = {
            "grant_type": "refresh_token",
            "refresh_token": stored.refresh_token,
            "client_id": self._config.app_id,
            "client_secret": self._config.app_secret,
        }
        data = await self._post_refresh(endpoints.token, request)
        code = data.get("code")
        error = data.get("error")

        if error or (code not in (None, 0)):
            if code in REFRESH_TOKEN_RETRYABLE:
                data = await self._post_refresh(endpoints.token, request)
                code = data.get("code")
                error = data.get("error")
            if error or (code not in (None, 0)):
                self._store.remove_token(self._config.app_id, stored.user_open_id)
                if code in {
                    LARK_ERROR.REFRESH_TOKEN_INVALID,
                    LARK_ERROR.REFRESH_TOKEN_EXPIRED,
                    LARK_ERROR.REFRESH_TOKEN_REVOKED,
                    LARK_ERROR.REFRESH_TOKEN_ALREADY_USED,
                } or error:
                    raise NeedAuthorizationError(stored.user_open_id)
                raise TokenRefreshError(
                    "refresh token request failed",
                    code=code or error,
                    payload=data,
                )

        access_token = data.get("access_token")
        if not access_token:
            raise TokenRefreshError("refresh token response missing access_token", payload=data)

        now_ms = self._now_ms()
        return StoredFeishuToken(
            user_open_id=stored.user_open_id,
            app_id=stored.app_id,
            access_token=str(access_token),
            refresh_token=str(data.get("refresh_token") or stored.refresh_token),
            expires_at=now_ms + int(data.get("expires_in", 7200)) * 1000,
            refresh_expires_at=(
                now_ms + int(data["refresh_token_expires_in"]) * 1000
                if data.get("refresh_token_expires_in") is not None
                else stored.refresh_expires_at
            ),
            scope=str(data.get("scope") or stored.scope),
            granted_at=stored.granted_at,
        )

    async def _post_refresh(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        async with self._session.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            payload = await response.json(content_type=None)
            if not isinstance(payload, dict):
                raise TokenRefreshError(
                    "refresh token response was not a JSON object",
                    status=response.status,
                )
            if response.status >= 400 and payload.get("error") is None and payload.get("code") is None:
                raise TokenRefreshError(
                    f"refresh token request failed with HTTP {response.status}",
                    status=response.status,
                    payload=payload,
                )
            return payload
