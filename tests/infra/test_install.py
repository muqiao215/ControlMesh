"""Tests for install mode detection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from controlmesh.infra.install import (
    InstallInfo,
    detect_install_info,
    detect_install_mode,
    detect_runtime_provenance,
    is_upgradeable,
)


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

    def test_uv_tool_detected_from_sys_prefix(self) -> None:
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = None

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/root/.local/share/uv/tools/controlmesh"
            assert detect_install_mode() == "uv_tool"

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

    def test_uv_tool_pypi_install_keeps_uv_tool_mode(self) -> None:
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = None

        with (
            patch("controlmesh.infra.install.sys") as mock_sys,
            patch("controlmesh.infra.install.distribution", return_value=mock_dist),
        ):
            mock_sys.prefix = "/root/.local/share/uv/tools/controlmesh"
            info = detect_install_info()

        assert info.mode == "uv_tool"
        assert info.source == "pypi"


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


class TestRuntimeProvenance:
    def test_packaged_install_matches_expected_runtime_root(self) -> None:
        info = InstallInfo(mode="pipx", source="pypi")
        fake_module_file = "/root/.local/share/uv/tools/controlmesh/lib/python3.12/site-packages/controlmesh/__init__.py"

        with (
            patch("controlmesh.infra.install.detect_install_info", return_value=info),
            patch(
                "controlmesh.infra.install._installed_distribution_root",
                return_value=Path("/root/.local/share/uv/tools/controlmesh/lib/python3.12/site-packages"),
            ),
            patch("controlmesh.infra.install.controlmesh.__file__", fake_module_file),
            patch("controlmesh.infra.install.controlmesh.__version__", "0.24.18"),
            patch("controlmesh.infra.install.sys.executable", "/usr/bin/python3.12"),
            patch("controlmesh.infra.install.sys.prefix", "/root/.local/share/uv/tools/controlmesh"),
            patch("controlmesh.infra.install.Path.cwd", return_value=Path("/root")),
            patch("controlmesh.infra.install.os.environ", {"PYTHONPATH": ""}),
            patch("controlmesh.infra.version.importlib.metadata.version", return_value="0.24.18"),
        ):
            provenance = detect_runtime_provenance()

        assert provenance.matches_expected is True
        assert provenance.path_matches_expected is True
        assert provenance.version_matches_expected is True
        assert provenance.imported_version == "0.24.18"

    def test_packaged_install_detects_source_tree_drift(self) -> None:
        info = InstallInfo(mode="pipx", source="pypi")

        with (
            patch("controlmesh.infra.install.detect_install_info", return_value=info),
            patch(
                "controlmesh.infra.install._installed_distribution_root",
                return_value=Path("/root/.local/share/uv/tools/controlmesh/lib/python3.12/site-packages"),
            ),
            patch("controlmesh.infra.install.controlmesh.__file__", "/root/ControlMesh/controlmesh/__init__.py"),
            patch("controlmesh.infra.install.controlmesh.__version__", "0.23.5"),
            patch("controlmesh.infra.install.sys.executable", "/usr/bin/python3.12"),
            patch("controlmesh.infra.install.sys.prefix", "/root/.local/share/uv/tools/controlmesh"),
            patch("controlmesh.infra.install.Path.cwd", return_value=Path("/root/ControlMesh")),
            patch("controlmesh.infra.install.os.environ", {"PYTHONPATH": "/root/ControlMesh"}),
            patch("controlmesh.infra.version.importlib.metadata.version", return_value="0.24.15"),
        ):
            provenance = detect_runtime_provenance()

        assert provenance.matches_expected is False
        assert provenance.path_matches_expected is False
        assert provenance.version_matches_expected is False
        assert "outside expected runtime root" in provenance.reason
        assert "does not match installed package version" in provenance.reason

    def test_packaged_install_tracks_version_mismatch_separately(self) -> None:
        info = InstallInfo(mode="uv_tool", source="pypi")
        fake_module_file = (
            "/root/.local/share/uv/tools/controlmesh/lib/python3.12/site-packages/controlmesh/__init__.py"
        )

        with (
            patch("controlmesh.infra.install.detect_install_info", return_value=info),
            patch(
                "controlmesh.infra.install._installed_distribution_root",
                return_value=Path("/root/.local/share/uv/tools/controlmesh/lib/python3.12/site-packages"),
            ),
            patch("controlmesh.infra.install.controlmesh.__file__", fake_module_file),
            patch("controlmesh.infra.install.controlmesh.__version__", "0.31.3"),
            patch("controlmesh.infra.install.sys.executable", "/usr/bin/python3.12"),
            patch("controlmesh.infra.install.sys.prefix", "/root/.local/share/uv/tools/controlmesh"),
            patch("controlmesh.infra.install.Path.cwd", return_value=Path("/root")),
            patch("controlmesh.infra.install.os.environ", {"PYTHONPATH": ""}),
            patch("controlmesh.infra.version.importlib.metadata.version", return_value="0.34.7"),
        ):
            provenance = detect_runtime_provenance()

        assert provenance.matches_expected is False
        assert provenance.path_matches_expected is True
        assert provenance.version_matches_expected is False
        assert "does not match installed package version" in provenance.reason
