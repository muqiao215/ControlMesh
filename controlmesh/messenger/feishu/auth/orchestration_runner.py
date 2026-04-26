"""Runtime bridge for Feishu auth-kit orchestration cards and retries."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from controlmesh.config import AgentConfig
from controlmesh.integrations.feishu_auth_kit import run_feishu_auth_kit_json
from controlmesh.messenger.feishu.card_action_payload import extract_card_action_target
from controlmesh.messenger.feishu.auth.card_auth_context import build_card_auth_context
from controlmesh.messenger.feishu.auth.feishu_card_sender import FeishuCardSender
from controlmesh.messenger.feishu.auth.runtime_continuation import (
    FeishuAuthContinuationEntry,
    FeishuAuthRuntimeStore,
)

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.bot import FeishuIncomingText
    from controlmesh.messenger.feishu.tool_auth import FeishuNativeToolAuthContract

logger = logging.getLogger(__name__)

_PERMISSION_COMMANDS = frozenset({"/feishu_permission", "feishu permission", "飞书权限"})
_CONTINUE_ACTIONS = frozenset({"permissions_granted_continue", "app_auth_done"})


class FeishuAuthOrchestrationRunner:
    """Connect auth-kit permission cards, card actions, and synthetic retry injection."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        sender: FeishuCardSender,
        inject_retry: Callable[[FeishuAuthContinuationEntry, dict[str, Any]], Awaitable[None]],
        run_json: Callable[[list[str]], dict[str, Any]] = run_feishu_auth_kit_json,
    ) -> None:
        self._config = config
        self._sender = sender
        self._inject_retry = inject_retry
        self._run_json = run_json
        self._store = FeishuAuthRuntimeStore(config.controlmesh_home)
        self._tasks: set[asyncio.Task[None]] = set()

    async def handle_message(self, message: FeishuIncomingText) -> bool:
        parsed = _parse_permission_command(message.text)
        if parsed is None:
            return False
        await self.start_permission_flow(
            message,
            required_scopes=parsed.required_scopes,
            permission_url=parsed.permission_url,
            retry_text=parsed.retry_text,
        )
        return True

    async def start_permission_flow(
        self,
        message: FeishuIncomingText,
        *,
        required_scopes: list[str],
        permission_url: str,
        retry_text: str,
    ) -> FeishuAuthContinuationEntry:
        if not required_scopes:
            msg = "required_scopes must not be empty"
            raise ValueError(msg)
        if not permission_url:
            msg = "permission_url must not be empty"
            raise ValueError(msg)

        route = await self._run_json_async(
            [
                "orchestration",
                "route",
                "--app-id",
                self._config.feishu.app_id,
                "--error-kind",
                "app_scope_missing",
                "--user-open-id",
                message.sender_id,
                "--permission-url",
                permission_url,
                "--source",
                "controlmesh-feishu-runtime",
                "--continuation-store-path",
                _continuation_store_path(self._config),
                "--pending-flow-store-path",
                _pending_flow_store_path(self._config),
                *[
                    item
                    for scope in required_scopes
                    for item in ("--required-scope", scope)
                ],
            ]
        )
        operation_id = _operation_id_from_route(route)
        entry = FeishuAuthContinuationEntry(
            operation_id=operation_id,
            chat_id=message.chat_id,
            sender_open_id=message.sender_id,
            retry_text=retry_text,
            thread_id=message.thread_id,
            trigger_message_id=message.message_id,
        )
        self._store.save(entry)
        await self._bind_native_continuation(entry, source="controlmesh-feishu-runtime")
        context = build_card_auth_context(self._config, message)
        await self._sender.send_card(context, _feishu_card_from_auth_kit(route["card"]))
        return entry

    async def start_auth_requirement(
        self,
        message: FeishuIncomingText,
        requirement: FeishuNativeToolAuthContract,
    ) -> FeishuAuthContinuationEntry:
        if requirement.error_kind != "app_scope_missing":
            msg = f"Unsupported Feishu permission-card requirement: {requirement.error_kind}"
            raise ValueError(msg)
        if not requirement.permission_url:
            msg = "permission_url must not be empty"
            raise ValueError(msg)

        route = await self._run_json_async(
            [
                "orchestration",
                "route",
                "--app-id",
                self._config.feishu.app_id,
                "--error-kind",
                requirement.error_kind,
                "--user-open-id",
                message.sender_id,
                "--permission-url",
                requirement.permission_url,
                "--source",
                requirement.source,
                "--token-type",
                requirement.token_type,
                "--scope-need-type",
                requirement.scope_need_type,
                "--continuation-store-path",
                _continuation_store_path(self._config),
                "--pending-flow-store-path",
                _pending_flow_store_path(self._config),
                *([] if not requirement.operation_id else ["--operation-id", requirement.operation_id]),
                *([] if not requirement.flow_key else ["--flow-key", requirement.flow_key]),
                *[
                    item
                    for scope in requirement.required_scopes
                    for item in ("--required-scope", scope)
                ],
            ]
        )
        operation_id = _operation_id_from_route(route)
        entry = FeishuAuthContinuationEntry(
            operation_id=operation_id,
            chat_id=message.chat_id,
            sender_open_id=message.sender_id,
            retry_text=requirement.retry_text or message.text,
            thread_id=message.thread_id,
            trigger_message_id=message.message_id,
        )
        self._store.save(entry)
        await self._bind_native_continuation(entry, source=requirement.source)
        context = build_card_auth_context(self._config, message)
        await self._sender.send_card(context, _feishu_card_from_auth_kit(route["card"]))
        return entry

    def schedule_card_action(self, payload: dict[str, Any]) -> bool:
        parsed = _parse_card_action(payload)
        if parsed is None:
            return False
        task = asyncio.create_task(self._handle_card_action(parsed))
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return True

    async def handle_card_action_event(self, payload: dict[str, Any]) -> bool:
        parsed = _parse_card_action(payload)
        if parsed is None:
            return False
        await self._handle_card_action(parsed)
        return True

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _handle_card_action(self, parsed: _ParsedCardAction) -> None:
        entry = self._store.load(parsed.operation_id)
        if entry is None:
            logger.warning("Feishu auth continuation not found operation_id=%s", parsed.operation_id)
            return
        if parsed.operator_open_id and parsed.operator_open_id != entry.sender_open_id:
            logger.warning(
                "Ignoring Feishu auth continuation click by unexpected user operation_id=%s",
                parsed.operation_id,
            )
            return
        resolved = await self._resolve_action_to_retry(parsed)
        artifact = resolved.get("retry_artifact")
        if not isinstance(artifact, dict):
            msg = "auth-kit action-to-retry payload did not include retry_artifact"
            raise TypeError(msg)
        self._store.remove(parsed.operation_id)
        await self._inject_retry(entry, artifact)

    async def _run_json_async(self, args: list[str]) -> dict[str, Any]:
        return await asyncio.to_thread(self._run_json, args)

    async def _bind_native_continuation(
        self,
        entry: FeishuAuthContinuationEntry,
        *,
        source: str,
    ) -> dict[str, Any]:
        return await self._run_json_async(
            [
                "agent",
                "bind-continuation",
                "--operation-id",
                entry.operation_id,
                "--text",
                entry.retry_text,
                "--source",
                source,
                "--continuation-store-path",
                _continuation_store_path(self._config),
            ]
        )

    async def _resolve_action_to_retry(self, parsed: _ParsedCardAction) -> dict[str, Any]:
        return await asyncio.to_thread(self._run_action_to_retry_sync, parsed)

    def _run_action_to_retry_sync(self, parsed: _ParsedCardAction) -> dict[str, Any]:
        args = [
            "agent",
            "action-to-retry",
            "--operation-id",
            parsed.operation_id,
            "--action",
            parsed.action,
            "--continuation-store-path",
            _continuation_store_path(self._config),
        ]
        if parsed.operator_open_id:
            args.extend(["--actor-open-id", parsed.operator_open_id])
        if parsed.message_id:
            args.extend(["--message-id", parsed.message_id])
        if not parsed.payload:
            return self._run_json(args)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(parsed.payload, handle, ensure_ascii=False)
            handle.flush()
            return self._run_json([*args, "--payload-file", handle.name])

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Feishu auth orchestration task failed")


