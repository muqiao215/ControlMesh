"""Tests for Feishu app-info and granted-scope helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Self

import pytest

from controlmesh.messenger.feishu.auth.app_info import (
    FeishuAppInfoCache,
    intersect_scopes,
    is_app_scope_satisfied,
    missing_scopes,
)
from controlmesh.messenger.feishu.auth.errors import AppInfoAccessError


@dataclass
class _FakeResponse:
    status: int
    payload: dict[str, Any]

    async def json(self, content_type: object | None = None) -> dict[str, Any]:
        return self.payload

    async def text(self) -> str:
        import json

        return json.dumps(self.payload)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self._responses.popleft()


@pytest.mark.asyncio
async def test_get_app_info_caches_scopes_and_derives_owner() -> None:
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "app": {
                            "creator_id": "ou_creator",
                            "owner": {"owner_id": "ou_owner", "owner_type": 2},
                            "scopes": [
                                {"scope": "docs:read", "token_types": ["user"]},
                                {"scope": "calendar:read", "token_types": ["tenant"]},
                            ],
                        }
                    },
                },
            )
        ]
    )
    cache = FeishuAppInfoCache(now_ms=lambda: 1_000_000)

    app_info = await cache.get_app_info(
        session,
        brand="feishu",
        tenant_access_token="tenant-token",
        app_id="cli_app",
    )
    user_scopes = await cache.get_granted_scopes(
        session,
        brand="feishu",
        tenant_access_token="tenant-token",
        app_id="cli_app",
        token_type="user",
    )

    assert app_info.effective_owner_open_id == "ou_owner"
    assert user_scopes == ["docs:read"]
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_get_app_info_raises_on_permission_failure() -> None:
    session = _FakeSession([_FakeResponse(403, {"msg": "forbidden"})])
    cache = FeishuAppInfoCache(now_ms=lambda: 1_000_000)

    with pytest.raises(AppInfoAccessError):
        await cache.get_app_info(
            session,
            brand="feishu",
            tenant_access_token="tenant-token",
            app_id="cli_app",
        )


def test_scope_helpers_cover_intersection_missing_and_satisfaction() -> None:
    granted = ["docs:read", "calendar:read"]
    required = ["docs:read", "task:write"]

    assert intersect_scopes(granted, required) == ["docs:read"]
    assert missing_scopes(granted, required) == ["task:write"]
    assert is_app_scope_satisfied(granted, required, "one") is True
    assert is_app_scope_satisfied(granted, required, "all") is False


def test_empty_app_scopes_do_not_satisfy_non_empty_required_scopes() -> None:
    assert is_app_scope_satisfied([], ["docs:read"], "one") is False
    assert is_app_scope_satisfied([], ["docs:read"], "all") is False
    assert is_app_scope_satisfied([], [], "one") is True
