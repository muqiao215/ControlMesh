from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.qqbot.bot import QQBotBot
from controlmesh.messenger.qqbot.inbound import QQBotIncomingText, QQBotInteraction
from controlmesh.messenger.qqbot.outbound import reset_reply_tracker
from controlmesh.messenger.qqbot.ref_index import QQBotRefIndexEntry
from controlmesh.messenger.qqbot.types import QQBotRuntimeAccount
from controlmesh.orchestrator.selectors.models import Button, ButtonGrid
from controlmesh.session.key import SessionKey


@pytest.fixture(autouse=True)
def _reset_qqbot_reply_tracker() -> None:
    reset_reply_tracker()


async def test_run_initializes_orchestrator_and_executes_startup_hooks(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    startup_hook = AsyncMock()
    bot.register_startup_hook(startup_hook)

    fake_orchestrator = MagicMock()

    async def _fake_start_runtime() -> None:
        bot._stop_event.set()

    with (
        patch("controlmesh.orchestrator.core.Orchestrator.create", AsyncMock(return_value=fake_orchestrator)),
        patch.object(bot, "_start_runtime", _fake_start_runtime),
        patch.object(bot, "_close_runtime", AsyncMock()),
    ):
        exit_code = await bot.run()
    if bot._session is not None and not bot._session.closed:
        await bot._session.close()

    assert exit_code == 0
    fake_orchestrator.wire_observers_to_bus.assert_called_once_with(bot._bus)
    startup_hook.assert_awaited_once()


def test_resolve_account_uses_named_default_and_secret_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "qqbot.secret"
    secret_file.write_text("secret-from-file\n", encoding="utf-8")
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "default_account": "bot2",
            "accounts": {
                "bot1": {"app_id": "1903891441", "client_secret": "secret-1"},
                "bot2": {
                    "app_id": "1903891442",
                    "client_secret_file": str(secret_file),
                    "allow_from": ["USER_A"],
                    "group_allow_from": ["GROUP_A"],
                },
            },
        },
    )
    bot = QQBotBot(config)

    account = bot._resolve_account()

    assert account == QQBotRuntimeAccount(
        account_key="bot2",
        app_id="1903891442",
        client_secret="secret-from-file",
        allow_from=("USER_A",),
        group_allow_from=("GROUP_A",),
        dm_policy="open",
        group_policy="open",
        group_message_mode="passive",
        mention_patterns=(),
        activate_on_bot_reply=False,
    )


