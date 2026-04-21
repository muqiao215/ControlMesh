"""Tests for the Feishu denylist-based bulk auth runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.native_auth_useful_runner import (
    FeishuNativeAuthUsefulRunner,
    filter_useful_user_auth_scopes,
    is_native_auth_useful_command,
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


def _message(text: str = "/feishu_auth_useful") -> FeishuIncomingText:
    return FeishuIncomingText(
        sender_id="ou_sender",
        chat_id="oc_chat_1",
        message_id="om_1",
        text=text,
        thread_id="omt_1",
    )


def test_is_native_auth_useful_command_accepts_expected_aliases() -> None:
    assert is_native_auth_useful_command("/feishu_auth_useful") is True
    assert is_native_auth_useful_command("feishu_auth_useful") is True
    assert is_native_auth_useful_command(" 飞书实用授权 ") is True
    assert is_native_auth_useful_command("ping") is False


def test_filter_useful_user_auth_scopes_excludes_blacklist_but_preserves_native_needs() -> None:
    scopes = [
        "mail:message:readonly",
        "payroll:payment:readonly",
        "contact:user:search",
        "offline_access",
    ]

    filtered = filter_useful_user_auth_scopes(
        scopes,
        preserve_scopes=("contact:user:search", "offline_access"),
    )

    assert filtered == ["contact:user:search", "offline_access"]


@pytest.mark.asyncio
async def test_auth_useful_starts_first_filtered_user_scope_batch(tmp_path: Path) -> None:
    user_auth_calls: list[dict[str, Any]] = []
    replies: list[tuple[str, str, str | None]] = []

    def _run_json(args: list[str]) -> dict[str, Any]:
        requested_scopes = [
            args[index + 1]
            for index, item in enumerate(args[:-1])
            if item == "--requested-scope"
        ]
        assert requested_scopes == ["contact:user:search", "space:document:retrieve"]
        return {
            "requested_scopes": ["contact:user:search", "space:document:retrieve"],
            "app_granted_scopes": [
                "mail:message:readonly",
                "contact:user:search",
                "space:document:retrieve",
            ],
            "user_granted_scopes": [],
            "already_granted_scopes": [],
            "missing_user_scopes": ["contact:user:search", "space:document:retrieve"],
            "unavailable_scopes": [],
            "batches": [["contact:user:search"], ["space:document:retrieve"]],
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

    runner = FeishuNativeAuthUsefulRunner(
        _config(tmp_path),
        get_app_scopes=lambda: [
            "mail:message:readonly",
            "payroll:payment:readonly",
            "contact:user:search",
            "space:document:retrieve",
        ],
        get_user_scopes=lambda _open_id: [],
        start_user_auth_flow=_start_user_auth_flow,
        text_reply=lambda chat_id, text, reply_to: _record_reply(replies, chat_id, text, reply_to),
        run_json=_run_json,
    )

    handled = await runner.handle_message(_message())

    assert handled is True
    assert "开始飞书扩展用户授权, 第 1/2 批." in replies[0][1]
    assert "contact:user:search" in replies[0][1]
    assert user_auth_calls[0]["required_scopes"] == ["contact:user:search"]
    assert user_auth_calls[0]["retry_text"] == "/feishu_auth_useful"


@pytest.mark.asyncio
async def test_auth_useful_replies_when_only_blacklisted_scopes_exist(tmp_path: Path) -> None:
    replies: list[tuple[str, str, str | None]] = []

    runner = FeishuNativeAuthUsefulRunner(
        _config(tmp_path),
        get_app_scopes=lambda: ["mail:message:readonly", "payroll:payment:readonly"],
        get_user_scopes=lambda _open_id: [],
        start_user_auth_flow=lambda *_args, **_kwargs: _return(None),
        text_reply=lambda chat_id, text, reply_to: _record_reply(replies, chat_id, text, reply_to),
    )

    handled = await runner.handle_message(_message())

    assert handled is True
    assert "没有需要补的非黑名单用户权限" in replies[0][1]


async def _return(value: Any) -> Any:
    return value


async def _record_reply(
    replies: list[tuple[str, str, str | None]],
    chat_id: str,
    text: str,
    reply_to: str | None,
) -> None:
    replies.append((chat_id, text, reply_to))
