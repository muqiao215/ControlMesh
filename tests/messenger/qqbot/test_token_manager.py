from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

from controlmesh.messenger.qqbot.api import QQBotAccessToken
from controlmesh.messenger.qqbot.token_manager import QQBotTokenManager


async def test_reuses_cached_token_until_refresh_window() -> None:
    fetcher = AsyncMock(
        return_value=QQBotAccessToken(
            access_token="TOKEN123",
            expires_in=7200,
            expires_at=time.time() + 7200,
        )
    )
    manager = QQBotTokenManager(fetcher)

    first = await manager.get_access_token("1903891442", "secret")
    second = await manager.get_access_token("1903891442", "secret")

    assert first.access_token == "TOKEN123"
    assert second.access_token == "TOKEN123"
    fetcher.assert_awaited_once_with("1903891442", "secret")


async def test_dedupes_concurrent_fetches_per_app_id() -> None:
    started = asyncio.Event()
    unblock = asyncio.Event()

    async def _fetch(app_id: str, client_secret: str) -> QQBotAccessToken:
        assert app_id == "1903891442"
        assert client_secret == "secret"
        started.set()
        await unblock.wait()
        return QQBotAccessToken(
            access_token="TOKEN123",
            expires_in=7200,
            expires_at=time.time() + 7200,
        )

    fetcher = AsyncMock(side_effect=_fetch)
    manager = QQBotTokenManager(fetcher)

    first_task = asyncio.create_task(manager.get_access_token("1903891442", "secret"))
    await started.wait()
    second_task = asyncio.create_task(manager.get_access_token("1903891442", "secret"))

    unblock.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert first.access_token == "TOKEN123"
    assert second.access_token == "TOKEN123"
    fetcher.assert_awaited_once()


async def test_clear_cache_forces_refetch() -> None:
    fetcher = AsyncMock(
        side_effect=[
            QQBotAccessToken("TOKEN1", 7200, time.time() + 7200),
            QQBotAccessToken("TOKEN2", 7200, time.time() + 7200),
        ]
    )
    manager = QQBotTokenManager(fetcher)

    first = await manager.get_token_value("1903891442", "secret")
    manager.clear_cache("1903891442")
    second = await manager.get_token_value("1903891442", "secret")

    assert first == "TOKEN1"
    assert second == "TOKEN2"
    assert fetcher.await_count == 2
