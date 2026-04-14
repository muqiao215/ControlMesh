"""Tests for Weixin iLink credential storage and QR helper seams."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ductor_bot.messenger.weixin.auth_store import (
    StoredWeixinCredentials,
    WeixinCredentialStore,
    credentials_from_confirmed_qr_status,
)


class TestWeixinCredentialStore:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        store = WeixinCredentialStore(tmp_path)
        credentials = StoredWeixinCredentials(
            token="bot-token",
            base_url="https://ilinkai.weixin.qq.com",
            account_id="bot-account",
            user_id="wx-user",
        )

        store.save_credentials(credentials)

        assert store.load_credentials() == credentials
        mode = oct(store.path.stat().st_mode & 0o777)
        assert mode == "0o600"

    def test_load_accepts_legacy_camel_case_fields(self, tmp_path: Path) -> None:
        store = WeixinCredentialStore(tmp_path)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            json.dumps(
                {
                    "token": "bot-token",
                    "baseUrl": "https://ilinkai.weixin.qq.com",
                    "accountId": "bot-account",
                    "userId": "wx-user",
                }
            ),
            encoding="utf-8",
        )

        assert store.load_credentials() == StoredWeixinCredentials(
            token="bot-token",
            base_url="https://ilinkai.weixin.qq.com",
            account_id="bot-account",
            user_id="wx-user",
        )

    def test_clear_removes_credentials_file(self, tmp_path: Path) -> None:
        store = WeixinCredentialStore(tmp_path)
        store.save_credentials(
            StoredWeixinCredentials(
                token="bot-token",
                base_url="https://ilinkai.weixin.qq.com",
                account_id="bot-account",
                user_id="wx-user",
            )
        )

        store.clear()

        assert store.load_credentials() is None
        assert store.path.exists() is False


def test_credentials_from_confirmed_qr_status() -> None:
    credentials = credentials_from_confirmed_qr_status(
        {
            "status": "confirmed",
            "bot_token": "bot-token",
            "ilink_bot_id": "bot-account",
            "ilink_user_id": "wx-user",
            "baseurl": "https://mirror.example.com",
        }
    )

    assert credentials == StoredWeixinCredentials(
        token="bot-token",
        base_url="https://mirror.example.com",
        account_id="bot-account",
        user_id="wx-user",
    )


def test_credentials_from_confirmed_qr_status_requires_fields() -> None:
    with pytest.raises(TypeError, match="did not return bot credentials"):
        credentials_from_confirmed_qr_status({"status": "confirmed", "bot_token": "bot-token"})
