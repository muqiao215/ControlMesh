"""Red contracts for the Weixin QR auth CLI slice."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ductor_bot.config import AgentConfig
from ductor_bot.messenger.weixin.auth_state import WeixinAuthStateStore
from ductor_bot.messenger.weixin.auth_store import StoredWeixinCredentials, WeixinCredentialStore
from ductor_bot.messenger.weixin.runtime_state import WeixinRuntimeState, WeixinRuntimeStateStore


def _import_auth_cli_module() -> ModuleType:
    try:
        return importlib.import_module("ductor_bot.cli_commands.auth")
    except ModuleNotFoundError as exc:  # pragma: no cover - red-path contract
        msg = "missing CLI auth command module: ductor_bot.cli_commands.auth"
        raise AssertionError(msg) from exc


def _weixin_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        ductor_home=str(tmp_path),
        transport="weixin",
        transports=["weixin"],
        weixin={
            "mode": "ilink",
            "enabled": True,
            "credentials_path": "weixin_store/credentials.json",
        },
    )


def _disabled_weixin_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        ductor_home=str(tmp_path),
        transport="weixin",
        transports=["weixin"],
        weixin={
            "mode": "ilink",
            "enabled": False,
            "credentials_path": "weixin_store/credentials.json",
        },
    )


def test_main_routes_weixin_auth_login_to_auth_command(monkeypatch: pytest.MonkeyPatch) -> None:
    import ductor_bot.__main__ as main_mod

    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(sys, "argv", ["ductor", "weixin", "auth", "login"])
    monkeypatch.setattr(
        main_mod,
        "_cmd_auth",
        lambda args: calls.append(("auth", list(args))),
        raising=False,
    )
    monkeypatch.setattr(
        main_mod,
        "_default_action",
        lambda verbose: calls.append(("default", verbose)),
    )

    main_mod.main()

    assert calls == [("auth", ["weixin", "auth", "login"])]


def test_cmd_auth_weixin_login_fetches_qr_and_persists_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    polls = [
        {"status": "scaned"},
        {
            "status": "confirmed",
            "bot_token": "bot-token",
            "ilink_bot_id": "bot-account",
            "ilink_user_id": "wx-user",
            "baseurl": "https://mirror.example.com",
        },
    ]

    async def _fake_fetch_qr_code(base_url: str) -> dict[str, str]:
        assert base_url == config.weixin.base_url
        return {
            "qrcode": "qr-token",
            "qrcode_img_content": "https://login.example.com/qr",
        }

    async def _fake_poll_qr_status(base_url: str, qrcode: str) -> dict[str, object]:
        assert base_url == config.weixin.base_url
        assert qrcode == "qr-token"
        return polls.pop(0)

    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)
    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep, raising=False)

    module.cmd_auth(["weixin", "auth", "login"])

    store = WeixinCredentialStore(
        config.ductor_home,
        relative_path=config.weixin.credentials_path,
    )
    assert store.load_credentials() == StoredWeixinCredentials(
        token="bot-token",
        base_url="https://mirror.example.com",
        account_id="bot-account",
        user_id="wx-user",
    )
    rendered = "\n".join(console_lines)
    assert "https://login.example.com/qr" in rendered
    assert "bot-account" in rendered
    assert "wx-user" in rendered


def test_cmd_auth_weixin_login_clears_stale_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)

    async def _fake_fetch_qr_code(_base_url: str) -> dict[str, str]:
        return {
            "qrcode": "qr-token",
            "qrcode_img_content": "https://login.example.com/qr",
        }

    async def _fake_poll_qr_status(_base_url: str, _qrcode: str) -> dict[str, object]:
        return {
            "status": "confirmed",
            "bot_token": "bot-token",
            "ilink_bot_id": "bot-account",
            "ilink_user_id": "wx-user",
            "baseurl": "https://mirror.example.com",
        }

    runtime_store = WeixinRuntimeStateStore(config.ductor_home)
    runtime_store.save_state(
        StoredWeixinCredentials(
            token="old-token",
            base_url="https://ilinkai.weixin.qq.com",
            account_id="bot-account",
            user_id="wx-user",
        ),
        WeixinRuntimeState(cursor="cursor-stale", context_tokens=(("user-1", "ctx-stale"),)),
    )

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)

    module.cmd_auth(["weixin", "auth", "login"])

    assert runtime_store.load_state(
        StoredWeixinCredentials(
            token="bot-token",
            base_url="https://mirror.example.com",
            account_id="bot-account",
            user_id="wx-user",
        )
    ) == WeixinRuntimeState()


def test_cmd_auth_weixin_status_reports_logged_in_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    WeixinCredentialStore(
        config.ductor_home,
        relative_path=config.weixin.credentials_path,
    ).save_credentials(
        StoredWeixinCredentials(
            token="bot-token",
            base_url="https://ilinkai.weixin.qq.com",
            account_id="bot-account",
            user_id="wx-user",
        )
    )

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)

    module.cmd_auth(["weixin", "auth", "status"])

    rendered = "\n".join(console_lines)
    assert "configured: true" in rendered
    assert "logged_in" in rendered
    assert "context_token_unavailable" in rendered
    assert "bot-account" in rendered
    assert "wx-user" in rendered


def test_cmd_auth_weixin_status_reports_reauth_required_as_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    WeixinAuthStateStore(config.ductor_home).mark_reauth_required()

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)

    module.cmd_auth(["weixin", "auth", "status"])

    rendered = "\n".join(console_lines)
    assert "configured: true" in rendered
    assert "reauth_required" in rendered
    assert "runtime state: degraded" in rendered


def test_cmd_auth_weixin_status_reports_logged_out_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)

    module.cmd_auth(["weixin", "auth", "status"])

    rendered = "\n".join(console_lines)
    assert "configured: true" in rendered
    assert "logged_out" in rendered


def test_cmd_auth_weixin_status_treats_corrupt_credentials_as_logged_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    store = WeixinCredentialStore(
        config.ductor_home,
        relative_path=config.weixin.credentials_path,
    )
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"token":"x","account_id":1}', encoding="utf-8")

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)

    module.cmd_auth(["weixin", "auth", "status"])

    rendered = "\n".join(console_lines)
    assert "logged_out" in rendered


def test_cmd_auth_weixin_logout_clears_credentials_runtime_state_and_reauth_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    credentials = StoredWeixinCredentials(
        token="bot-token",
        base_url="https://ilinkai.weixin.qq.com",
        account_id="bot-account",
        user_id="wx-user",
    )
    WeixinCredentialStore(
        config.ductor_home,
        relative_path=config.weixin.credentials_path,
    ).save_credentials(credentials)
    WeixinRuntimeStateStore(config.ductor_home).save_state(
        credentials,
        WeixinRuntimeState(cursor="cursor-2", context_tokens=(("user-1", "ctx-1"),)),
    )
    WeixinAuthStateStore(config.ductor_home).mark_reauth_required()

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)

    module.cmd_auth(["weixin", "auth", "logout"])

    assert WeixinCredentialStore(
        config.ductor_home,
        relative_path=config.weixin.credentials_path,
    ).load_credentials() is None
    assert WeixinRuntimeStateStore(config.ductor_home).path.exists() is False
    assert WeixinAuthStateStore(config.ductor_home).load_state() is None
    rendered = "\n".join(console_lines)
    assert "logged_out" in rendered


def test_cmd_auth_weixin_reauth_reuses_login_entry_when_reauth_required(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    called: list[str] = []
    WeixinAuthStateStore(config.ductor_home).mark_reauth_required()

    async def _fake_weixin_login() -> None:
        called.append("login")

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "_cmd_weixin_login", _fake_weixin_login, raising=False)

    module.cmd_auth(["weixin", "auth", "reauth"])

    assert called == ["login"]


def test_cmd_auth_weixin_reauth_stays_bounded_when_transport_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _disabled_weixin_config(tmp_path)
    called: list[str] = []

    async def _fake_weixin_login() -> None:
        called.append("login")

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "_cmd_weixin_login", _fake_weixin_login, raising=False)

    with pytest.raises(SystemExit, match="1"):
        module.cmd_auth(["weixin", "auth", "reauth"])

    assert called == []
