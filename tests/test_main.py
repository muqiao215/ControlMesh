"""Tests for __main__.py entry point."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from controlmesh.config import AgentConfig
from controlmesh.infra.version import get_current_version
from controlmesh.workspace.paths import ControlMeshPaths

# Shorthand module paths for patching the new submodules.
_LIFECYCLE = "controlmesh.cli_commands.lifecycle"
_STATUS = "controlmesh.cli_commands.status"
_SERVICE = "controlmesh.cli_commands.service"


class TestLoadConfig:
    """Test config loading, creation, and smart-merge."""

    def test_creates_config_from_example(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import load_config

        home = tmp_path / ".controlmesh"
        fw = tmp_path / "framework"
        fw.mkdir()
        example = {"telegram_token": "TEST", "provider": "claude"}
        (fw / "config.example.json").write_text(json.dumps(example))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(controlmesh_home=home, home_defaults=fw / "workspace", framework_root=fw)
            mock_paths.return_value = paths
            with patch("controlmesh.__main__.init_workspace"):
                config = load_config()

        assert config.telegram_token == "TEST"
        assert paths.config_path.exists()

    def test_preserves_existing_user_config(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import load_config

        home = tmp_path / ".controlmesh"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        fw = tmp_path / "framework"
        fw.mkdir()
        user_cfg = {"telegram_token": "MY_TOKEN", "provider": "codex", "model": "gpt-5.2-codex"}
        (config_dir / "config.json").write_text(json.dumps(user_cfg))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(controlmesh_home=home, home_defaults=fw / "workspace", framework_root=fw)
            mock_paths.return_value = paths
            with patch("controlmesh.__main__.init_workspace"):
                config = load_config()

        assert config.telegram_token == "MY_TOKEN"
        assert config.provider == "codex"

    def test_merges_new_defaults_into_existing(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import load_config

        home = tmp_path / ".controlmesh"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        fw = tmp_path / "framework"
        fw.mkdir()
        old_cfg = {"telegram_token": "TOKEN", "provider": "claude"}
        (config_dir / "config.json").write_text(json.dumps(old_cfg))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(controlmesh_home=home, home_defaults=fw / "workspace", framework_root=fw)
            mock_paths.return_value = paths
            with patch("controlmesh.__main__.init_workspace"):
                config = load_config()

        assert config.streaming.enabled is True
        assert config.gemini_api_key is None
        merged = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert merged["gemini_api_key"] == "null"

    def test_creates_default_config_when_no_example(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import load_config

        home = tmp_path / ".controlmesh"
        fw = tmp_path / "framework"
        fw.mkdir()

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(controlmesh_home=home, home_defaults=fw / "workspace", framework_root=fw)
            mock_paths.return_value = paths
            with patch("controlmesh.__main__.init_workspace"):
                config = load_config()

        assert paths.config_path.exists()
        assert config.provider == "claude"
        created = json.loads(paths.config_path.read_text(encoding="utf-8"))
        assert created["gemini_api_key"] == "null"

    def test_normalizes_existing_null_gemini_api_key_to_string(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import load_config

        home = tmp_path / ".controlmesh"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        fw = tmp_path / "framework"
        fw.mkdir()
        user_cfg = {"telegram_token": "TOKEN", "provider": "claude", "gemini_api_key": None}
        (config_dir / "config.json").write_text(json.dumps(user_cfg), encoding="utf-8")

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(controlmesh_home=home, home_defaults=fw / "workspace", framework_root=fw)
            mock_paths.return_value = paths
            with patch("controlmesh.__main__.init_workspace"):
                config = load_config()

        assert config.gemini_api_key is None
        merged = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert merged["gemini_api_key"] == "null"

    def test_persists_resolved_home_when_env_selected_legacy_config_lacks_field(
        self, tmp_path: Path
    ) -> None:
        from controlmesh.__main__ import load_config

        home = tmp_path / ".ductor"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        fw = tmp_path / "framework"
        fw.mkdir()
        legacy_cfg = {"telegram_token": "TOKEN", "provider": "codex"}
        (config_dir / "config.json").write_text(json.dumps(legacy_cfg), encoding="utf-8")

        with (
            patch.dict(os.environ, {"CONTROLMESH_HOME": str(home)}),
            patch("controlmesh.__main__.resolve_paths") as mock_paths,
        ):
            paths = ControlMeshPaths(
                controlmesh_home=home, home_defaults=fw / "workspace", framework_root=fw
            )
            mock_paths.return_value = paths
            with patch("controlmesh.__main__.init_workspace"):
                config = load_config()

        assert Path(config.controlmesh_home).resolve() == home.resolve()
        merged = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert Path(merged["controlmesh_home"]).resolve() == home.resolve()


class TestIsConfigured:
    def test_unconfigured_when_no_config(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(
                controlmesh_home=tmp_path / "home",
                home_defaults=tmp_path / "fw" / "workspace",
                framework_root=tmp_path / "fw",
            )
            mock_paths.return_value = paths
            assert _is_configured() is False

    def test_configured_with_valid_token(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        home = tmp_path / "home"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        cfg = {"telegram_token": "123456:ABC", "allowed_user_ids": [1]}
        (config_dir / "config.json").write_text(json.dumps(cfg))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(
                controlmesh_home=home,
                home_defaults=tmp_path / "fw" / "workspace",
                framework_root=tmp_path / "fw",
            )
            mock_paths.return_value = paths
            assert _is_configured() is True

    def test_configured_with_valid_feishu_bot_only(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        home = tmp_path / "home"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        cfg = {
            "transport": "feishu",
            "feishu": {
                "mode": "bot_only",
                "app_id": "cli_123",
                "app_secret": "sec_456",
            },
        }
        (config_dir / "config.json").write_text(json.dumps(cfg))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(
                controlmesh_home=home,
                home_defaults=tmp_path / "fw" / "workspace",
                framework_root=tmp_path / "fw",
            )
            mock_paths.return_value = paths
            assert _is_configured() is True

    def test_unconfigured_with_missing_feishu_secret(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        home = tmp_path / "home"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        cfg = {
            "transport": "feishu",
            "feishu": {
                "mode": "bot_only",
                "app_id": "cli_123",
                "app_secret": "",
            },
        }
        (config_dir / "config.json").write_text(json.dumps(cfg))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(
                controlmesh_home=home,
                home_defaults=tmp_path / "fw" / "workspace",
                framework_root=tmp_path / "fw",
            )
            mock_paths.return_value = paths
            assert _is_configured() is False

    def test_unconfigured_with_weixin_disabled_by_default(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        home = tmp_path / "home"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        cfg = {
            "transport": "weixin",
            "weixin": {
                "mode": "ilink",
                "enabled": False,
            },
        }
        (config_dir / "config.json").write_text(json.dumps(cfg))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(
                controlmesh_home=home,
                home_defaults=tmp_path / "fw" / "workspace",
                framework_root=tmp_path / "fw",
            )
            mock_paths.return_value = paths
            assert _is_configured() is False

    def test_configured_with_enabled_weixin_and_stored_credentials(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        home = tmp_path / "home"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        credentials_path = home / "weixin_store" / "credentials.json"
        credentials_path.parent.mkdir(parents=True)
        credentials_path.write_text(
            json.dumps(
                {
                    "token": "bot-token",
                    "base_url": "https://ilinkai.weixin.qq.com",
                    "account_id": "bot-account",
                    "user_id": "wx-user",
                }
            ),
            encoding="utf-8",
        )
        cfg = {
            "transport": "weixin",
            "controlmesh_home": str(home),
            "weixin": {
                "mode": "ilink",
                "enabled": True,
                "credentials_path": "weixin_store/credentials.json",
            },
        }
        (config_dir / "config.json").write_text(json.dumps(cfg))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(
                controlmesh_home=home,
                home_defaults=tmp_path / "fw" / "workspace",
                framework_root=tmp_path / "fw",
            )
            mock_paths.return_value = paths
            assert _is_configured() is True

    def test_unconfigured_with_enabled_weixin_and_corrupt_credentials(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        home = tmp_path / "home"
        config_dir = home / "config"
        config_dir.mkdir(parents=True)
        credentials_path = home / "weixin_store" / "credentials.json"
        credentials_path.parent.mkdir(parents=True)
        credentials_path.write_text('{"token":"bot-token","account_id":1}', encoding="utf-8")
        cfg = {
            "transport": "weixin",
            "controlmesh_home": str(home),
            "weixin": {
                "mode": "ilink",
                "enabled": True,
                "credentials_path": "weixin_store/credentials.json",
            },
        }
        (config_dir / "config.json").write_text(json.dumps(cfg))

        with patch("controlmesh.__main__.resolve_paths") as mock_paths:
            paths = ControlMeshPaths(
                controlmesh_home=home,
                home_defaults=tmp_path / "fw" / "workspace",
                framework_root=tmp_path / "fw",
            )
            mock_paths.return_value = paths
            assert _is_configured() is False


class TestRunTelegram:
    async def test_exits_on_missing_token(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import run_telegram

        config = AgentConfig(telegram_token="", controlmesh_home=str(tmp_path))
        with pytest.raises(SystemExit):
            await run_telegram(config)

    async def test_exits_on_placeholder_token(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import run_telegram

        config = AgentConfig(telegram_token="YOUR_TOKEN_HERE", controlmesh_home=str(tmp_path))
        with pytest.raises(SystemExit):
            await run_telegram(config)

    async def test_exits_on_empty_allowed_users(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import run_telegram

        config = AgentConfig(
            telegram_token="valid:token", allowed_user_ids=[], controlmesh_home=str(tmp_path)
        )
        with pytest.raises(SystemExit):
            await run_telegram(config)

    async def test_runs_bot_with_valid_config(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import run_telegram

        config = AgentConfig(
            telegram_token="valid:token", allowed_user_ids=[123], controlmesh_home=str(tmp_path)
        )
        mock_supervisor = MagicMock()
        mock_supervisor.start = AsyncMock(return_value=0)
        mock_supervisor.stop_all = AsyncMock()

        with (
            patch("controlmesh.__main__.resolve_paths"),
            patch("controlmesh.infra.pidlock.acquire_lock"),
            patch("controlmesh.infra.pidlock.release_lock"),
            patch(
                "controlmesh.multiagent.supervisor.AgentSupervisor",
                return_value=mock_supervisor,
            ),
        ):
            await run_telegram(config)

        mock_supervisor.start.assert_called_once()
        mock_supervisor.stop_all.assert_called_once()


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    home = tmp_path / "home"
    fw = tmp_path / "fw"
    fw.mkdir(parents=True, exist_ok=True)
    return ControlMeshPaths(controlmesh_home=home, home_defaults=fw / "workspace", framework_root=fw)


def _write_config(paths: ControlMeshPaths, data: dict[str, object]) -> None:
    paths.config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.config_path.write_text(json.dumps(data), encoding="utf-8")


class TestIsConfiguredExtended:
    def test_unconfigured_with_placeholder_token(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        paths = _make_paths(tmp_path)
        _write_config(paths, {"telegram_token": "YOUR_TOKEN", "allowed_user_ids": [1]})
        with patch("controlmesh.__main__.resolve_paths", return_value=paths):
            assert _is_configured() is False

    def test_unconfigured_with_empty_users(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        paths = _make_paths(tmp_path)
        _write_config(paths, {"telegram_token": "123:ABC", "allowed_user_ids": []})
        with patch("controlmesh.__main__.resolve_paths", return_value=paths):
            assert _is_configured() is False

    def test_unconfigured_with_corrupt_json(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        paths = _make_paths(tmp_path)
        paths.config_path.parent.mkdir(parents=True)
        paths.config_path.write_text("{invalid json", encoding="utf-8")
        with patch("controlmesh.__main__.resolve_paths", return_value=paths):
            assert _is_configured() is False


class TestIsConfiguredMultiTransport:
    def test_configured_multi_transport_both_valid(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        paths = _make_paths(tmp_path)
        _write_config(
            paths,
            {
                "transports": ["telegram", "matrix"],
                "telegram_token": "123:ABC",
                "allowed_user_ids": [1],
                "matrix": {"homeserver": "https://mx.test", "user_id": "@bot:test"},
            },
        )
        with patch("controlmesh.__main__.resolve_paths", return_value=paths):
            assert _is_configured() is True

    def test_unconfigured_multi_transport_missing_matrix(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        paths = _make_paths(tmp_path)
        _write_config(
            paths,
            {
                "transports": ["telegram", "matrix"],
                "telegram_token": "123:ABC",
                "allowed_user_ids": [1],
                "matrix": {},
            },
        )
        with patch("controlmesh.__main__.resolve_paths", return_value=paths):
            assert _is_configured() is False

    def test_unconfigured_multi_transport_missing_telegram(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured

        paths = _make_paths(tmp_path)
        _write_config(
            paths,
            {
                "transports": ["telegram", "matrix"],
                "telegram_token": "",
                "allowed_user_ids": [],
                "matrix": {"homeserver": "https://mx.test", "user_id": "@bot:test"},
            },
        )
        with patch("controlmesh.__main__.resolve_paths", return_value=paths):
            assert _is_configured() is False


class TestStopBot:
    def test_stop_kills_running_process(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import stop_bot

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        pid_file = paths.controlmesh_home / "bot.pid"
        pid_file.write_text("12345", encoding="utf-8")
        with (
            patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths),
            patch("controlmesh.infra.pidlock._is_process_alive", return_value=True),
            patch("controlmesh.infra.pidlock._kill_and_wait") as mock_kill,
        ):
            stop_bot()
        mock_kill.assert_called_once_with(12345)

    def test_stop_no_running_instance(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import stop_bot

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        with patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths):
            stop_bot()

    def test_stop_with_docker(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import stop_bot

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        _write_config(
            paths,
            {
                "docker": {"enabled": True, "container_name": "test-container"},
                "telegram_token": "x",
                "allowed_user_ids": [1],
            },
        )
        with (
            patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths),
            patch(f"{_LIFECYCLE}.shutil.which", return_value="/usr/bin/docker"),
            patch(f"{_LIFECYCLE}.subprocess.run") as mock_run,
        ):
            stop_bot()
        docker_calls = [c for c in mock_run.call_args_list if "docker" in str(c)]
        assert len(docker_calls) >= 2


class TestUpgradeCli:
    def test_upgrade_with_pipx(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import upgrade

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        with (
            patch("controlmesh.infra.install.detect_install_mode", return_value="pipx"),
            patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths),
            patch(
                "controlmesh.infra.updater.perform_upgrade_pipeline",
                new=AsyncMock(return_value=(True, "9.9.9", "upgraded controlmesh")),
            ) as mock_pipeline,
            patch(f"{_LIFECYCLE}._re_exec_bot") as mock_exec,
            patch(f"{_LIFECYCLE}.stop_bot"),
        ):
            upgrade()
        mock_pipeline.assert_called_once()
        mock_exec.assert_called_once()

    def test_upgrade_with_pip(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import upgrade

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        with (
            patch("controlmesh.infra.install.detect_install_mode", return_value="pip"),
            patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths),
            patch(
                "controlmesh.infra.updater.perform_upgrade_pipeline",
                new=AsyncMock(return_value=(True, "9.9.9", "installed controlmesh-2.0.0")),
            ) as mock_pipeline,
            patch(f"{_LIFECYCLE}._re_exec_bot") as mock_exec,
            patch(f"{_LIFECYCLE}.stop_bot"),
        ):
            upgrade()
        mock_pipeline.assert_called_once()
        mock_exec.assert_called_once()

    def test_upgrade_version_unchanged_no_restart(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import upgrade

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        current = get_current_version()
        with (
            patch("controlmesh.infra.install.detect_install_mode", return_value="pipx"),
            patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths),
            patch(
                "controlmesh.infra.updater.perform_upgrade_pipeline",
                new=AsyncMock(return_value=(False, current, "already up to date")),
            ),
            patch(f"{_LIFECYCLE}._re_exec_bot") as mock_exec,
            patch(f"{_LIFECYCLE}.stop_bot"),
        ):
            upgrade()
        mock_exec.assert_not_called()

    def test_upgrade_fails_no_restart(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import upgrade

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        with (
            patch("controlmesh.infra.install.detect_install_mode", return_value="pip"),
            patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths),
            patch(
                "controlmesh.infra.updater.perform_upgrade_pipeline",
                new=AsyncMock(
                    return_value=(False, get_current_version(), "error: package not found")
                ),
            ),
            patch(f"{_LIFECYCLE}._re_exec_bot") as mock_exec,
            patch(f"{_LIFECYCLE}.stop_bot"),
        ):
            upgrade()
        mock_exec.assert_not_called()

    def test_upgrade_rejects_dev_mode(self) -> None:
        from controlmesh.cli_commands.lifecycle import upgrade

        with (
            patch("controlmesh.infra.install.detect_install_mode", return_value="dev"),
            patch(f"{_LIFECYCLE}.stop_bot") as mock_stop,
            patch(f"{_LIFECYCLE}._re_exec_bot") as mock_exec,
        ):
            upgrade()
        mock_stop.assert_not_called()
        mock_exec.assert_not_called()


class TestReExecBot:
    def test_re_exec_uses_popen_on_posix(self) -> None:
        from controlmesh.cli_commands.lifecycle import _re_exec_bot

        with (
            patch(f"{_LIFECYCLE}.subprocess.Popen") as mock_popen,
            pytest.raises(SystemExit) as exc_info,
        ):
            _re_exec_bot()
        mock_popen.assert_called_once_with([sys.executable, "-m", "controlmesh"])
        assert exc_info.value.code == 0

    def test_re_exec_uses_same_args_on_windows_flag(self) -> None:
        from controlmesh.cli_commands.lifecycle import _re_exec_bot

        with (
            patch(f"{_LIFECYCLE}.subprocess.Popen") as mock_popen,
            pytest.raises(SystemExit) as exc_info,
        ):
            _re_exec_bot()
        mock_popen.assert_called_once_with([sys.executable, "-m", "controlmesh"])
        assert exc_info.value.code == 0


def _mock_asyncio_run(return_value: int):
    def _side_effect(coro):
        coro.close()
        return return_value

    return _side_effect


class TestStartBotRestart:
    def _mock_config(self) -> AgentConfig:
        return AgentConfig(telegram_token="test:token", allowed_user_ids=[1])

    def test_exit42_with_supervisor_exits(self) -> None:
        from controlmesh.cli_commands.lifecycle import start_bot

        with (
            patch(f"{_LIFECYCLE}.resolve_paths"),
            patch("controlmesh.logging_config.setup_logging"),
            patch("controlmesh.__main__.load_config", return_value=self._mock_config()),
            patch(f"{_LIFECYCLE}.asyncio.run", side_effect=_mock_asyncio_run(42)),
            patch.dict("os.environ", {"CONTROLMESH_SUPERVISOR": "1"}),
            pytest.raises(SystemExit) as exc_info,
        ):
            start_bot()
        assert exc_info.value.code == 42

    def test_exit42_with_systemd_invocation_id_exits(self) -> None:
        from controlmesh.cli_commands.lifecycle import start_bot

        with (
            patch(f"{_LIFECYCLE}.resolve_paths"),
            patch("controlmesh.logging_config.setup_logging"),
            patch("controlmesh.__main__.load_config", return_value=self._mock_config()),
            patch(f"{_LIFECYCLE}.asyncio.run", side_effect=_mock_asyncio_run(42)),
            patch.dict("os.environ", {"INVOCATION_ID": "abc-123"}, clear=True),
            pytest.raises(SystemExit) as exc_info,
        ):
            start_bot()
        assert exc_info.value.code == 42

    def test_exit42_without_supervisor_re_execs(self) -> None:
        from controlmesh.cli_commands.lifecycle import start_bot

        with (
            patch(f"{_LIFECYCLE}.resolve_paths"),
            patch("controlmesh.logging_config.setup_logging"),
            patch("controlmesh.__main__.load_config", return_value=self._mock_config()),
            patch(f"{_LIFECYCLE}.asyncio.run", side_effect=_mock_asyncio_run(42)),
            patch.dict("os.environ", {}, clear=True),
            patch(f"{_LIFECYCLE}._re_exec_bot") as mock_exec,
        ):
            start_bot()
        mock_exec.assert_called_once()

    def test_exit0_does_nothing(self) -> None:
        from controlmesh.cli_commands.lifecycle import start_bot

        with (
            patch(f"{_LIFECYCLE}.resolve_paths"),
            patch("controlmesh.logging_config.setup_logging"),
            patch("controlmesh.__main__.load_config", return_value=self._mock_config()),
            patch(f"{_LIFECYCLE}.asyncio.run", side_effect=_mock_asyncio_run(0)),
            patch(f"{_LIFECYCLE}._re_exec_bot") as mock_exec,
        ):
            start_bot()
        mock_exec.assert_not_called()

    def test_nonzero_non42_exits(self) -> None:
        from controlmesh.cli_commands.lifecycle import start_bot

        with (
            patch(f"{_LIFECYCLE}.resolve_paths"),
            patch("controlmesh.logging_config.setup_logging"),
            patch("controlmesh.__main__.load_config", return_value=self._mock_config()),
            patch(f"{_LIFECYCLE}.asyncio.run", side_effect=_mock_asyncio_run(1)),
            pytest.raises(SystemExit) as exc_info,
        ):
            start_bot()
        assert exc_info.value.code == 1


class TestCountLogErrors:
    def test_counts_errors_in_log(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.status import count_log_errors

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "controlmesh.log").write_text(
            "2024-01-01 INFO Started\n2024-01-01 ERROR Something broke\n"
            "2024-01-01 INFO Continued\n2024-01-01 ERROR Another error\n",
            encoding="utf-8",
        )
        assert count_log_errors(log_dir) == 2

    def test_returns_zero_no_dir(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.status import count_log_errors

        assert count_log_errors(tmp_path / "nonexistent") == 0

    def test_returns_zero_no_log_files(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.status import count_log_errors

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        assert count_log_errors(log_dir) == 0


class TestUninstall:
    def test_uninstall_removes_workspace(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import uninstall

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        _write_config(paths, {"telegram_token": "x", "allowed_user_ids": [1]})
        with (
            patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths),
            patch("questionary.confirm") as mock_confirm,
            patch(f"{_LIFECYCLE}.stop_bot"),
            patch(f"{_LIFECYCLE}.shutil.which", return_value=None),
            patch(f"{_LIFECYCLE}.subprocess.run"),
        ):
            mock_confirm.return_value.ask.return_value = True
            uninstall()
        assert not paths.controlmesh_home.exists()

    def test_uninstall_cancelled(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.lifecycle import uninstall

        paths = _make_paths(tmp_path)
        paths.controlmesh_home.mkdir(parents=True)
        _write_config(paths, {"telegram_token": "x", "allowed_user_ids": [1]})
        with (
            patch(f"{_LIFECYCLE}.resolve_paths", return_value=paths),
            patch("questionary.confirm") as mock_confirm,
        ):
            mock_confirm.return_value.ask.return_value = False
            uninstall()
        assert paths.controlmesh_home.exists()


class TestMainDispatch:
    def test_version_short_flag(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "-v"]),
            patch("controlmesh.__main__._print_version") as mock_version,
            patch("controlmesh.__main__._default_action") as mock_default,
        ):
            main()
        mock_version.assert_called_once()
        mock_default.assert_not_called()

    def test_version_long_flag(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "--version"]),
            patch("controlmesh.__main__._print_version") as mock_version,
            patch("controlmesh.__main__._default_action") as mock_default,
        ):
            main()
        mock_version.assert_called_once()
        mock_default.assert_not_called()

    def test_help_command(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "help"]),
            patch("controlmesh.__main__._print_usage") as mock_usage,
        ):
            main()
        mock_usage.assert_called_once()

    def test_status_command(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "status"]),
            patch("controlmesh.__main__._cmd_status") as mock_status,
        ):
            main()
        mock_status.assert_called_once()

    def test_stop_command(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "stop"]),
            patch("controlmesh.__main__._stop_bot") as mock_stop,
        ):
            main()
        mock_stop.assert_called_once()

    def test_default_starts_bot_when_configured(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh"]),
            patch("controlmesh.__main__._is_configured", return_value=True),
            patch("controlmesh.__main__._start_bot") as mock_start,
        ):
            main()
        mock_start.assert_called_once_with(False)

    def test_default_runs_onboarding_when_unconfigured(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh"]),
            patch("controlmesh.__main__._is_configured", return_value=False),
            patch("controlmesh.cli.init_wizard.run_onboarding", return_value=False) as mock_onboard,
            patch("controlmesh.__main__._start_bot") as mock_start,
        ):
            main()
        mock_onboard.assert_called_once()
        mock_start.assert_called_once_with(False)

    def test_default_does_not_start_bot_when_service_installed(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh"]),
            patch("controlmesh.__main__._is_configured", return_value=False),
            patch("controlmesh.cli.init_wizard.run_onboarding", return_value=True),
            patch("controlmesh.__main__._start_bot") as mock_start,
        ):
            main()
        mock_start.assert_not_called()

    def test_verbose_flag_passed(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "--verbose"]),
            patch("controlmesh.__main__._is_configured", return_value=True),
            patch("controlmesh.__main__._start_bot") as mock_start,
        ):
            main()
        mock_start.assert_called_once_with(True)

    def test_dash_h_maps_to_help(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "-h"]),
            patch("controlmesh.__main__._print_usage") as mock_usage,
        ):
            main()
        mock_usage.assert_called_once()

    def test_upgrade_command(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "upgrade"]),
            patch("controlmesh.__main__._upgrade") as mock_upgrade,
        ):
            main()
        mock_upgrade.assert_called_once()

    def test_onboarding_command(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "onboarding"]),
            patch("controlmesh.__main__._cmd_setup") as mock_setup,
        ):
            main()
        mock_setup.assert_called_once()

    def test_reset_maps_to_setup(self) -> None:
        from controlmesh.__main__ import main

        with (
            patch("sys.argv", ["controlmesh", "reset"]),
            patch("controlmesh.__main__._cmd_setup") as mock_setup,
        ):
            main()
        mock_setup.assert_called_once()


class TestSetupCommand:
    def test_setup_starts_bot_when_service_not_installed(self) -> None:
        from controlmesh.__main__ import _cmd_setup

        with (
            patch("controlmesh.__main__._stop_bot"),
            patch("controlmesh.__main__.resolve_paths"),
            patch("controlmesh.__main__._is_configured", return_value=False),
            patch("controlmesh.cli.init_wizard.run_onboarding", return_value=False),
            patch("controlmesh.__main__._start_bot") as mock_start,
        ):
            _cmd_setup(False)
        mock_start.assert_called_once_with(False)

    def test_setup_skips_start_when_service_installed(self) -> None:
        from controlmesh.__main__ import _cmd_setup

        with (
            patch("controlmesh.__main__._stop_bot"),
            patch("controlmesh.__main__.resolve_paths"),
            patch("controlmesh.__main__._is_configured", return_value=False),
            patch("controlmesh.cli.init_wizard.run_onboarding", return_value=True),
            patch("controlmesh.__main__._start_bot") as mock_start,
        ):
            _cmd_setup(False)
        mock_start.assert_not_called()


class TestMainHelpers:
    def test_parse_service_subcommand_ignores_flags(self) -> None:
        from controlmesh.cli_commands.service import _parse_service_subcommand

        assert _parse_service_subcommand(["-v", "service", "status"]) == "status"

    def test_parse_service_subcommand_unknown_returns_none(self) -> None:
        from controlmesh.cli_commands.service import _parse_service_subcommand

        assert _parse_service_subcommand(["service", "invalid"]) is None

    def test_cmd_service_without_subcommand_prints_help(self) -> None:
        from controlmesh.cli_commands.service import cmd_service

        with patch(f"{_SERVICE}.print_service_help") as mock_help:
            cmd_service(["service"])
        mock_help.assert_called_once()

    def test_cmd_service_install_dispatches_backend(self) -> None:
        from controlmesh.cli_commands.service import cmd_service

        with patch("controlmesh.infra.service.install_service") as mock_install:
            cmd_service(["service", "install"])
        mock_install.assert_called_once()

    def test_cmd_service_status_dispatches_backend(self) -> None:
        from controlmesh.cli_commands.service import cmd_service

        with patch("controlmesh.infra.service.print_service_status") as mock_status:
            cmd_service(["service", "status"])
        mock_status.assert_called_once()

    def test_print_usage_calls_status_when_configured(self) -> None:
        from controlmesh.cli_commands.status import print_usage

        with (
            patch("controlmesh.__main__._is_configured", return_value=True),
            patch(f"{_STATUS}.print_status") as mock_status,
        ):
            print_usage()
        mock_status.assert_called_once()

    def test_print_usage_shows_not_configured_panel(self) -> None:
        from controlmesh.cli_commands.status import print_usage

        with patch("controlmesh.__main__._is_configured", return_value=False):
            print_usage()

    def test_cmd_status_prints_not_configured(self) -> None:
        from controlmesh.__main__ import _cmd_status

        with patch("controlmesh.__main__._is_configured", return_value=False):
            _cmd_status()

    def test_cmd_restart_stops_and_reexecs(self) -> None:
        from controlmesh.cli_commands.lifecycle import cmd_restart

        with (
            patch(f"{_LIFECYCLE}.stop_bot") as mock_stop,
            patch(f"{_LIFECYCLE}._re_exec_bot", side_effect=SystemExit),
            pytest.raises(SystemExit),
        ):
            cmd_restart()
        mock_stop.assert_called_once()

    def test_default_action_configured_starts(self) -> None:
        from controlmesh.__main__ import _default_action

        with (
            patch("controlmesh.__main__._is_configured", return_value=True),
            patch("controlmesh.__main__._start_bot") as mock_start,
        ):
            _default_action(verbose=True)
        mock_start.assert_called_once_with(True)

    def test_default_action_onboarding_service_installed_skips_start(self) -> None:
        from controlmesh.__main__ import _default_action

        with (
            patch("controlmesh.__main__._is_configured", return_value=False),
            patch("controlmesh.cli.init_wizard.run_onboarding", return_value=True),
            patch("controlmesh.__main__._start_bot") as mock_start,
        ):
            _default_action(verbose=False)
        mock_start.assert_not_called()
