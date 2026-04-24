from __future__ import annotations

import base64
import json

from controlmesh.messenger.qqbot.inbound import (
    QQBotIncomingText,
    QQBotInteraction,
    normalize_gateway_event,
    normalize_interaction_event,
)


def _face_tag(name: str) -> str:
    ext = base64.b64encode(json.dumps({"text": name}).encode("utf-8")).decode("ascii")
    return f'<faceType=1,faceId="13",ext="{ext}">'


def test_normalize_c2c_message_event() -> None:
    event = normalize_gateway_event(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg-1",
            "content": "hello",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "user-id",
                "union_openid": "union-id",
                "user_openid": "USER_A",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-1",
        text="hello",
    )


def test_normalize_c2c_message_decodes_face_tags() -> None:
    face = _face_tag("呲牙")
    event = normalize_gateway_event(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg-face-1",
            "content": f"hello {face}",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "user-id",
                "union_openid": "union-id",
                "user_openid": "USER_A",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-face-1",
        text="hello 【表情: 呲牙】",
    )


def test_normalize_c2c_attachment_only_event_to_attachment_summary() -> None:
    event = normalize_gateway_event(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg-1a",
            "content": "",
            "timestamp": "2026-04-24T00:00:00Z",
            "attachments": [
                {
                    "content_type": "image/png",
                    "filename": "image.png",
                    "url": "https://cdn.example/image.png",
                }
            ],
            "author": {
                "id": "user-id",
                "union_openid": "union-id",
                "user_openid": "USER_A",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-1a",
        text="Attachment: image.png (image/png) https://cdn.example/image.png",
    )


def test_normalize_c2c_attachment_without_url_keeps_structured_attachment_label() -> None:
    event = normalize_gateway_event(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg-1a2",
            "content": "",
            "timestamp": "2026-04-24T00:00:00Z",
            "attachments": [
                {
                    "content_type": "image/png",
                    "filename": "image.png",
                }
            ],
            "author": {
                "id": "user-id",
                "union_openid": "union-id",
                "user_openid": "USER_A",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-1a2",
        text="[图片: image.png]",
    )


def test_normalize_c2c_voice_attachment_uses_asr_text() -> None:
    event = normalize_gateway_event(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg-1b",
            "content": "",
            "timestamp": "2026-04-24T00:00:00Z",
            "attachments": [
                {
                    "content_type": "audio/silk",
                    "filename": "voice.silk",
                    "url": "https://cdn.example/voice.silk",
                    "voice_wav_url": "https://cdn.example/voice.wav",
                    "asr_refer_text": "hello from voice",
                }
            ],
            "author": {
                "id": "user-id",
                "union_openid": "union-id",
                "user_openid": "USER_A",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-1b",
        text=(
            "Voice transcript: hello from voice\n"
            "Attachment: voice.silk (audio/silk) https://cdn.example/voice.wav"
        ),
    )


def test_normalize_group_at_event_strips_self_mention() -> None:
    event = normalize_gateway_event(
        "GROUP_AT_MESSAGE_CREATE",
        {
            "id": "msg-2",
            "content": "<@BOT_OPENID> hello team",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
            "mentions": [
                {
                    "member_openid": "BOT_OPENID",
                    "nickname": "ControlMesh",
                    "is_you": True,
                }
            ],
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_AT_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        message_id="msg-2",
        text="hello team",
        topic_id="member:USER_A",
    )


def test_normalize_group_message_event_as_passive_group_surface() -> None:
    event = normalize_gateway_event(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-2b",
            "content": "plain group traffic",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_B",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_B",
        message_id="msg-2b",
        text="plain group traffic",
        topic_id="member:USER_B",
        deliver_to_orchestrator=False,
    )


def test_normalize_group_message_extracts_reference_indices() -> None:
    event = normalize_gateway_event(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-2c",
            "content": "quoted traffic",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "message_scene": {
                "source": "quote",
                "ext": ["ref_msg_idx=REFIDX_bot_1", "msg_idx=REFIDX_current"],
            },
            "author": {
                "id": "member-id",
                "member_openid": "USER_C",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_C",
        message_id="msg-2c",
        text="quoted traffic",
        topic_id="member:USER_C",
        deliver_to_orchestrator=False,
        ref_msg_idx="REFIDX_bot_1",
        msg_idx="REFIDX_current",
    )


def test_normalize_group_message_includes_quoted_message_context() -> None:
    face = _face_tag("玫瑰")
    event = normalize_gateway_event(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-2d",
            "content": "replying without explicit text mention",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "message_scene": {
                "source": "quote",
                "ext": ["ref_msg_idx=REFIDX_bot_1", "msg_idx=REFIDX_current"],
            },
            "msg_elements": [
                {
                    "msg_idx": "REFIDX_bot_1",
                    "message_type": 103,
                    "content": f"prior bot message {face}",
                }
            ],
            "author": {
                "id": "member-id",
                "member_openid": "USER_C",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_C",
        message_id="msg-2d",
        text="Quoted message:\nprior bot message 【表情: 玫瑰】\n\nreplying without explicit text mention",
        topic_id="member:USER_C",
        deliver_to_orchestrator=False,
        ref_msg_idx="REFIDX_bot_1",
        msg_idx="REFIDX_current",
    )


def test_normalize_group_message_uses_quote_message_type_msg_idx_when_ext_missing() -> None:
    event = normalize_gateway_event(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-2d2",
            "content": "replying to quoted body",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "message_type": 103,
            "msg_elements": [
                {
                    "msg_idx": "REFIDX_quote_only",
                    "message_type": 0,
                    "content": "quoted body from msg_elements",
                }
            ],
            "author": {
                "id": "member-id",
                "member_openid": "USER_C",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_C",
        message_id="msg-2d2",
        text="Quoted message:\nquoted body from msg_elements\n\nreplying to quoted body",
        topic_id="member:USER_C",
        deliver_to_orchestrator=False,
        ref_msg_idx="REFIDX_quote_only",
    )


def test_normalize_group_message_includes_quoted_attachment_label_without_url() -> None:
    event = normalize_gateway_event(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-2d3",
            "content": "replying to quoted file",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "message_scene": {
                "source": "quote",
                "ext": ["ref_msg_idx=REFIDX_file", "msg_idx=REFIDX_current"],
            },
            "msg_elements": [
                {
                    "msg_idx": "REFIDX_file",
                    "message_type": 0,
                    "attachments": [
                        {
                            "content_type": "application/pdf",
                            "filename": "spec.pdf",
                        }
                    ],
                }
            ],
            "author": {
                "id": "member-id",
                "member_openid": "USER_C",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_C",
        message_id="msg-2d3",
        text="Quoted message:\n[文件: spec.pdf]\n\nreplying to quoted file",
        topic_id="member:USER_C",
        deliver_to_orchestrator=False,
        ref_msg_idx="REFIDX_file",
        msg_idx="REFIDX_current",
    )


def test_normalize_group_message_recursively_resolves_quoted_msg_elements() -> None:
    event = normalize_gateway_event(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-2e",
            "content": "replying to quoted media",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "message_scene": {
                "source": "quote",
                "ext": ["ref_msg_idx=REFIDX_nested", "msg_idx=REFIDX_current"],
            },
            "msg_elements": [
                {
                    "msg_idx": "REFIDX_wrapper",
                    "message_type": 103,
                    "msg_elements": [
                        {
                            "msg_idx": "REFIDX_nested",
                            "message_type": 0,
                            "content": "prior bot image reply",
                            "attachments": [
                                {
                                    "content_type": "image/png",
                                    "filename": "image.png",
                                    "url": "https://cdn.example/image.png",
                                }
                            ],
                        }
                    ],
                }
            ],
            "author": {
                "id": "member-id",
                "member_openid": "USER_C",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_C",
        message_id="msg-2e",
        text=(
            "Quoted message:\n"
            "prior bot image reply\n"
            "Attachment: image.png (image/png) https://cdn.example/image.png\n\n"
            "replying to quoted media"
        ),
        topic_id="member:USER_C",
        deliver_to_orchestrator=False,
        ref_msg_idx="REFIDX_nested",
        msg_idx="REFIDX_current",
    )


def test_normalize_group_message_includes_quoted_voice_attachment_context() -> None:
    event = normalize_gateway_event(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-2f",
            "content": "replying to quoted voice",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "message_scene": {
                "source": "quote",
                "ext": ["ref_msg_idx=REFIDX_voice", "msg_idx=REFIDX_current"],
            },
            "msg_elements": [
                {
                    "msg_idx": "REFIDX_voice",
                    "message_type": 0,
                    "attachments": [
                        {
                            "content_type": "audio/silk",
                            "filename": "voice.silk",
                            "url": "https://cdn.example/voice.silk",
                            "voice_wav_url": "https://cdn.example/voice.wav",
                            "asr_refer_text": "quoted voice transcript",
                        }
                    ],
                }
            ],
            "author": {
                "id": "member-id",
                "member_openid": "USER_C",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_C",
        message_id="msg-2f",
        text=(
            "Quoted message:\n"
            "Voice transcript: quoted voice transcript\n"
            "Attachment: voice.silk (audio/silk) https://cdn.example/voice.wav\n\n"
            "replying to quoted voice"
        ),
        topic_id="member:USER_C",
        deliver_to_orchestrator=False,
        ref_msg_idx="REFIDX_voice",
        msg_idx="REFIDX_current",
    )


def test_normalize_group_message_includes_quoted_voice_label_without_url() -> None:
    event = normalize_gateway_event(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-2f2",
            "content": "replying to quoted voice",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "message_scene": {
                "source": "quote",
                "ext": ["ref_msg_idx=REFIDX_voice2", "msg_idx=REFIDX_current"],
            },
            "msg_elements": [
                {
                    "msg_idx": "REFIDX_voice2",
                    "message_type": 0,
                    "attachments": [
                        {
                            "content_type": "audio/silk",
                            "filename": "voice.silk",
                            "asr_refer_text": "quoted voice transcript",
                        }
                    ],
                }
            ],
            "author": {
                "id": "member-id",
                "member_openid": "USER_C",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_C",
        message_id="msg-2f2",
        text=(
            "Quoted message:\n"
            "Voice transcript: quoted voice transcript\n"
            "[语音消息（内容: \"quoted voice transcript\"）]\n\n"
            "replying to quoted voice"
        ),
        topic_id="member:USER_C",
        deliver_to_orchestrator=False,
        ref_msg_idx="REFIDX_voice2",
        msg_idx="REFIDX_current",
    )


def test_normalize_channel_at_event_strips_leading_mention_markup() -> None:
    event = normalize_gateway_event(
        "AT_MESSAGE_CREATE",
        {
            "id": "msg-3",
            "content": "<@!BOT_ID> status please",
            "channel_id": "CHANNEL_A",
            "guild_id": "GUILD_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "USER_A",
                "username": "alice",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="AT_MESSAGE_CREATE",
        chat_id="qqbot:channel:CHANNEL_A",
        sender_id="USER_A",
        message_id="msg-3",
        text="status please",
    )


def test_normalize_direct_message_event_to_sender_scoped_c2c_target() -> None:
    event = normalize_gateway_event(
        "DIRECT_MESSAGE_CREATE",
        {
            "id": "msg-4",
            "content": "hello from dm",
            "channel_id": "CHANNEL_DM_A",
            "guild_id": "GUILD_DM_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "USER_DM_A",
                "username": "dm-user",
            },
        },
    )

    assert event == QQBotIncomingText(
        event_type="DIRECT_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_DM_A",
        sender_id="USER_DM_A",
        message_id="msg-4",
        text="hello from dm",
    )


def test_normalize_ignores_unknown_event_types() -> None:
    assert normalize_gateway_event("UNKNOWN_EVENT", {}) is None


def test_normalize_group_interaction_event_to_member_scoped_callback() -> None:
    event = normalize_interaction_event(
        {
            "id": "interaction-1",
            "scene": "group",
            "group_openid": "GROUP_A",
            "group_member_openid": "USER_A",
            "data": {
                "resolved": {
                    "button_data": "ms:m:opus",
                    "button_id": "btn-1",
                    "message_id": "msg-1",
                }
            },
        }
    )

    assert event == QQBotInteraction(
        interaction_id="interaction-1",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        button_data="ms:m:opus",
        button_id="btn-1",
        message_id="msg-1",
        topic_id="member:USER_A",
    )


def test_normalize_c2c_interaction_event_to_c2c_callback() -> None:
    event = normalize_interaction_event(
        {
            "id": "interaction-2",
            "scene": "c2c",
            "user_openid": "USER_A",
            "data": {"resolved": {"button_data": "crn:r:0"}},
        }
    )

    assert event == QQBotInteraction(
        interaction_id="interaction-2",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        button_data="crn:r:0",
    )
