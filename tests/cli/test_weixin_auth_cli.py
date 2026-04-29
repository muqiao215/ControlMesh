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


def _weixin_config_without_transport(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        controlmesh_home=str(tmp_path),
        transport="feishu",
        transports=["feishu", "telegram"],
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


def test_cmd_auth_weixin_setup_renders_preflight_before_login(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    called: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    async def _fake_weixin_login() -> None:
        called.append("login")

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "_cmd_weixin_login", _fake_weixin_login, raising=False)

    module.cmd_auth(["weixin", "auth", "setup"])

    rendered = "\n".join(console_lines)
    assert "Weixin setup" in rendered
    assert "transport state: configured" in rendered
    assert called == ["login"]


def test_cmd_auth_weixin_login_fetches_qr_and_starts_detached_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    spawned_commands: list[list[str]] = []

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

    async def _fake_save_qr_artifact(_qr_url: str, store: WeixinQrLoginStateStore) -> None:
        _write_fake_qr_artifact(store.qr_image_path)

    class _FakeProcess:
        pid = 4242

    def _fake_popen(command: list[str], **_kwargs: object) -> _FakeProcess:
        spawned_commands.append(command)
        return _FakeProcess()

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(module, "_save_qr_artifact", _fake_save_qr_artifact, raising=False)
    monkeypatch.setattr(module, "_weixin_completion_worker_is_active", lambda _config: False)
    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen, raising=False)

    module.cmd_auth(["weixin", "auth", "login"])

    qr_state = WeixinQrLoginStateStore(config.controlmesh_home).load()
    assert qr_state == WeixinQrLoginState(
        auth_state="qr_waiting_scan",
        qrcode_id="qr-token",
        qrcode_url="https://login.example.com/qr",
        qrcode_created_at=qr_state.qrcode_created_at,
        last_status="created",
        last_polled_at=None,
        updated_at=qr_state.updated_at,
    )
    assert qr_state.qrcode_created_at is not None
    assert qr_state.updated_at is not None
    assert spawned_commands == [
        [
            sys.executable,
            "-m",
            "controlmesh",
            "auth",
            "weixin",
            "login-complete",
            "--qrcode-id",
            "qr-token",
        ]
    ]
    assert (
        WeixinCredentialStore(
            config.controlmesh_home,
            relative_path=config.weixin.credentials_path,
        ).load_credentials()
        is None
    )
    rendered = "\n".join(console_lines)
    assert "https://login.example.com/qr" in rendered
    assert "qr_waiting_scan" in rendered
    assert "Weixin QR completion worker started in the background." in rendered
    assert "This command can exit now" in rendered
    assert (tmp_path / "weixin_store" / "current_qr.png").read_bytes() == b"png-bytes"
    assert (tmp_path / "restart-requested").exists() is False


def test_cmd_auth_weixin_login_complete_retries_after_poll_timeout(
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

    WeixinQrLoginStateStore(config.controlmesh_home).save(
        WeixinQrLoginState(
            auth_state="qr_waiting_scan",
            qrcode_id="qr-token",
            qrcode_url="https://login.example.com/qr",
            qrcode_created_at=1710000000000,
            last_status="created",
            updated_at=1710000000000,
        )
    )

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)
    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep, raising=False)

    asyncio.run(module._cmd_weixin_login_complete("qr-token"))

    rendered = "\n".join(console_lines)
    assert "poll timeout" in rendered
    assert "logged_in" in rendered
    assert len(poll_attempts) == 2
    assert (tmp_path / "restart-requested").read_text(encoding="utf-8") == "1"
    assert (
        WeixinCredentialStore(
            config.controlmesh_home,
            relative_path=config.weixin.credentials_path,
        ).load_credentials()
        == StoredWeixinCredentials(
            token="bot-token",
            base_url="https://ilinkai.weixin.qq.com",
            account_id="bot-account",
            user_id="wx-user",
        )
    )
    assert WeixinQrLoginStateStore(config.controlmesh_home).path.exists() is False


def test_cmd_auth_weixin_login_complete_expiry_clears_stale_qr_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    qr_store = WeixinQrLoginStateStore(config.controlmesh_home)
    qr_store.save(
        WeixinQrLoginState(
            auth_state="qr_waiting_scan",
            qrcode_id="qr-token",
            qrcode_url="https://login.example.com/qr",
            qrcode_created_at=1710000000000,
            last_status="created",
            updated_at=1710000000000,
        )
    )
    _write_fake_qr_artifact(qr_store.qr_image_path)

    async def _fake_poll_qr_status(_base_url: str, _qrcode: str) -> dict[str, object]:
        return {"status": "expired"}

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)

    asyncio.run(module._cmd_weixin_login_complete("qr-token"))

    assert qr_store.path.exists() is False
    assert qr_store.qr_image_path.exists() is False
    rendered = "\n".join(console_lines)
    assert "Weixin QR status: expired" in rendered


