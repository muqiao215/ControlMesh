"""Red contracts for the minimal Feishu device-flow auth CLI slice."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.device_flow import DeviceAuthorization, DeviceTokenGrant

if TYPE_CHECKING:
    import pytest


def _import_auth_cli_module() -> ModuleType:
    try:
        return importlib.import_module("controlmesh.cli_commands.auth")
    except ModuleNotFoundError as exc:  # pragma: no cover - red-path contract
        msg = "missing CLI auth command module: controlmesh.cli_commands.auth"
        raise AssertionError(msg) from exc


def _feishu_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        controlmesh_home=str(tmp_path),
        transport="feishu",
        transports=["feishu"],
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "app_id": "cli_123",
            "app_secret": "sec_456",
        },
    )


def test_main_routes_auth_feishu_login_to_auth_command(monkeypatch: pytest.MonkeyPatch) -> None:
    import controlmesh.__main__ as main_mod

    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(sys, "argv", ["controlmesh", "auth", "feishu", "login"])
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

    assert calls == [("auth", ["auth", "feishu", "login"])]


def test_cmd_auth_feishu_login_starts_device_flow_and_surfaces_authorization_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config(tmp_path)
    console_lines: list[str] = []
    persisted: dict[str, Any] = {}

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    async def _fake_request_device_authorization(*_args: object, **_kwargs: object) -> DeviceAuthorization:
        return DeviceAuthorization(
            device_code="dc_123",
            user_code="USER-123",
            verification_uri="https://verify.test/device",
            verification_uri_complete="https://verify.test/device?user_code=USER-123",
            expires_in=600,
            interval=5,
        )

    async def _fake_poll_device_token(*_args: object, **_kwargs: object) -> DeviceTokenGrant:
        return DeviceTokenGrant(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=7200,
            refresh_token_expires_in=86400,
            scope="offline_access im:message",
        )

    def _fake_persist_device_flow_auth(**kwargs: object) -> dict[str, object]:
        persisted.update(kwargs)
        return persisted

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        module,
        "request_device_authorization",
        _fake_request_device_authorization,
        raising=False,
    )
    monkeypatch.setattr(module, "poll_device_token", _fake_poll_device_token, raising=False)
    monkeypatch.setattr(module, "persist_device_flow_auth", _fake_persist_device_flow_auth, raising=False)

    module.cmd_auth(["auth", "feishu", "login"])

    rendered = "\n".join(console_lines)
    for field in (
        "dc_123",
        "USER-123",
        "https://verify.test/device",
        "https://verify.test/device?user_code=USER-123",
        "600",
        "5",
    ):
        assert field in rendered

    assert persisted["auth_mode"] == "device_flow"
    assert persisted["token_source"] == "device_flow"
    assert persisted["access_token"] == "access-token"
    assert persisted["refresh_token"] == "refresh-token"
    assert "expires_at" in persisted
    assert "refresh_expires_at" in persisted


def test_cmd_auth_feishu_status_reports_active_device_flow_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config(tmp_path)
    console_lines: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    class _Status:
        active_auth_mode = "device_flow"
        uses_device_flow = True
        token_source = "device_flow"

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "get_feishu_auth_status", lambda **_kwargs: _Status(), raising=False)

    module.cmd_auth(["auth", "feishu", "status"])

    rendered = "\n".join(console_lines)
    assert "device_flow" in rendered


def test_cmd_auth_feishu_logout_clears_only_device_flow_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config(tmp_path)
    cleared: list[dict[str, object]] = []

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        module,
        "clear_device_flow_auth",
        lambda **kwargs: cleared.append(dict(kwargs)),
        raising=False,
    )

    module.cmd_auth(["auth", "feishu", "logout"])

    assert len(cleared) == 1
    assert config.feishu.app_id == "cli_123"
    assert config.feishu.app_secret == "sec_456"
