"""Tests for Windows Task Scheduler service management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from controlmesh.infra.service_windows import (
    _TASK_NAME,
    _generate_task_xml,
    _is_access_denied,
    install_service,
    is_service_installed,
    is_service_running,
    print_service_logs,
    print_service_status,
    start_service,
    stop_service,
    uninstall_service,
)
from tests.infra.conftest import make_completed


class TestGenerateTaskXml:
    def test_contains_command(self) -> None:
        xml = _generate_task_xml(r"C:\Python\pythonw.exe", "-m controlmesh")
        assert r"C:\Python\pythonw.exe" in xml

    def test_contains_arguments(self) -> None:
        xml = _generate_task_xml(r"C:\Python\pythonw.exe", "-m controlmesh")
        assert "-m controlmesh" in xml

    def test_no_arguments_element_when_empty(self) -> None:
        xml = _generate_task_xml(r"C:\Users\test\.local\bin\controlmesh.exe")
        assert "<Arguments>" not in xml

    def test_contains_logon_trigger(self) -> None:
        xml = _generate_task_xml("controlmesh")
        assert "LogonTrigger" in xml

    def test_delay_is_10_seconds(self) -> None:
        xml = _generate_task_xml("controlmesh")
        assert "PT10S" in xml

    def test_contains_restart_on_failure(self) -> None:
        xml = _generate_task_xml("controlmesh")
        assert "RestartOnFailure" in xml

    def test_valid_xml_declaration_and_root(self) -> None:
        xml = _generate_task_xml("controlmesh")
        assert xml.startswith('<?xml version="1.0" encoding="UTF-16"?>')
        assert "<Task " in xml
        assert "</Task>" in xml


class TestIsAccessDenied:
    def test_english_access_denied(self) -> None:
        result = make_completed(1, stderr="ERROR: Access is denied.")
        assert _is_access_denied(result) is True

    def test_german_zugriff_verweigert(self) -> None:
        result = make_completed(1, stderr="FEHLER: Zugriff verweigert.")
        assert _is_access_denied(result) is True

    def test_german_zugriff_wurde_verweigert(self) -> None:
        result = make_completed(1, stderr="FEHLER: Der Zugriff wurde verweigert.")
        assert _is_access_denied(result) is True

    def test_other_error(self) -> None:
        result = make_completed(1, stderr="ERROR: The system cannot find the file.")
        assert _is_access_denied(result) is False

    def test_access_denied_in_stdout(self) -> None:
        result = make_completed(1, stdout="Access is denied", stderr="")
        assert _is_access_denied(result) is True


class TestIsServiceInstalled:
    @patch("controlmesh.infra.service_windows._run_schtasks")
    def test_installed_when_query_succeeds(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0, stdout="TaskName: controlmesh")
        assert is_service_installed() is True
        mock_run.assert_called_once_with("/Query", "/TN", _TASK_NAME, "/FO", "LIST")

    @patch("controlmesh.infra.service_windows._run_schtasks")
    def test_not_installed_when_query_fails(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(1, stderr="not found")
        assert is_service_installed() is False


class TestIsServiceRunning:
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=False)
    def test_not_running_when_not_installed(self, _mock: MagicMock) -> None:
        assert is_service_running() is False

    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=True)
    def test_running_when_status_contains_running(
        self, _installed: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = make_completed(0, stdout='"controlmesh","Running","Interactive"')
        assert is_service_running() is True

    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=True)
    def test_not_running_when_status_says_ready(
        self, _installed: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = make_completed(0, stdout='"controlmesh","Ready","Interactive"')
        assert is_service_running() is False


class TestInstallService:
    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=False)
    @patch("controlmesh.infra.service_windows.is_service_available", return_value=True)
    @patch(
        "controlmesh.infra.service_windows._find_pythonw",
        return_value=r"C:\Python\pythonw.exe",
    )
    @patch("controlmesh.infra.service_windows._task_xml_path")
    def test_install_with_pythonw(
        self,
        mock_xml_path: MagicMock,
        _pythonw: MagicMock,
        _avail: MagicMock,
        _installed: MagicMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        xml_file = tmp_path / "task.xml"
        mock_xml_path.return_value = xml_file
        mock_run.return_value = make_completed(0)

        console = MagicMock()
        assert install_service(console) is True
        assert mock_run.call_count >= 2  # Create + Run

    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=False)
    @patch("controlmesh.infra.service_windows.is_service_available", return_value=True)
    @patch("controlmesh.infra.service_windows._find_pythonw", return_value=None)
    @patch("controlmesh.infra.service_windows.find_controlmesh_binary", return_value="controlmesh.exe")
    @patch("controlmesh.infra.service_windows._task_xml_path")
    def test_install_fallback_to_binary(
        self,
        mock_xml_path: MagicMock,
        _binary: MagicMock,
        _pythonw: MagicMock,
        _avail: MagicMock,
        _installed: MagicMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        xml_file = tmp_path / "task.xml"
        mock_xml_path.return_value = xml_file
        mock_run.return_value = make_completed(0)

        console = MagicMock()
        assert install_service(console) is True

    @patch("controlmesh.infra.service_windows.is_service_available", return_value=False)
    def test_install_fails_on_non_windows(self, _avail: MagicMock) -> None:
        console = MagicMock()
        assert install_service(console) is False

    @patch("controlmesh.infra.service_windows.is_service_available", return_value=True)
    @patch("controlmesh.infra.service_windows._find_pythonw", return_value=None)
    @patch("controlmesh.infra.service_windows.find_controlmesh_binary", return_value=None)
    def test_install_fails_without_binary(
        self, _binary: MagicMock, _pythonw: MagicMock, _avail: MagicMock
    ) -> None:
        console = MagicMock()
        assert install_service(console) is False

    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=False)
    @patch("controlmesh.infra.service_windows.is_service_available", return_value=True)
    @patch(
        "controlmesh.infra.service_windows._find_pythonw",
        return_value=r"C:\Python\pythonw.exe",
    )
    @patch("controlmesh.infra.service_windows._task_xml_path")
    def test_install_shows_admin_hint_on_access_denied(
        self,
        mock_xml_path: MagicMock,
        _pythonw: MagicMock,
        _avail: MagicMock,
        _installed: MagicMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        xml_file = tmp_path / "task.xml"
        mock_xml_path.return_value = xml_file
        mock_run.return_value = make_completed(1, stderr="ERROR: Access is denied.")

        console = MagicMock()
        assert install_service(console) is False
        # Should have printed the admin hint panel
        assert console.print.called


class TestUninstallService:
    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=True)
    def test_uninstall_success(self, _installed: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0)
        console = MagicMock()
        assert uninstall_service(console) is True
        assert mock_run.call_count == 2  # End + Delete

    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=False)
    def test_uninstall_when_not_installed(self, _installed: MagicMock) -> None:
        console = MagicMock()
        assert uninstall_service(console) is False

    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=True)
    def test_uninstall_shows_admin_hint_on_access_denied(
        self, _installed: MagicMock, mock_run: MagicMock
    ) -> None:
        end_result = make_completed(0)
        delete_result = make_completed(1, stderr="ERROR: Access is denied.")
        mock_run.side_effect = [end_result, delete_result]
        console = MagicMock()
        assert uninstall_service(console) is False
        assert console.print.called


class TestStartService:
    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=True)
    def test_start_success(self, _installed: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0)
        console = MagicMock()
        start_service(console)
        mock_run.assert_called_once_with("/Run", "/TN", _TASK_NAME)

    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=False)
    def test_start_not_installed(self, _installed: MagicMock) -> None:
        console = MagicMock()
        start_service(console)
        console.print.assert_called_once()


class TestStopService:
    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_running", return_value=True)
    def test_stop_success(self, _running: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0)
        console = MagicMock()
        stop_service(console)
        mock_run.assert_called_once_with("/End", "/TN", _TASK_NAME)

    @patch("controlmesh.infra.service_windows.is_service_running", return_value=False)
    def test_stop_not_running(self, _running: MagicMock) -> None:
        console = MagicMock()
        stop_service(console)
        console.print.assert_called_once()


class TestPrintServiceStatus:
    @patch("controlmesh.infra.service_windows._run_schtasks")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=True)
    def test_prints_status(self, _installed: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = make_completed(0, stdout="Task details here")
        console = MagicMock()
        print_service_status(console)
        console.print.assert_called_with("Task details here")


class TestPrintServiceLogs:
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=False)
    def test_not_installed(self, _installed: MagicMock) -> None:
        console = MagicMock()
        print_service_logs(console)
        console.print.assert_called_once()

    @patch("controlmesh.infra.service_windows.resolve_paths")
    @patch("controlmesh.infra.service_windows.is_service_installed", return_value=True)
    def test_shows_logs_from_file(
        self, _installed: MagicMock, mock_paths: MagicMock, tmp_path: Path
    ) -> None:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        log_file = logs_dir / "controlmesh_2026-02-21.log"
        log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        paths_obj = MagicMock()
        paths_obj.logs_dir = logs_dir
        mock_paths.return_value = paths_obj

        console = MagicMock()
        print_service_logs(console)
        # Should have printed header, 3 log lines, and footer = 5 calls
        assert console.print.call_count == 5
