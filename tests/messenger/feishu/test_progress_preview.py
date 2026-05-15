"""Tests for Feishu preview-card progress reporter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from controlmesh.messenger.feishu.progress_preview import FeishuCardPreviewReporter


@pytest.mark.asyncio
async def test_preview_reporter_accepts_agent_events_and_single_card_runs() -> None:
    bot = AsyncMock()
    bot._send_card_to_chat_ref.return_value = "om_1"

    reporter = FeishuCardPreviewReporter(
        bot,
        chat_ref="oc_chat_1",
        reply_to_message_id="om_source",
        max_messages=5,
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
    await reporter.on_agent_event(
        {
            "schema": "feishu-auth-kit.agent-event.v1",
            "kind": "assistant_message",
            "text": "列出 2 个文件",
        }
    )
    await reporter.finish_with_single_card_run(
        {
            "schema": "feishu-auth-kit.cardkit.single_card.v1",
            "status": "completed",
            "final_text": "列出 2 个文件",
        }
    )
    await reporter.close()

    bot._send_card_to_chat_ref.assert_awaited()
    assert bot._patch_message.await_count >= 1
    final_content = bot._patch_message.await_args_list[-1].kwargs["content"]
    body = final_content["elements"][0]["text"]["content"]
    assert "列出 2 个文件" in body
    assert final_content["header"]["title"]["content"] == "已完成"
