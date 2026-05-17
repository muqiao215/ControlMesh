"""Tests for Weixin runtime continuity state persistence."""

from __future__ import annotations

from pathlib import Path

from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials
from controlmesh.messenger.weixin.runtime_state import (
    WeixinOutboundEchoStore,
    WeixinRuntimeState,
    WeixinRuntimeStateStore,
    weixin_runtime_identity_fingerprint,
)


def _credentials(*, account_id: str = "bot-account", user_id: str = "wx-user") -> StoredWeixinCredentials:
    return StoredWeixinCredentials(
        token="bot-token",
        base_url="https://ilinkai.weixin.qq.com",
        account_id=account_id,
        user_id=user_id,
    )


class TestWeixinRuntimeStateStore:
    def test_save_and_load_round_trip_with_file_protection(self, tmp_path: Path) -> None:
        store = WeixinRuntimeStateStore(tmp_path)
        state = WeixinRuntimeState(
            cursor="cursor-2",
            context_tokens=(("user-1", "ctx-1"), ("user-2", "ctx-2")),
            recent_outbound=(("client-1", 1710000000.0),),
        )

        store.save_state(_credentials(), state)

        assert store.load_state(_credentials()) == state
        mode = oct(store.path.stat().st_mode & 0o777)
        assert mode == "0o600"

    def test_load_state_clears_mismatched_identity_fingerprint(self, tmp_path: Path) -> None:
        store = WeixinRuntimeStateStore(tmp_path)
        store.save_state(
            _credentials(account_id="bot-a", user_id="wx-a"),
            WeixinRuntimeState(
                cursor="cursor-2",
                context_tokens=(("user-1", "ctx-1"),),
            ),
        )

        assert store.load_state(_credentials(account_id="bot-b", user_id="wx-b")) == WeixinRuntimeState()
        assert store.path.exists() is False

    def test_runtime_identity_fingerprint_changes_with_token(self) -> None:
        first = weixin_runtime_identity_fingerprint(_credentials())
        second = weixin_runtime_identity_fingerprint(
            StoredWeixinCredentials(
                token="other-token",
                base_url="https://ilinkai.weixin.qq.com",
                account_id="bot-account",
                user_id="wx-user",
            )
        )
        assert first != second


class TestWeixinOutboundEchoStore:
    def test_consumes_known_client_id_once(self) -> None:
        store = WeixinOutboundEchoStore((("client-1", 100.0),), ttl_seconds=60.0)
        assert store.consume("client-1", now=120.0) is True
        assert store.consume("client-1", now=121.0) is False

    def test_drops_expired_client_id(self) -> None:
        store = WeixinOutboundEchoStore((("client-1", 100.0),), ttl_seconds=10.0)
        assert store.consume("client-1", now=111.0) is False
