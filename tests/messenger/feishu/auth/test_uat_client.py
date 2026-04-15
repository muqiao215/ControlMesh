"""Tests for Feishu user access token refresh helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

import pytest

from controlmesh.messenger.feishu.auth.errors import LARK_ERROR, FeishuAuthError
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore, StoredFeishuToken
from controlmesh.messenger.feishu.auth.uat_client import FeishuUATClient, UATClientConfig


@dataclass
class _FakeResponse:
    status: int
    payload: dict[str, Any]

    async def json(self, content_type: object | None = None) -> dict[str, Any]:
        return self.payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self._responses.popleft()


def _store_with_token(tmp_path: Path, *, expires_at: int = 1_000_100) -> FeishuTokenStore:
    store = FeishuTokenStore(tmp_path)
    store.save_token(
        StoredFeishuToken(
            user_open_id="ou_user",
            app_id="cli_app",
            access_token="access-old",
            refresh_token="refresh-old",
            expires_at=expires_at,
            refresh_expires_at=5_000_000,
            scope="offline_access docs:read",
            granted_at=1_000_000,
        )
    )
    return store


@pytest.mark.asyncio
async def test_get_valid_access_token_refreshes_when_needed(tmp_path: Path) -> None:
    store = _store_with_token(tmp_path)
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "access_token": "access-new",
                    "refresh_token": "refresh-new",
                    "expires_in": 7200,
                    "refresh_token_expires_in": 86400,
                    "scope": "offline_access docs:read",
                },
            )
        ]
    )
    client = FeishuUATClient(
        session,
        store,
        UATClientConfig(app_id="cli_app", app_secret="sec_app", brand="feishu"),
        now_ms=lambda: 1_000_000,
    )

    token = await client.get_valid_access_token("ou_user")

    assert token == "access-new"
    assert store.load_token("cli_app", "ou_user").access_token == "access-new"


@pytest.mark.asyncio
async def test_get_valid_access_token_refreshes_even_when_access_token_is_expired(
    tmp_path: Path,
) -> None:
    store = _store_with_token(tmp_path, expires_at=999_000)
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "access_token": "access-expired-refresh",
                    "refresh_token": "refresh-new",
                    "expires_in": 7200,
                    "refresh_token_expires_in": 86400,
                    "scope": "offline_access docs:read",
                },
            )
        ]
    )
    client = FeishuUATClient(
        session,
        store,
        UATClientConfig(app_id="cli_app", app_secret="sec_app", brand="feishu"),
        now_ms=lambda: 1_000_000,
    )

    token = await client.get_valid_access_token("ou_user")

    assert token == "access-expired-refresh"
    assert store.load_token("cli_app", "ou_user").access_token == "access-expired-refresh"


@pytest.mark.asyncio
async def test_call_with_token_retries_once_on_token_expiry(tmp_path: Path) -> None:
    store = _store_with_token(tmp_path, expires_at=2_000_000)
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "access_token": "access-new",
                    "refresh_token": "refresh-new",
                    "expires_in": 7200,
                    "refresh_token_expires_in": 86400,
                    "scope": "offline_access docs:read",
                },
            )
        ]
    )
    client = FeishuUATClient(
        session,
        store,
        UATClientConfig(app_id="cli_app", app_secret="sec_app", brand="feishu"),
        now_ms=lambda: 1_000_000,
    )
    seen: list[str] = []

    async def _api_call(access_token: str) -> str:
        seen.append(access_token)
        if len(seen) == 1:
            raise FeishuAuthError("expired", code=LARK_ERROR.TOKEN_EXPIRED)
        return f"ok:{access_token}"

    result = await client.call_with_token("ou_user", _api_call)

    assert result == "ok:access-new"
    assert seen == ["access-old", "access-new"]
