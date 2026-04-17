"""Executor seam for Feishu native-only OAPI tools."""

from __future__ import annotations

import inspect
import json
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.app_info import (
    FeishuAppInfoCache,
    missing_scopes,
)
from controlmesh.messenger.feishu.auth.brand import open_platform_domain
from controlmesh.messenger.feishu.auth.errors import (
    LARK_ERROR,
    AppInfoAccessError,
    NeedAuthorizationError,
)
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore
from controlmesh.messenger.feishu.auth.uat_client import FeishuUATClient, UATClientConfig
from controlmesh.messenger.feishu.native_tools.client import (
    FeishuNativeOAPIClient,
    FeishuOAPIError,
)
from controlmesh.messenger.feishu.tool_auth import (
    FeishuInboundContextV1,
    FeishuNativeToolAuthContract,
    FeishuNativeToolAuthRequiredError,
    new_feishu_operation_id,
)

_OFFLINE_ACCESS = "offline_access"
_USER_AUTH_KIND = "user"

CONTACT_SEARCH_USER_SCOPES = ("contact:user:search",)
CONTACT_GET_USER_SCOPES = (
    "contact:contact.base:readonly",
    "contact:user.base:readonly",
)

_SUPPORTED_TOOLS = {
    "contact.search_user",
    "contact.get_user",
}


@dataclass(frozen=True, slots=True)
class NativeToolCommand:
    """Parsed Feishu native-tool smoke command."""

    tool_name: str
    arguments: dict[str, Any]


