"""Tests for update observer, upgrade execution, and sentinel lifecycle."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from controlmesh.infra.install import InstallInfo
from controlmesh.infra.updater import (
    InstalledState,
    UpdateObserver,
    _build_package_spec,
    _build_upgrade_command,
    consume_upgrade_sentinel,
    ensure_update_observer_started,
    perform_upgrade_pipeline,
    resolve_upgrade_target,
    write_upgrade_sentinel,
)
from controlmesh.infra.version import VersionInfo

# ---------------------------------------------------------------------------
# Upgrade Sentinel
# ---------------------------------------------------------------------------


class TestUpgradeSentinel:
    """Test sentinel write/read/delete lifecycle."""

    def test_write_and_consume(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(tmp_path, chat_id=42, old_version="1.0.0", new_version="2.0.0")
        sentinel_file = tmp_path / "upgrade-sentinel.json"
        assert sentinel_file.exists()

        data = consume_upgrade_sentinel(tmp_path)
        assert data is not None
        assert data["chat_id"] == 42
        assert data["old_version"] == "1.0.0"
        assert data["new_version"] == "2.0.0"

        # File should be deleted after consumption
        assert not sentinel_file.exists()

    def test_consume_returns_none_when_absent(self, tmp_path: Path) -> None:
        assert consume_upgrade_sentinel(tmp_path) is None

    def test_consume_deletes_corrupt_file(self, tmp_path: Path) -> None:
        sentinel = tmp_path / "upgrade-sentinel.json"
        sentinel.write_text("not valid json{{{", encoding="utf-8")

        result = consume_upgrade_sentinel(tmp_path)
        assert result is None
        assert not sentinel.exists()

    def test_write_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "dir"
        write_upgrade_sentinel(nested, chat_id=1, old_version="0.1", new_version="0.2")
        assert (nested / "upgrade-sentinel.json").exists()

    def test_double_consume_returns_none(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(tmp_path, chat_id=1, old_version="1.0", new_version="2.0")
        first = consume_upgrade_sentinel(tmp_path)
        second = consume_upgrade_sentinel(tmp_path)
        assert first is not None
        assert second is None

    def test_sentinel_content_is_valid_json(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(tmp_path, chat_id=99, old_version="1.0.0", new_version="1.1.0")
        raw = (tmp_path / "upgrade-sentinel.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data == {"chat_id": 99, "old_version": "1.0.0", "new_version": "1.1.0"}

    def test_transport_mismatch_does_not_consume(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(
            tmp_path,
            chat_id=99,
            old_version="1.0.0",
            new_version="1.1.0",
            transport="feishu",
        )

        assert consume_upgrade_sentinel(tmp_path, transport="telegram") is None
        assert (tmp_path / "upgrade-sentinel.json").exists()

        data = consume_upgrade_sentinel(tmp_path, transport="feishu")
        assert data is not None
        assert data["transport"] == "feishu"


class TestPerformUpgradePipeline:
    """Test upgrade pipeline behavior (verification + retry)."""

    async def test_changes_on_first_attempt(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(matches_expected=True, reason=""),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python"),
            ),
            patch(
                "controlmesh.infra.updater._inspect_runtime_after_upgrade",
                new=AsyncMock(
                    return_value=("2.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python")
                ),
            ),
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(return_value=(True, "first-pass")),
            ) as mock_upgrade,
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(mode="pipx", source="pypi"),
            ),
            patch(
                "controlmesh.infra.updater._wait_for_install_change",
                new=AsyncMock(return_value=InstalledState(version="2.0.0")),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is True
        assert version == "2.0.0"
        assert "first-pass" in output
        assert "requested_version=latest" in output
        assert "resolved_target_version=none" in output
        mock_upgrade.assert_called_once_with(target_version=None, force_reinstall=False)

    async def test_retries_with_target_when_unchanged(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(matches_expected=True, reason=""),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python"),
            ),
            patch(
                "controlmesh.infra.updater._inspect_runtime_after_upgrade",
                new=AsyncMock(
                    return_value=("2.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python")
                ),
            ),
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(side_effect=[(True, "first-pass"), (True, "retry-pass")]),
            ) as mock_upgrade,
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(mode="pip", source="pypi"),
            ),
            patch(
                "controlmesh.infra.updater._wait_for_install_change",
                new=AsyncMock(
                    side_effect=[
                        InstalledState(version="1.0.0"),
                        InstalledState(version="2.0.0"),
                    ]
                ),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(
                current_version="1.0.0",
                target_version="2.0.0",
            )

        assert changed is True
        assert version == "2.0.0"
        assert "first-pass" in output
        assert "retry-pass" in output
        assert "requested_version=2.0.0" in output
        assert "resolved_target_version=2.0.0" in output
        assert mock_upgrade.call_count == 2
        assert mock_upgrade.call_args_list[0].kwargs == {
            "target_version": "2.0.0",
            "force_reinstall": False,
        }
        assert mock_upgrade.call_args_list[1].kwargs == {
            "target_version": "2.0.0",
            "force_reinstall": True,
        }

    async def test_returns_unchanged_when_no_target_version_is_frozen(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(matches_expected=True, reason=""),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python"),
            ),
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(return_value=(True, "first-pass")),
            ),
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(mode="pip", source="pypi"),
            ),
            patch(
                "controlmesh.infra.updater._wait_for_install_change",
                new=AsyncMock(return_value=InstalledState(version="1.0.0")),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is False
        assert version == "1.0.0"
        assert "first-pass" in output
        assert "resolved_target_version=none" in output

    async def test_refuses_upgrade_when_runtime_import_is_polluted(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(mode="uv_tool", source="pypi"),
            ),
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(
                    matches_expected=False,
                    reason="imported module is outside expected runtime root",
                ),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("0.24.33", "/root/ControlMesh/controlmesh/__init__.py", "/usr/bin/python3"),
            ),
            patch("controlmesh.infra.updater._perform_upgrade_impl", new=AsyncMock()) as mock_upgrade,
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="0.24.33")

        assert changed is False
        assert version == "0.24.33"
        assert "Refusing upgrade: current runtime import path is polluted." in output
        assert "requested_version=latest" in output
        assert "resolved_target_version=none" in output
        assert "/root/ControlMesh/controlmesh/__init__.py" in output
        mock_upgrade.assert_not_called()

    async def test_missing_distribution_reports_broken_publish_when_github_release_exists(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(matches_expected=True, reason=""),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python"),
            ),
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(return_value=(False, "ERROR: No matching distribution found for controlmesh==2.0.0")),
            ),
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(mode="pip", source="pypi"),
            ),
            patch(
                "controlmesh.infra.updater._wait_for_install_change",
                new=AsyncMock(return_value=InstalledState(version="1.0.0")),
            ),
            patch("controlmesh.infra.updater.check_pypi", new=AsyncMock(return_value=None)),
            patch(
                "controlmesh.infra.updater.check_github_release",
                new=AsyncMock(
                    return_value=VersionInfo(
                        current="1.0.0",
                        latest="2.0.0",
                        update_available=True,
                        summary="GitHub release",
                        source="github",
                    )
                ),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is False
        assert version == "1.0.0"
        assert "GitHub already shows release 2.0.0" in output

    async def test_github_branch_change_detected_by_commit_id(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(matches_expected=True, reason=""),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python"),
            ),
            patch(
                "controlmesh.infra.updater._inspect_runtime_after_upgrade",
                new=AsyncMock(
                    return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python")
                ),
            ),
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(
                    mode="pipx",
                    source="github",
                    url="https://github.com/muqiao215/ControlMesh.git",
                    vcs="git",
                    requested_revision="main",
                    commit_id="old123",
                ),
            ),
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(return_value=(True, "first-pass")),
            ),
            patch(
                "controlmesh.infra.updater._wait_for_install_change",
                new=AsyncMock(return_value=InstalledState(version="1.0.0", commit_id="new456")),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is True
        assert version == "1.0.0"
        assert "first-pass" in output

    async def test_github_retry_preserves_branch_target(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(matches_expected=True, reason=""),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python"),
            ),
            patch(
                "controlmesh.infra.updater._inspect_runtime_after_upgrade",
                new=AsyncMock(
                    return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python")
                ),
            ),
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(
                    mode="pipx",
                    source="github",
                    url="https://github.com/muqiao215/ControlMesh.git",
                    vcs="git",
                    requested_revision="main",
                    commit_id="old123",
                ),
            ),
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(side_effect=[(True, "first-pass"), (True, "retry-pass")]),
            ) as mock_upgrade,
            patch(
                "controlmesh.infra.updater._wait_for_install_change",
                new=AsyncMock(
                    side_effect=[
                        InstalledState(version="1.0.0", commit_id="old123"),
                        InstalledState(version="1.0.0", commit_id="new456"),
                    ]
                ),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(
                current_version="1.0.0",
                target_version="2.0.0",
            )

        assert changed is True
        assert version == "1.0.0"
        assert "retry-pass" in output
        assert mock_upgrade.call_args_list[0].kwargs == {
            "target_version": "2.0.0",
            "force_reinstall": False,
        }
        assert mock_upgrade.call_args_list[1].kwargs == {
            "target_version": "2.0.0",
            "force_reinstall": True,
        }

    async def test_github_retry_does_not_run_without_frozen_target(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(matches_expected=True, reason=""),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python"),
            ),
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(
                    mode="pipx",
                    source="github",
                    url="https://github.com/muqiao215/ControlMesh.git",
                    vcs="git",
                    requested_revision="main",
                    commit_id="old123",
                ),
            ),
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(return_value=(True, "first-pass")),
            ) as mock_upgrade,
            patch(
                "controlmesh.infra.updater._wait_for_install_change",
                new=AsyncMock(return_value=InstalledState(version="1.0.0", commit_id="old123")),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is False
        assert version == "1.0.0"
        assert "first-pass" in output
        assert "resolved_target_version=none" in output
        mock_upgrade.assert_called_once_with(target_version=None, force_reinstall=False)

    async def test_postcheck_requires_fresh_runtime_version_match_target(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_runtime_provenance",
                return_value=SimpleNamespace(matches_expected=True, reason=""),
            ),
            patch(
                "controlmesh.infra.updater._inspect_current_runtime",
                return_value=("1.0.0", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python"),
            ),
            patch(
                "controlmesh.infra.updater._inspect_runtime_after_upgrade",
                new=AsyncMock(
                    return_value=("2.0.1", "/venv/site-packages/controlmesh/__init__.py", "/tmp/cm-python")
                ),
            ),
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(return_value=(True, "first-pass")),
            ),
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(mode="uv_tool", source="pypi"),
            ),
            patch(
                "controlmesh.infra.updater._wait_for_install_change",
                new=AsyncMock(return_value=InstalledState(version="2.0.0")),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(
                current_version="1.0.0",
                target_version="2.0.0",
                requested_version="v2.0.0",
            )

        assert changed is False
        assert version == "1.0.0"
        assert "requested_version=2.0.0" in output
        assert "resolved_target_version=2.0.0" in output
        assert "did not match target_version=2.0.0" in output


class TestResolveUpgradeTarget:
    async def test_explicit_requested_version_is_normalized_and_frozen(self) -> None:
        requested, resolved = await resolve_upgrade_target(
            current_version="1.0.0",
            requested_version="v2.0.0",
            install_info=InstallInfo(mode="uv_tool", source="pypi"),
        )

        assert requested == "2.0.0"
        assert resolved == "2.0.0"

    async def test_no_requested_version_resolves_latest_once(self) -> None:
        info = VersionInfo(
            current="1.0.0",
            latest="2.0.0",
            update_available=True,
            summary="release",
            source="pypi",
        )
        with patch("controlmesh.infra.updater.check_latest_version", new=AsyncMock(return_value=info)):
            requested, resolved = await resolve_upgrade_target(
                current_version="1.0.0",
                requested_version=None,
                install_info=InstallInfo(mode="uv_tool", source="pypi"),
            )

        assert requested is None
        assert resolved == "2.0.0"

    async def test_dev_install_fast_forwards_and_refreshes_editable_install(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(
                    mode="dev",
                    source="dev",
                    local_path="/repo/controlmesh",
                ),
            ),
            patch(
                "controlmesh.infra.updater._resolve_source_repo_root",
                new=AsyncMock(return_value=(Path("/repo/controlmesh"), "repo-root")),
            ),
            patch(
                "controlmesh.infra.updater._read_source_state",
                new=AsyncMock(return_value=InstalledState(version="1.0.0", commit_id="old123")),
            ),
            patch(
                "controlmesh.infra.updater._git_output",
                new=AsyncMock(
                    side_effect=[
                        (True, "main"),
                        (True, ""),
                        (True, "fetch-ok"),
                        (True, "origin/main"),
                        (True, "0\t3"),
                        (True, "pull-ok"),
                    ]
                ),
            ),
            patch(
                "controlmesh.infra.updater._run_upgrade_command",
                new=AsyncMock(return_value=(True, "reinstall-ok")),
            ) as mock_run,
            patch(
                "controlmesh.infra.updater._wait_for_source_state_change",
                new=AsyncMock(return_value=InstalledState(version="1.0.0", commit_id="new456")),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is True
        assert version == "1.0.0"
        assert "pull-ok" in output
        assert "reinstall-ok" in output
        assert mock_run.call_args.kwargs["cwd"] == "/repo/controlmesh"

    async def test_dev_install_refuses_dirty_worktree(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(
                    mode="dev",
                    source="dev",
                    local_path="/repo/controlmesh",
                ),
            ),
            patch(
                "controlmesh.infra.updater._resolve_source_repo_root",
                new=AsyncMock(return_value=(Path("/repo/controlmesh"), "repo-root")),
            ),
            patch(
                "controlmesh.infra.updater._read_source_state",
                new=AsyncMock(return_value=InstalledState(version="1.0.0", commit_id="old123")),
            ),
            patch(
                "controlmesh.infra.updater._git_output",
                new=AsyncMock(
                    side_effect=[
                        (True, "main"),
                        (True, " M controlmesh/infra/updater.py\n?? notes.txt"),
                    ]
                ),
            ),
            patch(
                "controlmesh.infra.updater._run_upgrade_command",
                new=AsyncMock(return_value=(True, "should-not-run")),
            ) as mock_run,
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is False
        assert version == "1.0.0"
        assert "worktree has uncommitted or untracked changes" in output
        mock_run.assert_not_called()


class TestPerformUpgradeImpl:
    async def test_bootstraps_pip_with_ensurepip_when_missing(self) -> None:
        from controlmesh.infra.updater import _perform_upgrade_impl

        with (
            patch(
                "controlmesh.infra.updater.detect_install_info",
                return_value=InstallInfo(mode="pip", source="pypi"),
            ),
            patch("controlmesh.infra.updater.shutil.which", return_value=None),
            patch("controlmesh.infra.updater.sys.executable", "/tmp/cm-python"),
            patch(
                "controlmesh.infra.updater._run_upgrade_command",
                new=AsyncMock(
                    side_effect=[
                        (False, "/tmp/cm-python: No module named pip"),
                        (True, "ensurepip ok"),
                        (True, "retry ok"),
                    ]
                ),
            ) as mock_run,
        ):
            changed, output = await _perform_upgrade_impl(
                target_version="0.22.4",
                force_reinstall=False,
            )

        assert changed is True
        assert "ensurepip ok" in output
        assert "retry ok" in output
        assert mock_run.call_count == 3


class TestBuildUpgradeCommand:
    """Test source-aware upgrade command construction."""

    def test_pipx_github_install_uses_runpip_direct_url(self) -> None:
        cmd = _build_upgrade_command(
            mode="pipx",
            package_spec="controlmesh @ git+https://github.com/muqiao215/ControlMesh.git@v0.16.0",
            target_version="0.16.0",
            force_reinstall=True,
        )

        assert cmd == [
            "pipx",
            "runpip",
            "controlmesh",
            "install",
            "--upgrade",
            "--no-cache-dir",
            "--force-reinstall",
            "controlmesh @ git+https://github.com/muqiao215/ControlMesh.git@v0.16.0",
        ]

    def test_pip_install_prefers_uv_when_available(self) -> None:
        with (
            patch("controlmesh.infra.updater.shutil.which", return_value="/root/.local/bin/uv"),
            patch("controlmesh.infra.updater.sys.executable", "/tmp/cm-python"),
        ):
            cmd = _build_upgrade_command(
                mode="pip",
                package_spec="controlmesh==0.22.4",
                target_version="0.22.4",
                force_reinstall=False,
            )

        assert cmd == [
            "uv",
            "pip",
            "install",
            "--python",
            "/tmp/cm-python",
            "--no-cache",
            "--upgrade",
            "controlmesh==0.22.4",
        ]

    def test_pip_install_falls_back_to_python_m_pip_without_uv(self) -> None:
        with (
            patch("controlmesh.infra.updater.shutil.which", return_value=None),
            patch("controlmesh.infra.updater.sys.executable", "/tmp/cm-python"),
        ):
            cmd = _build_upgrade_command(
                mode="pip",
                package_spec="controlmesh==0.22.4",
                target_version="0.22.4",
                force_reinstall=True,
            )

        assert cmd == [
            "/tmp/cm-python",
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-cache-dir",
            "--force-reinstall",
            "controlmesh==0.22.4",
        ]

    def test_uv_tool_install_uses_force_reinstall_refresh(self) -> None:
        cmd = _build_upgrade_command(
            mode="uv_tool",
            package_spec="controlmesh==0.25.0",
            target_version="0.25.0",
            force_reinstall=True,
        )

        assert cmd == [
            "uv",
            "tool",
            "install",
            "--force-reinstall",
            "--refresh",
            "controlmesh==0.25.0",
        ]


class TestBuildPackageSpec:
    """Test source-aware package spec selection."""

    def test_github_main_preserves_requested_revision(self) -> None:
        spec = _build_package_spec(
            InstallInfo(
                mode="pipx",
                source="github",
                url="https://github.com/muqiao215/ControlMesh.git",
                vcs="git",
                requested_revision="main",
            ),
            target_version="0.16.0",
        )

        assert spec == "controlmesh @ git+https://github.com/muqiao215/ControlMesh.git@main"

    def test_non_github_direct_url_does_not_switch_to_vcs_spec(self) -> None:
        spec = _build_package_spec(
            InstallInfo(
                mode="pip",
                source="other",
                url="https://example.com/packages/controlmesh.whl",
            ),
            target_version="0.16.0",
        )

        assert spec == "controlmesh==0.16.0"


# ---------------------------------------------------------------------------
# UpdateObserver
# ---------------------------------------------------------------------------


class TestUpdateObserver:
    """Test background version check observer."""

    async def test_notifies_on_new_version(self) -> None:
        info = VersionInfo(current="1.0.0", latest="2.0.0", update_available=True, summary="New!")
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", return_value=info),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.1)
            await observer.stop()

        notify.assert_called_once_with(info)

    async def test_does_not_notify_when_up_to_date(self) -> None:
        info = VersionInfo(current="1.0.0", latest="1.0.0", update_available=False, summary="")
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", return_value=info),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.1)
            await observer.stop()

        notify.assert_not_called()

    async def test_deduplicates_same_version(self) -> None:
        info = VersionInfo(current="1.0.0", latest="2.0.0", update_available=True, summary="New!")
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", return_value=info),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            # Let multiple check cycles run
            await asyncio.sleep(0.15)
            await observer.stop()

        # Should only notify once for the same version
        notify.assert_called_once()

    async def test_handles_check_failure_gracefully(self) -> None:
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch(
                "controlmesh.infra.updater.check_latest_version",
                side_effect=RuntimeError("network"),
            ),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.1)
            await observer.stop()

        notify.assert_not_called()

    async def test_handles_none_from_check_latest_version(self) -> None:
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", return_value=None),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.1)
            await observer.stop()

        notify.assert_not_called()

    async def test_stop_without_start_is_safe(self) -> None:
        observer = UpdateObserver(notify=AsyncMock())
        await observer.stop()  # Should not raise

    async def test_notifies_again_for_newer_version(self) -> None:
        call_count = 0
        versions = [
            VersionInfo(current="1.0.0", latest="2.0.0", update_available=True, summary="v2"),
            VersionInfo(current="1.0.0", latest="3.0.0", update_available=True, summary="v3"),
        ]

        async def mock_check() -> VersionInfo:
            nonlocal call_count
            idx = min(call_count, len(versions) - 1)
            call_count += 1
            return versions[idx]

        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", side_effect=mock_check),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.15)
            await observer.stop()

        assert notify.call_count == 2


class TestEnsureUpdateObserverStarted:
    async def test_starts_when_enabled_for_main_agent(self) -> None:
        notify = AsyncMock()
        observer = ensure_update_observer_started(
            None,
            update_check=True,
            agent_name="main",
            notify=notify,
        )

        assert observer is not None
        assert isinstance(observer, UpdateObserver)
        assert observer._task is not None
        await observer.stop()

    def test_reuses_existing_observer(self) -> None:
        existing = UpdateObserver(notify=AsyncMock())
        observer = ensure_update_observer_started(
            existing,
            update_check=True,
            agent_name="main",
            notify=AsyncMock(),
        )

        assert observer is existing

    def test_skips_when_disabled(self) -> None:
        observer = ensure_update_observer_started(
            None,
            update_check=False,
            agent_name="main",
            notify=AsyncMock(),
        )

        assert observer is None

    def test_skips_for_non_main_agent(self) -> None:
        observer = ensure_update_observer_started(
            None,
            update_check=True,
            agent_name="worker",
            notify=AsyncMock(),
        )

        assert observer is None
