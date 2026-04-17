"""Tests for Feishu inbound message context compatibility."""

from __future__ import annotations

import json
from typing import Any

from controlmesh.messenger.feishu import message_context


def test_extract_content_prefers_auth_kit_prompt_text_and_keeps_cm_quote_glue(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _parse_with_kit(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {
            "schema": "feishu-auth-kit.message-context.v1",
            "text": "@_bot hello from kit",
            "prompt_text": "hello from kit",
        }

    monkeypatch.setattr(
        message_context,
        "parse_feishu_auth_kit_message_context",
        _parse_with_kit,
    )
    payload = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_type": "text",
                "content": json.dumps(
                    {"text": "@_bot hello from cm", "quote": {"text": "上一条"}},
                    ensure_ascii=False,
                ),
            }
        },
    }

    parsed = message_context.extract_feishu_content_from_event(
        payload,
        "text",
        payload["event"]["message"]["content"],
    )

    assert calls == [payload]
    assert parsed.text == "hello from kit"
    assert parsed.quote_summary == "上一条"


def test_extract_content_falls_back_to_cm_post_parser_when_auth_kit_unavailable(
    monkeypatch,
) -> None:
    def _parse_with_kit(_payload: dict[str, Any]) -> dict[str, Any]:
        msg = "kit unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        message_context,
        "parse_feishu_auth_kit_message_context",
        _parse_with_kit,
    )
    content = {
        "zh_cn": {
            "title": "项目更新",
            "content": [[{"tag": "text", "text": "继续推进"}]],
        }
    }

    parsed = message_context.extract_feishu_content_from_event(
        {"event": {"message": {"message_type": "post", "content": content}}},
        "post",
        content,
    )

    assert parsed.text == "**项目更新**\n\n继续推进"
    assert parsed.post_title == "项目更新"
