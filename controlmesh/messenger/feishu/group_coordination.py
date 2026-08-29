"""Opt-in routing for groups that contain multiple real Feishu bots."""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Literal, Protocol

from controlmesh.config import FeishuGroupConfig

FeishuGroupRouteAction = Literal["respond", "observe", "drop"]


class FeishuGroupMessage(Protocol):
    """Inbound fields needed by the multi-bot router."""

    sender_id: str
    chat_id: str
    message_id: str
    text: str
    sender_type: str | None
    sender_is_bot: bool | None
    mention_open_ids: tuple[str, ...]
    mentions_bot: bool
    reply_sender_id: str | None
    replies_to_bot: bool


@dataclass(frozen=True, slots=True)
class FeishuGroupRouteDecision:
    """One local CM instance's disposition for an inbound group message."""

    action: FeishuGroupRouteAction
    reason: str
    broadcast: bool = False


class FeishuBotLoopGuard:
    """Bounded sliding-window guard for explicit bot-to-bot handoffs.

    The guard follows the shape of Lark's channel SDK: only bot-authored messages
    that explicitly target this bot consume budget, while a human message clears
    the chat's handoff chain.
    """

    _MAX_KEYS = 5000

    def __init__(self) -> None:
        self._events: OrderedDict[str, deque[tuple[float, str]]] = OrderedDict()

    def reset_chat(self, chat_id: str) -> None:
        """Clear all bot handoff windows for one chat."""
        prefix = f"{chat_id}:"
        for key in list(self._events):
            if key == chat_id or key.startswith(prefix):
                self._events.pop(key, None)

    def allow(
        self,
        *,
        chat_id: str,
        sender_id: str,
        message_id: str,
        scope: Literal["chat", "chat+sender"],
        window_seconds: float,
        max_bot_mentions: int,
        now: float | None = None,
    ) -> bool:
        """Return whether one explicitly addressed bot handoff may proceed."""
        timestamp = time.monotonic() if now is None else now
        key = chat_id if scope == "chat" else f"{chat_id}:{sender_id}"
        events = self._events.setdefault(key, deque())
        cutoff = timestamp - window_seconds
        while events and events[0][0] < cutoff:
            events.popleft()

        if any(seen_message_id == message_id for _, seen_message_id in events):
            return False
        if len(events) >= max_bot_mentions:
            return False

        events.append((timestamp, message_id))
        self._events.move_to_end(key)
        while len(self._events) > self._MAX_KEYS:
            self._events.popitem(last=False)
        return True


def decide_multi_bot_group_route(
    message: FeishuGroupMessage,
    *,
    group: FeishuGroupConfig,
    local_agent: str,
    loop_guard: FeishuBotLoopGuard,
) -> FeishuGroupRouteDecision:
    """Resolve whether the local CM should respond, observe, or drop a message."""
    identities = group.bot_identities
    local_bot_id = identities.get(local_agent, "")
    if not local_bot_id:
        return FeishuGroupRouteDecision("drop", "local_bot_identity_missing")

    configured_bot_ids = frozenset(identities.values())
    sender_type = (message.sender_type or "").strip().lower()
    sender_is_bot = bool(
        message.sender_is_bot is True
        or sender_type in {"bot", "app"}
        or message.sender_id in configured_bot_ids
    )
    mentioned_configured_bots = configured_bot_ids.intersection(message.mention_open_ids)
    targeted_configured_bots = set(mentioned_configured_bots)
    if message.reply_sender_id in configured_bot_ids:
        targeted_configured_bots.add(str(message.reply_sender_id))
    local_is_targeted = bool(
        local_bot_id in targeted_configured_bots or message.mentions_bot or message.replies_to_bot
    )
    if local_is_targeted:
        targeted_configured_bots.add(local_bot_id)

    if sender_is_bot:
        if message.sender_id == local_bot_id:
            return FeishuGroupRouteDecision("drop", "self_bot_message")
        if message.sender_id not in configured_bot_ids:
            return FeishuGroupRouteDecision("drop", "unknown_bot_sender")
        if not local_is_targeted:
            return FeishuGroupRouteDecision("drop", "bot_without_explicit_local_target")
        guard = group.bot_loop_guard
        if guard.enabled and not loop_guard.allow(
            chat_id=message.chat_id,
            sender_id=message.sender_id,
            message_id=message.message_id,
            scope=guard.scope,
            window_seconds=guard.window_seconds,
            max_bot_mentions=guard.max_bot_mentions,
        ):
            return FeishuGroupRouteDecision("drop", "bot_loop_guard")
        return FeishuGroupRouteDecision("respond", "explicit_bot_handoff")

    loop_guard.reset_chat(message.chat_id)
    stripped = message.text.strip()
    broadcast_command = group.broadcast_command
    if stripped == broadcast_command or stripped.startswith(f"{broadcast_command} "):
        return FeishuGroupRouteDecision("respond", "explicit_broadcast", broadcast=True)

    if targeted_configured_bots:
        if local_is_targeted:
            return FeishuGroupRouteDecision("respond", "explicit_local_bot_target")
        return FeishuGroupRouteDecision("observe", "different_bot_targeted")

    if local_agent == group.coordinator_agent:
        return FeishuGroupRouteDecision("respond", "coordinator_default")
    return FeishuGroupRouteDecision("observe", "coordinator_default_elsewhere")


def strip_broadcast_command(text: str, command: str) -> str:
    """Remove an exact broadcast command prefix before provider execution."""
    stripped = text.strip()
    if stripped == command:
        return "Respond to this explicit group broadcast."
    prefix = f"{command} "
    if stripped.startswith(prefix):
        return stripped[len(prefix) :].lstrip()
    return text
