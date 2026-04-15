"""Tests for Feishu OAuth device-flow helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Self

import pytest

from controlmesh.messenger.feishu.auth.device_flow import (
    poll_device_token,
    request_device_authorization,
)
from controlmesh.messenger.feishu.auth.errors import DeviceAccessDeniedError, DeviceCodeExpiredError


@dataclass
class _FakeResponse:
    status: int
    payload: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status < 400

    async def text(self) -> str:
        import json

        return json.dumps(self.payload)

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


@pytest.mark.asyncio
async def test_request_device_authorization_appends_offline_access() -> None:
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "device_code": "dc",
                    "user_code": "uc",
                    "verification_uri": "https://verify.test",
                    "verification_uri_complete": "https://verify.test/full",
                    "expires_in": 600,
                    "interval": 5,
                },
            )
        ]
    )

    result = await request_device_authorization(
        session,
        app_id="cli_app",
        app_secret="sec_app",
        brand="feishu",
        scope="docs:read",
    )

    assert result.device_code == "dc"
    assert result.user_code == "uc"
    assert session.calls[0]["url"] == "https://accounts.feishu.cn/oauth/v1/device_authorization"
    assert "offline_access" in session.calls[0]["data"]["scope"]
    assert session.calls[0]["auth"].login == "cli_app"


@pytest.mark.asyncio
async def test_poll_device_token_retries_pending_then_succeeds() -> None:
    session = _FakeSession(
        [
            _FakeResponse(200, {"error": "authorization_pending"}),
            _FakeResponse(
                200,
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 7200,
                    "refresh_token_expires_in": 86400,
                    "scope": "offline_access docs:read",
                },
            ),
        ]
    )
    sleeps: list[float] = []

    async def _sleep(delay: float) -> None:
        sleeps.append(delay)

    token = await poll_device_token(
        session,
        app_id="cli_app",
        app_secret="sec_app",
        brand="feishu",
        device_code="dc",
        interval=2,
        expires_in=60,
        sleep=_sleep,
    )

    assert token.access_token == "access"
    assert token.refresh_token == "refresh"
    assert sleeps == [2, 2]


@pytest.mark.asyncio
async def test_poll_device_token_raises_on_access_denied() -> None:
    session = _FakeSession([_FakeResponse(200, {"error": "access_denied"})])

    async def _sleep(_delay: float) -> None:
        return None

    with pytest.raises(DeviceAccessDeniedError):
        await poll_device_token(
            session,
            app_id="cli_app",
            app_secret="sec_app",
            brand="feishu",
            device_code="dc",
            interval=1,
            expires_in=60,
            sleep=_sleep,
        )


@pytest.mark.asyncio
async def test_poll_device_token_slows_down_before_retrying() -> None:
    session = _FakeSession(
        [
            _FakeResponse(200, {"error": "slow_down"}),
            _FakeResponse(
                200,
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 7200,
                    "refresh_token_expires_in": 86400,
                    "scope": "offline_access docs:read",
                },
            ),
        ]
    )
    sleeps: list[float] = []

    async def _sleep(delay: float) -> None:
        sleeps.append(delay)

    token = await poll_device_token(
        session,
        app_id="cli_app",
        app_secret="sec_app",
        brand="feishu",
        device_code="dc",
        interval=2,
        expires_in=60,
        sleep=_sleep,
    )

    assert token.access_token == "access"
    assert sleeps == [2, 7]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", ["expired_token", "invalid_grant"])
async def test_poll_device_token_raises_when_device_code_is_no_longer_valid(
    error_code: str,
) -> None:
    session = _FakeSession([_FakeResponse(200, {"error": error_code})])

    async def _sleep(_delay: float) -> None:
        return None

    with pytest.raises(DeviceCodeExpiredError) as exc_info:
        await poll_device_token(
            session,
            app_id="cli_app",
            app_secret="sec_app",
            brand="feishu",
            device_code="dc",
            interval=1,
            expires_in=60,
            sleep=_sleep,
        )

    assert exc_info.value.code == error_code