@dataclass(frozen=True, slots=True)
class _ParsedPermissionCommand:
    required_scopes: list[str]
    permission_url: str
    retry_text: str


@dataclass(frozen=True, slots=True)
class _ParsedCardAction:
    action: str
    operation_id: str
    operator_open_id: str | None = None
    message_id: str | None = None
    payload: dict[str, Any] | None = None


def _parse_permission_command(text: str) -> _ParsedPermissionCommand | None:
    stripped = text.strip()
    try:
        parts = shlex.split(stripped)
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0].lower() not in _PERMISSION_COMMANDS:
        return None
    return _parse_permission_command_parts(parts[1:])


def _parse_permission_command_parts(parts: list[str]) -> _ParsedPermissionCommand | None:
    scopes: list[str] = []
    permission_url = ""
    retry_text = "应用权限已开通, 请继续执行之前的操作。"
    index = 0
    while index < len(parts):
        key = parts[index]
        if key in {"--scope", "--required-scope"} and index + 1 < len(parts):
            scopes.extend(_split_csv(parts[index + 1]))
            index += 2
            continue
        if key in {"--url", "--permission-url"} and index + 1 < len(parts):
            permission_url = parts[index + 1]
            index += 2
            continue
        if key == "--text" and index + 1 < len(parts):
            retry_text = parts[index + 1]
            index += 2
            continue
        return None
    if not scopes or not permission_url:
        return None
    return _ParsedPermissionCommand(
        required_scopes=scopes,
        permission_url=permission_url,
        retry_text=retry_text,
    )