async def test_broadcast_text_fans_out_to_allowlisted_targets(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "allow_from": ["USER_A"],
            "group_allow_from": ["GROUP_A"],
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(send_text_message=AsyncMock())
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.broadcast_text("hello")

    bot._api_client.send_text_message.assert_has_awaits(
        [
            call("TOKEN123", "qqbot:c2c:USER_A", "hello"),
            call("TOKEN123", "qqbot:group:GROUP_A", "hello"),
        ]
    )


async def test_broadcast_text_honors_disabled_policy(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "allow_from": ["USER_A"],
            "group_allow_from": ["GROUP_A"],
            "group_policy": "disabled",
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(send_text_message=AsyncMock())
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.broadcast_text("hello")

    bot._api_client.send_text_message.assert_awaited_once_with(
        "TOKEN123",
        "qqbot:c2c:USER_A",
        "hello",
    )


async def test_broadcast_text_skips_wildcard_allowlist_entries(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "allow_from": ["*", "USER_A"],
            "group_allow_from": ["*", "GROUP_A"],
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(send_text_message=AsyncMock())
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.broadcast_text("hello")

    bot._api_client.send_text_message.assert_has_awaits(
        [
            call("TOKEN123", "qqbot:c2c:USER_A", "hello"),
            call("TOKEN123", "qqbot:group:GROUP_A", "hello"),
        ]
    )


async def test_broadcast_text_uses_discovered_targets_when_policy_open(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._known_targets.record_target("1903891442", "qqbot:c2c:USER_A")
    bot._known_targets.record_target("1903891442", "qqbot:group:GROUP_A")
    bot._known_targets.record_target("1903891442", "qqbot:dm:GUILD_DM_A")
    bot._api_client = SimpleNamespace(send_text_message=AsyncMock())
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.broadcast_text("hello")

    bot._api_client.send_text_message.assert_has_awaits(
        [
            call("TOKEN123", "qqbot:c2c:USER_A", "hello"),
            call("TOKEN123", "qqbot:dm:GUILD_DM_A", "hello"),
            call("TOKEN123", "qqbot:group:GROUP_A", "hello"),
        ]
    )


async def test_broadcast_text_ignores_discovered_targets_when_allowlist_policy(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "dm_policy": "allowlist",
            "group_policy": "allowlist",
            "allow_from": ["USER_CFG"],
            "group_allow_from": ["GROUP_CFG"],
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._known_targets.record_target("1903891442", "qqbot:c2c:USER_A")
    bot._known_targets.record_target("1903891442", "qqbot:group:GROUP_A")
    bot._known_targets.record_target("1903891442", "qqbot:dm:GUILD_DM_A")
    bot._api_client = SimpleNamespace(send_text_message=AsyncMock())
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.broadcast_text("hello")

    bot._api_client.send_text_message.assert_has_awaits(
        [
            call("TOKEN123", "qqbot:c2c:USER_CFG", "hello"),
            call("TOKEN123", "qqbot:group:GROUP_CFG", "hello"),
        ]
    )


async def test_handle_incoming_text_routes_to_orchestrator_and_replies(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong"))
    )
    bot._orchestrator = orchestrator
    bot.send_text = AsyncMock()  # type: ignore[method-assign]
    message = QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-1",
        text="ping",
    )

    await bot.handle_incoming_text(message)

    key = orchestrator.handle_message_streaming.await_args.args[0]
    assert key == SessionKey.for_transport("qqbot", "qqbot:c2c:USER_A")
    assert orchestrator.handle_message_streaming.await_args.args[1] == "ping"
    bot.send_text.assert_awaited_once_with("qqbot:c2c:USER_A", "pong")
    assert bot._known_targets.list_targets("1903891442", kinds=("c2c",)) == ("qqbot:c2c:USER_A",)


async def test_handle_incoming_text_uses_passive_reply_msg_id_for_text_send(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(return_value={"id": "reply-1"}),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))
    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong"))
    )
    message = QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-1",
        text="ping",
    )

    await bot.handle_incoming_text(message)

    bot._api_client.send_text_message.assert_awaited_once_with(
        "TOKEN123",
        "qqbot:c2c:USER_A",
        "pong",
        msg_id="msg-1",
    )


async def test_handle_incoming_c2c_text_sends_input_notify_before_reply_handling(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    call_order: list[str] = []

    async def _send_c2c_input_notify(*args, **kwargs):
        call_order.append("typing")
        return {"ref_idx": "typing-ref-1"}

    async def _handle_message_streaming(*args, **kwargs):
        call_order.append("orchestrator")
        return SimpleNamespace(text="pong")

    bot._api_client = SimpleNamespace(
        send_c2c_input_notify=AsyncMock(side_effect=_send_c2c_input_notify),
        send_text_message=AsyncMock(return_value={"id": "reply-1"}),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(
        get_token_value=AsyncMock(return_value="TOKEN123"),
        clear_cache=MagicMock(),
    )
    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(side_effect=_handle_message_streaming)
    )
    message = QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-typing-1",
        text="ping",
    )

    await bot.handle_incoming_text(message)

    assert call_order[:2] == ["typing", "orchestrator"]
    bot._api_client.send_c2c_input_notify.assert_awaited_once_with(
        "TOKEN123",
        "USER_A",
        msg_id="msg-typing-1",
        input_second=60,
    )


async def test_handle_incoming_c2c_text_keeps_typing_alive_while_processing(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_c2c_input_notify=AsyncMock(return_value={"ref_idx": "typing-ref-1"}),
        send_text_message=AsyncMock(return_value={"id": "reply-1"}),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(
        get_token_value=AsyncMock(return_value="TOKEN123"),
        clear_cache=MagicMock(),
    )

    async def _slow_handle_message_streaming(*args, **kwargs):
        await asyncio.sleep(0.03)
        return SimpleNamespace(text="pong")

    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(side_effect=_slow_handle_message_streaming)
    )
    message = QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-typing-2",
        text="ping",
    )

    with patch("controlmesh.messenger.qqbot.typing_keepalive.TYPING_INTERVAL_SECONDS", 0.01):
        await bot.handle_incoming_text(message)

    assert bot._api_client.send_c2c_input_notify.await_count >= 2


