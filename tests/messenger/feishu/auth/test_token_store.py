"""Tests for Feishu auth token persistence."""

from __future__ import annotations

from pathlib import Path

from controlmesh.messenger.feishu.auth.token_store import (
    FeishuTokenStore,
    StoredFeishuToken,
    token_status,
)


def _make_token(**overrides: object) -> StoredFeishuToken:
    data: dict[str, object] = {
        "user_open_id": "ou_user",
        "app_id": "cli_app",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": 2_000_000,
        "refresh_expires_at": 4_000_000,
        "scope": "offline_access docs:read",
        "granted_at": 1_000_000,
    }
    data.update(overrides)
    return StoredFeishuToken(**data)


def test_store_round_trip_uses_controlmesh_home(tmp_path: Path) -> None:
    store = FeishuTokenStore(tmp_path)
    token = _make_token()

    store.save_token(token)

    assert store.path == tmp_path / "feishu_store" / "auth" / "tokens.json"
    assert store.path.exists()
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.load_token("cli_app", "ou_user") == token


def test_remove_token_deletes_entry(tmp_path: Path) -> None:
    store = FeishuTokenStore(tmp_path)
    token = _make_token()
    store.save_token(token)

    store.remove_token(token.app_id, token.user_open_id)

    assert store.load_token(token.app_id, token.user_open_id) is None


def test_token_status_tracks_refresh_window() -> None:
    valid = _make_token(expires_at=2_000_000)
    needs_refresh = _make_token(expires_at=1_200_000)
    expired = _make_token(expires_at=900_000)

    assert token_status(valid, now_ms=1_000_000) == "valid"
    assert token_status(needs_refresh, now_ms=1_000_000) == "needs_refresh"
    assert token_status(expired, now_ms=1_000_000) == "expired"
