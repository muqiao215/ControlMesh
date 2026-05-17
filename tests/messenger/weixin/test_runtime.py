"""Tests for the minimal Weixin iLink long-poll runtime seam."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from controlmesh.messenger.weixin.api import WeixinIlinkApiError
from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials
from controlmesh.messenger.weixin.inbound_spool import WeixinInboundSpool
from controlmesh.messenger.weixin.runtime import (
    WeixinContextTokenRequiredError,
    WeixinIncomingText,
    WeixinLongPollRuntime,
    WeixinPollResult,
    WeixinReauthRequiredError,
    WeixinUpdateBatch,
)
from controlmesh.messenger.weixin.runtime_state import WeixinRuntimeState, WeixinRuntimeStateStore


@dataclass
class _FakeClient:
    updates: list[WeixinUpdateBatch]
    get_updates_error: Exception | None = None
    send_text_error: Exception | None = None

    def __post_init__(self) -> None:
        self.get_updates_calls: list[tuple[StoredWeixinCredentials, str]] = []
        self.send_text_calls: list[tuple[StoredWeixinCredentials, str, str, str]] = []

    async def get_updates(
        self,
        credentials: StoredWeixinCredentials,
        cursor: str,
    ) -> WeixinUpdateBatch:
        self.get_updates_calls.append((credentials, cursor))
        if self.get_updates_error is not None:
            raise self.get_updates_error
        return self.updates.pop(0)

    async def send_text(
        self,
        credentials: StoredWeixinCredentials,
        user_id: str,
        context_token: str,
        text: str,
        *,
        client_ids: list[str] | None = None,
    ) -> None:
        if self.send_text_error is not None:
            raise self.send_text_error
        self.send_text_calls.append((credentials, user_id, context_token, text, tuple(client_ids or ())))


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
    async def test_runtime_restores_saved_cursor_for_next_poll(self, tmp_path: Path) -> None:
        state_store = WeixinRuntimeStateStore(tmp_path)
        state_store.save_state(
            _credentials(),
            WeixinRuntimeState(cursor="cursor-1", context_tokens=(("user-1", "ctx-restore"),)),
        )
        client = _FakeClient(
            updates=[
                WeixinUpdateBatch(cursor="cursor-2", messages=[]),
            ]
        )
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
            state_store=state_store,
        )

        await runtime.poll_once()

        assert client.get_updates_calls == [(_credentials(), "cursor-1")]
        assert runtime.cursor == "cursor-2"

    async def test_poll_once_persists_cursor_and_context_for_restart(self, tmp_path: Path) -> None:
        state_store = WeixinRuntimeStateStore(tmp_path)
        spool = WeixinInboundSpool(tmp_path, _credentials())
        client = _FakeClient(
            updates=[
                WeixinUpdateBatch(cursor="cursor-2", messages=[_user_text_message(text="hello wx")]),
            ]
        )
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
            state_store=state_store,
            inbound_spool=spool,
        )

        await runtime.poll_once()

        assert state_store.load_state(_credentials()) == WeixinRuntimeState(
            cursor="cursor-2",
            context_tokens=(("user-1", "ctx-1"),),
            last_inbound_drain_at=state_store.load_state(_credentials()).last_inbound_drain_at,
        )

        restored_client = _FakeClient(updates=[])
        restored_runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=restored_client,
            on_text=lambda _message: None,
            state_store=state_store,
            inbound_spool=WeixinInboundSpool(tmp_path, _credentials()),
        )

        await restored_runtime.send_text("user-1", "pong")

        assert restored_client.send_text_calls == [
            (_credentials(), "user-1", "ctx-1", "pong", restored_client.send_text_calls[0][4])
        ]

    async def test_context_cache_is_bounded_and_evicts_oldest_user(self, tmp_path: Path) -> None:
        state_store = WeixinRuntimeStateStore(tmp_path)
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=_FakeClient(updates=[]),
            on_text=lambda _message: None,
            state_store=state_store,
            max_context_tokens=2,
        )

        runtime.remember_context("user-1", "ctx-1")
        runtime.remember_context("user-2", "ctx-2")
        runtime.remember_context("user-3", "ctx-3")

        assert runtime.context_token_for("user-1") is None
        assert runtime.context_token_for("user-2") == "ctx-2"
        assert runtime.context_token_for("user-3") == "ctx-3"
        assert state_store.load_state(_credentials()) == WeixinRuntimeState(
            cursor="",
            context_tokens=(("user-2", "ctx-2"), ("user-3", "ctx-3")),
        )

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

    async def test_poll_once_empty_success_still_returns_alive_result(self) -> None:
        client = _FakeClient(
            updates=[
                WeixinUpdateBatch(cursor="cursor-2", messages=[]),
            ]
        )
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
        )

        result = await runtime.poll_once()

        assert result == WeixinPollResult(
            cursor="cursor-2",
            message_count=0,
            delivered_text_count=0,
        )
        assert result.empty_success is True
        assert runtime.cursor == "cursor-2"

    async def test_poll_once_replays_spooled_backlog_after_restart(self, tmp_path: Path) -> None:
        state_store = WeixinRuntimeStateStore(tmp_path)
        spool = WeixinInboundSpool(tmp_path, _credentials())
        first_client = _FakeClient(
            updates=[
                WeixinUpdateBatch(cursor="cursor-1", messages=[_user_text_message(text="hello wx")]),
            ]
        )
        failing_seen: list[WeixinIncomingText] = []

        async def _fail_once(message: WeixinIncomingText) -> None:
            failing_seen.append(message)
            raise RuntimeError("handler crashed")

        failing_runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=first_client,
            on_text=_fail_once,
            state_store=state_store,
            inbound_spool=spool,
        )

        with pytest.raises(RuntimeError, match="handler crashed"):
            await failing_runtime.poll_once()

        assert spool.stats().pending_count == 1

        replay_seen: list[WeixinIncomingText] = []
        restored_runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=_FakeClient(updates=[WeixinUpdateBatch(cursor="cursor-2", messages=[])]),
            on_text=replay_seen.append,
            state_store=state_store,
            inbound_spool=WeixinInboundSpool(tmp_path, _credentials()),
        )

        result = await restored_runtime.poll_once()

        assert [item.text for item in replay_seen] == ["hello wx"]
        assert result.delivered_text_count == 1
        assert result.backlog_pending_count == 0

    async def test_poll_once_recovers_stale_claim_and_reports_it(self, tmp_path: Path) -> None:
        spool = WeixinInboundSpool(tmp_path, _credentials(), claim_ttl_seconds=1.0)
        spool.enqueue([_user_text_message(text="hello stale")])
        claim = spool.claim_next(owner="worker-a", now=10.0)
        assert claim is not None

        seen: list[WeixinIncomingText] = []
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=_FakeClient(updates=[WeixinUpdateBatch(cursor="cursor-2", messages=[])]),
            on_text=seen.append,
            inbound_spool=spool,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("controlmesh.messenger.weixin.inbound_spool.time.time", lambda: 12.0)
            mp.setattr("controlmesh.messenger.weixin.runtime.time.time", lambda: 12.0)
            result = await runtime.poll_once()

        assert result.recovered_stale_claim_count == 1
        assert [item.text for item in seen] == ["hello stale"]

    async def test_poll_once_reports_unhealthy_blocked_backlog(self, tmp_path: Path) -> None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("controlmesh.messenger.weixin.inbound_spool.time.time", lambda: 20.0)
            spool = WeixinInboundSpool(
                tmp_path,
                _credentials(),
                claim_ttl_seconds=60.0,
                unhealthy_backlog_age_seconds=5.0,
            )
            spool.enqueue([_user_text_message(text="a1"), _user_text_message(text="a2")])
            claim = spool.claim_next(owner="worker-a", now=20.0)
            assert claim is not None

            runtime = WeixinLongPollRuntime(
                credentials=_credentials(),
                client=_FakeClient(updates=[WeixinUpdateBatch(cursor="cursor-2", messages=[])]),
                on_text=lambda _message: None,
                inbound_spool=spool,
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("controlmesh.messenger.weixin.inbound_spool.time.time", lambda: 30.0)
            result = await runtime.poll_once()

        assert result.unhealthy_reason == "blocked_backlog"
        assert result.blocked_lane_count == 1

    async def test_send_text_uses_cached_context_token(self) -> None:
        client = _FakeClient(updates=[])
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
        )
        runtime.remember_context("user-1", "ctx-1")

        await runtime.send_text("user-1", "pong")

        assert client.send_text_calls == [
            (_credentials(), "user-1", "ctx-1", "pong", client.send_text_calls[0][4])
        ]

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
        assert client.send_text_calls == [
            (_credentials(), "user-1", "ctx-2", "pong", client.send_text_calls[0][4])
        ]

    async def test_poll_once_skips_persisted_outbound_self_echo_after_restart(self, tmp_path: Path) -> None:
        state_store = WeixinRuntimeStateStore(tmp_path)
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=_FakeClient(updates=[]),
            on_text=lambda _message: None,
            state_store=state_store,
        )
        await runtime.send_text("user-1", "pong", context_token="ctx-1")
        persisted = state_store.load_state(_credentials())
        client_ids = [client_id for client_id, _ in persisted.recent_outbound]
        assert client_ids

        seen: list[WeixinIncomingText] = []
        restored_client = _FakeClient(
            updates=[
                WeixinUpdateBatch(
                    cursor="cursor-echoed",
                    messages=[
                        {
                            "message_id": 202,
                            "from_user_id": "",
                            "to_user_id": "user-1",
                            "client_id": client_ids[0],
                            "message_type": 2,
                            "message_state": 2,
                            "context_token": "ctx-1",
                            "item_list": [{"type": 1, "text_item": {"text": "pong"}}],
                        },
                        _user_text_message(text="real user"),
                    ],
                )
            ]
        )
        restored_runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=restored_client,
            on_text=seen.append,
            state_store=state_store,
        )

        await restored_runtime.poll_once()

        assert [item.text for item in seen] == ["real user"]
        assert state_store.load_state(_credentials()).recent_outbound == ()

    async def test_send_text_requires_context_token(self) -> None:
        client = _FakeClient(updates=[])
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
        )

        with pytest.raises(WeixinContextTokenRequiredError, match="No cached context token for user user-1"):
            await runtime.send_text("user-1", "pong")

    async def test_session_expiry_marks_reauth_required_and_clears_context_tokens(self) -> None:
        expired: list[StoredWeixinCredentials] = []
        client = _FakeClient(
            updates=[],
            get_updates_error=WeixinIlinkApiError("expired", status=200, code=-14),
        )
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
            on_auth_expired=expired.append,
        )
        runtime.remember_context("user-1", "ctx-1")

        with pytest.raises(WeixinReauthRequiredError, match="Weixin iLink session expired"):
            await runtime.poll_once()

        assert runtime.auth_state == "reauth_required"
        assert runtime.context_token_for("user-1") is None
        assert expired == [_credentials()]

    async def test_send_text_expiry_marks_reauth_required_and_clears_persisted_state(
        self,
        tmp_path: Path,
    ) -> None:
        expired: list[StoredWeixinCredentials] = []
        state_store = WeixinRuntimeStateStore(tmp_path)
        client = _FakeClient(
            updates=[],
            send_text_error=WeixinIlinkApiError("expired", status=200, code=-14),
        )
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
            on_auth_expired=expired.append,
            state_store=state_store,
        )
        runtime.remember_context("user-1", "ctx-1")

        with pytest.raises(WeixinReauthRequiredError, match="Weixin iLink session expired"):
            await runtime.send_text("user-1", "pong")

        assert runtime.auth_state == "reauth_required"
        assert runtime.cursor == ""
        assert runtime.context_token_for("user-1") is None
        assert state_store.load_state(_credentials()) == WeixinRuntimeState()
        assert expired == [_credentials()]

    async def test_send_text_after_reauth_required_fails_explicitly(self) -> None:
        client = _FakeClient(updates=[])
        runtime = WeixinLongPollRuntime(
            credentials=_credentials(),
            client=client,
            on_text=lambda _message: None,
        )
        runtime.remember_context("user-1", "ctx-1")
        runtime.mark_reauth_required()

        with pytest.raises(WeixinReauthRequiredError, match="Weixin iLink session requires QR re-auth"):
            await runtime.send_text("user-1", "pong")