async def test_handle_incoming_dm_text_uses_sender_scoped_c2c_input_notify(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_c2c_input_notify=AsyncMock(return_value={"ref_idx": "typing-ref-1"}),
        send_text_message=AsyncMock(return_value={"id": "reply-1"}),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(
        get_token_value=AsyncMock(return_value="TOKEN123"),
        clear_cache=MagicMock(),
    )
    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong"))
    )
    message = QQBotIncomingText(
        event_type="DIRECT_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-dm-typing-1",
        text="ping",
    )

    await bot.handle_incoming_text(message)

    bot._api_client.send_c2c_input_notify.assert_awaited_once_with(
        "TOKEN123",
        "USER_A",
        msg_id="msg-dm-typing-1",
        input_second=60,
    )


async def test_handle_incoming_text_falls_back_to_proactive_text_after_passive_reply_limit(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(return_value={"id": "reply-5"}),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))
    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="pong-5"))
    )
    message = QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-limit-1",
        text="ping",
    )

    for _ in range(5):
        await bot.handle_incoming_text(message)

    assert bot._api_client.send_text_message.await_count == 5
    first_four = bot._api_client.send_text_message.await_args_list[:4]
    for send_call in first_four:
        assert send_call.args == ("TOKEN123", "qqbot:c2c:USER_A", "pong-5")
        assert send_call.kwargs["msg_id"] == "msg-limit-1"

    fallback_call = bot._api_client.send_text_message.await_args_list[4]
    assert fallback_call.args == ("TOKEN123", "qqbot:c2c:USER_A", "pong-5")
    assert "msg_id" not in fallback_call.kwargs


async def test_handle_incoming_text_sends_inline_keyboard_for_c2c_selector_response(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(return_value={"id": "reply-1"}),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))
    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(
            return_value=SimpleNamespace(
                text="pick a mode",
                buttons=ButtonGrid(rows=[[Button(text="OPUS", callback_data="ms:m:opus")]]),
            )
        )
    )
    message = QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-buttons-1",
        text="/model",
    )

    await bot.handle_incoming_text(message)

    send_call = bot._api_client.send_text_message.await_args
    assert send_call.args == ("TOKEN123", "qqbot:c2c:USER_A", "pick a mode")
    assert send_call.kwargs["msg_id"] == "msg-buttons-1"
    assert send_call.kwargs["inline_keyboard"] == {
        "content": {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": "cm-btn-0",
                            "render_data": {
                                "label": "OPUS",
                                "visited_label": "OPUS",
                                "style": 1,
                            },
                            "action": {
                                "type": 1,
                                "data": "ms:m:opus",
                                "permission": {"type": 0},
                                "click_limit": 1,
                            },
                            "group_id": "cm-row-0",
                        }
                    ]
                }
            ]
        }
    }


async def test_handle_incoming_text_uses_passive_reply_msg_id_for_attachment_send(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image_path = workspace / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(return_value={"id": "reply-image-1"}),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))
    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text=f"<file:{image_path}>"))
    )
    message = QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-attach-1",
        text="ping",
    )

    await bot.handle_incoming_text(message)

    bot._api_client.send_text_message.assert_not_called()
    bot._api_client.send_image_message.assert_awaited_once_with(
        "TOKEN123",
        "qqbot:c2c:USER_A",
        file_name="image.png",
        file_bytes=image_path.read_bytes(),
        msg_id="msg-attach-1",
    )


