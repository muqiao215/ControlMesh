"""Tests for Weixin runtime continuity state persistence."""

from __future__ import annotations

from pathlib import Path

from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials
from controlmesh.messenger.weixin.runtime_state import (
    WeixinRuntimeState,
    WeixinRuntimeStateStore,
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
        )

        store.save_state(_credentials(), state)

        assert store.load_state(_credentials()) == state
        mode = oct(store.path.stat().st_mode & 0o777)
        assert mode == "0o600"

    def test_load_state_clears_mismatched_account_identity(self, tmp_path: Path) -> None:
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

