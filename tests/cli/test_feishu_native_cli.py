"""Tests for product-friendly Feishu native CLI aliases."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

from rich.console import Console


def _import_feishu_cli_module() -> ModuleType:
    return importlib.import_module("controlmesh.cli_commands.feishu")


def test_feishu_native_bootstrap_aliases_auth_feishu_setup(monkeypatch) -> None:
    module = _import_feishu_cli_module()
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "cmd_auth", lambda args: calls.append(list(args)), raising=False)

    module.cmd_feishu(["feishu", "native", "bootstrap"])

    assert calls == [["auth", "feishu", "setup"]]


def test_feishu_native_setup_aliases_register_begin_and_preserves_flags(monkeypatch) -> None:
    module = _import_feishu_cli_module()
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "cmd_auth", lambda args: calls.append(list(args)), raising=False)

    module.cmd_feishu(["feishu", "native", "setup", "--no-start-service"])

    assert calls == [["auth", "feishu", "register-begin", "--no-start-service"]]


def test_feishu_native_complete_aliases_register_complete(monkeypatch) -> None:
    module = _import_feishu_cli_module()
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "cmd_auth", lambda args: calls.append(list(args)), raising=False)

    module.cmd_feishu(["feishu", "native", "complete"])

    assert calls == [["auth", "feishu", "register-complete"]]


def test_main_routes_feishu_native_bootstrap(monkeypatch) -> None:
    import controlmesh.__main__ as main_mod

    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", ["controlmesh", "feishu", "native", "bootstrap"])
    monkeypatch.setattr(main_mod, "_cmd_feishu", lambda args: calls.append(list(args)))

    main_mod.main()

    assert calls == [["feishu", "native", "bootstrap"]]


def test_main_routes_tasks_list(monkeypatch) -> None:
    import controlmesh.__main__ as main_mod

    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", ["controlmesh", "tasks", "list"])
    monkeypatch.setattr(main_mod, "_cmd_tasks", lambda args: calls.append(list(args)))

    main_mod.main()

    assert calls == [["tasks", "list"]]


def test_feishu_native_bootstrap_help_prints_usage_without_running_auth(monkeypatch) -> None:
    module = _import_feishu_cli_module()
    console = Console(record=True, width=120)

    def _unexpected_auth(_args: list[str]) -> None:
        raise AssertionError("cmd_auth should not run for --help")

    monkeypatch.setattr(module, "cmd_auth", _unexpected_auth, raising=False)
    monkeypatch.setattr(module, "_console", console, raising=False)

    module.cmd_feishu(["feishu", "native", "bootstrap", "--help"])

    rendered = console.export_text()
    assert "controlmesh feishu native bootstrap" in rendered
    assert "bootstrap flow" in rendered


def test_feishu_native_setup_help_prints_stable_flow(monkeypatch) -> None:
    module = _import_feishu_cli_module()
    console = Console(record=True, width=120)

    def _unexpected_auth(_args: list[str]) -> None:
        raise AssertionError("cmd_auth should not run for --help")

    monkeypatch.setattr(module, "cmd_auth", _unexpected_auth, raising=False)
    monkeypatch.setattr(module, "_console", console, raising=False)

    module.cmd_feishu(["feishu", "native", "setup", "--help"])

    rendered = console.export_text()
    assert "controlmesh feishu native setup" in rendered
    assert "stable Feishu-native setup flow" in rendered
    assert "auto-complete config writeback" in rendered