async def test_handle_incoming_direct_message_uses_c2c_attachment_send(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image_path = workspace / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(return_value={"id": "reply-dm-image-1"}),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))
    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text=f"<file:{image_path}>"))
    )
    message = QQBotIncomingText(
        event_type="DIRECT_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_DM_A",
        sender_id="USER_DM_A",
        message_id="msg-dm-attach-1",
        text="ping",
    )

    await bot.handle_incoming_text(message)

    bot._api_client.send_text_message.assert_not_called()
    bot._api_client.send_image_message.assert_awaited_once_with(
        "TOKEN123",
        "qqbot:c2c:USER_DM_A",
        file_name="image.png",
        file_bytes=image_path.read_bytes(),
        msg_id="msg-dm-attach-1",
    )


async def test_handle_incoming_text_falls_back_to_proactive_attachment_send_after_passive_reply_limit(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image_path = workspace / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(return_value={"id": "reply-image-limit-1"}),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))
    bot._orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text=f"<file:{image_path}>"))
    )
    message = QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-attach-limit-1",
        text="ping",
    )

    for _ in range(5):
        await bot.handle_incoming_text(message)

    assert bot._api_client.send_image_message.await_count == 5
    first_four = bot._api_client.send_image_message.await_args_list[:4]
    for send_call in first_four:
        assert send_call.args == ("TOKEN123", "qqbot:c2c:USER_A")
        assert send_call.kwargs["file_name"] == "image.png"
        assert send_call.kwargs["file_bytes"] == image_path.read_bytes()
        assert send_call.kwargs["msg_id"] == "msg-attach-limit-1"

    fallback_call = bot._api_client.send_image_message.await_args_list[4]
    assert fallback_call.args == ("TOKEN123", "qqbot:c2c:USER_A")
    assert fallback_call.kwargs["file_name"] == "image.png"
    assert fallback_call.kwargs["file_bytes"] == image_path.read_bytes()
    assert "msg_id" not in fallback_call.kwargs


async def test_handle_group_incoming_text_uses_per_user_isolated_session_and_group_reply(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="group-pong"))
    )
    bot._orchestrator = orchestrator
    bot.send_text = AsyncMock()  # type: ignore[method-assign]
    message = QQBotIncomingText(
        event_type="GROUP_AT_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        message_id="msg-2",
        text="ping",
        topic_id="member:USER_A",
    )

    await bot.handle_incoming_text(message)

    key = orchestrator.handle_message_streaming.await_args.args[0]
    assert key == SessionKey.for_transport("qqbot", "qqbot:group:GROUP_A", "member:USER_A")
    assert orchestrator.handle_message_streaming.await_args.args[1] == "ping"
    bot.send_text.assert_awaited_once_with("qqbot:group:GROUP_A", "group-pong")


async def test_handle_interaction_routes_shared_callback_and_replies_with_buttons(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        acknowledge_interaction=AsyncMock(),
        send_text_message=AsyncMock(return_value={"id": "reply-1"}),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))
    bot._orchestrator = MagicMock()
    interaction = QQBotInteraction(
        interaction_id="interaction-1",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        button_data="ms:m:opus",
        button_id="btn-1",
        message_id="msg-1",
        topic_id="member:USER_A",
    )

    with patch(
        "controlmesh.messenger.callback_router.route_callback",
        AsyncMock(
            return_value=SimpleNamespace(
                handled=True,
                text="switched",
                buttons=ButtonGrid(rows=[[Button(text="Claude", callback_data="ms:p:claude")]]),
            )
        ),
    ) as route_callback:
        await bot._handle_interaction(interaction)

    bot._api_client.acknowledge_interaction.assert_awaited_once_with("TOKEN123", "interaction-1")
    route_args = route_callback.await_args.args
    assert route_args[1] == SessionKey.for_transport("qqbot", "qqbot:group:GROUP_A", "member:USER_A")
    assert route_args[2] == "ms:m:opus"
    send_call = bot._api_client.send_text_message.await_args
    assert send_call.args == ("TOKEN123", "qqbot:group:GROUP_A", "switched")
    assert send_call.kwargs["msg_id"] == "msg-1"
    assert "inline_keyboard" in send_call.kwargs


