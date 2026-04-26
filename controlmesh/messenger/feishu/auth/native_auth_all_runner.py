"""Feishu-native auth UX runner for batch/user-friendly slash commands."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from controlmesh.config import AgentConfig
from controlmesh.integrations.feishu_auth_kit import run_feishu_auth_kit_json
from controlmesh.messenger.feishu.auth.app_info import FeishuAppInfoCache
from controlmesh.messenger.feishu.auth.brand import build_permission_url
from controlmesh.messenger.feishu.auth.errors import AppInfoAccessError
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore
from controlmesh.messenger.feishu.native_tools import all_native_user_auth_scopes

if False:  # pragma: no cover
    from controlmesh.messenger.feishu.bot import FeishuIncomingText

logger = logging.getLogger(__name__)

_AUTH_ALL_COMMANDS = frozenset(
    {
        "/feishu_auth_all",
        "feishu_auth_all",
        "feishu auth all",
        "飞书全部授权",
        "飞书原生授权",
    }
)
_AUTH_ALL_SUCCESS_TEXT = (
    "Feishu native OAPI permissions are ready.\n\n"
    "Current native-only tools should now be able to reuse the stored auth path."
)


def is_native_auth_all_command(text: str) -> bool:
    """Return True when the user is explicitly asking to authorize all native scopes."""
    return text.strip().lower() in _AUTH_ALL_COMMANDS


class FeishuNativeAuthAllRunner:
    """Bridge a user-friendly slash command into auth-kit plan + runtime flows."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        start_app_permission_flow: Callable[..., Awaitable[None]],
        start_user_auth_flow: Callable[..., Awaitable[None]],
        text_reply: Callable[[str, str, str | None], Awaitable[None]],
        session_factory: Callable[[], Awaitable[Any]] | None = None,
        get_tenant_access_token: Callable[[], Awaitable[str]] | Callable[[], str] | None = None,
        get_app_scopes: Callable[[], Awaitable[list[str]]] | Callable[[], list[str]] | None = None,
        get_user_scopes: Callable[[str], list[str]] | None = None,
        run_json: Callable[[list[str]], dict[str, Any]] = run_feishu_auth_kit_json,
        app_info_cache: FeishuAppInfoCache | None = None,
        token_store: FeishuTokenStore | None = None,
        batch_size: int = 100,
    ) -> None:
        self._config = config
        self._start_app_permission_flow = start_app_permission_flow
        self._start_user_auth_flow = start_user_auth_flow
        self._text_reply = text_reply
        self._session_factory = session_factory
        self._get_tenant_access_token = get_tenant_access_token
        self._get_app_scopes = get_app_scopes
        self._get_user_scopes = get_user_scopes
        self._run_json = run_json
        self._app_info_cache = app_info_cache or FeishuAppInfoCache()
        self._token_store = token_store or FeishuTokenStore(config.controlmesh_home)
        self._batch_size = batch_size

    async def handle_message(self, message: FeishuIncomingText) -> bool:
        if self._config.feishu.runtime_mode != "native":
            return False
        if not is_native_auth_all_command(message.text):
            return False

        requested_scopes = list(all_native_user_auth_scopes())
        app_scopes = await self._load_app_scopes()
        user_scopes = self._load_user_scopes(message.sender_id)
        plan = await self._plan_scopes(
            requested_scopes=requested_scopes,
            app_scopes=app_scopes,
            user_scopes=user_scopes,
        )

        unavailable_scopes = _string_list(plan.get("unavailable_scopes"))
        if unavailable_scopes:
            permission_url = _permission_url(self._config, unavailable_scopes)
            await self._text_reply(
                message.chat_id,
                _render_app_scope_missing_text(
                    unavailable_scopes=unavailable_scopes,
                    permission_url=permission_url,
                ),
                message.message_id if self._config.feishu.reply_to_trigger else None,
            )
            await self._start_app_permission_flow(
                message,
                required_scopes=unavailable_scopes,
                permission_url=permission_url,
                retry_text=message.text,
            )
            return True

        batches = _list_of_string_lists(plan.get("batches"))
        next_batch = batches[0] if batches else _string_list(plan.get("missing_user_scopes"))
        if next_batch:
            await self._text_reply(
                message.chat_id,
                _render_user_scope_batch_text(
                    scopes=next_batch,
                    batch_index=1,
                    total_batches=len(batches) if batches else 1,
                ),
                message.message_id if self._config.feishu.reply_to_trigger else None,
            )
            await self._start_user_auth_flow(
                message,
                required_scopes=next_batch,
                retry_text=message.text,
            )
            return True

        await self._text_reply(
            message.chat_id,
            _AUTH_ALL_SUCCESS_TEXT,
            message.message_id if self._config.feishu.reply_to_trigger else None,
        )
        return True

    async def _load_app_scopes(self) -> list[str]:
        if self._get_app_scopes is not None:
            return _string_list(await _maybe_await(self._get_app_scopes()))
        if self._session_factory is None or self._get_tenant_access_token is None:
            return list(all_native_user_auth_scopes())
        try:
            session = await self._session_factory()
            tenant_access_token = await _maybe_await(self._get_tenant_access_token())
            return await self._app_info_cache.get_granted_scopes(
                session,
                brand=self._config.feishu.brand,
                tenant_access_token=tenant_access_token,
                app_id=self._config.feishu.app_id,
                token_type="user",
            )
        except AppInfoAccessError:
            logger.warning("Feishu auth-all could not inspect app scopes; falling back to optimistic planning")
            return list(all_native_user_auth_scopes())

    def _load_user_scopes(self, user_open_id: str) -> list[str]:
        if self._get_user_scopes is not None:
            return _string_list(self._get_user_scopes(user_open_id))
        stored = self._token_store.load_token(self._config.feishu.app_id, user_open_id)
        if stored is None:
            return []
        return [scope for scope in stored.scope.split() if scope]

    async def _plan_scopes(
        self,
        *,
        requested_scopes: list[str],
        app_scopes: list[str],
        user_scopes: list[str],
    ) -> dict[str, Any]:
        args = [
            "orchestration",
            "plan",
            "--batch-size",
            str(self._batch_size),
            *[item for scope in requested_scopes for item in ("--requested-scope", scope)],
            *[item for scope in app_scopes for item in ("--app-scope", scope)],
            *[item for scope in user_scopes for item in ("--user-scope", scope)],
        ]
        payload = await asyncio.to_thread(self._run_json, args)
        if not isinstance(payload, dict):
            msg = "feishu-auth-kit orchestration plan returned a non-object payload"
            raise TypeError(msg)
        return payload


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _permission_url(config: AgentConfig, scopes: list[str]) -> str:
    return build_permission_url(
        app_id=config.feishu.app_id,
        scopes=scopes,
        brand=config.feishu.brand,
        token_type="user",
        op_from="controlmesh-feishu-auth-all",
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _list_of_string_lists(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    batches: list[list[str]] = []
    for item in value:
        if isinstance(item, list):
            batch = [str(scope) for scope in item if str(scope).strip()]
            if batch:
                batches.append(batch)
    return batches


def _render_app_scope_missing_text(*, unavailable_scopes: list[str], permission_url: str) -> str:
    scope_lines = "\n".join(f"- {scope}" for scope in unavailable_scopes)
    return (
        "批量授权需要先补齐应用权限。\n\n"
        "请打开下面的飞书快捷授权页。页面会直接带上这次缺少的权限，不用再去开发者后台慢慢找：\n"
        f"{permission_url}\n\n"
        "缺少的应用权限：\n"
        f"{scope_lines}\n\n"
        "权限保存后，点卡片里的继续，或重新发 `/feishu_auth_all`。"
    )


def _render_user_scope_batch_text(*, scopes: list[str], batch_index: int, total_batches: int) -> str:
    scope_lines = "\n".join(f"- {scope}" for scope in scopes)
    return (
        f"开始飞书原生用户授权，第 {batch_index}/{total_batches} 批。\n\n"
        "这一步会发一张授权卡，请按卡片完成授权。\n\n"
        "本批权限：\n"
        f"{scope_lines}"
    )
