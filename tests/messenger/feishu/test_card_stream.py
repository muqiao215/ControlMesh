"""Tests for Feishu CardKit streaming progress cards."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from controlmesh.messenger.feishu.card_stream import (
    FeishuCardStreamReporter,
    merge_streaming_text,
    render_feishu_streaming_card,
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
    assert card["body"]["elements"][0]["content"] == "处理中..."
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
    assert bot._update_streaming_card_content.await_args_list[-1].args[1] == "hello, world"
    bot._close_streaming_card.assert_awaited_once()