async def test_handle_interaction_defers_approval_button_semantics_explicitly(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        acknowledge_interaction=AsyncMock(),
        send_text_message=AsyncMock(return_value={"id": "reply-1"}),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))
    bot._orchestrator = MagicMock()
    interaction = QQBotInteraction(
        interaction_id="interaction-approval-1",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        button_data="approve:exec:123e4567-e89b-12d3-a456-426614174000:allow-once",
        message_id="msg-approval-1",
    )

    with patch("controlmesh.messenger.callback_router.route_callback", AsyncMock()) as route_callback:
        await bot._handle_interaction(interaction)

    bot._api_client.acknowledge_interaction.assert_awaited_once_with(
        "TOKEN123", "interaction-approval-1"
    )
    route_callback.assert_not_awaited()
    bot._api_client.send_text_message.assert_awaited_once()
    send_call = bot._api_client.send_text_message.await_args
    assert send_call.args[0:3] == (
        "TOKEN123",
        "qqbot:c2c:USER_A",
        "[ControlMesh qqbot approvals are not implemented in the direct runtime yet. "
        "OpenClaw approval-handler semantics remain reference-only in Phase 6.]",
    )
    assert send_call.kwargs["msg_id"] == "msg-approval-1"


async def test_handle_gateway_dispatch_records_passive_group_message_without_reply(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-gm-1",
            "content": "plain group traffic",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
        },
    )

    bot.handle_incoming_text.assert_not_called()
    assert bot._known_targets.list_targets("1903891442", kinds=("group",)) == ("qqbot:group:GROUP_A",)


async def test_handle_gateway_dispatch_activates_plain_group_message_for_text_mention_pattern(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "group_message_mode": "mention_patterns",
            "mention_patterns": ["ControlMesh"],
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-gm-2",
            "content": "@ControlMesh status please",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
        },
    )

    bot.handle_incoming_text.assert_awaited_once()
    event = bot.handle_incoming_text.await_args.args[0]
    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        message_id="msg-gm-2",
        text="@ControlMesh status please",
        topic_id="member:USER_A",
    )


async def test_handle_gateway_dispatch_activates_plain_group_slash_command_in_passive_mode(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "group_message_mode": "passive",
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-gm-slash-1",
            "content": "   /status   ",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
        },
    )

    bot.handle_incoming_text.assert_awaited_once()
    event = bot.handle_incoming_text.await_args.args[0]
    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        message_id="msg-gm-slash-1",
        text="/status",
        topic_id="member:USER_A",
    )


async def test_handle_gateway_dispatch_keeps_plain_group_message_passive_without_text_mention_match(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "group_message_mode": "mention_patterns",
            "mention_patterns": ["ControlMesh"],
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-gm-3",
            "content": "plain group traffic",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
        },
    )

    bot.handle_incoming_text.assert_not_called()
    assert bot._known_targets.list_targets("1903891442", kinds=("group",)) == ("qqbot:group:GROUP_A",)


async def test_handle_gateway_dispatch_activates_plain_group_slash_command_even_without_mention_match(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "group_message_mode": "mention_patterns",
            "mention_patterns": ["ControlMesh"],
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-gm-slash-2",
            "content": "/help",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
        },
    )

    bot.handle_incoming_text.assert_awaited_once()
    event = bot.handle_incoming_text.await_args.args[0]
    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        message_id="msg-gm-slash-2",
        text="/help",
        topic_id="member:USER_A",
    )


