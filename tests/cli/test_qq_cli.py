"""Tests for the archived QQ bridge connect CLI."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from controlmesh.config import AgentConfig
from controlmesh.workspace.paths import resolve_paths


def _import_qq_cli_module() -> ModuleType:
    return importlib.import_module("controlmesh.cli_commands.qq")


def _write_config(tmp_path: Path, config: AgentConfig) -> Path:
    paths = resolve_paths(controlmesh_home=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.config_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")
    return paths.config_path


def test_qq_connect_outputs_bridge_payload_and_persists_api_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _import_qq_cli_module()
    config = AgentConfig(controlmesh_home=str(tmp_path))
    config_path = _write_config(tmp_path, config)

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "nacl_available", lambda: True, raising=False)

    module.cmd_qq(["qq", "connect"])

    payload = json.loads(capsys.readouterr().out)
    persisted = json.loads(config_path.read_text(encoding="utf-8"))

    assert payload["schema"] == "controlmesh.qq.connect.v2"
    assert payload["transport"] == "qq"
    assert payload["mode"] == "bridge"
    assert payload["status"] == "archived_experimental"
    assert payload["active_qq_route"] == "controlmesh-direct-official-qqbot"
    assert payload["bridge_protocol"] == "onebot.v11"
    assert payload["controlmesh"]["bind_host"] == "0.0.0.0"
    assert payload["controlmesh"]["connect_host"] == "127.0.0.1"
    assert payload["controlmesh"]["ws_url"] == "ws://127.0.0.1:8741/ws"
    assert payload["controlmesh"]["http_base_url"] == "http://127.0.0.1:8741"
    assert payload["qq"]["protocol"] == "onebot.v11"
    assert payload["qq"]["connection_mode"] == "forward_websocket_client"
    assert payload["qq"]["onebot_ws_url"] == "ws://127.0.0.1:3001"
    assert payload["qq"]["token"] == ""
    assert payload["qq"]["allow_from"] == "*"
    assert "NapCat" in payload["qq"]["recommended_implementations"]
    assert payload["references"]["cc_connect"].startswith("https://github.com/chenhg5/cc-connect")
    assert payload["api_enabled_changed"] is True
    assert payload["token_generated"] is True
    assert persisted["api"]["enabled"] is True
    assert persisted["api"]["token"] == payload["controlmesh"]["token"]


def test_qq_connect_respects_explicit_api_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _import_qq_cli_module()
    config = AgentConfig(
        controlmesh_home=str(tmp_path),
        api={"enabled": True, "host": "127.0.0.1", "port": 9001, "token": "tok_123", "chat_id": 7},
    )
    _write_config(tmp_path, config)

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "nacl_available", lambda: True, raising=False)

    module.cmd_qq(["qq", "connect"])

    payload = json.loads(capsys.readouterr().out)

    assert payload["controlmesh"]["connect_host"] == "127.0.0.1"
    assert payload["controlmesh"]["ws_url"] == "ws://127.0.0.1:9001/ws"
    assert payload["controlmesh"]["http_base_url"] == "http://127.0.0.1:9001"
    assert payload["controlmesh"]["chat_id"] == 7
    assert payload["controlmesh"]["token"] == "tok_123"
    assert payload["api_enabled_changed"] is False
    assert payload["token_generated"] is False


def test_qq_connect_help_prints_usage_without_loading_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _import_qq_cli_module()

    def _unexpected_load() -> AgentConfig:
        raise AssertionError("load_config should not run for --help")

    monkeypatch.setattr(module, "load_config", _unexpected_load, raising=False)

    module.cmd_qq(["qq", "connect", "--help"])

    rendered = capsys.readouterr().out
    assert "controlmesh qq connect" in rendered
    assert "archived experimental QQ bridge" in rendered
    assert "OneBot v11" in rendered


def test_main_routes_qq_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    import controlmesh.__main__ as main_mod

    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", ["controlmesh", "qq", "connect"])
    monkeypatch.setattr(main_mod, "_cmd_qq", lambda args: calls.append(list(args)))

    main_mod.main()

    assert calls == [["qq", "connect"]]
