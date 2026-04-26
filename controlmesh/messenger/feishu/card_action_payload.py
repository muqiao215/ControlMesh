"""Helpers for extracting Feishu card-action metadata across payload variants."""

from __future__ import annotations

from typing import Any


def extract_card_action_target(
    event: dict[str, Any],
) -> tuple[str | None, str, str | None]:
    """Return chat/message ids from legacy and P2 card-action payloads.

    P2 card-action events nest identifiers under ``event.context.*`` while some
    legacy webhook-shaped payloads flatten them directly onto ``event``.
    """

    context = event.get("context") if isinstance(event.get("context"), dict) else {}

    open_chat_id = context.get("open_chat_id") or event.get("open_chat_id")
    if isinstance(open_chat_id, str) and open_chat_id:
        chat_id = open_chat_id
        receive_id_type = "open_chat_id"
    else:
        raw_chat_id = context.get("chat_id") or event.get("chat_id")
        chat_id = raw_chat_id if isinstance(raw_chat_id, str) and raw_chat_id else None
        receive_id_type = "chat_id"

    raw_message_id = (
        context.get("open_message_id")
        or event.get("open_message_id")
        or context.get("message_id")
        or event.get("message_id")
    )
    message_id = raw_message_id if isinstance(raw_message_id, str) and raw_message_id else None
    return chat_id, receive_id_type, message_id
