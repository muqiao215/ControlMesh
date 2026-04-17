"""Tests for Feishu bot native-tool command routing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from controlmesh.messenger.feishu.bot import FeishuIncomingText
from controlmesh.messenger.feishu.tool_auth import (
    FeishuNativeToolAuthContract,
    FeishuNativeToolAuthRequiredError,
)

from .test_bot import _make_bot


class TestFeishuBotNativeTools:
    async def test_native_tool_command_routes_app_scope_auth_requirement(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, runtime_mode="native")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._auth_orchestration_runner = SimpleNamespace(
            handle_message=AsyncMock(return_value=False),
            start_auth_requirement=AsyncMock(return_value=True),
        )
        bot._native_tool_executor = SimpleNamespace(
            execute=AsyncMock(
                side_effect=FeishuNativeToolAuthRequiredError(
                    FeishuNativeToolAuthContract(
                        error_kind="app_scope_missing",
                        required_scopes=("contact:user:search",),
                        permission_url="https://open.feishu.cn/app/cli_123/permission",
                    )
                )
            )
        )
        bot._orchestrator = SimpleNamespace(handle_message_streaming=AsyncMock())

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="/feishu-native contact.search_user Alice",
                thread_id="omt_1",
            )
        )

        bot._native_tool_executor.execute.assert_awaited_once()
        bot._auth_orchestration_runner.start_auth_requirement.assert_awaited_once()
        bot._orchestrator.handle_message_streaming.assert_not_awaited()
        bot._send_text_to_chat_ref.assert_not_awaited()
