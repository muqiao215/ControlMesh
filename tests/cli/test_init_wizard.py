"""Tests for onboarding wizard behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from controlmesh.cli.init_wizard import _WizardConfig, _write_config, run_onboarding
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "framework"
    fw.mkdir(parents=True, exist_ok=True)
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


def test_write_config_ignores_corrupt_existing_json(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.config_path.write_text("{broken json", encoding="utf-8")

    with (
        patch("controlmesh.cli.init_wizard.resolve_paths", return_value=paths),
        patch("controlmesh.cli.init_wizard.init_workspace"),
    ):
        out = _write_config(
            _WizardConfig(
                transport="telegram",
                telegram_token="123456789:abcdefghijklmnopqrstuvwxyzABCDE",
                allowed_user_ids=[1234],
                user_timezone="UTC",
                docker_enabled=False,
            )
        )

    assert out == paths.config_path
    data = json.loads(paths.config_path.read_text(encoding="utf-8"))
    assert data["telegram_token"] == "123456789:abcdefghijklmnopqrstuvwxyzABCDE"
    assert data["allowed_user_ids"] == [1234]
    assert data["user_timezone"] == "UTC"
    assert data["gemini_api_key"] == "null"


def test_write_config_normalizes_existing_null_gemini_api_key(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.config_path.write_text('{"gemini_api_key": null}', encoding="utf-8")

    with (
        patch("controlmesh.cli.init_wizard.resolve_paths", return_value=paths),
        patch("controlmesh.cli.init_wizard.init_workspace"),
    ):
        _write_config(
            _WizardConfig(
                transport="telegram",
                telegram_token="123456789:abcdefghijklmnopqrstuvwxyzABCDE",
                allowed_user_ids=[1234],
                user_timezone="UTC",
                docker_enabled=False,
            )
        )

    data = json.loads(paths.config_path.read_text(encoding="utf-8"))
    assert data["gemini_api_key"] == "null"


def test_run_onboarding_returns_false_when_service_install_fails(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)

    with (
        patch("controlmesh.cli.init_wizard._show_banner"),
        patch("controlmesh.cli.init_wizard._check_clis"),
        patch("controlmesh.cli.init_wizard._show_disclaimer"),
        patch("controlmesh.cli.init_wizard._ask_transport", return_value="telegram"),
        patch("controlmesh.cli.init_wizard._ask_telegram_token", return_value="token"),
        patch("controlmesh.cli.init_wizard._ask_user_id", return_value=[1]),
        patch("controlmesh.cli.init_wizard._ask_docker", return_value=False),
        patch("controlmesh.cli.init_wizard._ask_timezone", return_value="UTC"),
        patch("controlmesh.cli.init_wizard._write_config", return_value=paths.config_path),
        patch("controlmesh.cli.init_wizard.resolve_paths", return_value=paths),
        patch("controlmesh.cli.init_wizard._offer_service_install", return_value=True),
        patch("controlmesh.infra.service.install_service", return_value=False),
    ):
        assert run_onboarding() is False


def test_run_onboarding_returns_true_when_service_install_succeeds(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)

    with (
        patch("controlmesh.cli.init_wizard._show_banner"),
        patch("controlmesh.cli.init_wizard._check_clis"),
        patch("controlmesh.cli.init_wizard._show_disclaimer"),
        patch("controlmesh.cli.init_wizard._ask_transport", return_value="telegram"),
        patch("controlmesh.cli.init_wizard._ask_telegram_token", return_value="token"),
        patch("controlmesh.cli.init_wizard._ask_user_id", return_value=[1]),
        patch("controlmesh.cli.init_wizard._ask_docker", return_value=False),
        patch("controlmesh.cli.init_wizard._ask_timezone", return_value="UTC"),
        patch("controlmesh.cli.init_wizard._write_config", return_value=paths.config_path),
        patch("controlmesh.cli.init_wizard.resolve_paths", return_value=paths),
        patch("controlmesh.cli.init_wizard._offer_service_install", return_value=True),
        patch("controlmesh.infra.service.install_service", return_value=True),
    ):
        assert run_onboarding() is True
