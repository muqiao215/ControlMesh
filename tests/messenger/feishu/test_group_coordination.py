"""Tests for opt-in routing across multiple real Feishu bots."""

from __future__ import annotations

from dataclasses import dataclass

from controlmesh.config import FeishuGroupConfig
from controlmesh.messenger.feishu.group_coordination import (
    FeishuBotLoopGuard,
    decide_multi_bot_group_route,
    strip_broadcast_command,
)


@dataclass
class _Message:
    sender_id: str = "ou_human"
    chat_id: str = "oc_group"
    message_id: str = "om_1"
    text: str = "hello"
    sender_type: str | None = "user"
    sender_is_bot: bool | None = False
    mention_open_ids: tuple[str, ...] = ()
    mentions_bot: bool = False
    reply_sender_id: str | None = None
    replies_to_bot: bool = False


def _group(**overrides: object) -> FeishuGroupConfig:
    values: dict[str, object] = {
        "multi_bot_mode": True,
        "coordinator_agent": "main",
        "local_bot_agent": "main",
        "bot_identities": {
            "main": "ou_bot_main",
            "reviewer": "ou_bot_reviewer",
        },
    }
    values.update(overrides)
    return FeishuGroupConfig.model_validate(values)


def test_ordinary_human_message_only_activates_coordinator() -> None:
    message = _Message()
    group = _group()

    coordinator = decide_multi_bot_group_route(
        message,
        group=group,
        local_agent="main",
        loop_guard=FeishuBotLoopGuard(),
    )
    reviewer = decide_multi_bot_group_route(
        message,
        group=group,
        local_agent="reviewer",
        loop_guard=FeishuBotLoopGuard(),
    )

    assert (coordinator.action, coordinator.reason) == ("respond", "coordinator_default")
    assert (reviewer.action, reviewer.reason) == (
        "observe",
        "coordinator_default_elsewhere",
    )


def test_explicit_bot_target_silences_every_other_bot() -> None:
    message = _Message(mention_open_ids=("ou_bot_reviewer",))
    group = _group()

    coordinator = decide_multi_bot_group_route(
        message,
        group=group,
        local_agent="main",
        loop_guard=FeishuBotLoopGuard(),
    )
    reviewer = decide_multi_bot_group_route(
        message,
        group=group,
        local_agent="reviewer",
        loop_guard=FeishuBotLoopGuard(),
    )

    assert coordinator.action == "observe"
    assert reviewer.action == "respond"
    assert reviewer.reason == "explicit_local_bot_target"


def test_all_command_is_an_explicit_broadcast_and_is_removed_from_prompt() -> None:
    message = _Message(text="/all compare the two answers")
    decision = decide_multi_bot_group_route(
        message,
        group=_group(),
        local_agent="reviewer",
        loop_guard=FeishuBotLoopGuard(),
    )

    assert decision.action == "respond"
    assert decision.broadcast is True
    assert strip_broadcast_command(message.text, "/all") == "compare the two answers"
    assert strip_broadcast_command("/all", "/all") == "Respond to this explicit group broadcast."
    assert strip_broadcast_command("/allow normal", "/all") == "/allow normal"


def test_bot_message_requires_explicit_local_target() -> None:
    group = _group()
    untargeted = _Message(
        sender_id="ou_bot_main",
        sender_type="app",
        sender_is_bot=True,
    )
    targeted = _Message(
        sender_id="ou_bot_main",
        sender_type="app",
        sender_is_bot=True,
        mention_open_ids=("ou_bot_reviewer",),
    )

    assert (
        decide_multi_bot_group_route(
            untargeted,
            group=group,
            local_agent="reviewer",
            loop_guard=FeishuBotLoopGuard(),
        ).reason
        == "bot_without_explicit_local_target"
    )
    assert (
        decide_multi_bot_group_route(
            targeted,
            group=group,
            local_agent="reviewer",
            loop_guard=FeishuBotLoopGuard(),
        ).reason
        == "explicit_bot_handoff"
    )


def test_loop_guard_blocks_chain_until_human_message_resets_chat() -> None:
    guard = FeishuBotLoopGuard()
    group = _group(bot_loop_guard={"max_bot_mentions": 2, "window_seconds": 60})

    for index in range(2):
        message = _Message(
            sender_id="ou_bot_main",
            message_id=f"om_bot_{index}",
            sender_type="app",
            sender_is_bot=True,
            mention_open_ids=("ou_bot_reviewer",),
        )
        assert (
            decide_multi_bot_group_route(
                message,
                group=group,
                local_agent="reviewer",
                loop_guard=guard,
            ).action
            == "respond"
        )

    blocked = _Message(
        sender_id="ou_bot_main",
        message_id="om_bot_3",
        sender_type="app",
        sender_is_bot=True,
        mention_open_ids=("ou_bot_reviewer",),
    )
    assert (
        decide_multi_bot_group_route(
            blocked,
            group=group,
            local_agent="reviewer",
            loop_guard=guard,
        ).reason
        == "bot_loop_guard"
    )

    decide_multi_bot_group_route(
        _Message(message_id="om_human"),
        group=group,
        local_agent="reviewer",
        loop_guard=guard,
    )
    assert (
        decide_multi_bot_group_route(
            blocked,
            group=group,
            local_agent="reviewer",
            loop_guard=guard,
        ).action
        == "respond"
    )


def test_unknown_bot_sender_is_dropped() -> None:
    message = _Message(
        sender_id="ou_unknown_bot",
        sender_type="app",
        sender_is_bot=True,
        mention_open_ids=("ou_bot_main",),
    )

    decision = decide_multi_bot_group_route(
        message,
        group=_group(),
        local_agent="main",
        loop_guard=FeishuBotLoopGuard(),
    )

    assert (decision.action, decision.reason) == ("drop", "unknown_bot_sender")
