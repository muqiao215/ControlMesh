"""Tests for the minimal Weixin iLink long-poll runtime seam."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ductor_bot.messenger.weixin.auth_store import StoredWeixinCredentials
from ductor_bot.messenger.weixin.runtime import (
    WeixinIncomingText,
    WeixinLongPollRuntime,
    WeixinUpdateBatch,
)


@dataclass
class _FakeClient:
    updates: list[WeixinUpdateBatch]

    def __post_init__(self) -> None:
        self.get_updates_calls: list[tuple[StoredWeixinCredentials, str]] = []
        self.send_text_calls: list[tuple[StoredWeixinCredentials, str, str, str]] = []

    async def get_updates(
        self,
        credentials: StoredWeixinCredentials,
        cursor: str,
    ) -> WeixinUpdateBatch:
        self.get_updates_calls.append((credentials, cursor))
        return self.updates.pop(0)

    async def send_text(
        self,
        credentials: StoredWeixinCredentials,
        user_id: str,
        context_token: str,
        text: str,
    ) -> None:
        self.send_text_calls.append((credentials, user_id, context_token, text))


def _credentials() -> StoredWeixinCredentials:
    return StoredWeixinCredentials(
        token="bot-token",
        base_url="https://ilinkai.weixin.qq.com",
        account_id="bot-account",
        user_id="wx-user",
    )


def _user_text_message(*, text: str, context_token: str = "ctx-1") -> dict[str, object]:
    return {
        "message_id": 101,
        "from_user_id": "user-1",
        "to_user_id": "bot-account",
        "client_id": "client-1",
        "create_time_ms": 1710000000000,
        "message_type": 1,
        "message_state": 0,
        "context_token": context_token,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


class TestWeixinLongPollRuntime:
    async def test_poll_once_dispatches_user_text_and_caches_context_token(self) -> None:
        seen: list[WeixinIncomingText] = []
        client = _FakeClient(
            updates=[
                WeixinUpdateBatch(cursor="cursor-2", messages=[_user_text_message(text="hello wx")]),
            ]
        )
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=seen.append,
        )

        await runtime.poll_once()

        assert client.get_updates_calls == [(_credentials(), "")]
        assert runtime.cursor == "cursor-2"
        assert runtime.context_token_for("user-1") == "ctx-1"
        assert seen == [
            WeixinIncomingText(
                user_id="user-1",
                text="hello wx",
                context_token="ctx-1",
                message_id=101,
                raw=_user_text_message(text="hello wx"),
            )
        ]

    async def test_send_text_uses_cached_context_token(self) -> None:
        client = _FakeClient(updates=[])
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
        )
        runtime.remember_context("user-1", "ctx-1")

        await runtime.send_text("user-1", "pong")

        assert client.send_text_calls == [(_credentials(), "user-1", "ctx-1", "pong")]

    async def test_reply_uses_message_context_token(self) -> None:
        client = _FakeClient(updates=[])
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
        )
        message = WeixinIncomingText(
            user_id="user-1",
            text="ping",
            context_token="ctx-2",
            message_id=202,
            raw=_user_text_message(text="ping", context_token="ctx-2"),
        )

        await runtime.reply(message, "pong")

        assert runtime.context_token_for("user-1") == "ctx-2"
        assert client.send_text_calls == [(_credentials(), "user-1", "ctx-2", "pong")]

    async def test_send_text_requires_context_token(self) -> None:
        client = _FakeClient(updates=[])
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
        )

        with pytest.raises(RuntimeError, match="No cached context token for user user-1"):
            await runtime.send_text("user-1", "pong")
