"""Tests for the Feishu native all-auth slash command runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.native_auth_all_runner import (
    FeishuNativeAuthAllRunner,
    is_native_auth_all_command,
)
from controlmesh.messenger.feishu.bot import FeishuIncomingText


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        transport="feishu",
        transports=["feishu"],
        controlmesh_home=str(tmp_path),
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "runtime_mode": "native",
            "app_id": "cli_app",
            "app_secret": "sec_app",
        },
    )


def _message(text: str = "/feishu_auth_all") -> FeishuIncomingText:
    return FeishuIncomingText(
        sender_id="ou_sender",
        chat_id="oc_chat_1",
        message_id="om_1",
        text=text,
        thread_id="omt_1",
    )


def test_is_native_auth_all_command_accepts_slash_underscore_and_chinese_aliases() -> None:
    assert is_native_auth_all_command("/feishu_auth_all") is True
    assert is_native_auth_all_command("feishu_auth_all") is True
    assert is_native_auth_all_command(" feishu auth all ") is True
    assert is_native_auth_all_command("飞书全部授权") is True
    assert is_native_auth_all_command("ping") is False


@pytest.mark.asyncio
async def test_auth_all_routes_missing_app_scopes_to_permission_card(tmp_path: Path) -> None:
    app_permission_calls: list[dict[str, Any]] = []
    user_auth_calls: list[dict[str, Any]] = []
    replies: list[tuple[str, str, str | None]] = []

    def _run_json(args: list[str]) -> dict[str, Any]:
        assert args[:2] == ["orchestration", "plan"]
        assert "contact:user:search" in ",".join(args)
        assert "im:message:readonly" in ",".join(args)
        return {
            "requested_scopes": ["offline_access", "contact:user:search"],
            "app_granted_scopes": ["offline_access"],
            "user_granted_scopes": [],
            "already_granted_scopes": [],
            "missing_user_scopes": ["offline_access"],
            "unavailable_scopes": ["contact:user:search"],
            "batches": [["offline_access"]],
        }

    async def _start_app_permission_flow(
        message: FeishuIncomingText,
        *,
        required_scopes: list[str],
        permission_url: str,
        retry_text: str,
    ) -> None:
        app_permission_calls.append(
            {
                "message": message,
                "required_scopes": required_scopes,
                "permission_url": permission_url,
                "retry_text": retry_text,
            }
        )

    async def _start_user_auth_flow(
        message: FeishuIncomingText,
        *,
        required_scopes: list[str],
        retry_text: str,
        operation_id: str = "",
    ) -> None:
        user_auth_calls.append(
            {
                "message": message,
                "required_scopes": required_scopes,
                "retry_text": retry_text,
                "operation_id": operation_id,
            }
        )

    runner = FeishuNativeAuthAllRunner(
        _config(tmp_path),
        get_app_scopes=lambda: ["offline_access"],
        get_user_scopes=lambda _open_id: [],
        start_app_permission_flow=_start_app_permission_flow,
        start_user_auth_flow=_start_user_auth_flow,
        text_reply=lambda chat_id, text, reply_to: _record_reply(replies, chat_id, text, reply_to),
        run_json=_run_json,
    )

    handled = await runner.handle_message(_message())

    assert handled is True
    assert replies[0][0] == "oc_chat_1"
    assert "批量授权需要先补齐应用权限" in replies[0][1]
    assert "/auth?q=contact%3Auser%3Asearch" in replies[0][1]
    assert "开发者后台" in replies[0][1]
    assert "contact:user:search" in replies[0][1]
    assert replies[0][2] == "om_1"
    assert app_permission_calls[0]["required_scopes"] == ["contact:user:search"]
    assert app_permission_calls[0]["retry_text"] == "/feishu_auth_all"
    assert (
        app_permission_calls[0]["permission_url"]
        == "https://open.feishu.cn/app/cli_app/auth?q=contact%3Auser%3Asearch&op_from=controlmesh-feishu-auth-all&token_type=user"
    )
    assert user_auth_calls == []


@pytest.mark.asyncio
async def test_auth_all_starts_first_user_scope_batch_when_app_scopes_are_ready(
    tmp_path: Path,
) -> None:
    user_auth_calls: list[dict[str, Any]] = []
    replies: list[tuple[str, str, str | None]] = []

    def _run_json(_args: list[str]) -> dict[str, Any]:
        return {
            "requested_scopes": ["contact:user:search", "im:message:readonly"],
            "app_granted_scopes": ["contact:user:search", "im:message:readonly"],
            "user_granted_scopes": [],
            "already_granted_scopes": [],
            "missing_user_scopes": ["contact:user:search", "im:message:readonly"],
            "unavailable_scopes": [],
            "batches": [["contact:user:search"], ["im:message:readonly"]],
        }

    async def _start_user_auth_flow(
        message: FeishuIncomingText,
        *,
        required_scopes: list[str],
        retry_text: str,
        operation_id: str = "",
    ) -> None:
        user_auth_calls.append(
            {
                "message": message,
                "required_scopes": required_scopes,
                "retry_text": retry_text,
                "operation_id": operation_id,
            }
        )

    runner = FeishuNativeAuthAllRunner(
        _config(tmp_path),
        get_app_scopes=lambda: ["contact:user:search", "im:message:readonly"],
        get_user_scopes=lambda _open_id: [],
        start_app_permission_flow=lambda *_args, **_kwargs: _return(None),
        start_user_auth_flow=_start_user_auth_flow,
        text_reply=lambda chat_id, text, reply_to: _record_reply(replies, chat_id, text, reply_to),
        run_json=_run_json,
    )

    handled = await runner.handle_message(_message())

    assert handled is True
    assert replies[0][0] == "oc_chat_1"
    assert "开始飞书原生用户授权，第 1/2 批" in replies[0][1]
    assert "contact:user:search" in replies[0][1]
    assert replies[0][2] == "om_1"
    assert user_auth_calls[0]["required_scopes"] == ["contact:user:search"]
    assert user_auth_calls[0]["retry_text"] == "/feishu_auth_all"


@pytest.mark.asyncio
async def test_auth_all_replies_when_all_native_scopes_are_already_authorized(
    tmp_path: Path,
) -> None:
    replies: list[tuple[str, str, str | None]] = []

    def _run_json(_args: list[str]) -> dict[str, Any]:
        return {
            "requested_scopes": ["offline_access"],
            "app_granted_scopes": ["offline_access"],
            "user_granted_scopes": ["offline_access"],
            "already_granted_scopes": ["offline_access"],
            "missing_user_scopes": [],
            "unavailable_scopes": [],
            "batches": [],
        }

    runner = FeishuNativeAuthAllRunner(
        _config(tmp_path),
        get_app_scopes=lambda: ["offline_access"],
        get_user_scopes=lambda _open_id: ["offline_access"],
        start_app_permission_flow=lambda *_args, **_kwargs: _return(None),
        start_user_auth_flow=lambda *_args, **_kwargs: _return(None),
        text_reply=lambda chat_id, text, reply_to: _record_reply(replies, chat_id, text, reply_to),
        run_json=_run_json,
    )

    handled = await runner.handle_message(_message())

    assert handled is True
    assert replies[0][0] == "oc_chat_1"
    assert "native OAPI permissions are ready" in replies[0][1]
    assert replies[0][2] == "om_1"


async def _return(value: Any) -> Any:
    return value


async def _record_reply(
    replies: list[tuple[str, str, str | None]],
    chat_id: str,
    text: str,
    reply_to: str | None,
) -> None:
    replies.append((chat_id, text, reply_to))
