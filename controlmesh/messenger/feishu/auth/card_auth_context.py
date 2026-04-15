"""Thin context objects for bridging Feishu messages into card auth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from controlmesh.config import AgentConfig

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.bot import FeishuIncomingText


@dataclass(frozen=True, slots=True)
class FeishuCardAuthContext:
    app_id: str
    app_secret: str
    brand: str
    sender_open_id: str
    chat_id: str
    trigger_message_id: str
    thread_id: str | None


def build_card_auth_context(
    config: AgentConfig,
    message: FeishuIncomingText,
) -> FeishuCardAuthContext:
    """Extract the smallest stable auth context from a Feishu message."""
    return FeishuCardAuthContext(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
        brand=config.feishu.brand,
        sender_open_id=message.sender_id,
        chat_id=message.chat_id,
        trigger_message_id=message.message_id,
        thread_id=message.thread_id,
    )