async def test_handle_gateway_dispatch_keeps_quote_like_plain_group_message_passive_without_supported_activation(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "group_message_mode": "mention_patterns",
            "mention_patterns": ["ControlMesh"],
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-gm-4",
            "content": "replying without explicit text mention",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
            "message_scene": {
                "source": "quote",
                "ext": ["ref_msg_idx=REFIDX_bot_message", "msg_idx=REFIDX_current"],
            },
            "msg_elements": [
                {
                    "msg_idx": "REFIDX_bot_message",
                    "message_type": 7,
                    "content": "prior bot message",
                }
            ],
        },
    )

    bot.handle_incoming_text.assert_not_called()
    assert bot._known_targets.list_targets("1903891442", kinds=("group",)) == ("qqbot:group:GROUP_A",)


async def test_handle_gateway_dispatch_activates_plain_group_message_for_bot_reply_reference(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "activate_on_bot_reply": True,
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._ref_index.record_ref(
        "1903891442",
        "REFIDX_bot_message",
        QQBotRefIndexEntry(
            target="qqbot:group:GROUP_A",
            content="prior bot message",
            timestamp_ms=1,
            is_bot=True,
        ),
    )
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-gm-5",
            "content": "replying without explicit text mention",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
            "message_scene": {
                "source": "quote",
                "ext": ["ref_msg_idx=REFIDX_bot_message", "msg_idx=REFIDX_current"],
            },
        },
    )

    bot.handle_incoming_text.assert_awaited_once()
    event = bot.handle_incoming_text.await_args.args[0]
    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        message_id="msg-gm-5",
        text="replying without explicit text mention",
        topic_id="member:USER_A",
        ref_msg_idx="REFIDX_bot_message",
        msg_idx="REFIDX_current",
    )


async def test_handle_gateway_dispatch_activates_bot_reply_reference_from_quote_message_type_without_ext(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "activate_on_bot_reply": True,
        },
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._ref_index.record_ref(
        "1903891442",
        "REFIDX_quote_only",
        QQBotRefIndexEntry(
            target="qqbot:group:GROUP_A",
            content="prior bot message",
            timestamp_ms=1,
            is_bot=True,
        ),
    )
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-gm-5b",
            "content": "replying via quote message type",
            "group_openid": "GROUP_A",
            "timestamp": "2026-04-24T00:00:00Z",
            "message_type": 103,
            "msg_elements": [
                {
                    "msg_idx": "REFIDX_quote_only",
                    "message_type": 0,
                    "content": "prior bot message",
                }
            ],
            "author": {
                "id": "member-id",
                "member_openid": "USER_A",
            },
        },
    )

    bot.handle_incoming_text.assert_awaited_once()
    event = bot.handle_incoming_text.await_args.args[0]
    assert event == QQBotIncomingText(
        event_type="GROUP_MESSAGE_CREATE",
        chat_id="qqbot:group:GROUP_A",
        sender_id="USER_A",
        message_id="msg-gm-5b",
        text="Quoted message:\nprior bot message\n\nreplying via quote message type",
        topic_id="member:USER_A",
        ref_msg_idx="REFIDX_quote_only",
    )


