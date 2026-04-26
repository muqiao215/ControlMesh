"""Feishu auth runner for broad user-scope auth with a fixed denylist."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from controlmesh.config import AgentConfig
from controlmesh.integrations.feishu_auth_kit import run_feishu_auth_kit_json
from controlmesh.messenger.feishu.auth.app_info import AppInfoAccessError, FeishuAppInfoCache
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore
from controlmesh.messenger.feishu.native_tools import all_native_user_auth_scopes

if False:  # pragma: no cover
    from controlmesh.messenger.feishu.bot import FeishuIncomingText

logger = logging.getLogger(__name__)

_AUTH_USEFUL_COMMANDS = frozenset(
    {
        "/feishu_auth_useful",
        "feishu_auth_useful",
        "feishu auth useful",
        "飞书实用授权",
        "飞书扩展授权",
    }
)
_DEFAULT_EXCLUDED_SCOPE_KEYWORDS = (
    "corehr:",
    "payroll:",
    "minutes:",
    "mail:",
    "email:",
    "okr:",
    "task:",
)
_AUTH_USEFUL_SUCCESS_TEXT = (
    "Feishu useful user permissions are ready.\n\n"
    "The excluded enterprise-heavy scope groups were skipped."
)


def is_native_auth_useful_command(text: str) -> bool:
    """Return True when the user is asking for the denylist-based bulk auth flow."""
    return text.strip().lower() in _AUTH_USEFUL_COMMANDS


def filter_useful_user_auth_scopes(
    scopes: Iterable[str],
    *,
    excluded_scope_keywords: Iterable[str] = _DEFAULT_EXCLUDED_SCOPE_KEYWORDS,
    preserve_scopes: Iterable[str] = (),
) -> list[str]:
    """Filter app user scopes by a fixed denylist while preserving hard requirements."""
    preserved = {str(scope).strip().lower() for scope in preserve_scopes if str(scope).strip()}
    excluded = tuple(
        keyword.strip().lower() for keyword in excluded_scope_keywords if keyword.strip()
    )
    filtered: list[str] = []
    seen: set[str] = set()
    for scope in scopes:
        normalized = str(scope).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        lowered = normalized.lower()
        if lowered not in preserved and any(keyword in lowered for keyword in excluded):
            continue
        filtered.append(normalized)
    return filtered


class FeishuNativeAuthUsefulRunner:
    """Authorize all currently granted user scopes except excluded enterprise domains."""

    def __init__(
        self,
        config: AgentConfig,
        *,
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
        excluded_scope_keywords: Iterable[str] = _DEFAULT_EXCLUDED_SCOPE_KEYWORDS,
    ) -> None:
        self._config = config
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
        self._excluded_scope_keywords = tuple(excluded_scope_keywords)
        self._preserve_scopes = all_native_user_auth_scopes()

    async def handle_message(self, message: FeishuIncomingText) -> bool:
        if self._config.feishu.runtime_mode != "native":
            return False
        if not is_native_auth_useful_command(message.text):
            return False

        app_scopes = await self._load_app_scopes()
        requested_scopes = filter_useful_user_auth_scopes(
            app_scopes,
            excluded_scope_keywords=self._excluded_scope_keywords,
            preserve_scopes=self._preserve_scopes,
        )
        if not requested_scopes:
            await self._text_reply(
                message.chat_id,
                _render_no_scopes_text(),
                message.message_id if self._config.feishu.reply_to_trigger else None,
            )
            return True

        user_scopes = self._load_user_scopes(message.sender_id)
        plan = await self._plan_scopes(
            requested_scopes=requested_scopes,
            app_scopes=app_scopes,
            user_scopes=user_scopes,
        )
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
            _AUTH_USEFUL_SUCCESS_TEXT,
            message.message_id if self._config.feishu.reply_to_trigger else None,
        )
        return True

    async def _load_app_scopes(self) -> list[str]:
        if self._get_app_scopes is not None:
            return _string_list(await _maybe_await(self._get_app_scopes()))
        if self._session_factory is None or self._get_tenant_access_token is None:
            return []
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
            logger.warning("Feishu auth-useful could not inspect app scopes")
            return []

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


def _render_no_scopes_text() -> str:
    return (
        "当前应用里没有需要补的非黑名单用户权限。\n\n"
        "这个命令会自动跳过邮件、HR、Payroll、Minutes、OKR、Tasks 这些重域。"
    )


def _render_user_scope_batch_text(*, scopes: list[str], batch_index: int, total_batches: int) -> str:
    scope_lines = "\n".join(f"- {scope}" for scope in scopes)
    return (
        f"开始飞书扩展用户授权, 第 {batch_index}/{total_batches} 批.\n\n"
        "这一步会发一张授权卡, 请按卡片完成授权.\n\n"
        "本批权限:\n"
        f"{scope_lines}"
    )
