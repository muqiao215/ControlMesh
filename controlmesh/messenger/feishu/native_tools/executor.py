"""Executor seam for Feishu native-only OAPI tools."""

from __future__ import annotations

import inspect
import json
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.app_info import FeishuAppInfoCache, missing_scopes
from controlmesh.messenger.feishu.auth.brand import build_permission_url
from controlmesh.messenger.feishu.auth.errors import (
    LARK_ERROR,
    AppInfoAccessError,
    NeedAuthorizationError,
)
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore
from controlmesh.messenger.feishu.auth.uat_client import FeishuUATClient, UATClientConfig
from controlmesh.messenger.feishu.native_tools.agent_runtime import (
    FeishuNativeAgentToolSpec,
    get_native_agent_tool_spec,
    native_user_auth_scopes,
)
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

_USER_AUTH_KIND = "user"


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
        spec = _require_native_tool_spec(tool_name)
        if tool_name == "contact.search_user":
            return await self._contact_search_user(
                arguments,
                context=context,
                required_scopes=spec.required_scopes,
            )
        if tool_name == "contact.get_user":
            return await self._contact_get_user(
                arguments,
                context=context,
                required_scopes=spec.required_scopes,
            )
        if tool_name == "im.get_messages":
            return await self._im_get_messages(
                arguments,
                context=context,
                required_scopes=spec.required_scopes,
            )
        if tool_name == "drive.list_files":
            return await self._drive_list_files(
                arguments,
                context=context,
                required_scopes=spec.required_scopes,
            )
        msg = f"Unsupported Feishu native tool: {tool_name}"
        raise ValueError(msg)

    async def _contact_search_user(
        self,
        arguments: Mapping[str, Any],
        *,
        context: FeishuInboundContextV1,
        required_scopes: tuple[str, ...],
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
            required_scopes=required_scopes,
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
        required_scopes: tuple[str, ...],
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
            required_scopes=required_scopes,
            context=context,
            api_call=lambda token: self._oapi_client.get_json(
                f"/open-apis/contact/v3/users/{user_id}",
                access_token=token,
                params={"user_id_type": user_id_type},
            ),
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    async def _im_get_messages(
        self,
        arguments: Mapping[str, Any],
        *,
        context: FeishuInboundContextV1,
        required_scopes: tuple[str, ...],
    ) -> dict[str, Any]:
        chat_id = str(arguments.get("chat_id") or "").strip()
        if not chat_id:
            msg = "im.get_messages requires chat_id"
            raise ValueError(msg)
        raw_page_size = arguments.get("page_size", 20)
        page_size = max(1, min(int(raw_page_size), 50))
        sort_rule = str(arguments.get("sort_rule") or "create_time_desc").strip()
        sort_type = _sort_type(sort_rule)
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": str(page_size),
            "sort_type": sort_type,
            "card_msg_content_type": "raw_card_content",
        }
        page_token = str(arguments.get("page_token") or "").strip()
        if page_token:
            params["page_token"] = page_token
        start_time = str(arguments.get("start_time") or "").strip()
        end_time = str(arguments.get("end_time") or "").strip()
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        payload = await self._call_user_tool(
            tool_name="im.get_messages",
            required_scopes=required_scopes,
            context=context,
            api_call=lambda token: self._oapi_client.get_json(
                "/open-apis/im/v1/messages",
                access_token=token,
                params=params,
            ),
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    async def _drive_list_files(
        self,
        arguments: Mapping[str, Any],
        *,
        context: FeishuInboundContextV1,
        required_scopes: tuple[str, ...],
    ) -> dict[str, Any]:
        raw_page_size = arguments.get("page_size", 20)
        page_size = max(1, min(int(raw_page_size), 200))
        params = {"page_size": str(page_size)}
        folder_token = str(arguments.get("folder_token") or "").strip()
        page_token = str(arguments.get("page_token") or "").strip()
        order_by = str(arguments.get("order_by") or "").strip()
        direction = str(arguments.get("direction") or "").strip()
        if folder_token:
            params["folder_token"] = folder_token
        if page_token:
            params["page_token"] = page_token
        if order_by in {"EditedTime", "CreatedTime"}:
            params["order_by"] = order_by
        if direction in {"ASC", "DESC"}:
            params["direction"] = direction

        payload = await self._call_user_tool(
            tool_name="drive.list_files",
            required_scopes=required_scopes,
            context=context,
            api_call=lambda token: self._oapi_client.get_json(
                "/open-apis/drive/v1/files",
                access_token=token,
                params=params,
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
        app_check_scopes = tuple(dict.fromkeys((*business_scopes, "offline_access")))
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
                permission_url=_permission_url(self._config, required_scopes),
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


def parse_native_tool_command(text: str) -> NativeToolCommand | None:  # noqa: PLR0911
    """Parse the MVP Feishu native-tool smoke command."""
    try:
        parts = shlex.split(text.strip())
    except ValueError:
        return None
    if len(parts) < 2 or parts[0] not in {"/feishu-native", "/feishu_native"}:
        return None
    tool_name = parts[1]
    _require_native_tool_spec(tool_name)
    if tool_name == "contact.search_user":
        return _parse_contact_search_user(parts)
    if tool_name == "contact.get_user":
        return _parse_contact_get_user(parts)
    if tool_name == "im.get_messages":
        return _parse_im_get_messages(parts)
    if tool_name == "drive.list_files":
        return _parse_drive_list_files(parts)
    return None


def format_native_tool_result(tool_name: str, result: Mapping[str, Any]) -> str:
    """Render small native tool results for the explicit Feishu smoke command."""
    if tool_name == "contact.search_user":
        users = result.get("users")
        count = len(users) if isinstance(users, list) else 0
        return f"Feishu native tool contact.search_user returned {count} user(s).\n```json\n{_json(result)}\n```"
    if tool_name == "contact.get_user":
        return f"Feishu native tool contact.get_user returned:\n```json\n{_json(result)}\n```"
    if tool_name == "im.get_messages":
        items = result.get("items")
        count = len(items) if isinstance(items, list) else 0
        return f"Feishu native tool im.get_messages returned {count} message(s).\n```json\n{_json(result)}\n```"
    if tool_name == "drive.list_files":
        files = result.get("files")
        count = len(files) if isinstance(files, list) else 0
        return f"Feishu native tool drive.list_files returned {count} file(s).\n```json\n{_json(result)}\n```"
    return f"Feishu native tool {tool_name} returned:\n```json\n{_json(result)}\n```"


def _permission_url(config: AgentConfig, scopes: tuple[str, ...]) -> str:
    return build_permission_url(
        app_id=config.feishu.app_id,
        scopes=scopes,
        brand=config.feishu.brand,
        token_type=_USER_AUTH_KIND,
        op_from="controlmesh-feishu-native-tool",
    )


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def all_native_user_auth_scopes() -> tuple[str, ...]:
    """Return the deduped user-scope set needed by current native Feishu tools."""
    return native_user_auth_scopes()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _sort_type(rule: str) -> str:
    if rule == "create_time_asc":
        return "ByCreateTimeAsc"
    return "ByCreateTimeDesc"


def _require_native_tool_spec(tool_name: str) -> FeishuNativeAgentToolSpec:
    spec = get_native_agent_tool_spec(tool_name)
    if spec is None:
        msg = f"Unsupported Feishu native tool: {tool_name}"
        raise ValueError(msg)
    return spec


def _parse_contact_search_user(parts: list[str]) -> NativeToolCommand:
    if len(parts) < 3:
        msg = "Usage: /feishu-native contact.search_user <query>"
        raise ValueError(msg)
    return NativeToolCommand(tool_name="contact.search_user", arguments={"query": " ".join(parts[2:])})


def _parse_contact_get_user(parts: list[str]) -> NativeToolCommand:
    if len(parts) < 3:
        msg = "Usage: /feishu-native contact.get_user <open_id>"
        raise ValueError(msg)
    return NativeToolCommand(
        tool_name="contact.get_user",
        arguments={"user_id": parts[2], "user_id_type": parts[3] if len(parts) > 3 else "open_id"},
    )


def _parse_im_get_messages(parts: list[str]) -> NativeToolCommand:
    if len(parts) < 3:
        msg = "Usage: /feishu-native im.get_messages <chat_id> [page_size]"
        raise ValueError(msg)
    arguments: dict[str, Any] = {"chat_id": parts[2]}
    if len(parts) > 3:
        arguments["page_size"] = int(parts[3])
    return NativeToolCommand(tool_name="im.get_messages", arguments=arguments)


def _parse_drive_list_files(parts: list[str]) -> NativeToolCommand:
    arguments: dict[str, Any] = {}
    if len(parts) > 2:
        arguments["folder_token"] = parts[2]
    if len(parts) > 3:
        arguments["page_size"] = int(parts[3])
    return NativeToolCommand(tool_name="drive.list_files", arguments=arguments)
