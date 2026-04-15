"""Tests for Matrix credential handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from controlmesh.messenger.matrix.credentials import _save_credentials, login_or_restore

# ---------------------------------------------------------------------------
# _save_credentials
# ---------------------------------------------------------------------------


class TestSaveCredentials:
    def test_creates_file_with_correct_permissions(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "creds.json"
        _save_credentials(creds_path, "@bot:test", "DEV1", "tok123")

        assert creds_path.exists()
        mode = oct(creds_path.stat().st_mode & 0o777)
        assert mode == "0o600"

        data = json.loads(creds_path.read_text())
        assert data["user_id"] == "@bot:test"
        assert data["device_id"] == "DEV1"
        assert data["access_token"] == "tok123"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "sub" / "dir" / "creds.json"
        _save_credentials(creds_path, "@bot:test", "DEV1", "tok123")
        assert creds_path.exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        creds_path = tmp_path / "creds.json"
        _save_credentials(creds_path, "@old:test", "OLD", "old-tok")
        _save_credentials(creds_path, "@new:test", "NEW", "new-tok")

        data = json.loads(creds_path.read_text())
        assert data["user_id"] == "@new:test"


# ---------------------------------------------------------------------------
# login_or_restore
# ---------------------------------------------------------------------------


class TestLoginOrRestore:
    async def test_restores_from_saved_credentials(self, tmp_path: Path) -> None:
        creds = {"user_id": "@bot:test", "device_id": "DEV1", "access_token": "saved-tok"}
        (tmp_path / "credentials.json").write_text(json.dumps(creds))

        client = MagicMock()
        config = MagicMock()
        config.access_token = ""
        config.device_id = ""
        config.password = ""

        await login_or_restore(client, config, tmp_path)

        client.restore_login.assert_called_once_with(
            user_id="@bot:test",
            device_id="DEV1",
            access_token="saved-tok",
        )

    async def test_falls_back_to_config_token(self, tmp_path: Path) -> None:
        client = MagicMock()
        config = MagicMock()
        config.user_id = "@bot:test"
        config.access_token = "config-tok"
        config.device_id = "CFG-DEV"
        config.password = ""

        await login_or_restore(client, config, tmp_path)

        client.restore_login.assert_called_once_with(
            user_id="@bot:test",
            device_id="CFG-DEV",
            access_token="config-tok",
        )
        # Verify credentials were saved
        saved = json.loads((tmp_path / "credentials.json").read_text())
        assert saved["access_token"] == "config-tok"

    async def test_password_login_saves_credentials(self, tmp_path: Path) -> None:
        client = AsyncMock()
        resp = MagicMock()
        resp.access_token = "new-tok"
        resp.user_id = "@bot:test"
        resp.device_id = "NEW-DEV"
        client.login.return_value = resp

        config = MagicMock()
        config.access_token = ""
        config.device_id = ""
        config.password = "secret"

        await login_or_restore(client, config, tmp_path)

        client.login.assert_awaited_once_with("secret", device_name="controlmesh")
        saved = json.loads((tmp_path / "credentials.json").read_text())
        assert saved["access_token"] == "new-tok"
        assert saved["device_id"] == "NEW-DEV"

    async def test_password_login_failure_raises(self, tmp_path: Path) -> None:
        client = AsyncMock()
        resp = MagicMock(spec=[])  # No access_token attribute
        client.login.return_value = resp

        config = MagicMock()
        config.access_token = ""
        config.device_id = ""
        config.password = "bad-password"

        with pytest.raises(RuntimeError, match="Matrix AUTH FAILED"):
            await login_or_restore(client, config, tmp_path)

    async def test_no_credentials_no_password_raises(self, tmp_path: Path) -> None:
        client = MagicMock()
        config = MagicMock()
        config.access_token = ""
        config.device_id = ""
        config.password = ""

        with pytest.raises(RuntimeError, match="Matrix AUTH FAILED"):
            await login_or_restore(client, config, tmp_path)

    async def test_corrupt_saved_credentials_falls_through(self, tmp_path: Path) -> None:
        (tmp_path / "credentials.json").write_text("not valid json")

        client = AsyncMock()
        resp = MagicMock()
        resp.access_token = "fresh-tok"
        resp.user_id = "@bot:test"
        resp.device_id = "DEV2"
        client.login.return_value = resp

        config = MagicMock()
        config.access_token = ""
        config.device_id = ""
        config.password = "secret"

        await login_or_restore(client, config, tmp_path)

        # Should have fallen through to password login
        client.login.assert_awaited_once()
