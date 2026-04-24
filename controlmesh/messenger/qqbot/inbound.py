"""Inbound event normalization for the direct official QQ Bot runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from controlmesh.messenger.qqbot.media import build_inbound_text, extract_quoted_element

_LEADING_MENTION_RE = re.compile(r"^(?:\s*<@!?[^>]+>\s*)+")


@dataclass(frozen=True, slots=True)
class QQBotIncomingText:
    """Normalized inbound text event ready for ControlMesh routing."""

    event_type: str
    chat_id: str
    sender_id: str
    message_id: str
    text: str
    topic_id: str | None = None
    deliver_to_orchestrator: bool = True
    ref_msg_idx: str | None = None
    msg_idx: str | None = None


@dataclass(frozen=True, slots=True)
class QQBotInteraction:
    """Normalized qqbot button interaction event."""

    interaction_id: str
    chat_id: str
    sender_id: str
    button_data: str
    button_id: str | None = None
    message_id: str | None = None
    topic_id: str | None = None


def normalize_gateway_event(
    event_type: str,
    payload: dict[str, Any],
) -> QQBotIncomingText | None:
    """Normalize one QQ gateway dispatch payload into a text event."""
    if event_type == "C2C_MESSAGE_CREATE":
        author = payload.get("author")
        user_openid = author.get("user_openid") if isinstance(author, dict) else None
        message_id = payload.get("id")
        ref_msg_idx, _ = _extract_scene_indices(payload)
        text = build_inbound_text(
            _clean_text(payload.get("content")),
            attachments=_attachments(payload),
            quoted_element=extract_quoted_element(payload, ref_msg_idx=ref_msg_idx),
        )
        if not (isinstance(user_openid, str) and user_openid and isinstance(message_id, str) and text):
            return None
        return QQBotIncomingText(
            event_type=event_type,
            chat_id=f"qqbot:c2c:{user_openid}",
            sender_id=user_openid,
            message_id=message_id,
            text=text,
        )

    if event_type == "GROUP_AT_MESSAGE_CREATE":
        author = payload.get("author")
        group_openid = payload.get("group_openid")
        member_openid = author.get("member_openid") if isinstance(author, dict) else None
        message_id = payload.get("id")
        mentions = payload.get("mentions")
        base_text = _strip_mentions(
            payload.get("content"),
            mentions if isinstance(mentions, list) else None,
        )
        ref_msg_idx, _ = _extract_scene_indices(payload)
        text = build_inbound_text(
            base_text,
            attachments=_attachments(payload),
            quoted_element=extract_quoted_element(payload, ref_msg_idx=ref_msg_idx),
        )
        if not (
            isinstance(group_openid, str)
            and group_openid
            and isinstance(member_openid, str)
            and member_openid
            and isinstance(message_id, str)
            and text
        ):
            return None
        return QQBotIncomingText(
            event_type=event_type,
            chat_id=f"qqbot:group:{group_openid}",
            sender_id=member_openid,
            message_id=message_id,
            text=text,
            topic_id=_group_member_topic(member_openid),
        )

    if event_type == "GROUP_MESSAGE_CREATE":
        author = payload.get("author")
        group_openid = payload.get("group_openid")
        member_openid = author.get("member_openid") if isinstance(author, dict) else None
        message_id = payload.get("id")
        ref_msg_idx, msg_idx = _extract_scene_indices(payload)
        text = build_inbound_text(
            _clean_text(payload.get("content")),
            attachments=_attachments(payload),
            quoted_element=extract_quoted_element(payload, ref_msg_idx=ref_msg_idx),
        )
        if not (
            isinstance(group_openid, str)
            and group_openid
            and isinstance(member_openid, str)
            and member_openid
            and isinstance(message_id, str)
            and text
        ):
            return None
        return QQBotIncomingText(
            event_type=event_type,
            chat_id=f"qqbot:group:{group_openid}",
            sender_id=member_openid,
            message_id=message_id,
            text=text,
            topic_id=_group_member_topic(member_openid),
            deliver_to_orchestrator=False,
            ref_msg_idx=ref_msg_idx,
            msg_idx=msg_idx,
        )

    if event_type == "AT_MESSAGE_CREATE":
        author = payload.get("author")
        channel_id = payload.get("channel_id")
        sender_id = author.get("id") if isinstance(author, dict) else None
        message_id = payload.get("id")
        ref_msg_idx, _ = _extract_scene_indices(payload)
        text = build_inbound_text(
            _strip_leading_mentions(payload.get("content")),
            attachments=_attachments(payload),
            quoted_element=extract_quoted_element(payload, ref_msg_idx=ref_msg_idx),
        )
        if not (
            isinstance(channel_id, str)
            and channel_id
            and isinstance(sender_id, str)
            and sender_id
            and isinstance(message_id, str)
            and text
        ):
            return None
        return QQBotIncomingText(
            event_type=event_type,
            chat_id=f"qqbot:channel:{channel_id}",
            sender_id=sender_id,
            message_id=message_id,
            text=text,
        )

    if event_type == "DIRECT_MESSAGE_CREATE":
        author = payload.get("author")
        sender_id = author.get("id") if isinstance(author, dict) else None
        message_id = payload.get("id")
        ref_msg_idx, _ = _extract_scene_indices(payload)
        text = build_inbound_text(
            _clean_text(payload.get("content")),
            attachments=_attachments(payload),
            quoted_element=extract_quoted_element(payload, ref_msg_idx=ref_msg_idx),
        )
        if not (
            isinstance(sender_id, str)
            and sender_id
            and isinstance(message_id, str)
            and text
        ):
            return None
        return QQBotIncomingText(
            event_type=event_type,
            chat_id=f"qqbot:c2c:{sender_id}",
            sender_id=sender_id,
            message_id=message_id,
            text=text,
        )

    return None


def normalize_interaction_event(payload: dict[str, Any]) -> QQBotInteraction | None:
    """Normalize one ``INTERACTION_CREATE`` payload into a callback event."""
    interaction_id = payload.get("id")
    data = payload.get("data")
    if not isinstance(interaction_id, str) or not interaction_id or not isinstance(data, dict):
        return None

    resolved = data.get("resolved")
    if not isinstance(resolved, dict):
        return None

    button_data = resolved.get("button_data")
    if not isinstance(button_data, str) or not button_data:
        return None

    scene = payload.get("scene")
    if scene == "group":
        group_openid = payload.get("group_openid")
        member_openid = payload.get("group_member_openid")
        if not (
            isinstance(group_openid, str)
            and group_openid
            and isinstance(member_openid, str)
            and member_openid
        ):
            return None
        return QQBotInteraction(
            interaction_id=interaction_id,
            chat_id=f"qqbot:group:{group_openid}",
            sender_id=member_openid,
            button_data=button_data,
            button_id=_optional_string(resolved.get("button_id")),
            message_id=_optional_string(resolved.get("message_id")),
            topic_id=_group_member_topic(member_openid),
        )

    if scene == "c2c":
        user_openid = payload.get("user_openid")
        if not isinstance(user_openid, str) or not user_openid:
            return None
        return QQBotInteraction(
            interaction_id=interaction_id,
            chat_id=f"qqbot:c2c:{user_openid}",
            sender_id=user_openid,
            button_data=button_data,
            button_id=_optional_string(resolved.get("button_id")),
            message_id=_optional_string(resolved.get("message_id")),
        )

    if scene == "guild":
        channel_id = payload.get("channel_id")
        user_id = resolved.get("user_id")
        if not isinstance(channel_id, str) or not channel_id or not isinstance(user_id, str) or not user_id:
            return None
        return QQBotInteraction(
            interaction_id=interaction_id,
            chat_id=f"qqbot:channel:{channel_id}",
            sender_id=user_id,
            button_data=button_data,
            button_id=_optional_string(resolved.get("button_id")),
            message_id=_optional_string(resolved.get("message_id")),
        )

    return None


def matches_text_mention_patterns(text: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Return True when content contains one configured plain-text bot mention."""
    cleaned = _clean_text(text)
    if not cleaned:
        return False
    haystack = cleaned.casefold()
    for raw_pattern in patterns:
        pattern = raw_pattern.strip()
        if not pattern:
            continue
        candidates = {pattern.casefold()}
        if not pattern.startswith("@"):
            candidates.add(f"@{pattern}".casefold())
        if any(candidate in haystack for candidate in candidates):
            return True
    return False


