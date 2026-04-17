"""Tests for Feishu native-only OAPI tools and auth routing."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Self

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.app_info import FeishuAppInfoCache
from controlmesh.messenger.feishu.auth.errors import LARK_ERROR
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore, StoredFeishuToken
from controlmesh.messenger.feishu.native_tools import FeishuNativeToolExecutor
from controlmesh.messenger.feishu.tool_auth import (
    FeishuInboundContextV1,
    FeishuNativeToolAuthRequiredError,
)


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

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self._responses.popleft()

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._responses.popleft()


def _make_config(tmp_path: Any, **feishu_overrides: object) -> AgentConfig:
    feishu_config: dict[str, object] = {
        "mode": "bot_only",
        "brand": "feishu",
        "runtime_mode": "native",
        "app_id": "cli_123",
        "app_secret": "sec_456",
    }
    feishu_config.update(feishu_overrides)
    return AgentConfig(
        transport="feishu",
        transports=["feishu"],
        controlmesh_home=str(tmp_path),
        feishu=feishu_config,
    )


def _make_context() -> FeishuInboundContextV1:
    return FeishuInboundContextV1(
        app_id="cli_123",
        brand="feishu",
        runtime_mode="native",
        sender_open_id="ou_sender",
        chat_id="oc_chat_1",
        message_id="om_1",
        thread_id="omt_1",
    )


def _store_token(store: FeishuTokenStore, scope: str) -> None:
    store.save_token(
        StoredFeishuToken(
            user_open_id="ou_sender",
            app_id="cli_123",
            access_token="u_token",
            refresh_token="r_token",
            expires_at=9_999_999_999_000,
            refresh_expires_at=9_999_999_999_000,
            scope=scope,
            granted_at=1_000,
        )
    )


@pytest.mark.asyncio
async def test_contact_search_calls_oapi_client_with_user_token(tmp_path: Any) -> None:
    config = _make_config(tmp_path)
    store = FeishuTokenStore(tmp_path)
    _store_token(store, "contact:user:search offline_access")
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "app": {
                            "scopes": [
                                {"scope": "contact:user:search", "token_types": ["user"]},
                                {"scope": "offline_access", "token_types": ["user"]},
                            ]
                        }
                    },
                },
            ),
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "users": [
                            {
                                "name": "Alice",
                                "open_id": "ou_alice",
                                "department_names": ["Engineering"],
                            }
                        ],
                        "has_more": False,
                    },
                },
            ),
        ]
    )
    executor = FeishuNativeToolExecutor(
        config,
        session=session,
        token_store=store,
        app_info_cache=FeishuAppInfoCache(now_ms=lambda: 1_000_000),
        get_tenant_access_token=lambda: "tenant_token",
    )

    result = await executor.execute(
        "contact.search_user",
        {"query": "Alice", "page_size": 5},
        context=_make_context(),
    )

    assert result["users"][0]["name"] == "Alice"
    assert session.calls[1]["url"].endswith("/open-apis/search/v1/user")
    assert session.calls[1]["params"] == {"query": "Alice", "page_size": "5"}
    assert session.calls[1]["headers"]["Authorization"] == "Bearer u_token"


@pytest.mark.asyncio
async def test_contact_search_missing_app_scope_raises_standard_contract(tmp_path: Any) -> None:
    config = _make_config(tmp_path)
    store = FeishuTokenStore(tmp_path)
    _store_token(store, "contact:user:search offline_access")
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "app": {
                            "scopes": [
                                {"scope": "offline_access", "token_types": ["user"]},
                            ]
                        }
                    },
                },
            )
        ]
    )
    executor = FeishuNativeToolExecutor(
        config,
        session=session,
        token_store=store,
        app_info_cache=FeishuAppInfoCache(now_ms=lambda: 1_000_000),
        get_tenant_access_token=lambda: "tenant_token",
    )

    with pytest.raises(FeishuNativeToolAuthRequiredError) as exc_info:
        await executor.execute(
            "contact.search_user",
            {"query": "Alice"},
            context=_make_context(),
        )

    contract = exc_info.value.contract
    assert contract.error_kind == "app_scope_missing"
    assert contract.required_scopes == ("contact:user:search",)
    assert contract.permission_url == "https://open.feishu.cn/app/cli_123/permission"
    assert contract.token_type == "user"


@pytest.mark.asyncio
async def test_contact_get_missing_user_token_raises_standard_contract(tmp_path: Any) -> None:
    config = _make_config(tmp_path)
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "app": {
                            "scopes": [
                                {
                                    "scope": "contact:contact.base:readonly",
                                    "token_types": ["user"],
                                },
                                {
                                    "scope": "contact:user.base:readonly",
                                    "token_types": ["user"],
                                },
                                {"scope": "offline_access", "token_types": ["user"]},
                            ]
                        }
                    },
                },
            )
        ]
    )
    executor = FeishuNativeToolExecutor(
        config,
        session=session,
        token_store=FeishuTokenStore(tmp_path),
        app_info_cache=FeishuAppInfoCache(now_ms=lambda: 1_000_000),
        get_tenant_access_token=lambda: "tenant_token",
    )

    with pytest.raises(FeishuNativeToolAuthRequiredError) as exc_info:
        await executor.execute(
            "contact.get_user",
            {"user_id": "ou_target"},
            context=_make_context(),
        )

    contract = exc_info.value.contract
    assert contract.error_kind == "user_auth_required"
    assert contract.required_scopes == (
        "contact:contact.base:readonly",
        "contact:user.base:readonly",
    )


@pytest.mark.asyncio
async def test_contact_get_missing_user_scope_raises_standard_contract(tmp_path: Any) -> None:
    config = _make_config(tmp_path)
    store = FeishuTokenStore(tmp_path)
    _store_token(store, "contact:contact.base:readonly offline_access")
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "app": {
                            "scopes": [
                                {
                                    "scope": "contact:contact.base:readonly",
                                    "token_types": ["user"],
                                },
                                {
                                    "scope": "contact:user.base:readonly",
                                    "token_types": ["user"],
                                },
                                {"scope": "offline_access", "token_types": ["user"]},
                            ]
                        }
                    },
                },
            )
        ]
    )
    executor = FeishuNativeToolExecutor(
        config,
        session=session,
        token_store=store,
        app_info_cache=FeishuAppInfoCache(now_ms=lambda: 1_000_000),
        get_tenant_access_token=lambda: "tenant_token",
    )

    with pytest.raises(FeishuNativeToolAuthRequiredError) as exc_info:
        await executor.execute(
            "contact.get_user",
            {"user_id": "ou_target"},
            context=_make_context(),
        )

    contract = exc_info.value.contract
    assert contract.error_kind == "user_scope_insufficient"
    assert contract.required_scopes == ("contact:user.base:readonly",)


@pytest.mark.asyncio
async def test_im_get_messages_calls_oapi_client_with_user_token(tmp_path: Any) -> None:
    config = _make_config(tmp_path)
    store = FeishuTokenStore(tmp_path)
    _store_token(
        store,
        (
            "im:chat:read im:message:readonly im:message.group_msg:get_as_user "
            "im:message.p2p_msg:get_as_user offline_access"
        ),
    )
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "app": {
                            "scopes": [
                                {"scope": "im:chat:read", "token_types": ["user"]},
                                {"scope": "im:message:readonly", "token_types": ["user"]},
                                {"scope": "im:message.group_msg:get_as_user", "token_types": ["user"]},
                                {"scope": "im:message.p2p_msg:get_as_user", "token_types": ["user"]},
                                {"scope": "offline_access", "token_types": ["user"]},
                            ]
                        }
                    },
                },
            ),
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "items": [
                            {
                                "message_id": "om_msg_1",
                                "msg_type": "text",
                                "chat_id": "oc_chat_1",
                                "content": '{"text":"hello"}',
                                "create_time": "1710000000",
                            }
                        ],
                        "has_more": False,
                    },
                },
            ),
        ]
    )
    executor = FeishuNativeToolExecutor(
        config,
        session=session,
        token_store=store,
        app_info_cache=FeishuAppInfoCache(now_ms=lambda: 1_000_000),
        get_tenant_access_token=lambda: "tenant_token",
    )

    result = await executor.execute(
        "im.get_messages",
        {"chat_id": "oc_chat_1", "page_size": 10},
        context=_make_context(),
    )

    assert result["items"][0]["message_id"] == "om_msg_1"
    assert session.calls[1]["url"].endswith("/open-apis/im/v1/messages")
    assert session.calls[1]["params"]["container_id_type"] == "chat"
    assert session.calls[1]["params"]["container_id"] == "oc_chat_1"
    assert session.calls[1]["params"]["page_size"] == "10"
    assert session.calls[1]["headers"]["Authorization"] == "Bearer u_token"


@pytest.mark.asyncio
async def test_im_get_messages_missing_user_token_raises_standard_contract(tmp_path: Any) -> None:
    config = _make_config(tmp_path)
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "app": {
                            "scopes": [
                                {"scope": "im:chat:read", "token_types": ["user"]},
                                {"scope": "im:message:readonly", "token_types": ["user"]},
                                {"scope": "im:message.group_msg:get_as_user", "token_types": ["user"]},
                                {"scope": "im:message.p2p_msg:get_as_user", "token_types": ["user"]},
                                {"scope": "offline_access", "token_types": ["user"]},
                            ]
                        }
                    },
                },
            )
        ]
    )
    executor = FeishuNativeToolExecutor(
        config,
        session=session,
        token_store=FeishuTokenStore(tmp_path),
        app_info_cache=FeishuAppInfoCache(now_ms=lambda: 1_000_000),
        get_tenant_access_token=lambda: "tenant_token",
    )

    with pytest.raises(FeishuNativeToolAuthRequiredError) as exc_info:
        await executor.execute(
            "im.get_messages",
            {"chat_id": "oc_chat_1"},
            context=_make_context(),
        )

    contract = exc_info.value.contract
    assert contract.error_kind == "user_auth_required"
    assert contract.required_scopes == (
        "im:chat:read",
        "im:message:readonly",
        "im:message.group_msg:get_as_user",
        "im:message.p2p_msg:get_as_user",
    )


@pytest.mark.asyncio
async def test_im_get_messages_oapi_user_scope_error_is_translated(tmp_path: Any) -> None:
    config = _make_config(tmp_path)
    store = FeishuTokenStore(tmp_path)
    _store_token(
        store,
        (
            "im:chat:read im:message:readonly im:message.group_msg:get_as_user "
            "im:message.p2p_msg:get_as_user offline_access"
        ),
    )
    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "app": {
                            "scopes": [
                                {"scope": "im:chat:read", "token_types": ["user"]},
                                {"scope": "im:message:readonly", "token_types": ["user"]},
                                {"scope": "im:message.group_msg:get_as_user", "token_types": ["user"]},
                                {"scope": "im:message.p2p_msg:get_as_user", "token_types": ["user"]},
                                {"scope": "offline_access", "token_types": ["user"]},
                            ]
                        }
                    },
                },
            ),
            _FakeResponse(
                200,
                {
                    "code": LARK_ERROR.USER_SCOPE_INSUFFICIENT,
                    "msg": "scope insufficient",
                },
            ),
        ]
    )
    executor = FeishuNativeToolExecutor(
        config,
        session=session,
        token_store=store,
        app_info_cache=FeishuAppInfoCache(now_ms=lambda: 1_000_000),
        get_tenant_access_token=lambda: "tenant_token",
    )

    with pytest.raises(FeishuNativeToolAuthRequiredError) as exc_info:
        await executor.execute(
            "im.get_messages",
            {"chat_id": "oc_chat_1"},
            context=_make_context(),
        )

    contract = exc_info.value.contract
    assert contract.error_kind == "user_scope_insufficient"
    assert contract.required_scopes == (
        "im:chat:read",
        "im:message:readonly",
        "im:message.group_msg:get_as_user",
        "im:message.p2p_msg:get_as_user",
    )


@pytest.mark.asyncio
async def test_im_get_messages_oapi_app_scope_error_is_translated(tmp_path: Any) -> None:
    config = _make_config(tmp_path)
    store = FeishuTokenStore(tmp_path)
    _store_token(
        store,
        (
            "im:chat:read im:message:readonly im:message.group_msg:get_as_user "
            "im:message.p2p_msg:get_as_user offline_access"
        ),
    )
    session = _FakeSession(
        [
            _FakeResponse(403, {"code": 99999, "msg": "cannot inspect app"}),
            _FakeResponse(
                200,
                {
                    "code": LARK_ERROR.APP_SCOPE_MISSING,
                    "msg": "app scope missing",
                },
            ),
        ]
    )
    executor = FeishuNativeToolExecutor(
        config,
        session=session,
        token_store=store,
        app_info_cache=FeishuAppInfoCache(now_ms=lambda: 1_000_000),
        get_tenant_access_token=lambda: "tenant_token",
    )

    with pytest.raises(FeishuNativeToolAuthRequiredError) as exc_info:
        await executor.execute(
            "im.get_messages",
            {"chat_id": "oc_chat_1"},
            context=_make_context(),
        )

    contract = exc_info.value.contract
    assert contract.error_kind == "app_scope_missing"
    assert contract.required_scopes == (
        "im:chat:read",
        "im:message:readonly",
        "im:message.group_msg:get_as_user",
        "im:message.p2p_msg:get_as_user",
    )