class FeishuNativeToolExecutor:
    """Execute the first Feishu native OAPI tools with standardized auth errors."""

    def __init__(  # noqa: PLR0913 - explicit seams keep the MVP easy to test.
        self,
        config: AgentConfig,
        *,
        session: Any,
        get_tenant_access_token: Callable[[], str] | Callable[[], Any],
        token_store: FeishuTokenStore | None = None,
        app_info_cache: FeishuAppInfoCache | None = None,
        oapi_client: FeishuNativeOAPIClient | None = None,
    ) -> None:
        self._config = config
        self._session = session
        self._get_tenant_access_token = get_tenant_access_token
        self._token_store = token_store or FeishuTokenStore(config.controlmesh_home)
        self._app_info_cache = app_info_cache or FeishuAppInfoCache()
        self._oapi_client = oapi_client or FeishuNativeOAPIClient(
            session,
            domain=config.feishu.domain,
        )
        self._uat_client = FeishuUATClient(
            session,
            self._token_store,
            UATClientConfig(
                app_id=config.feishu.app_id,
                app_secret=config.feishu.app_secret,
                brand=config.feishu.brand,
            ),
        )

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        context: FeishuInboundContextV1,
    ) -> dict[str, Any]:
        """Execute a native tool using the Feishu sender as user identity."""
        self._ensure_native_context(context)
        if tool_name == "contact.search_user":
            return await self._contact_search_user(arguments, context=context)
        if tool_name == "contact.get_user":
            return await self._contact_get_user(arguments, context=context)
        msg = f"Unsupported Feishu native tool: {tool_name}"
        raise ValueError(msg)

    async def _contact_search_user(
        self,
        arguments: Mapping[str, Any],
        *,
        context: FeishuInboundContextV1,
    ) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            msg = "contact.search_user requires query"
            raise ValueError(msg)
        raw_page_size = arguments.get("page_size", 20)
        page_size = max(1, min(int(raw_page_size), 200))
        params = {
            "query": query,
            "page_size": str(page_size),
        }
        page_token = str(arguments.get("page_token") or "").strip()
        if page_token:
            params["page_token"] = page_token

        payload = await self._call_user_tool(
            tool_name="contact.search_user",
            required_scopes=CONTACT_SEARCH_USER_SCOPES,
            context=context,
            api_call=lambda token: self._oapi_client.get_json(
                "/open-apis/search/v1/user",
                access_token=token,
                params=params,
            ),
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    async def _contact_get_user(
        self,
        arguments: Mapping[str, Any],
        *,
        context: FeishuInboundContextV1,
    ) -> dict[str, Any]:
        user_id = str(arguments.get("user_id") or "").strip()
        if not user_id:
            msg = "contact.get_user requires user_id"
            raise ValueError(msg)
        user_id_type = str(arguments.get("user_id_type") or "open_id").strip()
        if user_id_type not in {"open_id", "union_id", "user_id"}:
            msg = "contact.get_user user_id_type must be open_id, union_id, or user_id"
            raise ValueError(msg)

        payload = await self._call_user_tool(
            tool_name="contact.get_user",
            required_scopes=CONTACT_GET_USER_SCOPES,
            context=context,
            api_call=lambda token: self._oapi_client.get_json(
                f"/open-apis/contact/v3/users/{user_id}",
                access_token=token,
                params={"user_id_type": user_id_type},
            ),
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    async def _call_user_tool(
        self,
        *,
        tool_name: str,
        required_scopes: tuple[str, ...],
        context: FeishuInboundContextV1,
        api_call: Callable[[str], Any],
    ) -> dict[str, Any]:
        await self._ensure_app_scopes(
            tool_name=tool_name,
            business_scopes=required_scopes,
            context=context,
        )
        self._ensure_user_scopes(
            tool_name=tool_name,
            required_scopes=required_scopes,
            context=context,
        )
        try:
            payload = await self._uat_client.call_with_token(context.sender_open_id, api_call)
        except NeedAuthorizationError as exc:
            raise self._auth_required(
                "user_auth_required",
                tool_name=tool_name,
                required_scopes=required_scopes,
                context=context,
            ) from exc
        except FeishuOAPIError as exc:
            raise self._translate_oapi_auth_error(
                exc,
                tool_name=tool_name,
                required_scopes=required_scopes,
                context=context,
            ) from exc
        if not isinstance(payload, dict):
            msg = "Feishu native OAPI client returned non-dict payload"
            raise TypeError(msg)
        return payload

    async def _ensure_app_scopes(
        self,
        *,
        tool_name: str,
        business_scopes: tuple[str, ...],
        context: FeishuInboundContextV1,
    ) -> None:
        app_check_scopes = (*business_scopes, _OFFLINE_ACCESS)
        try:
            tenant_access_token = await _maybe_await(self._get_tenant_access_token())
            app_scopes = await self._app_info_cache.get_granted_scopes(
                self._session,
                brand=self._config.feishu.brand,
                tenant_access_token=tenant_access_token,
                app_id=self._config.feishu.app_id,
                token_type=_USER_AUTH_KIND,
            )
        except AppInfoAccessError:
            return
        missed = missing_scopes(app_scopes, list(app_check_scopes))
        if missed:
            raise self._auth_required(
                "app_scope_missing",
                tool_name=tool_name,
                required_scopes=tuple(missed),
                context=context,
            )

    def _ensure_user_scopes(
        self,
        *,
        tool_name: str,
        required_scopes: tuple[str, ...],
        context: FeishuInboundContextV1,
    ) -> None:
        stored = self._token_store.load_token(self._config.feishu.app_id, context.sender_open_id)
        if stored is None:
            raise self._auth_required(
                "user_auth_required",
                tool_name=tool_name,
                required_scopes=required_scopes,
                context=context,
            )
        granted = [scope for scope in stored.scope.split() if scope]
        missed = missing_scopes(granted, list(required_scopes))
        if missed:
            raise self._auth_required(
                "user_scope_insufficient",
                tool_name=tool_name,
                required_scopes=tuple(missed),
                context=context,
            )

    def _translate_oapi_auth_error(
        self,
        exc: FeishuOAPIError,
        *,
        tool_name: str,
        required_scopes: tuple[str, ...],
        context: FeishuInboundContextV1,
    ) -> FeishuNativeToolAuthRequiredError:
        if exc.code == LARK_ERROR.APP_SCOPE_MISSING:
            return self._auth_required(
                "app_scope_missing",
                tool_name=tool_name,
                required_scopes=required_scopes,
                context=context,
            )
        if exc.code == LARK_ERROR.USER_SCOPE_INSUFFICIENT:
            return self._auth_required(
                "user_scope_insufficient",
                tool_name=tool_name,
                required_scopes=required_scopes,
                context=context,
            )
        raise exc

    def _auth_required(
        self,
        error_kind: str,
        *,
        tool_name: str,
        required_scopes: tuple[str, ...],
        context: FeishuInboundContextV1,
    ) -> FeishuNativeToolAuthRequiredError:
        return FeishuNativeToolAuthRequiredError(
            FeishuNativeToolAuthContract(
                error_kind=error_kind,  # type: ignore[arg-type]
                required_scopes=required_scopes,
                permission_url=_permission_url(self._config),
                user_open_id=context.sender_open_id,
                operation_id=new_feishu_operation_id(),
                token_type=_USER_AUTH_KIND,
                scope_need_type="all",
                source=f"controlmesh-feishu-native-tool:{tool_name}",
            )
        )

    @staticmethod
    def _ensure_native_context(context: FeishuInboundContextV1) -> None:
        if context.runtime_mode != "native":
            msg = "Feishu native OAPI tools require feishu.runtime_mode=native"
            raise RuntimeError(msg)


def parse_native_tool_command(text: str) -> NativeToolCommand | None:
    """Parse the MVP Feishu native-tool smoke command."""
    try:
        parts = shlex.split(text.strip())
    except ValueError:
        return None
    if len(parts) < 2 or parts[0] not in {"/feishu-native", "/feishu_native"}:
        return None
    tool_name = parts[1]
    if tool_name not in _SUPPORTED_TOOLS:
        msg = f"Unsupported Feishu native tool: {tool_name}"
        raise ValueError(msg)
    if tool_name == "contact.search_user":
        if len(parts) < 3:
            msg = "Usage: /feishu-native contact.search_user <query>"
            raise ValueError(msg)
        return NativeToolCommand(tool_name=tool_name, arguments={"query": " ".join(parts[2:])})
    if tool_name == "contact.get_user":
        if len(parts) < 3:
            msg = "Usage: /feishu-native contact.get_user <open_id>"
            raise ValueError(msg)
        return NativeToolCommand(
            tool_name=tool_name,
            arguments={"user_id": parts[2], "user_id_type": parts[3] if len(parts) > 3 else "open_id"},
        )
    return None


def format_native_tool_result(tool_name: str, result: Mapping[str, Any]) -> str:
    """Render small native tool results for the explicit Feishu smoke command."""
    if tool_name == "contact.search_user":
        users = result.get("users")
        count = len(users) if isinstance(users, list) else 0
        return f"Feishu native tool contact.search_user returned {count} user(s).\n```json\n{_json(result)}\n```"
    if tool_name == "contact.get_user":
        return f"Feishu native tool contact.get_user returned:\n```json\n{_json(result)}\n```"
    return f"Feishu native tool {tool_name} returned:\n```json\n{_json(result)}\n```"


def _permission_url(config: AgentConfig) -> str:
    return f"{open_platform_domain(config.feishu.brand)}/app/{config.feishu.app_id}/permission"


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
