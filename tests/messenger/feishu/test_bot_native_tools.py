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

    async def test_native_im_tool_command_routes_user_auth_required_to_retryable_flow(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, runtime_mode="native")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._card_auth_runner = SimpleNamespace(
            handle_message=AsyncMock(return_value=False),
            start_retryable_auth_flow=AsyncMock(return_value=True),
        )
        bot._native_tool_executor = SimpleNamespace(
            execute=AsyncMock(
                side_effect=FeishuNativeToolAuthRequiredError(
                    FeishuNativeToolAuthContract(
                        error_kind="user_auth_required",
                        required_scopes=(
                            "im:chat:read",
                            "im:message:readonly",
                        ),
                    )
                )
            )
        )
        bot._orchestrator = SimpleNamespace(handle_message_streaming=AsyncMock())

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_2",
                text="/feishu-native im.get_messages oc_chat_1",
                thread_id="omt_1",
            )
        )

        bot._native_tool_executor.execute.assert_awaited_once()
        bot._card_auth_runner.start_retryable_auth_flow.assert_awaited_once()
        bot._orchestrator.handle_message_streaming.assert_not_awaited()
        bot._send_text_to_chat_ref.assert_not_awaited()

    async def test_native_im_tool_command_routes_user_scope_insufficient_to_retryable_flow(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, runtime_mode="native")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._card_auth_runner = SimpleNamespace(
            handle_message=AsyncMock(return_value=False),
            start_retryable_auth_flow=AsyncMock(return_value=True),
        )
        bot._native_tool_executor = SimpleNamespace(
            execute=AsyncMock(
                side_effect=FeishuNativeToolAuthRequiredError(
                    FeishuNativeToolAuthContract(
                        error_kind="user_scope_insufficient",
                        required_scopes=(
                            "im:chat:read",
                            "im:message:readonly",
                        ),
                    )
                )
            )
        )
        bot._orchestrator = SimpleNamespace(handle_message_streaming=AsyncMock())

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_4",
                text="/feishu-native im.get_messages oc_chat_1",
                thread_id="omt_1",
            )
        )

        bot._native_tool_executor.execute.assert_awaited_once()
        bot._card_auth_runner.start_retryable_auth_flow.assert_awaited_once()
        bot._orchestrator.handle_message_streaming.assert_not_awaited()
        bot._send_text_to_chat_ref.assert_not_awaited()

    async def test_native_auth_all_command_is_handled_before_orchestrator(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, runtime_mode="native")
        bot._native_auth_all_runner = SimpleNamespace(handle_message=AsyncMock(return_value=True))
        bot._orchestrator = SimpleNamespace(handle_message_streaming=AsyncMock())

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_3",
                text="/feishu_auth_all",
                thread_id="omt_1",
            )
        )

        bot._native_auth_all_runner.handle_message.assert_awaited_once()
        bot._orchestrator.handle_message_streaming.assert_not_awaited()
