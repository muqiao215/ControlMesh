"""Tests for Feishu bot routing on async/task return paths."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.bot import FeishuBot, FeishuIncomingText
from controlmesh.messenger.feishu.bundled_runtime import BundledFeishuRuntimeTurn
from controlmesh.messenger.feishu.tool_auth import (
    FeishuNativeToolAuthContract,
    FeishuNativeToolAuthRequiredError,
)


@dataclass
class _FakeTaskResult:
    task_id: str = "t1"
    chat_id: int = 123
    parent_agent: str = "main"
    name: str = "research"
    prompt_preview: str = "find info"
    result_text: str = "found it"
    status: str = "done"
    elapsed_seconds: float = 5.0
    provider: str = "claude"
    model: str = "sonnet"
    session_id: str = "tsid1"
    error: str = ""
    task_folder: str = "/tmp/tasks/t1"
    original_prompt: str = "find info about X"
    thread_id: int | None = None


def _make_bot(
    tmp_path: Path,
    *,
    provider: str = "claude",
    model: str = "sonnet",
    **feishu_overrides: object,
) -> FeishuBot:
    feishu_config: dict[str, object] = {
        "mode": "bot_only",
        "brand": "feishu",
        "app_id": "cli_123",
        "app_secret": "sec_456",
    }
    feishu_config.update(feishu_overrides)
    config = AgentConfig(
        transport="feishu",
        transports=["feishu"],
        controlmesh_home=str(tmp_path),
        provider=provider,
        model=model,
        feishu=feishu_config,
    )
    bot = FeishuBot(config)
    bot.send_text = AsyncMock()  # type: ignore[method-assign]
    bot.broadcast_text = AsyncMock()  # type: ignore[method-assign]
    return bot


class TestFeishuBotRouting:
    async def test_handle_incoming_text_auth_command_routes_to_card_auth_runner(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._orchestrator = SimpleNamespace(
            handle_message=AsyncMock(return_value=SimpleNamespace(text="pong"))
        )
        bot._card_auth_runner = SimpleNamespace(handle_message=AsyncMock(return_value=True))

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="授权飞书",
                thread_id="omt_1",
            )
        )

        bot._card_auth_runner.handle_message.assert_awaited_once()
        bot._orchestrator.handle_message.assert_not_awaited()

    async def test_handle_incoming_event_normalizes_text_payload(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]
        create_time_ms = int(time.time() * 1000)

        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_1",
                "event_type": "im.message.receive_v1",
                "create_time": str(create_time_ms),
                "tenant_key": "tenant_1",
                "app_id": "cli_123",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_sender"}},
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_chat_1",
                    "thread_id": "omt_1",
                    "message_type": "text",
                    "content": '{"text":"hello from feishu"}',
                },
            },
        }

        await bot.handle_incoming_event(payload)

        bot.handle_incoming_text.assert_awaited_once_with(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="hello from feishu",
                thread_id="omt_1",
                create_time_ms=create_time_ms,
            )
        )

    async def test_handle_incoming_event_extracts_post_and_reply_thread_context(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]
        create_time_ms = int(time.time() * 1000)
        post_content = {
            "zh_cn": {
                "title": "项目更新",
                "content": [
                    [
                        {"tag": "text", "text": "请看 "},
                        {"tag": "a", "text": "文档", "href": "https://example.com/doc"},
                    ],
                    [{"tag": "at", "user_id": "ou_alice", "user_name": "Alice"}],
                ],
            },
            "quote": {"text": "上一条结论"},
        }

        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_1",
                "event_type": "im.message.receive_v1",
                "create_time": str(create_time_ms),
                "tenant_key": "tenant_1",
                "app_id": "cli_123",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_sender"}},
                "message": {
                    "message_id": "om_2",
                    "chat_id": "oc_chat_1",
                    "thread_id": "omt_thread",
                    "root_id": "om_root",
                    "parent_id": "om_parent",
                    "message_type": "post",
                    "content": json.dumps(post_content, ensure_ascii=False),
                },
            },
        }

        await bot.handle_incoming_event(payload)

        bot.handle_incoming_text.assert_awaited_once_with(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_2",
                text="**项目更新**\n\n请看 [文档](https://example.com/doc)\n@Alice",
                thread_id="omt_thread",
                create_time_ms=create_time_ms,
                message_type="post",
                root_id="om_root",
                parent_id="om_parent",
                quote_summary="上一条结论",
                post_title="项目更新",
            )
        )

    async def test_handle_incoming_text_passes_feishu_context_to_orchestrator(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="ok"))
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="继续处理",
                thread_id="omt_thread",
                message_type="post",
                root_id="om_root",
                parent_id="om_parent",
                quote_summary="上一条结论",
                post_title="项目更新",
            )
        )

        prompt = bot._orchestrator.handle_message_streaming.await_args.args[1]
        assert "[Feishu inbound context]" in prompt
        assert "message_type=post" in prompt
        assert "root_message_id=om_root" in prompt
        assert "parent_message_id=om_parent" in prompt
        assert "quote_summary=上一条结论" in prompt
        assert prompt.endswith("继续处理")

    async def test_handle_incoming_event_normalizes_image_payload(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]
        bot._resolve_incoming_media_text = AsyncMock(  # type: ignore[method-assign]
            return_value="[INCOMING FILE]\nPath: feishu_files/2026-04-17/photo.webp"
        )
        create_time_ms = int(time.time() * 1000)

        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_1",
                "event_type": "im.message.receive_v1",
                "create_time": str(create_time_ms),
                "tenant_key": "tenant_1",
                "app_id": "cli_123",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_sender"}},
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_chat_1",
                    "thread_id": "omt_1",
                    "message_type": "image",
                    "content": '{"image_key":"img_123"}',
                },
            },
        }

        await bot.handle_incoming_event(payload)

        bot._resolve_incoming_media_text.assert_awaited_once_with(
            message_id="om_1",
            message_type="image",
            raw_content='{"image_key":"img_123"}',
        )
        bot.handle_incoming_text.assert_awaited_once_with(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="[INCOMING FILE]\nPath: feishu_files/2026-04-17/photo.webp",
                thread_id="omt_1",
                create_time_ms=create_time_ms,
                message_type="image",
            )
        )

    async def test_handle_incoming_event_ignores_old_message_after_startup(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._process_start_time = 1710000005.0
        bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_1",
                "event_type": "im.message.receive_v1",
                "create_time": "1710000000000",
                "tenant_key": "tenant_1",
                "app_id": "cli_123",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_sender"}},
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_chat_1",
                    "thread_id": "omt_1",
                    "message_type": "text",
                    "content": '{"text":"hello from feishu"}',
                },
            },
        }

        await bot.handle_incoming_event(payload)

        bot.handle_incoming_text.assert_not_awaited()

    async def test_handle_incoming_event_routes_card_action_to_auth_orchestration_runner(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]
        routed: list[dict[str, object]] = []
        bot._auth_orchestration_runner = SimpleNamespace(
            schedule_card_action=lambda payload: routed.append(payload) or True
        )

        payload = {
            "schema": "2.0",
            "header": {"event_type": "card.action.trigger"},
            "event": {
                "operator": {"open_id": "ou_sender"},
                "action": {
                    "value": {
                        "action": "permissions_granted_continue",
                        "operation_id": "op_123",
                    }
                },
            },
        }

        await bot.handle_incoming_event(payload)

        assert routed == [payload]
        bot.handle_incoming_text.assert_not_awaited()

    async def test_handle_incoming_text_routes_to_orchestrator_and_replies(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong"))
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._orchestrator.handle_message_streaming.assert_awaited_once()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "pong",
            reply_to_message_id="om_1",
        )

    async def test_non_auth_message_still_routes_to_orchestrator_when_card_auth_runner_exists(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong"))
        )
        bot._card_auth_runner = SimpleNamespace(handle_message=AsyncMock(return_value=False))
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._card_auth_runner.handle_message.assert_awaited_once()
        bot._orchestrator.handle_message_streaming.assert_awaited_once()

    async def test_handle_incoming_text_deduplicates_same_message_id(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong"))
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        message = FeishuIncomingText(
            sender_id="ou_sender",
            chat_id="oc_chat_1",
            message_id="om_same",
            text="ping",
        )

        await bot.handle_incoming_text(message)
        await bot.handle_incoming_text(message)

        bot._orchestrator.handle_message_streaming.assert_awaited_once()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "pong",
            reply_to_message_id="om_same",
        )

    async def test_handle_incoming_text_deduplicates_inflight_same_content(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        started = asyncio.Event()
        release = asyncio.Event()

        async def _blocking_stream(*_args: object, **_kwargs: object) -> SimpleNamespace:
            started.set()
            await release.wait()
            return SimpleNamespace(text="pong")

        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(side_effect=_blocking_stream)
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        first = FeishuIncomingText(
            sender_id="ou_sender",
            chat_id="oc_chat_1",
            message_id="om_first",
            text="ping",
        )
        duplicate_content = FeishuIncomingText(
            sender_id="ou_sender",
            chat_id="oc_chat_1",
            message_id="om_second",
            text="ping",
        )

        first_task = asyncio.create_task(bot.handle_incoming_text(first))
        await asyncio.wait_for(started.wait(), timeout=1)

        await bot.handle_incoming_text(duplicate_content)

        bot._orchestrator.handle_message_streaming.assert_awaited_once()
        release.set()
        await first_task
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "pong",
            reply_to_message_id="om_first",
        )

    async def test_handle_incoming_text_deduplicates_recent_same_content(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong"))
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_first",
                text="ping",
            )
        )
        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_second",
                text="  ping\n",
            )
        )

        bot._orchestrator.handle_message_streaming.assert_awaited_once()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "pong",
            reply_to_message_id="om_first",
        )

    async def test_handle_incoming_text_emits_progress_feedback_during_streaming(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        sent: list[tuple[str, str, str | None]] = []

        async def _fake_send(
            chat_ref: str,
            text: str,
            *,
            reply_to_message_id: str | None = None,
        ) -> None:
            sent.append((chat_ref, text, reply_to_message_id))

        async def _fake_stream(
            _key: object,
            _text: str,
            *,
            on_tool_activity: AsyncMock | None = None,
            on_system_status: AsyncMock | None = None,
            **_kwargs: object,
        ) -> SimpleNamespace:
            assert on_system_status is not None
            assert on_tool_activity is not None
            await on_system_status("thinking")
            await on_system_status("thinking")
            await on_tool_activity("Shell")
            return SimpleNamespace(text="pong")

        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(side_effect=_fake_stream)
        )
        bot._send_text_to_chat_ref = AsyncMock(side_effect=_fake_send)  # type: ignore[method-assign]

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        assert sent == [
            ("oc_chat_1", "处理中...", "om_1"),
            ("oc_chat_1", "[TOOL: Shell]", "om_1"),
            ("oc_chat_1", "pong", "om_1"),
        ]

    async def test_handle_incoming_text_app_scope_missing_routes_to_native_permission_flow(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._auth_orchestration_runner = SimpleNamespace(
            handle_message=AsyncMock(return_value=False),
            start_auth_requirement=AsyncMock(return_value=True),
        )
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(
                side_effect=FeishuNativeToolAuthRequiredError(
                    FeishuNativeToolAuthContract(
                        error_kind="app_scope_missing",
                        required_scopes=("im:message",),
                        permission_url="https://open.feishu.cn/perm",
                        retry_text="继续原来的任务",
                    )
                )
            )
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
                thread_id="omt_1",
            )
        )

        bot._auth_orchestration_runner.start_auth_requirement.assert_awaited_once()
        call = bot._auth_orchestration_runner.start_auth_requirement.await_args
        assert call.args[0].message_id == "om_1"
        assert call.args[1].error_kind == "app_scope_missing"
        bot._send_text_to_chat_ref.assert_not_awaited()

    async def test_handle_incoming_text_user_auth_required_routes_to_retryable_device_flow(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._card_auth_runner = SimpleNamespace(
            handle_message=AsyncMock(return_value=False),
            start_retryable_auth_flow=AsyncMock(return_value=True),
        )
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(
                side_effect=FeishuNativeToolAuthRequiredError(
                    FeishuNativeToolAuthContract(
                        error_kind="user_auth_required",
                        required_scopes=("offline_access", "im:message"),
                        retry_text="继续原来的任务",
                    )
                )
            )
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
                thread_id="omt_1",
            )
        )

        bot._card_auth_runner.start_retryable_auth_flow.assert_awaited_once()
        call = bot._card_auth_runner.start_retryable_auth_flow.await_args
        assert call.args[0].message_id == "om_1"
        assert call.kwargs["required_scopes"] == ["offline_access", "im:message"]
        assert call.kwargs["retry_text"] == "继续原来的任务"
        bot._send_text_to_chat_ref.assert_not_awaited()

    async def test_shutdown_awaits_card_auth_runner(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot._card_auth_runner = SimpleNamespace(shutdown=AsyncMock())

        await bot.shutdown()

        bot._card_auth_runner.shutdown.assert_awaited_once()

    async def test_handle_incoming_text_card_preview_mode_reuses_single_message(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, progress_mode="card_preview")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._send_card_to_chat_ref = AsyncMock(return_value="om_preview")  # type: ignore[attr-defined]
        bot._patch_message = AsyncMock()  # type: ignore[attr-defined]

        async def _fake_stream(
            _key: object,
            _text: str,
            *,
            on_tool_activity: AsyncMock | None = None,
            on_system_status: AsyncMock | None = None,
            **_kwargs: object,
        ) -> SimpleNamespace:
            assert on_system_status is not None
            assert on_tool_activity is not None
            await on_system_status("thinking")
            await on_tool_activity("Shell")
            return SimpleNamespace(text="pong")

        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(side_effect=_fake_stream)
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._send_card_to_chat_ref.assert_awaited_once()
        send_kwargs = bot._send_card_to_chat_ref.await_args.kwargs
        assert send_kwargs["reply_to_message_id"] == "om_1"
        bot._patch_message.assert_awaited()
        for call in bot._patch_message.await_args_list:
            assert call.args[0] == "om_preview"
        final_content = bot._patch_message.await_args_list[-1].kwargs["content"]
        assert isinstance(final_content, dict)
        assert "pong" in str(final_content)
        bot._send_text_to_chat_ref.assert_not_awaited()

    async def test_handle_incoming_text_card_preview_mode_finalizes_failure_on_same_message(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, progress_mode="card_preview")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._send_card_to_chat_ref = AsyncMock(return_value="om_preview")  # type: ignore[attr-defined]
        bot._patch_message = AsyncMock()  # type: ignore[attr-defined]

        async def _failing_stream(
            _key: object,
            _text: str,
            *,
            _on_tool_activity: AsyncMock | None = None,
            on_system_status: AsyncMock | None = None,
            **_kwargs: object,
        ) -> SimpleNamespace:
            assert on_system_status is not None
            await on_system_status("thinking")
            raise RuntimeError("boom")

        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(side_effect=_failing_stream)
        )

        with pytest.raises(RuntimeError, match="boom"):
            await bot.handle_incoming_text(
                FeishuIncomingText(
                    sender_id="ou_sender",
                    chat_id="oc_chat_1",
                    message_id="om_1",
                    text="ping",
                )
            )

        bot._send_card_to_chat_ref.assert_awaited_once()
        bot._patch_message.assert_awaited()
        final_content = bot._patch_message.await_args.kwargs["content"]
        assert isinstance(final_content, dict)
        assert "boom" in str(final_content)
        bot._send_text_to_chat_ref.assert_not_awaited()

    async def test_handle_incoming_text_card_preview_mode_does_not_resend_preview_when_initial_send_has_no_message_id(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, progress_mode="card_preview")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._send_card_to_chat_ref = AsyncMock(return_value=None)  # type: ignore[attr-defined]
        bot._patch_message = AsyncMock()  # type: ignore[attr-defined]

        async def _fake_stream(
            _key: object,
            _text: str,
            *,
            on_tool_activity: AsyncMock | None = None,
            on_system_status: AsyncMock | None = None,
            **_kwargs: object,
        ) -> SimpleNamespace:
            assert on_system_status is not None
            assert on_tool_activity is not None
            await on_system_status("thinking")
            await on_tool_activity("Shell")
            return SimpleNamespace(text="pong")

        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(side_effect=_fake_stream)
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._send_card_to_chat_ref.assert_awaited_once()
        bot._patch_message.assert_not_awaited()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "pong",
            reply_to_message_id="om_1",
        )

    async def test_handle_incoming_text_card_stream_mode_uses_text_delta_callback(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, runtime_mode="native", progress_mode="card_stream")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._create_streaming_card = AsyncMock(return_value="card_1")  # type: ignore[attr-defined]
        bot._send_card_to_chat_ref = AsyncMock(return_value="om_stream")  # type: ignore[attr-defined]
        bot._update_streaming_card_content = AsyncMock()  # type: ignore[attr-defined]
        bot._close_streaming_card = AsyncMock()  # type: ignore[attr-defined]
        bot._patch_message = AsyncMock()  # type: ignore[attr-defined]

        async def _fake_stream(
            _key: object,
            _text: str,
            *,
            on_text_delta: AsyncMock | None = None,
            on_tool_activity: AsyncMock | None = None,
            on_system_status: AsyncMock | None = None,
            **_kwargs: object,
        ) -> SimpleNamespace:
            assert on_text_delta is not None
            assert on_system_status is not None
            assert on_tool_activity is not None
            await on_system_status("thinking")
            await on_text_delta("你")
            await on_text_delta("好")
            await on_tool_activity("Shell")
            return SimpleNamespace(text="你好")

        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(side_effect=_fake_stream)
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._create_streaming_card.assert_awaited_once()
        bot._send_card_to_chat_ref.assert_awaited_once()
        bot._patch_message.assert_not_awaited()
        assert bot._update_streaming_card_content.await_count >= 1
        bot._close_streaming_card.assert_awaited_once()
        bot._send_text_to_chat_ref.assert_not_awaited()

    async def test_handle_incoming_text_card_stream_mode_sends_file_tags_as_attachments(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bot = _make_bot(tmp_path, runtime_mode="native", progress_mode="card_stream")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._send_plain_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._create_streaming_card = AsyncMock(return_value="card_1")  # type: ignore[attr-defined]
        bot._send_card_to_chat_ref = AsyncMock(return_value="om_stream")  # type: ignore[attr-defined]
        bot._update_streaming_card_content = AsyncMock()  # type: ignore[attr-defined]
        bot._close_streaming_card = AsyncMock()  # type: ignore[attr-defined]
        send_files = AsyncMock()
        monkeypatch.setattr(
            "controlmesh.messenger.feishu.sender.send_files_from_text",
            send_files,
        )
        attachment = tmp_path / "tone.wav"
        attachment.write_bytes(b"RIFF")

        async def _fake_stream(
            _key: object,
            _text: str,
            *,
            on_text_delta: AsyncMock | None = None,
            **_kwargs: object,
        ) -> SimpleNamespace:
            assert on_text_delta is not None
            await on_text_delta("处理中")
            return SimpleNamespace(text=f"音频如下\n<file:{attachment}>")

        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(side_effect=_fake_stream)
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        send_files.assert_awaited_once_with(
            bot,
            "oc_chat_1",
            f"音频如下\n<file:{attachment}>",
            allowed_roots=None,
            reply_to_message_id="om_1",
        )
        bot._close_streaming_card.assert_awaited_once()
        assert bot._close_streaming_card.await_args.kwargs["summary"].endswith("音频如下")
        bot._send_text_to_chat_ref.assert_not_awaited()
        bot._send_plain_text_to_chat_ref.assert_not_awaited()

    async def test_handle_incoming_text_plain_mode_sends_visible_text_and_files_without_duplication(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bot = _make_bot(tmp_path)
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._send_plain_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        send_files = AsyncMock()
        monkeypatch.setattr(
            "controlmesh.messenger.feishu.sender.send_files_from_text",
            send_files,
        )
        attachment = tmp_path / "tone.wav"
        attachment.write_bytes(b"RIFF")
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(
                return_value=SimpleNamespace(text=f"音频如下\n<file:{attachment}>")
            )
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        send_files.assert_awaited_once_with(
            bot,
            "oc_chat_1",
            f"音频如下\n<file:{attachment}>",
            allowed_roots=None,
            reply_to_message_id="om_1",
        )
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "音频如下",
            reply_to_message_id="om_1",
        )

    async def test_handle_incoming_text_card_stream_mode_falls_back_to_text_when_cardkit_unavailable(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path, runtime_mode="native", progress_mode="card_stream")
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._send_plain_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._create_streaming_card = AsyncMock(return_value=None)  # type: ignore[attr-defined]
        bot._send_card_to_chat_ref = AsyncMock()  # type: ignore[attr-defined]
        bot._update_streaming_card_content = AsyncMock()  # type: ignore[attr-defined]
        bot._close_streaming_card = AsyncMock()  # type: ignore[attr-defined]

        async def _fake_stream(
            _key: object,
            _text: str,
            *,
            on_text_delta: AsyncMock | None = None,
            **_kwargs: object,
        ) -> SimpleNamespace:
            assert on_text_delta is not None
            await on_text_delta("你")
            return SimpleNamespace(text="你好")

        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(side_effect=_fake_stream)
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._create_streaming_card.assert_awaited()
        bot._send_card_to_chat_ref.assert_not_awaited()
        bot._update_streaming_card_content.assert_not_awaited()
        bot._close_streaming_card.assert_not_awaited()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "你好",
            reply_to_message_id="om_1",
        )

    async def test_handle_incoming_text_native_codex_card_stream_uses_bundled_runtime(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(
            tmp_path,
            provider="codex",
            model="gpt-5.4",
            runtime_mode="native",
            progress_mode="card_stream",
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._create_streaming_card = AsyncMock(return_value="card_1")  # type: ignore[attr-defined]
        bot._send_card_to_chat_ref = AsyncMock(return_value="om_stream")  # type: ignore[attr-defined]
        bot._update_streaming_card_content = AsyncMock()  # type: ignore[attr-defined]
        bot._close_streaming_card = AsyncMock()  # type: ignore[attr-defined]
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(),
            resolve_runtime_target=lambda _model=None: ("gpt-5.4", "codex"),
            cli_service=None,
        )
        bot._run_bundled_native_runtime_turn = AsyncMock(  # type: ignore[method-assign]
            return_value=BundledFeishuRuntimeTurn(
                text="来自 bundled runtime 的回复",
                status="completed",
                events=[
                    {"kind": "start", "text": "Codex thread started", "status": "start"},
                    {
                        "kind": "assistant_message",
                        "text": "来自 bundled runtime 的回复",
                        "status": "completed",
                    },
                ],
                card={
                    "status": "completed",
                    "final_text": "来自 bundled runtime 的回复",
                    "summary": "来自 bundled runtime 的回复",
                    "steps": [
                        {
                            "id": "step-1",
                            "kind": "assistant_message",
                            "title": "Assistant response",
                            "status": "completed",
                            "detail": "来自 bundled runtime 的回复",
                        }
                    ],
                },
                metadata={},
            )
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._run_bundled_native_runtime_turn.assert_awaited_once()
        bot._orchestrator.handle_message_streaming.assert_not_awaited()
        bot._create_streaming_card.assert_awaited_once()
        bot._send_card_to_chat_ref.assert_awaited_once()
        bot._close_streaming_card.assert_awaited_once()
        bot._send_text_to_chat_ref.assert_not_awaited()

    async def test_handle_incoming_text_native_codex_plain_mode_uses_bundled_runtime(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(
            tmp_path,
            provider="codex",
            model="gpt-5.4",
            runtime_mode="native",
            progress_mode="text",
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(),
            resolve_runtime_target=lambda _model=None: ("gpt-5.4", "codex"),
            cli_service=None,
        )
        bot._run_bundled_native_runtime_turn = AsyncMock(  # type: ignore[method-assign]
            return_value=BundledFeishuRuntimeTurn(
                text="bundled plain reply",
                status="completed",
                events=[],
                card={},
                metadata={},
            )
        )

        await bot.handle_incoming_text(
            FeishuIncomingText(
                sender_id="ou_sender",
                chat_id="oc_chat_1",
                message_id="om_1",
                text="ping",
            )
        )

        bot._run_bundled_native_runtime_turn.assert_awaited_once()
        bot._orchestrator.handle_message_streaming.assert_not_awaited()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "bundled plain reply",
            reply_to_message_id="om_1",
        )

    async def test_on_task_result_routes_to_fs_and_delivers(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        await bot.on_task_result(_FakeTaskResult())

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()

    async def test_on_task_question_routes_to_fs_and_delivers(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        await bot.on_task_question("t1", "what color?", "what co...", 123)

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()

    async def test_on_async_interagent_result_routes_to_fs_and_delivers(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        result = SimpleNamespace(
            task_id="ia1",
            sender="agent-a",
            recipient="agent-b",
            message_preview="please do X",
            result_text="done",
            success=True,
            error=None,
            elapsed_seconds=2.0,
            session_name="ia-agent-a",
            provider_switch_notice="",
            original_message="full message",
            chat_id=123,
            topic_id=None,
        )

        await bot.on_async_interagent_result(result)

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()


class TestFeishuInboundListener:
    async def test_start_inbound_listener_accepts_event_payload(self, tmp_path: Path) -> None:
        bot = _make_bot(
            tmp_path,
            callback_host="127.0.0.1",
            callback_port=0,
            callback_path="/feishu/events",
        )
        create_time_ms = int(time.time() * 1000)
        bot._orchestrator = SimpleNamespace(
            handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong")),
            shutdown=AsyncMock(),
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        await bot.start_inbound_listener()
        assert bot._inbound_server is not None

        url = (
            f"http://{bot.config.feishu.listener_host}:"
            f"{bot._inbound_server.bound_port}"
            f"{bot.config.feishu.listener_path}"
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt_1",
                "event_type": "im.message.receive_v1",
                "create_time": str(create_time_ms),
                "tenant_key": "tenant_1",
                "app_id": "cli_123",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_sender"}},
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_chat_1",
                    "thread_id": "omt_1",
                    "message_type": "text",
                    "content": '{"text":"hello from feishu"}',
                },
            },
        }

        async with (
            aiohttp.ClientSession() as session,
            session.post(url, json=payload) as response,
        ):
            assert response.status == 202
            assert await response.json() == {"accepted": True}

        await asyncio.sleep(0)
        bot._orchestrator.handle_message_streaming.assert_awaited_once()
        bot._send_text_to_chat_ref.assert_awaited_once_with(
            "oc_chat_1",
            "pong",
            reply_to_message_id="om_1",
        )
        await bot.shutdown()

    async def test_start_inbound_listener_handles_url_verification(self, tmp_path: Path) -> None:
        bot = _make_bot(
            tmp_path,
            callback_host="127.0.0.1",
            callback_port=0,
            callback_path="/feishu/events",
        )
        bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

        await bot.start_inbound_listener()
        assert bot._inbound_server is not None

        url = (
            f"http://{bot.config.feishu.listener_host}:"
            f"{bot._inbound_server.bound_port}"
            f"{bot.config.feishu.listener_path}"
        )

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                url,
                json={"type": "url_verification", "challenge": "verify-me"},
            ) as response,
        ):
            assert response.status == 200
            assert await response.json() == {"challenge": "verify-me"}

        bot._send_text_to_chat_ref.assert_not_awaited()
        await bot.shutdown()

    async def test_shutdown_stops_inbound_listener(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot._inbound_server = SimpleNamespace(stop=AsyncMock())

        await bot.shutdown()

        bot._inbound_server.stop.assert_awaited_once()

    async def test_shutdown_stops_long_connection_runtime(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot._long_connection = SimpleNamespace(stop=AsyncMock())

        await bot.shutdown()

        bot._long_connection.stop.assert_awaited_once()


@dataclass
class _FakeResponse:
    status: int
    payload: dict[str, object]

    async def text(self) -> str:
        return str(self.payload)

    async def json(self, content_type: object | None = None) -> dict[str, object]:
        return self.payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


@pytest.mark.asyncio
async def test_get_tenant_access_token_consumes_runtime_resolver_and_keeps_bot_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import controlmesh.messenger.feishu.bot as bot_mod

    bot = _make_bot(tmp_path)
    fake_session = _FakeSession(_FakeResponse(200, {"tenant_access_token": "tenant-token", "expire": 7200}))
    bot._session = fake_session  # type: ignore[assignment]
    resolver_calls: list[dict[str, object]] = []

    def _fake_resolve_feishu_auth(**kwargs: object) -> SimpleNamespace:
        resolver_calls.append(dict(kwargs))
        return SimpleNamespace(
            auth_mode="device_flow",
            token_source="device_flow",
            access_token="user-access-token",
            refresh_token="user-refresh-token",
            app_id="cli_123",
            app_secret="",
        )

    monkeypatch.setattr(bot_mod, "resolve_feishu_auth", _fake_resolve_feishu_auth, raising=False)

    token = await bot._get_tenant_access_token()

    assert token == "tenant-token"
    assert len(resolver_calls) == 1
    assert resolver_calls[0]["config"] is bot.config
    assert fake_session.calls[0]["url"] == (
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    )
    assert fake_session.calls[0]["json"] == {
        "app_id": "cli_123",
        "app_secret": "sec_456",
    }


@pytest.mark.asyncio
async def test_send_local_audio_uploads_with_duration_and_audio_message(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"audio")
    bot._prepare_audio_send_payload = MagicMock(return_value=(path, 1234))  # type: ignore[method-assign]
    bot._upload_file = AsyncMock(return_value="file_key_audio")  # type: ignore[method-assign]
    bot._send_message_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

    await bot._send_local_file_to_chat_ref("oc_chat_1", path, upload_mode="audio")

    bot._upload_file.assert_awaited_once_with(path, file_type="opus", duration_ms=1234)
    bot._send_message_to_chat_ref.assert_awaited_once_with(
        "oc_chat_1",
        msg_type="audio",
        content={"file_key": "file_key_audio"},
        reply_to_message_id=None,
    )


@pytest.mark.asyncio
async def test_send_local_video_uploads_with_duration_and_media_message(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    bot._parse_video_duration_ms = MagicMock(return_value=2500)  # type: ignore[method-assign]
    bot._upload_file = AsyncMock(return_value="file_key_video")  # type: ignore[method-assign]
    bot._send_message_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

    await bot._send_local_file_to_chat_ref("oc_chat_1", path, upload_mode="video")

    bot._upload_file.assert_awaited_once_with(path, file_type="mp4", duration_ms=2500)
    bot._send_message_to_chat_ref.assert_awaited_once_with(
        "oc_chat_1",
        msg_type="media",
        content={"file_key": "file_key_video"},
        reply_to_message_id=None,
    )


@pytest.mark.asyncio
async def test_send_local_common_audio_falls_back_to_document_when_transcode_unavailable(
    tmp_path: Path,
) -> None:
    bot = _make_bot(tmp_path)
    path = tmp_path / "voice.mp3"
    path.write_bytes(b"audio")
    bot._prepare_audio_send_payload = MagicMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("ffmpeg not available")
    )
    bot._upload_file = AsyncMock(return_value="file_key_doc")  # type: ignore[method-assign]
    bot._send_message_to_chat_ref = AsyncMock()  # type: ignore[method-assign]

    await bot._send_local_file_to_chat_ref("oc_chat_1", path, upload_mode="audio")

    bot._upload_file.assert_awaited_once_with(path, file_type="stream", duration_ms=None)
    bot._send_message_to_chat_ref.assert_awaited_once_with(
        "oc_chat_1",
        msg_type="file",
        content={"file_key": "file_key_doc"},
        reply_to_message_id=None,
    )


@pytest.mark.asyncio
async def test_upload_file_includes_duration_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import controlmesh.messenger.feishu.bot as bot_mod

    class _FakeFormData:
        def __init__(self) -> None:
            self.fields: list[tuple[str, object]] = []

        def add_field(self, name: str, value: object, **_kwargs: object) -> None:
            self.fields.append((name, value))

    bot = _make_bot(tmp_path)
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"audio")
    form = _FakeFormData()
    fake_session = _FakeSession(_FakeResponse(200, {"data": {"file_key": "file_key_audio"}}))
    bot._session = fake_session  # type: ignore[assignment]
    bot._get_tenant_access_token = AsyncMock(return_value="tenant-token")  # type: ignore[method-assign]
    monkeypatch.setattr(bot_mod.aiohttp, "FormData", lambda: form)

    assert await bot._upload_file(path, file_type="opus", duration_ms=1234) == "file_key_audio"

    assert ("duration", "1234") in form.fields
    assert ("file_type", "opus") in form.fields
    assert ("file_name", "voice.ogg") in form.fields