def is_standalone_slash_command(text: str) -> bool:
    """Return True when content is a standalone slash-command surface."""
    cleaned = _clean_text(text)
    return cleaned.startswith("/") and len(cleaned) > 1


def _strip_mentions(text: Any, mentions: list[dict[str, Any]] | None) -> str:
    cleaned = _clean_text(text)
    if not cleaned or not mentions:
        return cleaned
    for mention in mentions:
        openid = _mention_openid(mention)
        if not openid:
            continue
        cleaned = re.sub(rf"<@!?{re.escape(openid)}>", "", cleaned)
    return " ".join(cleaned.split())


def _mention_openid(mention: dict[str, Any]) -> str | None:
    for key in ("member_openid", "id", "user_openid"):
        value = mention.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _strip_leading_mentions(text: Any) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    return " ".join(_LEADING_MENTION_RE.sub("", cleaned).split())


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _group_member_topic(member_openid: str) -> str:
    return f"member:{member_openid}"


def _attachments(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw = payload.get("attachments")
    if not isinstance(raw, list):
        return None
    return [item for item in raw if isinstance(item, dict)]


def _extract_scene_indices(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    message_scene = payload.get("message_scene")
    ref_msg_idx: str | None = None
    msg_idx: str | None = None

    if isinstance(message_scene, dict):
        ext = message_scene.get("ext")
        if isinstance(ext, list):
            for item in ext:
                if not isinstance(item, str) or "=" not in item:
                    continue
                key, value = item.split("=", 1)
                if not value:
                    continue
                if key == "ref_msg_idx":
                    ref_msg_idx = value
                elif key == "msg_idx":
                    msg_idx = value

    # Upstream parseRefIndices() treats quoted msg_elements[0].msg_idx as the
    # authoritative referenced message index when message_type=103.
    if payload.get("message_type") == 103:
        raw = payload.get("msg_elements")
        if isinstance(raw, list) and raw:
            first = raw[0]
            if isinstance(first, dict):
                first_msg_idx = first.get("msg_idx")
                if isinstance(first_msg_idx, str) and first_msg_idx:
                    ref_msg_idx = first_msg_idx
    return ref_msg_idx, msg_idx


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