def test_cmd_auth_weixin_login_resumes_existing_qr_and_starts_worker_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    fetch_calls: list[str] = []
    spawned: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    async def _fake_fetch_qr_code(base_url: str) -> dict[str, str]:
        assert base_url == config.weixin.base_url
        fetch_calls.append("fetch")
        return {"qrcode": "fresh-qr", "qrcode_img_content": "https://login.example.com/fresh-qr"}

    WeixinQrLoginStateStore(config.controlmesh_home).save(
        WeixinQrLoginState(
            auth_state="qr_waiting_scan",
            qrcode_id="existing-qr",
            qrcode_url="https://login.example.com/existing-qr",
            qrcode_created_at=1710000000000,
            last_status="created",
            updated_at=1710000001000,
        )
    )
    _write_fake_qr_artifact(WeixinQrLoginStateStore(config.controlmesh_home).qr_image_path)

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(
        module,
        "_spawn_weixin_completion_worker",
        lambda *, qrcode_id, **_kwargs: spawned.append(qrcode_id),
    )
    monkeypatch.setattr(module, "_weixin_completion_worker_is_active", lambda _config: False)

    module.cmd_auth(["weixin", "auth", "login"])

    rendered = "\n".join(console_lines)
    assert "existing-qr" in rendered
    assert fetch_calls == []
    assert spawned == ["existing-qr"]
    assert "background." in rendered


def test_cmd_auth_weixin_login_does_not_spawn_duplicate_worker_for_pending_qr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)
    console_lines: list[str] = []
    fetch_calls: list[str] = []
    spawned: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    async def _fake_fetch_qr_code(base_url: str) -> dict[str, str]:
        assert base_url == config.weixin.base_url
        fetch_calls.append("fetch")
        return {
            "qrcode": "qr-token",
            "qrcode_img_content": "https://login.example.com/qr",
        }

    WeixinQrLoginStateStore(config.controlmesh_home).save(
        WeixinQrLoginState(
            auth_state="qr_waiting_scan",
            qrcode_id="qr-token",
            qrcode_url="https://login.example.com/qr",
            qrcode_created_at=1710000000000,
            last_status="created",
            updated_at=1710000001000,
        )
    )
    _write_fake_qr_artifact(WeixinQrLoginStateStore(config.controlmesh_home).qr_image_path)

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)
    monkeypatch.setattr(
        module,
        "_spawn_weixin_completion_worker",
        lambda *, qrcode_id, **_kwargs: spawned.append(qrcode_id),
    )
    monkeypatch.setattr(module, "_weixin_completion_worker_is_active", lambda _config: True)
    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    module.cmd_auth(["weixin", "auth", "login"])

    assert fetch_calls == []
    assert spawned == []
    assert "already active" in "\n".join(console_lines)


def test_cmd_auth_weixin_login_complete_clears_stale_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config(tmp_path)

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
    WeixinQrLoginStateStore(config.controlmesh_home).save(
        WeixinQrLoginState(
            auth_state="qr_waiting_scan",
            qrcode_id="qr-token",
            qrcode_url="https://login.example.com/qr",
            qrcode_created_at=1710000000000,
            last_status="created",
            updated_at=1710000001000,
        )
    )

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "poll_qr_status", _fake_poll_qr_status, raising=False)

    asyncio.run(module._cmd_weixin_login_complete("qr-token"))

    assert runtime_store.load_state(
        StoredWeixinCredentials(
            token="bot-token",
            base_url="https://mirror.example.com",
            account_id="bot-account",
            user_id="wx-user",
        )
    ) == WeixinRuntimeState()


def test_try_save_qr_artifact_falls_back_when_local_qr_image_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    console_lines: list[str] = []
    qr_store = WeixinQrLoginStateStore(str(tmp_path))
    _write_fake_qr_artifact(qr_store.qr_image_path)

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            console_lines.append(" ".join(str(arg) for arg in args))

    async def _fake_save_qr_artifact(_qr_url: str, _store: WeixinQrLoginStateStore) -> None:
        raise ValueError("QR artifact did not contain an image")

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "_save_qr_artifact", _fake_save_qr_artifact, raising=False)

    saved = asyncio.run(
        module._try_save_qr_artifact("https://login.example.com/qr", qr_store)
    )

    assert saved is False
    assert qr_store.qr_image_path.exists() is False
    rendered = "\n".join(console_lines)
    assert "Weixin QR image unavailable locally: QR artifact did not contain an image" in rendered
    assert "Use the Weixin QR login URL above to scan on another device." in rendered


