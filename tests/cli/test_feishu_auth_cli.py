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


def _feishu_config_without_app(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        controlmesh_home=str(tmp_path),
        transport="feishu",
        transports=["feishu"],
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
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


def test_cmd_auth_feishu_setup_guides_zero_app_users(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config_without_app(tmp_path)
    console_lines: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)

    module.cmd_auth(["auth", "feishu", "setup"])

    rendered = "\n".join(console_lines)
    assert "Feishu app configured: false" in rendered
    assert "missing feishu.app_id" in rendered or "feishu.app_id" in rendered
    assert "controlmesh auth feishu register-begin" in rendered
    assert "official Feishu/Lark scan-to-create" in rendered
    assert "Manual fallback" in rendered
    assert "controlmesh auth feishu login" in rendered


def test_cmd_auth_feishu_setup_reuses_feishu_auth_kit_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config_without_app(tmp_path)
    console_lines: list[str] = []
    calls: list[tuple[list[str], dict[str, str]]] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    class _FakeResult:
        returncode = 0
        stdout = "Feishu / Lark app setup guide\nThis kit cannot create the app for you.\n"
        stderr = ""

    def _fake_run_feishu_auth_kit(
        args: list[str],
        *,
        extra_env: dict[str, str] | None = None,
    ) -> _FakeResult:
        calls.append((args, extra_env or {}))
        return _FakeResult()

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "run_feishu_auth_kit", _fake_run_feishu_auth_kit, raising=False)

    module.cmd_auth(["auth", "feishu", "setup"])

    rendered = "\n".join(console_lines)
    assert calls == [(["setup", "--brand", "feishu"], {})]
    assert "Feishu / Lark app setup guide" in rendered
    assert "cannot create the app" in rendered


def test_cmd_auth_feishu_register_begin_delegates_to_scan_create_no_poll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config_without_app(tmp_path)
    console_lines: list[str] = []
    calls: list[list[str]] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    def _fake_run_feishu_auth_kit_json(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {
            "status": "authorization_required",
            "qr_url": "https://accounts.feishu.cn/verify?from=oc_onboard&tp=ob_cli_app",
            "device_code": "dev_123",
            "user_code": "ABCD-EFGH",
            "interval": 5,
            "expires_in": 600,
        }

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        module,
        "run_feishu_auth_kit_json",
        _fake_run_feishu_auth_kit_json,
        raising=False,
    )

    module.cmd_auth(["auth", "feishu", "register-begin"])

    assert calls == [
        ["register", "scan-create", "--brand", "feishu", "--no-poll", "--json"]
    ]
    rendered = "\n".join(console_lines)
    assert '"status": "authorization_required"' in rendered
    assert "dev_123" in rendered
    assert "oc_onboard" in rendered


def test_cmd_auth_feishu_register_poll_delegates_to_auth_kit_poll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config_without_app(tmp_path)
    console_lines: list[str] = []
    calls: list[list[str]] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    def _fake_run_feishu_auth_kit_json(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {
            "status": "success",
            "app_id": "cli_new",
            "app_secret": "secret-new",
            "domain": "feishu",
            "open_id": "ou_owner",
        }

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        module,
        "run_feishu_auth_kit_json",
        _fake_run_feishu_auth_kit_json,
        raising=False,
    )

    module.cmd_auth(
        [
            "auth",
            "feishu",
            "register-poll",
            "--device-code",
            "dev_123",
            "--interval",
            "5",
            "--expires-in",
            "600",
            "--poll-timeout",
            "30",
        ]
    )

    assert calls == [
        [
            "register",
            "poll",
            "--brand",
            "feishu",
            "--device-code",
            "dev_123",
            "--interval",
            "5",
            "--expires-in",
            "600",
            "--poll-timeout",
            "30",
            "--json",
        ]
    ]
    rendered = "\n".join(console_lines)
    assert '"status": "success"' in rendered
    assert '"app_id": "cli_new"' in rendered


def test_cmd_auth_feishu_probe_delegates_to_register_probe_with_env_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config(tmp_path)
    console_lines: list[str] = []
    calls: list[tuple[list[str], dict[str, str]]] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    def _fake_run_feishu_auth_kit_json(
        args: list[str],
        *,
        extra_env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        calls.append((args, extra_env or {}))
        return {
            "ok": True,
            "app_id": "cli_123",
            "bot_name": "ControlMesh Bot",
            "bot_open_id": "ou_bot",
        }

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        module,
        "run_feishu_auth_kit_json",
        _fake_run_feishu_auth_kit_json,
        raising=False,
    )

    module.cmd_auth(["auth", "feishu", "probe"])

    assert calls == [
        (
            ["register", "probe", "--brand", "feishu", "--json"],
            {
                "FEISHU_APP_ID": "cli_123",
                "FEISHU_APP_SECRET": "sec_456",
                "FEISHU_BRAND": "feishu",
            },
        )
    ]
    rendered = "\n".join(console_lines)
    assert '"ok": true' in rendered
    assert "ControlMesh Bot" in rendered


def test_cmd_auth_feishu_doctor_delegates_to_feishu_auth_kit_with_env_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config(tmp_path)
    console_lines: list[str] = []
    calls: list[tuple[list[str], dict[str, str]]] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    class _FakeResult:
        returncode = 0
        stdout = "Doctor report\nTenant token: OK\n"
        stderr = ""

    def _fake_run_feishu_auth_kit(
        args: list[str],
        *,
        extra_env: dict[str, str] | None = None,
    ) -> _FakeResult:
        calls.append((args, extra_env or {}))
        return _FakeResult()

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "run_feishu_auth_kit", _fake_run_feishu_auth_kit, raising=False)

    module.cmd_auth(["auth", "feishu", "doctor"])

    rendered = "\n".join(console_lines)
    assert calls == [
        (
            ["doctor", "--brand", "feishu"],
            {
                "FEISHU_APP_ID": "cli_123",
                "FEISHU_APP_SECRET": "sec_456",
                "FEISHU_BRAND": "feishu",
            },
        )
    ]
    assert "Doctor report" in rendered
    assert "Tenant token: OK" in rendered
    assert "sec_456" not in " ".join(calls[0][0])


