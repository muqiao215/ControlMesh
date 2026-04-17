"""Tests for product-friendly Feishu native CLI aliases."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType


def _import_feishu_cli_module() -> ModuleType:
    return importlib.import_module("controlmesh.cli_commands.feishu")


def test_feishu_native_bootstrap_aliases_auth_feishu_setup(monkeypatch) -> None:
    module = _import_feishu_cli_module()
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "cmd_auth", lambda args: calls.append(list(args)), raising=False)

    module.cmd_feishu(["feishu", "native", "bootstrap"])

    assert calls == [["auth", "feishu", "setup"]]


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
