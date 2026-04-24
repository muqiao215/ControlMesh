"""Tests for install mode detection."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from controlmesh.infra.install import detect_install_info, detect_install_mode, is_upgradeable


class TestDetectInstallMode:
    """Test runtime installation method detection."""

    def test_pipx_detected_from_sys_prefix(self) -> None:
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = None

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/home/user/.local/share/pipx/venvs/controlmesh"
            assert detect_install_mode() == "pipx"

    def test_editable_install_detected_as_dev(self) -> None:
        direct_url = json.dumps({"dir_info": {"editable": True}, "url": "file:///src"})
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = direct_url

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/home/user/venv"
            assert detect_install_mode() == "dev"

    def test_editable_install_keeps_local_source_path(self) -> None:
        direct_url = json.dumps({"dir_info": {"editable": True}, "url": "file:///src/project"})
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = direct_url

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/home/user/venv"
            info = detect_install_info()

        assert info.mode == "dev"
        assert info.source == "dev"
        assert info.url == "file:///src/project"
        assert info.local_path == "/src/project"

    def test_pip_install_from_pypi(self) -> None:
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = None  # No direct_url.json

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/home/user/venv"
            assert detect_install_mode() == "pip"

    def test_package_not_found_is_dev(self) -> None:
        from importlib.metadata import PackageNotFoundError

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch(
                "controlmesh.infra.install.distribution",
                side_effect=PackageNotFoundError("controlmesh"),
            ),
        ):
            mock_sys.prefix = "/usr"
            assert detect_install_mode() == "dev"

    def test_metadata_error_falls_back_to_dev(self) -> None:
        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", side_effect=OSError("corrupt")),
        ):
            mock_sys.prefix = "/usr"
            assert detect_install_mode() == "dev"

    def test_pipx_path_variant_windows(self) -> None:
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = None

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "C:\\Users\\me\\AppData\\Local\\pipx\\venvs\\controlmesh"
            assert detect_install_mode() == "pipx"

    def test_non_editable_direct_url_is_pip(self) -> None:
        direct_url = json.dumps({"dir_info": {"editable": False}, "url": "file:///src"})
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = direct_url

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/home/user/venv"
            assert detect_install_mode() == "pip"


class TestDetectInstallInfo:
    """Test installation source detection details."""

    def test_github_vcs_install_detected(self) -> None:
        direct_url = json.dumps(
            {
                "url": "https://github.com/muqiao215/ControlMesh.git",
                "vcs_info": {
                    "vcs": "git",
                    "requested_revision": "main",
                    "commit_id": "abc123",
                },
            }
        )
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = direct_url

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/home/user/venv"
            info = detect_install_info()

        assert info.mode == "pip"
        assert info.source == "github"
        assert info.url == "https://github.com/muqiao215/ControlMesh.git"
        assert info.vcs == "git"
        assert info.requested_revision == "main"
        assert info.commit_id == "abc123"

    def test_pipx_github_install_keeps_pipx_mode(self) -> None:
        direct_url = json.dumps(
            {
                "url": "https://github.com/muqiao215/ControlMesh.git",
                "vcs_info": {
                    "vcs": "git",
                    "requested_revision": "v0.15.0",
                    "commit_id": "abc123",
                },
            }
        )
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = direct_url

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/home/user/.local/share/pipx/venvs/controlmesh"
            info = detect_install_info()

        assert info.mode == "pipx"
        assert info.source == "github"
        assert info.requested_revision == "v0.15.0"


class TestIsUpgradeable:
    """Test upgrade eligibility helper."""

    def test_pipx_is_upgradeable(self) -> None:
        with patch("controlmesh.infra.install.detect_install_mode", return_value="pipx"):
            assert is_upgradeable() is True

    def test_pip_is_upgradeable(self) -> None:
        with patch("controlmesh.infra.install.detect_install_mode", return_value="pip"):
            assert is_upgradeable() is True

    def test_dev_is_not_upgradeable(self) -> None:
        with patch("controlmesh.infra.install.detect_install_mode", return_value="dev"):
            assert is_upgradeable() is False
