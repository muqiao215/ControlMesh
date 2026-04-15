"""Tests for cross-platform boot ID detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from controlmesh.infra.boot_id import get_boot_id


class TestGetBootIdLinux:
    @patch("controlmesh.infra.boot_id.sys")
    def test_reads_proc_boot_id(self, mock_sys: MagicMock, tmp_path: Path) -> None:
        mock_sys.platform = "linux"
        boot_file = tmp_path / "boot_id"
        boot_file.write_text("abc-123-def\n")
        with patch("controlmesh.infra.boot_id._LINUX_BOOT_ID_PATH", boot_file):
            result = get_boot_id()
        assert result == "abc-123-def"

    @patch("controlmesh.infra.boot_id.sys")
    def test_missing_proc_file_returns_empty(self, mock_sys: MagicMock) -> None:
        mock_sys.platform = "linux"
        with patch("controlmesh.infra.boot_id._LINUX_BOOT_ID_PATH", Path("/nonexistent/boot_id")):
            result = get_boot_id()
        assert result == ""


class TestGetBootIdMacOS:
    @patch("controlmesh.infra.boot_id.sys")
    @patch("controlmesh.infra.boot_id.subprocess")
    def test_reads_sysctl(self, mock_sp: MagicMock, mock_sys: MagicMock) -> None:
        mock_sys.platform = "darwin"
        mock_sp.run.return_value = MagicMock(
            returncode=0,
            stdout="DEADBEEF-1234-5678\n",
        )
        result = get_boot_id()
        assert result == "DEADBEEF-1234-5678"
        mock_sp.run.assert_called_once()

    @patch("controlmesh.infra.boot_id.sys")
    @patch("controlmesh.infra.boot_id.subprocess")
    def test_sysctl_failure_returns_empty(self, mock_sp: MagicMock, mock_sys: MagicMock) -> None:
        mock_sys.platform = "darwin"
        mock_sp.run.side_effect = OSError("command not found")
        result = get_boot_id()
        assert result == ""


class TestGetBootIdWindows:
    @patch("controlmesh.infra.boot_id.sys")
    def test_uses_uptime(self, mock_sys: MagicMock) -> None:
        mock_sys.platform = "win32"
        with patch("controlmesh.infra.boot_id._windows_boot_id", return_value="win-12345"):
            result = get_boot_id()
        assert result == "win-12345"

    @patch("controlmesh.infra.boot_id.sys")
    def test_windows_failure_returns_empty(self, mock_sys: MagicMock) -> None:
        mock_sys.platform = "win32"
        with patch("controlmesh.infra.boot_id._windows_boot_id", return_value=""):
            result = get_boot_id()
        assert result == ""


class TestGetBootIdUnknownPlatform:
    @patch("controlmesh.infra.boot_id.sys")
    def test_unknown_platform_returns_empty(self, mock_sys: MagicMock) -> None:
        mock_sys.platform = "freebsd"
        result = get_boot_id()
        assert result == ""


class TestBootIdConsistency:
    def test_returns_string(self) -> None:
        result = get_boot_id()
        assert isinstance(result, str)
