"""Direct official QQ Bot transport primitives."""

from controlmesh.messenger.qqbot.inbound import QQBotIncomingText, normalize_gateway_event
from controlmesh.messenger.qqbot.known_targets import QQBotKnownTargetsStore
from controlmesh.messenger.qqbot.target import (
    looks_like_qqbot_target,
    normalize_target,
    parse_target,
)
from controlmesh.messenger.qqbot.types import ParsedQQTarget, QQBotRuntimeAccount, QQTargetType

__all__ = [
    "ParsedQQTarget",
    "QQBotIncomingText",
    "QQBotKnownTargetsStore",
    "QQBotRuntimeAccount",
    "QQTargetType",
    "looks_like_qqbot_target",
    "normalize_gateway_event",
    "normalize_target",
    "parse_target",
]
