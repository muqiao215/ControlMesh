"""Tests for Linux systemd service management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from controlmesh.infra.service_linux import (
    _SERVICE_NAME,
    _generate_service_unit,
    is_service_available,
    is_service_running,
    print_service_logs,
    print_service_status,
    start_service,
    stop_service,
    uninstall_service,
)
from tests.infra.conftest import make_completed


class TestGenerateServiceUnit:
    def test_contains_binary_path(self) -> None:
        unit = _generate_service_unit("/usr/local/bin/controlmesh")
        assert "ExecStart=/usr/local/bin/controlmesh" in unit

    def test_has_restart_policy(self) -> None:
        unit = _generate_service_unit("controlmesh")
        assert "Restart=on-failure" in unit

    def test_has_service_section(self) -> None:
        unit = _generate_service_unit("controlmesh")
        assert "[Service]" in unit
        assert "[Unit]" in unit
        assert "[Install]" in unit

    def test_does_not_install_legacy_alias(self) -> None:
        unit = _generate_service_unit("controlmesh")
        assert "Alias=" not in unit

    def test_includes_all_nvm_bins(self, tmp_path: Path) -> None:
        (tmp_path / ".nvm" / "versions" / "node" / "v24.0.0" / "bin").mkdir(parents=True)
        (tmp_path / ".nvm" / "versions" / "node" / "v22.0.0" / "bin").mkdir(parents=True)

        with patch("controlmesh.infra.service_linux.Path.home", return_value=tmp_path):
            unit = _generate_service_unit("controlmesh")

        assert f"{tmp_path}/.nvm/versions/node/v24.0.0/bin" in unit
        assert f"{tmp_path}/.nvm/versions/node/v22.0.0/bin" in unit


class TestIsServiceAvailable:
    @patch("controlmesh.infra.service_linux.shutil.which", return_value="/usr/bin/systemctl")
    def test_available_with_systemctl(self, _mock: MagicMock) -> None:
        assert is_service_available() is True

    @patch("controlmesh.infra.service_linux.shutil.which", return_value=None)
    def test_unavailable_without_systemctl(self, _mock: MagicMock) -> None:
        assert is_service_available() is False


class TestIsServiceRunning:
    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux.is_service_installed", return_value=True)
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=True)
    def test_running(self, _sys: MagicMock, _inst: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0, stdout="active")
        assert is_service_running() is True

    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux.is_service_installed", return_value=True)
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=True)
    def test_not_running(self, _sys: MagicMock, _inst: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0, stdout="inactive")
        assert is_service_running() is False


class TestStartService:
    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=False)
    def test_start_without_systemd(self, _has: MagicMock, mock_run: MagicMock) -> None:
        console = MagicMock()
        start_service(console)
        mock_run.assert_not_called()
        console.print.assert_called_with("[dim]systemd not available.[/dim]")

    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux.is_service_installed", return_value=False)
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=True)
    def test_start_not_installed(
        self,
        _has: MagicMock,
        _installed: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        console = MagicMock()
        start_service(console)
        mock_run.assert_not_called()
        console.print.assert_called_with(
            "[dim]Service not installed. Run [bold]controlmesh service install[/bold].[/dim]"
        )

    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux.is_service_installed", return_value=True)
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=True)
    def test_start_success(
        self,
        _has: MagicMock,
        _installed: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        mock_run.return_value = make_completed(0)
        console = MagicMock()
        start_service(console)
        mock_run.assert_called_once_with("start", _SERVICE_NAME)


class TestStopService:
    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux.is_service_running", return_value=True)
    def test_stop_success(self, _running: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0)
        console = MagicMock()
        stop_service(console)
        mock_run.assert_called_once_with("stop", _SERVICE_NAME)


class TestUninstallService:
    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=False)
    def test_uninstall_without_systemd(self, _has: MagicMock, mock_run: MagicMock) -> None:
        console = MagicMock()
        assert uninstall_service(console) is False
        mock_run.assert_not_called()
        console.print.assert_called_with("[dim]systemd not available.[/dim]")

    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux._service_path")
    @patch("controlmesh.infra.service_linux.is_service_installed", return_value=True)
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=True)
    def test_uninstall(
        self,
        _has: MagicMock,
        _inst: MagicMock,
        mock_path: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        mock_path.return_value = MagicMock()
        mock_run.return_value = make_completed(0)
        console = MagicMock()
        assert uninstall_service(console) is True

    @patch("controlmesh.infra.service_linux.is_service_installed", return_value=False)
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=True)
    def test_uninstall_not_installed(self, _has: MagicMock, _inst: MagicMock) -> None:
        console = MagicMock()
        assert uninstall_service(console) is False


class TestPrintServiceStatus:
    @patch("controlmesh.infra.service_linux._run_systemctl")
    @patch("controlmesh.infra.service_linux.is_service_installed", return_value=True)
    @patch("controlmesh.infra.service_linux._has_systemd", return_value=True)
    def test_prints_status(self, _sys: MagicMock, _inst: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0, stdout="active running")
        console = MagicMock()
        print_service_status(console)
        console.print.assert_called_with("active running")


class TestPrintServiceLogs:
    @patch("controlmesh.infra.service_linux.resolve_paths")
    @patch("controlmesh.infra.service_linux.print_journal_service_logs")
    @patch("controlmesh.infra.service_linux.is_service_installed", return_value=True)
    def test_passes_logs_dir_for_fallback(
        self,
        _installed: MagicMock,
        mock_print_logs: MagicMock,
        mock_paths: MagicMock,
        tmp_path: Path,
    ) -> None:
        paths_obj = MagicMock()
        paths_obj.logs_dir = tmp_path / "logs"
        mock_paths.return_value = paths_obj

        console = MagicMock()
        print_service_logs(console)

        mock_print_logs.assert_called_once_with(
            console,
            installed=True,
            service_name=_SERVICE_NAME,
            fallback_logs_dir=paths_obj.logs_dir,
        )