def test_cmd_auth_feishu_doctor_exits_with_auth_kit_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config(tmp_path)

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            return None

    class _FakeResult:
        returncode = 3
        stdout = "Doctor failed\n"
        stderr = "missing permission\n"

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        module,
        "run_feishu_auth_kit",
        lambda *_args, **_kwargs: _FakeResult(),
        raising=False,
    )

    import pytest

    with pytest.raises(SystemExit) as exc_info:
        module.cmd_auth(["auth", "feishu", "doctor"])

    assert exc_info.value.code == 3


def test_cmd_auth_feishu_plan_delegates_to_orchestration_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _import_auth_cli_module()
    console_lines: list[str] = []
    calls: list[list[str]] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    def _fake_run_feishu_auth_kit_json(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {
            "requested_scopes": ["offline_access", "im:message"],
            "missing_user_scopes": ["im:message"],
            "batches": [["im:message"]],
        }

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(
        module,
        "run_feishu_auth_kit_json",
        _fake_run_feishu_auth_kit_json,
        raising=False,
    )

    module.cmd_auth(
        [
            "auth",
            "feishu",
            "plan",
            "--requested-scope",
            "offline_access,im:message",
            "--app-scope",
            "offline_access",
            "--user-scope",
            "offline_access",
            "--batch-size",
            "25",
            "--keep-sensitive",
        ]
    )

    assert calls == [
        [
            "orchestration",
            "plan",
            "--requested-scope",
            "offline_access",
            "--requested-scope",
            "im:message",
            "--app-scope",
            "offline_access",
            "--user-scope",
            "offline_access",
            "--batch-size",
            "25",
            "--keep-sensitive",
        ]
    ]
    rendered = "\n".join(console_lines)
    assert '"missing_user_scopes": [' in rendered
    assert '"im:message"' in rendered


def test_cmd_auth_feishu_route_delegates_to_orchestration_route_with_default_store_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config(tmp_path)
    console_lines: list[str] = []
    calls: list[list[str]] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    def _fake_run_feishu_auth_kit_json(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {
            "decision": "permission_card",
            "flow": {"operation_id": "op_123", "flow_key": "fk_123"},
            "card": {"kind": "permission_missing"},
        }

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        module,
        "run_feishu_auth_kit_json",
        _fake_run_feishu_auth_kit_json,
        raising=False,
    )

    module.cmd_auth(
        [
            "auth",
            "feishu",
            "route",
            "--error-kind",
            "app_scope_missing",
            "--required-scope",
            "im:message",
            "--permission-url",
            "https://open.feishu.cn/perm",
            "--user-open-id",
            "ou_123",
        ]
    )

    assert calls == [
        [
            "orchestration",
            "route",
            "--app-id",
            "cli_123",
            "--error-kind",
            "app_scope_missing",
            "--required-scope",
            "im:message",
            "--user-open-id",
            "ou_123",
            "--permission-url",
            "https://open.feishu.cn/perm",
            "--continuation-store-path",
            f"{tmp_path}/feishu_store/auth/continuations.json",
            "--pending-flow-store-path",
            f"{tmp_path}/feishu_store/auth/pending_flows.json",
        ]
    ]
    rendered = "\n".join(console_lines)
    assert '"decision": "permission_card"' in rendered


def test_cmd_auth_feishu_retry_delegates_to_orchestration_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config(tmp_path)
    console_lines: list[str] = []
    calls: list[list[str]] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    def _fake_run_feishu_auth_kit_json(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {
            "kind": "synthetic_retry",
            "operation_id": "op_123",
            "text": "retry original task",
        }

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        module,
        "run_feishu_auth_kit_json",
        _fake_run_feishu_auth_kit_json,
        raising=False,
    )

    module.cmd_auth(
        [
            "auth",
            "feishu",
            "retry",
            "--operation-id",
            "op_123",
            "--text",
            "retry original task",
        ]
    )

    assert calls == [
        [
            "orchestration",
            "retry",
            "--operation-id",
            "op_123",
            "--text",
            "retry original task",
            "--continuation-store-path",
            f"{tmp_path}/feishu_store/auth/continuations.json",
        ]
    ]
    rendered = "\n".join(console_lines)
    assert '"kind": "synthetic_retry"' in rendered


def test_cmd_auth_feishu_login_requires_existing_app_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _import_auth_cli_module()
    config = _feishu_config_without_app(tmp_path)
    console_lines: list[str] = []

    class _FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            console_lines.append(" ".join(str(arg) for arg in args))

    async def _should_not_call(*_args: object, **_kwargs: object) -> DeviceAuthorization:
        raise AssertionError("login must not call Feishu device authorization without app credentials")

    monkeypatch.setattr(module, "_console", _FakeConsole(), raising=False)
    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "request_device_authorization", _should_not_call, raising=False)

    import pytest

    with pytest.raises(SystemExit) as exc_info:
        module.cmd_auth(["auth", "feishu", "login"])

    assert exc_info.value.code == 1
    rendered = "\n".join(console_lines)
    assert "Feishu login requires an existing Feishu self-built app" in rendered
    assert "feishu.app_id" in rendered
    assert "feishu.app_secret" in rendered
    assert "controlmesh auth feishu login" in rendered


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
