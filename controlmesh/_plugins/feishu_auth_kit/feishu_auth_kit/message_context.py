from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"text": value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


@dataclass(frozen=True)
class FeishuMention:
    key: str | None = None
    name: str | None = None
    open_id: str | None = None
    user_id: str | None = None
    union_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "key": self.key,
            "name": self.name,
            "open_id": self.open_id,
            "user_id": self.user_id,
            "union_id": self.union_id,
        }


@dataclass(frozen=True)
class FeishuMessageContext:
    schema: str = "feishu-auth-kit.message-context.v1"
    source: str = "feishu"
    delivery: str = "event_callback"
    event_id: str | None = None
    event_type: str | None = None
    app_id: str | None = None
    tenant_key: str | None = None
    chat_id: str | None = None
    chat_type: str | None = None
    message_id: str | None = None
    message_type: str = "text"
    sender_open_id: str | None = None
    sender_user_id: str | None = None
    sender_union_id: str | None = None
    text: str = ""
    mentions: list[FeishuMention] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def prompt_text(self, *, strip_mentions: bool = True) -> str:
        prompt = self.text.strip()
        if strip_mentions:
            for mention in self.mentions:
                if mention.key:
                    prompt = prompt.replace(mention.key, " ")
            prompt = re.sub(r"(^|\s)@_[A-Za-z0-9_:-]+", " ", prompt)
        return " ".join(prompt.split())

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "source": self.source,
            "delivery": self.delivery,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "app_id": self.app_id,
            "tenant_key": self.tenant_key,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "sender_open_id": self.sender_open_id,
            "sender_user_id": self.sender_user_id,
            "sender_union_id": self.sender_union_id,
            "text": self.text,
            "prompt_text": self.prompt_text(),
            "mentions": [mention.to_dict() for mention in self.mentions],
        }
        if include_raw:
            payload["raw"] = self.raw
        return payload


def _parse_text(message_type: str, content: Any) -> str:
    content_payload = _as_dict(content)
    if "text" in content_payload:
        return str(content_payload["text"])
    if message_type == "text" and isinstance(content, str):
        return content
    if content_payload:
        return json.dumps(content_payload, ensure_ascii=False, sort_keys=True)
    return ""


def _parse_mentions(message: dict[str, Any]) -> list[FeishuMention]:
    mentions: list[FeishuMention] = []
    for item in message.get("mentions") or []:
        if not isinstance(item, dict):
            continue
        mention_id = item.get("id") if isinstance(item.get("id"), dict) else {}
        mentions.append(
            FeishuMention(
                key=_first_string(item.get("key")),
                name=_first_string(item.get("name")),
                open_id=_first_string(item.get("open_id"), mention_id.get("open_id")),
                user_id=_first_string(item.get("user_id"), mention_id.get("user_id")),
                union_id=_first_string(item.get("union_id"), mention_id.get("union_id")),
            )
        )
    return mentions


def parse_feishu_message_context(payload: dict[str, Any]) -> FeishuMessageContext:
    header = _as_dict(payload.get("header"))
    event = _as_dict(payload.get("event") or payload)
    message = _as_dict(event.get("message") or payload.get("message"))
    sender = _as_dict(event.get("sender") or payload.get("sender"))
    sender_id = _as_dict(sender.get("sender_id") or sender.get("id") or sender)
    message_type = _first_string(message.get("message_type"), payload.get("message_type")) or "text"

    return FeishuMessageContext(
        event_id=_first_string(header.get("event_id"), payload.get("event_id")),
        event_type=_first_string(header.get("event_type"), payload.get("event_type")),
        app_id=_first_string(header.get("app_id"), payload.get("app_id")),
        tenant_key=_first_string(
            header.get("tenant_key"),
            event.get("tenant_key"),
            sender.get("tenant_key"),
            payload.get("tenant_key"),
        ),
        chat_id=_first_string(message.get("chat_id"), payload.get("chat_id")),
        chat_type=_first_string(message.get("chat_type"), payload.get("chat_type")),
        message_id=_first_string(
            message.get("message_id"),
            message.get("open_message_id"),
            payload.get("message_id"),
            payload.get("open_message_id"),
        ),
        message_type=message_type,
        sender_open_id=_first_string(sender_id.get("open_id"), payload.get("sender_open_id")),
        sender_user_id=_first_string(sender_id.get("user_id"), payload.get("sender_user_id")),
        sender_union_id=_first_string(sender_id.get("union_id"), payload.get("sender_union_id")),
        text=_parse_text(message_type, message.get("content", payload.get("content"))),
        mentions=_parse_mentions(message),
        raw=payload,
    )
