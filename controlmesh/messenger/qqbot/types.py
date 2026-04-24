"""Shared types for the direct official QQ Bot transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

QQTargetType: TypeAlias = Literal["c2c", "group", "channel", "dm"]


@dataclass(frozen=True, slots=True)
class ParsedQQTarget:
    """Canonical parsed QQ delivery target."""

    type: QQTargetType
    id: str


@dataclass(frozen=True, slots=True)
class QQBotRuntimeAccount:
    """Resolved official QQ account ready for live runtime use."""

    account_key: str
    app_id: str
    client_secret: str
    allow_from: tuple[str, ...] = ()
    group_allow_from: tuple[str, ...] = ()
    dm_policy: Literal["open", "allowlist", "disabled"] = "open"
    group_policy: Literal["open", "allowlist", "disabled"] = "open"
    group_message_mode: Literal["passive", "mention_patterns"] = "passive"
    mention_patterns: tuple[str, ...] = ()
    activate_on_bot_reply: bool = False