def _parse_card_action(payload: dict[str, Any]) -> _ParsedCardAction | None:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    if not isinstance(event, dict):
        return None
    action_obj = event.get("action")
    if not isinstance(action_obj, dict):
        return None
    value = action_obj.get("value")
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    operation_id = value.get("operation_id")
    if action not in _CONTINUE_ACTIONS or not isinstance(operation_id, str) or not operation_id:
        return None
    operator = event.get("operator")
    operator_open_id = None
    if isinstance(operator, dict):
        operator_open_id = operator.get("open_id")
        if not operator_open_id and isinstance(operator.get("operator_id"), dict):
            operator_open_id = operator["operator_id"].get("open_id")
    _, _, message_id = extract_card_action_target(event)
    action_payload = value if isinstance(value, dict) else {}
    return _ParsedCardAction(
        action=str(action),
        operation_id=operation_id,
        operator_open_id=operator_open_id if isinstance(operator_open_id, str) else None,
        message_id=message_id,
        payload=action_payload,
    )


def _operation_id_from_route(route: dict[str, Any]) -> str:
    flow = route.get("flow")
    if isinstance(flow, dict) and isinstance(flow.get("operation_id"), str):
        return flow["operation_id"]
    card = route.get("card")
    if isinstance(card, dict) and isinstance(card.get("operation_id"), str):
        return card["operation_id"]
    msg = "auth-kit route payload did not include an operation_id"
    raise RuntimeError(msg)


def _feishu_card_from_auth_kit(card: object) -> dict[str, Any]:
    if not isinstance(card, dict):
        msg = "auth-kit route payload did not include a card object"
        raise TypeError(msg)
    title = str(card.get("title") or "Feishu permissions required")
    message = str(card.get("message") or "Grant permissions, then continue.")
    if card.get("type") == "permission_missing":
        message = (
            f"{message}\n\n"
            "This is an app-level boundary handled by the app owner/admin, not user OAuth.\n"
            "After the app permissions are approved, come back here and tap continue / retry."
        )
    operation_id = str(card.get("operation_id") or "")
    fields = card.get("fields") if isinstance(card.get("fields"), dict) else {}
    missing_scopes = fields.get("missing_scopes") if isinstance(fields, dict) else []
    scopes = [str(scope) for scope in missing_scopes] if isinstance(missing_scopes, list) else []
    link_url = _first_link_url(card)
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "orange", "title": {"tag": "plain_text", "content": title}},
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"{message}\n\n"
                    f"Missing scopes: `{', '.join(scopes) if scopes else 'unknown'}`"
                ),
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "type": "primary",
                        "text": {"tag": "plain_text", "content": "Open permission page"},
                        "multi_url": {
                            "url": link_url,
                            "pc_url": link_url,
                            "android_url": link_url,
                            "ios_url": link_url,
                        },
                    },
                    {
                        "tag": "button",
                        "type": "default",
                        "text": {"tag": "plain_text", "content": "I have granted permissions"},
                        "value": {
                            "action": "permissions_granted_continue",
                            "operation_id": operation_id,
                        },
                    },
                ],
            },
        ],
    }


def _first_link_url(card: dict[str, Any]) -> str:
    links = card.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and isinstance(link.get("url"), str):
                return link["url"]
    return ""


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _auth_state_dir(config: AgentConfig) -> Path:
    return Path(config.controlmesh_home).expanduser() / "feishu_store" / "auth"


def _continuation_store_path(config: AgentConfig) -> str:
    return str(_auth_state_dir(config) / "continuations.json")


def _pending_flow_store_path(config: AgentConfig) -> str:
    return str(_auth_state_dir(config) / "pending_flows.json")