async def test_handle_gateway_dispatch_accepts_attachment_only_c2c_event(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot.handle_incoming_text = AsyncMock()  # type: ignore[method-assign]

    await bot._handle_gateway_dispatch(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg-c2c-attachment-1",
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

    bot.handle_incoming_text.assert_awaited_once()
    event = bot.handle_incoming_text.await_args.args[0]
    assert event == QQBotIncomingText(
        event_type="C2C_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_A",
        sender_id="USER_A",
        message_id="msg-c2c-attachment-1",
        text="Attachment: image.png (image/png) https://cdn.example/image.png",
    )


async def test_send_text_records_outbound_ref_index(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(return_value={"ext_info": {"ref_idx": "REFIDX_out_1"}}),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text("qqbot:group:GROUP_A", "hello group")

    entry = bot._ref_index.get_ref("1903891442", "REFIDX_out_1")
    assert entry is not None
    assert entry.target == "qqbot:group:GROUP_A"
    assert entry.content == "hello group"
    assert entry.is_bot is True
    assert entry.timestamp_ms > 0


async def test_handle_dm_incoming_text_routes_to_sender_scoped_c2c_session_and_reply_target(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    orchestrator = SimpleNamespace(
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="dm-pong"))
    )
    bot._orchestrator = orchestrator
    bot.send_text = AsyncMock()  # type: ignore[method-assign]
    message = QQBotIncomingText(
        event_type="DIRECT_MESSAGE_CREATE",
        chat_id="qqbot:c2c:USER_DM_A",
        sender_id="USER_DM_A",
        message_id="msg-dm-1",
        text="ping",
    )

    await bot.handle_incoming_text(message)

    key = orchestrator.handle_message_streaming.await_args.args[0]
    assert key == SessionKey.for_transport("qqbot", "qqbot:c2c:USER_DM_A")
    assert orchestrator.handle_message_streaming.await_args.args[1] == "ping"
    bot.send_text.assert_awaited_once_with("qqbot:c2c:USER_DM_A", "dm-pong")
    assert bot._known_targets.list_targets("1903891442", kinds=("c2c",)) == ("qqbot:c2c:USER_DM_A",)


async def test_on_task_result_uses_live_qq_target(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot.send_text = AsyncMock()  # type: ignore[method-assign]
    result = SimpleNamespace(chat_id="qqbot:c2c:USER_A", result_text="done")

    await bot.on_task_result(result)

    bot.send_text.assert_awaited_once_with("qqbot:c2c:USER_A", "done")


async def test_on_task_question_uses_live_qq_target(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot.send_text = AsyncMock()  # type: ignore[method-assign]

    await bot.on_task_question(
        "task-1",
        "What now?",
        "preview",
        "qqbot:group:GROUP_A",
    )

    bot.send_text.assert_awaited_once()
    assert bot.send_text.await_args.args[0] == "qqbot:group:GROUP_A"
    assert "task-1" in bot.send_text.await_args.args[1]


async def test_send_text_sends_clean_text_then_image_attachment(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image_path = workspace / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text("qqbot:c2c:USER_A", f"hello <file:{image_path}>")

    bot._api_client.send_text_message.assert_awaited_once_with(
        "TOKEN123",
        "qqbot:c2c:USER_A",
        "hello",
    )
    bot._api_client.send_image_message.assert_awaited_once()
    assert bot._api_client.send_image_message.await_args.args[:2] == (
        "TOKEN123",
        "qqbot:c2c:USER_A",
    )
    assert bot._api_client.send_image_message.await_args.kwargs["file_name"] == "image.png"
    assert bot._api_client.send_image_message.await_args.kwargs["file_bytes"].startswith(b"\x89PNG")
    bot._api_client.send_file_message.assert_not_called()


async def test_send_text_filters_internal_markers_before_text_send(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text(
        "qqbot:c2c:USER_A",
        "hello\n\n[[reply_to: msg-1]]\n@image:image_123.png\n\nworld",
    )

    bot._api_client.send_text_message.assert_awaited_once_with(
        "TOKEN123",
        "qqbot:c2c:USER_A",
        "hello\n\nworld",
    )
    bot._api_client.send_image_message.assert_not_called()
    bot._api_client.send_file_message.assert_not_called()


async def test_send_text_skips_send_when_only_internal_markers_remain(tmp_path: Path) -> None:
    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text(
        "qqbot:c2c:USER_A",
        "[[reply_to: msg-1]]\n@voice:voice_123.silk",
    )

    bot._api_client.send_text_message.assert_not_called()
    bot._api_client.send_image_message.assert_not_called()
    bot._api_client.send_file_message.assert_not_called()


async def test_send_text_filters_internal_markers_without_affecting_file_tags(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image_path = workspace / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text(
        "qqbot:c2c:USER_A",
        f"hello\n@image:image_123.png\n[[reply_to: msg-1]]\n<file:{image_path}>",
    )

    bot._api_client.send_text_message.assert_awaited_once_with(
        "TOKEN123",
        "qqbot:c2c:USER_A",
        "hello",
    )
    bot._api_client.send_image_message.assert_awaited_once()
    assert bot._api_client.send_image_message.await_args.args[:2] == (
        "TOKEN123",
        "qqbot:c2c:USER_A",
    )
    assert bot._api_client.send_image_message.await_args.kwargs["file_name"] == "image.png"
    bot._api_client.send_file_message.assert_not_called()


async def test_send_text_sends_file_attachment_without_clean_text(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_path = workspace / "report.pdf"
    file_path.write_bytes(b"%PDF-1.7 fake")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text("qqbot:group:GROUP_A", f"<file:{file_path}>")

    bot._api_client.send_text_message.assert_not_called()
    bot._api_client.send_image_message.assert_not_called()
    bot._api_client.send_file_message.assert_awaited_once()
    assert bot._api_client.send_file_message.await_args.args[:2] == (
        "TOKEN123",
        "qqbot:group:GROUP_A",
    )
    assert bot._api_client.send_file_message.await_args.kwargs["file_name"] == "report.pdf"
    assert bot._api_client.send_file_message.await_args.kwargs["file_bytes"].startswith(b"%PDF")


async def test_send_text_reports_blocked_attachment_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    blocked_root = tmp_path / "blocked"
    blocked_root.mkdir()
    blocked_file = blocked_root / "secret.txt"
    blocked_file.write_text("secret", encoding="utf-8")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        file_access="workspace",
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text("qqbot:c2c:USER_A", f"<file:{blocked_file}>")

    bot._api_client.send_text_message.assert_awaited_once()
    warning_text = bot._api_client.send_text_message.await_args.args[2]
    assert "outside allowed roots" in warning_text
    assert "secret.txt" in warning_text
    bot._api_client.send_image_message.assert_not_called()
    bot._api_client.send_file_message.assert_not_called()


async def test_send_text_reports_channel_attachment_deferral(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image_path = workspace / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text("qqbot:channel:CHANNEL_A", f"hello <file:{image_path}>")

    bot._api_client.send_text_message.assert_has_awaits(
        [
            call("TOKEN123", "qqbot:channel:CHANNEL_A", "hello"),
            call(
                "TOKEN123",
                "qqbot:channel:CHANNEL_A",
                "[ControlMesh qqbot skipped 1 attachment(s): channel media delivery is not implemented yet.]",
            ),
        ]
    )
    bot._api_client.send_image_message.assert_not_called()
    bot._api_client.send_file_message.assert_not_called()


async def test_send_text_reports_dm_attachment_deferral(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image_path = workspace / "image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    config = AgentConfig(
        transport="qqbot",
        controlmesh_home=str(tmp_path),
        qqbot={"app_id": "1903891442", "client_secret": "secret"},
    )
    bot = QQBotBot(config)
    bot._runtime_account = bot._resolve_account()
    bot._api_client = SimpleNamespace(
        send_text_message=AsyncMock(),
        send_image_message=AsyncMock(),
        send_file_message=AsyncMock(),
    )
    bot._token_manager = SimpleNamespace(get_token_value=AsyncMock(return_value="TOKEN123"))

    await bot.send_text("qqbot:dm:GUILD_DM_A", f"hello <file:{image_path}>")

    bot._api_client.send_text_message.assert_has_awaits(
        [
            call("TOKEN123", "qqbot:dm:GUILD_DM_A", "hello"),
            call(
                "TOKEN123",
                "qqbot:dm:GUILD_DM_A",
                "[ControlMesh qqbot skipped 1 attachment(s): dm media delivery is not implemented yet.]",
            ),
        ]
    )
    bot._api_client.send_image_message.assert_not_called()
    bot._api_client.send_file_message.assert_not_called()
