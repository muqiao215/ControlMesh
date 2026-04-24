"""Per-account token cache for the official QQ Bot runtime."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from controlmesh.messenger.qqbot.api import QQBotAccessToken

FetchAccessToken = Callable[[str, str], Awaitable[QQBotAccessToken]]


class QQBotTokenManager:
    """Caches official QQ access tokens with per-app singleflight fetches."""

    def __init__(self, fetch_access_token: FetchAccessToken) -> None:
        self._fetch_access_token = fetch_access_token
        self._cache: dict[str, QQBotAccessToken] = {}
        self._inflight: dict[str, asyncio.Task[QQBotAccessToken]] = {}
        self._guard = asyncio.Lock()

    async def get_access_token(
        self,
        app_id: str,
        client_secret: str,
        *,
        force_refresh: bool = False,
    ) -> QQBotAccessToken:
        normalized = app_id.strip()
        cached = self._cache.get(normalized)
        if not force_refresh and cached is not None and not _needs_refresh(cached):
            return cached

        async with self._guard:
            cached = self._cache.get(normalized)
            if not force_refresh and cached is not None and not _needs_refresh(cached):
                return cached

            task = self._inflight.get(normalized)
            if task is None:
                task = asyncio.create_task(
                    self._fetch_and_cache(normalized, client_secret),
                    name=f"qqbot-token:{normalized}",
                )
                self._inflight[normalized] = task

        return await task

    async def get_token_value(
        self,
        app_id: str,
        client_secret: str,
        *,
        force_refresh: bool = False,
    ) -> str:
        token = await self.get_access_token(app_id, client_secret, force_refresh=force_refresh)
        return token.access_token

    def clear_cache(self, app_id: str | None = None) -> None:
        if app_id is None:
            self._cache.clear()
            return
        self._cache.pop(app_id.strip(), None)

    async def _fetch_and_cache(self, app_id: str, client_secret: str) -> QQBotAccessToken:
        try:
            token = await self._fetch_access_token(app_id, client_secret)
            self._cache[app_id] = token
            return token
        finally:
            async with self._guard:
                self._inflight.pop(app_id, None)


def _needs_refresh(token: QQBotAccessToken) -> bool:
    remaining = token.expires_at - time.time()
    refresh_ahead = min(300.0, max(remaining / 3, 0.0))
    return remaining <= refresh_ahead