def test_save_qr_artifact_rejects_non_image_payloads(tmp_path: Path) -> None:
    module = _import_auth_cli_module()
    qr_store = WeixinQrLoginStateStore(str(tmp_path))
    html_payload = "data:text/html;base64,PGh0bWw+bm90LWFuLWltYWdlPC9odG1sPg=="

    with pytest.raises(ValueError, match="QR artifact did not contain an image"):
        asyncio.run(module._save_qr_artifact(html_payload, qr_store))

    assert qr_store.qr_image_path.exists() is False


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
    assert "transport state: configured" in rendered
    assert "context_token_unavailable" in rendered
    assert "reply state: waiting_first_message" in rendered
    assert "bot-account" in rendered
    assert "wx-user" in rendered
    assert "请向该微信机器人发送任意消息以建立 context_token" in rendered
    assert 'send a first message such as "你好"' in rendered


def test_cmd_auth_weixin_status_warns_when_login_exists_but_transport_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _weixin_config_without_transport(tmp_path)
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
    assert "transport state: not_in_transports" in rendered
    assert "reply state: transport_not_configured" in rendered
    assert "transports 未包含 weixin" in rendered
    assert 'add "weixin" to transports and restart ControlMesh' in rendered


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
    _write_fake_qr_artifact(WeixinQrLoginStateStore(config.controlmesh_home).qr_image_path)

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
    assert WeixinQrLoginStateStore(config.controlmesh_home).qr_image_path.exists() is False
    rendered = "\n".join(console_lines)
    assert "logged_out" in rendered


def test_cmd_auth_weixin_doctor_reports_direct_and_proxy_routes(
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

    async def _fake_probe(base_url: str, *, mode: str, trust_env: bool):
        assert base_url == config.weixin.base_url
        if mode == "direct":
            assert trust_env is False
            return module.WeixinIlinkProbeResult(
                mode="direct",
                ok=True,
                elapsed_ms=120,
                detail="direct ok",
            )
        assert trust_env is True
        return module.WeixinIlinkProbeResult(
            mode="env-proxy",
            ok=False,
            elapsed_ms=2200,
            detail="proxy timeout",
        )

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "_probe_weixin_route", _fake_probe, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@proxy.example.com:8080")
    monkeypatch.setenv("NO_PROXY", "localhost,ilinkai.weixin.qq.com")

    module.cmd_auth(["weixin", "auth", "doctor"])

    rendered = "\n".join(console_lines)
    assert "Weixin doctor" in rendered
    assert "Weixin proxy env:" in rendered
    assert "http://user:***@proxy.example.com:8080" in rendered
    assert "Weixin direct route: ok in 120 ms" in rendered
    assert "Weixin env-proxy route: failed in 2200 ms" in rendered
    assert "bypass proxy for ilinkai.weixin.qq.com" in rendered


def test_cmd_auth_weixin_doctor_skips_proxy_probe_when_no_proxy_env(
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

    async def _fake_probe(base_url: str, *, mode: str, trust_env: bool):
        assert base_url == config.weixin.base_url
        assert mode == "direct"
        assert trust_env is False
        return module.WeixinIlinkProbeResult(
            mode="direct",
            ok=False,
            elapsed_ms=980,
            detail="connect timeout",
        )

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "_probe_weixin_route", _fake_probe, raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    module.cmd_auth(["weixin", "auth", "doctor"])

    rendered = "\n".join(console_lines)
    assert "Weixin proxy env: none" in rendered
    assert "Weixin env-proxy route: skipped (no proxy env configured)" in rendered
    assert "direct probe failed" in rendered


async def test_probe_weixin_route_uses_explicit_doctor_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _import_auth_cli_module()
    seen: list[tuple[str, bool, float | None]] = []

    async def _fake_fetch_qr_code(
        base_url: str,
        *,
        trust_env: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, str]:
        seen.append((base_url, trust_env, timeout_seconds))
        return {
            "qrcode": "qr-token",
            "qrcode_img_content": "https://login.example.com/qr",
        }

    monkeypatch.setattr(module, "fetch_qr_code", _fake_fetch_qr_code, raising=False)

    result = await module._probe_weixin_route(
        "https://ilinkai.weixin.qq.com",
        mode="direct",
        trust_env=False,
    )

    assert result.ok is True
    assert seen == [
        (
            "https://ilinkai.weixin.qq.com",
            False,
            module._WEIXIN_DOCTOR_TIMEOUT_SECONDS,
        )
    ]


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
