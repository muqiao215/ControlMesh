"""Tests for ControlMesh's bundled feishu-auth-kit plugin seam."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from controlmesh.integrations import feishu_auth_kit


def test_env_override_still_wins_when_executable_exists(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "feishu-auth-kit"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("CONTROLMESH_FEISHU_AUTH_KIT_BIN", f"{binary} --flag")

    command, cwd = feishu_auth_kit.resolve_feishu_auth_kit_command()

    assert command == [str(binary), "--flag"]
    assert cwd is None


def test_stale_env_override_falls_back_to_bundled_plugin(monkeypatch) -> None:
    monkeypatch.setenv("CONTROLMESH_FEISHU_AUTH_KIT_BIN", "/missing/feishu-auth-kit")
    monkeypatch.setattr(feishu_auth_kit, "_bundled_plugin_available", lambda: True)

    command, cwd = feishu_auth_kit.resolve_feishu_auth_kit_command()

    assert command == [
        sys.executable,
        "-m",
        "controlmesh._plugins.feishu_auth_kit.runner",
    ]
    assert cwd is None


def test_bundled_plugin_is_default_when_no_override(monkeypatch) -> None:
    monkeypatch.delenv("CONTROLMESH_FEISHU_AUTH_KIT_BIN", raising=False)
    monkeypatch.setattr(feishu_auth_kit, "_bundled_plugin_available", lambda: True)

    command, cwd = feishu_auth_kit.resolve_feishu_auth_kit_command()

    assert command == [
        sys.executable,
        "-m",
        "controlmesh._plugins.feishu_auth_kit.runner",
    ]
    assert cwd is None


def test_bundled_runner_help_is_executable() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "controlmesh._plugins.feishu_auth_kit.runner", "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage: feishu-auth-kit" in result.stdout
    assert "agent" in result.stdout
