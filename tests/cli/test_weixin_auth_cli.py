"""Red contracts for the Weixin QR auth CLI slice."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.weixin.auth_state import WeixinAuthStateStore
from controlmesh.messenger.weixin.auth_store import (
    StoredWeixinCredentials,
    WeixinCredentialStore,
    WeixinQrLoginState,
    WeixinQrLoginStateStore,
)
from controlmesh.messenger.weixin.runtime_state import WeixinRuntimeState, WeixinRuntimeStateStore


def _import_auth_cli_module() -> ModuleType:
    try:
        return importlib.import_module("controlmesh.cli_commands.auth")
    except ModuleNotFoundError as exc:  # pragma: no cover - red-path contract
        msg = "missing CLI auth command module: controlmesh.cli_commands.auth"
        raise AssertionError(msg) from exc


def _weixin_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        controlmesh_home=str(tmp_path),
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
        controlmesh_home=str(tmp_path),
        transport="weixin",
        transports=["weixin"],
        weixin={
            "mode": "ilink",
            "enabled": False,
            "credentials_path": "weixin_store/credentials.json",
        },
    )


def _write_fake_qr_artifact(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"png-bytes")


def test_main_routes_weixin_auth_login_to_auth_command(monkeypatch: pytest.MonkeyPatch) -> None:
    import controlmesh.__main__ as main_mod

    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(sys, "argv", ["controlmesh", "weixin", "auth", "login"])
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

    async def _fake_save_qr_artifact(_qr_url: str, store: WeixinQrLoginStateStore) -> None:
        _write_fake_qr_artifact(store.qr_image_path)

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)
    monkeypatch.setattr(module, "_save_qr_artifact", _fake_save_qr_artifact, raising=False)
    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep, raising=False)

    module.cmd_auth(["weixin", "auth", "login"])

    store = WeixinCredentialStore(
        config.controlmesh_home,
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
    assert "qr_waiting_scan" in rendered
    assert "qr_scanned_waiting_confirm" in rendered
    assert "qr_confirmed_persisting" in rendered
    assert (tmp_path / "weixin_store" / "current_qr.png").read_bytes() == b"png-bytes"
    assert WeixinQrLoginStateStore(config.controlmesh_home).path.exists() is False


def test_cmd_auth_weixin_login_retries_after_poll_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    poll_attempts: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    async def _fake_fetch_qr_code(base_url: str) -> dict[str, str]:
        assert base_url == config.weixin.base_url
        return {
            "qrcode": "qr-token",
            "qrcode_img_content": "https://login.example.com/qr",
        }

    async def _fake_poll_qr_status(base_url: str, qrcode: str) -> dict[str, object]:
        assert base_url == config.weixin.base_url
        assert qrcode == "qr-token"
        poll_attempts.append(qrcode)
        if len(poll_attempts) == 1:
            raise TimeoutError("long poll timeout")
        return {
            "status": "confirmed",
            "bot_token": "bot-token",
            "ilink_bot_id": "bot-account",
            "ilink_user_id": "wx-user",
        }

    async def _fake_sleep(_seconds: float) -> None:
        return None

    async def _fake_save_qr_artifact(_qr_url: str, store: WeixinQrLoginStateStore) -> None:
        _write_fake_qr_artifact(store.qr_image_path)

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)
    monkeypatch.setattr(module, "_save_qr_artifact", _fake_save_qr_artifact, raising=False)
    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep, raising=False)

    module.cmd_auth(["weixin", "auth", "login"])

    rendered = "\n".join(console_lines)
    assert "poll timeout" in rendered
    assert "logged_in" in rendered
    assert len(poll_attempts) == 2


def test_cmd_auth_weixin_login_regenerates_after_expired_qr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    created_qrs: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    responses = {
        "stale-qr": [{"status": "expired"}],
        "fresh-qr": [
            {"status": "scaned"},
            {
                "status": "confirmed",
                "bot_token": "bot-token",
                "ilink_bot_id": "bot-account",
                "ilink_user_id": "wx-user",
            },
        ],
    }

    async def _fake_fetch_qr_code(base_url: str) -> dict[str, str]:
        assert base_url == config.weixin.base_url
        created_qrs.append("fresh-qr")
        return {
            "qrcode": "fresh-qr",
            "qrcode_img_content": "https://login.example.com/fresh-qr",
        }

    async def _fake_poll_qr_status(base_url: str, qrcode: str) -> dict[str, object]:
        assert base_url == config.weixin.base_url
        return responses[qrcode].pop(0)

    async def _fake_sleep(_seconds: float) -> None:
        return None

    async def _fake_save_qr_artifact(_qr_url: str, store: WeixinQrLoginStateStore) -> None:
        _write_fake_qr_artifact(store.qr_image_path)

    WeixinQrLoginStateStore(config.controlmesh_home).save(
        WeixinQrLoginState(
            auth_state="qr_waiting_scan",
            qrcode_id="stale-qr",
            qrcode_url="https://login.example.com/stale-qr",
            qrcode_created_at=1710000000000,
            last_status="waiting",
            last_polled_at=1710000001000,
            updated_at=1710000001000,
        )
    )

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)
    monkeypatch.setattr(module, "_save_qr_artifact", _fake_save_qr_artifact, raising=False)
    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep, raising=False)

    module.cmd_auth(["weixin", "auth", "login"])

    rendered = "\n".join(console_lines)
    assert "stale-qr" in rendered
    assert "expired" in rendered
    assert created_qrs == ["fresh-qr"]


def test_cmd_auth_weixin_login_resumes_existing_qr_after_interrupted_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    first_console_lines: list[str] = []
    second_console_lines: list[str] = []
    fetch_calls: list[str] = []
    interrupted = {"done": False}

    class _FakeConsole:
        def __init__(self, sink: list[str]) -> None:
            self._sink = sink

        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            self._sink.append(" ".join(str(arg) for arg in args))

    async def _fake_fetch_qr_code(base_url: str) -> dict[str, str]:
        assert base_url == config.weixin.base_url
        fetch_calls.append("fetch")
        return {
            "qrcode": "qr-token",
            "qrcode_img_content": "https://login.example.com/qr",
        }

    async def _fake_poll_qr_status(base_url: str, qrcode: str) -> dict[str, object]:
        assert base_url == config.weixin.base_url
        assert qrcode == "qr-token"
        if not interrupted["done"]:
            interrupted["done"] = True
            raise KeyboardInterrupt
        return {
            "status": "confirmed",
            "bot_token": "bot-token",
            "ilink_bot_id": "bot-account",
            "ilink_user_id": "wx-user",
        }

    async def _fake_sleep(_seconds: float) -> None:
        return None

    async def _fake_save_qr_artifact(_qr_url: str, store: WeixinQrLoginStateStore) -> None:
        _write_fake_qr_artifact(store.qr_image_path)

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)
    monkeypatch.setattr(module, "_save_qr_artifact", _fake_save_qr_artifact, raising=False)
    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep, raising=False)

    monkeypatch.setattr(module, "_console", _FakeConsole(first_console_lines), raising=False)
    with pytest.raises(KeyboardInterrupt):
        module.cmd_auth(["weixin", "auth", "login"])

    monkeypatch.setattr(module, "_console", _FakeConsole(second_console_lines), raising=False)
    module.cmd_auth(["weixin", "auth", "login"])

    assert fetch_calls == ["fetch"]
    assert "qr-token" in "\n".join(second_console_lines)


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

    runtime_store = WeixinRuntimeStateStore(config.controlmesh_home)
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
    monkeypatch.setattr(
        module,
        "_save_qr_artifact",
        lambda _qr_url, _store: asyncio.sleep(0),
        raising=False,
    )

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
        config.controlmesh_home,
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
    assert "请向该微信机器人发送任意消息以建立 context_token" in rendered


def test_cmd_auth_weixin_status_reports_reauth_required_as_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    WeixinAuthStateStore(config.controlmesh_home).mark_reauth_required()

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


def test_cmd_auth_weixin_status_reports_pending_qr_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    WeixinQrLoginStateStore(config.controlmesh_home).save(
        WeixinQrLoginState(
            auth_state="qr_scanned_waiting_confirm",
            qrcode_id="qr-token",
            qrcode_url="https://login.example.com/qr",
            qrcode_created_at=1710000000000,
            last_status="scaned",
            last_polled_at=1710000005000,
            updated_at=1710000005000,
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
    assert "qr_scanned_waiting_confirm" in rendered
    assert "runtime state: unavailable" in rendered
    assert "qr-token" in rendered


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
        config.controlmesh_home,
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
        config.controlmesh_home,
        relative_path=config.weixin.credentials_path,
    ).save_credentials(credentials)
    WeixinRuntimeStateStore(config.controlmesh_home).save_state(
        credentials,
        WeixinRuntimeState(cursor="cursor-2", context_tokens=(("user-1", "ctx-1"),)),
    )
    WeixinAuthStateStore(config.controlmesh_home).mark_reauth_required()
    WeixinQrLoginStateStore(config.controlmesh_home).save(
        WeixinQrLoginState(
            auth_state="qr_waiting_scan",
            qrcode_id="qr-token",
            qrcode_url="https://login.example.com/qr",
            qrcode_created_at=1710000000000,
            updated_at=1710000000000,
        )
    )

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)

    module.cmd_auth(["weixin", "auth", "logout"])

    assert WeixinCredentialStore(
        config.controlmesh_home,
        relative_path=config.weixin.credentials_path,
    ).load_credentials() is None
    assert WeixinRuntimeStateStore(config.controlmesh_home).path.exists() is False
    assert WeixinAuthStateStore(config.controlmesh_home).load_state() is None
    assert WeixinQrLoginStateStore(config.controlmesh_home).path.exists() is False
    rendered = "\n".join(console_lines)
    assert "logged_out" in rendered


def test_cmd_auth_weixin_reauth_reuses_login_entry_when_reauth_required(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    called: list[str] = []
    WeixinAuthStateStore(config.controlmesh_home).mark_reauth_required()

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
