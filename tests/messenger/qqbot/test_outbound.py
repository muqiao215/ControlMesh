from __future__ import annotations

from controlmesh.messenger.qqbot.outbound import (
    choose_reply_mode,
    record_passive_reply,
    reset_reply_tracker,
    sanitize_outbound_text,
)


def setup_function() -> None:
    reset_reply_tracker()


def test_sanitize_outbound_text_filters_internal_markers() -> None:
    assert (
        sanitize_outbound_text("hello\n\n[[reply_to: msg-1]]\n@image:image_1.png\n\nworld")
        == "hello\n\nworld"
    )


def test_choose_reply_mode_falls_back_after_limit_for_c2c() -> None:
    for _ in range(4):
        assert choose_reply_mode("c2c", "msg-1", now=10).msg_id == "msg-1"
        record_passive_reply("c2c", "msg-1", now=10)

    decision = choose_reply_mode("c2c", "msg-1", now=10)

    assert decision.msg_id is None
    assert decision.fallback_to_proactive is True
    assert decision.fallback_reason == "limit_exceeded"


def test_choose_reply_mode_falls_back_after_expiry_for_group() -> None:
    record_passive_reply("group", "msg-1", now=10)

    decision = choose_reply_mode("group", "msg-1", now=10 + 3601)

    assert decision.msg_id is None
    assert decision.fallback_to_proactive is True
    assert decision.fallback_reason == "expired"


def test_choose_reply_mode_keeps_msg_id_for_channel() -> None:
    for _ in range(10):
        record_passive_reply("channel", "msg-1", now=10)

    decision = choose_reply_mode("channel", "msg-1", now=10 + 99999)

    assert decision.msg_id == "msg-1"
    assert decision.fallback_to_proactive is False
    assert decision.fallback_reason is None
