"""Tests for Feishu CardKit streaming progress cards."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from controlmesh.messenger.feishu.card_stream import (
    FeishuCardStreamReporter,
    merge_streaming_text,
    render_feishu_streaming_card,
    render_feishu_streaming_card_from_single_card_run,
    tool_step_from_auth_kit_agent_event,
)


def test_render_feishu_streaming_card_enables_cardkit_streaming() -> None:
    card = render_feishu_streaming_card(
        title="乔乔",
        body="处理中...",
        note="ControlMesh",
    )

    assert card["schema"] == "2.0"
    assert card["config"]["streaming_mode"] is True
    assert card["config"]["streaming_config"]["print_frequency_ms"]["default"] == 50
    assert card["body"]["elements"][0]["element_id"] == "content"
    assert "状态" in card["body"]["elements"][0]["content"]
    assert "处理中..." in card["body"]["elements"][0]["content"]
    assert card["body"]["elements"][2]["element_id"] == "note"


def test_merge_streaming_text_preserves_snapshot_and_delta_updates() -> None:
    assert merge_streaming_text("", "a") == "a"
    assert merge_streaming_text("hello", "hello, world") == "hello, world"
    assert merge_streaming_text("hello, wor", "world") == "hello, world"
    assert merge_streaming_text("abc", "xyz") == "abcxyz"


@pytest.mark.asyncio
async def test_card_stream_reporter_updates_cardkit_content_and_closes_settings() -> None:
    bot = AsyncMock()
    bot._create_streaming_card.return_value = "card_1"
    bot._send_card_to_chat_ref.return_value = "om_1"

    reporter = FeishuCardStreamReporter(
        bot,
        chat_ref="oc_chat_1",
        reply_to_message_id="om_source",
        title="乔乔",
        note="ControlMesh",
    )

    reporter.start()
    await reporter.on_text_delta("hello")
    await reporter.on_text_delta(", world")
    await reporter.finish_success("hello, world")
    await reporter.close()

    bot._create_streaming_card.assert_awaited_once()
    bot._send_card_to_chat_ref.assert_awaited_once_with(
        "oc_chat_1",
        {"type": "card", "data": {"card_id": "card_1"}},
        reply_to_message_id="om_source",
    )
    bot._patch_message.assert_not_called()
    assert bot._update_streaming_card_content.await_count >= 1
    final_content = bot._update_streaming_card_content.await_args_list[-1].args[1]
    assert "hello, world" in final_content
    assert "状态" in final_content
    bot._close_streaming_card.assert_awaited_once()


@pytest.mark.asyncio
async def test_card_stream_reporter_renders_structured_tool_steps_and_terminal_state() -> None:
    bot = AsyncMock()
    bot._create_streaming_card.return_value = "card_1"
    bot._send_card_to_chat_ref.return_value = "om_1"

    reporter = FeishuCardStreamReporter(
        bot,
        chat_ref="oc_chat_1",
        reply_to_message_id="om_source",
        title="乔乔",
    )

    reporter.start()
    await reporter.on_tool("contact.search_user")
    await reporter.on_text_delta("找到 Alice")
    await reporter.finish_success("找到 Alice")
    await reporter.close()

    final_content = bot._update_streaming_card_content.await_args_list[-1].args[1]
    assert "工具步骤" in final_content
    assert "contact.search_user" in final_content
    assert "success" in final_content
    assert "终态" in final_content
    assert "success" in final_content


def test_card_stream_converts_auth_kit_agent_event_tool_steps() -> None:
    call_step = tool_step_from_auth_kit_agent_event(
        {
            "schema": "feishu-auth-kit.agent-event.v1",
            "kind": "tool_call",
            "state": "running",
            "tool_name": "drive.list_files",
        }
    )
    result_step = tool_step_from_auth_kit_agent_event(
        {
            "schema": "feishu-auth-kit.agent-event.v1",
            "kind": "tool_result",
            "state": "completed",
            "tool_name": "drive.list_files",
        }
    )

    assert call_step is not None
    assert call_step.name == "drive.list_files"
    assert call_step.status == "running"
    assert result_step is not None
    assert result_step.name == "drive.list_files"
    assert result_step.status == "success"


def test_card_stream_renders_auth_kit_single_card_run_contract() -> None:
    card = render_feishu_streaming_card_from_single_card_run(
        {
            "schema": "feishu-auth-kit.cardkit.single_card.v1",
            "status": "completed",
            "summary": "done",
            "final_text": "列出 2 个文件",
            "steps": [
                {
                    "id": "step-1",
                    "kind": "tool_call",
                    "title": "Tool: drive.list_files",
                    "status": "completed",
                }
            ],
        },
        title="乔乔",
    )

    content = card["body"]["elements"][0]["content"]
    assert "列出 2 个文件" in content
    assert "Tool: drive.list_files" in content
    assert "success" in content


@pytest.mark.asyncio
async def test_card_stream_reporter_consumes_auth_kit_events_and_single_card_run() -> None:
    bot = AsyncMock()
    bot._create_streaming_card.return_value = "card_1"
    bot._send_card_to_chat_ref.return_value = "om_1"
    reporter = FeishuCardStreamReporter(
        bot,
        chat_ref="oc_chat_1",
        reply_to_message_id="om_source",
        title="乔乔",
    )

    reporter.start()
    await reporter.on_agent_event(
        {
            "schema": "feishu-auth-kit.agent-event.v1",
            "kind": "tool_call",
            "state": "running",
            "tool_name": "drive.list_files",
        }
    )
    await reporter.finish_with_single_card_run(
        {
            "schema": "feishu-auth-kit.cardkit.single_card.v1",
            "status": "completed",
            "final_text": "列出 2 个文件",
            "steps": [
                {
                    "kind": "tool_call",
                    "title": "Tool: drive.list_files",
                    "status": "completed",
                }
            ],
        }
    )
    await reporter.close()

    final_content = bot._update_streaming_card_content.await_args_list[-1].args[1]
    assert "Tool: drive.list_files" in final_content
    assert "列出 2 个文件" in final_content
    assert "终态" in final_content
